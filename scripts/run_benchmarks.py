"""Run real CLI methods on the official dataset and retain exact outputs/commands."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-trials", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=120)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    verification = root / "workspace/verification"
    verification.mkdir(parents=True, exist_ok=True)
    results = []
    for algorithm in ("baseline", "random", "tpe", "tpe_robust"):
        command = [sys.executable, "-m", "rac_hpo"]
        if algorithm == "baseline":
            command += ["train", "--seed", "42", "--estimators", "300"]
        else:
            command += ["optimize", "--algorithm", algorithm, "--seed", "42", "--estimators", "300",
                        "--max-trials", str(arguments.max_trials), "--timeout", str(arguments.timeout)]
        started = time.perf_counter()
        process = subprocess.run(command, cwd=root, capture_output=True)
        wall = time.perf_counter() - started
        if process.returncode:
            sys.stderr.buffer.write(process.stderr)
            raise RuntimeError(f"Real CLI experiment failed: {algorithm}, exit={process.returncode}")
        detail = json.loads(process.stdout.decode("utf-8"))
        tag = f"{algorithm}-{detail['id']}"
        (verification / f"{tag}.json").write_bytes(process.stdout)
        (verification / f"{tag}.log").write_bytes(process.stderr)
        result = {key: detail.get(key) for key in (
            "id", "algorithm", "status", "metrics", "best_params", "best_trial",
            "duration_seconds", "baseline_duration_seconds", "search_duration_seconds", "best_iteration",
        )}
        result.update(command=command, cli_wall_seconds=wall,
                      search_trial_count=sum(trial["number"] >= 0 for trial in detail["trials"]))
        results.append(result)
        print(json.dumps(result, ensure_ascii=True), flush=True)
    output = verification / f"benchmark-{results[0]['id']}.json"
    output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


if __name__ == "__main__":
    main()
