"""Multi-seed steel benchmark.

The single-seed comparison cannot answer "does the ranking hold?". This runs every
algorithm over several seeds with an identical trial budget and prints the aggregate,
so a defence can quote a stable ordering instead of one lucky run.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ALGORITHMS = ("baseline", "random", "tpe", "tpe_robust", "rac_hpo")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 71, 103])
    parser.add_argument("--max-trials", type=int, default=48)
    parser.add_argument("--timeout", type=float, default=180)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    verification = root / "workspace/verification"
    verification.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in arguments.seeds:
        for algorithm in ALGORITHMS:
            command = [sys.executable, "-m", "rac_hpo"]
            if algorithm == "baseline":
                command += ["train", "--seed", str(seed), "--estimators", "300"]
            else:
                command += [
                    "optimize", "--algorithm", algorithm, "--seed", str(seed),
                    "--estimators", "300", "--max-trials", str(arguments.max_trials),
                    "--timeout", str(arguments.timeout),
                ]
            started = time.perf_counter()
            process = subprocess.run(command, cwd=root, capture_output=True)
            wall = time.perf_counter() - started
            if process.returncode:
                sys.stderr.buffer.write(process.stderr)
                raise RuntimeError(f"Real CLI experiment failed: {algorithm} seed={seed}")
            detail = json.loads(process.stdout.decode("utf-8"))
            metrics = detail["metrics"]
            rows.append({
                "seed": seed,
                "algorithm": algorithm,
                "id": detail["id"],
                "overall_mae": metrics["overall_mae"],
                "robust_objective": metrics["robust_objective"],
                "worst_normalized_mae": metrics["worst_normalized_mae"],
                "weekday_mae": metrics["regimes"]["weekday"]["mae"],
                "weekend_mae": metrics["regimes"]["weekend"]["mae"],
                "duration_seconds": detail["duration_seconds"],
                "search_trials": sum(1 for trial in detail["trials"] if trial["number"] >= 0),
                "cli_wall_seconds": wall,
            })
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    output = verification / f"steel-seeds-{int(time.time())}.json"
    output.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n算法          MAE 均值    MAE 标准差    J 均值     J 标准差")
    for algorithm in ALGORITHMS:
        subset = [row for row in rows if row["algorithm"] == algorithm]
        if not subset:
            continue
        maes = [row["overall_mae"] for row in subset]
        js = [row["robust_objective"] for row in subset]
        mae_mean = sum(maes) / len(maes)
        j_mean = sum(js) / len(js)
        mae_sd = (sum((value - mae_mean) ** 2 for value in maes) / len(maes)) ** 0.5
        j_sd = (sum((value - j_mean) ** 2 for value in js) / len(js)) ** 0.5
        print(f"{algorithm:<12} {mae_mean:>9.4f}  {mae_sd:>10.4f}  {j_mean:>8.6f}  {j_sd:>9.6f}")

    print("\n按 MAE 排序:")
    ranked = sorted(
        (algorithm for algorithm in ALGORITHMS if any(r["algorithm"] == algorithm for r in rows)),
        key=lambda a: sum(r["overall_mae"] for r in rows if r["algorithm"] == a) / max(1, sum(1 for r in rows if r["algorithm"] == a)),
    )
    print("  " + " < ".join(ranked))
    print("按 J 排序:")
    ranked_j = sorted(
        (algorithm for algorithm in ALGORITHMS if any(r["algorithm"] == algorithm for r in rows)),
        key=lambda a: sum(r["robust_objective"] for r in rows if r["algorithm"] == a) / max(1, sum(1 for r in rows if r["algorithm"] == a)),
    )
    print("  " + " < ".join(ranked_j))
    print(f"\n明细已保存: {output}")
    return rows


if __name__ == "__main__":
    main()
