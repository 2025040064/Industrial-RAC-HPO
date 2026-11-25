"""Uncalibrated nearest-prior bearing feasibility, strictly shadow-only."""
import math


def _vector(params, parent, space, keys):
    if not isinstance(params,dict) or params.keys()!=space.keys() or not isinstance(parent,dict) or set(parent)!=set(keys):
        raise ValueError('incompatible_features')
    values=[]
    for name,spec in space.items():
        v=params[name]; low=spec['low']; high=spec['high']
        if (isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v)
                or not low<=v<=high or spec['type']=='int' and type(v) is not int):
            raise ValueError('invalid_parameters')
        if spec.get('log'): v,low,high=math.log(v),math.log(low),math.log(high)
        values.append(0.0 if high==low else (v-low)/(high-low))
    for key in keys:
        v=parent[key]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:
            raise ValueError('invalid_parent_bearing')
        values.append(math.log(v+1e-8))
    return values


def _nearest(past,target):
    def distance(item):
        return sum((a-b)**2 for a,b in zip(item['features'],target))
    return min(past,key=distance)


def assess_feasibility(records,parent,params,space,round_index):
    result={'mode':'shadow','training_candidate_filtered':False,'predicted_feasible':None,
            'probability':None,'history_count':0,'excluded':[],'forward_splits':[],
            'forward_validation':{'passed':False,'reason':'insufficient_history'},'reason':'insufficient_history'}
    if not isinstance(parent,dict) or not parent or type(round_index) is not int or round_index<1:
        result['reason']='missing_parent_bearings'; return result
    keys=sorted(parent)
    try: target=_vector(params,parent,space,keys)
    except (TypeError,ValueError): result['reason']='invalid_current_features'; return result
    valid=[]; seen=set()
    for row in records:
        n=row.get('round') if isinstance(row,dict) else None
        try:
            if type(n) is not int or not 1<=n<round_index: raise ValueError('non_prior_round')
            if n in seen: raise ValueError('duplicate_round')
            comp=row['bearing_comparison']
            if not isinstance(comp,dict) or type(comp.get('feasible')) is not bool: raise ValueError('missing_label')
            features=_vector(row['rac_params'],row['parent_bearing_rmse'],space,keys)
            seen.add(n); valid.append({'round':n,'features':features,'label':comp['feasible']})
        except (KeyError,TypeError,ValueError,ArithmeticError) as exc:
            result['excluded'].append({'round':n,'reason':str(exc)})
    valid.sort(key=lambda x:x['round']);result['history_count']=len(valid)
    if len(valid)<8: return result
    if len({r['label'] for r in valid})<2:
        result.update(reason='single_label_history',forward_validation={'passed':False,'reason':'single_label_history'})
        return result
    predicted=[]; truth=[]; naive=[]
    for i in range(5,len(valid)):
        past=valid[:i]
        if len({r['label'] for r in past})<2: continue
        neighbor=_nearest(past,valid[i]['features'])
        predicted.append(neighbor['label']);truth.append(valid[i]['label'])
        naive.append(sum(r['label'] for r in past)>len(past)/2)
        result['forward_splits'].append({'training_last_round':past[-1]['round'],'held_out_round':valid[i]['round'],
                                         'nearest_round':neighbor['round']})
    quality={'passed':False,'reason':'insufficient_forward_labels','forward_splits':result['forward_splits']}
    if len(truth)>=3 and len(set(truth))==2:
        accuracy=sum(a==b for a,b in zip(predicted,truth))/len(truth)
        baseline=sum(a==b for a,b in zip(naive,truth))/len(truth)
        quality.update(passed=accuracy>baseline,reason='passed' if accuracy>baseline else 'not_better_than_majority',
                       accuracy=accuracy,majority_accuracy=baseline)
    nearest=_nearest(valid,target)
    result.update(predicted_feasible=nearest['label'],nearest_round=nearest['round'],
                  reason='uncalibrated_shadow_only',forward_validation=quality)
    return result
