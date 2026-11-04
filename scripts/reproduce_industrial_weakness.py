"""Replay the recorded industrial validation weaknesses without accessing test."""
import argparse
import json
from pathlib import Path
import sys

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rac_hpo.application.industrial_service import IndustrialService
from rac_hpo.data.industrial import prepare
from rac_hpo.infrastructure.artifacts import file_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secom-run", default="IND-79b21a15b8cd4767")
    parser.add_argument("--paderborn-run", default="IND-19c7b3684f154662")
    parser.add_argument("--dataset", choices=("both", "secom", "paderborn"), default="both")
    parser.add_argument("--require-positive-recall", action="store_true",
                        help="Return failure when either recorded weak-class recall is zero")
    args = parser.parse_args()
    service = IndustrialService(ROOT)
    results = []
    for run_id, weak_class in ((args.secom_run, 1), (args.paderborn_run, 1)):
        run = service.get_run(run_id)
        if args.dataset != "both" and run["dataset_key"] != args.dataset:
            continue
        data = prepare(run["dataset_key"], run["config"]["data_path"],
                       archive_cache_dir=ROOT / "datasets/processed/industrial")
        if data.source_sha256 != run["data_sha256"] or data.manifest["split_fingerprint"] != run["manifest"]["split_fingerprint"]:
            raise ValueError(f"Source or split changed for {run_id}")
        if file_hash(run["artifacts"]["model"]) != run["model_sha256"]:
            raise ValueError(f"Model hash changed for {run_id}")
        model = joblib.load(run["artifacts"]["model"])
        X, y, regimes, groups = data.split("validation")
        predicted = model.predict(X)
        truth = np.asarray(y)
        selected = truth == weak_class
        results.append({"dataset": run["dataset_key"], "run_id": run_id,
                        "weak_class": weak_class, "weak_class_samples": int(selected.sum()),
                        "weak_class_recall": float(np.mean(predicted[selected] == weak_class)),
                        "validation_groups": int(groups.nunique()), "regimes": sorted(regimes.unique().tolist()),
                        "test_used_for_training_or_selection": False})
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return int(args.require_positive_recall and any(item["weak_class_recall"] == 0 for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
