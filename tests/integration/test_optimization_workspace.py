"""Presentation regressions; constructed records exercise UI mapping only."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rac_hpo.interfaces.gui.pages.optimize_page import OptimizePage
from rac_hpo.interfaces.gui.theme import apply_theme
from rac_hpo.interfaces.gui.charts import ExperimentChart


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def page(qt_app):
    widget = OptimizePage()
    yield widget
    widget.close()
    qt_app.processEvents()


def experiment(identifier="EXP-ui-mapping", algorithm="tpe_robust"):
    return {
        "id": identifier, "dataset_id": "recorded-dataset", "algorithm": algorithm,
        "status": "completed", "target_unit": "cycles", "duration_seconds": 14.5,
        "best_trial": 2, "best_value": 1.2, "best_params": {"learning_rate": 0.1},
        "config": {"model": {"name": "lightgbm"}, "optimization": {
            "max_trials": 8, "search_space": {"learning_rate": {"log": True}},
        }},
        "trials": [
            {"number": -1, "status": "completed", "objective": 0.01,
             "metrics": {"overall_mae": 4.0}, "duration_seconds": 1.0},
            {"number": 0, "status": "completed", "objective": 1.5,
             "params": {"learning_rate": 0.02}, "metrics": {"overall_mae": 3.0}},
            {"number": 1, "status": "failed", "objective": None,
             "failure_reason": "recorded failure"},
            {"number": 2, "status": "completed", "objective": 1.2,
             "params": {"learning_rate": 0.1}, "metrics": {"overall_mae": 2.5}},
        ],
    }


def test_history_does_not_change_new_search_controls(page):
    page.algorithm_combo.setCurrentIndex(page.algorithm_combo.findData("random"))
    page.trials_spin.setValue(19)
    page.seed_spin.setValue(73)
    page.show_result(experiment(algorithm="rac_hpo"))
    assert page.algorithm_combo.currentData() == "random"
    assert page.trials_spin.value() == 19
    assert page.seed_spin.value() == 73


def test_default_baseline_is_excluded_from_search_metrics_and_charts(page):
    page.show_result(experiment())
    assert page.chart.values == [1.5, 1.2]
    assert page.trial_table.rowCount() == 3
    assert page.metrics.cards["trials"].value_label.text() == "3 / 8"
    assert "1.2" in page.metrics.cards["best"].value_label.text()
    assert "J" in page.metrics.cards["best"].value_label.text()
    assert "cycles" in page.trial_table.columns[3][1]


def test_history_curve_preserves_real_trial_numbers(page):
    page.show_result(experiment())
    assert page.chart.trial_numbers == [0, 2]
    assert page.chart.best_values == [1.5, 1.2]
    assert page.parameter_chart.log_scale


def test_history_lines_do_not_fill_the_area_between_unrelated_points(qt_app):
    from PySide6.QtGui import QColor

    chart = ExperimentChart("history")
    chart.resize(600, 320)
    chart.set_snapshot({"algorithm": "tpe", "target_unit": "cycles", "trials": [
        {"number": number, "status": "completed", "objective": value}
        for number, value in enumerate((10.0, 1.0, 8.0, 2.0))
    ]})
    try:
        chart.show()
        qt_app.processEvents()
        image = chart.grab().toImage()
        grey_samples = sum(image.pixelColor(x, y) == QColor("#94A3B8")
                           for x in range(0, image.width(), 4)
                           for y in range(0, image.height(), 4))
        assert grey_samples < 300, "Line chart must not paint a filled polygon"
    finally:
        chart.close()


def test_active_snapshot_does_not_replace_viewed_history(page):
    history = experiment("EXP-history")
    current = experiment("EXP-active", "random")
    current["status"] = "running"
    current["trials"] = current["trials"][:2]
    page.set_active_experiment(current["id"])
    page.show_result(history, historical=True)
    page.update_snapshot(current, active=True)
    page.set_elapsed(200)
    page.set_task_state("cancelling")
    assert page.experiment_id == history["id"]
    assert page.chart.trial_numbers == [0, 2]
    assert page.elapsed_value.text() == "14.5 秒"
    assert page.metrics.cards["status"].value_label.text() == "已完成"
    assert not page.return_button.isHidden()


def test_all_failed_search_never_displays_baseline_as_best(page):
    result = experiment()
    result["status"] = "failed"
    result["trials"] = [result["trials"][0], result["trials"][2]]
    result["failure_reason"] = "No successful trial"
    result["best_value"] = None
    page.show_result(result, historical=True)
    assert page.metrics.cards["best"].value_label.text() == "—"
    assert page.chart.values == []
    assert page.status_chart.snapshot["trials"] == result["trials"]
    assert "No successful trial" in page.error_label.text()


def test_progress_deduplicates_number_and_preserves_mae_unit(page):
    result = experiment(algorithm="random")
    result["trials"].append({**result["trials"][1], "objective": 1.4})
    page.show_result(result)
    assert page.chart.trial_numbers == [0, 2]
    assert page.chart.values == [1.4, 1.2]
    assert page.trial_table.rowCount() == 3
    assert page.trial_table.columns[2][1] == "目标 MAE / cycles"


def test_maximized_chart_stays_bound_to_opened_experiment(page, qt_app):
    original = experiment("EXP-opened")
    page.show_result(original, historical=True)
    page.maximize_chart("history")
    dialog = page._maximized[0]
    page.show_result(experiment("EXP-other"), historical=True)
    original["trials"].append({"number": 5, "status": "completed", "objective": 1.0})
    page.update_snapshot(original)
    assert dialog.experiment_id == "EXP-opened"
    assert dialog.chart.trial_numbers == [0, 2, 5]
    assert page.experiment_id == "EXP-other"
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    qt_app.processEvents()
    assert not page._maximized


def test_responsive_charts_render_and_hover_real_trial_records(page, qt_app):
    page.show_result(experiment(), historical=True)
    page.resize(1440, 900)
    page.show()
    QTest.qWait(30)
    assert page.panel_grid.column_count == 2
    for panel in page.chart_panels.values():
        assert not panel.chart.grab().isNull()
    assert any("试验 #2" in tip for _, tip in page.chart._hits)
    page.resize(800, 600)
    QTest.qWait(30)
    assert page.panel_grid.column_count == 1
    assert page.scroll.horizontalScrollBar().maximum() == 0


def test_historical_running_has_no_live_clock_or_cancel(page):
    result = experiment()
    result["status"] = "running"
    page.show_result(result, historical=True)
    page.set_task_state("running")
    page.set_elapsed(500)
    assert page.elapsed_value.text() == "14.5 秒"
    assert not page.cancel_button.isEnabled()
    assert "历史实验" in page.header.status_label.text()


def test_active_timer_is_not_replaced_by_initial_snapshot_duration(page):
    result = experiment("EXP-clock")
    result.update(status="running", duration_seconds=0)
    page.set_active_experiment(result["id"])
    page.show_result(result)
    page.set_elapsed(23.5)
    page.update_snapshot(result, active=True)
    assert page.elapsed_value.text() == "23.5 秒"
    result.update(status="completed", duration_seconds=25.7)
    page.update_snapshot(result)
    assert page.elapsed_value.text() == "25.7 秒"


def test_table_detail_binds_true_trial_after_numeric_sort(page, qt_app):
    page.resize(1280, 880)
    page.show_result(experiment())
    page.show()
    qt_app.processEvents()
    page.trial_table.sort_by("objective", Qt.SortOrder.AscendingOrder)
    record = page.trial_table.model.rows[0]
    assert record["number"] == 2
    page._open_trial(record)
    assert page.drawer._trial_number == 2
    assert page.drawer.experiment_id == "EXP-ui-mapping"
    page.show_result(experiment("EXP-switched"), historical=True)
    assert page.drawer.isHidden()

