import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from offline_claim_audit.audit import OFFLINE, ONLINE, audit, claim_sentences, network_evidence
from offline_claim_audit.cli import main


class AuditTests(unittest.TestCase):
    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_json_shape(self):
        code, output, _ = self.cli(str(ROOT/'tests/fixtures/bad/offline'), '--json')
        data = json.loads(output)
        self.assertEqual(code, 2)
        self.assertEqual(set(data), {'path', 'verdict', 'claims', 'evidence', 'findings'})
        self.assertEqual(data['verdict'], 'fail')
        self.assertEqual(data['findings'][0]['rule'], 'documented-offline-claim-false')

    def test_threshold_offline(self):
        self.assertEqual(self.cli(str(ROOT/'tests/fixtures/testonly/offline'), '--fail-on', 'HIGH')[0], 0)

    def test_threshold_online(self):
        self.assertEqual(self.cli(str(ROOT/'tests/fixtures/testonly/online'), '--fail-on', 'HIGH')[0], 0)

    def test_verbose(self):
        _, output, _ = self.cli(str(ROOT/'tests/fixtures/bad/offline'), '--verbose')
        self.assertIn('claim offline README.md:', output)
        self.assertIn('evidence app.py', output)

    def test_bad_path(self):
        self.assertEqual(self.cli(str(ROOT/'missing'))[0], 1)

    def test_bad_flag(self):
        with self.assertRaises(SystemExit) as error:
            self.cli('--unknown')
        self.assertEqual(error.exception.code, 1)

    def test_module_version(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT/'src'))
        run = subprocess.run([sys.executable, '-m', 'offline_claim_audit', '--version'], env=env, capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout.strip()), (0, '0.1.0'))

    def test_ignore(self):
        result = audit(ROOT/'tests/fixtures/bad/offline', ['README*'])
        self.assertEqual(result['claims'], [])

    def test_self(self):
        result = audit(ROOT)
        self.assertEqual((result['verdict'], result['claims']), ('pass', []))

    def test_docs_symlinks_and_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'README.md').write_text('works offline')
            (root/'app.py').write_text('print(1)')
            for directory in ('docs', 'examples'):
                (root/directory).mkdir()
                (root/directory/'net.py').write_text('import requests')
            (root/'linked.py').symlink_to(root/'examples/net.py')
            (root/'docs/claim.md').write_text('requires internet access')
            (root/'docs/link.md').symlink_to(root/'README.md')
            result = audit(root)
            self.assertEqual(len(result['claims']), 2)
            self.assertEqual(result['evidence'], [])
            self.assertEqual(len(result['findings']), 1)
            self.assertEqual(audit(root, ['docs/*'])['findings'], [])

    def test_negation_and_normalization(self):
        self.assertEqual(claim_sentences('It never works offline.'), [])
        self.assertEqual(claim_sentences("It doesn't require an internet connection.")[0]['family'], 'offline')
        self.assertEqual(claim_sentences('WORKS-OFFLINE!')[0]['family'], 'offline')
        self.assertEqual(claim_sentences('offline online internet network'), [])
        self.assertEqual(claim_sentences('works offlineness'), [])

    def test_fences(self):
        self.assertEqual(claim_sentences('~~~\nworks offline\n~~~'), [])
        self.assertEqual(claim_sentences('```\nworks offline'), [])
        self.assertEqual(len(claim_sentences('`works offline`')), 1)

    def test_family_overlap(self):
        claims = claim_sentences('no internet connection required')
        self.assertEqual([c['family'] for c in claims], ['offline'])
        self.assertEqual(len(claim_sentences('works offline and requires internet access')), 1)


# Each phrase is an independent regression case, so additions cannot silently go untested.
def phrase_test(phrase, family):
    def test(self):
        result = claim_sentences(phrase)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['family'], family)
        self.assertIn(phrase, result[0]['phrases'])
    return test
for family, phrases in [('offline', OFFLINE), ('online', ONLINE)]:
    for index, phrase in enumerate(phrases):
        setattr(AuditTests, 'test_phrase_{}_{}'.format(family, index), phrase_test(phrase, family))


CASES = [
 ('requests.get("x")', True),
 ('import requests as r\nr.get("x")', True),
 ('import httpx\nhttpx.post("x")', True),
 ('import urllib.request\nurllib.request.urlopen("x")', True),
 ('from urllib.request import urlopen as fetch\nfetch("x")', True),
 ('import http.client\nhttp.client.HTTPConnection("x")', True),
 ('import socket\nsocket.create_connection(("x", 80))', True),
 ('import aiohttp\naiohttp.ClientSession()', True),
 ('import websockets, ftplib, smtplib, telnetlib, urllib3', True),
 ('client.HTTPSConnection("x")', True),
 ('client.urlopen("x")', True),
 ('get("x")\npost("x")\nrequest("x")', False),
 ('import os, sys, json, pathlib\nopen("x")', False),
 ('# requests.get("x")\nprint("https://example.invalid")', False),
 ('def urlopen(x): return x\nurlopen("x")', False),
 ('from requests import get as fetch\ndef fetch(x): return x\nfetch("x")', True),
]
def evidence_test(source, expected):
    def test(self):
        items = network_evidence(source)
        self.assertEqual(bool(items), expected)
        if 'def fetch' in source:
            self.assertFalse(any('call fetch' in item for item in items))
    return test
for index, (source, expected) in enumerate(CASES):
    setattr(AuditTests, 'test_evidence_{}'.format(index), evidence_test(source, expected))

FIXTURES = {
 'good/offline': None, 'good/online': None,
 'bad/offline': ('offline', 'HIGH'), 'bad/online': ('online', 'HIGH'),
 'testonly/offline': ('offline', 'MEDIUM'), 'testonly/online': ('online', 'MEDIUM'),
 'noclaim': None, 'nosource/offline': ('offline', 'HIGH'), 'negation': None,
 'inline-code': ('offline', 'HIGH'), 'fenced-code': None, 'alias': ('offline', 'HIGH'),
 'shadowed': None, 'subprocess': None,
}
def fixture_test(name, expected):
    def test(self):
        path = ROOT/'tests/fixtures'/name
        code, output, _ = self.cli(str(path), '--json')
        result = json.loads(output)
        self.assertEqual(code, 2 if expected else 0)
        self.assertEqual(result['verdict'], 'fail' if expected else 'pass')
        self.assertEqual(len(result['findings']), 1 if expected else 0)
        if expected:
            family, severity = expected
            finding = result['findings'][0]
            suffix = '-test-only' if severity == 'MEDIUM' else ''
            self.assertEqual(finding['rule'], 'documented-' + family + '-claim-false' + suffix)
            self.assertEqual(finding['severity'], severity)
            if name.startswith('nosource'):
                self.assertEqual(finding['evidence'], ['no-source'])
    return test
for name, expected in FIXTURES.items():
    setattr(AuditTests, 'test_fixture_' + name.replace('/', '_').replace('-', '_'), fixture_test(name, expected))
