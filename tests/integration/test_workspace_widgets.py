"""Presentation contracts: real record identity, numeric ordering and disclosure."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from rac_hpo.interfaces.gui.workspace_widgets import (
    CollapsiblePanel, MetricsGrid, PanelGrid, RecordTable, RunDetailDrawer,
)
from rac_hpo.interfaces.gui.theme import apply_theme


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    apply_theme(application)
    return application


def test_numeric_sort_precedes_paging_and_missing_values_stay_last(app):
    table = RecordTable([("number", "编号"), ("objective", "目标")])
    table.set_records([
        {"_id": str(number), "number": number, "objective": None if number == 3 else number}
        for number in range(60)
    ])
    table.sort_by("objective", Qt.SortOrder.DescendingOrder)
    assert table.rowCount() == 25
    assert table.model.index(0, 0).data(Qt.ItemDataRole.UserRole)["_id"] == "59"
    table.set_page(2)
    assert table.rowCount() == 10
    assert table.model.index(9, 0).data(Qt.ItemDataRole.UserRole)["_id"] == "3"
    table.deleteLater()


def test_search_filters_nested_parameters_and_selection_uses_stable_id(app):
    table = RecordTable([("number", "编号"), ("status", "状态")], ("status",))
    records = [
        {"_id": "trial-9", "number": 9, "status": "completed", "params": {"depth": "needle"}},
        {"_id": "trial-2", "number": 2, "status": "failed", "params": {"depth": "other"}},
    ]
    table.set_records(records)
    table.view.selectRow(0)
    assert table.selected_record["_id"] == "trial-9"
    table.sort_by("number", Qt.SortOrder.AscendingOrder)
    assert table.selected_record["_id"] == "trial-9"
    table.search_edit.setText("needle")
    assert table.rowCount() == 1
    assert table.model.index(0, 0).data(Qt.ItemDataRole.UserRole)["_id"] == "trial-9"
    table.filters["status"].setCurrentIndex(table.filters["status"].findData("failed"))
    assert table.rowCount() == 0
    assert table.selected_record is None
    table.deleteLater()


def test_clicking_selected_record_reopens_detail_once_per_click(app):
    table = RecordTable([("number", "编号")])
    table.set_records([{"_id": "trial-7", "number": 7}])
    table.resize(700, 240)
    table.show()
    app.processEvents()
    opened = []
    table.record_selected.connect(lambda record: opened.append(record["_id"]))
    point = table.view.visualRect(table.model.index(0, 0)).center()
    QTest.mouseClick(table.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert opened == ["trial-7"]
    QTest.mouseClick(table.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert opened == ["trial-7", "trial-7"]
    table.close()


def test_responsive_panels_and_collapsed_actions_remain_visible(app):
    grid = PanelGrid()
    panels = [QWidget(), QWidget()]
    for panel in panels:
        grid.add_panel(panel)
    grid.resize(1100, 600)
    grid.show()
    app.processEvents()
    assert grid.column_count == 2
    grid.resize(800, 600)
    app.processEvents()
    assert grid.column_count == 1
    metrics = MetricsGrid([("dataset", "数据集"), ("model", "模型")])
    metrics.set_metric("dataset", "A long dataset identifier", "真实数据集")
    assert metrics.cards["dataset"].value_label.toolTip() == "A long dataset identifier"
    panel = CollapsiblePanel("配置")
    action = QPushButton("取消任务")
    panel.actions.addWidget(action)
    panel.show()
    panel.set_expanded(False)
    assert not panel.content.isVisible()
    assert action.isVisible()
    grid.close()
    panel.close()
    metrics.close()


def test_drawer_keeps_experiment_id_during_trial_drilldown_and_escape(app):
    host = QWidget()
    host.resize(900, 700)
    host.show()
    drawer = RunDetailDrawer(host)
    experiment = {
        "id": "EXP-real-id", "algorithm": "tpe", "target_unit": "kWh",
        "metrics": {"overall_mae": 2.5}, "status": "completed",
        "trials": [{"number": 12, "status": "completed", "objective": 2.5,
                    "params": {"max_depth": 7}, "metrics": {"overall_mae": 2.5}}],
    }
    exports = []
    drawer.export_requested.connect(exports.append)
    drawer.show_experiment(experiment)
    assert drawer.width() == 900
    drawer.trial_table.view.selectRow(0)
    assert drawer.experiment_id == "EXP-real-id"
    assert drawer.back_button.isVisible()
    drawer.export_button.click()
    assert exports == ["EXP-real-id"]
    host.resize(500, 700)
    app.processEvents()
    assert drawer.width() == 500
    QTest.keyClick(drawer, Qt.Key.Key_Escape)
    assert not drawer.isVisible()
    host.close()


def test_metric_breakpoint_uses_available_width_without_empty_columns(app):
    grid = MetricsGrid([(str(index), str(index)) for index in range(6)])
    grid.resize(1150, 120)
    grid.show()
    app.processEvents()
    assert grid.column_count == 4
    grid.resize(800, 240)
    app.processEvents()
    assert grid.column_count == 2
    grid.resize(600, 360)
    app.processEvents()
    assert grid.column_count == 2
    four = MetricsGrid([(str(index), str(index)) for index in range(4)])
    four.resize(1200, 120)
    four.show()
    app.processEvents()
    assert four.column_count == 4
    grid.close()
    four.close()


def test_drawer_units_diagnostics_elapsed_labels_and_focus_are_truthful(app):
    host = QWidget()
    host.resize(800, 700)
    background = QPushButton("后台控件", host)
    host.show()
    background.setFocus()
    app.processEvents()
    drawer = RunDetailDrawer(host)
    experiment = {"id": "EXP-units", "algorithm": "rac_hpo", "target_unit": "mm",
                  "config": {}, "search_diagnostics": {"decision_counts": {"rac_acquisition": 3}},
                  "trials": []}
    drawer.show_experiment(experiment)
    app.processEvents()
    labels = "\n".join(label.text() for label in drawer.findChildren(QLabel))
    assert "候选排序诊断" in labels
    assert "rac_acquisition" in labels
    drawer.show_trial(experiment, {"number": 0, "status": "failed", "duration_seconds": 4,
                                   "metrics": {}, "params": {}})
    app.processEvents()
    labels = "\n".join(label.text() for label in drawer.findChildren(QLabel) if label.isVisible())
    assert "试验耗时 (s)" in labels
    assert "J（无量纲）" in labels
    drawer.view_button.setFocus()
    QTest.keyClick(drawer.view_button, Qt.Key.Key_Tab)
    assert drawer.isAncestorOf(app.focusWidget())
    drawer.close_drawer()
    assert app.focusWidget() is background
    host.close()
def test_live_drawer_update_preserves_content_scroll_and_filter(app):
    from copy import deepcopy
    from PySide6.QtWidgets import QWidget
    from rac_hpo.interfaces.gui.workspace_widgets import RunDetailDrawer

    host = QWidget()
    host.resize(800, 600)
    host.show()
    drawer = RunDetailDrawer(host)
    result = {"id": "test-live", "algorithm": "tpe", "status": "running",
              "target_unit": "cycles", "config": {}, "trials": [
                  {"number": number, "status": "completed", "objective": 1.0}
                  for number in range(30)
              ]}
    try:
        drawer.show_experiment(result)
        drawer.trial_table.search_edit.setText("completed")
        app.processEvents()
        drawer.scroll.verticalScrollBar().setValue(100)
        previous_content = drawer.scroll.widget()
        previous_scroll = drawer.scroll.verticalScrollBar().value()
        updated = deepcopy(result)
        updated["trials"].append({"number": 30, "status": "completed", "objective": 0.9})
        drawer.update_experiment(updated)
        app.processEvents()
        assert drawer.scroll.widget() is previous_content
        assert drawer.trial_table.search_edit.text() == "completed"
        assert drawer.scroll.verticalScrollBar().value() == previous_scroll
    finally:
        host.close()

