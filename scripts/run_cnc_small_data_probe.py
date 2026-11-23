"""Run a paired CNC search-space probe in a fresh, isolated workspace."""
from collections import Counter
import argparse
from copy import deepcopy
import itertools
import json
from pathlib import Path
import shutil
from time import perf_counter_ns
from unittest.mock import patch
import uuid

import numpy as np

from rac_hpo.application.experiment_service import ApplicationService
from rac_hpo.data.cnc_milling import OFFICIAL_SHA256, prepare_cnc_milling
from rac_hpo.data.registry import DEFAULT_PATHS
from rac_hpo.domain.schemas import PreparedDataset
from rac_hpo.infrastructure.artifacts import environment_snapshot, file_hash, write_json
from rac_hpo.infrastructure.config_loader import load_config
from rac_hpo.training.model_export import load_model


def audit_split(dataset):
    splits = dataset.manifest["split_groups"]
    for first, second in itertools.combinations(splits, 2):
        if set(splits[first]) & set(splits[second]):
            raise ValueError(f"Physical tool overlap: {first}, {second}")
        if set(dataset.splits[first]) & set(dataset.splits[second]):
            raise ValueError(f"Source row overlap: {first}, {second}")
    if set(dataset.features) & set(dataset.manifest["excluded_fields"]):
        raise ValueError("Excluded fields are present in model features")
    summary = {}
    for name in ("train", "validation"):
        _, _, regimes, groups = dataset.split(name)
        summary[name] = {
            str(regime): {"rows": int((regimes == regime).sum()),
                          "physical_tools": int(groups[regimes == regime].nunique())}
            for regime in sorted(regimes.unique())
        }
    return summary


def inspect_model(result, dataset):
    model_path = Path(result["artifacts"]["model"])
    model = load_model(model_path)
    if model.num_trees() != result["best_iteration"]:
        raise ValueError(f"Reloaded tree count differs for {result['id']}")
    metrics = {}
    for name in ("train", "validation"):
        features, target, regimes, groups = dataset.split(name)
        matrix = features.to_numpy()
        errors = np.abs(model.predict(matrix, num_threads=1) - target.to_numpy())
        metrics[name] = {
            "mae": float(errors.mean()),
            "p95_absolute_error": float(np.quantile(errors, .95)),
            "regimes": {str(regime): float(errors[regimes == regime].mean())
                        for regime in sorted(regimes.unique())},
            "tools": {str(group): float(errors[groups == group].mean())
                      for group in sorted(groups.unique())},
        }
        if name == "validation":
            np.testing.assert_allclose(errors.mean(), result["metrics"]["overall_mae"],
                                       rtol=0, atol=1e-10)
            validation_matrix = matrix
    samples = [validation_matrix[index:index + 1] for index in range(len(validation_matrix))]
    for sample in samples[:20]:
        model.predict(sample, num_threads=1)
    timings = []
    for sample in samples * 3:
        started = perf_counter_ns()
        model.predict(sample, num_threads=1)
        timings.append((perf_counter_ns() - started) / 1e6)
    metrics["inference"] = {
        "scope": "in_process_lightgbm_predict_on_precomputed_features",
        "batch_size": 1, "threads": 1, "warmup_calls": 20, "timed_calls": len(timings),
        **{f"p{p}_ms": float(np.percentile(timings, p)) for p in (50, 95, 99)},
    }
    return {"metrics": metrics, "model_sha256": file_hash(model_path),
            "model_bytes": model_path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", choices=("paired", "single_parameter"), default="paired")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / DEFAULT_PATHS["cnc_milling_2025"]
    if file_hash(source) != OFFICIAL_SHA256:
        raise ValueError("Local CNC data does not match the pinned author file")
    output = root / "workspace/verification" / f"cnc-small-data-{uuid.uuid4().hex[:12]}"
    config_dir = output / "configs"
    config_dir.mkdir(parents=True, exist_ok=False)
    config_path = config_dir / "default.yaml"
    shutil.copy2(root / "configs/default.yaml", config_path)
    shutil.copy2(root / "uv.lock", output / "uv.lock")
    config = load_config(config_path)
    standard = config["optimization"]["search_space"]
    compact = deepcopy(standard)
    compact["num_leaves"].update(high=16)
    compact["max_depth"].update(low=4, high=5)
    compact["min_child_samples"].update(low=25, high=80)
    spaces = {"standard": standard, "compact": compact}
    model_overrides = {}
    if arguments.study == "single_parameter":
        spaces = {"standard": standard}
        for parameter in ("num_leaves", "max_depth", "min_child_samples"):
            space = deepcopy(standard)
            space[parameter] = deepcopy(compact[parameter])
            spaces[parameter] = space
        spaces["trees_100"] = deepcopy(standard)
        model_overrides["trees_100"] = {"n_estimators": 100}
    seeds = [42, 71, 103]
    budget = {"max_trials": 24, "timeout_seconds": 120}
    dataset = prepare_cnc_milling(source)
    original_split = PreparedDataset.split

    def guarded_split(data, name):
        if name not in ("train", "validation"):
            raise AssertionError(f"Forbidden partition in exploratory study: {name}")
        return original_split(data, name)

    with patch.object(PreparedDataset, "split", guarded_split):
        write_json(output / "protocol.json", {
            "dataset_id": dataset.dataset_id, "source_sha256": dataset.source_sha256,
            "dataset_version": dataset.manifest["dataset_version"], "split_groups": dataset.manifest["split_groups"],
            "audited_partitions": audit_split(dataset), "mode": "exploratory",
            "selection_metric": "minimum validation MAE, first trial on ties",
            "baseline": "default LightGBM at seed 42",
            "model_config": config["model"], "budget": budget, "seeds": seeds,
            "study": arguments.study, "model_overrides": model_overrides,
            "search_algorithm": "random", "search_spaces": spaces,
            "comparison_requires_all_trials_completed": True,
            "runner_sha256": file_hash(Path(__file__)), "environment": environment_snapshot(root),
        })
        print(output.relative_to(root), flush=True)
        service = ApplicationService(output)
        schedule = [("baseline", 42)]
        for index, seed in enumerate(seeds):
            arms = list(spaces) if index % 2 == 0 else list(reversed(spaces))
            schedule.extend((arm, seed) for arm in arms)
        summaries = []
        for arm, seed in schedule:
            algorithm = "baseline" if arm == "baseline" else "random"
            result = service.run_experiment(algorithm, source, {
                "experiment": {"name": f"cnc_small_data_{arm}", "seed": seed},
                "optimization": {**budget, "search_space": spaces.get(arm, standard)},
                "model": model_overrides.get(arm, {}),
            })
            trial_counts = Counter(trial["status"] for trial in result["trials"] if trial["number"] >= 0)
            record = {key: result.get(key) for key in (
                "id", "status", "best_trial", "best_params", "best_iteration",
                "search_duration_seconds", "baseline_duration_seconds", "budget_overrun_seconds",
                "failure_reason")}
            record.update(arm=arm, seed=seed, trial_counts=dict(trial_counts))
            summaries.append(record)
            write_json(output / "summary.json", summaries)
            if result["status"] == "completed":
                record.update(inspect_model(result, dataset))
            write_json(output / "summary.json", summaries)
            print(json.dumps({
                "id": record["id"], "arm": arm, "seed": seed, "status": record["status"],
                "validation": record.get("metrics", {}).get("validation"), "trial_counts": trial_counts,
            }), flush=True)
            if result["status"] != "completed" or (
                algorithm == "random" and trial_counts != {"completed": budget["max_trials"]}
            ):
                raise RuntimeError(f"Incomplete probe. Inspect {record['id']} and {output / 'summary.json'}")


if __name__ == "__main__":
    main()
