#!/usr/bin/env python3
"""Produce append-only, paired hard-budget CSV/JSON summaries from committed rounds."""
import argparse
import csv
import itertools
import json
import math
from pathlib import Path
import statistics

from hard_budget import scan_commits


def descriptive(values):
    return {'n': len(values), 'mean': statistics.mean(values) if values else None,
            'sample_std': statistics.stdev(values) if len(values) > 1 else None,
            'median': statistics.median(values) if values else None,
            'min': min(values) if values else None, 'max': max(values) if values else None}


def cost_inversions(row, run_dir):
    trace = row['audit']['search_trace']
    if trace['method'] != 'transfer_tpe' or trace['transfer_cost_weight'] <= 0:
        return 0
    state = json.loads((run_dir / row['state_path'] / 'rac-round.json').read_text())
    archive = {record['round']: record for record in state['archive']}
    rounds = row['audit']['history_usage']['transfer_used_rounds'] + trace.get('history_rounds', [])
    observations = []
    for number in rounds:
        record = archive[number]
        objective = record['robust_objective'] / record['parent_objective']
        ratio = math.log(record['training_seconds']) - math.log(trace['transfer_cost_median_seconds'])
        penalized = objective + trace['transfer_cost_weight'] * max(-2.0, min(2.0, ratio))
        observations.append((objective, penalized))
    return sum((a[0]-b[0])*(a[1]-b[1]) < 0 for a,b in itertools.combinations(observations, 2))


def write_csv(path, rows, fields):
    with path.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('--output', required=True, type=Path, help='new result directory inside campaign')
    args = parser.parse_args()
    campaign, output = args.campaign.resolve(), args.output.resolve()
    if not output.is_relative_to(campaign):
        parser.error('output must be inside campaign')
    output.mkdir(exist_ok=False)
    protocol = json.loads((campaign / 'protocol.json').read_text())
    schedule = json.loads((campaign / 'paired-schedule.json').read_text())['runs']
    result_paths = sorted(campaign.glob('paired-result-resume-*.json'))
    result = json.loads((result_paths[-1] if result_paths else campaign / 'paired-result.json').read_text())
    if result['failures']:
        raise ValueError('campaign contains failed or invalid runs; inspect paired-result.json')
    runs, trajectory, subsets, anomaly = [], [], [], []
    groups = ('G0', 'G1', 'G2', 'G3')
    for item in schedule:
        task, group, seed = item['task'], item['group'], item['seed']
        run_dir = campaign / 'runs' / f'{task}-{group}-{seed}'
        summary = json.loads((run_dir / 'summary.json').read_text())
        rows = scan_commits(run_dir, protocol['inputs'][task]['initial_sha256'])
        if len(rows) != summary['rounds_completed'] or summary['budget_overrun_seconds'] > 0:
            raise ValueError(f'invalid budget or committed chain: {run_dir}')
        if abs(sum(summary['phase_cpu_seconds'].values()) - summary['worker_cpu_seconds']) > 1e-6:
            raise ValueError(f'CPU phase accounting mismatch: {run_dir}')
        metric = 'macro_f1' if task == 'A' else 'rmse'
        improvement = ((summary['final_metrics'][metric] - summary['initial_metrics'][metric]) if task == 'A'
                       else (summary['initial_metrics'][metric] - summary['final_metrics'][metric]))
        inversion_count = sum(cost_inversions(row, run_dir) for row in rows)
        bearing_rejects = sum(row['audit']['gates']['bearing_gate'] is False for row in rows)
        failures = len(list(run_dir.glob('attempt-*/round-*/failure.json')))
        selected_path = next((row['candidate_path'] for row in reversed(rows) if row['accepted']), 'initial.npz')
        run = {'task': task, 'group': group, 'seed': seed, 'status': summary['status'],
               'budget_seconds': summary['budget_seconds'], 'cpu_seconds': summary['worker_cpu_seconds'],
               'user_cpu_seconds': summary['user_cpu_seconds'], 'system_cpu_seconds': summary['system_cpu_seconds'],
               'rounds_completed': len(rows), 'partial_rounds': summary['partial_round_attempts'],
               'accepted': summary['accepted'], 'rejected': summary['rejected'],
               'acceptance_rate': summary['accepted'] / len(rows) if rows else None,
               'failed_rounds': failures, 'failed_attempts': summary['failed_attempts'],
               'failure_rate': failures / (len(rows) + failures) if len(rows) + failures else None,
               'bearing_guard_rejects': bearing_rejects, 'surrogate_attempts': summary['surrogate_attempts'],
               'surrogate_used': summary['surrogate_used'], 'transfer_tpe_rounds': summary['transfer_tpe_rounds'],
               'cost_ranking_inversions': inversion_count, 'peak_rss_bytes': summary['peak_rss_bytes'],
               'final_sha256': summary['final_sha256'], 'final_checkpoint_path': str(run_dir / selected_path),
               'macro_f1': summary['final_metrics'].get('macro_f1'),
               'accuracy': summary['final_metrics'].get('accuracy'), 'rmse': summary['final_metrics'].get('rmse'),
               'mae': summary['final_metrics'].get('mae'), 'nasa_score': None,
               'improvement_per_cpu_second': improvement / summary['worker_cpu_seconds'] if summary['worker_cpu_seconds'] else None,
               **{f'cpu_{name}': value for name, value in summary['phase_cpu_seconds'].items()}}
        runs.append(run)
        if summary['partial_rounds'] or failures or summary['budget_overrun_seconds']:
            anomaly.append({'task': task, 'group': group, 'seed': seed, 'status': summary['status'],
                            'partial_rounds': summary['partial_rounds'], 'failures': failures,
                            'budget_overrun_seconds': summary['budget_overrun_seconds']})
        baseline = json.loads((run_dir / 'baseline.json').read_text())
        trajectory.append({'task': task, 'group': group, 'seed': seed, 'round': 0,
                           'cpu_seconds': baseline['cpu_at_measurement'], 'round_cpu_seconds': None,
                           'budget_seconds': summary['budget_seconds'], 'peak_rss_bytes': None,
                           'parent_sha256': summary['initial_sha256'], 'candidate_sha256': None,
                           'selected_sha256': summary['initial_sha256'], 'accepted': None,
                           'selected_metrics_json': json.dumps(baseline['metrics'], sort_keys=True),
                           'candidate_metrics_json': None, 'recommended_params_json': None, 'actual_params_json': None,
                           'strategy': None, 'parent_j': None, 'candidate_j': None, 'gates_json': None,
                           'reason': 'initial checkpoint', 'history_json': None, 'search_method': None,
                           'tpe_model_ready': None, 'surrogate_used': None, 'cost_ranking_inversions': 0,
                           'status': 'initial'})
        for row in rows:
            a, trace = row['audit'], row['audit']['search_trace']
            trajectory.append({'task': task, 'group': group, 'seed': seed, 'round': row['round'],
                               'cpu_seconds': row['cumulative_cpu_seconds'], 'round_cpu_seconds': row['round_cpu_seconds'],
                               'budget_seconds': row['budget_seconds'], 'peak_rss_bytes': row['peak_rss_bytes'],
                               'parent_sha256': row['parent_sha256'], 'candidate_sha256': row['candidate_sha256'],
                               'selected_sha256': row['selected_sha256'], 'accepted': row['accepted'],
                               'selected_metrics_json': json.dumps(row['selected_metrics'], sort_keys=True),
                               'candidate_metrics_json': json.dumps(row['candidate_metrics'], sort_keys=True),
                               'recommended_params_json': json.dumps(a['decision']['recommended_params'], sort_keys=True),
                               'actual_params_json': json.dumps(a['decision']['final_params'], sort_keys=True),
                               'strategy': a['decision']['training_proposal']['strategy'],
                               'parent_j': a['parent_objective'], 'candidate_j': a['candidate_objective'],
                               'gates_json': json.dumps(a['gates'], sort_keys=True), 'reason': a['reason'],
                               'history_json': json.dumps(a['history_usage'], sort_keys=True),
                               'search_method': trace['method'], 'tpe_model_ready': trace.get('tpe_model_ready'),
                               'surrogate_used': row['surrogate_used'],
                               'cost_ranking_inversions': cost_inversions(row, run_dir), 'status': row['status']})
        for name, vals in (summary['final_subsets'] or {}).items():
            subsets.append({'task': task, 'group': group, 'seed': seed, 'subset': name, **vals})
    paired, aggregates, pair_aggregates = [], [], []
    for task in 'ABC':
        metric_names = ('macro_f1','accuracy') if task == 'A' else ('rmse','mae')
        fields = (*metric_names, 'cpu_seconds', 'rounds_completed', 'acceptance_rate',
                  'failure_rate', 'improvement_per_cpu_second', 'surrogate_used', 'transfer_tpe_rounds',
                  'cost_ranking_inversions', 'bearing_guard_rejects')
        for group in groups:
            for field in fields:
                values = [row[field] for row in runs if row['task']==task and row['group']==group and row[field] is not None]
                aggregates.append({'task':task,'group':group,'metric':field, **descriptive(values)})
        for left,right in (('G1','G0'),('G2','G1'),('G3','G2')):
            for seed in protocol['search_seeds']:
                a = next(row for row in runs if (row['task'],row['group'],row['seed'])==(task,left,seed))
                b = next(row for row in runs if (row['task'],row['group'],row['seed'])==(task,right,seed))
                for field in fields:
                    if a[field] is not None and b[field] is not None:
                        paired.append({'task':task,'comparison':f'{left}-{right}','seed':seed,'metric':field,
                                       'left':a[field],'right':b[field],'difference':a[field]-b[field]})
            for field in fields:
                values=[row['difference'] for row in paired if row['task']==task and row['comparison']==f'{left}-{right}' and row['metric']==field]
                pair_aggregates.append({'task':task,'comparison':f'{left}-{right}','metric':field,**descriptive(values)})
    subset_aggregates, subset_paired = [], []
    for name in sorted({row['subset'] for row in subsets}):
        for group in groups:
            for metric in ('mae', 'rmse'):
                values = [row[metric] for row in subsets if row['subset'] == name and row['group'] == group]
                subset_aggregates.append({'subset': name, 'group': group, 'metric': metric, **descriptive(values)})
        for left, right in (('G1', 'G0'), ('G2', 'G1'), ('G3', 'G2')):
            for metric in ('mae', 'rmse'):
                vals = []
                for seed in protocol['search_seeds']:
                    a = [row[metric] for row in subsets if row['subset'] == name and row['group'] == left and row['seed'] == seed]
                    b = [row[metric] for row in subsets if row['subset'] == name and row['group'] == right and row['seed'] == seed]
                    if len(a) == len(b) == 1:
                        vals.append(a[0] - b[0])
                subset_paired.append({'subset': name, 'comparison': f'{left}-{right}', 'metric': metric,
                                      **descriptive(vals)})
    write_csv(output/'runs.csv',runs,list(runs[0]))
    write_csv(output/'trajectory.csv',trajectory,list(trajectory[0]))
    write_csv(output/'paired.csv',paired,list(paired[0]))
    write_csv(output/'aggregate.csv',aggregates,list(aggregates[0]))
    write_csv(output/'paired-statistics.csv',pair_aggregates,list(pair_aggregates[0]))
    write_csv(output/'subsets.csv',subsets,['task','group','seed','subset','samples','mae','rmse'])
    write_csv(output/'subset-statistics.csv',subset_aggregates,['subset','group','metric','n','mean','sample_std','median','min','max'])
    write_csv(output/'subset-paired-statistics.csv',subset_paired,['subset','comparison','metric','n','mean','sample_std','median','min','max'])
    with (output/'anomalies.json').open('x') as f:
        json.dump(anomaly, f, indent=2, allow_nan=False)
        f.write('\n')
    with (output/'analysis.json').open('x') as f:
        json.dump({'runs':runs,'paired':paired,'aggregate':aggregates,'paired_statistics':pair_aggregates,
                   'subsets':subsets,'subset_statistics':subset_aggregates,'subset_paired_statistics':subset_paired,
                   'anomalies':anomaly,'controller_cpu_seconds':result['controller_cpu_seconds'],
                   'efficiency_definition':'positive primary improvement from initial checkpoint divided by worker CPU seconds',
                   'nasa_score':None},f,indent=2,allow_nan=False)
        f.write('\n')
    print(output)


if __name__ == '__main__':
    main()
