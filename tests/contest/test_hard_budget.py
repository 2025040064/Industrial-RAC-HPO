import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / 'experiments/ablation/hard_budget.py'
spec = importlib.util.spec_from_file_location('hard_budget', path)
hard_budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hard_budget)


class HardBudgetTest(unittest.TestCase):
    def test_remaining_budget_rounds_down_and_never_resets(self):
        self.assertEqual(hard_budget.remaining_limit(4, 1.25), 2)
        self.assertEqual(hard_budget.remaining_limit(4, 3.2), 0)
        self.assertEqual(hard_budget.remaining_limit(4, 4.1), 0)

    def test_nested_cpu_phase_accounting_is_exclusive_and_covers_interruption(self):
        events = [{'event': 'begin', 'phase': 'search', 'cpu': 1},
                  {'event': 'begin', 'phase': 'validation', 'cpu': 2},
                  {'event': 'end', 'phase': 'validation', 'cpu': 3},
                  {'event': 'end', 'phase': 'search', 'cpu': 4},
                  {'event': 'begin', 'phase': 'train', 'cpu': 5}]
        values = hard_budget.phase_totals(events, 7)
        self.assertEqual(values['search'], 2)
        self.assertEqual(values['validation'], 1)
        self.assertEqual(values['train'], 2)
        self.assertEqual(values['other'], 2)
        self.assertEqual(sum(values.values()), 7)

    def test_os_kills_uncooperative_cpu_task_and_reports_actual_cpu(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as tmp:
            out = hard_budget.execute_limited([sys.executable, '-c', 'while True: pass'], 1,
                                              Path(tmp) / 'worker.log', os.environ.copy())
        self.assertIn(out['signal'], (signal.SIGXCPU, signal.SIGKILL))
        self.assertGreater(out['cpu_seconds'], .8)
        self.assertLess(out['cpu_seconds'], 1.2)

    def test_soft_cpu_signal_reserves_one_second_before_hard_cap(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as tmp:
            out = hard_budget.execute_limited([sys.executable, '-c', 'while True: pass'], 2,
                                              Path(tmp) / 'worker.log', os.environ.copy(),
                                              safety_margin_seconds=1)
        self.assertIn(out['signal'], (signal.SIGXCPU, signal.SIGKILL))
        self.assertEqual(out['kernel_soft_limit_seconds'], 1)
        self.assertLess(out['cpu_seconds'], 2)

    def test_unfinished_attempt_cannot_be_silently_resumed(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as tmp:
            attempt = Path(tmp) / 'attempt-0001'
            attempt.mkdir()
            (attempt / 'reservation.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'unaccounted'):
                hard_budget.attempt_usage(Path(tmp))
            (attempt / 'completion.json').write_text(json.dumps({'cpu_seconds': 1.25}))
            self.assertEqual(hard_budget.attempt_usage(Path(tmp)), 1.25)

    def test_uncommitted_candidate_is_ignored_and_parent_chain_is_verified(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as tmp:
            root = Path(tmp)
            initial = root / 'initial.npz'
            initial.write_bytes(b'parent')
            one = root / 'attempt-0001/round-01'
            one.mkdir(parents=True)
            candidate = one / 'candidate.npz'
            candidate.write_bytes(b'candidate')
            sha0, sha1 = hard_budget.file_digest(initial), hard_budget.file_digest(candidate)
            state = one / 'state'
            state.mkdir()
            (state / 'selection-audit.jsonl').write_text(json.dumps({'round': 1, 'selected_sha256': sha1}) + '\n')
            row = {'round': 1, 'parent_sha256': sha0, 'candidate_sha256': sha1,
                   'selected_sha256': sha1, 'accepted': True,
                   'candidate_path': str(candidate.relative_to(root)), 'state_path': str(state.relative_to(root))}
            (one / 'result.json').write_text(json.dumps(row))
            partial = root / 'attempt-0002/round-02'
            partial.mkdir(parents=True)
            (partial / 'candidate.npz').write_bytes(b'uncommitted')
            committed = hard_budget.scan_commits(root, sha0)
            self.assertEqual(len(committed), 1)
            row['parent_sha256'] = '0' * 64
            (one / 'result.json').write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, 'parent chain'):
                hard_budget.scan_commits(root, sha0)

    @unittest.skipUnless(os.environ.get('CONTEST_HARD_BUDGET_INTEGRATION') == '1', 'explicit local CPU integration')
    def test_real_checkpoint_resume_after_cpu_kill_keeps_parent_and_consumed_budget(self):
        from rac_hpo.contest.packages import prepare, write_json

        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as tmp:
            campaign = Path(tmp)
            shutil.copyfile(ROOT / 'experiments/ablation/stage2-20261118-01/protocol.json', campaign / 'protocol.json')
            write_json(campaign / 'engine-lock.json', {'source_sha256': {
                'experiments/ablation/hard_budget.py': hard_budget.file_digest(path)}})
            package = campaign / 'package'
            prepare(next((ROOT / '训练集').glob('cpu-a-*.zip')), package, 'A')
            run = campaign / 'runs/A-G0-404'
            run.mkdir(parents=True)
            hard_budget.atomic_bytes(run / 'initial.npz', (package / 'checkpoint.npz').read_bytes())
            write_json(run / 'spec.json', {'task': 'A', 'group': 'G0', 'seed': 404, 'round_limit': 10,
                       'cpu_budget_seconds': 4, 'frozen_protocol_sha256': hard_budget.file_digest(campaign / 'protocol.json'),
                       'engine_lock_sha256': hard_budget.file_digest(campaign / 'engine-lock.json')})
            attempt = run / 'attempt-0001'
            attempt.mkdir()
            write_json(attempt / 'reservation.json', {'kernel_limit_seconds': 2})
            env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'OPENBLAS_NUM_THREADS': '1',
                   'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
            command = [sys.executable, str(path), '--worker', '--campaign', str(campaign), '--run-dir', str(run),
                       '--attempt', str(attempt), '--package', str(package), '--used-before', '0']
            result = hard_budget.execute_limited(command, 2, attempt / 'worker.log', env)
            self.assertIn(result['signal'], (signal.SIGXCPU, signal.SIGKILL))
            events = [json.loads(line) for line in (attempt / 'phases.jsonl').read_text().splitlines()]
            result['phase_cpu_seconds'] = hard_budget.phase_totals(events, result['cpu_seconds'])
            write_json(attempt / 'completion.json', result)
            before = hard_budget.scan_commits(run, hard_budget.file_digest(run / 'initial.npz'))
            self.assertGreater(len(before), 0)
            first = run / before[0]['candidate_path']
            checksum = hard_budget.file_digest(first)
            resumed = hard_budget.start_run(campaign, package, 'A', 'G0', 404, 10, resume=True)
            self.assertGreaterEqual(resumed['rounds_completed'], len(before))
            self.assertGreater(resumed['worker_cpu_seconds'], result['cpu_seconds'])
            self.assertLess(resumed['worker_cpu_seconds'], 4.1)
            self.assertEqual(hard_budget.file_digest(first), checksum)
            self.assertEqual(len(hard_budget.scan_commits(run, hard_budget.file_digest(run / 'initial.npz'))),
                             resumed['rounds_completed'])
            self.assertGreater(before[0]['peak_rss_bytes'], 0)
            self.assertEqual(resumed['partial_round_attempts'], len(resumed['partial_rounds']))
            for partial in resumed['partial_rounds']:
                if partial['start_cpu_seconds'] is not None:
                    self.assertGreaterEqual(partial['cpu_seconds_until_worker_exit'], 0)


if __name__ == '__main__':
    unittest.main()
