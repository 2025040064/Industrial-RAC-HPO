"""Native Qt smoke tests using the actual service and real Steel data."""

import os
import queue
import shutil
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtGui import QFont, QFontDatabase, QRawFont
from PySide6.QtWidgets import QApplication

from rac_hpo.interfaces.gui.main_window import MainWindow
from rac_hpo.interfaces.gui.theme import apply_theme
from rac_hpo.interfaces.gui.workers import TaskController


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def window(qt_app, tmp_path):
    (tmp_path / "configs").mkdir()
    shutil.copy2(PROJECT_ROOT / "configs/default.yaml", tmp_path / "configs/default.yaml")
    widget = MainWindow(tmp_path)
    yield widget
    if widget.controller.running:
        widget.controller.cancel()
        wait_for_idle(widget)
    widget.close()
    qt_app.processEvents()


def wait_for_idle(window, timeout=45):
    deadline = time.monotonic() + timeout
    while window.controller.running and time.monotonic() < deadline:
        QTest.qWait(20)
    assert not window.controller.running, "Actual backend worker did not finish before the timeout"


def test_gui_window_has_seven_working_pages(window):
    assert window.navigation.count() == 7
    assert window.pages.count() == 7
    for index in range(7):
        window.navigation.setCurrentRow(index)
        assert window.pages.currentIndex() == index
    assert window.train_page.start_button.isEnabled()
    assert not window.train_page.cancel_button.isEnabled()
    assert not window.train_page.export_button.isEnabled()
    assert window.optimize_page.algorithm_combo.count() == 4
    assert "rac_hpo" in [window.optimize_page.algorithm_combo.itemData(index) for index in range(4)]
    assert window.optimize_page.chart.values == []
    assert window.compare_page.history_table.rowCount() == 0


def test_gui_theme_has_real_text_glyphs(qt_app):
    assert QFontDatabase.families(), "The offscreen platform did not load any installed font"
    font = QRawFont.fromFont(qt_app.font())
    assert font.supportsCharacter("A"), "UI text must contain real glyphs instead of empty squares"
    chinese_families = QFontDatabase.families(QFontDatabase.WritingSystem.SimplifiedChinese)
    assert chinese_families, "UI requires an installed font with Simplified Chinese glyphs"
    chinese_font = QRawFont.fromFont(QFont(chinese_families[0], 10))
    assert chinese_font.supportsCharacter("中")


def test_gui_imports_real_dataset_in_background(window):
    failures = []
    window.controller.failed.connect(lambda message, trace: failures.append((message, trace)))
    source = PROJECT_ROOT / "datasets/raw/steel_energy/Steel_industry_data.csv"
    assert source.is_file(), "Download and verify the real UCI Steel dataset before integration tests"
    window.import_dataset(str(source))
    assert window.controller.running
    assert not window.train_page.start_button.isEnabled()
    with pytest.raises(RuntimeError, match="already running"):
        window.controller.start("prepare", path=str(source))
    wait_for_idle(window)
    assert not failures
    assert window.latest_result["row_count"] == 35040
    assert len(window.latest_result["source_sha256"]) == 64
    assert window.latest_result["split_counts"]["test"] > 0
    assert window.data_path == str(source)
    assert "35040" in window.dataset_badge.text()
    assert window.data_page.regime_table.rowCount() > 0
    assert window.train_page.start_button.isEnabled()


def test_gui_reports_actual_backend_errors(window):
    window.import_dataset(str(window.root / "missing-industrial-data.csv"))
    wait_for_idle(window)
    assert window.latest_result is None
    assert window.task_label.objectName() == "error"
    assert "任务失败" in window.task_label.text()
    assert "task_failed" in window.logs_page.view.toPlainText()
    assert window.train_page.start_button.isEnabled()


def test_gui_real_baseline_search_and_export(window, tmp_path):
    source = PROJECT_ROOT / "datasets/raw/steel_energy/Steel_industry_data.csv"
    assert source.is_file()
    window.data_path = str(source)
    overrides = {
        "model": {"n_estimators": 10, "n_jobs": 1},
        "optimization": {"max_trials": 2, "timeout_seconds": 30},
    }
    window.start_experiment("baseline", overrides)
    wait_for_idle(window)
    baseline = window.latest_result
    assert baseline["status"] == "completed", baseline
    assert baseline["metrics"]["overall_mae"] > 0
    assert window.train_page.export_button.isEnabled()
    exported = window.export_experiment(baseline["id"], str(tmp_path / "exports"))
    assert (Path(exported) / "experiment.json").is_file()
    assert (Path(exported) / "model.txt").is_file()
    window.start_experiment("tpe_robust", overrides)
    wait_for_idle(window)
    result = window.latest_result
    assert result["status"] == "completed", result
    search_trials = [trial for trial in result["trials"] if trial["number"] >= 0]
    assert len(search_trials) == 2
    assert window.optimize_page.chart.values == [trial["objective"] for trial in search_trials]
    assert window.optimize_page.trial_table.rowCount() == len(search_trials)
    assert window.compare_page.history_table.rowCount() == 2


def test_gui_cnc_chooser_runs_real_rac_and_displays_diagnostics(window):
    source = PROJECT_ROOT / "datasets/raw/cnc_milling_2025/FeatureAndMetadata_Milling.csv"
    assert source.exists()
    assert window.data_page.dataset_combo.count() == 2
    window.data_page.dataset_combo.setCurrentIndex(1)
    assert "cnc_milling_2025" in window.data_page.path_edit.text()
    window.import_dataset(str(source))
    wait_for_idle(window)
    assert window.latest_result["row_count"] == 968
    assert window.latest_result["manifest"]["independent_batch_count"] == 14
    index = window.optimize_page.algorithm_combo.findData("rac_hpo")
    window.optimize_page.algorithm_combo.setCurrentIndex(index)
    assert window.optimize_page.trials_spin.value() >= 32
    window.start_experiment("rac_hpo", {"optimization": {"max_trials": 24, "timeout_seconds": 30}})
    wait_for_idle(window)
    result = window.latest_result
    assert result["status"] == "completed", result.get("failure_reason")
    assert result["search_diagnostics"]["decision_counts"].get("rac_acquisition", 0) > 0
    assert "search_diagnostics" in window.optimize_page.params_view.toPlainText()
    assert window.optimize_page.trial_table.rowCount() == 24


def test_worker_receives_terminal_event_when_process_exits(qt_app, tmp_path):
    """Exercise the queue/exit race, without substituting any training results."""
    class EventQueue(queue.Queue):
        def close(self):
            pass

    events = EventQueue()

    class FinishingProcess:
        exitcode = 0

        def is_alive(self):
            events.put({"type": "result", "result": {"worker_protocol": "finished"}})
            return False

        def join(self):
            pass

        def close(self):
            pass

    controller = TaskController(tmp_path)
    controller._events = events
    controller._process = FinishingProcess()
    controller.action = "prepare"
    completed = []
    errors = []
    controller.finished.connect(lambda action, result: completed.append((action, result)))
    controller.failed.connect(lambda message, trace: errors.append(message))
    controller._poll()
    assert not errors
    assert completed == [("prepare", {"worker_protocol": "finished"})]


def test_gui_cancellation_is_confirmed_by_real_worker(window):
    source = PROJECT_ROOT / "datasets/raw/steel_energy/Steel_industry_data.csv"
    assert source.is_file()
    window.data_path = str(source)
    cancellation = []

    def cancel_after_real_trial(event):
        if event.get("type") == "trial_completed" and not cancellation:
            window.controller.cancel()
            cancellation.append({
                "running_when_requested": window.controller.running,
                "status_when_requested": window.task_label.text(),
                "start_enabled": window.optimize_page.start_button.isEnabled(),
            })

    window.controller.progress.connect(cancel_after_real_trial)
    window.start_experiment("tpe", {
        "model": {"n_estimators": 300, "n_jobs": 1},
        "optimization": {"max_trials": 1000, "timeout_seconds": 60},
    })
    wait_for_idle(window)
    assert cancellation
    assert cancellation[0]["running_when_requested"]
    assert "已请求取消" in cancellation[0]["status_when_requested"]
    assert not cancellation[0]["start_enabled"]
    result = window.latest_result
    assert result["status"] == "cancelled", result
    assert any(trial["number"] >= 0 for trial in result["trials"])
    assert window.service.get_experiment(result["id"])["status"] == "cancelled"
    assert window.optimize_page.start_button.isEnabled()
    assert window.controller._process is None
