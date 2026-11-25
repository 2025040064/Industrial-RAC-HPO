"""Participant callbacks for the official Harness SDK 1.0.2 template."""
from functools import lru_cache
import hashlib
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

from rac_hpo._io import atomic_text
from rac_hpo.contest.continuation import evaluate_diagnostics, evaluate_primary, fit_epochs
from rac_hpo.contest.packages import digest, write_json
from rac_hpo.contest.policy import accept_candidate
from rac_hpo.contest.rac_policy import ContestRACPolicy
from rac_hpo.contest.stage3_controls import bearing_deltas, controls, normalize_decision_text, parse_decision
from rac_hpo.contest.surrogate_evidence import shadow_evidence


TASKS = ("classification", "regression")
CONTRACTS = {
    "A": ("classification", "macro_f1", "higher"),
    "B": ("regression", "rmse", "lower"),
    "C": ("regression", "rmse", "lower"),
}
PREDICT_ARGV = ["python3", "/app/harness.py", "predict"]
STATE_FILE = "rac-round.json"
AUDIT_FILE = "selection-audit.jsonl"
WORKSPACE = Path("/workspace")
HISTORY_PROTOCOL = "contest-sdk-history-v2"


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
    if state.get("context") != context or state.get("round_index") != round_index - 1:
        return []
    records = state.get("records", [])
    if not records or records[-1].get("selected_sha256") != context["parent_sha256"]:
        return []
    return records


def transfer_from_state(directory, context, round_index):
    path = directory / STATE_FILE
    if not path.exists():
        return []
    state = json.loads(path.read_text())
    previous = state.get("context", {})
    if (state.get("round_index", round_index) >= round_index
            or any(previous.get(key) != value for key, value in context.items() if key != "parent_sha256")):
        return []
    records = state.get("archive", state.get("records", []))
    if not records:
        return []
    for index, record in enumerate(records):
        if (record.get("history_protocol") != HISTORY_PROTOCOL
                or record.get("selected_sha256") != (record.get("candidate_sha256") if record.get("accepted")
                                                       else record.get("parent_sha256"))
                or (index and (record.get("round") != records[index - 1].get("round", -2) + 1
                               or record.get("parent_sha256") != records[index - 1].get("selected_sha256")))):
            return []
    last = records[-1]
    expected = last.get("selected_sha256")
    if (last.get("round") != round_index - 1 or previous.get("parent_sha256") != last.get("parent_sha256")
            or expected != (last.get("candidate_sha256") if last.get("accepted") else last.get("parent_sha256"))):
        return []
    if expected != context["parent_sha256"]:
        return []
    return records


def train(rnd):
    round_started = time.monotonic()
    round_cpu_started = time.process_time()
    mode = controls(os.environ)
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
    preprocessing = {key: (model.meta[key][:] if isinstance(model.meta[key], list) else model.meta[key]) for key in
                     ("task", "profile", "paths", "classes", "target_mean", "target_scale")}
    parent_mean, parent_scale = model.mean.copy(), model.scale.copy()
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
    preload_cpu = time.process_time() - round_cpu_started

    work = WORKSPACE / f"round-{rnd.round_index:02}-{uuid4().hex}"
    work.mkdir()
    state = rnd.state_workspace(work / "state")
    group_projection = {"metadata_enabled": rnd.task.get("public_projection", {}).get("source_metadata") is True,
                        "train": train_groups, "validation": validation_groups}
    groups_sha = hashlib.sha256(json.dumps(group_projection, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False).encode("utf-8")).hexdigest()
    context = {"dataset": dataset, "parent_sha256": parent_sha, "train_sha256": train_set["sha256"],
               "validation_sha256": validation["sha256"], "groups_sha256": groups_sha,
               "history_protocol": HISTORY_PROTOCOL, "metric": metric, "direction": direction}
    audit_path = state / AUDIT_FILE
    previous_audit = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""
    if previous_audit and not previous_audit.endswith("\n"):
        raise ValueError("Selection audit is incomplete")
    prior_rows = [json.loads(line) for line in previous_audit.splitlines()]
    if prior_rows:
        last = prior_rows[-1]
        if (last.get("task") == dataset and last.get("round") == rnd.round_index - 1
                and last.get("selected_sha256") != parent_sha):
            raise ValueError("Platform parent differs from the previously selected checkpoint")
    records = record_from_state(state, context, rnd.round_index)
    archive = transfer_from_state(state, context, rnd.round_index)
    old_state = json.loads((state / STATE_FILE).read_text()) if (state / STATE_FILE).exists() else {}
    retired_archives = old_state.get("retired_archives", [])
    old_archive = old_state.get("archive", old_state.get("records", []))
    if old_archive and not archive:
        retired_archives = [*retired_archives, {"context": old_state.get("context"), "records": old_archive}]
        records = []
    current_rounds = {record["round"] for record in records}
    transfer = [record for record in archive if record["round"] not in current_rounds]
    sdk_cpu_started = time.process_time()
    history = rnd.history()
    sdk_cpu = time.process_time() - sdk_cpu_started
    # Read the host's completed round numbers for the model. Numeric search
    # observations come from the state bound to the exact parent and split.
    history_summary = [{"id": row["id"], "round_index": row.get("round_index")} for row in history]
    old = platform_metric(rnd.frame.get("current_validation"), metric)

    with threadpool_limits(limits=1):
        validation_started = time.process_time()
        baseline = evaluate_diagnostics(model, validation, validation_groups)
        local_parent = evaluate_primary(model, validation)
        validation_cpu = time.process_time() - validation_started
        proof = shadow_evidence(records, parent_sha, rnd.round_index)
        policy = ContestRACPolicy(dataset, {"diagnostics": baseline, "surrogate_evidence": proof}, transfer_mode=mode["transfer_mode"],
                                  surrogate_mode=mode["surrogate_mode"], cost_mode=mode["cost_mode"],
                                  bearing_mode=mode["bearing_mode"], enforce_shadow_evidence=True)
        policy.transfer_cost_weight = .05 if mode["cost_mode"] in {"transfer", "both"} else 0.0
        if dataset != "A" and train_groups is None:
            policy.space["sampling_level"]["high"] = 1
        transfer_enabled = mode["transfer_mode"] != "off"
        prior_audit = {row.get("round"): row for row in prior_rows if isinstance(row, dict)}
        enriched_transfer = []
        for old_record in transfer:
            copy = dict(old_record)
            prior = prior_audit.get(copy.get("round"), {})
            if ("parent_regime_errors" not in copy and prior.get("task") == dataset
                    and prior.get("parent_sha256") == copy.get("parent_sha256")
                    and prior.get("train_sha256") == context["train_sha256"]
                    and prior.get("validation_sha256") == context["validation_sha256"]
                    and prior.get("groups_sha256") == groups_sha
                    and isinstance(prior.get("objective_config"), dict)):
                copy["parent_regime_errors"] = prior["objective_config"].get("baseline_errors")
            enriched_transfer.append(copy)
        search_started = time.process_time()
        proposal, trace = policy.propose(
            model.meta, records, transfer_records=enriched_transfer if transfer_enabled else (),
            round_index=rnd.round_index,
        )
        trace["shadow_activation_evidence"] = proof
        search_cpu = time.process_time() - search_started
        params = trace["params"].copy()
        recommended_params = params.copy()
        recommended_proposal = proposal.copy()
        alternative = {**params, "learning_rate": max(1e-5, params["learning_rate"] / 2), "sampling_level": 1,
                       "epochs": 1}
        prompt_payload = {
                "request": "Select only RAC or conservative. Return JSON with selected_option, reason_codes and risk.",
                "allowed_reason_codes": ["history", "risk", "constraint", "cost", "uncertainty", "conservative", "other"],
                "allowed_risk": ["low", "medium", "high", "unknown"],
                "task": dataset, "metric": metric, "metric_direction": direction,
                "platform_parent_metric": old,
                "history": history_summary, "same_parent_observations": [
                    {"round": row["round"], "objective": row["robust_objective"],
                     "training_seconds": row["training_seconds"], "params": row["rac_params"]}
                    for row in records
                ],
                "transfer_history_rounds": trace["transfer_history_rounds"],
                "parent_regime_errors": policy.objective_config["baseline_errors"],
                "surrogate_quality": trace.get("forward_validation"),
                "constraint_risks": {"bearing_guard_available": dataset == "B" and validation_groups is not None,
                                     "predictions_are_not_acceptance": True},
                "rac": params, "conservative": alternative, "search": trace["method"],
            }
        prompt_text = json.dumps(prompt_payload, allow_nan=False)
        model_started, model_cpu_started = time.monotonic(), time.process_time()
        receipt = rnd.model(
            [{"role": "user", "content": prompt_text}],
            temperature=0, enable_thinking=False, max_tokens=min(128, rnd.max_output_tokens),
        )
        model_latency = time.monotonic() - model_started
        sdk_cpu += time.process_time() - model_cpu_started
        raw_answer = receipt.text
        parsed = parse_decision(raw_answer)
        action = parsed["action"]
        if action != "rac":
            params = alternative
            proposal.update(alternative, strategy="uniform")
            proposal.pop("target_class", None)
            proposal.pop("sampling_multiplier", None)
        for key in ("batch_size", "learning_rate"):
            model.meta[key] = params[key]
        model.validate()
        started = time.monotonic()
        training_cpu_started = time.process_time()
        fit_epochs(model, train_set, params["epochs"], proposal, train_groups)
        training_cpu = time.process_time() - training_cpu_started
        duration = time.monotonic() - started
        validation_started = time.process_time()
        candidate_diagnostics = evaluate_diagnostics(model, validation, validation_groups)
        score = policy.score(candidate_diagnostics)
        candidate_dir = work / "candidate"
        candidate_dir.mkdir()
        candidate_path = candidate_dir / "checkpoint.npz"
        model.save(candidate_path)
        saved_model = load_model(candidate_path, task, dataset)
        if (any(saved_model.meta[key] != value for key, value in preprocessing.items())
                or not np.array_equal(saved_model.mean, parent_mean)
                or not np.array_equal(saved_model.scale, parent_scale)):
            raise ValueError("Candidate preprocessing differs from the parent checkpoint")
        local_candidate = evaluate_primary(saved_model, validation)
        validation_cpu += time.process_time() - validation_started

    if digest(parent) != parent_sha:
        raise ValueError("Parent checkpoint changed during continuation")

    limit = rnd.limits.get("candidate_upload_bytes_per_round", 64 * 1024 * 1024)
    if candidate_path.stat().st_size > min(limit, 64 * 1024 * 1024):
        raise ValueError("Candidate exceeds the platform upload limit")
    hypothesis = "A small CPU continuation from the platform parent may improve public validation."
    change = "Updated the existing checkpoint weights and Adam state on the current public training projection."
    config = {"params": params, "model_action": action, "strategy": proposal["strategy"],
              "parent_sha256": parent_sha, "cpu_threads": 1}
    if proposal["strategy"] == "class_focus":
        config.update(target_class=proposal["target_class"], sampling_multiplier=proposal["sampling_multiplier"])
    sdk_cpu_started = time.process_time()
    submission = rnd.submit_candidate(candidate_dir, hypothesis=hypothesis, change_summary=change,
                                      configuration=config, seed=model.meta["seed"],
                                      checkpoint_paths=[candidate_path.name], predict_argv=PREDICT_ARGV)
    sdk_cpu += time.process_time() - sdk_cpu_started
    new = platform_metric(submission.get("summary"), metric)
    improved = old is not None and new is not None and (new > old if direction == "higher" else new < old)
    parent_matches = old is not None and math.isclose(old, local_parent, rel_tol=1e-7, abs_tol=1e-8)
    candidate_matches = new is not None and math.isclose(new, local_candidate, rel_tol=1e-7, abs_tol=1e-8)
    locally_improved = local_candidate > local_parent if direction == "higher" else local_candidate < local_parent
    bearing_gate = None
    if improved and dataset == "B" and validation_groups is not None:
        bearing_gate = accept_candidate(dataset, baseline, candidate_diagnostics, old, new)
    objective_improved = score["robust_objective"] < policy.baseline_objective
    accepted = (improved and parent_matches and candidate_matches and locally_improved
                and bearing_gate is not False and objective_improved)
    if accepted:
        reason = "Platform primary metric and local fixed robustness objective improved."
    elif old is None or new is None:
        reason = "Kept the platform parent because a platform metric was missing or invalid."
    elif not parent_matches or not candidate_matches:
        reason = "Kept the platform parent because platform and local checkpoint metrics differ."
    elif not improved:
        reason = "Kept the platform parent because the platform primary metric did not improve."
    elif not locally_improved:
        reason = "Kept the platform parent because the local checkpoint primary metric did not improve."
    elif bearing_gate is False:
        reason = "Kept the platform parent because the local per-bearing RMSE guard failed."
    else:
        reason = "Kept the platform parent because the local fixed robustness objective did not improve."
    candidate_sha = digest(candidate_path)
    selected_id = submission["artifact_id"] if accepted else rnd.parent.artifact_id
    selected_sha = candidate_sha if accepted else parent_sha
    gates = {"parent_metric_matches": parent_matches, "candidate_metric_matches": candidate_matches,
             "platform_primary_improved": improved, "local_primary_improved": locally_improved,
             "bearing_gate": bearing_gate, "objective_improved": objective_improved}
    response_info = receipt.response if isinstance(receipt.response, dict) else {}
    usage = response_info.get("usage") if isinstance(response_info.get("usage"), dict) else {}
    token_usage = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                   if type(usage.get(key)) is int and usage[key] >= 0}
    model_name = response_info.get("model")
    model_name = model_name[:256] if isinstance(model_name, str) else None
    reported_cost = response_info.get("cost", usage.get("cost"))
    if (isinstance(reported_cost, bool) or not isinstance(reported_cost, (int, float))
            or not math.isfinite(reported_cost) or reported_cost < 0):
        reported_cost = None
    decision = {"recommended_params": recommended_params, "recommended_proposal": recommended_proposal,
                "model_response": raw_answer, "normalized_response": normalize_decision_text(raw_answer),
                "model_response_valid": parsed["valid"],
                "reason_codes": parsed["reason_codes"], "risk": parsed["risk"], "response_format": parsed["format"],
                "response_reason": parsed.get("reason"),
                "model_id": model_name, "token_usage": token_usage, "cost": reported_cost,
                "model_latency_seconds": model_latency,
                "prompt_sha256": hashlib.sha256(prompt_text.encode('utf-8')).hexdigest(),
                "model_action": action, "final_params": params.copy(), "training_proposal": proposal.copy()}
    bearing = bearing_deltas(baseline, candidate_diagnostics) if dataset == "B" else None
    history_usage = {"same_parent_available": len(records),
                     "same_parent_used_rounds": ([] if trace["method"] == "global_exploration"
                                                 else trace.get("history_rounds", [])),
                     "same_parent_valid_rounds": trace.get("history_rounds", []),
                     "archive_available": len(archive), "transfer_candidates": len(transfer),
                     "transfer_enabled": transfer_enabled, "transfer_used_rounds": trace.get("transfer_history_rounds", []),
                     "excluded_history": trace.get("excluded_history", []), "search_method": trace["method"]}
    record = {"round": rnd.round_index, "rac_params": params, "diagnostics": candidate_diagnostics,
              "history_protocol": HISTORY_PROTOCOL, "parent_sha256": parent_sha, "selected_sha256": selected_sha,
              "parent_regime_errors": policy.objective_config["baseline_errors"],
              "parent_bearing_rmse": policy.parent_bearing_rmse if dataset == "B" else None,
              "robust_objective": score["robust_objective"], "parent_objective": policy.baseline_objective,
              "training_seconds": duration, "training_cpu_seconds": training_cpu,
              "bearing_comparison": bearing,
              "parent_metric": old, "candidate_metric": new, "accepted": accepted,
              "bearing_gate": bearing_gate, "validation_metadata_available": validation_groups is not None,
              "artifact_id": submission["artifact_id"], "candidate_sha256": candidate_sha,
              "local_parent_metric": local_parent, "local_candidate_metric": local_candidate,
              "gates": gates, "reason": reason, "selected_artifact_id": selected_id,
              "model_call_id": receipt.call_id, "history_ids": [row["id"] for row in history],
              "trace": trace, "configuration": config, "decision": decision, "history_usage": history_usage,
              "elapsed_seconds": time.monotonic() - round_started}
    write_json(work / STATE_FILE, {
        "context": context, "round_index": rnd.round_index, "records": [*records, record],
        "archive": [*archive, record], "retired_archives": retired_archives,
    })
    # Only the writable state copy is updated; SDK state remains immutable.
    (work / STATE_FILE).replace(state / STATE_FILE)
    audit = {"round": rnd.round_index, "task": dataset, "metric": metric, "direction": direction,
             "parent_artifact_id": rnd.parent.artifact_id, "parent_sha256": parent_sha,
             "parent_checkpoint": checkpoint_name(rnd.parent.descriptor["checkpoint_paths"]),
             "candidate_artifact_id": submission["artifact_id"], "candidate_sha256": candidate_sha,
             "candidate_checkpoint": candidate_path.name,
             "selected_artifact_id": selected_id, "selected_sha256": selected_sha,
             "selected_checkpoint": checkpoint_name(rnd.parent.descriptor["checkpoint_paths"]) if not accepted
                                    else candidate_path.name,
             "parent_metric": old, "candidate_metric": new,
             "local_parent_metric": local_parent, "local_candidate_metric": local_candidate,
             "parent_objective": policy.baseline_objective, "candidate_objective": score["robust_objective"],
             "normalized_group_errors": score["normalized_group_errors"],
             "objective_config": policy.objective_config, "parent_diagnostics": baseline,
             "candidate_diagnostics": candidate_diagnostics,
             "metric_match_tolerance": {"relative": 1e-7, "absolute": 1e-8},
             "selection_rule": "platform_and_local_primary_strictly_improve AND metrics_match AND "
                               "bearing_guard_if_available AND candidate_J < parent_J",
             "gates": gates, "accepted": accepted, "configuration": config, "seed": model.meta["seed"],
             "reason": reason, "train_sha256": train_set["sha256"], "validation_sha256": validation["sha256"],
             "groups_sha256": groups_sha, "training_seconds": duration, "decision": decision,
             "training_cpu_seconds": training_cpu,
             "cpu_breakdown_seconds": {"preload": preload_cpu, "search": search_cpu, "training": training_cpu,
                                       "validation": validation_cpu, "sdk_rpc": sdk_cpu,
                                       "process_until_audit": time.process_time() - round_cpu_started},
             "bearing_comparison": bearing, "controls": mode,
             "history_usage": history_usage, "search_trace": trace}
    atomic_text(audit_path, previous_audit + json.dumps(audit, ensure_ascii=False, allow_nan=False) + "\n")
    rnd.save_state(state)
    rnd.finish(selected_artifact_id=selected_id,
               hypothesis=hypothesis, change_summary=change, configuration=config, seed=model.meta["seed"],
               reason=reason, history_ids=record["history_ids"], model_call_ids=[receipt.call_id])
