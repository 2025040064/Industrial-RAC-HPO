#!/usr/bin/env python3
"""Export the exact local B bearing guard violations, without treating units as independent runs."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from hard_budget import scan_commits


def violations(audit):
    if audit['gates']['bearing_gate'] is not False:
        return []
    parent = audit['parent_diagnostics']['groups']
    candidate = audit['candidate_diagnostics']['groups']
    if parent.keys() != candidate.keys():
        return [{'bearing':'<group_mismatch>','parent_rmse':None,'candidate_rmse':None,'delta':None}]
    return [{'bearing':key,'parent_rmse':parent[key]['rmse'],'candidate_rmse':candidate[key]['rmse'],
             'delta':candidate[key]['rmse']-parent[key]['rmse']} for key in sorted(parent)
            if candidate[key]['rmse'] > parent[key]['rmse']]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    protocol=json.loads((args.campaign/'protocol.json').read_text())
    schedule=json.loads((args.campaign/'paired-schedule.json').read_text())['runs']
    details=[]
    for item in schedule:
        if item['task']!='B':
            continue
        group,seed=item['group'],item['seed']
        run=args.campaign/'runs'/f'B-{group}-{seed}'
        for row in scan_commits(run,protocol['inputs']['B']['initial_sha256']):
            for data in violations(row['audit']):
                details.append({'group':group,'seed':seed,'round':row['round'],**data})
    counts=Counter((d['group'],d['seed'],d['bearing']) for d in details)
    summary=[{'group':g,'seed':s,'bearing':b,'rejected_candidates':n}
             for (g,s,b),n in sorted(counts.items())]
    for name,rows,fields in [('bearing-details.csv',details,['group','seed','round','bearing','parent_rmse','candidate_rmse','delta']),
                             ('bearing-summary.csv',summary,['group','seed','bearing','rejected_candidates'])]:
        with (args.output/name).open('x',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    print(args.output/'bearing-details.csv')


if __name__=='__main__':
    main()
