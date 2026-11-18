#!/usr/bin/env python3
"""Aggregate paired ablation runs without modifying their immutable results."""
import argparse
import json
from pathlib import Path
import statistics


def stats(values):
    return {'values': values, 'mean': statistics.mean(values) if values else None,
            'sample_std': statistics.stdev(values) if len(values) > 1 else None}


def analyze(runs, equal_cpu):
    output = {'fixed_rounds': {}, 'paired_differences': {}, 'equal_cpu_prefix': equal_cpu,
              'equal_cpu_aggregate': {}, 'equal_cpu_paired_differences': {}}
    for task in 'ABC':
        task_prefixes = {int(key.split('-')[-1]): value for key, value in equal_cpu.items()
                         if key.startswith(f'{task}-')}
        if not task_prefixes:
            continue
        names = ('macro_f1', 'accuracy') if task == 'A' else ('rmse', 'mae')
        output['equal_cpu_aggregate'][task] = {}
        output['equal_cpu_paired_differences'][task] = {}
        for group in ('G0', 'G1', 'G2', 'G3'):
            seeds = sorted(seed for seed, row in task_prefixes.items() if group in row['groups'])
            output['equal_cpu_aggregate'][task][group] = {'seeds': seeds, 'metrics': {
                name: stats([task_prefixes[seed]['groups'][group]['metrics'][name] for seed in seeds])
                for name in names}}
        for left, right in (('G1', 'G0'), ('G2', 'G1'), ('G3', 'G2')):
            seeds = sorted(seed for seed, row in task_prefixes.items()
                           if left in row['groups'] and right in row['groups'])
            output['equal_cpu_paired_differences'][task][f'{left}-{right}'] = {
                'seeds': seeds, 'metrics': {name: stats([
                    task_prefixes[seed]['groups'][left]['metrics'][name]
                    - task_prefixes[seed]['groups'][right]['metrics'][name] for seed in seeds]) for name in names}}
    for task in 'ABC':
        subset = [row for row in runs if row['task'] == task and row['status'] == 'complete']
        if not subset:
            continue
        names = ('macro_f1', 'accuracy') if task == 'A' else ('rmse', 'mae')
        output['fixed_rounds'][task] = {}
        output['paired_differences'][task] = {}
        for group in ('G0', 'G1', 'G2', 'G3'):
            rows = sorted((row for row in subset if row['group'] == group), key=lambda row: row['seed'])
            output['fixed_rounds'][task][group] = {
                'seeds': [row['seed'] for row in rows],
                'metrics': {name: stats([row['final_metrics'][name] for row in rows]) for name in names},
                'campaign_cpu_seconds': stats([row['campaign_cpu_seconds'] for row in rows]),
                'training_seconds': stats([row['training_seconds'] for row in rows]),
                'peak_rss_bytes': stats([row['peak_rss_bytes'] for row in rows]),
                'surrogate_used': [row['surrogate_used'] for row in rows],
                'surrogate_attempts': [row['surrogate_attempts'] for row in rows],
                'nasa_score': None if task == 'C' else 'not_applicable'}
        for left, right in (('G1', 'G0'), ('G2', 'G1'), ('G3', 'G2')):
            a = {row['seed']: row for row in subset if row['group'] == left}
            b = {row['seed']: row for row in subset if row['group'] == right}
            seeds = sorted(a.keys() & b.keys())
            output['paired_differences'][task][f'{left}-{right}'] = {
                'seeds': seeds,
                'metrics': {name: stats([a[seed]['final_metrics'][name] - b[seed]['final_metrics'][name]
                                         for seed in seeds]) for name in names},
                'campaign_cpu_seconds': stats([a[seed]['campaign_cpu_seconds'] - b[seed]['campaign_cpu_seconds']
                                               for seed in seeds])}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('--output-name', default='analysis.json', help='new output filename inside campaign')
    args = parser.parse_args()
    raw = json.loads((args.campaign / 'summary.json').read_text())
    result = analyze(raw['runs'], raw['equal_cpu_prefix'])
    if Path(args.output_name).name != args.output_name:
        parser.error('output name must be a single filename')
    dest = args.campaign / args.output_name
    with dest.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')
    print(dest)


if __name__ == '__main__':
    main()
