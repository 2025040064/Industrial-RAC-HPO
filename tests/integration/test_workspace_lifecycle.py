"""Presentation lifecycle boundaries; fixture records are never production results."""

import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from rac_hpo.application.experiment_service import ApplicationService
from rac_hpo.interfaces.gui.main_window import MainWindow
from rac_hpo.interfaces.gui.theme import apply_theme


ROOT = Path(__file__).resolve().parents[2]


def snapshot(identifier, status="completed", algorithm="tpe", created="2026-10-30T01:00:00Z"):
    return {
        "id": identifier, "status": status, "algorithm": algorithm, "created_at": created,
        "dataset_id": "unit_test_only", "target_unit": "cycles", "duration_seconds": 2.5,
        "best_value": None, "best_params": {}, "metrics": {}, "trials": [],
        "config": {"model": {"name": "lightgbm"}, "optimization": {"max_trials": 12}},
    }


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    (tmp_path / "configs").mkdir()
    shutil.copy2(ROOT / "configs/default.yaml", tmp_path / "configs/default.yaml")
    widget = MainWindow(tmp_path)
    yield widget
    widget.close()
    app.processEvents()


def test_failed_result_received_via_finished_remains_visible(window):
    result = snapshot("failed-service", "failed")
    result["failure_reason"] = "No successful trial"
    window.active_algorithm = "tpe"
    window._finished("run", result)
    assert window.task_label.objectName() == "error"
    assert "No successful trial" in window.task_label.text()
    assert not window.cancel_button.isEnabled()


def test_startup_opens_latest_search_including_failed(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    (tmp_path / "configs").mkdir()
    shutil.copy2(ROOT / "configs/default.yaml", tmp_path / "configs/default.yaml")
    service = ApplicationService(tmp_path)
    for value in (
        snapshot("older-search"),
        snapshot("new-failed", "failed", created="2026-10-30T02:00:00Z"),
        snapshot("newest-baseline", algorithm="baseline", created="2026-10-30T03:00:00Z"),
    ):
        service.repository.save_experiment(value)
    widget = MainWindow(tmp_path)
    try:
        # Startup lands on 数据管理; the latest search stays loaded and one click away.
        assert widget.pages.currentIndex() == 0
        assert widget.optimize_page.experiment_id == "new-failed"
        assert not widget.controller.running
        assert not widget.cancel_button.isEnabled()
    finally:
        widget.close()


def test_history_does_not_change_new_run_inputs_and_live_events_do_not_mix(window, monkeypatch):
    old = snapshot("history")
    active = snapshot("active", "running")
    monkeypatch.setattr(window.service, "get_experiment", lambda key: dict({"history": old, "active": active}[key]))
    window.data_path = "current-data.csv"
    window.optimize_page.seed_spin.setValue(123)
    window.active_algorithm = "tpe"
    window._progress({"type": "started", "experiment_id": "active"})
    window.open_workspace("history")
    window._progress({"type": "trial_completed", "experiment_id": "active", "trial": {
        "number": 0, "status": "completed", "objective": 7.0,
        "metrics": {"overall_mae": 7.0}, "params": {"learning_rate": 0.1},
    }})
    assert window.optimize_page.experiment_id == "history"
    assert window.optimize_page.trials == []
    assert window.data_path == "current-data.csv"
    assert window.optimize_page.seed_spin.value() == 123
    window.return_to_active()
    assert window.optimize_page.experiment_id == "active"
    assert len(window.optimize_page.trials) == 1
    assert window.optimize_page.trials[0]["number"] == 0


def test_duplicate_events_are_deduplicated_and_baseline_not_progress(window, monkeypatch):
    active = snapshot("active", "running")
    active["trials"] = [{"number": -1, "status": "completed", "objective": 99.0}]
    monkeypatch.setattr(window.service, "get_experiment", lambda key: active)
    window.active_algorithm = "tpe"
    window._progress({"type": "started", "experiment_id": "active"})
    event = {"type": "trial_completed", "experiment_id": "active", "trial": {
        "number": 3, "status": "failed", "objective": None, "params": {},
    }}
    window._progress(event)
    window._progress(event)
    assert len(window._snapshots["active"]["trials"]) == 2
    assert window.progress_bar.value() == 1


def test_failed_import_does_not_relabel_previous_completed_experiment(window, monkeypatch):
    previous = snapshot("completed-search")
    window._snapshots[previous["id"]] = previous
    window.active_experiment_id = previous["id"]
    window.active_algorithm = "tpe"
    monkeypatch.setattr(window.controller, "start", lambda *args, **kwargs: None)
    window.import_dataset("missing.csv")
    window._failed("Missing data file", "")
    assert window._snapshots[previous["id"]]["status"] == "completed"


def test_prepare_success_updates_global_task_message(window):
    window._pending_data_path = "validated.csv"
    window.task_label.setText("正在校验真实数据…")
    window._finished("prepare", {"dataset_id": "test-only", "row_count": 3})
    assert window.task_label.text() == "数据导入与校验完成"


def test_delayed_render_does_not_restore_running_after_terminal_result(window, monkeypatch):
    active = snapshot("active", "running")
    monkeypatch.setattr(window.service, "get_experiment", lambda key: active)
    window.active_algorithm = "tpe"
    window._progress({"type": "started", "experiment_id": "active"})
    final = snapshot("active", "cancelled")
    window._finished("run", final)
    window._flush_snapshots()
    assert window._snapshots["active"]["status"] == "cancelled"
    assert window.optimize_page.metrics.cards["status"].value_label.text() == "已取消"


def test_worker_failure_does_not_replace_viewed_history(window, monkeypatch):
    old = snapshot("history")
    active = snapshot("active", "running")
    monkeypatch.setattr(window.service, "get_experiment", lambda key: {"history": old, "active": active}[key])
    window.active_algorithm = "tpe"
    window._progress({"type": "started", "experiment_id": "active"})
    window.open_workspace("history")
    before = window.optimize_page.result_label.text()
    window._failed("Worker crashed", "test-only traceback")
    assert window._snapshots["active"]["status"] == "failed"
    assert window._snapshots["history"]["status"] == "completed"
    assert window.optimize_page.experiment_id == "history"
    assert window.optimize_page.result_label.text() == before


def test_open_history_drawer_receives_terminal_snapshot(window):
    window.show()
    window.navigation.setCurrentRow(3)
    window.active_algorithm = "tpe"
    window.compare_page.show_detail(snapshot("active", "running"))
    window._finished("run", snapshot("active", "completed"))
    assert window.compare_page.drawer._experiment["status"] == "completed"


def test_live_snapshot_uses_recorded_baseline_time_and_best_trial_metrics(window, monkeypatch):
    active = snapshot("active", "running", "tpe_robust")
    monkeypatch.setattr(window.service, "get_experiment", lambda key: active)
    window.active_algorithm = "tpe_robust"
    window._progress({"type": "started", "experiment_id": "active"})
    window._progress({"type": "baseline_completed", "experiment_id": "active",
                      "duration_seconds": 3.2, "metrics": {"overall_mae": 99.0}})
    trial = {"number": 0, "status": "completed", "objective": 0.7,
             "metrics": {"overall_mae": 8.0}, "params": {"num_leaves": 16}}
    window._progress({"type": "trial_completed", "experiment_id": "active", "trial": trial})
    current = window._snapshots["active"]
    assert current.get("baseline_duration_seconds") == 3.2
    assert current["best_value"] == 0.7
    assert current["metrics"]["overall_mae"] == 8.0
    assert current["best_params"] == {"num_leaves": 16}
