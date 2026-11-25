"""A-direction final leg: stronger temporal teachers -> better OOF soft labels.

Earlier teachers were hidden=32, 15 epochs (OOF MAE ~38.3 vs offline bound 36.6).
Try wider / longer-trained teachers; if their OOF predictions are better, the
beta=0.3 soft labels may carry more temporal signal and lift the student further.

Teacher width is unconstrained (it never runs on the platform); only the student
stays 24->32->1. OOF by unit, no leakage.
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
CACHE = OUT / "oof_cache"


def oof_strong(x, y, units, *, folds=5, epochs, hidden, lr=0.002, batch=256, seed=42):
    unique = np.unique(units)
    rng = np.random.default_rng(seed)
    rng.shuffle(unique)
    parts = np.array_split(unique, folds)
    oof = np.empty(len(y), dtype=float)
    for held in parts:
        hs = set(map(int, held))
        mv = np.array([int(u) in hs for u in units])
        mt = ~mv
        model = ab.Model("regression", [f"p{i}" for i in range(x.shape[1])], [],
                         x[mt], y[mt], hidden=hidden, learning_rate=lr,
                         batch_size=batch, seed=seed + int(held[0]))
        model.fit(x[mt], y[mt], epochs)
        oof[mv] = model.predict(x[mv])
    return oof


def main():
    base, train, valid = ab.load()
    tu = np.array([r["unit"] for r in ab.meta("train")])
    uv = np.array([r["unit"] for r in ab.meta("validation")])
    cut = np.median(uv)
    masks = [uv <= cut, uv > cut]
    parent_halves = [rd.subset_score(base, valid, m)[0] for m in masks]

    xtr, _ = ab2.temporal_features(train, valid, window=30)
    rows = []
    configs = [(32, 15), (32, 30), (64, 25), (64, 40), (96, 30)]
    for hidden, epochs in configs:
        key = f"strong_w30_h{hidden}_e{epochs}.npy"
        path = CACHE / key
        if path.exists():
            oof_pred = np.load(path)
        else:
            oof_pred = oof_strong(xtr, train["y"], tu, epochs=epochs, hidden=hidden, seed=42)
            np.save(path, oof_pred)
        err = oof_pred - train["y"]
        print(f"teacher h{hidden} e{epochs}: OOF MAE {np.abs(err).mean():.4f} "
              f"RMSE {np.sqrt(np.mean(err ** 2)):.4f}", flush=True)
        for beta in (0.2, 0.3, 0.4):
            y_soft = train["y"] + beta * (oof_pred - train["y"])
            result = rd.simulate(base, train, valid, y_soft, masks, rounds=30,
                                 lr=4e-3, epochs=5, decay=0.4,
                                 tag=f"strong_h{hidden}_e{epochs}_b{beta}")
            both = all(h < p for h, p in zip(result["half_mae"], parent_halves))
            result.update(hidden=hidden, teacher_epochs=epochs, beta=beta,
                          teacher_oof_mae=float(np.abs(err).mean()),
                          both_halves_better=both)
            rows.append(result)
            print(f"  b{beta}: MAE {result['mae']:.4f} RMSE {result['rmse']:.4f} "
                  f"acc {result['accepted']}/30 {'BOTH' if both else 'SPLIT'}", flush=True)

    (OUT / "search-strong-teacher-results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    rows.sort(key=lambda r: r["rmse"])
    print("=== top 10 ===", flush=True)
    for r in rows[:10]:
        print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
