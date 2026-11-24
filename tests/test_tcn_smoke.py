"""Smoke tests for leakage-free temporal windowing and TCN trainer contract."""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from rac_hpo.data.temporal_window import (
    apply_zscore_scaler,
    build_unit_windows,
    extract_window_tabular_features,
    fit_zscore_scaler,
    select_degradation_features,
)
from rac_hpo.domain.schemas import PreparedDataset, TrainingResult
from rac_hpo.optimization.rac_hpo.search import RACSearchPolicy
from rac_hpo.training import tcn_trainer


HAS_TORCH = importlib.util.find_spec("torch") is not None


def _make_synthetic_dataset() -> PreparedDataset:
    rng = np.random.default_rng(42)
    rows = []
    targets = []
    regimes = []
    groups = []
    splits = {"train": [], "validation": []}
    idx = 0
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
        s3 = np.ones(length) * 5.0  # constant sensor
        rul = np.arange(length - 1, -1, -1, dtype=float) * 5.0
        for i in range(length):
            rows.append([s1[i], s2[i], s3[i]])
            targets.append(rul[i])
            regimes.append(regime)
            groups.append(unit)
            splits[split_name].append(idx)
            idx += 1

    features = ["s1", "s2", "s3"]
    return PreparedDataset(
        dataset_id="synthetic_rul",
        source_path="memory",
        source_sha256="0" * 64,
        features=features,
        target="rul",
        target_unit="cycles",
        X=pd.DataFrame(rows, columns=features),
        y=pd.Series(targets, name="rul"),
        regimes=pd.Series(regimes, name="regime"),
        groups=pd.Series(groups, name="unit"),
        splits=splits,
        manifest={"independent_unit_kind": "independent_run"},
    )


def test_unit_windows_no_cross_unit_leakage():
    x = np.array(
        [[1.0, 2.0], [1.0, 2.0], [1.0, 2.0], [100.0, 200.0], [101.0, 202.0]],
        dtype=float,
    )
    y = np.array([150.0, 120.0, 90.0, 200.0, 100.0], dtype=float)
    groups = np.array(["u1", "u1", "u1", "u2", "u2"], dtype=object)

    windows, targets = build_unit_windows(x, y, groups, window_size=4, rul_cap=125.0)
    assert windows.shape == (5, 2, 4)
    # First row of u2 must be left-padded with u2's own values, never u1's values.
    assert np.allclose(windows[3, 0, :], 100.0)
    assert np.allclose(windows[3, 1, :], 200.0)
    assert np.allclose(targets, [125.0, 120.0, 90.0, 125.0, 100.0])

    tab = extract_window_tabular_features(windows, ["s1", "s2"])
    assert tab.shape == (5, 10)


def test_zscore_scaler_and_feature_selection_train_only():
    dataset = _make_synthetic_dataset()
    X_train, y_train, _, train_groups = dataset.split("train")
    X_valid, _, _, _ = dataset.split("validation")

    scaler = fit_zscore_scaler(X_train)
    scaled_train = apply_zscore_scaler(X_train, scaler)
    scaled_valid = apply_zscore_scaler(X_valid, scaler)
    assert np.isfinite(scaled_train).all()
    assert np.isfinite(scaled_valid).all()

    selected = select_degradation_features(X_train, y_train, train_groups, top_k=2)
    assert set(selected) == {"s1", "s2"}


def test_tcn_search_space_compatible_with_rac_policy():
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
    assert params is None
    assert trace["method"] == "tpe_fallback"
    tcn_trainer.validate_params(tcn_trainer.DEFAULT_TCN_PARAMS)


@pytest.mark.skipif(not HAS_TORCH, reason="PyTorch optional dependency not installed in .venv")
def test_tcn_trainer_returns_valid_training_result():
    dataset = _make_synthetic_dataset()
    result = tcn_trainer.train(
        dataset,
        params={"window_size": 8, "tcn_channels": 16, "learning_rate": 1e-2, "dropout": 0.1},
        seed=42,
        model_config={"max_epochs": 3, "early_stopping_patience": 2, "batch_size": 16, "device": "cpu"},
    )
    assert isinstance(result, TrainingResult)
    assert result.best_iteration >= 1
    assert np.isfinite(result.metrics["overall_mae"]) and result.metrics["overall_mae"] >= 0
    assert np.isfinite(result.metrics["overall_rmse"]) and result.metrics["overall_rmse"] >= 0
