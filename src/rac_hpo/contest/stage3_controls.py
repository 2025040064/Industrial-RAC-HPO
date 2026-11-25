"""Validated, fail-closed contest controls and human-auditable decisions.

The accepted response contract is defined in official_submission/decision_contract.md.
Every rejection carries a machine-readable `reason` so platform fallbacks can be
classified without guessing at the raw model text.
"""
import json
import math
import re


SELECT_OPTIONS = {'rac', 'conservative'}
REASON_CODES = {'history', 'risk', 'constraint', 'cost', 'uncertainty', 'conservative', 'other'}
RISK_LEVELS = {'low', 'medium', 'high', 'unknown'}
ALLOWED_TERMINATORS = ('<|im_end|>',)
PARAMETER_KEYS = {'learning_rate', 'batch_size', 'epochs', 'strategy', 'reason',
                  'target_class', 'sampling_multiplier'}
_TERMINATOR_RE = re.compile(r'<\|[^|]+\|>')


def normalize_decision_text(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    for marker in ALLOWED_TERMINATORS:
        if text.endswith(marker):
            return text[:-len(marker)].strip()
    return text


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


def _invalid(reason):
    return {'action':'conservative_invalid_response','valid':False,'reason_codes':[],
            'risk':'unknown','format':'invalid','reason':reason}


def parse_decision(raw):
    if not isinstance(raw, str):
        return _invalid('not_json')
    text = normalize_decision_text(raw)
    if text is None:
        return _invalid('not_json')
    if text.casefold() in SELECT_OPTIONS:
        return {'action':text.casefold(),'valid':True,'reason_codes':[],
                'risk':'unknown','format':'legacy','reason':None}
    stripped = raw.strip()
    if (_TERMINATOR_RE.search(text)
            or any(stripped.count(marker) > 1 for marker in ALLOWED_TERMINATORS)):
        unknown = any(match.group(0) not in ALLOWED_TERMINATORS
                      for match in _TERMINATOR_RE.finditer(text))
        return _invalid('invalid_terminal_marker' if unknown else 'extra_content')
    if text.lstrip().startswith('```'):
        return _invalid('fenced_json')
    if text.startswith('{') and not text.rstrip().endswith('}'):
        return _invalid('truncated_json')
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return _invalid('not_json')
    if not isinstance(parsed, dict):
        return _invalid('not_json')
    keys = set(parsed)
    expected = {'selected_option', 'reason_codes', 'risk'}
    if 'selected_option' not in keys and keys & PARAMETER_KEYS:
        return _invalid('parameter_proposal_json')
    if not expected.issubset(keys):
        return _invalid('missing_fields')
    if keys != expected:
        return _invalid('unexpected_fields')
    option, reasons, risk = parsed['selected_option'], parsed['reason_codes'], parsed['risk']
    if not isinstance(option, str) or option.casefold() not in SELECT_OPTIONS:
        return _invalid('unknown_option')
    if not isinstance(risk, str) or risk not in RISK_LEVELS:
        return _invalid('invalid_risk')
    if (not isinstance(reasons, list) or len(reasons) > 5
            or any(not isinstance(v, str) or v not in REASON_CODES for v in reasons)
            or len(set(reasons)) != len(reasons)):
        return _invalid('invalid_reason_codes')
    return {'action':option.casefold(),'valid':True,'reason_codes':reasons,
            'risk':risk,'format':'json','reason':None}


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
