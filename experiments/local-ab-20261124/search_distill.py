"""Systematic (and cached) search for the best A-direction distillation config.

Two stages, because OOF teacher labels are expensive and student training is cheap:

Stage 1 -- build/cache OOF soft labels for several window sizes and fold seeds.
Stage 2 -- grid-search student hyper-parameters on the cached labels.

Everything uses the real C package and the platform's own accept gate
(validation RMSE must improve). A split-by-unit check is reported per config.
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
CACHE = OUT / "oof_cache"
CACHE.mkdir(exist_ok=True)


def cache_key(window, fold_seed, epochs, lr, batch):
    return f"w{window}_s{fold_seed}_e{epochs}_lr{lr:g}_b{batch}"


def get_oof(x, y, units, *, window, fold_seed, epochs=15, lr=0.002, batch=256):
    key = cache_key(window, fold_seed, epochs, lr, batch)
    path = CACHE / f"{key}.npy"
    if path.exists():
        return np.load(path)
    print(f"  computing OOF {key} ...", flush=True)
    pred = oof.oof_predictions(x, y, units, folds=5, epochs=epochs, lr=lr,
                                batch=batch, seed=fold_seed)
    np.save(path, pred)
    return pred


def main():
    base, train, valid = ab.load()
    train_units = np.array([r["unit"] for r in ab.meta("train")])
    valid_units = np.array([r["unit"] for r in ab.meta("validation")])
    cut = np.median(valid_units)
    masks = [valid_units <= cut, valid_units > cut]
    parent_halves = [rd.subset_score(base, valid, m)[0] for m in masks]
    print(f"parent halves MAE {[round(h, 4) for h in parent_halves]}", flush=True)

    # Stage 1: OOF soft labels across window sizes (fold seed fixed for stage 2).
    labels = {}
    for window in (8, 15, 30):
        xtr, _ = ab2.temporal_features(train, valid, window=window)
        raw = get_oof(xtr, train["y"], train_units, window=window, fold_seed=42)
        cal = rd.calibrate(raw, train["y"])
        labels[window] = {"raw": raw, "cal": cal}

    # Stage 2: grid search on cached labels.
    rows = []
    grid = list(product(
        labels.keys(),                       # window
        ("raw", "cal"),                      # soft label kind
        (0.1, 0.2, 0.3, 0.4),                # beta
        (0.4, 0.6, 0.8),                     # EMA decay
        (3e-3, 4e-3),                        # lr
        (4, 5),                              # epochs
    ))
    print(f"grid size {len(grid)}", flush=True)
    for i, (window, kind, beta, decay, lr, epochs) in enumerate(grid, 1):
        soft = labels[window][kind]
        y_target = train["y"] + beta * (soft - train["y"])
        result = rd.simulate(base, train, valid, y_target, masks, rounds=10,
                             lr=lr, batch=256, epochs=epochs, decay=decay,
                             tag=f"w{window}_{kind}_b{beta}_d{decay}_lr{lr:g}_e{epochs}")
        result.update(window=window, kind=kind, beta=beta, decay=decay, lr=lr, epochs=epochs)
        both = all(h < p for h, p in zip(result["half_mae"], parent_halves))
        result["both_halves_better"] = both
        rows.append(result)
        if i % 10 == 0 or result["rmse"] < 51.2:
            print(f"[{i}/{len(grid)}] {result['tag']:<38} "
                  f"MAE {result['mae']:.4f} RMSE {result['rmse']:.4f} "
                  f"acc {result['accepted']}/10 {'BOTH' if both else 'SPLIT'}", flush=True)

    (OUT / "search-grid-results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # Rank by RMSE, require both halves better and at least 6/10 accepted.
    eligible = [r for r in rows if r["both_halves_better"] and r["accepted"] >= 6]
    eligible.sort(key=lambda r: r["rmse"])
    print("=== top 10 eligible by RMSE ===", flush=True)
    for r in eligible[:10]:
        print(json.dumps(r, ensure_ascii=False), flush=True)
    baseline = min(rows, key=lambda r: abs(r["beta"]) + abs(r["decay"] - 0.6))
    print("saved", OUT / "search-grid-results.json", flush=True)


if __name__ == "__main__":
    main()
