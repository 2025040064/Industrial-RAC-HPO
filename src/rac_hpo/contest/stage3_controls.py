"""Validated, fail-closed contest controls and human-auditable decisions."""
import json
import math


REASON_CODES = {'history', 'risk', 'constraint', 'cost', 'uncertainty', 'conservative', 'other'}


def controls(env):
    transfer=env.get('RAC_TRANSFER_MODE')
    if transfer is None:
        transfer='legacy' if env.get('RAC_TRANSFER_HISTORY') == '1' else 'off'
    result={'transfer_mode':transfer,'surrogate_mode':env.get('RAC_SURROGATE_MODE','shadow'),
            'cost_mode':env.get('RAC_COST_MODE','off'),'bearing_mode':env.get('RAC_BEARING_FEASIBILITY','off')}
    allowed={'transfer_mode':{'off','legacy','gated'},'surrogate_mode':{'off','shadow','active'},
             'cost_mode':{'off','transfer','acquisition','both'},'bearing_mode':{'off','shadow','active'}}
    for key, value in result.items():
        if value not in allowed[key]: raise ValueError(f'Invalid {key}')
    return result


def parse_decision(raw):
    invalid={'action':'conservative_invalid_response','valid':False,'reason_codes':[],'risk':'unknown','format':'invalid'}
    if not isinstance(raw,str): return invalid
    text=raw.strip()
    if text.casefold() in {'rac','conservative'}:
        return {'action':text.casefold(),'valid':True,'reason_codes':[],'risk':'unknown','format':'legacy'}
    try: parsed=json.loads(text)
    except (TypeError,ValueError): return invalid
    if not isinstance(parsed,dict) or set(parsed)!={'selected_option','reason_codes','risk'}: return invalid
    option, reasons, risk = parsed['selected_option'],parsed['reason_codes'],parsed['risk']
    if (not isinstance(option,str) or option.casefold() not in {'rac','conservative'}
            or not isinstance(reasons,list) or len(reasons)>5 or any(not isinstance(v,str) or v not in REASON_CODES for v in reasons)
            or len(set(reasons))!=len(reasons) or not isinstance(risk,str)
            or risk not in {'low','medium','high','unknown'}):
        return invalid
    return {'action':option.casefold(),'valid':True,'reason_codes':reasons,'risk':risk,'format':'json'}


def bearing_deltas(parent,candidate):
    p=parent.get('groups') if isinstance(parent,dict) else None
    c=candidate.get('groups') if isinstance(candidate,dict) else None
    if not isinstance(p,dict) or not p or not isinstance(c,dict) or p.keys()!=c.keys():
        return {'feasible':None,'delta_rmse':{},'reason':'missing_or_incompatible_bearings'}
    result={}
    try:
        for key in sorted(p):
            a,b=p[key]['rmse'],c[key]['rmse']
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in (a,b)):
                raise ValueError('invalid rmse')
            result[key]=b-a
    except (KeyError,TypeError,ValueError):
        return {'feasible':None,'delta_rmse':{},'reason':'invalid_bearing_metrics'}
    return {'feasible':all(v<=0 for v in result.values()),'delta_rmse':result,'reason':'measured'}
