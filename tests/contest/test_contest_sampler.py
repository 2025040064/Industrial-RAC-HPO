import contextlib
import io
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
        latest = {"A": [("A", [], "rac A")], "B": [], "C": [("C", [], "rac C")]}
        older = {"B": [("B", [], "rules B")]}

        with patch("scripts.train_contest_sampler.examples",
                   side_effect=lambda root, task: (latest if root == primary else older)[task]) as read:
            with self.assertRaisesRegex(ValueError, "No accepted decisions for B"):
                split_examples(primary)
            read.reset_mock()
            training, heldout, sources = split_examples(primary, supplement)

        self.assertEqual(training, latest["A"] + older["B"])
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
        args = SimpleNamespace(project="test-project", name="test-run", output=Path("workspace/test-result.json"))
        stdout = io.StringIO()
        with patch.dict(sys.modules, modules), contextlib.redirect_stdout(stdout):
            with self.assertRaises(ReachedPyTrio):
                train(args, [], [])
        self.assertIn(f"TRAINING_RECORD_URL={url}", stdout.getvalue())
