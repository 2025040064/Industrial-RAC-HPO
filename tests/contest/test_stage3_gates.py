import unittest
from unittest.mock import patch

import numpy as np

from rac_hpo.optimization.rac_hpo.search import RACSearchPolicy, RACSettings
from rac_hpo.optimization.rac_hpo.surrogate import TrialSurrogate


class FakeSurrogate:
    quality = {}
    def __init__(self, *args):
        self.baselines = np.array([1.0])
    def forward_check(self):
        return self.quality
    def fit(self):
        return self
    def predict(self, candidates):
        means = .7 + .1 * np.asarray(candidates)[:, 0]
        return np.repeat(means[:, None, None], 8, axis=1), np.ones(len(candidates)) * 10


def history():
    return [{'status':'completed','params':{'x':i/10},'objective':1.,'duration_seconds':1.,
             'metrics':{'regimes':{'a':{'mae':1.,'samples':10}}}} for i in range(8)]


def config(gamma=0, mode='active'):
    return {'seed':42,'baseline_errors':{'a':1.},'weights':{'a':1.},
            'surrogate_mode':mode,'rac_hpo':{'warmup_trials':8,'minimum_history':8,
            'min_forward_train':5,'forward_holdout':3,'exploration_fraction':1e-12,'gamma':gamma}}


class Stage3GateTests(unittest.TestCase):
    def test_performance_pass_and_cost_fail_uses_performance_without_cost(self):
        FakeSurrogate.quality={'passed':False,'reason':'cost_surrogate_quality_failed',
                               'performance_validation':{'passed':True,'reason':'passed'},
                               'cost_validation':{'passed':False,'reason':'cost_surrogate_quality_failed'}}
        with patch('rac_hpo.optimization.rac_hpo.search.TrialSurrogate', FakeSurrogate):
            params, trace = RACSearchPolicy(config(gamma=.5), {'x':{'type':'float','low':0.,'high':1.}}).propose(history())
        self.assertIsNotNone(params)
        self.assertEqual(trace['method'],'rac_acquisition')
        self.assertEqual(trace['effective_cost_gamma'],0)
        self.assertEqual(trace['cost_gate_reason'],'cost_surrogate_quality_failed')

    def test_performance_failure_never_uses_surrogate_even_if_cost_passes(self):
        FakeSurrogate.quality={'passed':False,'reason':'surrogate_quality_failed',
                               'performance_validation':{'passed':False,'reason':'surrogate_quality_failed'},
                               'cost_validation':{'passed':True,'reason':'passed'}}
        with patch('rac_hpo.optimization.rac_hpo.search.TrialSurrogate', FakeSurrogate):
            params, trace = RACSearchPolicy(config(), {'x':{'type':'float','low':0.,'high':1.}}).propose(history())
        self.assertIsNone(params)
        self.assertEqual(trace['method'],'tpe_fallback')
        self.assertEqual(trace['reason'],'surrogate_quality_failed')

    def test_invalid_cost_prediction_cannot_block_valid_performance_ranking(self):
        FakeSurrogate.quality={'passed':True,'reason':'passed',
                               'performance_validation':{'passed':True,'reason':'passed'},
                               'cost_validation':{'passed':True,'reason':'passed'}}
        class InvalidCost(FakeSurrogate):
            def predict(self,candidates):
                members,_=super().predict(candidates)
                return members,np.full(len(candidates),float('nan'))
        with patch('rac_hpo.optimization.rac_hpo.search.TrialSurrogate', InvalidCost):
            params,trace=RACSearchPolicy(config(gamma=.5),{'x':{'type':'float','low':0.,'high':1.}}).propose(history())
        self.assertIsNotNone(params)
        self.assertEqual(trace['effective_cost_gamma'],0)
        self.assertEqual(trace['cost_gate_reason'],'invalid_cost_prediction')

    def test_legacy_coupled_reference_remains_available_for_replay(self):
        FakeSurrogate.quality={'passed':False,'reason':'cost_surrogate_quality_failed',
                               'performance_validation':{'passed':True,'reason':'passed'},
                               'cost_validation':{'passed':False,'reason':'cost_surrogate_quality_failed'}}
        options=config(gamma=0); options['cost_gate_mode']='coupled'
        with patch('rac_hpo.optimization.rac_hpo.search.TrialSurrogate', FakeSurrogate):
            params,trace=RACSearchPolicy(options,{'x':{'type':'float','low':0.,'high':1.}}).propose(history())
        self.assertIsNone(params)
        self.assertEqual(trace['reason'],'cost_surrogate_quality_failed')

    def test_shadow_records_hypothetical_proposal_without_choosing_it(self):
        FakeSurrogate.quality={'passed':True,'reason':'passed',
                               'performance_validation':{'passed':True,'reason':'passed'},
                               'cost_validation':{'passed':True,'reason':'passed'}}
        with patch('rac_hpo.optimization.rac_hpo.search.TrialSurrogate', FakeSurrogate):
            params, trace = RACSearchPolicy(config(mode='shadow'), {'x':{'type':'float','low':0.,'high':1.}}).propose(history())
        self.assertIsNone(params)
        self.assertEqual(trace['method'],'tpe_fallback')
        self.assertTrue(trace['surrogate_shadow_rank'])
        self.assertFalse(trace['surrogate_actual_proposal'])
        self.assertIn('shadow_proposal',trace)

    def test_forward_validation_reports_insufficient_and_rejects_nonfinite(self):
        settings=RACSettings(minimum_history=8,min_forward_train=5,forward_holdout=3)
        trials=history()[:7]
        model=TrialSurrogate(trials, {'x':{'type':'float','low':0.,'high':1.}}, {'a':1.},{'a':1.},.3,1e-8,settings,42)
        result=model.forward_check()
        self.assertFalse(result['performance_validation']['passed'])
        self.assertEqual(result['performance_validation']['reason'],'insufficient_forward_holdouts')
        trials=history()
        trials[0]['metrics']['regimes']['a']['mae']=float('nan')
        with self.assertRaisesRegex(ValueError,'finite'):
            TrialSurrogate(trials, {'x':{'type':'float','low':0.,'high':1.}}, {'a':1.},{'a':1.},.3,1e-8,settings,42)

    def test_flat_forward_correlation_fails_closed(self):
        model=TrialSurrogate(history(), {'x':{'type':'float','low':0.,'high':1.}}, {'a':1.},{'a':1.},
                             .3,1e-8,RACSettings(minimum_history=8,min_forward_train=5,forward_holdout=3),42)
        result=model.forward_check()
        self.assertFalse(result['performance_validation']['passed'])
        self.assertIsNone(result['performance_validation']['rank_correlation'])


if __name__=='__main__':
    unittest.main()
