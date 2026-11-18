import unittest
from rac_hpo.contest.bearing_feasibility import assess_feasibility


class BearingFeasibilityTest(unittest.TestCase):
    def setUp(self):
        self.space={'x':{'type':'float','low':0.,'high':1.}}
        self.parent={'one':1.,'two':2.}
    def test_single_label_is_shadow_only_without_prediction(self):
        rows=[{'round':i,'rac_params':{'x':i/10},'parent_bearing_rmse':self.parent,
               'bearing_comparison':{'feasible':False}} for i in range(1,9)]
        trace=assess_feasibility(rows,self.parent,{'x':.9},self.space,9)
        self.assertIsNone(trace['predicted_feasible'])
        self.assertEqual(trace['reason'],'single_label_history')
        self.assertFalse(trace['training_candidate_filtered'])
    def test_forward_validation_uses_only_earlier_rounds(self):
        rows=[{'round':i,'rac_params':{'x':i/10},'parent_bearing_rmse':self.parent,
               'bearing_comparison':{'feasible':i%2==0}} for i in range(1,9)]
        trace=assess_feasibility(rows,self.parent,{'x':.95},self.space,9)
        self.assertTrue(all(s['training_last_round']<s['held_out_round'] for s in trace['forward_splits']))
        self.assertIn('passed',trace['forward_validation'])
        self.assertFalse(trace['training_candidate_filtered'])
    def test_future_history_and_missing_parent_are_excluded(self):
        rows=[{'round':9,'rac_params':{'x':.5},'parent_bearing_rmse':self.parent,
               'bearing_comparison':{'feasible':True}},
              {'round':2,'rac_params':{'x':.5},'bearing_comparison':{'feasible':False}}]
        trace=assess_feasibility(rows,self.parent,{'x':.4},self.space,9)
        self.assertEqual(trace['history_count'],0)
        self.assertEqual(len(trace['excluded']),2)
