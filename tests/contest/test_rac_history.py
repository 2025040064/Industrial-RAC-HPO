from copy import deepcopy
import unittest
from unittest.mock import patch

from rac_hpo.contest.rac_policy import ContestRACPolicy
from rac_hpo.optimization.rac_hpo.search import RACSettings
from rac_hpo.optimization.rac_hpo.surrogate import TrialSurrogate


class ContestRACHistoryTest(unittest.TestCase):
    def setUp(self):
        self.metadata = {"learning_rate": 0.001, "batch_size": 64}
        self.diagnostics = {"groups": {"FD001/1": {"mae": 4.0, "samples": 20}}}
        self.policy = ContestRACPolicy("C", {
            "diagnostics": self.diagnostics, "units": {"validation": 1},
        })
        self.record = {
            "round": 1, "rac_params": {**self.metadata, "epochs": 2, "sampling_level": 1},
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
        second["rac_params"]["epochs"] = 3
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
        second["rac_params"]["epochs"] = 3
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
            record["rac_params"]["epochs"] = 1 + index % 5
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
