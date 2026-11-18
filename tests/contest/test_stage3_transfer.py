import math
import unittest

from rac_hpo.contest.transfer_gate import parent_distance, filter_transfer


class TransferGateTest(unittest.TestCase):
    def setUp(self):
        self.current={'a':1.,'b':2.}
        self.weights={'a':1.,'b':1.}
        self.records=[{'round':i,'parent_sha256':str(i%2)*64,'parent_regime_errors':{'a':1.,'b':2.},
                       'rac_params':{'x':i}} for i in range(1,5)]
    def test_distance_matches_weighted_log_formula_and_rejects_incompatible(self):
        self.assertAlmostEqual(parent_distance({'a':2.,'b':2.},self.current,self.weights),
                               .5*math.log((2+1e-8)/(1+1e-8)))
        with self.assertRaises(ValueError):
            parent_distance({'a':1.},self.current,self.weights)
        with self.assertRaises(ValueError):
            parent_distance({'a':float('nan'),'b':1.},self.current,self.weights)
    def test_history_and_parent_counts_never_enable_without_prior_replay_evidence(self):
        selected, audit=filter_transfer(self.records,self.current,self.weights,5,max_distance=.5)
        self.assertEqual(selected,[])
        self.assertEqual(audit['eligible_count'],4)
        self.assertEqual(audit['distinct_parent_count'],2)
        self.assertEqual(audit['reason'],'missing_prior_replay_evidence')
    def test_reject_future_missing_vectors_and_duplicates(self):
        bad=[*self.records,{'round':5,'parent_sha256':'3'*64,'parent_regime_errors':self.current,'rac_params':{'x':5}},
             {'round':6,'parent_sha256':'4'*64,'rac_params':{'x':6}},
             {'round':1,'parent_sha256':'1'*64,'parent_regime_errors':self.current,'rac_params':{'x':1}}]
        _, audit=filter_transfer(bad,self.current,self.weights,5,max_distance=.5)
        self.assertIn('non_prior_round',[row['reason'] for row in audit['excluded']])
        self.assertIn('duplicate',[row['reason'] for row in audit['excluded']])
    def test_past_successful_replay_can_enable_but_future_evidence_cannot(self):
        evidence={'valid':True,'evaluated_until':4,'pairs':3,'mean_gain':.1}
        selected,audit=filter_transfer(self.records,self.current,self.weights,5,max_distance=.5,replay_evidence=evidence)
        self.assertEqual(len(selected),4)
        evidence['evaluated_until']=5
        selected,audit=filter_transfer(self.records,self.current,self.weights,5,max_distance=.5,replay_evidence=evidence)
        self.assertEqual(selected,[])
        self.assertEqual(audit['reason'],'invalid_replay_evidence')

    def test_invalid_parameter_space_is_excluded_before_minimum_count(self):
        bad=list(self.records)
        bad[-1]={**bad[-1],'rac_params':{'x':float('nan')}}
        evidence={'valid':True,'evaluated_until':4,'pairs':3,'mean_gain':.1}
        selected,audit=filter_transfer(bad,self.current,self.weights,5,max_distance=.5,
            parameter_space={'x':{'type':'int','low':1,'high':10}},replay_evidence=evidence)
        self.assertEqual(selected,[])
        self.assertEqual(audit['reason'],'insufficient_transfer_records')
        self.assertIn('invalid_parameters',[row['reason'] for row in audit['excluded']])

    def test_missing_measured_outcomes_are_not_eligible(self):
        _,audit=filter_transfer(self.records,self.current,self.weights,5,max_distance=.5,require_complete=True)
        self.assertEqual(audit['eligible_count'],0)
        self.assertTrue(all(row['reason']=='invalid_observation' for row in audit['excluded']))
