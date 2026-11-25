"""Contract tests for leakage-free temporal windowing and the TCN trainer."""

from __future__ import annotations

import importlib.util
import unittest

import numpy as np
import pandas as pd

from rac_hpo.data.temporal_window import (
    apply_zscore_scaler,
    build_unit_windows,
    extract_window_tabular_features,
    fit_zscore_scaler,
    select_degradation_features,
    unit_sequence_order,
)
from rac_hpo.domain.schemas import PreparedDataset, TrainingResult
from rac_hpo.optimization.rac_hpo.search import RACSearchPolicy
from rac_hpo.training import tcn_trainer


HAS_TORCH = importlib.util.find_spec("torch") is not None


def _make_synthetic_dataset() -> PreparedDataset:
    rng = np.random.default_rng(42)
    records: list[list[float]] = []
    targets: list[float] = []
    regimes: list[str] = []
    groups: list[str] = []
    splits: dict[str, list[int]] = {"train": [], "validation": []}
    index = 0
    unit_specs = [
        ("train", "cond_A", "unit_1", 30),
        ("train", "cond_B", "unit_2", 30),
        ("train", "cond_A", "unit_3", 25),
        ("validation", "cond_A", "unit_4", 20),
        ("validation", "cond_B", "unit_5", 20),
    ]
    for split_name, regime, unit, length in unit_specs:
        t = np.linspace(0.0, 1.0, length)
        s1 = t * 2.0 + rng.normal(0, 0.05, size=length)
        s2 = (t ** 2) * 3.0 + rng.normal(0, 0.05, size=length)
        s3 = np.ones(length) * 5.0
        rul = np.arange(length - 1, -1, -1, dtype=float) * 5.0
        for i in range(length):
            records.append([s1[i], s2[i], s3[i]])
            targets.append(rul[i])
            regimes.append(regime)
            groups.append(unit)
            splits[split_name].append(index)
            index += 1

    features = ["s1", "s2", "s3"]
    return PreparedDataset(
        dataset_id="synthetic_rul",
        source_path="memory",
        source_sha256="0" * 64,
        features=features,
        target="rul",
        target_unit="cycles",
        X=pd.DataFrame(records, columns=features),
        y=pd.Series(targets, name="rul"),
        regimes=pd.Series(regimes, name="regime"),
        groups=pd.Series(groups, name="unit"),
        splits=splits,
        manifest={"independent_unit_kind": "independent_run"},
    )


class TemporalWindowTest(unittest.TestCase):
    def test_unit_windows_never_cross_units(self):
        x = np.array(
            [[1.0, 2.0], [1.0, 2.0], [1.0, 2.0], [100.0, 200.0], [101.0, 202.0]],
            dtype=float,
        )
        y = np.array([150.0, 120.0, 90.0, 200.0, 100.0], dtype=float)
        groups = np.array(["u1", "u1", "u1", "u2", "u2"], dtype=object)

        windows, targets = build_unit_windows(x, y, groups, window_size=4, rul_cap=125.0)
        self.assertEqual(windows.shape, (5, 2, 4))
        # The first row of u2 is padded with u2's own values, never u1's.
        self.assertTrue(np.allclose(windows[3, 0, :], 100.0))
        self.assertTrue(np.allclose(windows[3, 1, :], 200.0))
        self.assertTrue(np.allclose(targets, [125.0, 120.0, 90.0, 125.0, 100.0]))

        tab = extract_window_tabular_features(windows, ["s1", "s2"])
        self.assertEqual(tab.shape, (5, 10))

    def test_shuffled_frame_is_reordered_by_timestamp(self):
        # One unit of 5 steps, stored out of chronological order.
        x = np.array([[5.0], [1.0], [4.0], [2.0], [3.0]], dtype=float)
        y = np.zeros(5, dtype=float)
        groups = np.array(["u"] * 5, dtype=object)
        times = np.array([5.0, 1.0, 4.0, 2.0, 3.0], dtype=float)

        windows, _ = build_unit_windows(x, y, groups, window_size=2, time_values=times)
        # Row 1 (time=1) is chronologically first: two copies of its own value.
        self.assertTrue(np.allclose(windows[1, 0, :], [1.0, 1.0]))
        # Row 3 (time=2) must look back to time=1 then itself.
        self.assertTrue(np.allclose(windows[3, 0, :], [1.0, 2.0]))
        # Row 0 (time=5) must look back to time=4 then itself, not to storage order.
        self.assertTrue(np.allclose(windows[0, 0, :], [4.0, 5.0]))

    def test_duplicate_timestamps_are_rejected(self):
        groups = np.array(["u", "u", "u"], dtype=object)
        with self.assertRaises(ValueError):
            unit_sequence_order(groups, np.array([1.0, 2.0, 2.0]))

    def test_sequence_order_is_chronological(self):
        groups = np.array(["a", "b", "a", "b"], dtype=object)
        order = unit_sequence_order(groups, np.array([9.0, 2.0, 3.0, 1.0]))
        self.assertEqual(order["a"].tolist(), [2, 0])
        self.assertEqual(order["b"].tolist(), [3, 1])

    def test_scaler_and_feature_selection_use_train_only(self):
        dataset = _make_synthetic_dataset()
        X_train, y_train, _, train_groups = dataset.split("train")
        X_valid, _, _, _ = dataset.split("validation")

        scaler = fit_zscore_scaler(X_train)
        scaled_train = apply_zscore_scaler(X_train, scaler)
        scaled_valid = apply_zscore_scaler(X_valid, scaler)
        self.assertTrue(np.isfinite(scaled_train).all())
        self.assertTrue(np.isfinite(scaled_valid).all())

        selected = select_degradation_features(X_train, y_train, train_groups, top_k=2)
        self.assertEqual(set(selected), {"s1", "s2"})

        with self.assertRaises(ValueError):
            select_degradation_features(X_train, y_train, train_groups.iloc[:-1])

    def test_feature_ranking_follows_target_not_time(self):
        # The target oscillates (three full periods) so it carries no time trend,
        # while `tracker` encodes it exactly: correlation-with-target must win over
        # the pure monotonic trend of `clock`.
        steps = 120
        times = np.arange(steps, dtype=float)
        target = np.sin(np.linspace(0.0, 6 * np.pi, steps))
        self.assertLess(abs(np.corrcoef(times, target)[0, 1]), 0.4)
        frame = pd.DataFrame({"tracker": target, "clock": times, "flat": np.ones(steps)})
        selected = select_degradation_features(
            frame, pd.Series(target), np.array(["u"] * steps, dtype=object), top_k=1,
        )
        self.assertEqual(selected, ["tracker"])


class TCNContractTest(unittest.TestCase):
    def test_search_space_is_compatible_with_rac_policy(self):
        policy = RACSearchPolicy(
            {
                "seed": 42,
                "alpha": 0.3,
                "baseline_errors": {"cond_A": 10.0, "cond_B": 12.0},
                "weights": {"cond_A": 20, "cond_B": 20},
                "rac_hpo": {
                    "warmup_trials": 8,
                    "minimum_history": 8,
                    "min_forward_train": 5,
                    "forward_holdout": 3,
                },
            },
            tcn_trainer.TCN_SEARCH_SPACE,
        )
        params, trace = policy.propose([])
        self.assertIsNone(params)
        self.assertEqual(trace["method"], "tpe_fallback")
        tcn_trainer.validate_params(tcn_trainer.DEFAULT_TCN_PARAMS)

    def test_receptive_field_covers_every_searchable_window(self):
        low = tcn_trainer.TCN_SEARCH_SPACE["window_size"]["low"]
        high = tcn_trainer.TCN_SEARCH_SPACE["window_size"]["high"]
        for window in (low, 29, high):
            blocks = tcn_trainer.blocks_for_window(window)
            self.assertGreaterEqual(tcn_trainer.receptive_field(blocks), window)
            self.assertLessEqual(blocks, 6)
        # The old fixed 3-block stack only saw 29 steps, so wider windows were inert.
        self.assertEqual(tcn_trainer.receptive_field(3), 29)
        self.assertGreater(tcn_trainer.blocks_for_window(high), 3)

    def test_invalid_params_are_rejected(self):
        with self.assertRaises(ValueError):
            tcn_trainer.validate_params({"window_size": 0})
        with self.assertRaises(ValueError):
            tcn_trainer.validate_params({"learning_rate": -1.0})
        with self.assertRaises(ValueError):
            tcn_trainer.validate_params({"unknown_key": 1})

    @unittest.skipUnless(HAS_TORCH, "PyTorch optional dependency not installed")
    def test_trainer_returns_valid_training_result(self):
        dataset = _make_synthetic_dataset()
        result = tcn_trainer.train(
            dataset,
            params={"window_size": 8, "tcn_channels": 16, "learning_rate": 1e-2, "dropout": 0.1},
            seed=42,
            model_config={"max_epochs": 3, "early_stopping_patience": 2,
                          "batch_size": 16, "device": "cpu"},
        )
        self.assertIsInstance(result, TrainingResult)
        self.assertGreaterEqual(result.best_iteration, 1)
        self.assertTrue(np.isfinite(result.metrics["overall_mae"]))
        self.assertGreaterEqual(result.metrics["overall_mae"], 0.0)
        self.assertGreaterEqual(result.metrics["overall_rmse"], 0.0)
        self.assertGreaterEqual(result.diagnostics["receptive_field"], 8)

    @unittest.skipUnless(HAS_TORCH, "PyTorch optional dependency not installed")
    def test_checkpoint_round_trip(self):
        import tempfile
        from pathlib import Path

        dataset = _make_synthetic_dataset()
        result = tcn_trainer.train(
            dataset,
            params={"window_size": 8, "tcn_channels": 8, "learning_rate": 1e-2},
            seed=7,
            model_config={"max_epochs": 1, "batch_size": 16, "device": "cpu"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tcn.pt"
            tcn_trainer.save_checkpoint(path, result)
            payload = tcn_trainer.load_checkpoint(path)
            module = tcn_trainer.build_from_checkpoint(payload, in_channels=3)
            original = result.model["module"].state_dict()
            reloaded = module.state_dict()
            self.assertEqual(sorted(original), sorted(reloaded))
            for key in original:
                self.assertTrue(np.allclose(
                    original[key].detach().cpu().numpy(),
                    reloaded[key].detach().cpu().numpy(),
                ))


if __name__ == "__main__":
    unittest.main()
