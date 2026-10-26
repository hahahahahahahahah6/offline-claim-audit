"""Command-line interface."""
import argparse
import json
import sys
from . import __version__
from .audit import audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, '{}: error: {}\n'.format(self.prog, message))


def main(argv=None):
    parser = Parser(description='Compare documentation claims with static network evidence.')
    parser.add_argument('path', nargs='?', default='.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[], metavar='GLOB')
    parser.add_argument('--fail-on', choices=['HIGH', 'MEDIUM'])
    args = parser.parse_args(argv)
    try:
        result = audit(args.path, args.ignore, args.verbose)
    except (OSError, ValueError, SyntaxError) as error:
        print('error: {}'.format(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for finding in result['findings']:
            print('{} {} {}'.format(finding['severity'], finding['rule'], json.dumps(finding['evidence'])))
        if args.verbose:
            for claim in result['claim_sentences']:
                print('claim {} {}: {}'.format(claim['family'], claim['file'], claim['sentence']))
            for item in result['evidence']:
                print('evidence {} test_only={}: {}'.format(item['file'], item['test_only'], '; '.join(item['items'])))
        print(result['verdict'].upper())
    return 2 if any(args.fail_on != 'HIGH' or f['severity'] == 'HIGH' for f in result['findings']) else 0
