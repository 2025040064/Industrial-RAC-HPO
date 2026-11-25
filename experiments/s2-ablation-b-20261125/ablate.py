"""S2 factorial ablation: isolate EMA (factor A) and regression lr-floor (factor B)
on the B task, faithfully reproducing the v6 platform round loop.

Groups:
  G0: EMA=off, lr floor = 1e-5   (v5 original)
  G1: EMA=on,  lr floor = 1e-5
  G2: EMA=off, lr floor = 3e-3   (v6)
  G3: EMA=on,  lr floor = 3e-3   (v6 full == the real v6 training mechanism)

Design constraints (from user):
  * 2x2 factorial, no fixed lr; RAC-HPO searches lr dynamically in all groups.
  * EMA decay fixed at 0.6 whenever EMA is on.
  * Real PyTRIO rac/conservative decision (selection contract), temperature=0.
  * "3 rounds" = 3 consecutive candidate submissions with the acceptance gate.
  * Same parent checkpoint, data split, validation, search strategy, seed.
  * Phase 1 smoke: 3 seeds x 4 groups x 3 rounds = 36 continuation runs, single-thread CPU.
  * Record: lr before/after clip, floor-trigger count, proxy predictions, gates,
    per-round accept, CPU/wall time, epochs, sample count, candidate accept rate.

The original lr floor is VERIFIED from the v5 image (not assumed):
  v5  rac_policy.py  "learning_rate": {"low": 1e-5, "high": .01, "log": True}
  v6  rac_policy.py  "learning_rate": {"low": 1e-5 if task=="A" else 3e-3, ...}
  v5  continuation.py  fit_epochs -> model.fit(...) (NO EMA)
  v6  continuation.py  fit_epochs -> _fit_averaged(...) (EMA_DECAY=.6)
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time
from pathlib import Path

# --- path setup ---------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "experiments/s2-ablation-b-20261125/data"
OUT = ROOT / "experiments/s2-ablation-b-20261125/results"
PKG = DATA  # B package: contains public/, checkpoint.npz, baselines/

sys.path.insert(0, str(PKG))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "official_submission"))

os.environ.setdefault("BASELINE_CPU_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np  # noqa: E402

from baselines.data import read_dataset  # noqa: E402
from baselines.model import Model  # noqa: E402

from rac_hpo.contest.continuation import evaluate_diagnostics, evaluate_primary  # noqa: E402
from rac_hpo.contest.policy import accept_candidate  # noqa: E402
from rac_hpo.contest.rac_policy import ContestRACPolicy, REGRESSION_LEARNING_RATE_LOW  # noqa: E402
from rac_hpo.contest.sampler import selection_messages  # noqa: E402
from rac_hpo.contest.stage3_controls import parse_decision  # noqa: E402

CKPT = DATA / "checkpoint.npz"
SAMPLER_PATH = "trio://run_1fei9lfkoj70/sampler_weights/industrial-harness-lora-selection-v3-20261124"
BASE_MODEL = "Qwen/Qwen3.5-4B"
V5_LR_LOW = 1e-5
V6_LR_LOW = REGRESSION_LEARNING_RATE_LOW  # 3e-3


# ---------------------------------------------------------------- train kernels
def fit_plain(model, x, y, epochs):
    """v5 semantics: direct epoch-end weights, no EMA."""
    return model.fit(x, y, epochs)


def _blend(model, shadow, decay):
    for name, value in model.params.items():
        shadow[name] = decay * shadow[name] + (1 - decay) * value


def fit_ema(model, x, y, epochs, decay=0.6):
    """v6 semantics: epoch-averaged continuation (Polyak average folded back)."""
    shadow = {name: value.copy() for name, value in model.params.items()}
    for _ in range(epochs):
        model.fit(x, y, 1)
        _blend(model, shadow, decay)
    model.params = {name: value.copy() for name, value in shadow.items()}
    model.validate()
    return []


def make_kernel(ema_on: bool):
    if ema_on:
        return lambda m, x, y, e: fit_ema(m, x, y, e, decay=0.6)
    return fit_plain


# ---------------------------------------------------------------- scoring
def score_rmse(model, data):
    pred = model.predict(data["x"])
    err = pred - data["y"]
    return float(np.sqrt(np.mean(err ** 2)))


# ---------------------------------------------------------------- PyTRIO decision
class LocalDecisionClient:
    """Real PyTRIO sampling client for the selection contract (rac/conservative)."""

    def __init__(self):
        import pytrio as trio
        self.trio = trio
        self.client = None
        self.tokenizer = None

    def _ensure(self):
        if self.client is None:
            svc = self.trio.ServiceClient()
            self.client = svc.create_sampling_client(BASE_MODEL, model_path=SAMPLER_PATH)
            self.tokenizer = self.client.get_tokenizer()

    def decide(self, context):
        """Return parsed decision dict from the production selection contract."""
        self._ensure()
        messages = selection_messages(context)
        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        ids = self.tokenizer.encode(prompt, add_special_tokens=False)
        seq = self.client.sample(
            prompt=self.trio.ModelInput.from_ints(ids),
            sampling_params=self.trio.SamplingParams(max_tokens=128, temperature=0, seed=42,
                                                     stop=["<|im_end|>"]),
            num_samples=1,
        ).result().sequences[0]
        raw = seq.text
        parsed = parse_decision(raw)
        return {"raw": raw, "parsed": parsed}


# ---------------------------------------------------------------- round driver
def run_group(base, train, valid, groups, *, ema_on, lr_low, rounds, seed, tag):
    """Run `rounds` consecutive candidate submissions, mirroring contest_submission.train.

    Returns a full per-round audit trail.
    """
    model = copy.deepcopy(base)
    kernel = make_kernel(ema_on)
    best = copy.deepcopy(model)
    best_rmse = score_rmse(best, valid)

    # v6 platform B task has public_projection.source_metadata = False, so
    # validation_groups is None and the per-bearing gate NEVER fires (verified:
    # no v6 platform round reports a "bearing" rejection reason). Reproduce that
    # exactly: pass groups=None to evaluate_diagnostics (overall RMSE only), and
    # skip accept_candidate's bearing branch.
    groups_for_diag = None

    # Build the policy with the target lr floor.
    proof = {"passed": False, "reason": "local_ablation", "observations": 0, "rounds": []}
    policy = ContestRACPolicy(
        "B", {"diagnostics": evaluate_diagnostics(model, valid, groups_for_diag), "surrogate_evidence": proof},
        transfer_mode="off", surrogate_mode="shadow", cost_mode="off", bearing_mode="off",
        enforce_shadow_evidence=True, seed=seed,
    )
    # Override the regression lr floor (factor B).
    policy.space["learning_rate"]["low"] = 1e-5 if policy.task == "A" else lr_low

    client = LocalDecisionClient()
    records = []  # platform history rows
    audit = []

    for rnd in range(1, rounds + 1):
        t0 = time.monotonic()
        cpu0 = time.process_time()

        baseline_diag = evaluate_diagnostics(model, valid, groups_for_diag)
        local_parent = evaluate_primary(model, valid)
        # NOTE: policy.baseline_objective stays FROZEN at the parent-checkpoint J
        # (set in __init__), exactly like contest_submission.py which never
        # updates it across rounds. Do NOT overwrite it here.

        # propose: RAC-HPO dynamic search
        proposal, trace = policy.propose(model.meta, records, transfer_records=(), round_index=rnd)
        params = trace["params"].copy()
        recommended_lr = float(params["learning_rate"])

        # conservative alternative: half lr, clamped to floor
        conservative_lr = max(lr_low, recommended_lr / 2)
        alternative = {**params, "learning_rate": conservative_lr, "sampling_level": 1, "epochs": 1}

        # real PyTRIO decision
        selected_metric = local_parent
        decision = client.decide({
            "task": "B", "round": rnd, "history": records,
            "selected_metric": selected_metric,
            "rac": params, "conservative": alternative,
        })
        action = decision["parsed"]["action"]
        if action != "rac":
            params = alternative
            proposal = dict(proposal, **alternative)
            proposal["strategy"] = "uniform"

        final_lr = float(params["learning_rate"])
        floor_triggered = final_lr <= lr_low + 1e-12

        # apply params and fit
        model.meta["learning_rate"] = final_lr
        model.meta["batch_size"] = int(params["batch_size"])
        model.validate()
        train_cpu0 = time.process_time()
        epochs = int(params["epochs"])
        kernel(model, train["x"], train["y"], epochs)
        train_cpu = time.process_time() - train_cpu0

        candidate_diag = evaluate_diagnostics(model, valid, groups_for_diag)
        score = policy.score(candidate_diag)
        local_candidate = evaluate_primary(model, valid)

        # acceptance gate (mirror contest_submission.train, but local-only metric).
        # v6 platform: validation_groups is None -> bearing_gate is None (never
        # fires). Reproduce that: no per-bearing guard.
        improved = local_candidate < local_parent  # lower is better for rmse
        parent_matches = True
        candidate_matches = True
        locally_improved = improved
        bearing_gate = None
        objective_improved = score["robust_objective"] < policy.baseline_objective
        accepted = (improved and parent_matches and candidate_matches and locally_improved
                    and bearing_gate is not False and objective_improved)

        if accepted:
            best = copy.deepcopy(model)
            best_rmse = local_candidate
        else:
            model = copy.deepcopy(best)

        # record the round as platform-style history for the next proposal
        record = {
            "round": rnd, "rac_params": params, "diagnostics": candidate_diag,
            "robust_objective": score["robust_objective"], "parent_objective": policy.baseline_objective,
            "training_seconds": time.monotonic() - t0,
            "training_cpu_seconds": train_cpu,
            "accepted": accepted,
        }
        records.append(record)

        audit.append({
            "round": rnd,
            "recommended_lr": recommended_lr,
            "final_lr": final_lr,
            "floor": lr_low,
            "floor_triggered": floor_triggered,
            "action": action,
            "decision_valid": decision["parsed"]["valid"],
            "decision_reason_codes": decision["parsed"]["reason_codes"],
            "decision_risk": decision["parsed"]["risk"],
            "params": {k: (int(v) if isinstance(v, np.integer) else float(v) if isinstance(v, (np.floating, float)) else v)
                       for k, v in params.items()},
            "search_method": trace.get("method"),
            "search_reason": trace.get("reason"),
            "surrogate_mode": trace.get("surrogate_mode"),
            "surrogate_activation_reason": trace.get("surrogate_activation_reason"),
            "candidate_count": trace.get("candidate_count"),
            "eligible_candidate_count": trace.get("eligible_candidate_count"),
            "predicted_overall_mae": trace.get("predicted_overall_mae"),
            "predicted_cost_seconds": trace.get("predicted_cost_seconds"),
            "acquisition": trace.get("acquisition"),
            "forward_validation": trace.get("forward_validation"),
            "parent_rmse": local_parent,
            "candidate_rmse": local_candidate,
            "accepted": accepted,
            "bearing_gate": bearing_gate,
            "objective_improved": objective_improved,
            "epochs": epochs,
            "samples": int(train["x"].shape[0]),
            "train_cpu_seconds": train_cpu,
            "wall_seconds": time.monotonic() - t0,
            "process_cpu_seconds": time.process_time() - cpu0,
        })

    return {
        "tag": tag, "ema_on": ema_on, "lr_low": lr_low, "seed": seed,
        "final_rmse": best_rmse,
        "baseline_rmse": score_rmse(base, valid),
        "accepted_rounds": sum(a["accepted"] for a in audit),
        "floor_triggered_rounds": sum(a["floor_triggered"] for a in audit),
        "audit": audit,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 2024, 7])
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--groups", type=str, nargs="+",
                    default=["G0", "G1", "G2", "G3"])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    base = Model.load(CKPT)
    train = read_dataset(DATA / "public/train.jsonl", "regression", base.meta["classes"], base.meta["paths"])
    valid = read_dataset(DATA / "public/validation.jsonl", "regression", base.meta["classes"], base.meta["paths"])
    # B groups by bearing
    groups = []
    for line in (DATA / "public/validation.jsonl").read_text().splitlines():
        if line.strip():
            groups.append(json.loads(line)["meta"]["bearing"])
    print(f"B package: train {train['x'].shape[0]} rows, valid {valid['x'].shape[0]} rows, "
          f"parent RMSE {score_rmse(base, valid):.4f}", flush=True)

    group_specs = {
        "G0": dict(ema_on=False, lr_low=V5_LR_LOW),
        "G1": dict(ema_on=True, lr_low=V5_LR_LOW),
        "G2": dict(ema_on=False, lr_low=V6_LR_LOW),
        "G3": dict(ema_on=True, lr_low=V6_LR_LOW),
    }

    all_results = {}
    for gname in args.groups:
        spec = group_specs[gname]
        for seed in args.seeds:
            tag = f"{gname}_seed{seed}"
            print(f"\n=== {tag} (ema={spec['ema_on']}, lr_low={spec['lr_low']:.1e}, rounds={args.rounds}) ===", flush=True)
            res = run_group(base, train, valid, groups,
                            ema_on=spec["ema_on"], lr_low=spec["lr_low"],
                            rounds=args.rounds, seed=seed, tag=tag)
            all_results[tag] = res
            print(f"  final RMSE {res['final_rmse']:.4f} (base {res['baseline_rmse']:.4f}), "
                  f"accepted {res['accepted_rounds']}/{args.rounds}, "
                  f"floor-triggered {res['floor_triggered_rounds']}/{args.rounds}", flush=True)

    (args.out / "ablation-results.json").write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"\nsaved {args.out / 'ablation-results.json'}")


if __name__ == "__main__":
    main()
