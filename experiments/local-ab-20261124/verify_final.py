"""Final verification: best distill config over the platform's real 30 rounds.

The platform trial runs 30 rounds (not the 10 used in search). Verify that the
best config (beta=0.3 raw OOF, decay=0.4, lr=4e-3, epochs=5) keeps its advantage
over 30 rounds, and compare against the pure-training-side baseline (no distill)
over the same horizon. Multiple seeds test robustness of the fold split.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "experiments/local-ab-20261124")
import run_ab as ab  # noqa: E402
import run_ab2 as ab2  # noqa: E402
import run_distill as rd  # noqa: E402
import run_distill_oof as oof  # noqa: E402

OUT = Path("experiments/local-ab-20261124")
CACHE = OUT / "oof_cache"


def main():
    base, train, valid = ab.load()
    uv = np.array([r["unit"] for r in ab.meta("validation")])
    cut = np.median(uv)
    masks = [uv <= cut, uv > cut]
    parent_halves = [rd.subset_score(base, valid, m)[0] for m in masks]

    xtr, _ = ab2.temporal_features(train, valid, window=30)
    train_units = np.array([r["unit"] for r in ab.meta("train")])

    rows = []
    for fold_seed in (42, 17):

        path = CACHE / f"w30_s{fold_seed}_e15_lr0.002_b256.npy"
        if path.exists():
            oof_pred = np.load(path)
        else:
            oof_pred = oof.oof_predictions(xtr, train["y"], train_units,
                                           folds=5, epochs=15, seed=fold_seed)
            np.save(path, oof_pred)
        y_soft = train["y"] + 0.3 * (oof_pred - train["y"])

        for tag, target in (("distill", y_soft), ("pure", train["y"])):
            for decay in (0.4, 0.6):
                result = rd.simulate(base, train, valid, target, masks,
                                     rounds=30, lr=4e-3, epochs=5, decay=decay,
                                     tag=f"{tag}_fs{fold_seed}_d{decay}")
                both = all(h < p for h, p in zip(result["half_mae"], parent_halves))
                result.update(fold_seed=fold_seed, tag_full=result["tag"],
                              both_halves_better=both)
                rows.append(result)
                print(f"{tag:<8} fs{fold_seed} d{decay}: MAE {result['mae']:.4f} "
                      f"RMSE {result['rmse']:.4f} acc {result['accepted']}/30 "
                      f"halves {result['half_mae']} {'BOTH' if both else 'SPLIT'}",
                      flush=True)

    (OUT / "verify-final-30rounds.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("=== summary ===", flush=True)
    for r in rows:
        print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
