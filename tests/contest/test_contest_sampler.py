import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.train_contest_sampler import train


class ReachedPyTrio(Exception):
    pass


class ContestSamplerTests(unittest.TestCase):
    def test_explicit_supplement_fills_only_missing_training_task(self):
        from scripts.train_contest_sampler import split_examples

        primary, supplement = Path("rac"), Path("rules")

        def row(task, round_index):
            return {"task": task, "completion": '{"selected_option":"RAC","reason_codes":["history"],"risk":"low"}',
                    "context": {"task": task, "round": round_index, "history": [{"round": 1}],
                                "selected_metric": .7,
                                "rac": {"learning_rate": .003, "batch_size": 128, "epochs": 2},
                                "conservative": {"learning_rate": .0015, "batch_size": 128, "epochs": 1}}}

        latest = {"A": [row("A", 2)], "B": [], "C": [row("C", 2)]}
        older = {"B": [row("B", 2)]}

        with patch("scripts.train_contest_sampler.examples",
                   side_effect=lambda root, task, legacy=False: (
                       latest if root == primary else older)[task]) as read:
            with self.assertRaisesRegex(ValueError, "No accepted decisions for B"):
                split_examples(primary)
            read.reset_mock()
            training, heldout, sources = split_examples(primary, supplement)

        self.assertEqual(len(training), 4)
        self.assertEqual([row["task"] for row in training], ["A", "A", "B", "B"])
        self.assertEqual({row["context"]["round"] for row in training}, {2})
        labels = [json.loads(row["completion"])["selected_option"] for row in training]
        self.assertEqual(labels, ["RAC", "conservative", "RAC", "conservative"])
        self.assertEqual(heldout, latest["C"])
        self.assertEqual(sources, {"A": primary, "B": supplement, "C": primary})
        self.assertEqual([call.args for call in read.call_args_list],
                         [(primary, "A"), (primary, "B"), (supplement, "B"), (primary, "C")])

    def test_uses_swanlab_run_url_before_starting_pytrio(self):
        url = "https://swanlab.cn/@test/project/runs/test-run"
        swanlab = SimpleNamespace(init=lambda **kwargs: SimpleNamespace(url=url))

        def stop_before_cloud_call():
            raise ReachedPyTrio

        modules = {"swanlab": swanlab, "pytrio": SimpleNamespace(ServiceClient=stop_before_cloud_call),
                   "numpy": SimpleNamespace()}
        args = SimpleNamespace(project="test-project", name="test-run", epochs=1, learning_rate=1e-4,
                               legacy_params=False, output=Path("workspace/test-result.json"))
        row = {"task": "A", "context": {"task": "A", "round": 1, "history": [], "selected_metric": .7,
                                        "rac": {"learning_rate": .003, "batch_size": 128, "epochs": 2},
                                        "conservative": {"learning_rate": .0015, "batch_size": 128, "epochs": 1}},
               "completion": '{"selected_option":"RAC","reason_codes":["history"],"risk":"low"}'}
        stdout = io.StringIO()
        with patch.dict(sys.modules, modules), contextlib.redirect_stdout(stdout):
            with self.assertRaises(ReachedPyTrio):
                train(args, [row], [])
        self.assertIn(f"TRAINING_RECORD_URL={url}", stdout.getvalue())
