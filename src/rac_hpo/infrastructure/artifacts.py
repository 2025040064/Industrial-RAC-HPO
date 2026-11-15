import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from rac_hpo._io import atomic_text


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: str | Path, value) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def write_yaml(path: str | Path, value) -> None:
    atomic_text(path, yaml.safe_dump(value, allow_unicode=True, sort_keys=False))


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    paths = list((root / "src").rglob("*.py")) + list((root / "configs").rglob("*.yaml"))
    paths += [root / "pyproject.toml", root / "uv.lock"]
    for path in sorted(paths):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_commit(root: Path) -> str:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return commit.stdout.strip() if commit.returncode == 0 else "unversioned"
    except OSError:
        # git is absent from PATH on some installations; keep the snapshot usable.
        return "unversioned"


def environment_snapshot(root: Path) -> dict:
    from rac_hpo.runtime import build_info

    # The packaged app has no checkout; its commit and source digest were
    # recorded at build time. Never run git there: on a Mac without the
    # Command Line Tools /usr/bin/git opens an installer dialog.
    distribution = build_info()
    if distribution is None:
        code_commit, source_sha256 = _git_commit(root), source_fingerprint(root)
    else:
        code_commit = distribution.get("code_commit", "unversioned")
        source_sha256 = distribution.get("source_sha256", "unknown")
    packages = ("numpy", "pandas", "scipy", "scikit-learn", "lightgbm", "optuna",
                "PySide6", "matplotlib", "pydantic", "PyYAML")
    versions = {}
    for name in packages:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            if name != "PySide6":
                raise
            versions[name] = importlib.metadata.version("PySide6-Essentials")
    snapshot = {
        "python": sys.version, "platform": platform.platform(),
        "processor": platform.processor(), "cpu_count": os.cpu_count(),
        "packages": versions,
        "all_distributions": {item.metadata["Name"]: item.version
                              for item in importlib.metadata.distributions()
                              if item.metadata["Name"]},
        "code_commit": code_commit,
        "source_sha256": source_sha256, "captured_at": utc_now(),
    }
    if distribution is not None:
        snapshot["distribution"] = distribution
    return snapshot


def save_convergence(path: Path, trials: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    figure = Figure(figsize=(7, 4), tight_layout=True)
    axis = figure.subplots()
    x, y, elapsed, best = [], [], 0.0, float("inf")
    for trial in trials:
        elapsed += trial.get("wall_duration_seconds", trial.get("duration_seconds", 0)) + trial.get("selection_duration_seconds", 0)
        value = trial.get("objective")
        if trial["status"] == "completed" and value is not None:
            best = min(best, value)
            x.append(elapsed)
            y.append(best)
    axis.plot(x, y, marker="o", color="#007AFF")
    axis.set(xlabel="Cumulative completed-trial wall time (s)", ylabel="Best validation objective")
    axis.grid(alpha=0.2)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=140)
