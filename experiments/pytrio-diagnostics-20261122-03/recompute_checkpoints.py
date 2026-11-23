"""Recompute selected historical checkpoints on their public validation projection."""
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile

from rac_hpo.contest.packages import prepare
from threadpoolctl import threadpool_limits

root = Path(__file__).resolve().parent
campaign = Path('experiments/ablation/stage3-20261118-01/budget-comparison')
protocol = json.loads((campaign / 'protocol.json').read_text())
targets = {'A': {3}, 'B': {4, 5, 8}, 'C': {4, 7}}
results, failures = [], []
with tempfile.TemporaryDirectory(prefix='checkpoint-audit-', dir='.cache') as temp:
    packages = {}
    for task in targets:
        archive, = Path('训练集').glob(f'cpu-{task.lower()}-*.zip')
        packages[task] = Path(temp) / task
        prepare(archive, packages[task], task)
    sys.path.insert(0, str(packages['A']))
    from baselines.data import read_dataset
    from baselines.model import Model
    from baselines.train import metrics
    with threadpool_limits(limits=1):
        for task, selected in targets.items():
            directory = campaign / 'runs' / f'{task}-R3-4041'
            parent = directory / 'initial.npz'
            dataset_task = 'classification' if task == 'A' else 'regression'
            model = Model.load(parent)
            validation = read_dataset(packages[task] / 'public/validation.jsonl', dataset_task,
                                      model.meta['classes'], model.meta['paths'])
            if validation['sha256'] != protocol['inputs'][task]['validation_sha256']:
                raise ValueError(f'Public validation projection changed: {task}')
            for number in range(1, max(selected) + 1):
                folder = directory / 'attempt-0001' / f'round-{number:02}'
                result = json.loads((folder / 'result.json').read_text())
                candidate = folder / 'candidate.npz'
                if number in selected:
                    audit = result['audit']
                    key = audit['metric']
                    computed_parent = metrics(Model.load(parent), validation)[key]
                    computed_candidate = metrics(Model.load(candidate), validation)[key]
                    parent_sha = hashlib.sha256(parent.read_bytes()).hexdigest()
                    candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
                    checks = {
                        'parent_sha': parent_sha == audit['parent_sha256'],
                        'candidate_sha': candidate_sha == audit['candidate_sha256'],
                        'parent_metric': math.isclose(computed_parent, audit['local_parent_metric'], rel_tol=1e-7, abs_tol=1e-8),
                        'candidate_metric': math.isclose(computed_candidate, audit['local_candidate_metric'], rel_tol=1e-7, abs_tol=1e-8),
                    }
                    results.append({'task': task, 'round': number, 'group': 'R3', 'metric': key,
                                    'parent_value': computed_parent, 'candidate_value': computed_candidate,
                                    'accepted': audit['accepted'], 'checks': checks})
                    if not all(checks.values()):
                        failures.append({'task': task, 'round': number, 'checks': checks})
                if result['accepted']:
                    parent = candidate
report = {'source': 'historical local SDK experiment, not platform screenshots',
          'rows': results, 'failures': failures}
with (root / 'recomputed-checkpoints.json').open('x') as stream:
    json.dump(report, stream, indent=2, allow_nan=False)
print('checkpoints', len(results) * 2, 'rounds', len(results), 'failures', len(failures))
if failures:
    raise SystemExit(1)
