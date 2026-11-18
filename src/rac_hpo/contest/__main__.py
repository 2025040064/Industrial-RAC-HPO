"""Local contest simulation entry point."""
import argparse
import json
import os
import sys
from pathlib import Path

from rac_hpo.contest.sampler import BASE_MODEL
from rac_hpo.contest.service import run


def predict(argv):
    from rac_hpo.contest.packages import digest, verify
    from rac_hpo.contest.service import environment, read_json

    parser = argparse.ArgumentParser(description="Run a selected checkpoint on stdin JSONL")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--task", choices=("A", "B", "C"), required=True)
    args = parser.parse_args(argv)
    run_root = args.run.resolve()
    task_root = run_root / args.task
    package = task_root / "package"
    verify(package, args.task)
    summary = read_json(task_root / "summary.json")
    checkpoint = (run_root / summary["checkpoint"]).resolve()
    if (summary["task"] != args.task or not checkpoint.is_relative_to(task_root.resolve())
            or digest(checkpoint) != summary["checkpoint_sha256"]):
        parser.error("Selected checkpoint does not match task summary")
    os.chdir(package)
    os.execve(sys.executable, [sys.executable, "-m", "baselines.predict", "--checkpoint", str(checkpoint)],
              environment(1))


def main():
    if sys.argv[1:2] == ["predict"]:
        return predict(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    packages = os.environ.get("HARNESS_PACKAGES")
    parser.add_argument("--packages", type=Path, default=packages, required=packages is None)
    output = os.environ.get("HARNESS_OUTPUT")
    parser.add_argument("--output", type=Path, default=output, required=output is None)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--tasks", nargs="+", choices=("A", "B", "C"), default=["A", "B", "C"])
    parser.add_argument("--resume", action="store_true")
    default_policy = ("pytrio_sampler" if os.environ.get("HARNESS_SAMPLER_PATH")
                      else os.environ.get("HARNESS_POLICY", "local_validation_rule_v1"))
    parser.add_argument("--policy", choices=("local_validation_rule_v1", "task_aware_v3", "rac_hpo",
                                            "pytrio_base", "pytrio_sampler"),
                        default=default_policy)
    parser.add_argument("--sampler-model", default=os.environ.get("HARNESS_SAMPLER_MODEL", BASE_MODEL))
    parser.add_argument("--sampler-path", default=os.environ.get("HARNESS_SAMPLER_PATH"))
    args = parser.parse_args()
    result = run(args.packages, args.output, args.rounds, args.threads, args.timeout,
                 args.resume, args.tasks, args.policy, args.sampler_model, args.sampler_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
