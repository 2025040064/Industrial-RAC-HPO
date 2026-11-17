"""Participant callbacks for the official Harness SDK 1.0.2 template."""
from functools import lru_cache
import json
import math
import os
from pathlib import Path, PurePosixPath
import time
from uuid import uuid4

from baselines.data import flatten, read_dataset
from baselines.model import Model
import numpy as np
from threadpoolctl import threadpool_limits

from rac_hpo.contest.continuation import evaluate_diagnostics, fit_epochs
from rac_hpo.contest.packages import digest, write_json
from rac_hpo.contest.policy import accept_candidate
from rac_hpo.contest.rac_policy import ContestRACPolicy


TASKS = ("classification", "regression")
CONTRACTS = {
    "A": ("classification", "macro_f1", "higher"),
    "B": ("regression", "rmse", "lower"),
    "C": ("regression", "rmse", "lower"),
}
PREDICT_ARGV = ["python3", "/app/harness.py", "predict"]
STATE_FILE = "rac-round.json"
WORKSPACE = Path("/workspace")


def checkpoint_name(paths):
    if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], str):
        raise ValueError("Exactly one NPZ checkpoint is required")
    path = PurePosixPath(paths[0])
    if path.is_absolute() or ".." in path.parts or path.suffix != ".npz":
        raise ValueError("Invalid NPZ checkpoint path")
    return path.as_posix()


def load_model(path, task, dataset):
    if np.__version__ != "1.26.4":
        raise ValueError("Contest runtime requires numpy==1.26.4")
    model = Model.load(path)
    if (model.meta["task"] != task or model.meta["profile"] not in CONTRACTS
            or (dataset is not None and model.meta["profile"] != dataset)):
        raise ValueError("Checkpoint task or dataset differs from the platform contract")
    return model


@lru_cache(maxsize=1)
def prediction_model(path, task, dataset):
    return load_model(path, task, dataset)


def predict(sample, model_dir):
    root = model_dir.resolve()
    declared = sample.context["artifact"].get("checkpoint_paths") if sample.context else None
    path = Path(os.environ.get("CONTEST_ARTIFACT_PATH") or root / (
        checkpoint_name(declared) if declared is not None else "checkpoint.npz"
    ))
    if not path.is_absolute():
        path = root / path
    if not path.is_relative_to(root) or path.resolve() != path:
        raise ValueError("Prediction checkpoint must be a regular path within the artifact")
    if declared is not None and path != root / checkpoint_name(declared):
        raise ValueError("Prediction checkpoint differs from the context manifest")
    if os.environ.get("CONTEST_TASK", sample.task) != sample.task:
        raise ValueError("Prediction task conflicts with the environment")
    dataset = sample.dataset_key or os.environ.get("CONTEST_DATASET_KEY")
    model = prediction_model(path, sample.task, dataset)
    features, values = flatten(sample.inputs)
    if features != model.meta["paths"]:
        raise ValueError("Prediction feature schema differs from the checkpoint")
    prediction = model.predict(np.asarray([values], dtype=float))[0]
    if sample.task == "regression":
        return {"value": float(prediction)}
    # The platform scores the top label. Emit its actual probability and avoid ambiguous ties.
    top = int(np.argmax(prediction))
    return [{"label": model.meta["classes"][top], "score": float(prediction[top])}]


def projection_groups(view, split, dataset, contract, expected_ids):
    if contract.get("public_projection", {}).get("source_metadata") is not True:
        return None
    rows = view.training_rows() if split == "train" else view.validation_rows()
    groups = []
    for index, row in enumerate(rows):
        if index >= len(expected_ids) or row["id"] != expected_ids[index]:
            raise ValueError("Public projection changed during processing")
        meta = row.get("meta")
        if not isinstance(meta, dict):
            return None
        keys = {"A": ("source_batch",), "B": ("bearing",), "C": ("source_subset", "unit")}[dataset]
        values = [meta.get(key) for key in keys]
        if any(type(value) not in (str, int) or not str(value) or "/" in str(value) for value in values):
            return None
        groups.append("/".join(map(str, values)))
    if len(groups) != len(expected_ids):
        raise ValueError("Public projection changed during processing")
    return groups


def platform_metric(summary, name):
    if not isinstance(summary, dict):
        return None
    metrics = summary.get("metrics")
    value = metrics.get(name) if isinstance(metrics, dict) else summary.get(name)
    upper_bound = 1 if name == "macro_f1" else math.inf
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= upper_bound:
        return None
    return value


def record_from_state(directory, context, round_index):
    path = directory / STATE_FILE
    if not path.exists():
        return []
    state = json.loads(path.read_text())
    if state.get("context") != context or state.get("round_index", round_index) >= round_index:
        return []
    return state["records"]


def transfer_from_state(directory, context, round_index):
    path = directory / STATE_FILE
    if not path.exists():
        return []
    state = json.loads(path.read_text())
    previous = state.get("context", {})
    if (state.get("round_index", round_index) >= round_index
            or any(previous.get(key) != context[key]
                   for key in ("dataset", "train_sha256", "validation_sha256"))):
        return []
    records = state.get("archive", state.get("records", []))
    if not records:
        return []
    last = records[-1]
    expected = last.get("candidate_sha256") if last.get("accepted") else previous.get("parent_sha256")
    if expected != context["parent_sha256"]:
        return []
    return records


def train(rnd):
    round_started = time.monotonic()
    dataset = rnd.dataset_key
    task, metric, direction = CONTRACTS[dataset]
    if (rnd.task.get("dataset_key", dataset) != dataset or rnd.task.get("task") != task
            or rnd.task.get("metric") != metric or rnd.task.get("metric_direction") != direction):
        raise ValueError("Unsupported frozen task contract")
    parent = rnd.parent.path(checkpoint_name(rnd.parent.descriptor["checkpoint_paths"]))
    parent_sha = digest(parent)
    if rnd.parent.checkpoint_sha256.removeprefix("sha256:") != parent_sha:
        raise ValueError("Round parent checkpoint digest differs from the declared parent")
    model = load_model(parent, task, dataset)
    train_set, validation = [
        read_dataset(path, task, model.meta["classes"], model.meta["paths"])
        for path in (rnd.data.train_path, rnd.data.validation_path)
    ]
    if set(train_set["ids"]) & set(validation["ids"]):
        raise ValueError("Public train and validation samples overlap")
    train_groups = projection_groups(rnd.data, "train", dataset, rnd.task, train_set["ids"])
    validation_groups = projection_groups(rnd.data, "validation", dataset, rnd.task, validation["ids"])
    if train_groups is not None and validation_groups is not None and set(train_groups) & set(validation_groups):
        raise ValueError("Public train and validation units overlap")

    work = WORKSPACE / f"round-{rnd.round_index:02}-{uuid4().hex}"
    work.mkdir()
    state = rnd.state_workspace(work / "state")
    context = {"dataset": dataset, "parent_sha256": parent_sha, "train_sha256": train_set["sha256"],
               "validation_sha256": validation["sha256"]}
    records = record_from_state(state, context, rnd.round_index)
    archive = transfer_from_state(state, context, rnd.round_index)
    current_rounds = {record["round"] for record in records}
    transfer = [record for record in archive if record["round"] not in current_rounds]
    history = rnd.history()
    # Read the host's completed round numbers for the model. Numeric search
    # observations come from the state bound to the exact parent and split.
    history_summary = [{"id": row["id"], "round_index": row.get("round_index")} for row in history]
    old = platform_metric(rnd.frame.get("current_validation"), metric)

    with threadpool_limits(limits=1):
        baseline = evaluate_diagnostics(model, validation, validation_groups)
        policy = ContestRACPolicy(dataset, {"diagnostics": baseline})
        if dataset != "A" and train_groups is None:
            policy.space["sampling_level"]["high"] = 1
        transfer_enabled = os.environ.get("RAC_TRANSFER_HISTORY") == "1"
        proposal, trace = policy.propose(
            model.meta, records, transfer_records=transfer if transfer_enabled else (),
            round_index=rnd.round_index if transfer_enabled else None,
        )
        params = trace["params"].copy()
        alternative = {**params, "learning_rate": max(1e-5, params["learning_rate"] / 2), "sampling_level": 1,
                       "epochs": 1}
        receipt = rnd.model(
            [{"role": "user", "content": json.dumps({
                "request": "Choose RAC or conservative. Return only RAC or conservative.",
                "task": dataset, "metric": metric, "metric_direction": direction,
                "platform_parent_metric": old,
                "history": history_summary, "same_parent_observations": [
                    {"round": row["round"], "objective": row["robust_objective"],
                     "training_seconds": row["training_seconds"], "params": row["rac_params"]}
                    for row in records
                ],
                "transfer_history_rounds": trace["transfer_history_rounds"],
                "rac": params, "conservative": alternative, "search": trace["method"],
            }, allow_nan=False)}],
            temperature=0, enable_thinking=False, max_tokens=min(128, rnd.max_output_tokens),
        )
        answer = receipt.text.strip().casefold()
        action = answer if answer in ("rac", "conservative") else "conservative_invalid_response"
        if action != "rac":
            params = alternative
            proposal.update(alternative, strategy="uniform")
        for key in ("batch_size", "learning_rate"):
            model.meta[key] = params[key]
        model.validate()
        started = time.monotonic()
        fit_epochs(model, train_set, params["epochs"], proposal, train_groups)
        duration = time.monotonic() - started
        candidate_diagnostics = evaluate_diagnostics(model, validation, validation_groups)
        score = policy.score(candidate_diagnostics)
        candidate_dir = work / "candidate"
        candidate_dir.mkdir()
        candidate_path = candidate_dir / "checkpoint.npz"
        model.save(candidate_path)

    limit = rnd.limits.get("candidate_upload_bytes_per_round", 64 * 1024 * 1024)
    if candidate_path.stat().st_size > min(limit, 64 * 1024 * 1024):
        raise ValueError("Candidate exceeds the platform upload limit")
    hypothesis = "A small CPU continuation from the platform parent may improve public validation."
    change = "Updated the existing checkpoint weights and Adam state on the current public training projection."
    config = {"params": params, "model_action": action, "strategy": proposal["strategy"],
              "parent_sha256": parent_sha, "cpu_threads": 1}
    if proposal["strategy"] == "class_focus":
        config.update(target_class=proposal["target_class"], sampling_multiplier=proposal["sampling_multiplier"])
    submission = rnd.submit_candidate(candidate_dir, hypothesis=hypothesis, change_summary=change,
                                      configuration=config, seed=model.meta["seed"],
                                      checkpoint_paths=[candidate_path.name], predict_argv=PREDICT_ARGV)
    new = platform_metric(submission.get("summary"), metric)
    improved = old is not None and new is not None and (new > old if direction == "higher" else new < old)
    bearing_gate = None
    if improved and dataset == "B" and validation_groups is not None:
        bearing_gate = accept_candidate(dataset, baseline, candidate_diagnostics, old, new)
    accepted = improved and bearing_gate is not False and score["robust_objective"] < policy.baseline_objective
    if accepted:
        reason = "Platform primary metric and local fixed robustness objective improved."
    elif old is None or new is None:
        reason = "Kept the platform parent because a platform metric was missing or invalid."
    elif not improved:
        reason = "Kept the platform parent because the platform primary metric did not improve."
    elif bearing_gate is False:
        reason = "Kept the platform parent because the local per-bearing RMSE guard failed."
    else:
        reason = "Kept the platform parent because the local fixed robustness objective did not improve."
    record = {"round": rnd.round_index, "rac_params": params, "diagnostics": candidate_diagnostics,
              "robust_objective": score["robust_objective"], "parent_objective": policy.baseline_objective,
              "training_seconds": duration,
              "parent_metric": old, "candidate_metric": new, "accepted": accepted,
              "bearing_gate": bearing_gate, "validation_metadata_available": validation_groups is not None,
              "artifact_id": submission["artifact_id"], "candidate_sha256": digest(candidate_path),
              "model_call_id": receipt.call_id, "history_ids": [row["id"] for row in history],
              "trace": trace, "configuration": config, "elapsed_seconds": time.monotonic() - round_started}
    write_json(work / STATE_FILE, {
        "context": context, "round_index": rnd.round_index, "records": [*records, record],
        "archive": [*archive, record],
    })
    # Only the writable state copy is updated; SDK state remains immutable.
    (work / STATE_FILE).replace(state / STATE_FILE)
    rnd.save_state(state)
    rnd.finish(selected_artifact_id=submission["artifact_id"] if accepted else rnd.parent.artifact_id,
               hypothesis=hypothesis, change_summary=change, configuration=config, seed=model.meta["seed"],
               reason=reason, history_ids=record["history_ids"], model_call_ids=[receipt.call_id])
