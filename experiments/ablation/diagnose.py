#!/usr/bin/env python3
"""Inspect recorded histories and counterfactual cost rankings for a finished campaign."""
import argparse
from collections import Counter
import itertools
import json
import math
from pathlib import Path


def inspect(run_dir):
    rows = [json.loads(p.read_text()) for p in sorted(run_dir.glob('round-*/result.json'))]
    counts = Counter()
    changed = []
    for row in rows:
        audit = row['audit']
        trace = audit['search_trace']
        usage = audit['history_usage']
        counts['same_parent_observations_used'] += len(usage['same_parent_used_rounds'])
        counts['transfer_observations_used'] += len(usage['transfer_used_rounds'])
        counts['tpe_model_ready_rounds'] += trace.get('tpe_model_ready') is True
        counts['tpe_random_startup_rounds'] += trace.get('tpe_model_ready') is False
        counts['surrogate_attempts'] += row['surrogate_attempted']
        counts['surrogate_used'] += row['surrogate_used']
        counts['recommendation_changed'] += audit['decision']['recommended_params'] != audit['decision']['final_params']
        counts['rejected'] += not audit['accepted']
        counts['accepted'] += audit['accepted']
        if trace['method'] != 'transfer_tpe' or trace['transfer_cost_weight'] == 0:
            continue
        state = json.loads((run_dir / f"round-{row['round']:02}" / 'state/rac-round.json').read_text())
        archive = {record['round']: record for record in state['archive']}
        numbers = usage['transfer_used_rounds'] + trace.get('history_rounds', [])
        values = []
        for number in numbers:
            record = archive[number]
            raw = record['robust_objective'] / record['parent_objective']
            log_ratio = math.log(record['training_seconds']) - math.log(trace['transfer_cost_median_seconds'])
            penalized = raw + trace['transfer_cost_weight'] * max(-2.0, min(2.0, log_ratio))
            values.append((number, raw, penalized))
        inversions = sum((a[1]-b[1])*(a[2]-b[2]) < 0 for a, b in itertools.combinations(values, 2))
        ties_broken = sum(a[1] == b[1] and a[2] != b[2] for a, b in itertools.combinations(values, 2))
        if inversions or ties_broken:
            changed.append({'round': row['round'], 'strict_rank_inversions': inversions,
                            'ties_broken': ties_broken, 'observation_rounds': numbers})
    return {'counts': dict(counts), 'cost_ranking_changes': changed}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('campaign', type=Path)
    args = p.parse_args()
    results = {directory.name: inspect(directory) for directory in sorted(args.campaign.iterdir())
               if directory.is_dir() and (directory / 'summary.json').exists()}
    with (args.campaign / 'history-audit.json').open('x', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, allow_nan=False, indent=2)
        f.write('\n')
    print(args.campaign / 'history-audit.json')


if __name__ == '__main__':
    main()
