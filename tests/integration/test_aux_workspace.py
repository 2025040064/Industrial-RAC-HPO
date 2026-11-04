"""Presentation regressions, using explicit fixtures rather than claimed experiment results."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidget

from rac_hpo.interfaces.gui.pages.compare_page import ComparePage
from rac_hpo.interfaces.gui.pages.data_page import DataPage
from rac_hpo.interfaces.gui.pages.logs_page import LogsPage
from rac_hpo.interfaces.gui.pages.train_page import TrainPage


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_sorted_history_keeps_selected_experiment_id(app):
    page = ComparePage()
    records = [{"id": "EXP-A", "algorithm": "random"}, {"id": "EXP-Z", "algorithm": "tpe"}]
    page.show_experiments(records)
    selected = []
    page.detail_requested.connect(selected.append)
    page.history_table.sort_by('id', Qt.SortOrder.DescendingOrder)
    page.history_table.view.selectRow(0)
    assert not selected
    assert page.experiment_id == 'EXP-Z'
    page.history_table.details_button.click()
    assert selected[-1] == 'EXP-Z'
    page.close()


def test_logs_append_without_rewriting_existing_document(app, monkeypatch):
    page = LogsPage()
    rewrites = []
    original = page.view.setPlainText
    monkeypatch.setattr(page.view, "setPlainText", lambda text: (rewrites.append(text), original(text)))
    page.append("trial_completed number=1")
    page.append("trial_completed number=2")
    assert rewrites == []
    assert "number=1" in page.view.toPlainText()
    assert "number=2" in page.view.toPlainText()
    page.close()


def test_data_missing_counts_remain_unknown(app):
    page = DataPage()
    page.show_summary({"dataset_id": "fixture", "manifest": {"license": "Fixture only"}})
    assert page.metrics.cards["records"].value_label.text() == "—"
    assert "Fixture only" in page.provenance_label.text()
    page.close()


def test_training_units_and_durations_are_distinct(app):
    page = TrainPage()
    page.show_result({"id": "fixture", "status": "completed", "target_unit": "minutes",
                      "metrics": {"overall_mae": 2.5, "robust_objective": 0.4, "regimes": {}},
                      "baseline_duration_seconds": 3.0, "duration_seconds": 5.0,
                      "best_iteration": 7, "best_params": {"num_leaves": 16}})
    assert "minutes" in page.metrics.cards["mae"].value_label.text()
    assert "3" in page.metrics.cards["training_duration"].value_label.text()
    assert "5" in page.duration_label.text()
    assert "无量纲" in page.metrics.cards["objective"].value_label.text()
    page.close()


def test_history_numeric_sort_paging_filter_and_export_use_id(app):
    page = ComparePage()
    records = [{"id": f"EXP-{number:02}", "algorithm": "tpe" if number % 2 else "random",
                "status": "completed", "duration_seconds": float(number),
                "metrics": {"overall_mae": float(number)}} for number in range(60)]
    page.show_experiments(records)
    page.history_table.sort_by("overall_mae", Qt.SortOrder.DescendingOrder)
    page.history_table.set_page(1)
    page.history_table.view.selectRow(0)
    exported = []
    page.export_requested.connect(exported.append)
    page.export_button.click()
    assert exported == ["EXP-34"]
    assert page.history_table.rowCount() == 25
    page.history_table.filters["algorithm"].setCurrentIndex(2)
    assert page.history_table.filtered_count == 30
    page.history_table.search_edit.setText("EXP-59")
    assert page.history_table.rowCount() == 1
    page.history_table.view.selectRow(0)
    page.export_button.click()
    assert exported[-1] == "EXP-59"
    page.close()


def test_logs_filter_export_clear_and_manual_scroll(app):
    page = LogsPage()
    page.resize(760, 620)
    page.show()
    for number in range(150):
        page.append(f"TRIAL_COMPLETED number={number}")
    app.processEvents()
    page.auto_scroll.setChecked(False)
    scrollbar = page.view.verticalScrollBar()
    scrollbar.setValue(10)
    page.append("final trial event")
    assert scrollbar.value() == 10
    page.filter_edit.setText("trial_completed number=149")
    assert page.matched_events == 1
    assert "number=149" in page.view.toPlainText()
    exported = []
    page.export_requested.connect(exported.append)
    page.export_button.click()
    assert exported == [page.view.toPlainText()]
    page.copy_button.click()
    assert QApplication.clipboard().text() == exported[0]
    page.clear_display()
    assert page.view.toPlainText() == ""
    assert page.total_events == 151
    assert page.matched_events == 0
    page.close()


def test_collapsed_training_configuration_keeps_cancel_and_error_visible(app):
    page = TrainPage()
    page.resize(740, 600)
    page.show()
    page.set_busy(True, True)
    page.config_panel.set_expanded(False)
    page.set_task_state("cancelling")
    page.show_error("failure detail")
    app.processEvents()
    assert page.cancel_button.isVisible()
    assert not page.cancel_button.isEnabled()
    assert page.error_label.isVisible()
    assert page.error_label.text() == "failure detail"
    page.close()


def test_new_training_clears_previous_experiment_result(app):
    page = TrainPage()
    page.show_result({"id": "previous", "status": "completed", "target_unit": "cycles",
                      "metrics": {"overall_mae": 1, "regimes": {"old": {"samples": 2, "mae": 1}}},
                      "best_params": {"num_leaves": 31}, "failure_reason": "previous failure"})
    page.reset_progress()
    assert page.experiment_id is None
    assert not page.export_button.isEnabled()
    assert page.metrics.cards["mae"].value_label.text() == "—"
    assert page.regime_table.rowCount() == 0
    assert page.params_table.rowCount() == 0
    assert page.detail.toPlainText() == ""
    assert page.error_label.isHidden()
    page.close()


def test_data_field_units_and_time_range_come_from_manifest(app):
    page = DataPage()
    page.show_summary({"dataset_id": "fixture", "feature_names": ["ADOC"],
                       "manifest": {"feature_units": {"ADOC": "mm"}, "date_range": ["2025-01-01", "2025-03-01"]}})
    assert "ADOC" in page.feature_units_label.text()
    assert "mm" in page.feature_units_label.text()
    assert "2025-03-01" in page.date_range_label.text()
    page.show_summary({"dataset_id": "empty"})
    assert page.feature_units_label.isHidden()
    assert page.date_range_label.isHidden()
    page.close()
