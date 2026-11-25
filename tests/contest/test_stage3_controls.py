import json
import unittest
from rac_hpo.contest.stage3_controls import controls, parse_decision, bearing_deltas


class Stage3ControlsTest(unittest.TestCase):
    def test_known_terminal_marker_is_accepted_without_accepting_extra_content(self):
        for raw, expected in (
            ('RAC<|im_end|>', 'rac'),
            (' conservative<|im_end|>  ', 'conservative'),
            ('{"selected_option":"RAC","reason_codes":["history"],"risk":"low"}<|im_end|>', 'rac'),
        ):
            with self.subTest(raw=raw):
                result = parse_decision(raw)
                self.assertTrue(result['valid'])
                self.assertEqual(result['action'], expected)
        for raw in ('RAC<|unknown|>', 'RAC<|im_end|>extra', 'RAC<|im_end|><|im_end|>',
                    'RAC and conservative<|im_end|>',
                    '{"selected_option":"RAC"}<|im_end|>',
                    '{"selected_option":"RAC","reason_codes":[],"risk":"low","learning_rate":0.1}<|im_end|>'):
            with self.subTest(raw=raw):
                result = parse_decision(raw)
                self.assertFalse(result['valid'])
                self.assertEqual(result['action'], 'conservative_invalid_response')

    def test_defaults_are_safe_and_invalid_switches_fail(self):
        c=controls({})
        self.assertEqual((c['transfer_mode'],c['surrogate_mode'],c['cost_mode'],c['bearing_mode']),
                         ('off','shadow','off','off'))
        with self.assertRaises(ValueError): controls({'RAC_COST_MODE':'unknown'})
        self.assertEqual(controls({'RAC_TRANSFER_HISTORY':'1'})['transfer_mode'],'legacy')
    def test_structured_reply_selects_only_legal_option(self):
        result=parse_decision('{"selected_option":"RAC","reason_codes":["history"],"risk":"low"}')
        self.assertTrue(result['valid']); self.assertEqual(result['action'],'rac')
        for raw in ('{"selected_option":"other","reason_codes":[],"risk":"low"}',
                    '{"selected_option":"rac","reason_codes":[],"risk":"bad"}',
                    '{"selected_option":"rac","reason_codes":[],"risk":{}}',
                    '{"selected_option":"rac","reason_codes":[],"risk":"low","learning_rate":99}',
                    'bad'):
            result=parse_decision(raw)
            self.assertFalse(result['valid']); self.assertEqual(result['action'],'conservative_invalid_response')
        self.assertEqual(parse_decision(' RAC ')['action'],'rac')
    def test_bearing_deltas_use_parent_and_never_fabricate_missing(self):
        p={'groups':{'one':{'rmse':2.},'two':{'rmse':3.}}}
        c={'groups':{'one':{'rmse':2.5},'two':{'rmse':2.}}}
        x=bearing_deltas(p,c)
        self.assertFalse(x['feasible']); self.assertEqual(x['delta_rmse'],{'one':.5,'two':-1.})
        self.assertIsNone(bearing_deltas({},c)['feasible'])


class DecisionContractTest(unittest.TestCase):
    """H1/H2/H3 boundary cases: every rejection must carry a machine-readable reason."""

    def test_contract_constants_are_defined(self):
        from rac_hpo.contest.stage3_controls import (
            SELECT_OPTIONS, REASON_CODES, RISK_LEVELS, ALLOWED_TERMINATORS)
        self.assertEqual(SELECT_OPTIONS, {'rac', 'conservative'})
        self.assertEqual(REASON_CODES, {'history', 'risk', 'constraint', 'cost',
                                        'uncertainty', 'conservative', 'other'})
        self.assertEqual(RISK_LEVELS, {'low', 'medium', 'high', 'unknown'})
        self.assertEqual(tuple(ALLOWED_TERMINATORS), ('<|im_end|>',))

    def test_invalid_replies_carry_reason_codes(self):
        cases = {
            ('{"learning_rate":0.001,"batch_size":128,"epochs":2,'
             '"strategy":"uniform","reason":"x"}'): 'parameter_proposal_json',
            ('{"selected_option":"RAC","reason_codes":[],"risk":"low",'
             '"learning_rate":0.1}'): 'unexpected_fields',
            '{"selected_option":"RAC"}': 'missing_fields',
            '{"selected_option":"other","reason_codes":[],"risk":"low"}': 'unknown_option',
            '{"selected_option":"RAC","reason_codes":[],"risk":"bad"}': 'invalid_risk',
            ('{"selected_option":"RAC","reason_codes":["history","history"],'
             '"risk":"low"}'): 'invalid_reason_codes',
            ('```json {"selected_option":"RAC","reason_codes":[],"risk":"low"}'
             ' ```'): 'fenced_json',
            '{"selected_option":"RAC","reason_codes":': 'truncated_json',
            'RAC<|unknown|>': 'invalid_terminal_marker',
            'RAC<|im_end|><|im_end|>': 'extra_content',
            'RAC<|im_end|>extra': 'extra_content',
            'bad': 'not_json',
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                result = parse_decision(raw)
                self.assertFalse(result['valid'])
                self.assertEqual(result['action'], 'conservative_invalid_response')
                self.assertEqual(result.get('reason'), expected)

    def test_valid_replies_have_no_reason(self):
        for raw in ('RAC', 'conservative<|im_end|>',
                    '{"selected_option":"RAC","reason_codes":[],"risk":"low"}'):
            with self.subTest(raw=raw):
                result = parse_decision(raw)
                self.assertTrue(result['valid'])
                self.assertIsNone(result.get('reason'))

    def test_selection_prompt_and_reply_helpers_follow_contract(self):
        from rac_hpo.contest.sampler import (
            SELECTION_SYSTEM, parse_selection_reply, selection_messages)
        self.assertIn('selected_option', SELECTION_SYSTEM)
        self.assertIn('reason_codes', SELECTION_SYSTEM)
        self.assertNotIn('learning_rate', SELECTION_SYSTEM)
        context = {'task': 'A', 'round': 1, 'selected_metric': 0.7, 'history': [],
                   'rac': {'learning_rate': .003, 'batch_size': 128, 'epochs': 2},
                   'conservative': {'learning_rate': .0015, 'batch_size': 128, 'epochs': 1}}
        messages = selection_messages(context)
        self.assertEqual(messages[0]['content'], SELECTION_SYSTEM)
        self.assertEqual(json.loads(messages[1]['content'])['task'], 'A')
        reply = json.dumps({'selected_option': 'RAC', 'reason_codes': ['history'], 'risk': 'low'})
        self.assertEqual(parse_selection_reply(reply),
                         {'selected_option': 'rac', 'reason_codes': ['history'], 'risk': 'low'})
        with self.assertRaises(ValueError):
            parse_selection_reply(json.dumps({'learning_rate': 0.001}))

    def test_selection_payload_is_identical_for_offline_and_runtime_history(self):
        from rac_hpo.contest.sampler import selection_payload
        offline = {'task': 'A', 'round': 3, 'selected_metric': 0.71,
                   'history': [{'round': 1, 'proposal': {'learning_rate': .003, 'batch_size': 128, 'epochs': 2},
                                'metrics': {'macro_f1': 0.70}, 'accepted': True}],
                   'rac': {'learning_rate': .003, 'batch_size': 128, 'epochs': 2},
                   'conservative': {'learning_rate': .0015, 'batch_size': 128, 'epochs': 1}}
        runtime = {'task': 'A', 'round': 3, 'selected_metric': 0.71,
                   'history': [{'round': 1, 'rac_params': {'learning_rate': .003, 'batch_size': 128, 'epochs': 2},
                                'candidate_metric': 0.70, 'accepted': True}],
                   'rac': {'learning_rate': .003, 'batch_size': 128, 'epochs': 2},
                   'conservative': {'learning_rate': .0015, 'batch_size': 128, 'epochs': 1}}
        a, b = selection_payload(offline), selection_payload(runtime)
        self.assertEqual(a, b)
        self.assertEqual(a['history'][0]['value'], 0.70)
        self.assertEqual(a['history'][0]['action']['learning_rate'], .003)
        self.assertEqual(a['metric_direction'], 'higher')
        self.assertEqual(sorted(a), sorted(b))
        with self.assertRaises(KeyError):
            selection_payload({'task': 'A', 'round': 1})
