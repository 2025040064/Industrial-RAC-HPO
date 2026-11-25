"""Leakage-free temporal windowing, Z-score scaling, and degradation feature selection."""

from __future__ import annotations

import numpy as np
import pandas as pd


def fit_zscore_scaler(X_train: pd.DataFrame) -> dict[str, object]:
    """Fit per-feature Z-score parameters strictly on training rows."""
    if X_train.empty:
        raise ValueError("X_train must be nonempty")
    values = X_train.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("X_train must contain only finite values")
    mean = values.mean(axis=0)
    std = values.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    return {
        "columns": list(X_train.columns),
        "mean": mean,
        "std": std,
    }


def apply_zscore_scaler(X: pd.DataFrame, scaler: dict[str, object]) -> np.ndarray:
    """Apply a training-fitted Z-score scaler without mutating column order."""
    columns = list(scaler["columns"])
    if list(X.columns) != columns:
        raise ValueError("feature columns differ from fitted scaler schema")
    values = X.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("input features must contain only finite values")
    mean = np.asarray(scaler["mean"], dtype=float)
    std = np.asarray(scaler["std"], dtype=float)
    return (values - mean) / std


def select_degradation_features(
    X_train: pd.DataFrame,
    y_train: pd.Series | np.ndarray,
    groups_train: pd.Series | np.ndarray,
    top_k: int | None = None,
    min_score: float = 0.0,
) -> list[str]:
    """Rank features by ``0.7 * |corr(feature, target)| + 0.3 * monotonicity``.

    Both terms are computed strictly inside each independent unit so that no
    cross-unit distribution shift leaks into the ranking. When a unit's target is
    constant (degenerate RUL trace) the correlation term falls back to the
    feature/time trend of that unit instead of contributing a hard zero.
    """
    if X_train.empty:
        raise ValueError("X_train must be nonempty")
    values = X_train.to_numpy(dtype=float)
    target = np.asarray(y_train, dtype=float)
    group_arr = np.asarray(groups_train, dtype=object)
    if len(values) != len(group_arr) or len(values) != len(target):
        raise ValueError("X_train, y_train and groups_train must have equal length")
    if not np.isfinite(target).all():
        raise ValueError("y_train must contain only finite values")

    n_features = values.shape[1]
    corr_scores = np.zeros(n_features, dtype=float)
    mono_scores = np.zeros(n_features, dtype=float)
    valid_units = 0

    unique_units = list(dict.fromkeys(group_arr.tolist()))
    for unit in unique_units:
        idx = np.flatnonzero(group_arr == unit)
        if len(idx) < 3:
            continue
        valid_units += 1
        unit_x = values[idx]
        unit_y = target[idx]
        t = np.arange(len(idx), dtype=float)
        t_centered = t - t.mean()
        t_norm = float(np.linalg.norm(t_centered))

        diffs = np.diff(unit_x, axis=0)
        denom = float(len(idx) - 1)
        pos_frac = (diffs > 0).sum(axis=0) / denom
        neg_frac = (diffs < 0).sum(axis=0) / denom
        mono_scores += np.abs(pos_frac - neg_frac)

        x_centered = unit_x - unit_x.mean(axis=0, keepdims=True)
        x_norms = np.linalg.norm(x_centered, axis=0)
        safe = x_norms > 1e-12
        unit_corr = np.zeros(n_features, dtype=float)

        y_centered = unit_y - unit_y.mean()
        y_norm = float(np.linalg.norm(y_centered))
        if y_norm > 1e-12:
            if safe.any():
                unit_corr[safe] = np.abs(
                    (y_centered[:, None] * x_centered[:, safe]).sum(axis=0)
                    / (y_norm * x_norms[safe])
                )
        elif t_norm > 1e-12 and safe.any():
            unit_corr[safe] = np.abs(
                (t_centered[:, None] * x_centered[:, safe]).sum(axis=0)
                / (t_norm * x_norms[safe])
            )
        corr_scores += unit_corr

    if valid_units > 0:
        corr_scores /= valid_units
        mono_scores /= valid_units

    std_all = values.std(axis=0)
    combined = np.where(std_all < 1e-12, -1.0, 0.7 * corr_scores + 0.3 * mono_scores)
    ranked = sorted(
        [(float(combined[i]), str(col)) for i, col in enumerate(X_train.columns)],
        key=lambda item: (-item[0], item[1]),
    )
    selected = [col for score, col in ranked if score >= min_score]
    if top_k is not None:
        if top_k <= 0:
            raise ValueError("top_k must be a positive integer or None")
        selected = selected[:top_k]
    return selected if selected else [ranked[0][1]]


def unit_sequence_order(
    groups: pd.Series | np.ndarray,
    time_values: pd.Series | np.ndarray,
) -> dict[object, np.ndarray]:
    """Return the chronological row positions of every unit.

    Raises when two rows of the same unit share a timestamp, because a duplicated
    timestamp makes the causal window order ambiguous.
    """
    group_arr = np.asarray(groups, dtype=object)
    tv = np.asarray(time_values, dtype=float)
    if tv.shape != group_arr.shape:
        raise ValueError("time_values must align one-to-one with groups")
    if not np.isfinite(tv).all():
        raise ValueError("time_values must contain only finite values")

    order: dict[object, np.ndarray] = {}
    for unit in dict.fromkeys(group_arr.tolist()):
        idx = np.flatnonzero(group_arr == unit)
        sorted_idx = idx[np.argsort(tv[idx], kind="stable")]
        if len(sorted_idx) > 1 and np.unique(tv[sorted_idx]).size != len(sorted_idx):
            raise ValueError(f"duplicate timestamps inside unit {unit!r}; cannot order causally")
        order[unit] = sorted_idx
    return order


def build_unit_windows(
    X_scaled: np.ndarray,
    y: pd.Series | np.ndarray,
    groups: pd.Series | np.ndarray,
    window_size: int,
    rul_cap: float | None = None,
    time_values: pd.Series | np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Build causal sliding windows strictly inside each independent physical unit.

    Returns tensors of shape ``(N, C, L)`` ready for ``torch.nn.Conv1d``, preserving
    original row order and left-padding short prefixes with the unit's first row.

    Row order is only trusted when ``time_values`` is omitted. Passing a timestamp
    column makes the window order explicit: rows are sorted chronologically inside
    each unit and every window is written back to its original row position, so a
    frame that was shuffled upstream cannot silently produce backward windows.
    """
    if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 1:
        raise ValueError("window_size must be a positive integer")
    x_arr = np.asarray(X_scaled, dtype=np.float32)
    y_arr = np.asarray(y, dtype=np.float32)
    g_arr = np.asarray(groups, dtype=object)
    if x_arr.ndim != 2:
        raise ValueError("X_scaled must be 2-dimensional (N, C)")
    n_samples, n_channels = x_arr.shape
    if n_samples == 0 or len(y_arr) != n_samples or len(g_arr) != n_samples:
        raise ValueError("X_scaled, y and groups must be nonempty and have equal lengths")

    if time_values is not None:
        order_by_unit = unit_sequence_order(g_arr, time_values)
    else:
        order_by_unit = {
            unit: np.flatnonzero(g_arr == unit) for unit in dict.fromkeys(g_arr.tolist())
        }

    windows = np.empty((n_samples, n_channels, window_size), dtype=np.float32)
    for unit, unit_indices in order_by_unit.items():
        unit_x = x_arr[unit_indices]  # (T, C), chronological
        for local_t, global_idx in enumerate(unit_indices):
            start = local_t - window_size + 1
            if start >= 0:
                seq = unit_x[start : local_t + 1]
            else:
                pad_len = -start
                pad = np.repeat(unit_x[0:1], pad_len, axis=0)
                seq = np.concatenate([pad, unit_x[0 : local_t + 1]], axis=0)
            windows[global_idx] = seq.T  # (C, L)

    targets = y_arr.copy()
    if rul_cap is not None:
        if isinstance(rul_cap, bool) or not np.isfinite(rul_cap) or rul_cap <= 0:
            raise ValueError("rul_cap must be a positive finite number or None")
        targets = np.minimum(targets, np.float32(rul_cap))
    return windows, targets


def extract_window_tabular_features(
    windows_ncl: np.ndarray,
    feature_names: list[str],
) -> pd.DataFrame:
    """Summarize (N, C, L) windows into tabular degradation statistics for LightGBM."""
    arr = np.asarray(windows_ncl, dtype=float)
    if arr.ndim != 3:
        raise ValueError("windows_ncl must be 3-dimensional (N, C, L)")
    _, n_channels, _ = arr.shape
    if len(feature_names) != n_channels:
        raise ValueError("feature_names length must match channel dimension C")

    mean = arr.mean(axis=2)
    std = arr.std(axis=2)
    slope = arr[:, :, -1] - arr[:, :, 0]
    rms = np.sqrt(np.mean(arr ** 2, axis=2))
    ptp = arr.max(axis=2) - arr.min(axis=2)

    data: dict[str, np.ndarray] = {}
    for c, name in enumerate(feature_names):
        data[f"{name}__win_mean"] = mean[:, c]
        data[f"{name}__win_std"] = std[:, c]
        data[f"{name}__win_slope"] = slope[:, c]
        data[f"{name}__win_rms"] = rms[:, c]
        data[f"{name}__win_ptp"] = ptp[:, c]
    return pd.DataFrame(data)
