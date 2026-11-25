"""Conservative cross-parent compatibility checks; no weighted-TPE claims."""
import json
import math


def parent_distance(previous, current, weights, epsilon=1e-8):
    if (not isinstance(previous, dict) or not isinstance(current, dict) or not isinstance(weights, dict)
            or not current or previous.keys() != current.keys() or weights.keys() != current.keys()
            or not math.isfinite(epsilon) or epsilon <= 0):
        raise ValueError('Incompatible regime vectors')
    rows=[]
    for key in sorted(current):
        old, new, weight = previous[key], current[key], weights[key]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in (old,new,weight)) or old < 0 or new < 0 or weight < 0:
            raise ValueError('Invalid regime loss or weight')
        rows.append((old,new,weight))
    total=sum(w for _,_,w in rows)
    if total <= 0:
        raise ValueError('Invalid regime weights')
    return sum(w/total*abs(math.log((old+epsilon)/(new+epsilon))) for old,new,w in rows)


def filter_transfer(records,current,weights,round_index,*,max_distance,min_records=4,min_parents=2,
                    max_records=16,replay_evidence=None,parameter_space=None,require_complete=False,
                    allowed_strategies=None,weak_class=None):
    if (type(round_index) is not int or round_index < 1 or not math.isfinite(max_distance) or max_distance < 0
            or any(type(x) is not int or x < 1 for x in (min_records,min_parents,max_records))):
        raise ValueError('Invalid transfer gate configuration')
    accepted, excluded, seen = [], [], set()
    for row in records:
        number=row.get('round') if isinstance(row,dict) else None
        try:
            if type(number) is not int or not 1 <= number < round_index:
                raise ValueError('non_prior_round')
            parent=row['parent_sha256']
            if not isinstance(parent,str) or len(parent)!=64 or any(c not in '0123456789abcdef' for c in parent):
                raise ValueError('invalid_parent_digest')
            params = row['rac_params']
            if parameter_space is not None and (not isinstance(params, dict) or params.keys() != parameter_space.keys()
                    or any(isinstance(params[name], bool) or not isinstance(params[name], (int, float))
                           or not math.isfinite(params[name]) or not spec['low'] <= params[name] <= spec['high']
                           or (spec['type'] == 'int' and type(params[name]) is not int)
                           for name, spec in parameter_space.items())):
                raise ValueError('invalid_parameters')
            if require_complete:
                values = [row.get('parent_objective'),row.get('robust_objective'),row.get('training_seconds')]
                if (any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values)
                        or values[0] <= 0 or values[1] < 0 or values[2] <= 0
                        or not isinstance(row.get('configuration'),dict)):
                    raise ValueError('invalid_observation')
                config=row['configuration']
                if (allowed_strategies is not None and config.get('strategy') not in allowed_strategies
                        or config.get('strategy')=='class_focus' and config.get('target_class')!=weak_class):
                    raise ValueError('incompatible_strategy')
            distance=parent_distance(row['parent_regime_errors'],current,weights)
            if distance > max_distance:
                raise ValueError('parent_distance_exceeded')
            key=(parent,json.dumps(row['rac_params'],sort_keys=True,allow_nan=False,separators=(',',':')))
            if key in seen:
                raise ValueError('duplicate')
            seen.add(key)
            accepted.append((row,{'round':number,'parent_sha256':parent,'distance':distance}))
        except (KeyError,TypeError,ValueError,ArithmeticError) as error:
            reason=str(error) if str(error) in {'non_prior_round','invalid_parent_digest','invalid_parameters','invalid_observation','incompatible_strategy','parent_distance_exceeded','duplicate'} else 'incompatible_regimes_or_record'
            excluded.append({'round':number,'reason':reason})
    accepted=accepted[-max_records:]
    parents=len({item[1]['parent_sha256'] for item in accepted})
    audit={'eligible_count':len(accepted),'distinct_parent_count':parents,'eligible':[x[1] for x in accepted],
           'excluded':excluded,'max_distance':max_distance,'used':False,'reason':None}
    if len(accepted)<min_records:
        audit['reason']='insufficient_transfer_records'
    elif parents<min_parents:
        audit['reason']='insufficient_distinct_parents'
    elif replay_evidence is None:
        audit['reason']='missing_prior_replay_evidence'
    elif (not isinstance(replay_evidence,dict) or replay_evidence.get('valid') is not True
          or type(replay_evidence.get('evaluated_until')) is not int
          or not 0 < replay_evidence['evaluated_until'] < round_index
          or type(replay_evidence.get('pairs')) is not int or replay_evidence['pairs'] < 3
          or isinstance(replay_evidence.get('mean_gain'),bool)
          or not isinstance(replay_evidence.get('mean_gain'),(int,float))
          or not math.isfinite(replay_evidence['mean_gain']) or replay_evidence['mean_gain'] <= 0):
        audit['reason']='invalid_replay_evidence'
    else:
        audit.update(used=True,reason='prior_replay_passed')
    return ([row for row,_ in accepted] if audit['used'] else []),audit
