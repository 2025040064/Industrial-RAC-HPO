"""Append-only local experiments, selected-parent recovery and bounded subprocesses."""
import fcntl
from functools import partial
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from rac_hpo.contest.packages import digest, prepare, verify, write_json
from rac_hpo.contest.policy import local_decision, optimized_decision, accept_candidate
from rac_hpo.contest.sampler import SamplerPolicy
from rac_hpo._io import atomic_text


def read_json(path):
    return json.loads(Path(path).read_text())


def environment(threads):
    env = os.environ.copy()
    env.pop("PYTRIO_API_KEY", None)
    env.pop("SWANLAB_API_KEY", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in ("BASELINE_CPU_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        env[name] = str(threads)
    return env


def execute(command, cwd, log, threads, timeout):
    env = environment(threads)
    temporary = Path(log).parent / "tmp"
    temporary.mkdir(exist_ok=True)
    env["TMPDIR"] = str(temporary)
    try:
        with Path(log).open("xb") as stream:
            subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                           timeout=timeout, check=True)
    finally:
        if not any(temporary.iterdir()):
            temporary.rmdir()


def worker(action, package, output, threads, timeout, *extra):
    execute([sys.executable, "-m", "rac_hpo.contest.worker", action, str(package), str(output), *extra],
            package, output.with_suffix(".log"), threads, timeout)


def append_audit(path, row):
    """Publish a committed round once; rebuild a missing row after interruption."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        raise ValueError("Selection audit is incomplete")
    rows = [json.loads(line) for line in existing.splitlines()]
    same = [item for item in rows if item["round"] == row["round"]]
    if same:
        if len(same) != 1 or same[0] != row:
            raise ValueError("Selection audit differs from committed round")
        return
    if rows and rows[-1]["round"] >= row["round"]:
        raise ValueError("Selection audit rounds are out of order")
    atomic_text(path, existing + json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def run_task(task, archives, root, rounds, threads, timeout, policy, rac_policy_class=None,
             parent_mode="selected_checkpoint"):
    task_root = root / task
    task_root.mkdir(exist_ok=True)
    package = task_root / "package"
    if not package.exists():
        matches = list(archives.glob(f"cpu-{task.lower()}-*.zip"))
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one ZIP for {task}")
        prepare(matches[0], package, task)
    manifest = verify(package, task)
    audit_path = task_root / "audit.json"
    if not audit_path.exists():
        # Unique logs allow a failed audit to be retried without overwriting evidence.
        attempt = task_root / ("audit-" + uuid.uuid4().hex)
        attempt.mkdir()
        worker("audit", package, attempt / "result.json", threads, timeout)
        write_json(audit_path, read_json(attempt / "result.json"))
    audit = read_json(audit_path)
    metric = "macro_f1" if task == "A" else "rmse"
    sampler = isinstance(policy, SamplerPolicy)
    rac = rac_policy_class(task, audit) if rac_policy_class else None
    use_continuation_worker = sampler or policy is optimized_decision or rac is not None
    original = selected = package / "checkpoint.npz"
    selected_value = audit["baseline_metrics"][metric]
    selected_diagnostics = audit.get("diagnostics", {})
    selected_metadata = dict(audit["metadata"])
    if rac:
        selected_objective = rac.baseline_objective
        config_path = task_root / "rac_config.json"
        configuration = rac.configuration()
        if parent_mode == "selected_checkpoint":
            configuration["parent_mode"] = parent_mode
        if not config_path.exists():
            write_json(config_path, configuration)
        elif read_json(config_path) != configuration:
            raise ValueError("Saved RAC configuration differs from current protocol")
    history = []
    for number in range(1, rounds + 1):
        parent = original if rac and parent_mode == "original_checkpoint" else selected
        parent_sha = digest(parent)
        record_path = task_root / f"round-{number:02}.json"
        if record_path.exists():
            record = read_json(record_path)
            if record["parent_sha256"] != parent_sha:
                raise ValueError("Saved parent chain changed")
            checkpoint = task_root / record["candidate"]
            if digest(checkpoint) != record["checkpoint_sha256"]:
                raise ValueError("Saved candidate changed")
            if record["accepted"]:
                selected, selected_value = checkpoint, record["metrics"][metric]
                selected_diagnostics = record.get("diagnostics", {})
                selected_metadata.update({key: record["proposal"][key] for key in ("learning_rate", "batch_size")})
                if rac:
                    selected_objective = record["robust_objective"]
            if "selection_audit" in record:
                append_audit(task_root / "selection-audit.jsonl", record["selection_audit"])
            history.append(record)
            continue
        verify(package, task)
        attempt = task_root / f"round-{number:02}-{uuid.uuid4().hex}"
        attempt.mkdir()
        started = time.monotonic()
        context = {"task": task, "round": number, "metadata": audit["metadata"],
                   "baseline_metrics": audit["baseline_metrics"],
                   "selected_metric": selected_value, "history": history,
                   "diagnostics": audit.get("diagnostics", {})}
        write_json(attempt / "history.json", context)
        try:
            if rac:
                decision_started = time.monotonic()
                comparable = history if parent_mode == "original_checkpoint" else [
                    row for row in history if row["parent_sha256"] == parent_sha]
                proposal, trace = rac.propose(selected_metadata if parent_mode == "selected_checkpoint"
                                              else audit["metadata"], comparable)
                trace["decision_seconds"] = time.monotonic() - decision_started
                write_json(attempt / "rac.json", trace)
            else:
                proposal = policy.propose(context, attempt / "sampler.json") if sampler else policy(context)
            write_json(attempt / "decision.json", proposal)
            output = attempt / "training"
            mode = "--from-baseline" if parent == original else "--resume"
            command = [sys.executable, "-m", "baselines.train", "--profile", task,
                       "--train", "public/train.jsonl", "--validation", "public/validation.jsonl",
                       mode, str(parent), "--epochs", str(proposal["epochs"]),
                       "--learning-rate", str(proposal["learning_rate"]),
                       "--batch-size", str(proposal["batch_size"]), "--stage-id", f"round-{number:02}",
                       "--output", str(output)]
            if use_continuation_worker:
                command = [sys.executable, "-m", "rac_hpo.contest.worker", "train",
                           str(package), str(output), "--parent", str(parent),
                           "--proposal", str(attempt / "decision.json")]
            write_json(attempt / "command.json", command)
            execute(command, package, attempt / "training.log", threads, timeout)
            checked = attempt / "checked.json"
            worker("check", package, checked, threads, timeout,
                   "--parent", str(parent), "--candidate", str(output))
            verification = read_json(checked)
            candidate_path = output / "checkpoint.npz"
            candidate_sha = digest(candidate_path)
            if candidate_sha != verification["checkpoint_sha256"]:
                raise ValueError("Candidate checkpoint changed after verification")
            training = read_json(output / "training.json")
            if (digest(parent) != parent_sha
                    or training["parent_checkpoint_sha256"].removeprefix("sha256:") != parent_sha):
                raise ValueError("Parent checkpoint changed after training")
            parent_value = training["validation_before"][metric]
            if parent == selected and not math.isclose(parent_value, selected_value, rel_tol=1e-10, abs_tol=1e-10):
                raise ValueError("Selected checkpoint and validation metric do not match")
            value = verification["metrics"][metric]
            primary_improved = value > selected_value if task == "A" else value < selected_value
            accepted = primary_improved
            if use_continuation_worker:
                comparison_diagnostics = (selected_diagnostics if rac and parent_mode == "selected_checkpoint"
                                          else audit["diagnostics"])
                accepted = accept_candidate(task, comparison_diagnostics, verification["diagnostics"],
                                            selected_value, value)
            validation_gate = accepted
            objective_improved = None
            if rac:
                score = rac.score(verification["diagnostics"])
                objective_improved = score["robust_objective"] < selected_objective
                rac_record = {
                    **score, "previous_selected_objective": selected_objective,
                    "training_seconds": training["training_seconds"],
                    "validation_gate_passed": accepted, "objective_improved": objective_improved,
                    "decision_source": "rac_hpo", "rac_params": trace["params"],
                    "rac_trace": str((attempt / "rac.json").relative_to(task_root)),
                }
                accepted = accepted and objective_improved
            reason = ("accepted" if accepted else "primary_metric_not_improved" if not primary_improved
                      else "validation_guard_failed" if not validation_gate else "robust_objective_not_improved")
            selected_path = candidate_path if accepted else selected
            audit_row = {"round": number, "task": task, "metric": metric,
                         "direction": "higher" if task == "A" else "lower",
                         "parent_checkpoint": str(parent.relative_to(task_root)), "parent_sha256": parent_sha,
                         "candidate_checkpoint": str(candidate_path.relative_to(task_root)),
                         "candidate_sha256": candidate_sha,
                         "selected_checkpoint": str(selected_path.relative_to(task_root)),
                         "selected_sha256": candidate_sha if accepted else digest(selected),
                         "parent_metric": parent_value, "previous_selected_metric": selected_value,
                         "candidate_metric": value,
                         "parent_objective": (rac.baseline_objective if parent_mode == "original_checkpoint"
                                              else selected_objective) if rac else None,
                         "previous_selected_objective": selected_objective if rac else None,
                         "candidate_objective": score["robust_objective"] if rac else None,
                         "objective_config": rac.objective_config if rac else None,
                         "selection_rule": "primary_strictly_improves AND validation_guard AND "
                                           "candidate_J < selected_J_when_rac",
                         "candidate_diagnostics": verification.get("diagnostics", {}),
                         "gates": {"primary_improved": primary_improved, "validation_guard": validation_gate,
                                   "objective_improved": objective_improved},
                         "accepted": accepted, "reason": reason}
            record = {"task": task, "round": number, "purpose": "local_simulation_real_training",
                      "official_scoring_ready": False, "parent_sha256": parent_sha,
                      "proposal": proposal, "metrics": verification["metrics"],
                      "diagnostics": verification.get("diagnostics", {}),
                      "previous_selected_metric": selected_value, "accepted": accepted,
                      "candidate": str((output / "checkpoint.npz").relative_to(task_root)),
                      "checkpoint_sha256": verification["checkpoint_sha256"],
                      "elapsed_seconds": time.monotonic() - started,
                      "continuous_replay_equal": verification["continuous_replay_equal"], "selection_audit": audit_row,
                      "next_action": ("select_candidate" if rac else "continue_selected") if accepted
                      else "retain_previous_checkpoint"}
            if rac:
                record.update(rac_record)
            if sampler:
                record["decision_source"] = "pytrio_sampler" if policy.path else "pytrio_base"
                record["sampler_trace"] = str((attempt / "sampler.json").relative_to(task_root))
            write_json(record_path, record)
            append_audit(task_root / "selection-audit.jsonl", audit_row)
        except Exception as error:
            write_json(attempt / "failure.json", {"type": type(error).__name__,
                       "status": "failed", "elapsed_seconds": time.monotonic() - started})
            raise
        history.append(record)
        if accepted:
            selected, selected_value = output / "checkpoint.npz", value
            selected_diagnostics = verification.get("diagnostics", {})
            selected_metadata.update({key: proposal[key] for key in ("learning_rate", "batch_size")})
            if rac:
                selected_objective = score["robust_objective"]
        print(json.dumps({"task": task, "round": number, "metric": value,
                          "accepted": accepted, "selected": selected_value}), flush=True)
    summary = {"task": task, "rounds": len(history), "baseline": audit["baseline_metrics"][metric],
               "selected": selected_value, "metric": metric, "checkpoint": str(selected.relative_to(root)),
               "checkpoint_sha256": digest(selected), "archive_sha256": manifest["archive_sha256"],
               "purpose": "local_simulation_real_training", "official_scoring_ready": False}
    if rac:
        summary.update(baseline_objective=rac.baseline_objective, selected_objective=selected_objective,
                       parent_mode=parent_mode, decision_source="rac_hpo")
    target = task_root / "summary.json"
    if target.exists():
        if read_json(target) != summary:
            raise ValueError("Completed summary differs from reconstructed history")
    else:
        write_json(target, summary)
    return summary


def run(archives, output, rounds=10, threads=1, timeout=600, resume=False, tasks=("A", "B", "C"), policy_name="local_validation_rule_v1",
        sampler_model=None, sampler_path=None):
    if not 1 <= rounds <= 10 or not 1 <= threads <= 8 or timeout <= 0:
        raise ValueError("Invalid rounds, threads or timeout")
    policies = {"local_validation_rule_v1": local_decision, "task_aware_v3": optimized_decision}
    if policy_name == "pytrio_sampler" and not sampler_path:
        raise ValueError("Provide the full Sampler URI with --sampler-path or HARNESS_SAMPLER_PATH")
    if policy_name == "pytrio_base" and sampler_path:
        raise ValueError("Base-model policy does not accept a Sampler URI")
    policy = (SamplerPolicy(sampler_model, sampler_path)
              if policy_name in {"pytrio_base", "pytrio_sampler"} else policies.get(policy_name))
    rac_policy_class = None
    if policy_name == "rac_hpo":
        from rac_hpo.contest.rac_policy import LEGACY_PROTOCOL, PROTOCOL, ContestRACPolicy

        rac_policy_class = ContestRACPolicy
    elif policy is None:
        raise ValueError(f"Unknown contest policy: {policy_name}")
    root = Path(output).resolve()
    archives = Path(archives).resolve()
    if not resume:
        root.mkdir(parents=True, exist_ok=False)
    elif not root.is_dir():
        raise ValueError("Resume requires an existing run")
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings = {"rounds": rounds, "threads": threads, "tasks": list(tasks),
                    "policy": policy_name, "purpose": "local_simulation_real_training"}
        if isinstance(policy, SamplerPolicy):
            settings.update(sampler_model=policy.model, sampler_path=policy.path)
        config = root / "run.json"
        if rac_policy_class:
            protocol = PROTOCOL
            if config.exists() and read_json(config).get("rac_protocol") == LEGACY_PROTOCOL:
                protocol = LEGACY_PROTOCOL
            settings["rac_protocol"] = protocol
            parent_mode = "selected_checkpoint"
            if config.exists() and "parent_mode" not in read_json(config):
                parent_mode = "original_checkpoint"
            if parent_mode == "selected_checkpoint":
                settings["parent_mode"] = parent_mode
            rac_policy_class = partial(rac_policy_class, protocol=protocol)
        else:
            parent_mode = "selected_checkpoint"
        if config.exists():
            if read_json(config) != settings:
                raise ValueError("Resume settings differ from original run")
        else:
            write_json(config, settings)
        return [run_task(task, archives, root, rounds, threads, timeout, policy, rac_policy_class, parent_mode)
                for task in tasks]
