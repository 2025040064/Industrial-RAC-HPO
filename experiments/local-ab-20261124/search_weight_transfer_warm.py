"""A-direction leg 3 (fixed): warm-start teacher + weight transfer.

The naive transfer failed because a from-scratch teacher lives in a different
weight basin than the parent. Fix: initialise the 87-dim teacher FROM the parent

    teacher.w1[:24] = parent.w1      # inherited, then fine-tuned on window tasks
    teacher.w1[24:] ~ small random   # new window-feature inputs
    teacher.b1/w2/b2 = parent

so the teacher stays in the parent's neighbourhood. After training, transfer
teacher.w1[:24]/b1/w2/b2 back into a clone of the parent (mean/scale/paths/meta
unchanged -- only weights move). This passes the platform's preprocessing gate.

Point: at inference the model is stateless 24->32->1 on the current frame, so
this is another way to compile temporal priors into the student's representation.
"""
import copy
import json
import sys
from itertools import product
from pathlib import Path

import numpy as np

sys.path.insert(0, "experiments/local-ab-20261124")
import run_ab as ab  # noqa: E402
import run_ab2 as ab2  # noqa: E402
import run_distill as rd  # noqa: E402

OUT = Path("experiments/local-ab-20261124")


def warm_teacher(base, x, y, *, epochs=15, lr=0.002, batch=256, seed=42, win_scale=0.01):
    n_in = x.shape[1]
    model = ab.Model("regression", [f"p{i}" for i in range(n_in)], [],
                     x, y, hidden=base.meta["hidden"], learning_rate=lr,
                     batch_size=batch, seed=seed)
    rng = np.random.default_rng(seed)
    p = base.params
    model.params = {
        "w1": np.vstack([p["w1"], rng.normal(0, win_scale, (n_in - p["w1"].shape[0], p["w1"].shape[1]))]),
        "b1": p["b1"].copy(),
        "w2": p["w2"].copy(),
        "b2": p["b2"].copy(),
    }
    model.first = {k: np.zeros_like(v) for k, v in model.params.items()}
    model.second = {k: np.zeros_like(v) for k, v in model.params.items()}
    model.mean = np.concatenate([base.mean, np.zeros(n_in - len(base.mean))])
    model.scale = np.concatenate([base.scale, np.ones(n_in - len(base.scale))])
    model.validate()
    model.fit(x, y, epochs)
    return model


def transfer(base, teacher, blend=1.0):
    student = copy.deepcopy(base)
    t, s = teacher.params, student.params
    n = s["w1"].shape[0]
    targets = {
        "w1": t["w1"][:n], "b1": t["b1"], "w2": t["w2"], "b2": t["b2"],
    }
    if blend < 1.0:
        for k in targets:
            targets[k] = blend * targets[k] + (1 - blend) * s[k]
    student.params = {k: v.copy() for k, v in targets.items()}
    student.first = {k: np.zeros_like(v) for k, v in student.params.items()}
    student.second = {k: np.zeros_like(v) for k, v in student.params.items()}
    student.meta["epochs"] = 0
    student.meta["steps"] = 0
    student.validate()
    return student


def simulate_from(base_student, train, valid, masks, *, rounds=10, lr=4e-3,
                  epochs=5, decay=0.6, tag=""):
    model = copy.deepcopy(base_student)
    best = copy.deepcopy(model)
    best_score = ab.score(best, valid)
    accepted = 0
    for _ in range(rounds):
        model.meta["learning_rate"] = lr
        model.meta["batch_size"] = 256
        ab2.make_ema(decay)(model, train["x"], train["y"], epochs)
        mae, rmse = ab.score(model, valid)
        if rmse < best_score[1]:
            best, best_score = copy.deepcopy(model), (mae, rmse)
            accepted += 1
        else:
            model = copy.deepcopy(best)
    halves = [rd.subset_score(best, valid, m) for m in masks]
    return {"tag": tag, "mae": best_score[0], "rmse": best_score[1],
            "accepted": accepted, "half_mae": [round(h[0], 4) for h in halves]}


def main():
    base, train, valid = ab.load()
    uv = np.array([r["unit"] for r in ab.meta("validation")])
    cut = np.median(uv)
    masks = [uv <= cut, uv > cut]
    parent_halves = [rd.subset_score(base, valid, m)[0] for m in masks]
    print(f"parent halves MAE {[round(h, 4) for h in parent_halves]}", flush=True)

    xtr, _ = ab2.temporal_features(train, valid, window=15)
    rows = []
    for t_seed in (42, 7):
        teacher = warm_teacher(base, xtr, train["y"], seed=t_seed)
        err = teacher.predict(xtr) - train["y"]
        print(f"warm teacher seed {t_seed}: in-sample MAE {np.abs(err).mean():.4f}", flush=True)
        for blend in (0.5, 0.75, 1.0):
            student = transfer(base, teacher, blend=blend)
            mae0, rmse0 = ab.score(student, valid)
            print(f"  blend={blend}: round0 MAE {mae0:.4f} RMSE {rmse0:.4f}", flush=True)
            rows.append({"tag": f"warm_s{t_seed}_b{blend}_r0", "mae": mae0, "rmse": rmse0,
                         "accepted": 0, "half_mae": [round(rd.subset_score(student, valid, m)[0], 4) for m in masks]})
            for decay, lr in product((0.4, 0.6, 0.8), (3e-3, 4e-3)):
                result = simulate_from(student, train, valid, masks, rounds=10,
                                       lr=lr, epochs=5, decay=decay,
                                       tag=f"warm_s{t_seed}_b{blend}_d{decay}_lr{lr:g}")
                both = all(h < p for h, p in zip(result["half_mae"], parent_halves))
                result["both_halves_better"] = both
                rows.append(result)
                print(f"    d{decay} lr{lr:g}: MAE {result['mae']:.4f} RMSE {result['rmse']:.4f} "
                      f"acc {result['accepted']}/10 {'BOTH' if both else 'SPLIT'}", flush=True)

    (OUT / "search-weight-transfer-warm-results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    rows.sort(key=lambda r: r["rmse"])
    print("=== top 10 ===", flush=True)
    for r in rows[:10]:
        print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
