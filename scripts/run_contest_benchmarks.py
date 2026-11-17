"""Paired public-validation searches from the same original contest checkpoints."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

import optuna
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rac_hpo.contest.continuation import evaluate_diagnostics, fit_epochs, group_keys
from rac_hpo.contest.packages import digest, prepare, write_json
from rac_hpo.contest.policy import accept_candidate
from rac_hpo.contest.rac_policy import ContestRACPolicy
from rac_hpo.contest.worker import audit as audit_package

METHODS = ("random", "tpe", "tpe_robust", "rac_hpo", "rac_no_regimes", "rac_no_cost", "rac_no_priority")
EXPERIMENTAL_METHODS = ("rac_no_forward_gate", "rac_bearing_constraint")


def primary_loss(task, value):
    return 1 - value if task == "A" else value


def overall_diagnostics(task, metrics, rows):
    name = "macro_f1" if task == "A" else "rmse"
    return {"overall": {"mae": primary_loss(task, metrics[name]), "samples": rows}}


class ComparisonPolicy(ContestRACPolicy):
    def __init__(self, task, audit, method, seed, scoring):
        self.method = method
        if method == "rac_no_regimes":
            audit = {**audit, "diagnostics": overall_diagnostics(
                task, audit["baseline_metrics"], audit["rows"]["validation"])}
        super().__init__(task, audit, seed=seed, prioritize_bearing_feasibility=method == "rac_bearing_constraint")
        self.require_forward_quality = method != "rac_no_forward_gate"
        self.weak_class = scoring.weak_class
        settings = self.search_config["rac_hpo"]
        if method in ("random", "tpe", "tpe_robust"):
            settings["warmup_trials"] = 11
        if method == "rac_no_cost":
            settings.update(gamma=0.0, maximum_cost_log_mae_ratio=None)
        if method == "rac_no_priority":
            settings["beta"] = 0.0

    def _trial(self, record):
        trial = super()._trial(record)
        if self.method == "tpe":
            trial["objective"] = primary_loss(self.task, record["primary_metric"])
        return trial

    def _sampler(self, seed):
        if self.method == "random":
            return optuna.samplers.RandomSampler(seed=seed)
        return super()._sampler(seed)


def run_search(directory, task, package, audit, method, seed, rounds, train, validation, groups):
    from baselines.model import Model
    from baselines.train import metrics

    directory.mkdir()
    scoring = ContestRACPolicy(task, audit, seed=seed)
    search = ComparisonPolicy(task, audit, method, seed, scoring)
    name = "macro_f1" if task == "A" else "rmse"
    baseline = selected = audit["baseline_metrics"][name]
    selected_j = scoring.baseline_objective
    selected_round = None
    parent = package / "checkpoint.npz"
    parent_sha = digest(parent)
    write_json(directory / "config.json", {
        "task": task, "method": method, "seed": seed, "cpu_threads": 1, "rounds": rounds,
        "train_sha256": train["sha256"], "validation_sha256": validation["sha256"],
        "parent_sha256": parent_sha, "search": search.configuration(), "evaluation": scoring.configuration(),
    })
    records, results = [], []
    began = time.monotonic()
    campaign_cpu_started = time.process_time()
    for number in range(1, rounds + 1):
        trial_dir = directory / f"round-{number:02}"
        trial_dir.mkdir()
        proposal, trace = search.propose(audit["metadata"], records)
        trace["comparison_method"] = method
        if method == "random" and trace["method"] == "tpe_fallback":
            trace["method"] = "random_search"
            proposal["reason"] = "Random search sampled an unused point in the fixed domain."
        write_json(trial_dir / "decision.json", {"proposal": proposal, "trace": trace})
        child = Model.load(parent)
        child.meta.update(learning_rate=proposal["learning_rate"], batch_size=proposal["batch_size"])
        checkpoint = trial_dir / "checkpoint.npz"
        started = time.monotonic()
        cpu_started = time.process_time()
        try:
            fit_epochs(child, train, proposal["epochs"], proposal, groups["train"])
            training_cpu = time.process_time() - cpu_started
            duration = time.monotonic() - started
            child.save(checkpoint)
            reloaded = Model.load(checkpoint)
            result = metrics(reloaded, validation)
            diagnostics = evaluate_diagnostics(reloaded, validation, groups["validation"])
            score = scoring.score(diagnostics)
        except (ArithmeticError, ValueError) as error:
            failure = {"round": number, "status": "failed", "error": type(error).__name__,
                       "detail": str(error), "training_cpu_seconds": time.process_time() - cpu_started,
                       "training_seconds": time.monotonic() - started}
            write_json(trial_dir / "result.json", failure)
            records.append(failure)
            results.append(failure)
            continue
        comparable = overall_diagnostics(task, result, audit["rows"]["validation"]) \
            if method == "rac_no_regimes" else diagnostics
        value = result[name]
        gate = accept_candidate(task, audit["diagnostics"], diagnostics, selected, value)
        improved_j = score["robust_objective"] < selected_j
        accepted = gate and improved_j
        if accepted:
            selected, selected_j, selected_round = value, score["robust_objective"], number
        record = {"status": "completed", "round": number, "rac_params": trace["params"],
                  "training_seconds": duration, "training_cpu_seconds": training_cpu,
                  "primary_metric": value, "diagnostics": comparable,
                  "robust_objective": search.score(comparable)["robust_objective"]}
        records.append(record)
        rounded = {**record, **score, "diagnostics": diagnostics, "metrics": result,
                   "parent_sha256": parent_sha, "candidate_sha256": digest(checkpoint),
                   "validation_gate_passed": gate, "objective_improved": improved_j, "accepted": accepted,
                   "selected_metric": selected, "selected_round": selected_round}
        write_json(trial_dir / "result.json", rounded)
        results.append(rounded)
    completed = [row for row in results if row["status"] == "completed"]
    selected_diagnostics = next((row["diagnostics"] for row in completed if row["round"] == selected_round),
                                audit["diagnostics"])
    normalized = scoring.score(selected_diagnostics)["normalized_group_errors"]
    worst_group = max(normalized, key=normalized.get)
    summary = {
        "task": task, "method": method, "seed": seed, "metric": name, "baseline": baseline, "selected": selected,
        "completed": len(completed), "failed": rounds - len(completed), "selected_round": selected_round,
        "selected_j": selected_j, "worst_trial_primary_metric": (min if task == "A" else max)(
            (row["primary_metric"] for row in completed), default=None),
        "worst_selected_group": worst_group, "worst_selected_group_ratio": normalized[worst_group],
        "training_seconds": sum(row["training_seconds"] for row in results),
        "training_cpu_seconds": sum(row["training_cpu_seconds"] for row in results),
        "unaccepted_training_cpu_seconds": sum(row["training_cpu_seconds"] for row in results
                                               if not row.get("accepted")),
        "search_validation_and_training_cpu_seconds": time.process_time() - campaign_cpu_started,
        "accepted_rounds": sum(row.get("accepted", False) for row in completed),
        "elapsed_seconds": time.monotonic() - began,
    }
    write_json(directory / "summary.json", summary)
    return summary


def campaign(options, scratch):
    summaries = []
    for task in options.tasks:
        archive, = options.packages.glob(f"cpu-{task.lower()}-*.zip")
        package = scratch / task
        prepare(archive, package, task)
        audit_file = options.output / f"audit-{task}.json"
        audit_package(package, audit_file)
        audited = json.loads(audit_file.read_text())
        from baselines.data import read_dataset

        metadata = audited["metadata"]
        train, validation = [
            read_dataset(package / "public" / f"{split}.jsonl", metadata["task"],
                         metadata["classes"], metadata["paths"]) for split in ("train", "validation")
        ]
        groups = {split: group_keys(package, split, task) for split in ("train", "validation")}
        expected = json.loads((package / "training.json").read_text())
        if (train["sha256"] != expected["train_sha256"]
                or validation["sha256"] != expected["validation_sha256"]):
            raise ValueError("Public projection changed after package verification")
        for method in options.methods:
            for seed in options.seeds:
                path = options.output / f"{task}-{method}-{seed}"
                summary = run_search(path, task, package, audited, method, seed, options.rounds, train,
                                     validation, groups)
                summaries.append(summary)
                print(json.dumps(summary, allow_nan=False), flush=True)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--packages", type=Path, default=ROOT / "训练集")
    parser.add_argument("--tasks", nargs="+", choices=tuple("ABC"), default=list("ABC"))
    parser.add_argument("--methods", nargs="+", choices=METHODS + EXPERIMENTAL_METHODS, default=list(METHODS))
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 71, 103])
    parser.add_argument("--rounds", type=int, choices=range(1, 11), default=10)
    options = parser.parse_args()
    if any(len(values) != len(set(values)) for values in (options.tasks, options.methods, options.seeds)):
        parser.error("Tasks, methods and seeds must be unique")
    if "rac_bearing_constraint" in options.methods and options.tasks != ["B"]:
        parser.error("rac_bearing_constraint requires --tasks B")
    options.output.mkdir(parents=True, exist_ok=False)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    with tempfile.TemporaryDirectory(prefix=".packages-", dir=options.output) as tmp, threadpool_limits(limits=1):
        summaries = campaign(options, Path(tmp))
    aggregate = {}
    for task in options.tasks:
        aggregate[task] = {}
        for method in options.methods:
            rows = [row for row in summaries if row["task"] == task and row["method"] == method]
            values = [row["selected"] for row in rows]
            aggregate[task][method] = {
                "selected_mean": statistics.mean(values), "selected_std": statistics.stdev(values) if len(values) > 1 else None,
                "cpu_seconds_mean": statistics.mean(row["training_cpu_seconds"] for row in rows),
                "failed_rounds": sum(row["failed"] for row in rows),
            }
    write_json(options.output / "summary.json", {"purpose": "paired_local_public_validation", "runs": summaries,
                                                "aggregate": aggregate})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
