import importlib.metadata
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from rac_hpo.contest.packages import prepare
from rac_hpo.contest.policy import accept_candidate, local_decision, optimized_decision, validate
from rac_hpo.contest import service


ROOT = Path(__file__).resolve().parents[2]


class ContestTests(unittest.TestCase):
    def test_policy_uses_rejection_history(self):
        context = {"metadata": {"learning_rate": .003, "batch_size": 128}, "history": []}
        first = local_decision(context)
        context["history"] = [{"accepted": False, "proposal": first}]
        self.assertEqual(local_decision(context)["learning_rate"], .0015)

    def test_decision_rejects_invalid_actions(self):
        valid = {"learning_rate": .003, "batch_size": 128, "epochs": 2, "reason": "test"}
        for change in ({"learning_rate": float("nan")}, {"epochs": True},
                       {"epochs": 6}, {"command": "shell"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate({**valid, **change})

    def test_class_focus_uses_weak_class_from_diagnostics(self):
        context = {"task": "A", "round": 5, "history": [],
                   "metadata": {"learning_rate": .003, "batch_size": 128},
                   "diagnostics": {"classes": {"weak": {"f1": 0}, "strong": {"f1": .8}}}}
        proposal = optimized_decision(context)
        self.assertEqual(proposal["strategy"], "class_focus")
        self.assertEqual(proposal["target_class"], "weak")

    def test_bearing_gate_rejects_local_regression_despite_global_improvement(self):
        baseline = {"groups": {"one": {"rmse": 1.0}, "two": {"rmse": 3.0}}}
        degraded = {"groups": {"one": {"rmse": 1.1}, "two": {"rmse": 2.0}}}
        improved = {"groups": {"one": {"rmse": .9}, "two": {"rmse": 2.0}}}
        self.assertFalse(accept_candidate("B", baseline, degraded, 2.0, 1.5))
        self.assertTrue(accept_candidate("B", baseline, improved, 2.0, 1.5))

    @unittest.skipUnless(
        importlib.metadata.version("numpy") == "1.26.4",
        "Real continuation integration requires the isolated contest environment",
    )
    def test_rac_hpo_uses_selected_parent_and_resumes_committed_rounds(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache/contest-tmp") as temporary:
            output = Path(temporary) / "run"
            options = {"rounds": 2, "tasks": ("A",), "policy_name": "rac_hpo"}
            summaries = service.run(ROOT / "训练集", output, **options)
            task = output / "A"
            paths = [task / f"round-{number:02}.json" for number in (1, 2)]
            before = [p.read_bytes() for p in paths]
            records = [json.loads(data) for data in before]
            baseline_hash = json.loads((task / "audit.json").read_text())["checkpoint_sha256"]
            self.assertTrue(records[0]["accepted"])
            for record in records:
                self.assertEqual(record["decision_source"], "rac_hpo")
                self.assertTrue(record["continuous_replay_equal"])
                self.assertGreater(record["training_seconds"], 0)
            self.assertEqual(records[0]["parent_sha256"], baseline_hash)
            self.assertEqual(records[1]["parent_sha256"], records[0]["checkpoint_sha256"])
            self.assertEqual(summaries[0]["parent_mode"], "selected_checkpoint")
            rows = [json.loads(line) for line in (task / "selection-audit.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["parent_sha256"], records[0]["checkpoint_sha256"])
            self.assertEqual(summaries, service.run(ROOT / "训练集", output, resume=True, **options))
            self.assertEqual(before, [p.read_bytes() for p in paths])
            audit_path = task / "selection-audit.jsonl"
            complete_audit = audit_path.read_text()
            audit_path.write_text(complete_audit.splitlines(keepends=True)[0])
            self.assertEqual(summaries, service.run(ROOT / "训练集", output, resume=True, **options))
            self.assertEqual(audit_path.read_text(), complete_audit)

    @unittest.skipUnless(importlib.metadata.version("numpy") == "1.26.4", "contest environment required")
    def test_rejected_rac_candidate_keeps_next_parent_and_metric(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache/contest-tmp") as temporary:
            output = Path(temporary) / "run"
            with patch.object(service, "accept_candidate", return_value=False):
                service.run(ROOT / "训练集", output, rounds=2, tasks=("A",), policy_name="rac_hpo")
            rows = [json.loads(line) for line in (output / "A/selection-audit.jsonl").read_text().splitlines()]
            self.assertFalse(rows[0]["accepted"])
            self.assertEqual(rows[1]["parent_sha256"], rows[0]["selected_sha256"])
            self.assertEqual(rows[1]["parent_metric"], rows[0]["parent_metric"])
            self.assertEqual(rows[1]["previous_selected_metric"], rows[0]["previous_selected_metric"])

    def test_reported_primary_regressions_are_rejected(self):
        for task, parent, candidate in (("A", .964337, .963501), ("C", 51.436545, 51.658574)):
            with self.subTest(task=task):
                self.assertFalse(accept_candidate(task, {}, {}, parent, candidate))

    def test_archive_rejects_traversal_before_writing(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache/contest-tmp") as temporary:
            base = Path(temporary)
            archive = base / "bad.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("../escaped", "bad")
            with self.assertRaises(ValueError):
                prepare(archive, base / "package", "A")
            self.assertFalse((base / "package").exists())

    def test_interrupted_extraction_can_retry(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache/contest-tmp") as temporary:
            destination = Path(temporary) / "package"
            archive = ROOT / "训练集/cpu-a-guide-20261110-v1.zip"
            with patch.object(zipfile.ZipFile, "extractall", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    prepare(archive, destination, "A")
            self.assertFalse(destination.exists())
            self.assertEqual(prepare(archive, destination, "A")["task"], "A")

    @unittest.skipUnless(
        importlib.metadata.version("numpy") == "1.26.4",
        "Real continuation integration requires the isolated contest environment",
    )
    def test_failure_resume_preserves_attempt_and_completed_runs(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache/contest-tmp") as temporary:
            output = Path(temporary) / "run"
            original_worker = service.worker

            def fail_check(action, *args):
                if action == "check":
                    raise RuntimeError("injected verification failure")
                return original_worker(action, *args)

            with patch.object(service, "worker", side_effect=fail_check):
                with self.assertRaises(RuntimeError):
                    service.run(ROOT / "训练集", output, rounds=2, tasks=("A",))
            failures = list(output.glob("A/round-*/failure.json"))
            self.assertEqual(len(failures), 1)
            before = failures[0].read_bytes()
            results = service.run(ROOT / "训练集", output, rounds=2, resume=True, tasks=("A",))
            self.assertEqual(results[0]["rounds"], 2)
            self.assertEqual(failures[0].read_bytes(), before)
            records = {p: p.read_bytes() for p in output.glob("A/round-*.json")}
            again = service.run(ROOT / "训练集", output, rounds=2, resume=True, tasks=("A",))
            self.assertEqual(results, again)
            self.assertTrue(all(p.read_bytes() == content for p, content in records.items()))
            candidate = output / results[0]["checkpoint"]
            with candidate.open("ab") as stream:
                stream.write(b"corrupt")
            with self.assertRaises(ValueError):
                service.run(ROOT / "训练集", output, rounds=2, resume=True, tasks=("A",))


if __name__ == "__main__":
    unittest.main()
