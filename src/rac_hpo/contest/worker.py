"""Run within one task subprocess so each original baselines package stays isolated."""
import argparse
import json
from pathlib import Path
import sys

from rac_hpo.contest.packages import digest, write_json
from rac_hpo.contest.continuation import diagnostics, fit_epochs, group_keys


def audit(package, output):
    sys.path.insert(0, str(package))
    from baselines.model import Model
    from baselines.data import read_dataset
    from baselines.train import metrics
    import numpy as np

    if np.__version__ != "1.26.4":
        raise ValueError("Contest runtime requires numpy==1.26.4")
    model = Model.load(package / "checkpoint.npz")
    task = model.meta["profile"]
    datasets = {}
    units = {}
    for split in ("train", "validation"):
        path = package / "public" / f"{split}.jsonl"
        datasets[split] = read_dataset(path, model.meta["task"], model.meta["classes"], model.meta["paths"])
        groups = set()
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                meta = row["meta"]
                if task == "A":
                    key = meta["source_batch"]
                elif task == "B":
                    key = meta["bearing"]
                else:
                    key = (meta["source_subset"], meta["unit"])
                groups.add(key)
        units[split] = groups
    if units["train"] & units["validation"]:
        raise ValueError("Train/validation units overlap")
    if set(datasets["train"]["ids"]) & set(datasets["validation"]["ids"]):
        raise ValueError("Train/validation IDs overlap")
    report = json.loads((package / "training.json").read_text())
    for split in datasets:
        if datasets[split]["sha256"] != report[f"{split}_sha256"]:
            raise ValueError("Dataset differs from original training report")
    result = {"task": task, "purpose": "development_reference", "official_scoring_ready": False,
              "numpy_version": np.__version__, "checkpoint_sha256": digest(package / "checkpoint.npz"),
              "metadata": model.meta, "baseline_metrics": metrics(model, datasets["validation"]),
              "reported_metrics": report["validation_after"],
              "diagnostics": diagnostics(model, datasets["validation"], package),
              "rows": {k: len(v["ids"]) for k, v in datasets.items()},
              "units": {k: len(v) for k, v in units.items()}}
    write_json(output, result)


def check(package, parent_path, candidate_dir, output):
    sys.path.insert(0, str(package))
    from baselines.model import Model, PARAMETERS
    from baselines.data import read_dataset
    from baselines.train import metrics
    import numpy as np

    parent = Model.load(parent_path)
    child = Model.load(candidate_dir / "checkpoint.npz")
    report = json.loads((candidate_dir / "training.json").read_text())
    if report["parent_checkpoint_sha256"] != "sha256:" + digest(parent_path):
        raise ValueError("Parent hash mismatch")
    if report["checkpoint_sha256"] != "sha256:" + digest(candidate_dir / "checkpoint.npz"):
        raise ValueError("Candidate hash mismatch")
    for key in ("seed", "paths", "classes", "hidden", "profile", "target_mean", "target_scale"):
        if parent.meta[key] != child.meta[key]:
            raise ValueError(f"State continuity failed: {key}")
    for key in ("mean", "scale"):
        np.testing.assert_array_equal(getattr(parent, key), getattr(child, key))
    epochs = report["configuration"]["requested_epochs"]
    steps = epochs * ((report["train_rows"] + child.meta["batch_size"] - 1) // child.meta["batch_size"])
    for key, increment in (("epochs", epochs), ("steps", steps)):
        if (report[f"initial_{key}"] != parent.meta[key]
                or report[f"final_{key}"] != child.meta[key]
                or child.meta[key] != parent.meta[key] + increment):
            raise ValueError(f"Counter continuity failed: {key}")
    validation = read_dataset(package / "public/validation.jsonl", child.meta["task"],
                              child.meta["classes"], child.meta["paths"])
    measured = metrics(child, validation)
    for name, value in measured.items():
        if not np.isfinite(value) or not np.isclose(value, report["validation_after"][name], rtol=1e-10):
            raise ValueError("Reloaded metrics mismatch")
    # Check full weight/Adam recovery against independent continuous execution.
    train = read_dataset(package / "public/train.jsonl", child.meta["task"],
                         child.meta["classes"], child.meta["paths"])
    parent.meta["learning_rate"] = child.meta["learning_rate"]
    parent.meta["batch_size"] = child.meta["batch_size"]
    fit_epochs(parent, train, epochs, report.get("proposal", {}),
               group_keys(package, "train", parent.meta["profile"]))
    for group in ("params", "first", "second"):
        for key in PARAMETERS:
            np.testing.assert_array_equal(getattr(parent, group)[key], getattr(child, group)[key])
    write_json(output, {"metrics": measured, "checkpoint_sha256": digest(candidate_dir / "checkpoint.npz"),
                        "continuous_replay_equal": True, "normalization_preserved": True,
                        "diagnostics": diagnostics(child, validation, package)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("audit", "check", "train"))
    parser.add_argument("package", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--proposal", type=Path)
    args = parser.parse_args()
    if args.action == "audit":
        audit(args.package, args.output)
    elif args.action == "check":
        check(args.package, args.parent, args.candidate, args.output)
    else:
        sys.path.insert(0, str(args.package))
        from rac_hpo.contest.continuation import train
        train(args.package, args.parent, args.output, json.loads(args.proposal.read_text()))


if __name__ == "__main__":
    main()
