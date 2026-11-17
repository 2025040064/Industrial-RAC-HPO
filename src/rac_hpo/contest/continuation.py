"""Task-aware sampling with the original checkpoint model and Adam implementation."""
import json
import time
from pathlib import Path

from rac_hpo.contest.packages import digest, write_json


def group_keys(package, split, task):
    keys = []
    with (Path(package) / "public" / f"{split}.jsonl").open() as stream:
        for line in stream:
            meta = json.loads(line)["meta"]
            if task == "A":
                key = str(meta["source_batch"])
            elif task == "B":
                key = meta["bearing"]
            else:
                key = f"{meta['source_subset']}/{meta['unit']}"
            keys.append(key)
    return keys


def fit_epochs(model, train, epochs, proposal, groups):
    import numpy as np
    strategy = proposal.get("strategy", "uniform")
    if strategy == "uniform":
        return model.fit(train["x"], train["y"], epochs)
    if strategy == "class_focus" and model.meta["task"] == "classification":
        target = model.meta["classes"].index(proposal["target_class"])
        factor = proposal["sampling_multiplier"]
        if not 1 <= factor <= 16:
            raise ValueError("Invalid class sampling multiplier")
        probabilities = np.where(train["y"] == target, float(factor), 1.0)
    elif strategy == "unit_balanced" and model.meta["task"] == "regression":
        _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
        probabilities = 1.0 / counts[inverse]
    else:
        raise ValueError("Sampling strategy incompatible with checkpoint")
    probabilities /= probabilities.sum()
    losses = []
    for _ in range(epochs):
        rng = np.random.default_rng(np.random.SeedSequence(
            [model.meta["seed"], model.meta["epochs"], 20261116]))
        indices = rng.choice(len(probabilities), size=len(probabilities), replace=True, p=probabilities)
        losses.extend(model.fit(train["x"][indices], train["y"][indices], 1))
    return losses


def diagnostics(model, data, package):
    groups = group_keys(package, "validation", model.meta["profile"]) if model.meta["task"] == "regression" else None
    return evaluate_diagnostics(model, data, groups)


def evaluate_diagnostics(model, data, groups):
    import numpy as np
    prediction = model.predict(data["x"])
    if model.meta["task"] == "classification":
        labels = prediction.argmax(axis=1)
        result = {}
        for index, name in enumerate(model.meta["classes"]):
            expected, predicted = data["y"] == index, labels == index
            total = int(expected.sum() + predicted.sum())
            result[name] = {"samples": int(expected.sum()),
                            "f1": float(2 * (expected & predicted).sum() / total) if total else 0.0}
        return {"classes": result}
    if groups is None:
        errors = prediction - data["y"]
        return {"overall": {"samples": len(errors), "mae": float(np.abs(errors).mean())}}
    keys = np.asarray(groups)
    result = {}
    for key in sorted(set(keys)):
        error = prediction[keys == key] - data["y"][keys == key]
        result[key] = {"samples": len(error), "rmse": float(np.sqrt(np.mean(error ** 2))),
                       "mae": float(np.mean(np.abs(error)))}
    return {"groups": result}


def train(package, parent, output, proposal):
    from baselines.model import Model
    from baselines.data import read_dataset
    from baselines.train import metrics
    import numpy as np

    if np.__version__ != "1.26.4":
        raise ValueError("Contest runtime requires numpy==1.26.4")
    model = Model.load(parent)
    initial = dict(model.meta)
    train_data = read_dataset(package / "public/train.jsonl", model.meta["task"],
                              model.meta["classes"], model.meta["paths"])
    validation = read_dataset(package / "public/validation.jsonl", model.meta["task"],
                              model.meta["classes"], model.meta["paths"])
    if set(train_data["ids"]) & set(validation["ids"]):
        raise ValueError("Training and validation IDs overlap")
    model.meta["learning_rate"] = proposal["learning_rate"]
    model.meta["batch_size"] = proposal["batch_size"]
    model.validate()
    strategy = proposal.get("strategy", "uniform")
    groups = group_keys(package, "train", model.meta["profile"])
    before = metrics(model, validation)
    history = []
    started = time.monotonic()
    for _ in range(proposal["epochs"]):
        loss = fit_epochs(model, train_data, 1, proposal, groups)[0]
        history.append({"epoch": model.meta["epochs"], "step": model.meta["steps"],
                        "loss": loss, "validation": metrics(model, validation)})
    duration = time.monotonic() - started
    output.mkdir(exist_ok=False)
    model.save(output / "checkpoint.npz")
    report = {"profile": model.meta["profile"], "purpose": "local_optimization",
              "official_scoring_ready": False, "device": "cpu", "numpy_version": np.__version__,
              "parent_checkpoint_sha256": "sha256:" + digest(parent),
              "checkpoint_sha256": "sha256:" + digest(output / "checkpoint.npz"),
              "train_rows": len(train_data["ids"]), "validation_rows": len(validation["ids"]),
              "train_sha256": train_data["sha256"], "validation_sha256": validation["sha256"],
              "initial_steps": initial["steps"], "final_steps": model.meta["steps"],
              "initial_epochs": initial["epochs"], "final_epochs": model.meta["epochs"],
              "configuration": {"requested_epochs": proposal["epochs"], "strategy": strategy},
              "proposal": proposal,
              "learning_rate": model.meta["learning_rate"], "batch_size": model.meta["batch_size"],
              "training_seconds": duration, "validation_before": before,
              "validation_after": metrics(model, validation),
              "diagnostics": diagnostics(model, validation, package)}
    write_json(output / "training.json", report)
    from rac_hpo._io import atomic_text
    atomic_text(output / "history.jsonl", "".join(json.dumps(row, allow_nan=False) + "\n" for row in history),
                overwrite=False)
