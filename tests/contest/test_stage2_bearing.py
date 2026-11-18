import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments/ablation'))
spec = importlib.util.spec_from_file_location('stage2_bearing', ROOT / 'experiments/ablation/stage2_bearing.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BearingAuditTest(unittest.TestCase):
    def test_only_bearings_exceeding_current_parent_are_reported(self):
        audit = {'gates': {'bearing_gate': False},
                 'parent_diagnostics': {'groups': {'a': {'rmse': 10.}, 'b': {'rmse': 20.}}},
                 'candidate_diagnostics': {'groups': {'a': {'rmse': 11.}, 'b': {'rmse': 19.}}}}
        self.assertEqual(module.violations(audit), [{'bearing': 'a', 'parent_rmse': 10.,
                                                     'candidate_rmse': 11., 'delta': 1.}])
        audit['gates']['bearing_gate'] = None
        self.assertEqual(module.violations(audit), [])


if __name__ == '__main__':
    unittest.main()
