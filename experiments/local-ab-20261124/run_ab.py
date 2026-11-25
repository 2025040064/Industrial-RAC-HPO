"""Local A/B on the real platform C package (FD001 public split).

Everything here mirrors the submission runtime:
  * same `baselines.Model` (24 -> 32 -> 1 tanh MLP, 833 params)
  * same checkpoint as the platform parent
  * same continuation semantics: 10 rounds, accept only if validation RMSE improves

The only additions are training-side knobs that stay inside the frozen contract
(feature paths, target statistics and architecture of the parent all preserved).
"""
import copy
import json
import sys
from pathlib import Path

import numpy as np

PKG = Path("workspace/contest_sampler/live-harness-20261117/C/package").resolve()
sys.path.insert(0, str(PKG))
from baselines.data import read_dataset  # noqa: E402
from baselines.model import Model  # noqa: E402

CKPT = PKG / "checkpoint.npz"
OUT = Path("experiments/local-ab-20261124")
OUT.mkdir(parents=True, exist_ok=True)


def load():
    base = Model.load(CKPT)
    train = read_dataset(PKG / "public/train.jsonl", "regression", base.meta["classes"], base.meta["paths"])
    valid = read_dataset(PKG / "public/validation.jsonl", "regression", base.meta["classes"], base.meta["paths"])
    return base, train, valid


def meta(split):
    rows = []
    for line in (PKG / "public" / f"{split}.jsonl").read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line)["meta"])
    return rows


def score(model, valid):
    pred = model.predict(valid["x"])
    err = pred - valid["y"]
    return float(np.abs(err).mean()), float(np.sqrt(np.mean(err ** 2)))


# ---------------------------------------------------------------- train kernels
def fit_plain(model, x, y, epochs):
    return model.fit(x, y, epochs)


def fit_ema(model, x, y, epochs, decay=0.9):
    """Model.fit with a Polyak average folded back into the weights at the end."""
    shadow = {k: v.copy() for k, v in model.params.items()}
    for _ in range(epochs):
        model.fit(x, y, 1)
        for k, v in model.params.items():
            shadow[k] = decay * shadow[k] + (1 - decay) * v
    model.params = {k: v.copy() for k, v in shadow.items()}
    model.validate()
    return []


def fit_noise(model, x, y, epochs, sigma=0.05, seed=7):
    """Gaussian input noise on the standardised features (denoising augmentation)."""
    rng = np.random.default_rng(seed)
    original = model.normalized
    for _ in range(epochs):
        def noisy(values, _orig=original):
            z = _orig(values)
            return z + rng.normal(0.0, sigma, z.shape)
        model.normalized = noisy
        model.fit(x, y, 1)
    model.normalized = original
    model.validate()
    return []


def widen(model, hidden=64, seed=11):
    """Function-preserving net2wider: duplicated units, halved output weights."""
    old = model.params
    source = old["w1"].shape[1]
    rng = np.random.default_rng(seed)
    pick = np.concatenate([np.arange(source), rng.integers(0, source, hidden - source)])
    model.params = {
        "w1": old["w1"][:, pick].copy(),
        "b1": old["b1"][pick].copy(),
        "w2": old["w2"][pick] / (hidden / source),
        "b2": old["b2"].copy(),
    }
    model.first = {k: np.zeros_like(v) for k, v in model.params.items()}
    model.second = {k: np.zeros_like(v) for k, v in model.params.items()}
    model.meta["hidden"] = hidden
    model.meta["parameter_count"] = int(sum(v.size for v in model.params.values()))
    model.validate()
    before = model.predict
    return before


# ---------------------------------------------------------------- round driver
def simulate(base, train, valid, *, rounds, lr, batch, epochs, kernel="plain", widen_to=0, tag=""):
    model = copy.deepcopy(base)
    if widen_to:
        widen(model, hidden=widen_to)
        model.meta["epochs"] = 0
    model.meta["learning_rate"] = lr
    model.meta["batch_size"] = batch
    best = copy.deepcopy(model)
    best_score = score(best, valid)
    trace = [{"round": 0, "mae": best_score[0], "rmse": best_score[1], "accepted": True}]
    for rnd in range(1, rounds + 1):
        model.meta["learning_rate"] = lr
        model.meta["batch_size"] = batch
        if kernel == "plain":
            fit_plain(model, train["x"], train["y"], epochs)
        elif kernel == "ema":
            fit_ema(model, train["x"], train["y"], epochs)
        elif kernel == "noise":
            fit_noise(model, train["x"], train["y"], epochs)
        else:
            raise ValueError(kernel)
        mae, rmse = score(model, valid)
        accepted = rmse < best_score[1]
        if accepted:
            best, best_score = copy.deepcopy(model), (mae, rmse)
        else:
            model = copy.deepcopy(best)
        trace.append({"round": rnd, "mae": mae, "rmse": rmse, "accepted": accepted})
    return {"tag": tag, "final_mae": best_score[0], "final_rmse": best_score[1], "trace": trace,
            "params": int(sum(v.size for v in best.params.values()))}


def temporal_features(train, valid, window=15):
    """Offline-only upper bound: causal per-unit window statistics.

    Not deployable: the predict contract delivers `{task, inputs}` with a single
    time step and no unit/cycle, so these columns cannot be reproduced at inference.
    """
    import pandas as pd

    def build(x, rows):
        frame = pd.DataFrame(x, columns=[f"f{i}" for i in range(x.shape[1])])
        frame["unit"] = [r["unit"] for r in rows]
        frame["cycle"] = [r["cycle"] for r in rows]
        frame = frame.sort_values(["unit", "cycle"]).reset_index()
        keep = [c for c in frame.columns if c.startswith("f")]
        # only the sensor block carries the degradation signal
        keep = [c for c in keep if 3 <= int(c[1:])]
        pieces = []
        for _, group in frame.groupby("unit", sort=True):
            roll = group[keep].rolling(window, min_periods=1)
            block = pd.DataFrame({
                **{f"{c}__wmean": roll.mean()[c] for c in keep},
                **{f"{c}__wstd": roll.std(ddof=0)[c] for c in keep},
                **{f"{c}__wslope": (roll.apply(lambda s: np.polyfit(np.arange(len(s)), s, 1)[0], raw=True))[c]
                   for c in keep},
            })
            pieces.append(block)
        out = pd.concat(pieces).sort_index()
        out = out.loc[frame["index"].to_numpy()]
        return np.nan_to_num(out.to_numpy(dtype=np.float64), nan=0.0)

    return np.hstack([train["x"], build(train["x"], meta("train"))]), \
        np.hstack([valid["x"], build(valid["x"], meta("validation"))])


def from_scratch(train, valid, xtr, xva, *, epochs=15, hidden=32, lr=0.002, batch=256, seed=42):
    model = Model("regression", [f"p{i}" for i in range(xtr.shape[1])], [], xtr, train["y"],
                  hidden=hidden, learning_rate=lr, batch_size=batch, seed=seed)
    model.fit(xtr, train["y"], epochs)
    pred = model.predict(xva)
    err = pred - valid["y"]
    return float(np.abs(err).mean()), float(np.sqrt(np.mean(err ** 2)))


def main():
    base, train, valid = load()
    results = []
    mae0, rmse0 = score(base, valid)
    results.append({"tag": "package-checkpoint", "final_mae": mae0, "final_rmse": rmse0, "trace": [], "params": 833})
    print(f"package checkpoint  MAE {mae0:.4f}  RMSE {rmse0:.4f}", flush=True)

    grid = [
        dict(tag="race_v5like", rounds=10, lr=3e-3, batch=128, epochs=2, kernel="plain"),
        dict(tag="long_lr1e-3_ep5", rounds=10, lr=1e-3, batch=256, epochs=5, kernel="plain"),
        dict(tag="long_lr3e-3_ep5", rounds=10, lr=3e-3, batch=256, epochs=5, kernel="plain"),
        dict(tag="ema_lr1e-3_ep5", rounds=10, lr=1e-3, batch=256, epochs=5, kernel="ema"),
        dict(tag="ema_lr3e-3_ep5", rounds=10, lr=3e-3, batch=256, epochs=5, kernel="ema"),
        dict(tag="noise_lr1e-3_ep5", rounds=10, lr=1e-3, batch=256, epochs=5, kernel="noise"),
    ]
    for cfg in grid:
        result = simulate(base, train, valid, **cfg)
        results.append(result)
        print(f"{result['tag']:<20} MAE {result['final_mae']:.4f}  RMSE {result['final_rmse']:.4f}  "
              f"accepted {sum(r['accepted'] for r in result['trace'][1:])}/10", flush=True)

    widen_result = simulate(base, train, valid, rounds=10, lr=1e-3, batch=256, epochs=5,
                            kernel="plain", widen_to=64, tag="widen64_lr1e-3_ep5")
    results.append(widen_result)
    print(f"{widen_result['tag']:<20} MAE {widen_result['final_mae']:.4f}  RMSE {widen_result['final_rmse']:.4f}",
          flush=True)

    # Offline-only: how much would temporal context buy if the contract allowed it?
    xtr, xva = temporal_features(train, valid)
    base_scratch = from_scratch(train, valid, train["x"], valid["x"])
    temporal_scratch = from_scratch(train, valid, xtr, xva)
    results.append({"tag": "scratch_24", "final_mae": base_scratch[0], "final_rmse": base_scratch[1],
                    "trace": [], "params": 833, "note": "offline 15 epochs from scratch, row-local only"})
    results.append({"tag": "scratch_24+temporal", "final_mae": temporal_scratch[0], "final_rmse": temporal_scratch[1],
                    "trace": [], "params": int(24 + (xtr.shape[1] - 24) * 32), "note": "offline upper bound"})
    print(f"scratch 24 features      MAE {base_scratch[0]:.4f}  RMSE {base_scratch[1]:.4f}", flush=True)
    print(f"scratch +temporal feats  MAE {temporal_scratch[0]:.4f}  RMSE {temporal_scratch[1]:.4f}  "
          f"({xtr.shape[1]} features)", flush=True)

    (OUT / "ab-results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("saved", OUT / "ab-results.json")


if __name__ == "__main__":
    main()
