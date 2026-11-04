"""GUI contracts use labelled fixtures; actual worker failures use the real service."""

from copy import deepcopy
import os
from pathlib import Path
import queue
import shutil
import threading
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rac_hpo.interfaces.gui.pages.industrial_page import IndustrialPage
from rac_hpo.interfaces.gui.workers import run_worker

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app):
    widget = IndustrialPage()
    yield widget
    widget.close()
    app.processEvents()


def display_fixture(identifier='UI-FIXTURE-A'):
    """Small presentation input, never persisted as an industrial experiment."""
    return {
        'id': identifier, 'dataset_key': 'ai4i_2020', 'task_type': 'classification',
        'model_name': 'random_forest', 'algorithm': 'random', 'status': 'completed',
        'data_sha256': 'ui-fixture-source', 'duration_seconds': 1.25,
        'manifest': {'version': 'ui-fixture', 'split_fingerprint': 'ui-fixture-split'},
        'config': {'seed': 42, 'max_trials': 24, 'timeout_seconds': 300, 'model_config': {'n_jobs': 1}},
        'metrics': {'overall_balanced_accuracy': .75, 'overall_f1_macro': .7,
                    'overall_log_loss': .5, 'regimes': {'type-L': {
                        'samples': 12, 'balanced_accuracy': .65, 'f1_macro': .6, 'log_loss': .55,
                        'minority_class_samples': 2, 'sparse_class_warning': 'UI fixture sparse warning',
                        'effective_independent_groups': None}}},
        'trials': [{'number': -1, 'status': 'completed', 'metrics': {'overall_balanced_accuracy': .5}},
                   {'number': 0, 'status': 'completed', 'objective': .25, 'duration_seconds': 1,
                    'metrics': {'overall_balanced_accuracy': .75}, 'params': {'max_depth': 3}}],
        'best_params': {'max_depth': 3}, 'best_trial': 0,
        'artifacts': {'model': 'ui-fixture-only.joblib'},
    }


def test_industrial_page_has_source_and_model_specific_controls(page):
    assert page.dataset_combo.count() == 6
    assert {page.model_combo.itemData(index) for index in range(3)} == {'random_forest', 'xgboost', 'lightgbm'}
    assert '合成' in page.source_note.text()
    assert not page.cancel_button.isEnabled()
    events = []
    page.operation_requested.connect(lambda operation, arguments: events.append((operation, arguments)))
    page.path_edit.setText('local-source.zip')
    page.audit_button.click()
    assert events[-1] == ('audit', {'dataset_key': 'ai4i_2020', 'path': 'local-source.zip'})
    page.start_button.click()
    assert events[-1][0] == 'run'
    assert events[-1][1]['data_path'] == 'local-source.zip'
    assert events[-1][1]['algorithm'] == 'baseline'
    assert events[-1][1]['seed'] == 42
    assert 'model_config' not in events[-1][1]
    page.decision_combo.setCurrentIndex(page.decision_combo.findData('time_oof'))
    page.start_button.click()
    assert events[-1][1]['model_config'] == {'decision_mode': 'time_oof'}
    page.set_busy(True, True)
    assert not page.start_button.isEnabled()
    assert not page.fetch_button.isEnabled()
    assert not page.decision_combo.isEnabled()
    assert page.cancel_button.isEnabled()


def test_industrial_classification_metrics_and_curve_keep_real_field_names(page):
    fixture = display_fixture()
    page.show_result(fixture)
    assert page.metrics.cards['balanced_accuracy'].value_label.text() == '0.75'
    assert page.metrics.cards['f1_macro'].value_label.text() == '0.7'
    assert page.metrics.cards['log_loss'].value_label.text() == '0.5'
    assert page.regime_table.rowCount() == 1
    assert page.regime_table.item(0, 0).text() == 'type-L'
    assert page.regime_table.item(0, 1).text() == '12'
    assert '薄弱验证工况：type-L' in page.weak_regime_label.text()
    assert '少数类=2' in page.weak_regime_label.text()
    assert '仅作描述' in page.weak_regime_label.text()
    assert page.trial_table.rowCount() == 2
    assert page.curve.points == [(0, .25)]
    assert 'overall_mae' not in page.details_view.toPlainText()
    assert 'ui-fixture-only.joblib' in page.details_view.toPlainText()
    assert 'classification_metrics' in page.details_view.toPlainText()
    assert 'minority_class_samples' in page.details_view.toPlainText()


def test_industrial_missing_metrics_remain_empty(page):
    page.show_result({'id': 'UI-EMPTY', 'status': 'failed', 'failure_reason': 'UI fixture failure'})
    assert page.metrics.cards['balanced_accuracy'].value_label.text() == '—'
    assert not page.curve.points
    assert page.regime_table.rowCount() == 0
    assert page.failure_label.text() == 'UI fixture failure'
    page.show_error('UI fixture worker failure', 'traceback marker')
    assert 'traceback marker' in page.log_view.toPlainText()


def test_industrial_training_curve_and_saved_log_use_persisted_values(page):
    fixture = display_fixture()
    fixture['metrics']['learning_curve'] = [
        {'iteration': 1, 'train_loss': .8, 'validation_loss': .9},
        {'iteration': 2, 'train_loss': .6, 'validation_loss': .7},
    ]
    fixture['log_text'] = 'saved industrial experiment log'
    page.show_result(fixture)
    assert page.learning_curve.points == [(1, .9), (2, .7)]
    assert page.learning_curve.train_points == [(1, .8), (2, .6)]
    assert page.log_view.toPlainText() == 'saved industrial experiment log'
    page.append_progress({'type': 'trial_completed', 'run_id': fixture['id'],
                          'trial': {'number': 1, 'status': 'completed', 'metrics': {}}})
    assert 'trial_completed' in page.log_view.toPlainText()
    page.show_result({'id': 'UI-RF', 'metrics': {'learning_curve': [],
                     'learning_curve_reason': 'Random Forest has no boosting iterations'}})
    assert page.learning_curve.points == []
    assert 'Random Forest' in page.learning_curve.empty_reason
    assert page.log_view.toPlainText() == ''


def test_industrial_late_progress_preserves_selected_history(page):
    page.show_result(display_fixture('UI-VIEWED-HISTORY'))
    page.append_progress({'type': 'started', 'run_id': 'UI-ACTIVE'})
    page.append_progress({'type': 'trial_completed', 'run_id': 'UI-ACTIVE',
                          'trial': {'number': 1, 'metrics': {'overall_balanced_accuracy': .9}}})
    assert page.active_run_id == 'UI-ACTIVE'
    assert page.snapshot['id'] == 'UI-VIEWED-HISTORY'
    assert len(page.snapshot['trials']) == 2
    assert page.curve.points == [(0, .25)]


def test_industrial_comparison_requires_split_and_resource_evidence(page):
    left, right = display_fixture(), display_fixture('UI-FIXTURE-B')
    page.show_comparison(left, right)
    assert '搜索预算一致' in page.compare_note.text()
    right['manifest']['split_fingerprint'] = 'different-split'
    page.show_comparison(left, right)
    assert '不排名' in page.compare_note.text()
    right = deepcopy(left)
    right['config']['model_config'] = {}
    page.show_comparison(left, right)
    assert '不排名' in page.compare_note.text()
    right = deepcopy(left)
    right['status'] = 'failed'
    page.show_comparison(left, right)
    assert '不排名' in page.compare_note.text()
    assert page.compare_table.rowCount() > 5


def test_industrial_worker_does_not_create_regression_database(tmp_path):
    events = queue.Queue()
    run_worker(tmp_path, 'industrial_audit', {'dataset_key': 'ai4i_2020',
               'path': str(tmp_path / 'missing.csv')}, events, threading.Event())
    event = events.get_nowait()
    assert event['type'] == 'error'
    assert 'missing.csv' in event['message']
    assert not (tmp_path / 'workspace/database/experiments.sqlite3').exists()


def test_industrial_worker_reports_real_missing_data_and_keeps_old_pages(app, tmp_path):
    from rac_hpo.interfaces.gui.main_window import MainWindow
    (tmp_path / 'configs').mkdir()
    shutil.copy2(ROOT / 'configs/default.yaml', tmp_path / 'configs/default.yaml')
    window = MainWindow(tmp_path)
    try:
        assert window.navigation.count() == 7
        window.navigation.setCurrentRow(6)
        assert window.pages.currentWidget() is window.industrial_page
        assert window.pages.widget(5) is window.loop_page
        errors = []
        window.controller.failed.connect(lambda message, trace: errors.append((message, trace)))
        window.start_industrial_operation('audit', {'dataset_key': 'ai4i_2020',
                                                   'path': str(tmp_path / 'missing.csv')})
        assert window.controller.running
        assert not window.train_page.start_button.isEnabled()
        deadline = time.monotonic() + 30
        while window.controller.running and time.monotonic() < deadline:
            QTest.qWait(20)
        assert not window.controller.running
        assert errors
        assert 'missing.csv' in errors[0][0], errors
        assert window.industrial_page.failure_label.text()
        assert 'industrial_operation_failed' in window.industrial_page.log_view.toPlainText()
        assert window.task_label.objectName() == 'error'
        assert window.active_experiment_id is None
        assert window.train_page.start_button.isEnabled()
    finally:
        if window.controller.running:
            window.controller.cancel()
            deadline = time.monotonic() + 30
            while window.controller.running and time.monotonic() < deadline:
                QTest.qWait(20)
        window.close()
        app.processEvents()


def test_industrial_main_window_keeps_history_separate_from_active_task(app, tmp_path, monkeypatch):
    from rac_hpo.interfaces.gui.main_window import MainWindow
    (tmp_path / 'configs').mkdir()
    shutil.copy2(ROOT / 'configs/default.yaml', tmp_path / 'configs/default.yaml')
    window = MainWindow(tmp_path)
    viewed, active = display_fixture('UI-HISTORY'), display_fixture('UI-ACTIVE')
    records = {record['id']: record for record in (viewed, active)}
    monkeypatch.setattr(window.industrial_service, 'get_run', lambda identifier: records[identifier])
    monkeypatch.setattr(window.industrial_service, 'list_runs', lambda: list(records.values()))
    try:
        window.show_industrial_run(viewed['id'])
        window.controller.action = 'industrial_run'
        window._active_task_kind = 'industrial'
        window._progress({'type': 'started', 'run_id': active['id']})
        window._progress({'type': 'trial_completed', 'run_id': active['id'],
                          'trial': {'number': 5, 'metrics': {'overall_balanced_accuracy': .99}}})
        assert window.industrial_page.snapshot['id'] == viewed['id']
        window._finished('industrial_run', active)
        assert window.industrial_page.snapshot['id'] == viewed['id']
        assert window.active_experiment_id is None
        assert not window._snapshots
        window.return_to_active()
        assert window.industrial_page.snapshot['id'] == active['id']
        assert window.navigation.currentRow() == 6
    finally:
        window.close()
        app.processEvents()
