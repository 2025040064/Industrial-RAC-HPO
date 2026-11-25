from copy import deepcopy
import unittest
from unittest.mock import patch

from rac_hpo.contest.rac_policy import ContestRACPolicy
from rac_hpo.optimization.rac_hpo.search import RACSettings
from rac_hpo.optimization.rac_hpo.surrogate import TrialSurrogate


class ContestRACHistoryTest(unittest.TestCase):
    def setUp(self):
        # Inside the regression search space (learning rate floor is 3e-3).
        self.metadata = {"learning_rate": 0.004, "batch_size": 64}
        self.diagnostics = {"groups": {"FD001/1": {"mae": 4.0, "samples": 20}}}
        self.policy = ContestRACPolicy("C", {
            "diagnostics": self.diagnostics, "units": {"validation": 1},
        })
        self.record = {
            "round": 1, "rac_params": {**self.metadata, "epochs": 4, "sampling_level": 1},
            "diagnostics": self.diagnostics, "robust_objective": self.policy.baseline_objective,
            "training_seconds": 1.0,
        }

    def test_invalid_records_do_not_enter_the_search(self):
        invalid = [
            {**self.record, "round": 2, "training_seconds": float("nan")},
            {**self.record, "round": 3, "robust_objective": 0.0},
            {**self.record, "round": 4, "diagnostics": {}},
            {**self.record, "round": 5, "rac_params": {**self.record["rac_params"], "epochs": 1.5}},
            {**self.record, "round": 6},
        ]
        _, trace = self.policy.propose(self.metadata, [self.record, *invalid])
        self.assertEqual(trace["completed_history"], 1)
        self.assertEqual(trace["history_rounds"], [1])
        self.assertEqual([item["round"] for item in trace["excluded_history"]], [2, 3, 4, 5, 6])

    def test_transfer_tpe_penalizes_cost_and_reports_usage(self):
        first = {**deepcopy(self.record), "parent_objective": 1.0,
                 "configuration": {"strategy": "uniform"}}
        second = deepcopy(first)
        second.update(round=2, training_seconds=4.0)
        second["rac_params"]["epochs"] = 5
        with patch.object(self.policy, "_fallback", return_value=first["rac_params"]) as fallback:
            _, trace = self.policy.propose(self.metadata, [], transfer_records=[first, second], round_index=3)
        observations = fallback.call_args.args[0]
        self.assertLess(observations[0]["objective"], observations[1]["objective"])
        self.assertEqual(trace["transfer_history_rounds"], [1, 2])
        self.assertEqual(trace["transfer_cost_method"], "bounded_log_relative_seconds")

    def test_transfer_cost_can_be_disabled_without_changing_observations(self):
        policy = ContestRACPolicy("C", {"diagnostics": self.diagnostics}, transfer_cost_weight=0.0)
        first = {**deepcopy(self.record), "parent_objective": 1.0,
                 "configuration": {"strategy": "uniform"}}
        second = deepcopy(first)
        second.update(round=2, training_seconds=4.0)
        second["rac_params"]["epochs"] = 5
        with patch.object(policy, "_fallback", return_value=first["rac_params"]) as fallback:
            _, trace = policy.propose(self.metadata, [], transfer_records=[first, second], round_index=3)
        observations = fallback.call_args.args[0]
        self.assertEqual(observations[0]["objective"], observations[1]["objective"])
        self.assertEqual(trace["transfer_cost_weight"], 0.0)

    def test_future_rounds_are_never_search_observations(self):
        same = {**deepcopy(self.record), "round": 3}
        transfer = {**deepcopy(self.record), "round": 4, "parent_objective": 1.0,
                    "configuration": {"strategy": "uniform"}}
        _, trace = self.policy.propose(self.metadata, [same], transfer_records=[transfer], round_index=3)
        self.assertEqual(trace["history_rounds"], [])
        self.assertEqual(trace["transfer_history_rounds"], [])
        self.assertEqual(trace["method"], "checkpoint_reference")

    def test_cost_quality_falls_back_when_a_holdout_cost_spikes(self):
        trials = []
        for index in range(9):
            record = deepcopy(self.record)
            record["rac_params"]["epochs"] = 4 + index % 2
            trials.append({
                "params": record["rac_params"], "duration_seconds": 1 if index < 8 else 100,
                "metrics": {"regimes": {"FD001": {"mae": 4.0, "samples": 20}}},
            })
        surrogate = TrialSurrogate(
            trials, self.policy.space, {"FD001": 4.0}, {"FD001": 1},
            0.3, 1e-8, RACSettings(min_forward_train=5, forward_holdout=3,
                                  maximum_cost_log_mae_ratio=1.0), 42,
        )
        quality = surrogate.forward_check()["cost_validation"]
        self.assertFalse(quality["passed"])
        self.assertGreater(quality["log_mae"], 0.0)

    def test_task_specific_lr_floor_and_stage_aware_checkpoint_reference(self):
        policy_a = ContestRACPolicy("A", {"diagnostics": {"classes": {"c0": {"f1": 0.8, "samples": 10}}}})
        policy_b = ContestRACPolicy("B", {"diagnostics": {"groups": {"b1": {"mae": 100.0, "rmse": 120.0, "samples": 10}}}})
        policy_c = ContestRACPolicy("C", {"diagnostics": self.diagnostics})
        self.assertEqual(policy_a.space["learning_rate"]["low"], 1e-5)
        self.assertEqual(policy_b.space["learning_rate"]["low"], 3e-3)
        self.assertEqual(policy_c.space["learning_rate"]["low"], 1e-4)

        # C: round 1 uses 2-epoch lr=3e-3 warm step; later stage resets step down at 1 epoch
        p_c1, t_c1 = policy_c.propose({"learning_rate": 0.002, "batch_size": 256}, [], round_index=1)
        p_c2, t_c2 = policy_c.propose({"learning_rate": 0.003, "batch_size": 256}, [], round_index=2)
        p_c4, _ = policy_c.propose({"learning_rate": 0.003, "batch_size": 256}, [], round_index=4)
        p_c7, _ = policy_c.propose({"learning_rate": 0.003, "batch_size": 256}, [], round_index=7)
        self.assertEqual(t_c1["method"], "checkpoint_reference")
        self.assertEqual(t_c2["method"], "checkpoint_reference")
        self.assertEqual((p_c1["learning_rate"], p_c1["batch_size"], p_c1["epochs"]), (3e-3, 256, 2))
        self.assertEqual(p_c2["epochs"], 1)
        self.assertLess(p_c2["learning_rate"], 3e-3)
        self.assertLess(p_c4["learning_rate"], p_c2["learning_rate"])
        self.assertLess(p_c7["learning_rate"], p_c4["learning_rate"])

        # Excluded prior same-parent rejected params are skipped instead of repeated
        p_c2_dedup, _ = policy_c.propose(
            {"learning_rate": 0.003, "batch_size": 256}, [], round_index=2,
            excluded_params=[{**t_c2["params"]}],
        )
        self.assertNotEqual(
            (p_c2_dedup["learning_rate"], p_c2_dedup["batch_size"], p_c2_dedup["epochs"]),
            (p_c2["learning_rate"], p_c2["batch_size"], p_c2["epochs"]),
        )

        # B: preserves v8-B reference momentum on fresh parent, and steps down to 1-epoch if excluded
        p_b2, _ = policy_b.propose({"learning_rate": 0.003, "batch_size": 128}, [], round_index=2)
        p_b5_fresh, t_b5_fresh = policy_b.propose({"learning_rate": 0.0049, "batch_size": 106}, [], round_index=5)
        p_b8_dedup, _ = policy_b.propose(
            {"learning_rate": 0.0049, "batch_size": 106}, [], round_index=8,
            excluded_params=[{**t_b5_fresh["params"]}],
        )
        self.assertEqual(p_b2["epochs"], 2)
        self.assertEqual(p_b5_fresh["epochs"], 2)
        self.assertAlmostEqual(p_b5_fresh["learning_rate"], 0.0049)
        self.assertEqual(p_b5_fresh["batch_size"], 106)
        self.assertEqual(p_b8_dedup["epochs"], 1)

    def test_conservative_alternative_stabilizes_batch_and_halves_c_lr(self):
        from rac_hpo.contest.rac_policy import conservative_alternative

        alt_c = conservative_alternative(
            "C", {"learning_rate": 0.003, "batch_size": 18, "epochs": 2, "sampling_level": 1}, 256
        )
        self.assertEqual(alt_c["epochs"], 1)
        self.assertEqual(alt_c["batch_size"], 256)
        self.assertAlmostEqual(alt_c["learning_rate"], 0.0015)

        alt_b = conservative_alternative(
            "B", {"learning_rate": 0.005, "batch_size": 34, "epochs": 2, "sampling_level": 1}, 106
        )
        self.assertEqual(alt_b["epochs"], 1)
        self.assertEqual(alt_b["batch_size"], 34)
        self.assertAlmostEqual(alt_b["learning_rate"], 0.003)

        alt_a = conservative_alternative(
            "A", {"learning_rate": 0.003, "batch_size": 32, "epochs": 3, "sampling_level": 4}, 128
        )
        self.assertEqual(alt_a["batch_size"], 32)
        self.assertEqual(alt_a["sampling_level"], 1)
        self.assertAlmostEqual(alt_a["learning_rate"], 0.0015)
