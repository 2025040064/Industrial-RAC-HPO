"""Recalculate gates and objective on the frozen prior paired SDK experiment."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from rac_hpo.contest.rac_policy import regime_metrics
from rac_hpo.domain.metrics import robust_metrics

root = Path(__file__).resolve().parent
campaign = Path('experiments/ablation/stage3-20261118-01/budget-comparison')
protocol_path = campaign / 'protocol.json'
protocol = json.loads(protocol_path.read_text())
schedule = json.loads((campaign / 'paired-result.json').read_text())['runs']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

rows, failures = [], []
for item in schedule:
    task, group, seed = item['task'], item['group'], item['seed']
    directory = campaign / 'runs' / f'{task}-{group}-{seed}'
    summary = json.loads((directory / 'summary.json').read_text())
    previous = protocol['inputs'][task]['initial_sha256']
    counts = Counter()
    result_paths = sorted(directory.glob('attempt-*/round-*/result.json'),
                          key=lambda p: json.loads(p.read_text())['round'])
    for index, path in enumerate(result_paths, 1):
        result = json.loads(path.read_text())
        audit = result['audit']
        state_audit = [json.loads(line) for line in (path.parent / 'state/selection-audit.jsonl').read_text().splitlines()][-1]
        gates = audit['gates']
        errors = []
        def check(value, label):
            if not value:
                errors.append(label)
        check(index == result['round'], 'round_order')
        check(audit == state_audit, 'state_audit')
        check(result['parent_sha256'] == audit['parent_sha256'] == previous, 'parent_chain')
        check(sha(path.parent / 'candidate.npz') == audit['candidate_sha256'] == result['candidate_sha256'], 'candidate_sha')
        config = audit['objective_config']
        for prefix in ('parent', 'candidate'):
            diagnostics = audit[f'{prefix}_diagnostics']
            computed = robust_metrics(regime_metrics(task, diagnostics, None), **config)['robust_objective']
            check(math.isclose(computed, audit[f'{prefix}_objective'], rel_tol=1e-10, abs_tol=1e-10),
                  f'{prefix}_objective')
        before, after = audit['parent_metric'], audit['candidate_metric']
        local_before, local_after = audit['local_parent_metric'], audit['local_candidate_metric']
        improves = after > before if audit['direction'] == 'higher' else after < before
        local_improves = local_after > local_before if audit['direction'] == 'higher' else local_after < local_before
        expected = {'parent_metric_matches': math.isclose(before, local_before, rel_tol=1e-7, abs_tol=1e-8),
                    'candidate_metric_matches': math.isclose(after, local_after, rel_tol=1e-7, abs_tol=1e-8),
                    'platform_primary_improved': improves, 'local_primary_improved': local_improves,
                    'objective_improved': audit['candidate_objective'] < audit['parent_objective']}
        expected['bearing_gate'] = None
        if improves and task == 'B' and 'groups' in audit['parent_diagnostics']:
            parent_groups = audit['parent_diagnostics']['groups']
            candidate_groups = audit['candidate_diagnostics']['groups']
            expected['bearing_gate'] = (parent_groups.keys() == candidate_groups.keys()
                and all(candidate_groups[key]['rmse'] <= parent_groups[key]['rmse'] for key in parent_groups))
        check(gates == expected, 'gates')
        accepted = all((expected['parent_metric_matches'], expected['candidate_metric_matches'], improves,
                        local_improves, expected['bearing_gate'] is not False, expected['objective_improved']))
        check(accepted == result['accepted'] == audit['accepted'], 'acceptance')
        if accepted:
            reason = 'Platform primary metric and local fixed robustness objective improved.'
        elif not expected['parent_metric_matches'] or not expected['candidate_metric_matches']:
            reason = 'Kept the platform parent because platform and local checkpoint metrics differ.'
        elif not improves:
            reason = 'Kept the platform parent because the platform primary metric did not improve.'
        elif not local_improves:
            reason = 'Kept the platform parent because the local checkpoint primary metric did not improve.'
        elif expected['bearing_gate'] is False:
            reason = 'Kept the platform parent because the local per-bearing RMSE guard failed.'
        else:
            reason = 'Kept the platform parent because the local fixed robustness objective did not improve.'
        check(audit['reason'] == reason, 'reason')
        previous = audit['candidate_sha256'] if accepted else audit['parent_sha256']
        check(audit['selected_sha256'] == result['selected_sha256'] == previous, 'selected_sha')
        check(audit['selected_artifact_id'] == (audit['candidate_artifact_id'] if accepted else audit['parent_artifact_id']), 'selected_id')
        check(audit['validation_sha256'] == protocol['inputs'][task]['validation_sha256'], 'validation_projection')
        counts['accepted' if accepted else 'rejected'] += 1
        counts['bearing_rejected'] += expected['bearing_gate'] is False
        counts['objective_rejected'] += not expected['objective_improved']
        if errors:
            failures.append({'task': task, 'group': group, 'round': index, 'errors': errors})
    check_count = len(result_paths) == summary['rounds_completed']
    if not check_count or previous != summary['final_sha256']:
        failures.append({'task': task, 'group': group, 'errors': ['summary_chain_or_round_count']})
    rows.append({'task': task, 'group': group, 'seed': seed, 'rounds': len(result_paths),
                 'budget_cpu_seconds': summary['budget_seconds'], 'used_cpu_seconds': summary['worker_cpu_seconds'],
                 'final_metrics': summary['final_metrics'], 'counts': dict(counts),
                 'surrogate_attempts': summary['surrogate_attempts'], 'surrogate_used': summary['surrogate_used'],
                 'transfer_tpe_rounds': summary['transfer_tpe_rounds'], 'final_sha256': summary['final_sha256']})

report = {'protocol_sha256': sha(protocol_path), 'source': 'previously completed paired run, not a new trial',
          'runs': rows, 'failures': failures, 'rounds_checked': sum(r['rounds'] for r in rows),
          'cost_modes': sorted({g['cost_mode'] for g in protocol['groups'].values()}),
          'limitations': ['one seed per task and group', 'local SDK model stub', 'hidden test not evaluated']}
with (root / 'history-verification-v2.json').open('x') as stream:
    json.dump(report, stream, indent=2, allow_nan=False)
print('runs', len(rows), 'rounds', report['rounds_checked'], 'failures', len(failures))
if failures:
    raise SystemExit(1)
