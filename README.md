# offline-claim-audit

Version 0.1.0. A standard-library static auditor for Python projects. MIT licensed.
It compares documentation statements about connectivity with source-level network evidence.
It reads text and parses ASTs; it never imports or executes target code and never reads `.env` contents.

## Usage

```sh
python3 -m pip install .
python3 -m offline_claim_audit /path/to/project
 offline-claim-audit /path/to/project --json
python3 -m offline_claim_audit . --verbose
python3 -m unittest discover -s tests -v
python3 -m build
```

Exit status is 0 for no findings, 2 for findings, and 1 for usage or inspection errors
(including invalid syntax or unreadable UTF-8 files). `--version` prints the version.
`--ignore GLOB` is repeatable and matches project-relative paths using fnmatch;
matching directories prune their descendants. `--fail-on HIGH` prints MEDIUM findings
but returns 0 for those alone. `--fail-on MEDIUM` and the default fail on either severity.
The verdict reflects all findings regardless of the exit threshold.

## Documentation inspection

Only root README.md and Markdown files below docs/ are inspected. Backtick and tilde
fenced blocks are excluded; inline code is prose. Sentences split on punctuation
period, exclamation, question mark, and newline. Matching lowercases text, expands
n't to “ not”, replaces hyphens with spaces, and collapses whitespace. Exact phrases
use word boundaries and longest-first matching. Bare connectivity nouns do not count.
One sentence belongs to at most one family. Offline-family phrases are removed before
checking remaining no/not/never/without tokens; a remaining token suppresses the match.
Each project has at most one claim and one finding per family.

The complete recognized phrases are confined to this fenced block:

```text
OFFLINE
works without an internet connection
does not require an internet connection
does not need an internet connection
no internet connection required
no internet connection is required
requires no internet access
requires no internet connection
no network access required
works without network access
works without internet access
works offline
fully offline
runs offline
works without internet
no internet required
works with no internet

ONLINE
must be connected to the internet
requires an internet connection
requires internet access
requires network access
requires online access
needs an internet connection
needs internet access
internet connection required
internet access required
```

## Source inspection and limits

Production evidence comes from .py files outside tests/, fixtures/, docs/, examples/,
and outside test_*.py and *_test.py filenames. Test and fixture evidence is reported
separately. Symlink files and directories are skipped. Generated/environment directories
.git/, .venv/, venv/, __pycache__/, dist/, and build/ are skipped.

Imports of requests, httpx, urllib (including urllib.request), urllib3, http.client,
socket, aiohttp, websockets, ftplib, smtplib, and telnetlib count, including dotted
submodules and from-imports. Imported aliases are followed. Attribute calls rooted
in those names count. Calls to attributes urlopen, create_connection, HTTPConnection,
and HTTPSConnection on any receiver also count: this is an intentional
over-approximation. Dead code and unused imports still count. Bare calls to urlopen,
get, post, request, and create_connection count only when imported from a listed
module; function/class definitions with the same local name suppress that call
(the import itself remains evidence). This is static evidence, not proof that every
execution contacts a server; dynamic indirection and dependency behavior may be missed.

Ordinary imports such as os/sys/json/pathlib, local open() calls, comments, strings,
and printing/logging URL strings are not evidence. Subprocess invocations, including
curl/wget, are excluded because AST inspection cannot establish their behavior.

An offline-family claim with production evidence is HIGH. An online-family claim
without production evidence is HIGH. A project with no production source yields
HIGH and the evidence marker `no-source` for either family. When production source
exists and network evidence appears only in tests/fixtures, either family receives
MEDIUM. With no recognized claim there are no findings.

Rule identifiers:

```text
documented-offline-claim-false
documented-online-claim-false
documented-offline-claim-false-test-only
documented-online-claim-false-test-only
```

## Output

Plain output includes each finding and a PASS/FAIL line. Verbose output adds each
claim sentence and evidence-bearing file. JSON has path, verdict, claims, evidence,
and findings; claims contain family/phrases/files, evidence contains file/items/test_only,
and findings contain rule/severity/family/evidence. Finding evidence contains the relevant
file evidence objects, or the no-source marker. Verbose JSON additionally includes
claim_sentences. Files and phrases are deterministic and project-relative, apart from
an absolute project path.

## Development

Use Python 3.9 or later. Runtime dependencies: none. Packaging uses setuptools;
build verification uses the build frontend. Install the project before module execution
from a source checkout. Tests add src/ to their import path.
