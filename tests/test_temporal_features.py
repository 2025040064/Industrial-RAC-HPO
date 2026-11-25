"""Tests for the temporal feature augmentation seam (no torch required)."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from rac_hpo.data.temporal_features import (
    augment_with_temporal_features,
    temporal_feature_names,
)
from rac_hpo.domain.schemas import PreparedDataset


def _dataset(train_values: list[float], valid_values: list[float]) -> PreparedDataset:
    rows = [[value, value * 2.0] for value in train_values]
    rows += [[value, value * 2.0] for value in valid_values]
    n_train = len(train_values)
    features = ["s1", "s2"]
    return PreparedDataset(
        dataset_id="synthetic",
        source_path="memory",
        source_sha256="0" * 64,
        features=features,
        target="rul",
        target_unit="cycles",
        X=pd.DataFrame(rows, columns=features),
        y=pd.Series([float(10 - i) for i in range(len(rows))], name="rul"),
        regimes=pd.Series(["r"] * len(rows), name="regime"),
        groups=pd.Series(["tr"] * n_train + ["va"] * len(valid_values), name="unit"),
        splits={"train": list(range(n_train)),
                "validation": list(range(n_train, len(rows)))},
        manifest={"independent_unit_kind": "independent_run"},
    )


class TemporalFeatureAugmentationTest(unittest.TestCase):
    def test_features_expand_and_stay_ordered(self):
        dataset = _dataset([100.0, 110.0, 120.0, 130.0], [1.0, 2.0, 3.0, 4.0])
        augmented = augment_with_temporal_features(
            dataset, window_size=3, statistics=("win_mean", "win_slope"),
        )
        expected = temporal_feature_names(dataset.features, ("win_mean", "win_slope"))
        self.assertEqual(augmented.features, dataset.features + expected)
        self.assertEqual(len(expected), 4)
        # The trainers reject a dataset whose columns drift from dataset.features.
        self.assertEqual(list(augmented.X.columns), augmented.features)
        self.assertEqual(augmented.manifest["temporal_window"]["window_size"], 3)
        self.assertEqual(augmented.manifest["temporal_window"]["covered_splits"],
                         ["train", "validation"])

    def test_validation_windows_never_see_train_rows(self):
        dataset = _dataset([100.0, 110.0, 120.0, 130.0], [1.0, 2.0, 3.0, 4.0])
        augmented = augment_with_temporal_features(
            dataset, window_size=3, statistics=("win_mean", "win_ptp"),
        )
        train_mean = augmented.X.loc[0, "s1__win_mean"]
        valid_first = augmented.X.loc[4, "s1__win_mean"]
        valid_last = augmented.X.loc[7, "s1__win_mean"]
        # First validation row is left-padded with its own value, not with 130.
        self.assertAlmostEqual(valid_first, 1.0, places=6)
        self.assertAlmostEqual(valid_last, 3.0, places=6)
        self.assertGreater(train_mean, 90.0)
        self.assertTrue(np.isfinite(augmented.X["s1__win_mean"].to_numpy()).all())

    def test_rows_outside_any_split_stay_nan(self):
        dataset = _dataset([100.0, 110.0, 120.0], [1.0, 2.0, 3.0])
        dataset.splits = {"train": [0, 1, 2], "validation": [3, 4]}
        augmented = augment_with_temporal_features(dataset, window_size=2)
        # Row 5 belongs to no split, so it must not receive statistics.
        self.assertTrue(np.isnan(augmented.X.loc[5, "s1__win_mean"]))
        # First validation row is padded with its own value.
        self.assertAlmostEqual(augmented.X.loc[3, "s1__win_mean"], 1.0, places=6)

    def test_drop_original_replaces_point_features(self):
        dataset = _dataset([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        augmented = augment_with_temporal_features(
            dataset, window_size=2, statistics=("win_mean",), drop_original=True,
        )
        self.assertEqual(augmented.features, ["s1__win_mean", "s2__win_mean"])
        self.assertEqual(list(augmented.X.columns), augmented.features)

    def test_time_column_orders_without_becoming_a_feature(self):
        dataset = _dataset([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        dataset.X = dataset.X.copy()
        dataset.X["cycle"] = np.arange(len(dataset.X), dtype=float)
        # Shuffle storage order but keep the timestamp column authoritative.
        dataset.X = dataset.X.iloc[[2, 0, 1, 5, 3, 4]].reset_index(drop=True)
        dataset.y = dataset.y.iloc[[2, 0, 1, 5, 3, 4]].reset_index(drop=True)
        dataset.groups = dataset.groups.iloc[[2, 0, 1, 5, 3, 4]].reset_index(drop=True)
        dataset.splits = {"train": [0, 1, 2], "validation": [3, 4, 5]}

        augmented = augment_with_temporal_features(
            dataset, window_size=2, statistics=("win_mean",), time_column="cycle",
        )
        self.assertNotIn("cycle", augmented.features)
        self.assertEqual(augmented.manifest["temporal_window"]["time_column"], "cycle")
        # cycle==0 has no history: its window is two copies of its own value.
        row_zero = augmented.X.index[augmented.X["cycle"] == 0][0]
        self.assertAlmostEqual(augmented.X.loc[row_zero, "s1__win_mean"], 1.0, places=6)

    def test_invalid_inputs_are_rejected(self):
        dataset = _dataset([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        with self.assertRaises(ValueError):
            augment_with_temporal_features(dataset, statistics=("win_median",))
        with self.assertRaises(ValueError):
            augment_with_temporal_features(dataset, time_column="missing")
        with self.assertRaises(ValueError):
            augment_with_temporal_features(dataset, window_size=0)

        broken = _dataset([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        broken.X.loc[0, "s1"] = np.nan
        with self.assertRaises(ValueError):
            augment_with_temporal_features(broken)


if __name__ == "__main__":
    unittest.main()
