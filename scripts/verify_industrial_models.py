"""Reload and replay selected models using only train and validation for fitting and scoring."""
import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import joblib
import numpy as np

from rac_hpo.application.industrial_service import IndustrialService
from rac_hpo.data.industrial import prepare
from rac_hpo.infrastructure.artifacts import file_hash, utc_now, write_json
from rac_hpo.training.classification import train


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaigns", nargs="+", type=Path)
    args = parser.parse_args()
    service = IndustrialService(ROOT)
    checks = []
    datasets = {}
    for campaign_path in args.campaigns:
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        for row in campaign["runs"]:
            detail = service.get_run(row["id"])
            if detail["status"] != "completed":
                checks.append({"id": detail["id"], "status": "failed", "reason": "Source run incomplete"})
                continue
            config = detail["config"]
            key = (detail["dataset_key"], config["data_path"])
            if key not in datasets:
                datasets[key] = prepare(key[0], key[1])
            dataset = datasets[key]
            if dataset.source_sha256 != detail["data_sha256"] or dataset.manifest["split_fingerprint"] != detail["manifest"]["split_fingerprint"]:
                raise ValueError(f"Source or sealed split changed for {detail['id']}")
            artifact = detail["artifacts"]["model"]
            if file_hash(artifact) != detail["model_sha256"]:
                raise ValueError(f"Saved model hash mismatch for {detail['id']}")
            saved = joblib.load(artifact)
            # Predictions are compared on validation; test is never passed to the trainer.
            valid = dataset.X.iloc[dataset.splits["validation"]]
            replay = train(dataset, detail["model_name"], detail["best_params"],
                           config["seed"], config["model_config"])
            old_proba, new_proba = saved.predict_proba(valid), replay.model.predict_proba(valid)
            same_predictions = bool(np.array_equal(saved.predict(valid), replay.model.predict(valid)))
            difference = float(np.max(np.abs(old_proba - new_proba)))
            checks.append({"id": detail["id"], "dataset_key": key[0], "model_name": detail["model_name"],
                           "status": "passed" if same_predictions and difference < 1e-12 else "failed",
                           "identical_predictions": same_predictions, "max_probability_difference": difference,
                           "model_sha256": detail["model_sha256"], "test_accessed": False})
    output = ROOT / "workspace/verification" / f"industrial-model-replay-{uuid.uuid4().hex[:12]}.json"
    write_json(output, {"checked_at": utc_now(), "test_accessed": False, "checks": checks})
    print(json.dumps({"artifact": str(output), "checks": len(checks),
                      "passed": sum(check["status"] == "passed" for check in checks)}, ensure_ascii=False))
    return 0 if checks and all(check["status"] == "passed" for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
