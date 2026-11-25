"""Local end-to-end replay of the platform fallback decision path.

No network, no PyTRIO sampling, no billable training, no platform calls.
Real/legacy/candidate model texts are injected into the production SDK callback
via SDKCallbacksTest.run_round(), so the audit is produced by the same
contest_submission.train() path used by the competition harness.

Run from the repository root:
  CONTEST_SDK_SOURCE=.cache/sdk-stage3-save.wBTnNxLa \
  PYTHONPATH=src:official_submission \
  .venv-contest/bin/python experiments/local-fallback-replay-20261124/replay.py
"""
import hashlib
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TASKS = ("A", "B", "C")
ROUNDS_PER_TASK = 10


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def real_replies():
    rows = [json.loads(line) for line in
            (ROOT / "experiments/pytrio-diagnostics-20261122-01/responses.jsonl").read_text().splitlines()]
    submitted = next(row["raw_text"] for row in rows
                     if row["label"] == "submitted_sampler" and row["task"] == "A")
    live = [json.loads((ROOT / f"experiments/pytrio-diagnostics-20261122-03/live-{task}.json").read_text())
            for task in TASKS]
    for row in live:
        if row["status"] != "ok" or row["stop_reason"] != "stop":
            raise RuntimeError(f"Live SDK sample is not usable: {row}")
    return submitted, {row["task"]: row["text"] for row in live}


def scenarios(submitted_text, live_texts):
    legacy = {"learning_rate": 0.001, "batch_size": 128, "epochs": 2,
              "strategy": "uniform", "reason": "Measure a conservative continuation step."}
    return {
        "real-01-submitted-sampler": {task: submitted_text for task in TASKS},
        "real-03-sdk-selection-json": live_texts,
        "legacy-parameter-proposal-json": {
            task: json.dumps(legacy, ensure_ascii=False) for task in TASKS},
        "truncated-selection-json": {
            task: '{"selected_option":"conservative","reason_codes":["risk"]' for task in TASKS},
        "fenced-selection-json": {
            task: '```json\n{"selected_option":"conservative","reason_codes":["risk"],"risk":"medium"}\n```'
            for task in TASKS},
        "unknown-terminal-marker": {task: 'RAC<|unknown|>' for task in TASKS},
    }


def main():
    from official_submission.tests.test_sdk_callbacks import SDKCallbacksTest

    submitted_text, live_texts = real_replies()
    cases = scenarios(submitted_text, live_texts)
    SDKCallbacksTest.setUpClass()
    results = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "purpose": "Measure whether conservative_invalid_response fallback still occurs locally",
        "path": "real model texts and candidate formats injected into production SDK callback",
        "limits": [
            "Not a platform run: no original 11-23 receipts exist, so platform 30/30 cannot be reproduced exactly.",
            "No local LoRA weights: weights are remote trio:// pointers; no PyTRIO sampling or billable training was called.",
            "measure=False skips candidate metric computation; it does not skip decision parsing, parameter choice or training.",
        ],
        "source_sha256": {
            "official_submission/contest_submission.py": sha256(ROOT / "official_submission/contest_submission.py"),
            "src/rac_hpo/contest/stage3_controls.py": sha256(ROOT / "src/rac_hpo/contest/stage3_controls.py"),
        },
        "sdk_source": str(Path(__import__("os").environ.get("CONTEST_SDK_SOURCE", "<unset>"))),
        "rounds_per_task": ROUNDS_PER_TASK,
        "cases": {},
    }
    try:
        host = SDKCallbacksTest("test_train_all_tasks_with_real_weights_and_measurements")
        started = time.perf_counter()
        for name, replies in cases.items():
            actions, reasons, valid = Counter(), Counter(), Counter()
            samples = []
            for task in TASKS:
                for number in range(1, ROUNDS_PER_TASK + 1):
                    state, sent = host.run_round(task, number=number, option=replies[task], measure=False)
                    decision = json.loads((state / "selection-audit.jsonl").read_text().splitlines()[-1])["decision"]
                    action = decision["model_action"]
                    actions[action] += 1
                    reasons[str(decision.get("response_reason"))] += 1
                    valid[str(decision["model_response_valid"])] += 1
                    if len(samples) < 3:
                        samples.append({
                            "task": task, "round": number, "model_response": decision["model_response"],
                            "normalized_response": decision.get("normalized_response"),
                            "model_action": action, "response_reason": decision.get("response_reason"),
                            "final_params": decision["final_params"],
                            "recommended_params": decision["recommended_params"],
                        })
            total = ROUNDS_PER_TASK * len(TASKS)
            fallback = actions["conservative_invalid_response"]
            results["cases"][name] = {
                "reply_by_task": replies,
                "rounds": total,
                "fallback_count": fallback,
                "fallback_rate": round(fallback / total, 4),
                "actions": dict(actions),
                "rejection_reasons": {key: value for key, value in reasons.items() if key != "None"},
                "validity": dict(valid),
                "audit_samples": samples,
            }
            print(f"{name:36s} fallback {fallback:2d}/{total}  actions={dict(actions)} "
                  f"reasons={results['cases'][name]['rejection_reasons']}", flush=True)
        results["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    finally:
        SDKCallbacksTest.doClassCleanups()
    path = OUT / "results.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {path}", flush=True)


if __name__ == "__main__":
    main()
