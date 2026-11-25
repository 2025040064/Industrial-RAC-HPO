"""Zero-dependency temporal feature augmentation for tabular and sequence regressors.

This is the integration seam between the temporal direction and the existing
training stack: both ``lightgbm_trainer`` and ``tcn_trainer`` only require
``X.columns == dataset.features``, so widening the dataset here is enough to make
window statistics available without touching either trainer, the RAC policy, or
the search space.

Windows are built independently inside each split. A validation row can therefore
never see train rows, even when the same physical unit appears in both splits.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from rac_hpo.data.temporal_window import (
    build_unit_windows,
    extract_window_tabular_features,
)
from rac_hpo.domain.schemas import PreparedDataset


SUPPORTED_STATISTICS = ("win_mean", "win_std", "win_slope", "win_rms", "win_ptp")
DEFAULT_STATISTICS = SUPPORTED_STATISTICS


def temporal_feature_names(
    features: list[str],
    statistics: tuple[str, ...] | list[str] = DEFAULT_STATISTICS,
) -> list[str]:
    """Column names produced for ``features`` under ``statistics``."""
    return [f"{name}__{stat}" for name in features for stat in statistics]


def _validate_statistics(statistics: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    chosen = tuple(statistics)
    if not chosen:
        raise ValueError("at least one window statistic is required")
    unknown = [stat for stat in chosen if stat not in SUPPORTED_STATISTICS]
    if unknown:
        raise ValueError(f"unsupported window statistics: {unknown}; allowed {SUPPORTED_STATISTICS}")
    if len(set(chosen)) != len(chosen):
        raise ValueError("window statistics must be unique")
    return chosen


def augment_with_temporal_features(
    dataset: PreparedDataset,
    window_size: int = 16,
    statistics: tuple[str, ...] | list[str] = DEFAULT_STATISTICS,
    time_column: str | None = None,
    drop_original: bool = False,
) -> PreparedDataset:
    """Return a copy of ``dataset`` widened with causal window statistics.

    Parameters
    ----------
    window_size:
        Number of consecutive rows per window, built causally inside each unit.
    statistics:
        Any subset of ``SUPPORTED_STATISTICS``.
    time_column:
        Optional column used only to order rows chronologically inside a unit.
        It is never added to the feature list, so a raw cycle index cannot become
        a leaked predictor.
    drop_original:
        Replace the point features with window statistics instead of appending.
    """
    if not dataset.features:
        raise ValueError("dataset must expose at least one feature")
    chosen = _validate_statistics(statistics)
    if time_column is not None and time_column not in dataset.X.columns:
        raise ValueError(f"time_column {time_column!r} is not present in dataset.X")

    source_features = list(dataset.features)
    new_names = temporal_feature_names(source_features, chosen)
    values = dataset.X[source_features].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("dataset.X must contain only finite values in the selected features")

    n_rows = len(dataset.X)
    block = np.full((n_rows, len(new_names)), np.nan, dtype=float)
    covered: list[str] = []

    for split_name, indices in dataset.splits.items():
        if indices is None or len(indices) == 0:
            continue
        positions = np.asarray(indices, dtype=int)
        X_split = dataset.X.iloc[positions]
        y_split = dataset.y.iloc[positions]
        groups_split = dataset.groups.iloc[positions]
        times = X_split[time_column].to_numpy(dtype=float) if time_column is not None else None

        windows, _ = build_unit_windows(
            X_split[source_features].to_numpy(dtype=float),
            y_split.to_numpy(dtype=float),
            groups_split.to_numpy(dtype=object),
            window_size=window_size,
            rul_cap=None,
            time_values=times,
        )
        stats = extract_window_tabular_features(windows, source_features)
        block[positions] = stats[new_names].to_numpy(dtype=float)
        covered.append(split_name)

    if not covered:
        raise ValueError("dataset.splits is empty; nothing to augment")

    stats_frame = pd.DataFrame(block, columns=new_names, index=dataset.X.index)
    new_X = stats_frame if drop_original else pd.concat([dataset.X, stats_frame], axis=1)
    new_features = list(new_names) if drop_original else source_features + new_names

    uncovered = sorted(set(dataset.splits) - set(covered))
    manifest = {
        **dataset.manifest,
        "temporal_window": {
            "window_size": int(window_size),
            "statistics": list(chosen),
            "generated_features": new_names,
            "source_features": source_features,
            "time_column": time_column,
            "covered_splits": covered,
            "uncovered_splits": uncovered,
            "drop_original": bool(drop_original),
            "leakage_guard": "windows built per split and per unit; no cross-split window",
        },
    }
    return replace(dataset, X=new_X, features=new_features, manifest=manifest)
