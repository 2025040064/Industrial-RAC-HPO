"""Route A (corrected): OOF teacher predictions -> 24-dim student distillation.

Fix over the first attempt: the teacher's soft labels must be OUT-OF-FOLD.
An in-sample prediction (teacher looking at its own training answer) is heavily
shrunk and overfit; using it as a target injects bias, not temporal knowledge.

Protocol
--------
1. Build causal per-unit window features (87 dims) from train.jsonl meta.
2. Split train units into K folds. For each fold train a teacher on the other
   K-1 folds and predict the held-out fold -> OOF predictions for every train row.
3. Calibrate OOF predictions onto the true label scale (least squares), to
   undo the regression-to-mean range shrink.
4. Student stays 24 -> 32 -> 1 from the parent checkpoint:
       y_student = y_true + beta * (oof_calibrated - y_true)
5. Evaluate on public validation with the true labels and the same accept gate
   as the platform (RMSE improves). Split-by-unit halves guard tuning noise.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "experiments/local-ab-20261124")
import run_ab as ab  # noqa: E402
import run_ab2 as ab2  # noqa: E402
import run_distill as rd  # noqa: E402

OUT = Path("experiments/local-ab-20261124")


def oof_predictions(x, y, units, *, folds=5, epochs=15, lr=0.002, batch=256, seed=42):
    """Per-unit K-fold OOF teacher predictions — no unit predicts itself."""
    unique = np.unique(units)
    rng = np.random.default_rng(seed)
    rng.shuffle(unique)
    parts = np.array_split(unique, folds)
    oof = np.empty(len(y), dtype=float)
    for index, held in enumerate(parts):
        held_set = set(map(int, held))
        mask_val = np.array([int(u) in held_set for u in units])
        mask_train = ~mask_val
        model = ab.Model(
            "regression", [f"p{i}" for i in range(x.shape[1])], [],
            x[mask_train], y[mask_train], hidden=32,
            learning_rate=lr, batch_size=batch, seed=seed + index,
        )
        model.fit(x[mask_train], y[mask_train], epochs)
        oof[mask_val] = model.predict(x[mask_val])
        err = oof[mask_val] - y[mask_val]
        print(f"  fold {index + 1}/{folds}: {mask_val.sum():>6} rows  "
              f"MAE {np.abs(err).mean():.4f}  RMSE {np.sqrt(np.mean(err ** 2)):.4f}", flush=True)
    return oof


def main():
    base, train, valid = ab.load()
    train_units = np.array([r["unit"] for r in ab.meta("train")])
    valid_units = np.array([r["unit"] for r in ab.meta("validation")])
    cut = np.median(valid_units)
    masks = [valid_units <= cut, valid_units > cut]
    base_halves = [rd.subset_score(base, valid, m) for m in masks]
    print(f"parent halves MAE {[round(h[0], 4) for h in base_halves]}", flush=True)

    # 87-dim causal window features (offline only; from train.jsonl meta).
    xtr, _ = ab2.temporal_features(train, valid, window=15)
    print("building OOF teacher predictions ...", flush=True)
    oof = oof_predictions(xtr, train["y"], train_units)
    err = oof - train["y"]
    print(f"  OOF teacher: MAE {np.abs(err).mean():.4f}  "
          f"RMSE {np.sqrt(np.mean(err ** 2)):.4f}  "
          f"(in-sample was MAE 36.5966, residual std 51.36)", flush=True)

    calibrated = rd.calibrate(oof, train["y"])
    err_cal = calibrated - train["y"]
    print(f"  calibrated OOF: MAE {np.abs(err_cal).mean():.4f}  "
          f"RMSE {np.sqrt(np.mean(err_cal ** 2)):.4f}  "
          f"residual std {np.std(err_cal):.4f}", flush=True)

    rows = []
    for name, soft in (("raw", oof), ("calibrated", calibrated)):
        for beta in (0.1, 0.2, 0.3, 0.4, 0.5):
            y_target = train["y"] + beta * (soft - train["y"])
            result = rd.simulate(base, train, valid, y_target, masks,
                                 tag=f"oof_{name}_b{beta:g}")
            rows.append(result)
            both = all(h < b for h, b in
                       zip(result["half_mae"], [x[0] for x in base_halves]))
            print(f"{name:<11} beta={beta:<4} MAE {result['mae']:.4f} "
                  f"RMSE {result['rmse']:.4f} acc {result['accepted']}/10 "
                  f"halves {result['half_mae']} "
                  f"{'BOTH BETTER' if both else 'SPLIT'}", flush=True)

    (OUT / "distill-oof-results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    best_rmse = min(rows, key=lambda r: r["rmse"])
    print("best by RMSE", json.dumps(best_rmse, ensure_ascii=False), flush=True)
    print("saved", OUT / "distill-oof-results.json", flush=True)


if __name__ == "__main__":
    main()
