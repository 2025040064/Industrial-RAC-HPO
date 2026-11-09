"""Verification helpers must use the host's native Qt plugin when requested."""

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["verify_ui_workspace", "verify_controlled_loop"])
def test_qt_platform_configuration(name, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    module.configure_qt_platform(native=True)
    assert "QT_QPA_PLATFORM" not in module.os.environ
    module.configure_qt_platform(native=False)
    assert module.os.environ["QT_QPA_PLATFORM"] == "offscreen"
