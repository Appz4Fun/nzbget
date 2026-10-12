#!/usr/bin/env python3
"""Report configuration readiness without printing values or performing writes.

This check never establishes token identity, artifact trust, runner availability,
benchmark validity, or migration qualification. Trusted publishers must verify
GitHub /user as xbmc4lyfe immediately before any authenticated write.

Modes: measure needs BENCH_TESTBED without credentials; publish needs testbed,
project and both publication credentials; archive needs only project/credentials.
BENCHER_HOST_URL is optional (Bencher Cloud default) and must be HTTPS when set.
Workflow mappings preserve BENCHER_PROJECT, BENCHER_HOST, BENCHER_API_KEY and
BENCHMARK_GITHUB_TOKEN configuration names while using the shared env aliases.
Missing configuration exits 0 with ready=false; invalid configuration exits 2.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

CREDENTIAL_NAMES = ('BENCHER_KEY', 'BENCHER_API_KEY', 'BENCHER_API_TOKEN',
                    'BENCH_GITHUB_TOKEN', 'GITHUB_TOKEN', 'GH_TOKEN',
                    'BENCHMARK_GITHUB_TOKEN', 'RELEASE_TOKEN')
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}\Z')


def inspect_config(mode, env):
    """Return a value-free report; readiness is explicitly not authentication."""
    missing, diagnostics, invalid = [], [], []
    required = [('BENCH_TESTBED', 'BENCH_TESTBED')] if mode == 'measure' else [
        ('BENCHER_PROJECT', 'BENCHER_PROJECT'),
        ('BENCHER_KEY', 'BENCHER_API_KEY'),
        ('BENCH_GITHUB_TOKEN', 'BENCHMARK_GITHUB_TOKEN'),
    ]
    if mode == 'publish':
        required.append(('BENCH_TESTBED', 'BENCH_TESTBED'))
    for variable, name in required:
        if not env.get(variable, '').strip():
            missing.append(name)
            diagnostics.append(f'{name} is unavailable; this operation remains disabled.')

    if mode == 'measure':
        if any(env.get(name) for name in CREDENTIAL_NAMES):
            invalid.append('Measurement environment contains publication credentials; refuse measurement.')
    for name in ('BENCHER_PROJECT', 'BENCH_TESTBED'):
        value = env.get(name, '')
        if value.strip() and not IDENTIFIER.fullmatch(value):
            invalid.append(f'{name} must be a bounded identifier without whitespace or control characters.')
    host = env.get('BENCHER_HOST_URL', '')
    if host:
        try:
            parsed = urlsplit(host)
            port = parsed.port
            valid = (parsed.scheme == 'https' and bool(parsed.hostname) and
                     parsed.username is None and parsed.password is None and
                     not parsed.query and not parsed.fragment and
                     (port is None or 1 <= port <= 65535) and
                     not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in host))
        except ValueError:
            valid = False
        if not valid:
            invalid.append('BENCHER_HOST must be an HTTPS URL without credentials, query, fragment or control characters.')
    diagnostics.extend(invalid)
    status = 'invalid' if invalid else 'unavailable' if missing else 'ready'
    return {'schema_version': 1, 'mode': mode, 'status': status, 'ready': status == 'ready',
            'missing': missing, 'diagnostics': diagnostics,
            'requires_identity_verification': mode != 'measure'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=('measure', 'publish', 'archive'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args(argv)
    report = inspect_config(args.mode, os.environ)
    serialized = json.dumps(report, sort_keys=True) + '\n'
    try:
        if args.output:
            args.output.write_text(serialized, encoding='utf-8')
        if args.github_output:
            with args.github_output.open('a', encoding='utf-8') as output:
                output.write(f"ready={str(report['ready']).lower()}\nstatus={report['status']}\n")
    except OSError:
        print('Preflight output could not be written.', file=sys.stderr)
        return 2
    sys.stdout.write(serialized)
    for diagnostic in report['diagnostics']:
        print(diagnostic, file=sys.stderr)
    return 2 if report['status'] == 'invalid' else 0


if __name__ == '__main__':
    sys.exit(main())
