"""10-round local replay of the v6 platform B-task run.

Two modes, strictly separated (per the user's requirement not to conflate them):

  1. fixed-history replay  -- feed the EXACT parameters the platform executed
     (lr/bs/epochs/action per round) into the same continuation kernel, with the
     same parent-checkpoint chaining, and check whether each round's public
     validation RMSE matches the platform report (665.7101, 657.8522, ...).

  2. dynamic-decision replay -- drive the real policy (RAC-HPO dynamic search +
     real PyTRIO rac/conservative decision) for 10 rounds and compare the
     resulting parameter/method trajectory against the platform.

What CANNOT be reproduced locally is recorded explicitly (never assumed):
  * platform rnd.model() is a platform RPC -> substituted by a local PyTRIO
    sampling call against the SAME sampler path; decision text may differ.
  * platform primary metric `old`/`new` comes from the HIDDEN set the platform
    evaluates; locally we only have the public validation split, so the
    acceptance gate uses the public-validation RMSE (a known gap).
  * the platform's exact surrogate/shadow evidence state is not shipped back in
    the report, so `shadow_evidence(records, ...)` is recomputed locally.

This script is REPLAY/AUDIT ONLY. It writes nothing to git and never touches the
platform.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "experiments/s2-ablation-b-20261125/data"
OUT = ROOT / "experiments/s2-ablation-b-20261125/replay"

sys.path.insert(0, str(DATA))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "official_submission"))

os.environ.setdefault("BASELINE_CPU_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np  # noqa: E402

from baselines.data import read_dataset  # noqa: E402
from baselines.model import Model  # noqa: E402
from rac_hpo.contest.continuation import evaluate_primary  # noqa: E402

CKPT = DATA / "checkpoint.npz"
SAMPLER_PATH = "trio://run_1fei9lfkoj70/sampler_weights/industrial-harness-lora-selection-v3-20261124"
BASE_MODEL = "Qwen/Qwen3.5-4B"

# Exact v6 platform B-task trajectory (extracted from platform report
# 82522846a0d57928a16292b2c4ad183a). Each entry: (action, lr, batch_size, epochs,
# platform_public_validation_rmse, decision).
PLATFORM_TRAJECTORY = [
    ("rac",          0.00300, 128, 2, 665.7101, "promote"),
    ("rac",          0.00300, 128, 2, 657.8522, "promote"),
    ("rac",          0.00300, 128, 2, 657.8522, "keep"),
    ("conservative", 0.00493, 106, 1, 648.6114, "promote"),
    ("rac",          0.00493, 106, 2, 648.8518, "keep"),
    ("conservative", 0.00300, 469, 1, 648.8518, "keep"),
    ("conservative", 0.00300, 351, 1, 648.8518, "keep"),
    ("rac",          0.00493, 106, 2, 651.4012, "keep"),
    ("conservative", 0.00300, 34,  1, 647.9542, "promote"),
    ("rac",          0.00300, 34,  2, 647.9542, "keep"),
]


def fit_plain(model, x, y, epochs):
    return model.fit(x, y, epochs)


def _blend(model, shadow, decay):
    for name, value in model.params.items():
        shadow[name] = decay * shadow[name] + (1 - decay) * value


def fit_ema(model, x, y, epochs, decay=0.6):
    shadow = {name: value.copy() for name, value in model.params.items()}
    for _ in range(epochs):
        model.fit(x, y, 1)
        _blend(model, shadow, decay)
    model.params = {name: value.copy() for name, value in shadow.items()}
    model.validate()
    return []


def score_rmse(model, data):
    pred = model.predict(data["x"])
    err = pred - data["y"]
    return float(np.sqrt(np.mean(err ** 2)))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fixed_history_replay(base, train, valid):
    """Feed the exact platform parameters and check RMSE parity per round.

    v6 uses EMA (decay 0.6) for regression, so every round applies the EMA
    kernel. The parent chain is reproduced: an accepted round's checkpoint
    becomes the next round's parent; a rejected round falls back to the previous
    selected checkpoint.
    """
    rows = []
    selected = copy.deepcopy(base)          # current platform-selected checkpoint
    selected_rmse = score_rmse(selected, valid)
    prev_selected_sha = "baseline-cpu-b-rul-20261110-v1"  # root parent id
    chain = [prev_selected_sha]
    for rnd, (action, lr, bs, ep, plat_rmse, decision) in enumerate(PLATFORM_TRAJECTORY, start=1):
        # Start each round from the CURRENT selected checkpoint.
        model = copy.deepcopy(selected)
        parent_rmse = selected_rmse
        model.meta["learning_rate"] = lr
        model.meta["batch_size"] = int(bs)
        model.validate()
        fit_ema(model, train["x"], train["y"], int(ep), decay=0.6)
        candidate_rmse = score_rmse(model, valid)

        # Platform decision determines whether this candidate is selected.
        is_promote = decision == "promote"
        if is_promote:
            selected = copy.deepcopy(model)
            selected_rmse = candidate_rmse
            selected_sha = f"round-{rnd:02d}-local"
        else:
            selected_sha = prev_selected_sha
            # keep: the platform-reported validation_metrics is the PARENT's RMSE,
            # not the candidate's. So the "local selected RMSE" stays parent_rmse.
        # The platform report's validation_metrics reflects the SELECTED checkpoint
        # (parent on keep, candidate on promote), not the candidate.
        local_selected_rmse = candidate_rmse if is_promote else parent_rmse

        rows.append({
            "round": rnd, "action": action, "lr": lr, "batch_size": bs, "epochs": ep,
            "platform_decision": decision, "platform_rmse": plat_rmse,
            "parent_rmse": round(parent_rmse, 4),
            "candidate_rmse": round(candidate_rmse, 4),
            "local_selected_rmse": round(local_selected_rmse, 4),
            "rmse_delta": round(local_selected_rmse - plat_rmse, 4),
            "parent_id": prev_selected_sha, "selected_id": selected_sha,
            "parent_chained": prev_selected_sha in chain,
        })
        chain.append(selected_sha)
        prev_selected_sha = selected_sha
    return rows


def dynamic_replay(base, train, valid, *, seed=42, rounds=10):
    """Drive the real policy + real PyTRIO decision for `rounds` rounds."""
    from rac_hpo.contest.continuation import evaluate_diagnostics
    from rac_hpo.contest.rac_policy import ContestRACPolicy
    from rac_hpo.contest.sampler import selection_messages
    from rac_hpo.contest.stage3_controls import parse_decision

    import pytrio as trio

    svc = trio.ServiceClient()
    client = svc.create_sampling_client(BASE_MODEL, model_path=SAMPLER_PATH)
    tokenizer = client.get_tokenizer()

    def decide(context):
        messages = selection_messages(context)
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        ids = tokenizer.encode(prompt, add_special_tokens=False)
        seq = client.sample(
            prompt=trio.ModelInput.from_ints(ids),
            sampling_params=trio.SamplingParams(max_tokens=128, temperature=0, seed=seed,
                                                stop=["<|im_end|>"]),
            num_samples=1,
        ).result().sequences[0]
        return {"raw": seq.text, "parsed": parse_decision(seq.text)}

    model = copy.deepcopy(base)
    proof = {"passed": False, "reason": "local_ablation", "observations": 0, "rounds": []}
    policy = ContestRACPolicy(
        "B", {"diagnostics": evaluate_diagnostics(model, valid, None), "surrogate_evidence": proof},
        transfer_mode="off", surrogate_mode="shadow", cost_mode="off", bearing_mode="off",
        enforce_shadow_evidence=True, seed=seed,
    )
    records = []
    rows = []
    best = copy.deepcopy(base)
    for rnd in range(1, rounds + 1):
        local_parent = evaluate_primary(model, valid)
        proposal, trace = policy.propose(model.meta, records, transfer_records=(), round_index=rnd)
        params = trace["params"].copy()
        recommended_lr = float(params["learning_rate"])
        conservative_lr = max(policy.space["learning_rate"]["low"], recommended_lr / 2)
        alternative = {**params, "learning_rate": conservative_lr, "sampling_level": 1, "epochs": 1}
        decision = decide({
            "task": "B", "round": rnd, "history": records,
            "selected_metric": local_parent,
            "rac": params, "conservative": alternative,
        })
        action = decision["parsed"]["action"]
        if action != "rac":
            params = alternative
        model.meta["learning_rate"] = params["learning_rate"]
        model.meta["batch_size"] = int(params["batch_size"])
        model.validate()
        t_train0 = time.monotonic()
        fit_ema(model, train["x"], train["y"], int(params["epochs"]), decay=0.6)
        train_wall = max(time.monotonic() - t_train0, 1e-6)
        local_candidate = evaluate_primary(model, valid)
        candidate_diag = evaluate_diagnostics(model, valid, None)
        score = policy.score(candidate_diag)
        accepted = local_candidate < local_parent
        # Build the record from the CANDIDATE (pre-rollback) diagnostics so the
        # diagnostics and robust_objective are mutually consistent (same as
        # ablate.py / contest_submission.py). A rejected candidate still enters
        # history (status="completed"), matching platform semantics.
        # training_seconds MUST be > 0 or _trial rejects the record.
        record = {"round": rnd, "rac_params": params, "diagnostics": candidate_diag,
                  "robust_objective": score["robust_objective"], "parent_objective": policy.baseline_objective,
                  "training_seconds": train_wall, "training_cpu_seconds": train_wall, "accepted": accepted}
        records.append(record)
        if accepted:
            best = copy.deepcopy(model)
        else:
            model = copy.deepcopy(best)
        rows.append({
            "round": rnd, "action": action, "recommended_lr": recommended_lr,
            "final_lr": params["learning_rate"], "batch_size": params["batch_size"],
            "epochs": params["epochs"], "search_method": trace.get("method"),
            "search_reason": trace.get("reason"),
            "surrogate_mode": trace.get("surrogate_mode"),
            "completed_history": None,
            "decision_valid": decision["parsed"]["valid"],
            "decision_reason_codes": decision["parsed"]["reason_codes"],
            "parent_rmse": round(local_parent, 4), "candidate_rmse": round(local_candidate, 4),
            "accepted": accepted,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fixed", "dynamic", "both"], default="both")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--rounds", type=int, default=10)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    base = Model.load(CKPT)
    train = read_dataset(DATA / "public/train.jsonl", "regression", base.meta["classes"], base.meta["paths"])
    valid = read_dataset(DATA / "public/validation.jsonl", "regression", base.meta["classes"], base.meta["paths"])
    print(f"B replay: train {train['x'].shape[0]}, valid {valid['x'].shape[0]}, "
          f"parent RMSE {score_rmse(base, valid):.4f}", flush=True)

    result = {"parent_rmse": score_rmse(base, valid),
              "unreproducible": [
                  "platform rnd.model() is a platform RPC; local replay uses a PyTRIO "
                  "sampling call against the same sampler path, so decision text may differ",
                  "platform primary metric old/new is evaluated on the HIDDEN set; local "
                  "replay uses the public validation split only",
                  "platform surrogate/shadow evidence state is not shipped back; recomputed locally",
              ]}

    if args.mode in ("fixed", "both"):
        rows = fixed_history_replay(base, train, valid)
        result["fixed_history_replay"] = rows
        print("\n=== fixed-history replay (platform params -> local RMSE) ===", flush=True)
        for r in rows:
            flag = "OK" if abs(r["rmse_delta"]) < 0.01 else "DIFF"
            print(f"  r{r['round']}: lr={r['lr']:.5f} bs={r['batch_size']} ep={r['epochs']} "
                  f"plat={r['platform_rmse']:.4f} local_selected={r['local_selected_rmse']:.4f} "
                  f"(parent={r['parent_rmse']:.4f} cand={r['candidate_rmse']:.4f}) "
                  f"d={r['rmse_delta']:+.4f} {flag} {r['platform_decision']}", flush=True)

    if args.mode in ("dynamic", "both"):
        rows = dynamic_replay(base, train, valid, seed=args.seed, rounds=args.rounds)
        result["dynamic_replay"] = rows
        print("\n=== dynamic-decision replay (real PyTRIO + RAC-HPO) ===", flush=True)
        for r in rows:
            print(f"  r{r['round']}: action={r['action']:13s} method={r['search_method']:20s} "
                  f"lr={r['final_lr']:.5f} bs={r['batch_size']} ep={r['epochs']} "
                  f"parent={r['parent_rmse']:.4f} cand={r['candidate_rmse']:.4f} acc={r['accepted']}",
                  flush=True)

    out = OUT / f"replay_seed{args.seed}_r{args.rounds}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
