"""A-direction leg 2: temporal-aware SAMPLE WEIGHTING (no input/arch change).

Soft-label distillation only tells the 24-dim student the teacher's answers;
the student still cannot represent temporal context. A complementary, fully
legal lever is to reweight training samples using temporal signals at TRAIN
time (predict sees only settings+sensors, untouched):

  * degradation-stage weighting: late-cycle samples (near failure) get more mass
  * teacher-error weighting: rows where the OOF temporal teacher is least
    confident / most wrong are up-weighted (the temporal signal matters there)
  * combined schedule: easy->hard via a temperature on the weights

All variants keep parent mean/scale/paths and the 24->32->1 architecture.
"""
import json
import sys
from itertools import product
from pathlib import Path

import numpy as np

sys.path.insert(0, "experiments/local-ab-20261124")
import run_ab as ab  # noqa: E402
import run_ab2 as ab2  # noqa: E402
import run_distill as rd  # noqa: E402
import run_distill_oof as oof  # noqa: E402

OUT = Path("experiments/local-ab-20261124")
CACHE = OUT / "oof_cache"  # created by search_distill.py; must already exist


def weighted_fit(model, x, y, weights, epochs, decay, *, seed=7):
    """EMA continuation with weighted resampling of a FIXED sample count.

    Matches the project's existing unit_balanced / class_focus strategy shape:
    each epoch draws len(x) indices with replacement from p=w, then one fit.
    Same sample count as the uniform baseline, so the comparison is fair.
    """
    shadow = {k: v.copy() for k, v in model.params.items()}
    w = np.asarray(weights, dtype=float)
    w = np.clip(w, 1e-6, None)
    w /= w.sum()
    for _ in range(epochs):
        rng = np.random.default_rng(np.random.SeedSequence(
            [model.meta["seed"], model.meta["epochs"], seed]))
        idx = rng.choice(len(w), size=len(w), replace=True, p=w)
        model.fit(x[idx], y[idx], 1)
        for k, v in model.params.items():
            shadow[k] = decay * shadow[k] + (1 - decay) * v
    model.params = {k: v.copy() for k, v in shadow.items()}
    model.validate()


def simulate_weighted(base, train, valid, masks, weights, *, rounds=10, lr=4e-3,
                      epochs=5, decay=0.6, tag=""):
    model = __import__("copy").deepcopy(base)
    best = __import__("copy").deepcopy(model)
    best_score = ab.score(best, valid)
    accepted = 0
    for _ in range(rounds):
        model.meta["learning_rate"] = lr
        model.meta["batch_size"] = 256
        weighted_fit(model, train["x"], train["y"], weights, epochs, decay)
        mae, rmse = ab.score(model, valid)
        if rmse < best_score[1]:
            best, best_score = __import__("copy").deepcopy(model), (mae, rmse)
            accepted += 1
        else:
            model = __import__("copy").deepcopy(best)
    halves = [rd.subset_score(best, valid, m) for m in masks]
    return {"tag": tag, "mae": best_score[0], "rmse": best_score[1],
            "accepted": accepted,
            "half_mae": [round(h[0], 4) for h in halves]}


def main():
    base, train, valid = ab.load()
    train_meta = ab.meta("train")
    train_units = np.array([r["unit"] for r in train_meta])
    cycles = np.array([r["cycle"] for r in train_meta])
    valid_units = np.array([r["unit"] for r in ab.meta("validation")])
    cut = np.median(valid_units)
    masks = [valid_units <= cut, valid_units > cut]
    parent_halves = [rd.subset_score(base, valid, m)[0] for m in masks]

    y = train["y"]
    # OOF teacher residual (cached)
    oof_path = CACHE / "w15_s42_e15_lr0.002_b256.npy"
    if oof_path.exists():
        oof_pred = np.load(oof_path)
        abs_resid = np.abs(oof_pred - y)
    else:
        print("OOF cache missing; run search_distill.py first", flush=True)
        return
    # degrade stage proxy: cycle within unit, normalised
    max_cycle = np.array([cycles[train_units == u].max() for u in train_units])
    stage = cycles / np.maximum(max_cycle, 1)

    def normalise(w):
        return np.clip(w, 1e-6, None)

    weight_specs = {
        "uniform": np.ones(len(y)),
        "late_linear": normalise(0.5 + stage),
        "late_strong": normalise(0.2 + stage ** 3),
        "err_linear": normalise(0.5 + abs_resid / (abs_resid.mean() + 1e-9)),
        "err_strong": normalise(0.2 + (abs_resid / (abs_resid.mean() + 1e-9)) ** 2),
        "late_x_err": normalise((0.5 + stage) * (0.5 + abs_resid / (abs_resid.mean() + 1e-9))),
    }

    rows = []
    for name, weights in weight_specs.items():
        for decay in (0.4, 0.6, 0.8):
            for lr in (3e-3, 4e-3):
                result = simulate_weighted(base, train, valid, masks, weights,
                                           rounds=10, lr=lr, epochs=5, decay=decay,
                                           tag=f"{name}_d{decay}_lr{lr:g}")
                both = all(h < p for h, p in zip(result["half_mae"], parent_halves))
                result["both_halves_better"] = both
                rows.append(result)
                print(f"{result['tag']:<28} MAE {result['mae']:.4f} "
                      f"RMSE {result['rmse']:.4f} acc {result['accepted']}/10 "
                      f"{'BOTH' if both else 'SPLIT'}", flush=True)

    (OUT / "search-temporal-weight-results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    rows.sort(key=lambda r: r["rmse"])
    print("=== top 10 ===", flush=True)
    for r in rows[:10]:
        print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
