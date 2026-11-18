import unittest
from rac_hpo.contest.surrogate_evidence import shadow_evidence


class ShadowEvidenceTest(unittest.TestCase):
    def test_only_exact_trained_past_shadow_candidates_count(self):
        rows=[]
        for n,x in enumerate((.8,.9,1.0),1):
            rows.append({'round':n,'rac_params':{'x':n},'parent_sha256':'a'*64,
                         'parent_objective':1.,'robust_objective':x,
                         'trace':{'surrogate_shadow_rank':True,'shadow_proposal':{'x':n},'predicted_objective':x}})
        proof=shadow_evidence(rows,'a'*64,4)
        self.assertTrue(proof['passed']);self.assertEqual(proof['observations'],3)
        rows[2]['trace']['shadow_proposal']={'x':99}
        self.assertFalse(shadow_evidence(rows,'a'*64,4)['passed'])
        rows[2]['trace']['shadow_proposal']={'x':3}
        self.assertFalse(shadow_evidence(rows,'a'*64,3)['passed'])
    def test_flat_and_different_parent_fail_closed(self):
        rows=[{'round':i,'rac_params':{'x':i},'parent_sha256':'b'*64,
               'parent_objective':1.,'robust_objective':.9,
               'trace':{'surrogate_shadow_rank':True,'shadow_proposal':{'x':i},'predicted_objective':.9}}
              for i in range(1,4)]
        self.assertFalse(shadow_evidence(rows,'a'*64,4)['passed'])
        self.assertFalse(shadow_evidence(rows,'b'*64,4)['passed'])
