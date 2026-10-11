#!/usr/bin/env python3
"""Missing or duplicated benchmark samples must fail closed, including under -O."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).parent

class EvidenceIntegrity(unittest.TestCase):
    def setUp(self):
        self.rows = []
        for mode in ('quoted', 'unquoted'):
            for files, parts in ((1, 1), (30, 10), (100, 100)):
                self.add_case(mode, files, parts)
            self.add_case(mode + '-par', 1, 1)

    def add_case(self, mode, files, parts):
        for round_ in range(15):
            for language, ns in (('cpp', 1000), ('rust', 900)):
                self.rows.append(f'{mode},{files},{parts},{round_},{language},{ns},123\n')

    def run_report(self, rows):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp)/'samples.csv'
            path.write_text(''.join(rows))
            return subprocess.run([sys.executable, '-O', str(HERE/'summarize.py'), str(path)],
                                  capture_output=True, text=True)

    def test_complete_data_reports_all_eight_cases(self):
        result = self.run_report(self.rows)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 10)
        self.assertIn('-10.0%', result.stdout)

    def test_empty_or_missing_large_case_is_rejected(self):
        for rows in ([], [row for row in self.rows if not row.startswith('quoted,100,100,')]):
            result = self.run_report(rows)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('missing benchmark cases', result.stderr)
            self.assertEqual(result.stdout, '')

    def test_duplicate_missing_pair_and_missing_round_are_rejected(self):
        for rows in (self.rows + self.rows[:1], self.rows[1:],
                     [row for row in self.rows if not row.startswith('quoted,1,1,0,')]):
            result = self.run_report(rows)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_changed_output_and_nonfinite_timing_are_rejected(self):
        for replace in ('quoted,1,1,0,cpp,1000,999\n', 'quoted,1,1,0,cpp,nan,123\n'):
            result = self.run_report([replace]+self.rows[1:])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

if __name__ == '__main__':
    unittest.main()
