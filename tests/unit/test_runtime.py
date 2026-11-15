"""Workspace location for the source checkout and the packaged macOS app."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from rac_hpo import runtime
from rac_hpo.infrastructure.artifacts import environment_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def frozen_bundle(monkeypatch, tmp_path):
    """Simulate a PyInstaller bundle: read-only resources plus a user home."""
    bundle = tmp_path / "bundle"
    (bundle / "configs").mkdir(parents=True)
    (bundle / "configs/default.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (bundle / "uv.lock").write_text("lock-from-build\n", encoding="utf-8")
    (bundle / "build_info.json").write_text(json.dumps({
        "code_commit": "abc1234", "source_sha256": "f" * 64,
        "built_at": "2026-11-15T00:00:00+00:00", "kind": "macos-app",
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    home = tmp_path / "data home"
    monkeypatch.setenv(runtime.HOME_ENV, str(home))
    return bundle, home


def test_source_checkout_uses_project_root(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert runtime.default_root() == PROJECT_ROOT
    assert runtime.build_info() is None


def test_default_user_root_is_application_support(monkeypatch, tmp_path):
    monkeypatch.delenv(runtime.HOME_ENV, raising=False)
    root = runtime.user_root(home=tmp_path)
    assert root == tmp_path / "Library/Application Support" / runtime.APP_DIR_NAME
    assert root.name.isascii()


def test_frozen_root_is_seeded_outside_the_bundle(frozen_bundle):
    bundle, home = frozen_bundle
    root = runtime.default_root()
    assert root == home.resolve()
    assert not root.is_relative_to(bundle)
    assert (root / "configs/default.yaml").read_text(encoding="utf-8") == "schema_version: 1\n"
    assert (root / "uv.lock").read_text(encoding="utf-8") == "lock-from-build\n"


def test_frozen_root_keeps_user_config_and_refreshes_lock(frozen_bundle):
    bundle, home = frozen_bundle
    (home / "configs").mkdir(parents=True)
    (home / "configs/default.yaml").write_text("user: edited\n", encoding="utf-8")
    (home / "uv.lock").write_text("old build\n", encoding="utf-8")
    root = runtime.default_root()
    assert (root / "configs/default.yaml").read_text(encoding="utf-8") == "user: edited\n"
    assert (root / "uv.lock").read_text(encoding="utf-8") == "lock-from-build\n"


def test_frozen_snapshot_never_spawns_git(frozen_bundle, monkeypatch):
    """/usr/bin/git on a Mac without CLT pops an installer dialog; never call it."""

    original = subprocess.run

    def no_git(command, *args, **kwargs):
        # platform.processor() runs /usr/bin/uname on macOS; that is harmless.
        assert "git" not in str(command[0]), f"git spawned in frozen app: {command}"
        return original(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", no_git)
    snapshot = environment_snapshot(runtime.default_root())
    assert snapshot["code_commit"] == "abc1234"
    assert snapshot["source_sha256"] == "f" * 64
    assert snapshot["distribution"]["kind"] == "macos-app"


def test_implementation_fingerprint(frozen_bundle, monkeypatch):
    bundle, _ = frozen_bundle
    location, digest = runtime.implementation_fingerprint()
    assert location == bundle
    assert digest == "f" * 64
    monkeypatch.delattr(sys, "frozen")
    from rac_hpo.infrastructure.artifacts import source_fingerprint
    assert runtime.implementation_fingerprint() == (PROJECT_ROOT, source_fingerprint(PROJECT_ROOT))
