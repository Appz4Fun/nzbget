"""Configuration readiness, redaction and fail-closed measurement contracts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'preflight.py'


class PreflightTests(unittest.TestCase):
    def invoke(self, mode, env=None, *args):
        clean = {'PATH': os.environ.get('PATH', '')}
        clean.update(env or {})
        return subprocess.run([sys.executable, str(SCRIPT), '--mode', mode, *args],
                              env=clean, capture_output=True, text=True)

    def test_missing_archive_config_is_visible_and_inert(self):
        result = self.invoke('archive')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'unavailable')
        self.assertFalse(report['ready'])
        self.assertEqual(report['missing'], ['BENCHER_PROJECT', 'BENCHER_API_KEY', 'BENCHMARK_GITHUB_TOKEN'])
        self.assertTrue(report['requires_identity_verification'])
        self.assertIn('BENCHER_API_KEY', result.stderr)

    def test_ready_archive_is_not_an_identity_assertion(self):
        result = self.invoke('archive', {'BENCHER_PROJECT': 'test-project', 'BENCHER_KEY': 'secret-canary',
                                        'BENCH_GITHUB_TOKEN': 'token-canary', 'BENCH_GITHUB_ACTOR': 'attacker'})
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['ready'])
        self.assertTrue(report['requires_identity_verification'])
        self.assertNotIn('secret-canary', result.stdout + result.stderr)
        self.assertNotIn('token-canary', result.stdout + result.stderr)
        self.assertNotIn('attacker', result.stdout + result.stderr)

    def test_publish_requires_testbed_but_archive_does_not(self):
        env = {'BENCHER_PROJECT': 'test-project', 'BENCHER_KEY': 'canary', 'BENCH_GITHUB_TOKEN': 'canary'}
        report = json.loads(self.invoke('publish', env).stdout)
        self.assertFalse(report['ready'])
        self.assertEqual(report['missing'], ['BENCH_TESTBED'])
        env['BENCH_TESTBED'] = 'existing-i7-worker'
        self.assertTrue(json.loads(self.invoke('publish', env).stdout)['ready'])

    def test_measure_needs_no_publication_configuration(self):
        result = self.invoke('measure', {'BENCH_TESTBED': 'existing-i7-worker'})
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['ready'])
        self.assertFalse(report['requires_identity_verification'])

    def test_measure_rejects_every_known_credential_alias(self):
        for name in ('BENCHER_KEY', 'BENCHER_API_KEY', 'BENCHER_API_TOKEN', 'BENCH_GITHUB_TOKEN',
                     'GITHUB_TOKEN', 'GH_TOKEN', 'BENCHMARK_GITHUB_TOKEN', 'RELEASE_TOKEN'):
            with self.subTest(name=name):
                result = self.invoke('measure', {'BENCH_TESTBED': 'existing-i7-worker', name: 'credential-canary'})
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)['status'], 'invalid')
                self.assertNotIn('credential-canary', result.stdout + result.stderr)

    def test_invalid_host_and_project_are_never_echoed(self):
        valid = {'BENCHER_PROJECT': 'project', 'BENCHER_KEY': 'canary', 'BENCH_GITHUB_TOKEN': 'canary'}
        for host in ('http://host.example', 'https://user:pass@host.example', 'https://host.example?key=canary',
                     'https://host.example/#canary', 'https://host.example/\n::error::canary', 'https://host.example:invalid'):
            with self.subTest(host=host):
                result = self.invoke('archive', dict(valid, BENCHER_HOST_URL=host))
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertFalse(json.loads(result.stdout)['ready'])
                self.assertNotIn('canary', result.stdout + result.stderr)
        result = self.invoke('archive', dict(valid, BENCHER_PROJECT='project\n::error::canary'))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('canary', result.stdout + result.stderr)

    def test_output_files_contain_only_fixed_safe_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'config.json'
            github = Path(directory) / 'github-output'
            github.write_text('previous=value\n')
            result = self.invoke('archive', {}, '--output', str(output), '--github-output', str(github))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text()), json.loads(result.stdout))
            self.assertEqual(github.read_text(), 'previous=value\nready=false\nstatus=unavailable\n')


if __name__ == '__main__':
    unittest.main()
