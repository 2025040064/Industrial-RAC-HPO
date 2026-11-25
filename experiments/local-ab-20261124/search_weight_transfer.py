"""A-direction leg 3: WEIGHT TRANSFER from the temporal teacher.

Key observation: the teacher is 87 -> 32 -> 1 and the parent is 24 -> 32 -> 1.
Both share hidden width 32, and the teacher's first 24 inputs are exactly the
student's original features. Therefore the teacher's learned representation can
be transferred into the student by:

    student.w1 = teacher.w1[:24, :]     # keep weights on original features
    student.b1 = teacher.b1
    student.w2 = teacher.w2
    student.b2 = teacher.b2

while keeping the parent's mean/scale/paths/meta (which the platform校验 locks).
This lets the 24-dim student INHERIT the teacher's temporal-aware representation
instead of merely matching its answers (soft labels). All changes are weights
only -- fully inside the frozen contract.

We compare: parent (no transfer), transfer-only, transfer + EMA continuation.
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


def train_teacher(x, y, *, epochs=15, hidden=32, lr=0.002, batch=256, seed=42):
    model = ab.Model("regression", [f"p{i}" for i in range(x.shape[1])], [],
                     x, y, hidden=hidden, learning_rate=lr, batch_size=batch, seed=seed)
    model.fit(x, y, epochs)
    return model


def transfer_weights(base, teacher, *, blend=1.0):
    """Copy teacher's representation into a clone of the parent checkpoint."""
    student = copy.deepcopy(base)
    t = teacher.params
    s = student.params
    # w1: teacher's original-feature block; must match student's input width.
    assert t["w1"].shape[0] >= s["w1"].shape[0]
    new_w1 = t["w1"][:s["w1"].shape[0], :]
    new_b1 = t["b1"]
    new_w2 = t["w2"]
    new_b2 = t["b2"]
    if blend < 1.0:
        new_w1 = blend * new_w1 + (1 - blend) * s["w1"]
        new_b1 = blend * new_b1 + (1 - blend) * s["b1"]
        new_w2 = blend * new_w2 + (1 - blend) * s["w2"]
        new_b2 = blend * new_b2 + (1 - blend) * s["b2"]
    student.params = {"w1": new_w1.copy(), "b1": new_b1.copy(),
                      "w2": new_w2.copy(), "b2": new_b2.copy()}
    # Reset optimizer moments: transferred weights are a fresh starting point.
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
        kernel = ab2.make_ema(decay)
        kernel(model, train["x"], train["y"], epochs)
        mae, rmse = ab.score(model, valid)
        if rmse < best_score[1]:
            best, best_score = copy.deepcopy(model), (mae, rmse)
            accepted += 1
        else:
            model = copy.deepcopy(best)
    halves = [rd.subset_score(best, valid, m) for m in masks]
    return {"tag": tag, "mae": best_score[0], "rmse": best_score[1],
            "accepted": accepted,
            "half_mae": [round(h[0], 4) for h in halves]}


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
        teacher = train_teacher(xtr, train["y"], seed=t_seed)
        err = teacher.predict(xtr) - train["y"]
        print(f"teacher seed {t_seed}: in-sample MAE {np.abs(err).mean():.4f}", flush=True)
        for blend in (0.5, 0.75, 1.0):
            student = transfer_weights(base, teacher, blend=blend)
            mae0, rmse0 = ab.score(student, valid)
            rows.append({"tag": f"transfer_s{t_seed}_b{blend}_round0",
                         "mae": mae0, "rmse": rmse0, "accepted": 0,
                         "half_mae": [round(rd.subset_score(student, valid, m)[0], 4) for m in masks]})
            print(f"  blend={blend}: round0 MAE {mae0:.4f} RMSE {rmse0:.4f}", flush=True)
            for decay, lr in product((0.4, 0.6, 0.8), (3e-3, 4e-3)):
                result = simulate_from(student, train, valid, masks, rounds=10,
                                       lr=lr, epochs=5, decay=decay,
                                       tag=f"transfer_s{t_seed}_b{blend}_d{decay}_lr{lr:g}")
                both = all(h < p for h, p in zip(result["half_mae"], parent_halves))
                result["both_halves_better"] = both
                rows.append(result)
                print(f"    d{decay} lr{lr:g}: MAE {result['mae']:.4f} "
                      f"RMSE {result['rmse']:.4f} acc {result['accepted']}/10 "
                      f"{'BOTH' if both else 'SPLIT'}", flush=True)

    (OUT / "search-weight-transfer-results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    rows.sort(key=lambda r: r["rmse"])
    print("=== top 10 ===", flush=True)
    for r in rows[:10]:
        print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
