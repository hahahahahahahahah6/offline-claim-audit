"""Read-only documentation and AST inspection; target code is never imported."""
import ast
import fnmatch
import os
from pathlib import Path
import re

OFFLINE = (
    'works without an internet connection',
    'does not require an internet connection',
    'does not need an internet connection',
    'no internet connection required',
    'no internet connection is required',
    'requires no internet access',
    'requires no internet connection',
    'no network access required',
    'works without network access',
    'works without internet access',
    'works offline', 'fully offline', 'runs offline',
    'works without internet', 'no internet required', 'works with no internet',
)
ONLINE = (
    'must be connected to the internet', 'requires an internet connection',
    'requires internet access', 'requires network access', 'requires online access',
    'needs an internet connection', 'needs internet access',
    'internet connection required', 'internet access required',
)
NETWORK = {'requests', 'httpx', 'urllib', 'urllib3', 'http.client', 'socket',
           'aiohttp', 'websockets', 'ftplib', 'smtplib', 'telnetlib'}
SPECIAL = {'urlopen', 'create_connection', 'HTTPConnection', 'HTTPSConnection'}
BARE = {'urlopen', 'get', 'post', 'request', 'create_connection'}


def normalize(text):
    return re.sub(r'\s+', ' ', text.lower().replace("n't", ' not').replace('-', ' ')).strip()


def prose(text):
    """Remove CommonMark-style backtick/tilde fences, including unclosed ones."""
    fence = None
    lines = []
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            lines.append('')
        elif match and (match[1][0] != '`' or '`' not in match[2]):
            fence = match[1]
            lines.append('')
        else:
            lines.append(line)
    return '\n'.join(lines)


def claim_sentences(text):
    result = []
    for sentence in re.split(r'[.!?\n]+', prose(text)):
        remaining = normalize(sentence)
        for family, phrases in (('offline', OFFLINE), ('online', ONLINE)):
            found = []
            for phrase in sorted(phrases, key=len, reverse=True):
                pattern = r'(?<!\w)' + re.escape(phrase) + r'(?!\w)'
                if re.search(pattern, remaining):
                    found.append(phrase)
                    remaining = re.sub(pattern, ' ', remaining)
            if found:
                if family != 'offline' or not re.search(r'\b(no|not|never|without)\b', remaining):
                    result.append({'family': family, 'phrases': found, 'sentence': sentence.strip()})
                # A matched sentence belongs to at most one family, even if suppressed.
                break
    return result


def is_network(name):
    return any(name == module or name.startswith(module + '.') for module in NETWORK)


def network_evidence(source):
    tree = ast.parse(source)
    aliases = {module.split(".")[0] for module in NETWORK}
    imported = set()
    items = []
    shadowed = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    def add(node, label):
        items.append((node.lineno, label))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                if is_network(name.name):
                    aliases.add(name.asname or name.name.split('.')[0])
                    add(node, 'import ' + name.name)
        elif isinstance(node, ast.ImportFrom) and not node.level and is_network(node.module or ''):
            for name in node.names:
                local = name.asname or name.name
                aliases.add(local)
                if name.name in BARE:
                    imported.add(local)
                add(node, 'from ' + node.module + ' import ' + name.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            root = func
            while isinstance(root, ast.Attribute):
                root = root.value
            if func.attr in SPECIAL or (isinstance(root, ast.Name) and root.id in aliases):
                add(node, 'call ' + ast.unparse(func))
        elif isinstance(func, ast.Name) and func.id in imported and func.id not in shadowed:
            add(node, 'call ' + func.id)
    return ['line {}: {}'.format(line, label) for line, label in sorted(set(items))]


def audit(path, ignore=(), verbose=False):
    root = Path(path).resolve()
    if not root.is_dir():
        raise ValueError('project path must be a readable directory')
    records = []
    evidence = []
    production = 0
    def walk_error(error):
        raise error
    for directory, dirs, files in os.walk(root, onerror=walk_error, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if d not in {'.git', '.venv', 'venv', '__pycache__', 'dist', 'build'}
                         and not (base / d).is_symlink()
                         and not any(fnmatch.fnmatch((base / d).relative_to(root).as_posix(), g) for g in ignore))
        for name in sorted(files):
            file = base / name
            rel = file.relative_to(root)
            label = rel.as_posix()
            if file.is_symlink() or any(fnmatch.fnmatch(label, g) for g in ignore):
                continue
            doc = label == 'README.md' or (rel.parts[0] == 'docs' and file.suffix == '.md')
            source = file.suffix == '.py' and not any(part in {'docs', 'examples'} for part in rel.parts[:-1])
            if not (doc or source):
                continue
            text = file.read_text(encoding='utf-8')
            if doc:
                for record in claim_sentences(text):
                    records.append(dict(record, file=label))
            if source:
                test = any(part in {'tests', 'fixtures'} for part in rel.parts[:-1]) or name.startswith('test_') or name.endswith('_test.py')
                if not test:
                    production += 1
                items = network_evidence(text)
                if items:
                    evidence.append({'file': label, 'items': items, 'test_only': test})
    claims = []
    findings = []
    prod = [e for e in evidence if not e['test_only']]
    test = [e for e in evidence if e['test_only']]
    for family in ('offline', 'online'):
        matches = [c for c in records if c['family'] == family]
        if not matches:
            continue
        claims.append({'family': family, 'phrases': sorted({p for c in matches for p in c['phrases']}),
                       'files': sorted({c['file'] for c in matches})})
        severity = None
        proof = []
        if not production:
            severity, proof = 'HIGH', ['no-source']
        elif not prod and test:
            severity, proof = 'MEDIUM', test
        elif (family == 'offline' and prod) or (family == 'online' and not prod):
            severity, proof = 'HIGH', prod
        if severity:
            rule = 'documented-' + family + '-claim-false'
            if severity == 'MEDIUM':
                rule += '-test-only'
            findings.append({'rule': rule, 'severity': severity, 'family': family, 'evidence': proof})
    result = {'path': str(root), 'verdict': 'fail' if findings else 'pass',
              'claims': claims, 'evidence': evidence, 'findings': findings}
    if verbose:
        result['claim_sentences'] = records
    return result
