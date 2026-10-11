"""Run the workflow's real archive shell with controlled Bencher responses."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

WORKFLOW = Path(__file__).resolve().parents[3] / '.github/workflows/bench_pr_closed.yml'


def archive_shell():
    # Extract the last YAML literal block; execute it, never assert source text.
    blocks = WORKFLOW.read_text().split('        run: |\n')
    return '\n'.join(line[10:] if line.startswith('          ') else line
                     for line in blocks[-1].splitlines())


class ArchiveTests(unittest.TestCase):
    def invoke(self, rows, failure='', pr_number='17', guard_ready=True, guard_fails=False):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            executable = folder / 'bencher'
            executable.write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')
if os.environ.get('FAILURE') and (os.environ['FAILURE'] != 'archive' or sys.argv[1] == 'archive'):
    print('credential-canary ' + os.environ['FAILURE'], file=sys.stderr)
    sys.exit(1)
if sys.argv[1:3] == ['branch', 'list']: print(os.environ['ROWS'])
''')
            executable.chmod(0o755)
            scripts = folder / 'scripts/bench'
            scripts.mkdir(parents=True)
            (scripts / 'publish.py').write_text('''import os, sys
from pathlib import Path
if os.environ['GUARD_FAILS'] == '1':
    print('credential-canary invalid identity', file=sys.stderr)
    sys.exit(2)
Path(sys.argv[sys.argv.index('--github-output') + 1]).write_text(
    'ready=' + os.environ['GUARD_READY'] + '\\nactor=xbmc4lyfe\\n')
''')
            calls = folder / 'calls'
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ['PATH'],
                       CALLS=str(calls), ROWS=rows, FAILURE=failure,
                       BENCHER_PROJECT='test-project', BENCHER_KEY='credential-canary',
                       BENCHER_HOST_URL='https://bencher.example', PR_NUMBER=pr_number, GITHUB_REPOSITORY='Appz4Fun/nzbget',
                       BENCH_GITHUB_TOKEN='github-token-canary',
                       GUARD_READY=str(guard_ready).lower(), GUARD_FAILS=str(int(guard_fails)))
            result = subprocess.run(['bash', '-c', archive_shell()], env=env,
                                    capture_output=True, text=True, cwd=folder)
            invocations = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            return result, invocations

    def test_archive_uses_pr_identity_without_credentials_in_argv(self):
        result, calls = self.invoke('[{"name":"pr-17"}]')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:5], ['branch', 'list', 'test-project', '--name', 'pr-17'])
        self.assertEqual(calls[1][:5], ['archive', '--project', 'test-project', '--branch', 'pr-17'])
        self.assertNotIn('credential-canary', json.dumps(calls) + result.stdout + result.stderr)

    def test_no_active_branch_never_performs_write(self):
        result, calls = self.invoke('[]')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertIn('No active Bencher branch', result.stdout)

    def test_lookup_failure_is_not_treated_as_missing_history(self):
        result, calls = self.invoke('[]', 'network-failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('credential-canary', result.stdout + result.stderr)

    def test_reopened_pr_does_not_archive_existing_branch(self):
        result, calls = self.invoke('[{"name":"pr-17"}]', guard_ready=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertIn('reopened', result.stdout)

    def test_current_identity_or_pr_guard_failure_never_writes(self):
        result, calls = self.invoke('[{"name":"pr-17"}]', guard_fails=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('credential-canary', result.stdout + result.stderr)

    def test_archive_failure_preserves_failed_status_without_credential_echo(self):
        result, calls = self.invoke('[{"name":"pr-17"}]', 'archive')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)
        self.assertIn('lifecycle remains unresolved', result.stdout)
        self.assertNotIn('credential-canary', result.stdout + result.stderr)

    def test_invalid_pr_number_never_reaches_bencher(self):
        result, calls = self.invoke('[]', pr_number='17; echo injected')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_invalid_or_ambiguous_lookup_never_performs_write(self):
        for rows in ('{}', 'not-json', '[{"name":"pr-18"}]', '[{"name":"pr-17"},{"name":"pr-17"}]'):
            with self.subTest(rows=rows):
                result, calls = self.invoke(rows)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
