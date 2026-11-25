"""Lightweight causal dilated TCN regression trainer compatible with RAC-HPO."""

from __future__ import annotations

from collections.abc import Callable
import copy
import math
from time import perf_counter
from typing import Any

import numpy as np

from rac_hpo.data.temporal_window import (
    apply_zscore_scaler,
    build_unit_windows,
    fit_zscore_scaler,
)
from rac_hpo.domain.schemas import (
    PreparedDataset,
    TaskCancelled,
    TrainingResult,
    TrainingTimeout,
)
from rac_hpo.evaluation.evaluator import evaluate


DEFAULT_TCN_MODEL_CONFIG = {
    "max_epochs": 40,
    "early_stopping_patience": 8,
    "batch_size": 64,
    "rul_cap": None,
    "device": "auto",
    # Clip validation targets for early stopping so selection happens in the same
    # target space the network was trained on. Final metrics still use raw labels.
    "clip_validation_targets": True,
    # None derives the depth from window_size; an int overrides it for ablations.
    "num_blocks": None,
}

DEFAULT_TCN_PARAMS = {
    "window_size": 32,
    "tcn_channels": 32,
    "learning_rate": 1e-3,
    "dropout": 0.1,
}

TCN_SEARCH_SPACE = {
    "window_size": {"type": "int", "low": 16, "high": 64},
    "tcn_channels": {"type": "int", "low": 16, "high": 64},
    "learning_rate": {"type": "float", "low": 1e-4, "high": 1e-2, "log": True},
    "dropout": {"type": "float", "low": 0.0, "high": 0.4},
}

_KERNEL_SIZE = 3
_MAX_BLOCKS = 6
_MIN_BLOCKS = 2


def receptive_field(blocks: int, kernel_size: int = _KERNEL_SIZE) -> int:
    """Receptive field of ``blocks`` residual blocks with dilations 1, 2, 4, ...

    Each block holds two dilated convolutions, so block ``i`` (0-based, dilation
    ``2**i``) adds ``2 * (kernel_size - 1) * 2**i`` timesteps.
    """
    if isinstance(blocks, bool) or not isinstance(blocks, int) or blocks < 1:
        raise ValueError("blocks must be a positive integer")
    span = sum(2 * (kernel_size - 1) * (2 ** i) for i in range(blocks))
    return 1 + span


def blocks_for_window(window_size: int, kernel_size: int = _KERNEL_SIZE) -> int:
    """Smallest depth whose receptive field covers ``window_size`` (bounded)."""
    if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 1:
        raise ValueError("window_size must be a positive integer")
    needed = _MIN_BLOCKS
    while receptive_field(needed, kernel_size) < window_size and needed < _MAX_BLOCKS:
        needed += 1
    return needed


def validate_params(params: dict[str, Any]) -> None:
    """Validate TCN hyperparameters before training or HPO evaluation."""
    unknown = set(params) - set(DEFAULT_TCN_PARAMS)
    if unknown:
        raise ValueError(f"unsupported TCN parameters: {sorted(unknown)}")
    for key, value in params.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"TCN parameter must be a finite number: {key}")
        if key in {"window_size", "tcn_channels"} and not isinstance(value, int):
            raise ValueError(f"TCN parameter must be an integer: {key}")
        if key in {"window_size", "tcn_channels"} and value < 1:
            raise ValueError(f"TCN parameter must be at least 1: {key}")
        if key == "learning_rate" and value <= 0:
            raise ValueError("learning_rate must be positive")
        if key == "dropout" and not 0.0 <= value < 1.0:
            raise ValueError("dropout must be in [0, 1)")


def _require_torch():
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError as exc:
        raise ImportError(
            "PyTorch is required for tcn_trainer. Install optional temporal dependencies "
            "(e.g. `pip install torch`) without modifying requirements-contest.txt."
        ) from exc
    return torch, nn, DataLoader, TensorDataset


def _resolve_device(torch_mod, requested: str):
    if requested == "auto":
        if hasattr(torch_mod.backends, "mps") and torch_mod.backends.mps.is_available():
            return torch_mod.device("mps")
        if torch_mod.cuda.is_available():
            return torch_mod.device("cuda")
        return torch_mod.device("cpu")
    return torch_mod.device(requested)


def _group_norm(nn, channels: int, max_groups: int = 8):
    """GroupNorm instead of BatchNorm: correct at batch size 1 and on tiny units."""
    for groups in (max_groups, 4, 2, 1):
        candidate = min(groups, channels)
        if channels % candidate == 0:
            return nn.GroupNorm(candidate, channels)
    return nn.GroupNorm(1, channels)


def _build_tcn_module(torch_mod, nn, in_channels: int, tcn_channels: int, dropout: float,
                      blocks: int):
    class TemporalResidualBlock(nn.Module):
        def __init__(self, c_in: int, c_out: int, dilation: int, kernel_size: int = _KERNEL_SIZE):
            super().__init__()
            self.pad = (kernel_size - 1) * dilation
            self.conv1 = nn.Conv1d(c_in, c_out, kernel_size, padding=self.pad, dilation=dilation)
            self.bn1 = _group_norm(nn, c_out)
            self.act1 = nn.ReLU()
            self.drop1 = nn.Dropout(dropout)

            self.conv2 = nn.Conv1d(c_out, c_out, kernel_size, padding=self.pad, dilation=dilation)
            self.bn2 = _group_norm(nn, c_out)
            self.act2 = nn.ReLU()
            self.drop2 = nn.Dropout(dropout)

            self.downsample = nn.Conv1d(c_in, c_out, kernel_size=1) if c_in != c_out else None
            self.out_act = nn.ReLU()

        def _chomp(self, x):
            return x[:, :, :-self.pad] if self.pad > 0 else x

        def forward(self, x):
            h = self.drop1(self.act1(self.bn1(self._chomp(self.conv1(x)))))
            h = self.drop2(self.act2(self.bn2(self._chomp(self.conv2(h)))))
            res = x if self.downsample is None else self.downsample(x)
            return self.out_act(h + res)

    class CausalTCNRegressor(nn.Module):
        def __init__(self):
            super().__init__()
            self.blocks = nn.Sequential(*[
                TemporalResidualBlock(
                    in_channels if index == 0 else tcn_channels,
                    tcn_channels,
                    dilation=2 ** index,
                    kernel_size=_KERNEL_SIZE,
                )
                for index in range(blocks)
            ])
            self.head = nn.Linear(tcn_channels, 1)

        def forward(self, x):
            features = self.blocks(x)
            return self.head(features[:, :, -1]).squeeze(-1)

    return CausalTCNRegressor()


def save_checkpoint(path, result: TrainingResult) -> None:
    """Persist a trained TCN (state dict + scaler + window config) without lightgbm."""
    torch_mod, _, _, _ = _require_torch()
    model = result.model if isinstance(result.model, dict) else None
    if not model or "module" not in model:
        raise ValueError("result.model must expose a 'module' entry produced by train()")
    payload = {
        "state_dict": model["module"].state_dict(),
        "params": dict(result.params),
        "model_meta": {key: value for key, value in model.items() if key != "module"},
        "best_iteration": int(result.best_iteration),
    }
    torch_mod.save(payload, path)


def load_checkpoint(path) -> dict:
    """Load a checkpoint written by :func:`save_checkpoint` on CPU."""
    torch_mod, _, _, _ = _require_torch()
    return torch_mod.load(path, map_location="cpu", weights_only=False)


def build_from_checkpoint(payload: dict, in_channels: int):
    """Rebuild the module described by a checkpoint payload."""
    torch_mod, nn, _, _ = _require_torch()
    params = payload["params"]
    meta = payload["model_meta"]
    blocks = int(meta.get("blocks") or blocks_for_window(int(params["window_size"])))
    module = _build_tcn_module(
        torch_mod, nn,
        in_channels=in_channels,
        tcn_channels=int(params["tcn_channels"]),
        dropout=float(params["dropout"]),
        blocks=blocks,
    )
    module.load_state_dict(payload["state_dict"])
    module.eval()
    return module


def train(
    dataset: PreparedDataset,
    params: dict[str, Any],
    seed: int = 42,
    model_config: dict[str, Any] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    evaluation_config: dict[str, Any] | None = None,
    resource_callback: Callable[[int, float], None] | None = None,
    timeout_seconds: float | None = None,
) -> TrainingResult:
    """Train a causal TCN only on train and validate only on validation; never touch test."""
    if timeout_seconds is not None and (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("training timeout_seconds must be positive and finite, or None")

    validate_params(params)
    effective = {**DEFAULT_TCN_PARAMS, **params}
    config = {**DEFAULT_TCN_MODEL_CONFIG, **(model_config or {})}
    unknown_cfg = set(config) - set(DEFAULT_TCN_MODEL_CONFIG)
    if unknown_cfg:
        raise ValueError(f"unsupported TCN model_config keys: {sorted(unknown_cfg)}")

    torch_mod, nn, DataLoader, TensorDataset = _require_torch()
    started = perf_counter()
    completed_epochs = 0

    def check_limits() -> None:
        if cancel_check is not None and cancel_check():
            raise TaskCancelled("training cancelled")
        if timeout_seconds is not None:
            elapsed = perf_counter() - started
            if elapsed >= timeout_seconds:
                raise TrainingTimeout(timeout_seconds, elapsed, completed_epochs)

    check_limits()
    X_train, y_train, _, train_groups = dataset.split("train")
    X_valid, y_valid, regimes, valid_groups = dataset.split("validation")
    if X_train.empty or X_valid.empty:
        raise ValueError("train and validation splits must be nonempty")
    if list(X_train.columns) != dataset.features or list(X_valid.columns) != dataset.features:
        raise ValueError("feature order differs from the fixed dataset contract")
    if not np.isfinite(np.asarray(y_train, dtype=float)).all():
        raise ValueError("training targets must be finite")

    window_size = int(effective["window_size"])
    blocks = int(config["num_blocks"]) if config["num_blocks"] is not None else blocks_for_window(window_size)
    span = receptive_field(blocks)

    scaler = fit_zscore_scaler(X_train)
    x_train_scaled = apply_zscore_scaler(X_train, scaler)
    x_valid_scaled = apply_zscore_scaler(X_valid, scaler)

    train_windows, train_targets = build_unit_windows(
        x_train_scaled, y_train, train_groups,
        window_size=window_size, rul_cap=config["rul_cap"],
    )
    # Final metrics always use unclipped labels; only the selection signal may be capped.
    valid_windows, valid_targets = build_unit_windows(
        x_valid_scaled, y_valid, valid_groups,
        window_size=window_size, rul_cap=None,
    )
    if config["rul_cap"] is not None and config["clip_validation_targets"]:
        selection_targets = np.minimum(valid_targets, np.float32(config["rul_cap"]))
        target_mode = "capped_for_selection_uncapped_for_metrics"
    else:
        selection_targets = valid_targets
        target_mode = "uncapped"

    np.random.seed(seed)
    torch_mod.manual_seed(seed)
    device = _resolve_device(torch_mod, str(config["device"]))

    model = _build_tcn_module(
        torch_mod, nn,
        in_channels=train_windows.shape[1],
        tcn_channels=int(effective["tcn_channels"]),
        dropout=float(effective["dropout"]),
        blocks=blocks,
    ).to(device)

    optimizer = torch_mod.optim.AdamW(model.parameters(), lr=float(effective["learning_rate"]))
    max_epochs = int(config["max_epochs"])
    scheduler = torch_mod.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, max_epochs))
    criterion = nn.MSELoss()

    generator = torch_mod.Generator().manual_seed(seed)
    train_loader = DataLoader(
        TensorDataset(torch_mod.from_numpy(train_windows), torch_mod.from_numpy(train_targets)),
        batch_size=int(config["batch_size"]),
        shuffle=True,
        generator=generator,
    )
    valid_tensor = torch_mod.from_numpy(valid_windows).to(device)
    train_eval_tensor = torch_mod.from_numpy(train_windows).to(device)

    best_rmse = math.inf
    best_epoch = 1
    best_state = copy.deepcopy(model.state_dict())
    stale_epochs = 0
    patience = int(config["early_stopping_patience"])
    curve: list[dict[str, float | int]] = []

    for epoch in range(1, max_epochs + 1):
        check_limits()
        model.train()
        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(device)
            batch_y = batch_y.to(device)
            optimizer.zero_grad()
            loss = criterion(model(batch_x), batch_y)
            loss.backward()
            optimizer.step()
        scheduler.step()
        completed_epochs = epoch

        model.eval()
        with torch_mod.no_grad():
            val_preds = model(valid_tensor).detach().cpu().numpy()
        val_rmse = float(np.sqrt(np.mean((val_preds - selection_targets) ** 2)))
        val_mae = float(np.mean(np.abs(val_preds - selection_targets)))
        curve.append({"iteration": epoch, "rmse": val_rmse, "mae": val_mae})

        if resource_callback is not None:
            resource_callback(epoch, val_rmse)

        if val_rmse + 1e-8 < best_rmse:
            best_rmse = val_rmse
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= patience:
                break

    check_limits()
    model.load_state_dict(best_state)
    model.eval()
    with torch_mod.no_grad():
        predictions = model(valid_tensor).detach().cpu().numpy()
        train_predictions = model(train_eval_tensor).detach().cpu().numpy()

    metrics = evaluate(
        y_valid, predictions, regimes, valid_groups,
        group_kind=dataset.manifest.get("independent_unit_kind", "independent_run"),
        bootstrap_seed=seed, **(evaluation_config or {}),
    )
    metrics["overall_rmse"] = float(np.sqrt(np.mean((predictions - np.asarray(y_valid, dtype=float)) ** 2)))

    train_mae = float(np.mean(np.abs(train_predictions - train_targets)))
    train_rmse = float(np.sqrt(np.mean((train_predictions - train_targets) ** 2)))
    diagnostics = {
        "train_rows": len(X_train),
        "validation_rows": len(X_valid),
        "train_mae": train_mae,
        "train_rmse": train_rmse,
        "validation_mae": metrics["overall_mae"],
        "validation_rmse": metrics["overall_rmse"],
        "best_iteration": best_epoch,
        "evaluated_iterations": len(curve),
        "device": str(device),
        "window_size": window_size,
        "tcn_blocks": blocks,
        "receptive_field": span,
        "window_fully_observed": bool(span >= window_size),
        "validation_target_mode": target_mode,
        "validation_curve": curve,
    }
    check_limits()
    return TrainingResult(
        params=effective,
        metrics=metrics,
        duration_seconds=perf_counter() - started,
        model={
            "module": model.cpu(),
            "scaler": scaler,
            "window_size": window_size,
            "blocks": blocks,
            "receptive_field": span,
        },
        best_iteration=best_epoch,
        diagnostics=diagnostics,
    )
