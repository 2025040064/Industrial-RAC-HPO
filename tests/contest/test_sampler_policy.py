import json
import unittest

from rac_hpo.contest.sampler import decision_messages, parse_action
from rac_hpo.contest.service import run


class SamplerPolicyTests(unittest.TestCase):
    def test_base_and_sampler_modes_require_distinct_weight_configuration(self):
        with self.assertRaisesRegex(ValueError, "does not accept a Sampler URI"):
            run("unused", "unused", policy_name="pytrio_base", sampler_path="trio://test/weights")
        with self.assertRaisesRegex(ValueError, "Provide the full Sampler URI"):
            run("unused", "unused", policy_name="pytrio_sampler")

    def test_removes_qwen_marker_and_normalizes_observed_alias(self):
        text = ('{"learning_rate":0.001,"batch_size":32,"epochs":1,'
                '"strategy":"uniform_sampling","reason":"Try a smaller batch."}<|im_end|>')
        self.assertEqual(parse_action(text, "A")["strategy"], "uniform")

    def test_rejects_class_focusing_for_regression(self):
        action = {"learning_rate": 0.001, "batch_size": 32, "epochs": 1,
                  "strategy": "class_focus", "reason": "Try class balancing.",
                  "target_class": "Acetaldehyde", "sampling_multiplier": 2}
        with self.assertRaisesRegex(ValueError, "incompatible"):
            parse_action(json.dumps(action), "B")

    def test_prompt_includes_summary_only(self):
        action = {"learning_rate": 0.001, "batch_size": 32, "epochs": 1,
                  "strategy": "uniform", "reason": "not shared", "extra": "not shared"}
        history = [{"round": 1, "proposal": action, "metrics": {"rmse": 52, "mae": 10},
                    "accepted": True, "candidate": "/local.checkpoint"}]
        context = {"task": "C", "round": 2, "baseline_metrics": {"rmse": 53},
                   "selected_metric": 52, "history": history, "diagnostics": {"raw": "not shared"}}
        sent = json.loads(decision_messages(context)[-1]["content"])
        self.assertEqual(sent["history"], [{"round": 1, "value": 52, "accepted": True,
                                          "action": {key: action[key] for key in (
                                              "learning_rate", "batch_size", "epochs", "strategy")}}])
        self.assertNotIn("diagnostics", sent)
