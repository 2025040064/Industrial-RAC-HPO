#!/usr/bin/env python3
"""Verify frozen sources, CPU ledgers, data projections, histories, and all committed NPZ metadata."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from hard_budget import attempt_usage, file_digest, scan_commits

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'workspace/contest_training/20261114/A'))
from baselines.model import Model


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('campaign', type=Path)
    args = p.parse_args()
    campaign = args.campaign.resolve()
    protocol = json.loads((campaign/'protocol.json').read_text())
    schedule = json.loads((campaign/'paired-schedule.json').read_text())['runs']
    errors, counts, groups_sha = [], {'runs':0, 'rounds':0, 'partial_rounds':0, 'future_observations':0}, {}
    for name, expected in protocol['source_sha256'].items():
        if file_digest(ROOT/name) != expected:
            errors.append(f'source changed: {name}')
    for lock_name in ('engine-lock.json','report-lock.json','bearing-analysis-lock.json'):
        lock=json.loads((campaign/lock_name).read_text())
        for name,expected in lock['source_sha256'].items():
            if file_digest(ROOT/name)!=expected:
                errors.append(f'{lock_name}: changed {name}')
    analysis_lock=json.loads((campaign/'analysis-lock.json').read_text())
    script='experiments/ablation/stage2_stats.py'
    if file_digest(ROOT/script)!=analysis_lock['source_sha256'][script]:
        errors.append('analysis code changed')
    addendum=json.loads((campaign/'analysis-test-addendum.json').read_text())
    if file_digest(ROOT/'tests/contest/test_stage2_stats.py')!=addendum['test_source_sha256']:
        errors.append('current analysis tests changed after addendum')
    if len(schedule)!=36:
        errors.append(f'expected 36 runs, got {len(schedule)}')
    for item in schedule:
        task,group,seed=item['task'],item['group'],item['seed']
        run=campaign/'runs'/f'{task}-{group}-{seed}'
        try:
            summary=json.loads((run/'summary.json').read_text())
            if file_digest(run/'initial.npz')!=protocol['inputs'][task]['initial_sha256']:
                raise ValueError('initial NPZ differs')
            ledger=attempt_usage(run)
            rows=scan_commits(run,protocol['inputs'][task]['initial_sha256'])
            if abs(ledger-summary['worker_cpu_seconds'])>1e-7 or ledger>protocol['task_budgets_cpu_seconds'][task]:
                raise ValueError('CPU ledger or hard budget mismatch')
            if abs(sum(summary['phase_cpu_seconds'].values())-ledger)>1e-6:
                raise ValueError('CPU phase accounting mismatch')
            if len(rows)!=summary['rounds_completed']:
                raise ValueError('committed round count mismatch')
            for part in summary['partial_rounds']:
                if part['start_cpu_seconds'] is None or part['cpu_seconds_until_worker_exit'] is None:
                    raise ValueError('partial round CPU unavailable')
                if (run/part['attempt']/part['round_directory']/'result.json').exists():
                    raise ValueError('partial round counted as committed')
            parent_model=Model.load(run/'initial.npz')
            for row in rows:
                audit=row['audit']; decision=audit['decision']; params=decision['final_params']
                state=json.loads((run/row['state_path']/'rac-round.json').read_text())
                context=state['context']; trace=audit['search_trace']; number=row['round']
                if (context['dataset']!=task or context['parent_sha256']!=row['parent_sha256']
                        or context['train_sha256']!=protocol['inputs'][task]['train_sha256']
                        or context['validation_sha256']!=protocol['inputs'][task]['validation_sha256']):
                    raise ValueError(f'round {number}: context differs')
                groups_sha.setdefault(task,set()).add(context['groups_sha256'])
                prior=audit['history_usage']['same_parent_valid_rounds']+audit['history_usage']['transfer_used_rounds']
                if any(type(n) is not int or n<1 or n>=number for n in prior):
                    counts['future_observations']+=1
                    raise ValueError(f'round {number}: future observation')
                if group in ('G0','G1') and audit['history_usage']['transfer_used_rounds']:
                    raise ValueError(f'round {number}: transfer used in disabled group')
                if trace['method']=='transfer_tpe' and trace['transfer_cost_weight'] != (0.05 if group=='G3' else 0):
                    raise ValueError(f'round {number}: wrong cost weight')
                child=Model.load(run/row['candidate_path'])
                if (decision['model_response']!='RAC' or decision['recommended_params']!=params
                        or child.meta['learning_rate']!=params['learning_rate']
                        or child.meta['batch_size']!=params['batch_size']
                        or child.meta['epochs']!=parent_model.meta['epochs']+params['epochs']
                        or child.meta['seed']!=protocol['inputs'][task]['checkpoint_training_seed']):
                    raise ValueError(f'round {number}: actual training parameters differ')
                if row['peak_rss_bytes']<=0 or row['cumulative_cpu_seconds']>protocol['task_budgets_cpu_seconds'][task]:
                    raise ValueError(f'round {number}: memory or cumulative CPU invalid')
                if row['accepted']:
                    parent_model=child
            counts['runs']+=1; counts['rounds']+=len(rows); counts['partial_rounds']+=len(summary['partial_rounds'])
        except Exception as error:
            errors.append(f'{task}-{group}-{seed}: {type(error).__name__}: {error}')
    for task, values in groups_sha.items():
        if len(values)!=1:
            errors.append(f'{task}: source metadata projection differs across runs')
    result={'status':'passed' if not errors else 'failed','counts':counts,'errors':errors,
            'groups_sha256':{task:sorted(values) for task,values in groups_sha.items()},
            'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (campaign/'integrity-audit.json').open('x',encoding='utf-8') as f:
        json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps(result,ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__=='__main__':
    main()
