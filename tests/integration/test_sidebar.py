"""Fixed navigation contracts; expanded-sidebar tests were replaced by the V2 spec."""

import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rac_hpo.interfaces.gui import sidebar as sidebar_module
from rac_hpo.interfaces.gui.main_window import MainWindow
from rac_hpo.interfaces.gui.theme import apply_theme


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def _prepare_root(path):
    (path / "configs").mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_ROOT / "configs/default.yaml", path / "configs/default.yaml")
    return path


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    monkeypatch.delenv("RAC_HPO_REDUCED_MOTION", raising=False)
    widget = MainWindow(_prepare_root(tmp_path))
    widget.resize(1280, 880)
    widget.show()
    for _ in range(4):
        qt_app.processEvents()
    yield widget
    widget.close()
    qt_app.processEvents()


def test_rail_geometry_does_not_change_for_hover_or_focus(window):
    before=window.pages.geometry()
    assert window.sidebar.width()==56
    QTest.mouseMove(window.navigation.viewport(),window.navigation.visualItemRect(window.navigation.item(2)).center())
    QTest.qWait(300)
    window.navigation.setFocus()
    assert window.sidebar.width()==56
    assert window.pages.geometry()==before
    assert window.sidebar.height()==window.sidebar.parentWidget().height()


def test_only_current_item_has_tooltip_and_escape_dismisses(window):
    rail=window.sidebar
    for index in range(5):
        point=window.navigation.visualItemRect(window.navigation.item(index)).center()
        QTest.mouseMove(window.navigation.viewport(),point)
        QTest.qWait(280)
        assert rail.tooltip.isVisible()
        assert rail.tooltip.text()==window.navigation.item(index).text()
        assert rail.width()==56
    QTest.keyClick(window.navigation, Qt.Key.Key_Escape)
    assert not rail.tooltip.isVisible()


def test_navigation_still_drives_pages(window):
    for index in range(5):
        window.navigation.setCurrentRow(index)
        assert window.pages.currentIndex()==index


def test_reduced_motion_does_not_change_fixed_rail(qt_app,tmp_path,monkeypatch):
    monkeypatch.setenv('RAC_HPO_REDUCED_MOTION','1')
    widget=MainWindow(_prepare_root(tmp_path));widget.show();qt_app.processEvents()
    try:
        widget.navigation.setFocus();assert widget.sidebar.width()==56
    finally:widget.close()


def test_reduced_motion_detection_reads_the_environment(monkeypatch):
    monkeypatch.setenv('RAC_HPO_REDUCED_MOTION','1')
    assert sidebar_module.reduced_motion_enabled() is True
    monkeypatch.setenv('RAC_HPO_REDUCED_MOTION','0')
    assert sidebar_module.reduced_motion_enabled() is False
