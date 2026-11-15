"""Where the workspace lives: the source checkout, or a per-user folder for the packaged app.

A PyInstaller bundle is read-only and replaced on every upgrade, so the packaged
macOS app keeps configs, datasets and the append-only experiment history in
``~/Library/Application Support/RAC-HPO`` (override with ``RAC_HPO_HOME``).
The folder name is ASCII on purpose: Python 3.11 locale handling has failed on
non-ASCII paths before (docs/PHASE_0_1_REPORT.md).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

APP_DIR_NAME = "RAC-HPO"
HOME_ENV = "RAC_HPO_HOME"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Read-only resources: the PyInstaller data directory, or the checkout."""
    return Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) if is_frozen() else PROJECT_ROOT


def user_root(home: Path | None = None) -> Path:
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path(home or Path.home()) / "Library/Application Support" / APP_DIR_NAME


def build_info() -> dict | None:
    """Commit and source digest recorded at build time; None for a source checkout."""
    if not is_frozen():
        return None
    path = bundle_root() / "build_info.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _seed(root: Path) -> None:
    bundle = bundle_root()
    config = root / "configs/default.yaml"
    if not config.is_file():
        config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle / "configs/default.yaml", config)
    # uv.lock is copied into each experiment as the dependency record, so it
    # must describe the build that is running, not the first one installed.
    lock = bundle / "uv.lock"
    if lock.is_file():
        shutil.copy2(lock, root / "uv.lock")


def default_root() -> Path:
    if not is_frozen():
        return PROJECT_ROOT
    root = user_root().resolve()
    root.mkdir(parents=True, exist_ok=True)
    _seed(root)
    return root


def implementation_fingerprint() -> tuple[Path, str]:
    """Location and digest of the code actually executing."""
    info = build_info()
    if info is not None:
        return bundle_root(), info.get("source_sha256", "unknown")
    from rac_hpo.infrastructure.artifacts import source_fingerprint
    return PROJECT_ROOT, source_fingerprint(PROJECT_ROOT)
