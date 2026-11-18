#!/usr/bin/env python3
"""Offline selected-parent SDK ablations. No network, no paid model, append-only outputs."""
import argparse
import base64
from collections import deque
from io import StringIO
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / 'workspace/verification/contest-p4.HzWSoucE/context-v2/sdk'
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'official_submission'), str(SDK)]
from rac_hpo.contest.packages import digest, prepare, verify, write_json

GROUPS = ('G0', 'G1', 'G2', 'G3')


def group_settings(group):
    if group not in GROUPS:
        raise ValueError('unknown ablation group')
    return {'transfer_enabled': group in ('G2', 'G3'),
            'transfer_cost_weight': 0.05 if group == 'G3' else 0.0,
            'acquisition_cost_gamma': 0.5 if group == 'G3' else 0.0,
            'shared_cost_quality_gate_ratio': 1.0}


def worker(args):
    package, output = Path(args.package), Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(package))
    from baselines.data import read_dataset
    from baselines.model import Model
    from baselines.train import metrics
    from contest_harness import Round
    import contest_submission as submission
    from rac_hpo.contest.rac_policy import ContestRACPolicy
    from threadpoolctl import threadpool_limits
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    manifest = verify(package, args.task)
    initial = output / 'initial.npz'
    shutil.copyfile(package / 'checkpoint.npz', initial)
    model = Model.load(initial)
    task, metric, direction = submission.CONTRACTS[args.task]
    validation = read_dataset(package / 'public/validation.jsonl', task, model.meta['classes'], model.meta['paths'])
    train_data = read_dataset(package / 'public/train.jsonl', task, model.meta['classes'], model.meta['paths'])
    initial_metrics = metrics(model, validation)
    fixed = {'learning_rate': model.meta['learning_rate'], 'batch_size': model.meta['batch_size'],
             'epochs': 2, 'sampling_level': 1}
    settings = group_settings(args.group)
    weight, transfer = settings['transfer_cost_weight'], settings['transfer_enabled']
    config = {'task': args.task, 'group': args.group, 'search_seed': args.seed,
              'checkpoint_training_seed': model.meta['seed'], 'fixed_params': fixed,
              'transfer_enabled': transfer, 'transfer_cost_weight': weight,
              'acquisition_cost_gamma': settings['acquisition_cost_gamma'],
              'shared_cost_quality_gate_ratio': settings['shared_cost_quality_gate_ratio'],
              'round_limit': args.rounds, 'cpu_threads': 1, 'source_metadata': True,
              'model_response': 'RAC', 'selection': 'same official callback gates in every group',
              'initial_sha256': digest(initial), 'train_sha256': train_data['sha256'],
              'validation_sha256': validation['sha256'], 'archive_sha256': manifest['archive_sha256'],
              'sdk': '1.0.2 local host', 'nasa_score': 'unavailable: platform formula not verified',
              'cpu_budget_seconds': args.cpu_budget}
    write_json(output / 'config.json', config)

    class Policy(ContestRACPolicy):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw, seed=args.seed, transfer_cost_weight=weight)
            self.search_config['rac_hpo']['gamma'] = settings['acquisition_cost_gamma']

        def propose(self, metadata, records, *, transfer_records=(), round_index=None):
            if args.group != 'G0':
                return super().propose(metadata, records, transfer_records=transfer_records, round_index=round_index)
            params = fixed.copy()
            proposal = {'learning_rate': params['learning_rate'], 'batch_size': params['batch_size'],
                        'epochs': params['epochs'], 'strategy': 'uniform', 'reason': 'Fixed continuation baseline.'}
            return proposal, {'params': params, 'method': 'fixed_parameters', 'reason': 'fixed_baseline',
                              'history_rounds': [], 'transfer_history_rounds': [], 'excluded_history': [],
                              'completed_history': 0}

    parent, parent_id, state = initial, 'initial', None
    selected_metrics = initial_metrics
    rows = []
    training_cpu_accum = []
    original_fit = submission.fit_epochs
    def timed_fit(*a, **kw):
        started = time.process_time()
        try:
            return original_fit(*a, **kw)
        finally:
            training_cpu_accum.append(time.process_time() - started)
    start_cpu, start_wall = time.process_time(), time.monotonic()
    with tempfile.TemporaryDirectory(prefix='.sdk-work-', dir=output) as work, threadpool_limits(limits=1), \
         patch.object(submission, 'ContestRACPolicy', Policy), patch.object(submission, 'fit_epochs', timed_fit), \
         patch.object(submission, 'WORKSPACE', Path(work)), \
         patch.dict(os.environ, {'RAC_TRANSFER_HISTORY': '1' if transfer else '0'}):
        for number in range(1, args.rounds + 1):
            if args.cpu_budget is not None and time.process_time() - start_cpu >= args.cpu_budget:
                break
            round_dir = output / f'round-{number:02}'
            round_dir.mkdir()
            parent_sha = digest(parent)
            frame = {'protocol': 'contest.harness.workspace.v2', 'prompt': 'Offline ablation',
                     'prompt_version': 'industrial-workspace-flexible-v3', 'dataset_key': args.task,
                     'round_index': number, 'task_contract': {'task': task, 'metric': metric,
                         'metric_direction': direction, 'public_projection': {
                             'train_path': str(package / 'public/train.jsonl'),
                             'validation_path': str(package / 'public/validation.jsonl'), 'source_metadata': True}},
                     'parent_checkpoint_sha256': parent_sha,
                     'parent_artifact': {'artifact_id': parent_id, 'artifact': {'checkpoint_paths': [parent.name],
                         'code_paths': []}, 'files': [{'path': parent.name, 'sha256': parent_sha}]},
                     'artifacts': [], 'model_name': 'offline-fixed-rac', 'max_output_tokens': 128,
                     'current_validation': {'metrics': selected_metrics}, 'state_path': str(state) if state else None}
            replies, sent = deque([frame]), {}
            candidate = round_dir / 'candidate.npz'
            host_state = round_dir / 'state'
            candidate_metrics = None
            class Host(StringIO):
                def write(self, line):
                    nonlocal candidate_metrics
                    msg = json.loads(line)
                    kind = msg['type']
                    sent[kind] = msg
                    reply = {'id': msg.get('id')}
                    if kind == 'history_request':
                        reply.update(type='history_response', records=[{'id': f'round-{n}', 'round_index': n}
                                                                    for n in range(1, number)])
                    elif kind == 'model_request':
                        reply.update(type='model_response', call_id=f'offline-{number}',
                                     response={'choices': [{'message': {'content': 'RAC'}}]})
                    elif kind == 'candidate_request':
                        if msg['parent_checkpoint_sha256'] != parent_sha:
                            raise ValueError('host received wrong parent digest')
                        candidate.write_bytes(base64.b64decode(msg['files'][0]['data_base64'], validate=True))
                        candidate_metrics = metrics(Model.load(candidate), validation)
                        reply.update(type='candidate_response', artifact_id=f'candidate-{number}',
                                     summary={'metrics': candidate_metrics})
                    elif kind == 'state_request':
                        host_state.mkdir()
                        for item in msg['files']:
                            dest = host_state / item['path']
                            if not dest.resolve().is_relative_to(host_state.resolve()):
                                raise ValueError('invalid state path')
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(base64.b64decode(item['data_base64'], validate=True))
                        reply.update(type='state_response', state_sha256='offline-state')
                    elif kind == 'round_complete':
                        reply.update(type='round_ack', accepted=True)
                    else:
                        raise ValueError(f'unexpected SDK request: {kind}')
                    replies.append(reply)
                    return len(line)
                def readline(self):
                    return json.dumps(replies.popleft()) + '\n'
            host = Host()
            try:
                rnd = Round.start(reader=host, writer=host)
                rnd.parent.root = parent.parent
                submission.train(rnd)
                if digest(parent) != parent_sha:
                    raise ValueError('parent changed')
                audit = json.loads((host_state / 'selection-audit.jsonl').read_text().splitlines()[-1])
                if audit['parent_sha256'] != parent_sha or audit['candidate_sha256'] != digest(candidate):
                    raise ValueError('checkpoint audit mismatch')
                history = audit['history_usage']
                for prior in history['same_parent_valid_rounds'] + history['transfer_used_rounds']:
                    if not 1 <= prior < number:
                        raise ValueError('future or current search observation')
                if audit['decision']['model_response'] != 'RAC' or not audit['decision']['model_response_valid']:
                    raise ValueError('unexpected local model response')
                if audit['accepted']:
                    parent, parent_id = candidate, f'candidate-{number}'
                    selected_metrics = candidate_metrics
                if audit['selected_sha256'] != digest(parent):
                    raise ValueError('incorrect selected checkpoint')
                state = host_state
                elapsed_cpu = time.process_time() - start_cpu
                trace = audit['search_trace']
                row = {'round': number, 'audit': audit, 'candidate_metrics': candidate_metrics,
                       'selected_metrics': selected_metrics, 'selected_sha256': digest(parent),
                       'training_cpu_seconds': training_cpu_accum[-1], 'cumulative_cpu_seconds': elapsed_cpu,
                       'cumulative_wall_seconds': time.monotonic() - start_wall,
                       'surrogate_attempted': 'forward_validation' in trace,
                       'surrogate_used': trace['method'] == 'rac_acquisition',
                       'cost_heuristic_used': trace['method'] == 'transfer_tpe' and weight > 0}
                write_json(round_dir / 'result.json', row)
                rows.append(row)
                print(json.dumps({'task': args.task, 'group': args.group, 'seed': args.seed,
                                  'round': number, 'method': trace['method'], 'accepted': audit['accepted'],
                                  'primary': selected_metrics[metric]}, allow_nan=False), flush=True)
            except Exception as error:
                write_json(round_dir / 'failure.json', {'type': type(error).__name__, 'message': str(error),
                                                       'parent_sha256': parent_sha})
                raise
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != 'darwin':
        peak *= 1024
    result = {'status': 'complete' if len(rows) == args.rounds else 'cpu_budget_stopped',
              'task': args.task, 'group': args.group, 'seed': args.seed,
              'rounds_completed': len(rows), 'initial_metrics': initial_metrics,
              'final_metrics': selected_metrics, 'final_sha256': digest(parent),
              'training_seconds': sum(row['audit']['training_seconds'] for row in rows),
              'training_cpu_seconds': sum(training_cpu_accum), 'campaign_cpu_seconds': time.process_time()-start_cpu,
              'process_cpu_seconds': time.process_time(), 'wall_seconds': time.monotonic()-start_wall,
              'peak_rss_bytes': peak, 'accepted': sum(row['audit']['accepted'] for row in rows),
              'rejected': sum(not row['audit']['accepted'] for row in rows),
              'surrogate_attempts': sum(row['surrogate_attempted'] for row in rows),
              'surrogate_used': sum(row['surrogate_used'] for row in rows),
              'transfer_tpe_rounds': sum(row['audit']['search_trace']['method'] == 'transfer_tpe' for row in rows),
              'cost_heuristic_rounds': sum(row['cost_heuristic_used'] for row in rows),
              'nasa_score': None}
    write_json(output / 'summary.json', result)


def campaign(args):
    output = Path(args.output).resolve()
    if not output.is_relative_to((ROOT / 'experiments/ablation').resolve()):
        raise ValueError('output must be under experiments/ablation')
    output.mkdir(parents=True, exist_ok=False)
    if len(args.seeds) > 1 and not args.allow_multiseed:
        raise ValueError('multi-seed campaign requires --allow-multiseed')
    if not SDK.is_dir():
        raise ValueError('verified local SDK source not found')
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'OPENBLAS_NUM_THREADS': '1',
           'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'BASELINE_CPU_THREADS': '1'}
    for key in ('PYTRIO_API_KEY', 'SWANLAB_API_KEY'):
        env.pop(key, None)
    sources = [ROOT / 'official_submission/contest_submission.py', ROOT / 'src/rac_hpo/_io.py',
               ROOT / 'src/rac_hpo/domain/metrics.py', Path(__file__)]
    for directory in (ROOT / 'src/rac_hpo/contest', ROOT / 'src/rac_hpo/optimization/rac_hpo',
                      SDK / 'contest_harness'):
        sources.extend(sorted(directory.glob('*.py')))
    write_json(output / 'campaign.json', {'tasks': args.tasks, 'groups': args.groups, 'seeds': args.seeds,
              'rounds': args.rounds, 'cpu_budget_seconds': args.cpu_budget, 'sequential': True,
              'python': sys.version, 'platform': platform.platform(), 'sdk_source': str(SDK),
              'source_sha256': {str(p.resolve().relative_to(ROOT)): digest(p) for p in sources}})
    failures = []
    with tempfile.TemporaryDirectory(prefix='.packages-', dir=output) as tmp:
        for task in args.tasks:
            archive, = (ROOT / '训练集').glob(f'cpu-{task.lower()}-*.zip')
            package = Path(tmp) / task
            prepare(archive, package, task)
            for seed in args.seeds:
                for group in args.groups:
                    run_dir = output / f'{task}-{group}-{seed}'
                    command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--task', task, '--group', group,
                               '--seed', str(seed), '--rounds', str(args.rounds), '--package', str(package),
                               '--output', str(run_dir)]
                    if args.cpu_budget is not None:
                        command += ['--cpu-budget', str(args.cpu_budget)]
                    print(f'Starting {task} {group} seed={seed}', flush=True)
                    result = subprocess.run(command, env=env, check=False)
                    if result.returncode:
                        failures.append({'task': task, 'group': group, 'seed': seed, 'exit_code': result.returncode})
                        print(json.dumps({'failed': failures[-1]}), flush=True)
    results = [json.loads(p.read_text()) for p in sorted(output.glob('*/summary.json'))]
    budgets = {}
    for task in args.tasks:
        for seed in args.seeds:
            subset = [row for row in results if row['task'] == task and row['seed'] == seed]
            if len(subset) != len(args.groups):
                continue
            cutoff = min(row['campaign_cpu_seconds'] for row in subset)
            budgets[f'{task}-{seed}'] = {'common_cpu_seconds': cutoff, 'method': 'post-hoc completed-round prefix',
                                        'groups': {}}
            for result in subset:
                run_dir = output / f"{task}-{result['group']}-{seed}"
                rows = [json.loads(p.read_text()) for p in sorted(run_dir.glob('round-*/result.json'))]
                eligible = [row for row in rows if row['cumulative_cpu_seconds'] <= cutoff]
                budgets[f'{task}-{seed}']['groups'][result['group']] = {
                    'rounds_completed': len(eligible),
                    'metrics': eligible[-1]['selected_metrics'] if eligible else result['initial_metrics'],
                    'selected_sha256': eligible[-1]['selected_sha256'] if eligible else
                                       json.loads((run_dir / 'config.json').read_text())['initial_sha256']}
    write_json(output / 'summary.json', {'runs': results, 'failures': failures, 'equal_cpu_prefix': budgets})
    if failures:
        raise SystemExit(1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--tasks', nargs='+', choices=list('ABC'), default=list('ABC'))
    p.add_argument('--groups', nargs='+', choices=GROUPS, default=list(GROUPS))
    p.add_argument('--seeds', nargs='+', type=int, default=[42])
    p.add_argument('--rounds', type=int, choices=range(1, 11), default=10)
    p.add_argument('--allow-multiseed', action='store_true')
    p.add_argument('--cpu-budget', type=float, default=None)
    p.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--package', help=argparse.SUPPRESS)
    p.add_argument('--task', choices=list('ABC'), help=argparse.SUPPRESS)
    p.add_argument('--group', choices=GROUPS, help=argparse.SUPPRESS)
    p.add_argument('--seed', type=int, help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.cpu_budget is not None and args.cpu_budget <= 0:
        p.error('CPU budget must be positive')
    if args.worker:
        worker(args)
    else:
        for seq in (args.tasks, args.groups, args.seeds):
            if len(seq) != len(set(seq)):
                p.error('tasks, groups, and seeds must be unique')
        campaign(args)


if __name__ == '__main__':
    main()
