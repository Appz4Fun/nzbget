"""Bind workflow checkout pins to independently queried upstream repositories."""
import json
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent
WORKFLOW = HERE.parents[2] / '.github/workflows/bench_pr_closed.yml'


class ActionPinTests(unittest.TestCase):
    def test_checkout_pin_belongs_to_checkout_not_artifact_download(self):
        # Labeled upstream Git-ref responses are test data, independent of the
        # workflow. This catches a valid hex revision copied from another action.
        resolutions = json.loads((HERE / 'fixtures/action-resolution.json').read_text())['resolutions']
        owners = {row['sha']: row['repository'] for row in resolutions}
        checkouts = re.findall(r'uses:\s+actions/checkout@([^\s#]+)', WORKFLOW.read_text())
        self.assertTrue(checkouts, 'archive workflow has no reviewed controller checkout')
        for revision in checkouts:
            self.assertEqual(owners.get(revision), 'actions/checkout',
                             'checkout revision is not the independently resolved upstream checkout action')


if __name__ == '__main__':
    unittest.main()
