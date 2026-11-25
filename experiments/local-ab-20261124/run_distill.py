"""Route A: temporal teacher -> 24-dim student distillation.

The teacher is trained offline on causal per-unit window statistics reconstructed
from ``public/train.jsonl`` meta (unit, cycle). The student stays inside the
frozen contract: 24 -> 32 -> 1 MLP, 833 parameters, predict sees only
``{settings, sensors}``. Only the training TARGET is softened:

    y_student = y_true + beta * (teacher_prediction - y_true)

beta=0 is the current v6-style baseline (EMA + lr floor). Evaluation always
uses the true labels, and a split-by-unit check guards against tuning noise.
"""
import copy
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "experiments/local-ab-20261124")
import run_ab as ab  # noqa: E402
import run_ab2 as ab2  # noqa: E402

OUT = Path("experiments/local-ab-20261124")


def build_teacher(train, valid, *, window=15, epochs=15, lr=0.002, batch=256, seed=42):
    """Train the wide offline teacher on causal window statistics."""
    xtr, xva = ab2.temporal_features(train, valid, window=window)
    model = ab.Model(
        "regression",
        [f"p{i}" for i in range(xtr.shape[1])],
        [],
        xtr,
        train["y"],
        hidden=32,
        learning_rate=lr,
        batch_size=batch,
        seed=seed,
    )
    model.fit(xtr, train["y"], epochs)
    pred = model.predict(xva)
    err = pred - valid["y"]
    print(f"  teacher ({xtr.shape[1]} dims): MAE {np.abs(err).mean():.4f}  "
          f"RMSE {np.sqrt(np.mean(err ** 2)):.4f}", flush=True)
    return model, xtr


def calibrate(pred, y):
    """Linear map teacher output back onto the label scale (fixes range shrink)."""
    design = np.vstack([pred, np.ones_like(pred)]).T
    slope, intercept = np.linalg.lstsq(design, y, rcond=None)[0]
    print(f"  calibration y ~ {slope:.4f} * teacher + {intercept:.4f}", flush=True)
    return slope * pred + intercept


def subset_score(model, valid, mask):
    err = model.predict(valid["x"][mask]) - valid["y"][mask]
    return float(np.abs(err).mean()), float(np.sqrt(np.mean(err ** 2)))


def simulate(base, train, valid, y_target, masks, *, rounds=10, lr=4e-3, batch=256,
             epochs=5, decay=0.6, tag=""):
    """Continuation rounds; accept only if validation RMSE improves (v6 rule)."""
    kernel = ab2.make_ema(decay)
    model = copy.deepcopy(base)
    best = copy.deepcopy(model)
    best_score = ab.score(best, valid)
    accepted = 0
    for _ in range(rounds):
        model.meta["learning_rate"] = lr
        model.meta["batch_size"] = batch
        kernel(model, train["x"], y_target, epochs)
        mae, rmse = ab.score(model, valid)
        if rmse < best_score[1]:
            best, best_score = copy.deepcopy(model), (mae, rmse)
            accepted += 1
        else:
            model = copy.deepcopy(best)
    halves = [subset_score(best, valid, mask) for mask in masks]
    return {
        "tag": tag, "mae": best_score[0], "rmse": best_score[1],
        "accepted": accepted,
        "half_mae": [round(h[0], 4) for h in halves],
        "half_rmse": [round(h[1], 4) for h in halves],
    }


def main():
    base, train, valid = ab.load()
    unit_ids = np.array([r["unit"] for r in ab.meta("validation")])
    cut = np.median(unit_ids)
    masks = [unit_ids <= cut, unit_ids > cut]
    base_halves = subset_score(base, valid, masks[0]), subset_score(base, valid, masks[1])
    print(f"parent  halves MAE {[round(h[0], 4) for h in base_halves]}  "
          f"RMSE {[round(h[1], 4) for h in base_halves]}", flush=True)

    teacher, xtr = build_teacher(train, valid)
    teacher_train_pred = teacher.predict(xtr)
    print(f"  teacher in-sample residual std {np.std(train['y'] - teacher_train_pred):.4f}", flush=True)

    rows = []
    for beta in (0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0):
        y_target = train["y"] + beta * (teacher_train_pred - train["y"])
        result = simulate(base, train, valid, y_target, masks, tag=f"distill_b{beta:g}")
        rows.append(result)
        both_better = all(
            h < b for h, b in zip(result["half_mae"], [x[0] for x in base_halves])
        )
        print(f"beta={beta:<4} MAE {result['mae']:.4f} RMSE {result['rmse']:.4f} "
              f"acc {result['accepted']}/10 halves {result['half_mae']} "
              f"{'BOTH BETTER' if both_better else 'SPLIT'}", flush=True)

    (OUT / "distill-results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Calibrated variant: correct teacher's systematic range compression first.
    print("calibrated variant", flush=True)
    calibrated = calibrate(teacher_train_pred, train["y"])
    cal_rows = []
    for beta in (0.15, 0.3, 0.45, 0.6, 0.8):
        y_target = train["y"] + beta * (calibrated - train["y"])
        result = simulate(base, train, valid, y_target, masks, tag=f"caldistill_b{beta:g}")
        cal_rows.append(result)
        print(f"beta={beta:<4} MAE {result['mae']:.4f} RMSE {result['rmse']:.4f} "
              f"acc {result['accepted']}/10 halves {result['half_mae']}", flush=True)
    (OUT / "distill-calibrated.json").write_text(
        json.dumps(cal_rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    best = min(rows + cal_rows, key=lambda r: r["rmse"])
    print("best by RMSE", json.dumps(best, ensure_ascii=False), flush=True)
    print("saved", OUT / "distill-results.json", OUT / "distill-calibrated.json", flush=True)


if __name__ == "__main__":
    main()
