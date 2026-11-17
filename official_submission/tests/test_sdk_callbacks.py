"""SDK 1.0.2 protocol tests using real public checkpoints and a local host."""
import base64
from collections import deque
from io import StringIO
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SUBMISSION = ROOT / "official_submission"
SDK = os.environ.get("CONTEST_SDK_SOURCE")
IMAGE = os.environ.get("CONTEST_TEST_IMAGE")


@unittest.skipUnless(SDK, "set CONTEST_SDK_SOURCE to the verified extracted SDK")
class SDKCallbacksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rac_hpo.contest.packages import prepare

        cache = ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(prefix="official-sdk-test-", dir=cache)
        cls.addClassCleanup(temp.cleanup)
        cls.root = Path(temp.name)
        cls.packages = {}
        for task in ("A", "B", "C"):
            archive, = (ROOT / "训练集").glob(f"cpu-{task.lower()}-*.zip")
            package = cls.root / task
            prepare(archive, package, task)
            cls.packages[task] = package
        paths = [str(SUBMISSION), SDK, str(cls.packages["A"])]
        sys.path[:0] = paths
        cls.addClassCleanup(lambda: [sys.path.remove(path) for path in paths])
        cls.env = {**os.environ, "PYTHONPATH": os.pathsep.join([*paths, str(ROOT / "src")]),
                   "CONTEST_SUBMISSION": "contest_submission", "PYTHONDONTWRITEBYTECODE": "1"}

    def docker_command(self, operation, *, mounts=(), variables=None):
        command = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cpus", "1",
                   "--cap-drop", "ALL", "--user", "65534:65534",
                   "--security-opt", "no-new-privileges", "--tmpfs", "/workspace:rw,mode=1777",
                   "--tmpfs", "/tmp:rw,mode=1777"]
        for source, target in mounts:
            command.extend(("--mount", f"type=bind,source={source},target={target},readonly"))
        for key, value in (variables or {}).items():
            command.extend(("--env", f"{key}={value}"))
        return [*command, IMAGE, operation]

    def test_describe_and_prediction_streams(self):
        from contest_submission import CONTRACTS

        harness = str(Path(SDK) / "template" / "harness.py")
        describe_command = self.docker_command("describe") if IMAGE else [sys.executable, harness, "describe"]
        result = subprocess.run(describe_command, env=self.env, text=True,
                                capture_output=True, check=True, timeout=30)
        frame = json.loads(result.stdout)
        self.assertEqual(frame["protocol"], "contest.harness.workspace.v2")
        self.assertEqual(frame["model_access"], "host_gateway_rpc")
        self.assertEqual(frame["tasks"], ["classification", "regression"])
        for dataset, package in self.packages.items():
            with self.subTest(dataset=dataset):
                task, _, _ = CONTRACTS[dataset]
                artifact = {"checkpoint_paths": ["checkpoint.npz"], "code_paths": [],
                            "predict_argv": ["python3", "/app/harness.py", "predict"]}
                context = {"protocol": "contest.predict-context.v1", "dataset_key": dataset,
                           "task": task, "artifact_id": "test-parent", "artifact": artifact}
                env = {**self.env, "CONTEST_PREDICTION_CONTEXT": json.dumps(context),
                       "CONTEST_ARTIFACT_PATH": str(package / "checkpoint.npz")}
                # Replace only the container's fixed test mount path in this child.
                script = ("import importlib, pathlib, sys\n"
                          "importlib.import_module('contest_harness.predict').model_dir = "
                          "lambda: pathlib.Path(sys.argv[1])\n"
                          "from contest_harness.cli import main\n"
                          "raise SystemExit(main(['harness.py', 'predict']))")
                command = [sys.executable, "-c", script, str(package)]
                if IMAGE:
                    command = self.docker_command(
                        "predict", mounts=[(package / "checkpoint.npz", "/model/checkpoint.npz")],
                        variables={"CONTEST_PREDICTION_CONTEXT": json.dumps(context),
                                   "CONTEST_ARTIFACT_PATH": "/model/checkpoint.npz"},
                    )
                with subprocess.Popen(command, env=env,
                                      text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE) as child:
                    try:
                        with (package / "public/validation.jsonl").open() as rows:
                            for _ in range(2):
                                row = json.loads(next(rows))
                                child.stdin.write(json.dumps({"task": task, "inputs": row["inputs"]}) + "\n")
                                child.stdin.flush()
                                self.assertTrue(select.select([child.stdout], [], [], 20)[0])
                                prediction = json.loads(child.stdout.readline())["outputs"]
                                if task == "classification":
                                    self.assertIn(prediction[0]["label"], {
                                        "Acetone", "Acetaldehyde", "Ammonia", "Ethanol", "Ethylene", "Toluene",
                                    })
                                else:
                                    self.assertGreaterEqual(prediction["value"], 0.0)
                        child.stdin.close()
                        self.assertEqual(child.wait(timeout=10), 0, child.stderr.read())
                    finally:
                        if child.poll() is None:
                            child.kill()

    def run_round(self, dataset, *, number=1, incoming=None, option="conservative",
                  measure=True, corrupt_parent=False, model_callback=None, mounted_parent=None,
                  source_metadata=False, transfer_enabled=True):
        from baselines.data import read_dataset
        from baselines.model import Model
        from baselines.train import metrics
        from contest_harness import Round
        from contest_harness.errors import HarnessError
        from contest_submission import CONTRACTS, train
        from rac_hpo.contest.packages import digest

        package = self.packages[dataset]
        parent = mounted_parent or package / "checkpoint.npz"
        parent_model = Model.load(parent)
        task, key, direction = CONTRACTS[dataset]
        validation_path = package / "public/validation.jsonl"
        validation = read_dataset(validation_path, task, parent_model.meta["classes"], parent_model.meta["paths"])
        sha = digest(parent)
        root = Path(tempfile.mkdtemp(prefix=f"round-{dataset}-", dir=self.root))
        start = {
            "protocol": "contest.harness.workspace.v2", "prompt": "Local test prompt",
            "prompt_version": "industrial-workspace-flexible-v3", "dataset_key": dataset, "round_index": number,
            "task_contract": {"task": task, "metric": key, "metric_direction": direction,
                              "public_projection": {"train_path": str(package / "public/train.jsonl"),
                                                    "validation_path": str(validation_path),
                                                    "source_metadata": source_metadata}},
            "parent_checkpoint_sha256": sha,
            "parent_artifact": {"artifact_id": "parent", "artifact": {"checkpoint_paths": [parent.name],
                                                                     "code_paths": []},
                                "files": [{"path": parent.name, "sha256": "0" * 64 if corrupt_parent else sha}]},
            "artifacts": [], "model_name": "local-stand-in", "max_output_tokens": 128,
            "current_validation": {"metrics": metrics(parent_model, validation)},
            "state_path": str(incoming) if incoming else None,
        }
        replies = deque([start])
        sent = {}
        calls = []
        state = root / "host-state"
        stub_call = f"offline-call-{number}"

        class Host(StringIO):
            def write(self, line):
                frame = json.loads(line)
                kind = frame["type"]
                sent[kind] = frame
                reply = {"id": frame.get("id")}
                if kind == "history_request":
                    reply.update(type="history_response", records=[
                        {"id": f"round-{n}", "round_index": n} for n in range(1, number)
                    ])
                elif kind == "model_request":
                    if model_callback is None:
                        response = {"choices": [{"message": {"content": option}}]}
                        call = stub_call
                    else:
                        options = {key: frame[key] for key in ("max_tokens", "temperature", "enable_thinking")}
                        call, response = model_callback(frame["messages"], options)
                    calls.append(call)
                    reply.update(type="model_response", call_id=call, response=response)
                elif kind == "candidate_request":
                    self_test.assertEqual(frame["parent_checkpoint_sha256"], sha)
                    self_test.assertEqual(frame["artifact"]["predict_argv"], ["python3", "/app/harness.py", "predict"])
                    self_test.assertEqual(len(frame["files"]), 1)
                    candidate = root / "measured.npz"
                    candidate.write_bytes(base64.b64decode(frame["files"][0]["data_base64"]))
                    child = Model.load(candidate)
                    params = frame["configuration"]["params"]
                    self_test.assertEqual(child.meta["epochs"], parent_model.meta["epochs"] + params["epochs"])
                    self_test.assertEqual(child.meta["learning_rate"], params["learning_rate"])
                    self_test.assertEqual(child.meta["batch_size"], params["batch_size"])
                    reply.update(type="candidate_response", artifact_id="candidate",
                                 summary={"metrics": metrics(child, validation) if measure else {}})
                elif kind == "state_request":
                    state.mkdir()
                    for item in frame["files"]:
                        (state / item["path"]).write_bytes(base64.b64decode(item["data_base64"]))
                    reply.update(type="state_response", state_sha256="simulated-digest")
                elif kind == "round_complete":
                    self_test.assertEqual(frame["record"]["model_call_ids"], calls)
                    self_test.assertEqual(len(calls), 1)
                    reply.update(type="round_ack", accepted=True)
                replies.append(reply)
                return len(line)

            def readline(self):
                return json.dumps(replies.popleft()) + "\n"

        self_test = self
        host = Host()
        if IMAGE:
            projection = start["task_contract"]["public_projection"]
            projection.update(train_path="/data/train.jsonl", validation_path="/data/validation.jsonl")
            mounts = [(package / "public", "/data"), (parent, f"/previous/{parent.name}")]
            if incoming:
                mounts.append((incoming, "/state"))
                start["state_path"] = "/state"
            with subprocess.Popen(self.docker_command("train", mounts=mounts,
                                                     variables={"RAC_TRANSFER_HISTORY": "1" if transfer_enabled else "0"}), text=True, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
                try:
                    child.stdin.write(host.readline())
                    child.stdin.flush()
                    while "round_complete" not in sent:
                        self.assertTrue(select.select([child.stdout], [], [], 60)[0])
                        line = child.stdout.readline()
                        if not line:
                            child.wait(timeout=10)
                            self.fail(child.stderr.read())
                        frame = json.loads(line)
                        if frame["type"] == "round_failed":
                            raise HarnessError(frame["error"])
                        host.write(line)
                        child.stdin.write(host.readline())
                        child.stdin.flush()
                    child.stdin.close()
                    self.assertEqual(child.wait(timeout=20), 0, child.stderr.read())
                finally:
                    if child.poll() is None:
                        child.kill()
        else:
            rnd = Round.start(reader=host, writer=host)
            rnd.parent.root = parent.parent
            with patch("contest_submission.WORKSPACE", root), patch.dict(
                os.environ, {"RAC_TRANSFER_HISTORY": "1" if transfer_enabled else "0"}
            ):
                train(rnd)
        self.assertEqual(digest(parent), sha)
        self.assertEqual(list(sent), ["history_request", "model_request", "candidate_request", "state_request",
                                      "round_complete"])
        return state, sent

    def test_train_all_tasks_with_real_weights_and_measurements(self):
        for dataset in self.packages:
            with self.subTest(dataset=dataset):
                state, sent = self.run_round(dataset)
                result = sent["round_complete"]["record"]
                self.assertEqual(result["configuration"]["model_action"], "conservative")
                self.assertEqual(result["configuration"]["params"]["epochs"], 1)
                stored = json.loads((state / "rac-round.json").read_text())["records"][0]
                self.assertIsNotNone(stored["candidate_metric"])
                self.assertFalse(stored["validation_metadata_available"])

    def test_state_inherits_and_missing_measurement_keeps_parent(self):
        state, first = self.run_round("A", measure=False)
        state_path = state / "rac-round.json"
        original = state_path.read_bytes()
        self.assertEqual(first["round_complete"]["record"]["selected_artifact_id"], "parent")
        next_state, second = self.run_round("A", number=2, incoming=state, option="RAC")
        self.assertEqual(state_path.read_bytes(), original)
        self.assertEqual(second["round_complete"]["record"]["history_ids"], ["round-1"])
        records = json.loads((next_state / state_path.name).read_text())["records"]
        self.assertEqual([record["round"] for record in records], [1, 2])
        self.assertEqual(records[1]["trace"]["history_rounds"], [1])

    def test_invalid_parent_digest_blocks_training(self):
        from contest_harness.errors import HarnessError

        with self.assertRaises(HarnessError) as raised:
            self.run_round("A", corrupt_parent=True)
        self.assertEqual(raised.exception.code, "PARENT_DIGEST_MISMATCH")

    def test_changed_platform_parent_starts_new_comparable_history(self):
        state, _ = self.run_round("A")
        next_parent = state.parent / "measured.npz"
        next_state, _ = self.run_round("A", number=2, incoming=state, mounted_parent=next_parent)
        saved = json.loads((next_state / "rac-round.json").read_text())
        from rac_hpo.contest.packages import digest

        self.assertEqual(saved["context"]["parent_sha256"], digest(next_parent))
        self.assertEqual([row["round"] for row in saved["records"]], [2])
        self.assertEqual([row["round"] for row in saved["archive"]], [1, 2])
        self.assertEqual(saved["records"][0]["trace"]["transfer_history_rounds"], [1])

    def test_unrelated_parent_does_not_reuse_transfer_history(self):
        state, _ = self.run_round("A", measure=False)
        unrelated = self.packages["A"] / "checkpoint.npz"
        saved = json.loads((state / "rac-round.json").read_text())
        saved["context"]["parent_sha256"] = "0" * 64
        (state / "rac-round.json").write_text(json.dumps(saved))
        next_state, _ = self.run_round("A", number=2, incoming=state, mounted_parent=unrelated)
        result = json.loads((next_state / "rac-round.json").read_text())
        self.assertEqual(result["records"][0]["trace"]["transfer_history_rounds"], [])

    def test_transfer_can_be_disabled_for_existing_policy(self):
        state, _ = self.run_round("A", transfer_enabled=False)
        parent = state.parent / "measured.npz"
        state, _ = self.run_round("A", number=2, incoming=state, mounted_parent=parent, transfer_enabled=False)
        record = json.loads((state / "rac-round.json").read_text())["records"][0]
        self.assertEqual(record["trace"]["method"], "checkpoint_reference")
        self.assertEqual(record["trace"]["transfer_history_rounds"], [])

    def test_explicit_bearing_metadata_enables_group_guard(self):
        state, sent = self.run_round("B", option="RAC", source_metadata=True)
        saved = json.loads((state / "rac-round.json").read_text())["records"][0]
        self.assertTrue(saved["validation_metadata_available"])
        self.assertLess(saved["candidate_metric"], saved["parent_metric"])
        self.assertFalse(saved["bearing_gate"])
        self.assertEqual(sent["round_complete"]["record"]["selected_artifact_id"], "parent")
