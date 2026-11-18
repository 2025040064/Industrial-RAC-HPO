import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


path = Path(__file__).resolve().parents[2] / 'experiments/ablation/analyze.py'
spec = importlib.util.spec_from_file_location('ablation_analysis', path)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)
runner_spec = importlib.util.spec_from_file_location('ablation_runner', path.with_name('run.py'))
runner = importlib.util.module_from_spec(runner_spec)
runner_spec.loader.exec_module(runner)
diagnose_spec = importlib.util.spec_from_file_location('ablation_diagnose', path.with_name('diagnose.py'))
diagnose = importlib.util.module_from_spec(diagnose_spec)
diagnose_spec.loader.exec_module(diagnose)


class AblationAnalysisTest(unittest.TestCase):
    def test_paired_differences_only_use_matching_seeds_and_sample_std(self):
        def run(group, seed, value):
            return {'task': 'A', 'group': group, 'seed': seed, 'status': 'complete',
                    'final_metrics': {'macro_f1': value, 'accuracy': value}, 'campaign_cpu_seconds': 1.0,
                    'training_seconds': 0.5, 'peak_rss_bytes': 100, 'surrogate_used': 0, 'surrogate_attempts': 0}
        rows = [run('G0', 42, .1), run('G1', 42, .3), run('G0', 71, .2), run('G1', 103, .9)]
        result = analysis.analyze(rows, {})
        paired = result['paired_differences']['A']['G1-G0']
        self.assertEqual(paired['seeds'], [42])
        self.assertAlmostEqual(paired['metrics']['macro_f1']['mean'], .2)
        self.assertIsNone(paired['metrics']['macro_f1']['sample_std'])
        self.assertIsNotNone(result['fixed_rounds']['A']['G0']['metrics']['macro_f1']['sample_std'])

    def test_no_nasa_value_is_fabricated(self):
        self.assertEqual(analysis.stats([]), {'values': [], 'mean': None, 'sample_std': None})

    def test_equal_cpu_prefixes_have_seed_paired_differences(self):
        prefixes = {'A-42': {'groups': {'G0': {'metrics': {'macro_f1': .5, 'accuracy': .6}},
                                        'G1': {'metrics': {'macro_f1': .6, 'accuracy': .7}}}},
                    'A-71': {'groups': {'G0': {'metrics': {'macro_f1': .4, 'accuracy': .5}},
                                        'G1': {'metrics': {'macro_f1': .5, 'accuracy': .8}}}}}
        result = analysis.analyze([], prefixes)['equal_cpu_paired_differences']['A']['G1-G0']
        self.assertEqual(result['seeds'], [42, 71])
        self.assertAlmostEqual(result['metrics']['macro_f1']['mean'], .1)
        self.assertAlmostEqual(result['metrics']['accuracy']['mean'], .2)

    def test_ablation_switches_isolate_transfer_and_cost(self):
        groups = {group: runner.group_settings(group) for group in ('G1', 'G2', 'G3')}
        self.assertEqual({key for key in groups['G1'] if groups['G1'][key] != groups['G2'][key]},
                         {'transfer_enabled'})
        self.assertEqual({key for key in groups['G2'] if groups['G2'][key] != groups['G3'][key]},
                         {'transfer_cost_weight', 'acquisition_cost_gamma'})
        self.assertEqual(groups['G1']['shared_cost_quality_gate_ratio'], 1.0)

    def test_cost_ranking_audit_counts_actual_inversion(self):
        root = path.parents[2]
        with tempfile.TemporaryDirectory(dir=root / '.cache') as tmp:
            round_dir = Path(tmp) / 'round-03'
            (round_dir / 'state').mkdir(parents=True)
            trace = {'method': 'transfer_tpe', 'transfer_cost_weight': .05,
                     'transfer_cost_median_seconds': 2.5, 'history_rounds': []}
            usage = {'same_parent_used_rounds': [], 'transfer_used_rounds': [1, 2]}
            audit = {'search_trace': trace, 'history_usage': usage, 'accepted': False,
                     'decision': {'recommended_params': {}, 'final_params': {}}}
            (round_dir / 'result.json').write_text(json.dumps({'round': 3, 'audit': audit,
                'surrogate_attempted': False, 'surrogate_used': False}))
            records = [{'round': 1, 'robust_objective': .9, 'parent_objective': 1, 'training_seconds': 4},
                       {'round': 2, 'robust_objective': .91, 'parent_objective': 1, 'training_seconds': 1}]
            (round_dir / 'state/rac-round.json').write_text(json.dumps({'archive': records}))
            result = diagnose.inspect(Path(tmp))
            self.assertEqual(result['cost_ranking_changes'][0]['strict_rank_inversions'], 1)


if __name__ == '__main__':
    unittest.main()
