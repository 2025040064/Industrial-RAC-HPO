import importlib.util
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments/ablation'))
spec = importlib.util.spec_from_file_location('stage2_stats', ROOT / 'experiments/ablation/stage2_stats.py')
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


class StageTwoStatisticsTest(unittest.TestCase):
    def test_three_seed_descriptives_use_sample_std_and_range(self):
        value = stats.descriptive([1, 2, 3])
        self.assertEqual(value, {'n': 3, 'mean': 2, 'sample_std': 1.0, 'median': 2, 'min': 1, 'max': 3})
        self.assertIsNone(stats.descriptive([2])['sample_std'])

    def test_real_observation_cost_penalty_can_invert_order(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as tmp:
            state = Path(tmp) / 'state'
            state.mkdir()
            records = [{'round': 1, 'robust_objective': .9, 'parent_objective': 1, 'training_seconds': 4},
                       {'round': 2, 'robust_objective': .91, 'parent_objective': 1, 'training_seconds': 1}]
            (state / 'rac-round.json').write_text(json.dumps({'archive': records}))
            row = {'state_path': 'state', 'audit': {'search_trace': {'method': 'transfer_tpe',
                    'transfer_cost_weight': .05, 'transfer_cost_median_seconds': 2.5, 'history_rounds': []},
                    'history_usage': {'transfer_used_rounds': [1, 2]}}}
            self.assertEqual(stats.cost_inversions(row, Path(tmp)), 1)

    def test_export_pairs_three_seeds_even_when_budget_stops_before_first_round(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as tmp:
            campaign = Path(tmp)
            sha = hashlib.sha256(b'initial').hexdigest()
            seeds = [101, 202, 303]
            (campaign / 'protocol.json').write_text(json.dumps({'search_seeds': seeds,
                'inputs': {task: {'initial_sha256': sha} for task in 'ABC'}}))
            schedule = []
            for task in 'ABC':
                for group in ('G0', 'G1', 'G2', 'G3'):
                    for seed in seeds:
                        schedule.append({'task': task, 'group': group, 'seed': seed})
                        run = campaign / 'runs' / f'{task}-{group}-{seed}'
                        run.mkdir(parents=True)
                        (run / 'initial.npz').write_bytes(b'initial')
                        metrics = {'macro_f1': .7, 'accuracy': .8} if task == 'A' else {'rmse': 5., 'mae': 4.}
                        subsets = {'FD001': {'samples': 2, 'rmse': 5., 'mae': 4.}} if task == 'C' else None
                        (run / 'baseline.json').write_text(json.dumps({'metrics': metrics, 'subsets': subsets,
                                                                     'cpu_at_measurement': .5}))
                        summary = {'rounds_completed': 0, 'budget_overrun_seconds': 0, 'worker_cpu_seconds': 1.,
                                   'phase_cpu_seconds': {'preload': .5, 'search': 0., 'train': 0., 'validation': .2,
                                                         'sdk_host': 0., 'other': .3},
                                   'initial_sha256': sha, 'final_sha256': sha, 'final_metrics': metrics,
                                   'initial_metrics': metrics, 'status': 'budget_exhausted', 'budget_seconds': 2,
                                   'user_cpu_seconds': .9, 'system_cpu_seconds': .1, 'partial_round_attempts': 0,
                                   'partial_rounds': [], 'accepted': 0, 'rejected': 0, 'failed_attempts': 0,
                                   'surrogate_attempts': 0, 'surrogate_used': 0, 'transfer_tpe_rounds': 0,
                                   'peak_rss_bytes': 1, 'final_subsets': subsets}
                        (run / 'summary.json').write_text(json.dumps(summary))
            (campaign / 'paired-schedule.json').write_text(json.dumps({'runs': schedule}))
            (campaign / 'paired-result.json').write_text(json.dumps({'failures': [], 'controller_cpu_seconds': 1.}))
            output = campaign / 'statistics'
            subprocess.run([sys.executable, str(ROOT / 'experiments/ablation/stage2_stats.py'),
                            str(campaign), '--output', str(output)], check=True, capture_output=True)
            report = json.loads((output / 'analysis.json').read_text())
            self.assertEqual(len(report['runs']), 36)
            group = next(row for row in report['paired_statistics'] if row['task'] == 'A'
                         and row['comparison'] == 'G1-G0' and row['metric'] == 'macro_f1')
            self.assertEqual(group['n'], 3)
            self.assertEqual(group['sample_std'], 0)
            self.assertTrue((output / 'subset-statistics.csv').exists())
            (campaign / 'engine-lock.json').write_text(json.dumps({'source_sha256': {
                'experiments/ablation/hard_budget.py': 'test-only'}}))
            report_path = campaign / 'report.md'
            subprocess.run([sys.executable, str(ROOT / 'experiments/ablation/stage2_report.py'),
                            str(campaign), str(output), '--output', str(report_path)],
                           check=True, capture_output=True)
            self.assertIn('101 | 202 | 303', report_path.read_text())


if __name__ == '__main__':
    unittest.main()
