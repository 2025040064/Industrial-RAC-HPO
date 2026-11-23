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
