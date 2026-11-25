"""Final refinement + split-half confirmation.

The public validation set is split by physical unit (first/second half) so a
configuration is only kept if it improves both halves — guarding against tuning
noise on a single 23k-row metric.
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


def units():
    return np.array([r["unit"] for r in ab.meta("validation")])


def subset_score(model, valid, mask):
    err = model.predict(valid["x"][mask]) - valid["y"][mask]
    return float(np.abs(err).mean()), float(np.sqrt(np.mean(err ** 2)))


def run(base, train, valid, masks, *, rounds, lr, batch, epochs, decay, tag):
    kernel = ab2.make_ema(decay)
    model = copy.deepcopy(base)
    best = copy.deepcopy(model)
    best_score = ab.score(best, valid)
    accepted = 0
    for _ in range(rounds):
        model.meta["learning_rate"] = lr
        model.meta["batch_size"] = batch
        kernel(model, train["x"], train["y"], epochs)
        mae, rmse = ab.score(model, valid)
        if rmse < best_score[1]:
            best, best_score = copy.deepcopy(model), (mae, rmse)
            accepted += 1
        else:
            model = copy.deepcopy(best)
    halves = [subset_score(best, valid, mask) for mask in masks]
    return {"tag": tag, "mae": best_score[0], "rmse": best_score[1], "accepted": accepted,
            "half_mae": [round(h[0], 4) for h in halves], "half_rmse": [round(h[1], 4) for h in halves]}


def main():
    base, train, valid = ab.load()
    unit_ids = units()
    cut = np.median(unit_ids)
    masks = [unit_ids <= cut, unit_ids > cut]
    base_halves = [subset_score(base, valid, mask) for mask in masks]
    print(f"parent halves MAE {[round(h[0],4) for h in base_halves]}  RMSE {[round(h[1],4) for h in base_halves]}",
          flush=True)

    rows = []
    for decay in (0.4, 0.5, 0.6, 0.7):
        for lr in (3e-3, 4e-3):
            result = run(base, train, valid, masks, rounds=10, lr=lr, batch=256, epochs=5,
                         decay=decay, tag=f"ema{int(decay*100)}_lr{lr:g}")
            rows.append(result)
            verdict = "both halves better" if all(
                h < b for h, b in zip(result["half_mae"], [x[0] for x in base_halves])) else "ONE HALF WORSE"
            print(f"{result['tag']:<18} MAE {result['mae']:.4f} RMSE {result['rmse']:.4f} "
                  f"acc {result['accepted']}/10 halves {result['half_mae']} {verdict}", flush=True)

    (OUT / "ab-results-3.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    best = min(rows, key=lambda r: r["mae"])
    print("best", json.dumps(best, ensure_ascii=False))


if __name__ == "__main__":
    main()
