#!/usr/bin/env python3
"""OS-enforced CPU budget and crash-safe selected-checkpoint ablation runner."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def file_digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def remaining_limit(budget, used):
    if budget <= 0 or used < 0:
        raise ValueError('invalid CPU budget')
    return max(0, math.floor(budget - used + 1e-9))


def phase_totals(events, total_cpu):
    totals = {'preload': 0.0, 'search': 0.0, 'train': 0.0, 'validation': 0.0,
              'sdk_host': 0.0, 'other': 0.0}
    stack = []
    previous = 0.0
    for event in events:
        now = max(previous, min(float(event['cpu']), total_cpu))
        totals[stack[-1] if stack else 'other'] += now - previous
        previous = now
        if event['event'] == 'begin':
            stack.append(event['phase'])
        elif event['event'] == 'end':
            if not stack or stack[-1] != event['phase']:
                raise ValueError('unbalanced phase journal')
            stack.pop()
        else:
            raise ValueError('invalid phase event')
    totals[stack[-1] if stack else 'other'] += max(0, total_cpu - previous)
    return totals


def execute_limited(command, limit_seconds, log_path, env, *, safety_margin_seconds=0):
    if type(limit_seconds) is not int or limit_seconds < 1:
        raise ValueError('CPU limit must be positive integral seconds')
    if type(safety_margin_seconds) is not int or safety_margin_seconds < 0:
        raise ValueError('invalid kernel safety margin')
    soft_limit = max(1, limit_seconds - safety_margin_seconds)
    def set_limit():
        resource.setrlimit(resource.RLIMIT_CPU, (soft_limit, limit_seconds))
    started = time.monotonic()
    with Path(log_path).open('xb') as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env,
                                 preexec_fn=set_limit)
        interrupted = False
        try:
            _, status, usage = os.wait4(child.pid, 0)
        except KeyboardInterrupt:
            interrupted = True
            try:
                os.kill(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    peak = usage.ru_maxrss if sys.platform == 'darwin' else usage.ru_maxrss * 1024
    return {'exit_code': child.returncode, 'signal': os.WTERMSIG(status) if os.WIFSIGNALED(status) else None,
            'cpu_seconds': usage.ru_utime + usage.ru_stime, 'user_cpu_seconds': usage.ru_utime,
            'system_cpu_seconds': usage.ru_stime, 'peak_rss_bytes': peak,
            'wall_seconds': time.monotonic() - started, 'interrupted': interrupted,
            'kernel_limit_seconds': limit_seconds, 'kernel_soft_limit_seconds': soft_limit}


def attempt_usage(run_dir):
    total = 0.0
    for attempt in sorted(Path(run_dir).glob('attempt-*')):
        if not (attempt / 'reservation.json').is_file():
            continue
        completion = attempt / 'completion.json'
        if not completion.is_file():
            raise ValueError(f'unaccounted attempt; refusing to reset CPU budget: {attempt.name}')
        data = json.loads(completion.read_text())
        total += data['cpu_seconds']
    return total


def scan_commits(run_dir, initial_sha):
    run_dir = Path(run_dir)
    rows = [json.loads(p.read_text()) for p in run_dir.glob('attempt-*/round-*/result.json')]
    rows.sort(key=lambda row: row['round'])
    parent_sha = initial_sha
    for expected, row in enumerate(rows, 1):
        if row['round'] != expected or row['parent_sha256'] != parent_sha:
            raise ValueError('invalid or duplicate parent chain')
        candidate = (run_dir / row['candidate_path']).resolve()
        state = (run_dir / row['state_path']).resolve()
        if not candidate.is_relative_to(run_dir.resolve()) or not state.is_relative_to(run_dir.resolve()):
            raise ValueError('checkpoint outside run')
        if file_digest(candidate) != row['candidate_sha256']:
            raise ValueError('candidate digest mismatch')
        expected_sha = row['candidate_sha256'] if row['accepted'] else parent_sha
        if row['selected_sha256'] != expected_sha:
            raise ValueError('selected checkpoint differs from parent chain')
        audit = [json.loads(line) for line in (state / 'selection-audit.jsonl').read_text().splitlines()]
        if not audit or audit[-1]['round'] != expected or audit[-1]['selected_sha256'] != expected_sha:
            raise ValueError('selection audit differs from parent chain')
        parent_sha = expected_sha
    return rows


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.round = 0
        self.emit('begin', 'preload', cpu=0.0)

    def emit(self, event, phase, cpu=None):
        entry = {'round': self.round, 'event': event, 'phase': phase,
                 'cpu': time.process_time() if cpu is None else cpu}
        data = (json.dumps(entry, allow_nan=False) + '\n').encode()
        fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextmanager
    def section(self, phase):
        self.emit('begin', phase)
        try:
            yield
        finally:
            self.emit('end', phase)

    def events(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]


def atomic_bytes(path, data):
    path = Path(path)
    temp = path.with_name('.' + path.name + '.partial')
    with temp.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def subset_metrics(diagnostics):
    groups = diagnostics.get('groups') if isinstance(diagnostics, dict) else None
    if not groups:
        return None
    totals = {}
    for key, row in groups.items():
        subset = key.rsplit('/', 1)[0]
        target = totals.setdefault(subset, {'samples': 0, 'absolute_error_sum': 0.0, 'squared_error_sum': 0.0})
        target['samples'] += row['samples']
        target['absolute_error_sum'] += row['mae'] * row['samples']
        target['squared_error_sum'] += row['rmse'] ** 2 * row['samples']
    return {key: {'samples': val['samples'], 'mae': val['absolute_error_sum'] / val['samples'],
                  'rmse': math.sqrt(val['squared_error_sum'] / val['samples'])} for key, val in totals.items()}


def worker(options):
    from collections import deque
    from io import StringIO
    from unittest.mock import patch
    import base64
    import contextlib
    import shutil
    import tempfile

    run_dir, package, attempt = Path(options.run_dir), Path(options.package), Path(options.attempt)
    journal = Journal(attempt / 'phases.jsonl')
    sys.path[:0] = [str(package), str(ROOT / 'src'), str(ROOT / 'official_submission'),
                    str(ROOT / 'workspace/verification/contest-p4.HzWSoucE/context-v2/sdk')]
    from baselines.data import read_dataset
    from baselines.model import Model
    from baselines.train import metrics
    from contest_harness import Round
    from contest_harness.round import DataView
    import contest_submission as submission
    from rac_hpo.contest.packages import write_json
    from rac_hpo.contest.rac_policy import ContestRACPolicy
    from threadpoolctl import threadpool_limits
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    spec = json.loads((run_dir / 'spec.json').read_text())
    locked = json.loads((Path(options.campaign) / 'protocol.json').read_text())
    group, task_key, seed = spec['group'], spec['task'], spec['seed']
    task, metric, direction = submission.CONTRACTS[task_key]
    fixed = locked['fixed_params'][task_key].copy()
    settings = locked['groups'][group]
    weight, transfer = settings['transfer_cost_weight'], settings['transfer_enabled']
    if file_digest(run_dir / 'initial.npz') != locked['inputs'][task_key]['initial_sha256']:
        raise ValueError('initial checkpoint differs from frozen protocol')
    initial_model = Model.load(run_dir / 'initial.npz')
    validation = read_dataset(package / 'public/validation.jsonl', task,
                              initial_model.meta['classes'], initial_model.meta['paths'])
    train_data = read_dataset(package / 'public/train.jsonl', task,
                              initial_model.meta['classes'], initial_model.meta['paths'])
    if (train_data['sha256'] != locked['inputs'][task_key]['train_sha256']
            or validation['sha256'] != locked['inputs'][task_key]['validation_sha256']):
        raise ValueError('public projection differs from frozen protocol')
    projection = {'train_path': str(package / 'public/train.jsonl'),
                  'validation_path': str(package / 'public/validation.jsonl'), 'source_metadata': True}
    source_contract = {'public_projection': projection}
    view = DataView(source_contract)
    val_groups = submission.projection_groups(view, 'validation', task_key, source_contract, validation['ids'])
    with journal.section('validation'):
        initial_metrics = metrics(initial_model, validation)
        initial_diagnostics = submission.evaluate_diagnostics(initial_model, validation, val_groups)
    baseline = {'metrics': initial_metrics, 'diagnostics': initial_diagnostics,
                'subsets': subset_metrics(initial_diagnostics) if task_key == 'C' else None,
                'initial_sha256': locked['inputs'][task_key]['initial_sha256'],
                'cpu_at_measurement': options.used_before + time.process_time()}
    if not (run_dir / 'baseline.json').exists():
        write_json(run_dir / 'baseline.json', baseline)
    else:
        saved_baseline = json.loads((run_dir / 'baseline.json').read_text())
        if saved_baseline['metrics'] != initial_metrics or saved_baseline['initial_sha256'] != baseline['initial_sha256']:
            raise ValueError('baseline changed on resume')
    commits = scan_commits(run_dir, locked['inputs'][task_key]['initial_sha256'])
    parent = run_dir / 'initial.npz'
    parent_id, state, selected_metrics = 'initial', None, initial_metrics
    selected_diagnostics = initial_diagnostics
    for row in commits:
        if row['accepted']:
            parent = run_dir / row['candidate_path']
            parent_id = row['selected_artifact_id']
            selected_metrics = row['selected_metrics']
            selected_diagnostics = row['selected_diagnostics']
        state = run_dir / row['state_path']
    journal.emit('end', 'preload')

    class Policy(ContestRACPolicy):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw, seed=seed, transfer_cost_weight=weight)
            self.search_config['rac_hpo']['gamma'] = settings['acquisition_cost_gamma']
            self.search_config['cost_gate_mode'] = settings['cost_gate_mode']

        def propose(self, metadata, records, *, transfer_records=(), round_index=None):
            with journal.section('search'):
                if group != 'G0':
                    return super().propose(metadata, records, transfer_records=transfer_records, round_index=round_index)
                params = fixed.copy()
                proposal = {'learning_rate': params['learning_rate'], 'batch_size': params['batch_size'],
                            'epochs': params['epochs'], 'strategy': 'uniform', 'reason': 'Fixed continuation baseline.'}
                return proposal, {'params': params, 'method': 'fixed_parameters', 'reason': 'fixed_baseline',
                                  'history_rounds': [], 'transfer_history_rounds': [], 'excluded_history': [],
                                  'completed_history': 0}

    def wrap(fn, category):
        def inner(*a, **kw):
            with journal.section(category):
                return fn(*a, **kw)
        return inner

    patches = [(submission, 'ContestRACPolicy', Policy),
               (submission, 'fit_epochs', wrap(submission.fit_epochs, 'train')),
               (submission, 'read_dataset', wrap(submission.read_dataset, 'preload')),
               (submission, 'projection_groups', wrap(submission.projection_groups, 'preload')),
               (submission, 'load_model', wrap(submission.load_model, 'preload')),
               (submission, 'evaluate_diagnostics', wrap(submission.evaluate_diagnostics, 'validation')),
               (submission, 'evaluate_primary', wrap(submission.evaluate_primary, 'validation')),
               (Round, '_rpc', wrap(Round._rpc, 'sdk_host')),
               (Round, 'state_workspace', wrap(Round.state_workspace, 'sdk_host'))]
    os.environ['RAC_TRANSFER_HISTORY'] = '1' if transfer else '0'
    for key in ('transfer_mode', 'surrogate_mode', 'cost_mode', 'bearing_mode'):
        os.environ[{'transfer_mode':'RAC_TRANSFER_MODE','surrogate_mode':'RAC_SURROGATE_MODE',
                    'cost_mode':'RAC_COST_MODE','bearing_mode':'RAC_BEARING_FEASIBILITY'}[key]] = settings[key]
    with contextlib.ExitStack() as stack:
        stack.enter_context(threadpool_limits(limits=1))
        work = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='.sdk-work-', dir=attempt)))
        stack.enter_context(patch.object(submission, 'WORKSPACE', work))
        for target, name, value in patches:
            stack.enter_context(patch.object(target, name, value))
        for number in range(len(commits) + 1, spec['round_limit'] + 1):
            journal.round = number
            round_dir = attempt / f'round-{number:02}'
            round_dir.mkdir()
            parent_sha = file_digest(parent)
            before_cpu = options.used_before + time.process_time()
            write_json(round_dir / 'round-start.json', {'task': task_key, 'group': group, 'seed': seed,
                       'round': number, 'parent_sha256': parent_sha, 'cumulative_cpu_seconds': before_cpu})
            frame = {'protocol': 'contest.harness.workspace.v2', 'prompt': 'Offline budget ablation',
                     'prompt_version': 'industrial-workspace-flexible-v3', 'dataset_key': task_key,
                     'round_index': number, 'task_contract': {'task': task, 'metric': metric,
                         'metric_direction': direction, 'public_projection': projection},
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
                            raise ValueError('host received wrong parent')
                        atomic_bytes(candidate, base64.b64decode(msg['files'][0]['data_base64'], validate=True))
                        with journal.section('validation'):
                            candidate_metrics = metrics(Model.load(candidate), validation)
                        reply.update(type='candidate_response', artifact_id=f'candidate-{number}',
                                     summary={'metrics': candidate_metrics})
                    elif kind == 'state_request':
                        host_state.mkdir()
                        for item in msg['files']:
                            dest = host_state / item['path']
                            if not dest.resolve().is_relative_to(host_state.resolve()):
                                raise ValueError('invalid host state path')
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            atomic_bytes(dest, base64.b64decode(item['data_base64'], validate=True))
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
                with journal.section('sdk_host'):
                    rnd = Round.start(reader=host, writer=host)
                rnd.parent.root = parent.parent
                submission.train(rnd)
                if file_digest(parent) != parent_sha:
                    raise ValueError('parent checkpoint changed')
                audit = json.loads((host_state / 'selection-audit.jsonl').read_text().splitlines()[-1])
                if audit['parent_sha256'] != parent_sha or audit['candidate_sha256'] != file_digest(candidate):
                    raise ValueError('candidate or parent digest mismatch')
                for prior in audit['history_usage']['same_parent_valid_rounds'] + audit['history_usage']['transfer_used_rounds']:
                    if not 1 <= prior < number:
                        raise ValueError('future or current search observation')
                if audit['accepted']:
                    parent, parent_id = candidate, f'candidate-{number}'
                    selected_metrics = candidate_metrics
                    selected_diagnostics = audit['candidate_diagnostics']
                else:
                    selected_diagnostics = audit['parent_diagnostics']
                if audit['selected_sha256'] != file_digest(parent):
                    raise ValueError('incorrect selected checkpoint')
                state = host_state
                cpu = options.used_before + time.process_time()
                peak_at_round = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if sys.platform != 'darwin':
                    peak_at_round *= 1024
                trace = audit['search_trace']
                row = {'task': task_key, 'group': group, 'seed': seed, 'round': number,
                       'parent_sha256': parent_sha, 'candidate_sha256': audit['candidate_sha256'],
                       'selected_sha256': audit['selected_sha256'], 'accepted': audit['accepted'],
                       'selected_artifact_id': audit['selected_artifact_id'],
                       'candidate_path': str(candidate.relative_to(run_dir)),
                       'state_path': str(host_state.relative_to(run_dir)),
                       'candidate_metrics': candidate_metrics, 'selected_metrics': selected_metrics,
                       'selected_diagnostics': selected_diagnostics,
                       'selected_subset_metrics': subset_metrics(selected_diagnostics) if task_key == 'C' else None,
                       'nasa_score': None, 'audit': audit, 'round_cpu_seconds': cpu - before_cpu,
                       'cumulative_cpu_seconds': cpu, 'budget_seconds': spec['cpu_budget_seconds'],
                       'peak_rss_bytes': peak_at_round,
                       'surrogate_attempted': 'forward_validation' in trace,
                       'surrogate_used': trace['method'] == 'rac_acquisition',
                       'status': 'complete'}
                write_json(round_dir / 'result.json', row)
                print(json.dumps({'task': task_key, 'group': group, 'seed': seed, 'round': number,
                                  'cpu': round(cpu, 3), 'metric': selected_metrics[metric],
                                  'method': trace['method'], 'accepted': audit['accepted']}), flush=True)
            except Exception as error:
                write_json(round_dir / 'failure.json', {'type': type(error).__name__, 'message': str(error),
                                                       'parent_sha256': parent_sha})
                raise
    write_json(attempt / 'worker-completed.json', {'rounds_completed': len(scan_commits(run_dir, locked['inputs'][task_key]['initial_sha256']))})


def verify_sources(protocol):
    mismatches = [name for name, checksum in protocol['source_sha256'].items()
                  if file_digest(ROOT / name) != checksum]
    if mismatches:
        raise ValueError(f'frozen source differs: {mismatches}')


def verify_engine(campaign):
    lock = json.loads((Path(campaign) / 'engine-lock.json').read_text())
    for name, expected in lock['source_sha256'].items():
        if file_digest(ROOT / name) != expected:
            raise ValueError(f'frozen experiment driver differs: {name}')


def start_run(campaign, package, task, group, seed, round_limit, *, resume=False):
    import shutil
    from rac_hpo.contest.packages import write_json
    campaign, package = Path(campaign), Path(package)
    protocol = json.loads((campaign / 'protocol.json').read_text())
    run_dir = campaign / 'runs' / f'{task}-{group}-{seed}'
    spec = {'task': task, 'group': group, 'seed': seed, 'round_limit': round_limit,
            'cpu_budget_seconds': protocol['task_budgets_cpu_seconds'][task],
            'frozen_protocol_sha256': file_digest(campaign / 'protocol.json'),
            'engine_lock_sha256': file_digest(campaign / 'engine-lock.json')}
    if run_dir.exists():
        if not resume:
            raise FileExistsError(f'run exists; use --resume: {run_dir}')
        if json.loads((run_dir / 'spec.json').read_text()) != spec:
            raise ValueError('resume configuration differs from frozen run')
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        atomic_bytes(run_dir / 'initial.npz', (package / 'checkpoint.npz').read_bytes())
        write_json(run_dir / 'spec.json', spec)
    if file_digest(run_dir / 'initial.npz') != protocol['inputs'][task]['initial_sha256']:
        raise ValueError('initial checkpoint changed')
    if (run_dir / 'summary.json').exists():
        saved = json.loads((run_dir / 'summary.json').read_text())
        checked = scan_commits(run_dir, protocol['inputs'][task]['initial_sha256'])
        expected = checked[-1]['selected_sha256'] if checked else protocol['inputs'][task]['initial_sha256']
        if (saved['rounds_completed'] != len(checked) or saved['final_sha256'] != expected
                or abs(saved['worker_cpu_seconds'] - attempt_usage(run_dir)) > 1e-8):
            raise ValueError('saved summary differs from verified checkpoint chain or CPU ledger')
        return saved
    previous_cpu = attempt_usage(run_dir)
    committed = scan_commits(run_dir, protocol['inputs'][task]['initial_sha256'])
    remaining = remaining_limit(spec['cpu_budget_seconds'], previous_cpu)
    if len(committed) < round_limit and remaining:
        attempt_number = 1 + max((int(p.name.split('-')[1]) for p in run_dir.glob('attempt-*')), default=0)
        attempt = run_dir / f'attempt-{attempt_number:04}'
        attempt.mkdir()
        write_json(attempt / 'reservation.json', {'prior_cpu_seconds': previous_cpu,
                   'remaining_budget_seconds': max(0, spec['cpu_budget_seconds']-previous_cpu),
                   'kernel_limit_seconds': remaining, 'restarts_left_unallocated_seconds':
                       max(0, spec['cpu_budget_seconds'] - previous_cpu - remaining)})
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'OPENBLAS_NUM_THREADS': '1',
               'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'BASELINE_CPU_THREADS': '1'}
        for key in ('PYTRIO_API_KEY', 'SWANLAB_API_KEY'):
            env.pop(key, None)
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--campaign', str(campaign),
                   '--run-dir', str(run_dir), '--attempt', str(attempt), '--package', str(package),
                   '--used-before', str(previous_cpu)]
        engine_lock = json.loads((campaign / 'engine-lock.json').read_text())
        result = execute_limited(command, remaining, attempt / 'worker.log', env,
                                 safety_margin_seconds=engine_lock.get('soft_signal_margin_seconds', 0))
        events_file = attempt / 'phases.jsonl'
        events = [json.loads(line) for line in events_file.read_text().splitlines()] if events_file.exists() else []
        result['phase_cpu_seconds'] = phase_totals(events, result['cpu_seconds'])
        result['phase_journal_last_round'] = events[-1]['round'] if events else None
        result['prior_cpu_seconds'] = previous_cpu
        result['budget_overrun_seconds'] = max(0, previous_cpu + result['cpu_seconds'] - spec['cpu_budget_seconds'])
        write_json(attempt / 'completion.json', result)
        for temp in attempt.glob('.sdk-work-*'):
            if temp.is_dir() and not temp.is_symlink():
                shutil.rmtree(temp)
        if result['interrupted']:
            raise KeyboardInterrupt
        if result['exit_code'] != 0 and result['signal'] not in (signal.SIGXCPU, signal.SIGKILL):
            print(f"FAILED {task} {group} {seed}: exit={result['exit_code']}", flush=True)
        previous_cpu = attempt_usage(run_dir)
        committed = scan_commits(run_dir, protocol['inputs'][task]['initial_sha256'])
    attempts = [json.loads(p.read_text()) for p in sorted(run_dir.glob('attempt-*/completion.json'))]
    if not attempts and not committed:
        raise ValueError('budget too small to start worker')
    baseline_path = run_dir / 'baseline.json'
    if not baseline_path.exists():
        raise ValueError('worker stopped before measuring baseline')
    baseline = json.loads(baseline_path.read_text())
    last = committed[-1] if committed else None
    cpu_used = sum(item['cpu_seconds'] for item in attempts)
    signal_killed = any(item['signal'] in (signal.SIGXCPU, signal.SIGKILL) for item in attempts)
    completed = len(committed) >= round_limit
    failures = [item for item in attempts if item['exit_code'] != 0
                and item['signal'] not in (signal.SIGXCPU, signal.SIGKILL)]
    last_failed = bool(attempts and attempts[-1] in failures)
    status = 'complete' if completed else 'failed' if last_failed else 'budget_exhausted'
    total_phases = {name: sum(item['phase_cpu_seconds'][name] for item in attempts)
                    for name in ('preload', 'search', 'train', 'validation', 'sdk_host', 'other')}
    partial_rounds = []
    for attempt in sorted(run_dir.glob('attempt-*')):
        completion_path = attempt / 'completion.json'
        if not completion_path.exists():
            continue
        completion = json.loads(completion_path.read_text())
        end_cpu = completion.get('prior_cpu_seconds', 0.0) + completion['cpu_seconds']
        for directory in sorted(attempt.glob('round-*')):
            if (directory / 'result.json').exists():
                continue
            start_path = directory / 'round-start.json'
            start = json.loads(start_path.read_text()) if start_path.exists() else None
            partial_rounds.append({'attempt': attempt.name, 'round_directory': directory.name,
                                   'start_cpu_seconds': start['cumulative_cpu_seconds'] if start else None,
                                   'end_cpu_seconds': end_cpu,
                                   'cpu_seconds_until_worker_exit': max(0, end_cpu - start['cumulative_cpu_seconds'])
                                                                   if start else None})
    summary = {'task': task, 'group': group, 'seed': seed, 'status': status,
               'rounds_completed': len(committed), 'round_limit': round_limit,
               'partial_round_attempts': len(list(run_dir.glob('attempt-*/round-*'))) - len(committed),
               'partial_rounds': partial_rounds,
               'budget_seconds': spec['cpu_budget_seconds'], 'worker_cpu_seconds': cpu_used,
               'budget_overrun_seconds': max(0, cpu_used - spec['cpu_budget_seconds']),
               'unused_cpu_seconds': max(0, spec['cpu_budget_seconds'] - cpu_used),
               'kernel_cpu_limit_reached': signal_killed, 'phase_cpu_seconds': total_phases,
               'user_cpu_seconds': sum(item['user_cpu_seconds'] for item in attempts),
               'system_cpu_seconds': sum(item['system_cpu_seconds'] for item in attempts),
               'wall_seconds': sum(item['wall_seconds'] for item in attempts),
               'peak_rss_bytes': max((item['peak_rss_bytes'] for item in attempts), default=0),
               'initial_metrics': baseline['metrics'], 'final_metrics': last['selected_metrics'] if last else baseline['metrics'],
               'final_subsets': last['selected_subset_metrics'] if last else baseline['subsets'],
               'initial_sha256': baseline['initial_sha256'],
               'final_sha256': last['selected_sha256'] if last else baseline['initial_sha256'],
               'accepted': sum(row['accepted'] for row in committed),
               'rejected': sum(not row['accepted'] for row in committed),
               'surrogate_attempts': sum(row['surrogate_attempted'] for row in committed),
               'surrogate_used': sum(row['surrogate_used'] for row in committed),
               'transfer_tpe_rounds': sum(row['audit']['search_trace']['method'] == 'transfer_tpe' for row in committed),
               'nasa_score': None, 'attempts': len(attempts), 'failed_attempts': len(failures)}
    if status == 'failed':
        write_json(run_dir / f'failure-summary-{len(attempts):04}.json', summary)
    else:
        write_json(run_dir / 'summary.json', summary)
    print(json.dumps({'completed_run': f'{task}-{group}-{seed}', 'status': status,
                      'rounds': len(committed), 'cpu': cpu_used, 'budget': spec['cpu_budget_seconds'],
                      'final_metrics': summary['final_metrics']}), flush=True)
    return summary


def run_campaign(options):
    import tempfile
    from rac_hpo.contest.packages import prepare, write_json
    campaign = Path(options.campaign).resolve()
    protocol = json.loads((campaign / 'protocol.json').read_text())
    verify_sources(protocol)
    verify_engine(campaign)
    if not (campaign / 'BUDGET_TESTS_PASSED.json').is_file():
        raise ValueError('budget unit and recovery tests must pass before running the campaign')
    if options.smoke:
        seeds, round_limit = [404], 1
    else:
        seeds, round_limit = protocol['search_seeds'], protocol['maximum_rounds']
        if not (campaign / 'SMOKE_PASSED.json').is_file():
            raise ValueError('budget tests and smoke must pass before paired campaign')
    groups = ('R0-shadow', 'R1', 'R2', 'R3')
    # Each task/seed block rotates the group order; all groups occupy several positions.
    schedule = []
    for seed_index, seed in enumerate(seeds):
        for task_index, task in enumerate('ABC'):
            offset = (seed_index + task_index) % len(groups)
            for group in groups[offset:] + groups[:offset]:
                schedule.append((task, group, seed))
    schedule_path = campaign / ('smoke-schedule.json' if options.smoke else 'paired-schedule.json')
    frozen_schedule = {'runs': [{'task': t, 'group': g, 'seed': s} for t, g, s in schedule],
                       'round_limit': round_limit, 'order': 'group rotation by seed and task',
                       'controller_cpu_in_hard_budget': False}
    if schedule_path.exists():
        if not options.resume or json.loads(schedule_path.read_text()) != frozen_schedule:
            raise ValueError('schedule exists or differs; use matching --resume')
    else:
        write_json(schedule_path, frozen_schedule)
    errors = []
    controller_start = time.process_time()
    with tempfile.TemporaryDirectory(prefix='.packages-', dir=campaign) as tmp:
        packages = {}
        for task in 'ABC':
            archive, = (ROOT / '训练集').glob(f'cpu-{task.lower()}-*.zip')
            if file_digest(archive) != protocol['inputs'][task]['archive_sha256']:
                raise ValueError(f'archive differs: {task}')
            packages[task] = Path(tmp) / task
            prepare(archive, packages[task], task)
        for task, group, seed in schedule:
            print(f'START {task} {group} seed={seed} budget={protocol["task_budgets_cpu_seconds"][task]}', flush=True)
            try:
                row = start_run(campaign, packages[task], task, group, seed, round_limit, resume=options.resume)
                if row['status'] == 'failed':
                    errors.append({'task': task, 'group': group, 'seed': seed, 'reason': 'worker_failed'})
                if row['budget_overrun_seconds'] > 0:
                    errors.append({'task': task, 'group': group, 'seed': seed, 'reason': 'kernel_budget_overrun',
                                   'overrun_seconds': row['budget_overrun_seconds']})
            except Exception as error:
                errors.append({'task': task, 'group': group, 'seed': seed,
                               'reason': f'{type(error).__name__}: {error}'})
                print(json.dumps({'error': errors[-1]}), flush=True)
                break
    result_name = 'smoke-result.json' if options.smoke else 'paired-result.json'
    output = {'runs': [{'task': t, 'group': g, 'seed': s} for t, g, s in schedule],
              'failures': errors, 'controller_cpu_seconds': time.process_time()-controller_start,
              'worker_cpu_budget_note': 'per-task worker process user+system CPU; controller and analysis excluded'}
    result_path = campaign / result_name
    if result_path.exists():
        prior = len(list(campaign.glob(result_path.stem + '-resume-*.json')))
        result_path = campaign / f'{result_path.stem}-resume-{prior + 1:04}.json'
    write_json(result_path, output)
    if errors:
        raise SystemExit(1)
    if options.smoke:
        rows = [json.loads((campaign / 'runs' / f'{t}-{g}-{s}' / 'summary.json').read_text()) for t, g, s in schedule]
        if any(row['status'] != 'complete' or row['rounds_completed'] != 1
               or row['budget_overrun_seconds'] > 0
               or abs(sum(row['phase_cpu_seconds'].values()) - row['worker_cpu_seconds']) > 1e-6 for row in rows):
            raise ValueError('smoke did not complete one round in every task/group')
        write_json(campaign / 'SMOKE_PASSED.json', {'runs': len(rows), 'seed': seeds[0], 'rounds': 1})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', required=True)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--run-dir', help=argparse.SUPPRESS)
    parser.add_argument('--attempt', help=argparse.SUPPRESS)
    parser.add_argument('--package', help=argparse.SUPPRESS)
    parser.add_argument('--used-before', type=float, default=0, help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.worker:
        worker(options)
    else:
        sys.path.insert(0, str(ROOT / 'src'))
        run_campaign(options)


if __name__ == '__main__':
    main()
