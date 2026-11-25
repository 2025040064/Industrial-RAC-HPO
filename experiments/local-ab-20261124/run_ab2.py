"""Refined sweep: EMA decay / learning rate / batch size / width, on the real C package.

Same protocol as run_ab.py: 10 continuation rounds, accept only when public
validation RMSE improves, everything else frozen.
"""
import copy
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "experiments/local-ab-20261124")
import run_ab as ab  # noqa: E402

OUT = Path("experiments/local-ab-20261124")


def make_ema(decay, weight_decay=0.0):
    def kernel(model, x, y, epochs):
        shadow = {k: v.copy() for k, v in model.params.items()}
        for _ in range(epochs):
            if weight_decay:
                before = {k: v.copy() for k, v in model.params.items()}
                model.fit(x, y, 1)
                for k in model.params:
                    model.params[k] = model.params[k] - weight_decay * before[k]
            else:
                model.fit(x, y, 1)
            for k, v in model.params.items():
                shadow[k] = decay * shadow[k] + (1 - decay) * v
        model.params = {k: v.copy() for k, v in shadow.items()}
        model.validate()
    return kernel


def plain(model, x, y, epochs):
    model.fit(x, y, epochs)


def simulate(base, train, valid, *, rounds, lr, batch, epochs, kernel, widen_to=0, tag=""):
    model = copy.deepcopy(base)
    if widen_to:
        ab.widen(model, hidden=widen_to)
        model.meta["epochs"] = 0
    best = copy.deepcopy(model)
    best_score = ab.score(best, valid)
    trace = [{"round": 0, "mae": best_score[0], "rmse": best_score[1], "accepted": True}]
    for rnd in range(1, rounds + 1):
        model.meta["learning_rate"] = lr
        model.meta["batch_size"] = batch
        kernel(model, train["x"], train["y"], epochs)
        mae, rmse = ab.score(model, valid)
        accepted = rmse < best_score[1]
        if accepted:
            best, best_score = copy.deepcopy(model), (mae, rmse)
        else:
            model = copy.deepcopy(best)
        trace.append({"round": rnd, "mae": mae, "rmse": rmse, "accepted": accepted})
    return {"tag": tag, "final_mae": best_score[0], "final_rmse": best_score[1],
            "accepted": int(sum(r["accepted"] for r in trace[1:])), "trace": trace}


def temporal_features(train, valid, window=15, sensor_from=3):
    """Causal per-unit rolling statistics with a closed-form slope (no polyfit)."""
    import pandas as pd

    def build(x, rows):
        frame = pd.DataFrame(x, columns=[f"f{i}" for i in range(x.shape[1])])
        frame["unit"] = [r["unit"] for r in rows]
        frame["cycle"] = [r["cycle"] for r in rows]
        frame["row"] = np.arange(len(frame))
        frame = frame.sort_values(["unit", "cycle"])
        keep = [c for c in frame.columns if c.startswith("f") and int(c[1:]) >= sensor_from]
        blocks = []
        for _, group in frame.groupby("unit", sort=False):
            roll = group[keep].rolling(window, min_periods=1)
            mean = roll.mean()
            std = roll.std(ddof=0).fillna(0.0)
            values = group[keep].to_numpy(float)
            n = np.arange(1, len(values) + 1, dtype=float)
            cs = np.cumsum(values, axis=0)
            ct = np.cumsum(n[:, None] * values, axis=0)
            ct2 = np.cumsum(n ** 2)
            width = np.minimum(n, window)
            # window-local sums via shifted cumulative arrays
            lo = np.maximum(np.arange(len(values)) - window + 1, 0)
            sum_x = cs - np.vstack([np.zeros((1, values.shape[1])), cs])[lo]
            sum_tx = ct - np.vstack([np.zeros((1, values.shape[1])), ct])[lo]
            start = lo.astype(float)
            sum_t = (start + n - 1 + start) * width / 2.0
            sum_t2 = (n - 1 + start) * (n - 1 + start + 1) * (2 * (n - 1 + start) + 1) / 6.0 \
                - (start - 1) * start * (2 * start - 1) / 6.0
            denom = width * sum_t2 - sum_t ** 2
            denom[denom < 1e-9] = np.nan
            slope = (width[:, None] * sum_tx - sum_t[:, None] * sum_x) / denom[:, None]
            slope = np.nan_to_num(slope, nan=0.0, posinf=0.0, neginf=0.0)
            block = pd.DataFrame(
                {**{f"{c}__wmean": mean[c].to_numpy() for c in keep},
                 **{f"{c}__wstd": std[c].to_numpy() for c in keep},
                 **{f"{c}__wslope": slope[:, j] for j, c in enumerate(keep)}},
                index=group.index,
            )
            blocks.append(block)
        out = pd.concat(blocks).sort_index()
        return np.nan_to_num(out.to_numpy(dtype=np.float64), nan=0.0)

    return np.hstack([train["x"], build(train["x"], ab.meta("train"))]), \
        np.hstack([valid["x"], build(valid["x"], ab.meta("validation"))])


def from_scratch(train, valid, xtr, xva, *, epochs=15, hidden=32, lr=0.002, batch=256):
    model = ab.Model("regression", [f"p{i}" for i in range(xtr.shape[1])], [], xtr, train["y"],
                     hidden=hidden, learning_rate=lr, batch_size=batch, seed=42)
    model.fit(xtr, train["y"], epochs)
    err = model.predict(xva) - valid["y"]
    return float(np.abs(err).mean()), float(np.sqrt(np.mean(err ** 2)))


def main():
    base, train, valid = ab.load()
    rows = []

    def record(result):
        rows.append(result)
        print(f"{result['tag']:<26} MAE {result['final_mae']:.4f}  RMSE {result['final_rmse']:.4f}  "
              f"accepted {result['accepted']}/10", flush=True)

    for decay in (0.6, 0.7, 0.8, 0.9):
        for lr in (3e-3, 5e-3):
            record(simulate(base, train, valid, rounds=10, lr=lr, batch=256, epochs=5,
                            kernel=make_ema(decay), tag=f"ema{int(decay*100)}_lr{lr:g}_bs256"))
    for bs in (64, 128):
        record(simulate(base, train, valid, rounds=10, lr=1e-3, batch=bs, epochs=5,
                        kernel=make_ema(0.9), tag=f"ema90_lr0.001_bs{bs}"))
    record(simulate(base, train, valid, rounds=10, lr=1e-3, batch=256, epochs=5,
                    kernel=make_ema(0.9, weight_decay=1e-4), tag="ema90_wd1e-4_bs256"))
    record(simulate(base, train, valid, rounds=10, lr=1e-3, batch=256, epochs=5,
                    kernel=make_ema(0.9), widen_to=64, tag="ema90_widen64_bs256"))
    record(simulate(base, train, valid, rounds=10, lr=1e-3, batch=256, epochs=5,
                    kernel=plain, tag="plain_lr0.001_bs256_ep5"))

    xtr, xva = temporal_features(train, valid)
    scratch = from_scratch(train, valid, train["x"], valid["x"])
    temporal = from_scratch(train, valid, xtr, xva)
    rows.append({"tag": "scratch_24", "final_mae": scratch[0], "final_rmse": scratch[1], "accepted": 0})
    rows.append({"tag": "scratch_24+temporal", "final_mae": temporal[0], "final_rmse": temporal[1],
                 "accepted": 0, "features": int(xtr.shape[1])})
    print(f"scratch 24 features        MAE {scratch[0]:.4f}  RMSE {scratch[1]:.4f}", flush=True)
    print(f"scratch +temporal ({xtr.shape[1]:3d})     MAE {temporal[0]:.4f}  RMSE {temporal[1]:.4f}", flush=True)

    (OUT / "ab-results-2.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print("saved", OUT / "ab-results-2.json")


if __name__ == "__main__":
    main()
