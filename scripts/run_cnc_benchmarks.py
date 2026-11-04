"""Equal wall-budget experiments on physical-tool holdouts; test stays sealed."""
import argparse
import json
from pathlib import Path

from rac_hpo.application.experiment_service import ApplicationService
from rac_hpo.data.registry import DEFAULT_PATHS
from rac_hpo.infrastructure.artifacts import utc_now, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 71, 103])
    parser.add_argument("--max-trials", type=int, default=100000)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    service = ApplicationService(root)
    stamp = utc_now().replace(":", "").replace(".", "")
    output = root / "workspace/verification" / f"cnc-budget-{stamp}.json"
    records = []
    for seed in arguments.seeds:
        for algorithm in ("tpe", "tpe_robust", "rac_hpo"):
            result = service.run_experiment(algorithm, str(root / DEFAULT_PATHS["cnc_milling_2025"]), {
                "experiment": {"name": "cnc_physical_tool_holdout", "seed": seed},
                "optimization": {"max_trials": arguments.max_trials, "timeout_seconds": arguments.seconds},
            })
            record = {key: result.get(key) for key in (
                "id", "algorithm", "status", "metrics", "best_value", "best_params", "best_iteration",
                "duration_seconds", "baseline_duration_seconds", "search_duration_seconds", "budget_overrun_seconds",
                "search_diagnostics", "failure_reason")}
            record.update(seed=seed, timeout_seconds=arguments.seconds,
                          trials=sum(trial["number"] >= 0 for trial in result["trials"]))
            records.append(record)
            write_json(output, records)
            print(json.dumps({"id": record["id"], "algorithm": algorithm, "seed": seed,
                              "status": record["status"], "trials": record["trials"],
                              "mae": record["metrics"].get("overall_mae"),
                              "J": record["metrics"].get("robust_objective"),
                              "diagnostics": record.get("search_diagnostics")}), flush=True)
            if record["status"] != "completed":
                raise RuntimeError(f"Real benchmark failed; inspect experiment {record['id']}: {record.get('failure_reason')}")
    print(str(output), flush=True)


if __name__ == "__main__":
    main()
