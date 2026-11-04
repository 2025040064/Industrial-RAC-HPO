import os
from pathlib import Path
import shutil
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import pytest

from rac_hpo.interfaces.gui.main_window import MainWindow

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    (tmp_path/'configs').mkdir()
    shutil.copy2(ROOT/'configs/default.yaml', tmp_path/'configs/default.yaml')
    widget = MainWindow(tmp_path)
    widget.show()
    yield widget
    if widget.controller.running:
        widget.controller.cancel()
        deadline = time.monotonic()+30
        while widget.controller.running and time.monotonic()<deadline:
            QTest.qWait(20)
    widget.close()
    app.processEvents()


def test_loop_page_authorization_and_selection(window):
    page = window.loop_page
    assert not page.start_button.isEnabled()
    page.authorize_check.setChecked(True)
    assert page.start_button.isEnabled()
    window.navigation.setCurrentRow(5)
    assert window.pages.currentWidget() is page
    assert not page.promote_button.isEnabled()
    assert not page.rollback_button.isEnabled()
    assert '智训引擎' in window.windowTitle()


def test_loop_real_worker_and_history_isolation(window):
    source = ROOT/'datasets/raw/cnc_milling_2025/FeatureAndMetadata_Milling.csv'
    page = window.loop_page
    page.path_edit.setText(str(source))
    page.authorize_check.setChecked(True)
    page.trials_spin.setValue(2)
    page.demo_check.setChecked(True)
    errors = []
    window.controller.failed.connect(lambda message, trace: errors.append(message))
    page.start_button.click()
    assert window.controller.running
    assert not window.train_page.start_button.isEnabled()
    assert window.active_experiment_id is None
    deadline = time.monotonic()+45
    while window.controller.running and time.monotonic()<deadline:
        QTest.qWait(20)
    assert not window.controller.running
    assert not errors
    assert page.snapshot['state'] in {'WAITING_RELEASE', 'COMPLETED'}
    assert page.snapshot['candidate']
    assert window.active_experiment_id is None
    assert window.loop_active_session_id == page.snapshot['id']
    assert page.history_combo.count() >= 1
    assert page.timeline.toPlainText()


def test_loop_progress_and_terminal_do_not_replace_viewed_history(window):
    source = ROOT/'datasets/raw/cnc_milling_2025/FeatureAndMetadata_Milling.csv'
    viewed = window.loop_service.create_session(source)
    active = window.loop_service.create_session(source)
    window.loop_page.show_session(viewed)
    window.loop_active_session_id = active['id']
    window._active_task_kind = 'loop'
    window.controller.action = 'loop_run'
    window._progress({'type': 'loop_event', 'session_id': active['id'], 'state': 'MONITORING'})
    window._refresh_active_loop()
    assert window.loop_page.snapshot['id'] == viewed['id']
    window._finished('loop_run', active)
    assert window.loop_page.snapshot['id'] == viewed['id']
    assert window.active_experiment_id is None
    window.return_to_active()
    assert window.loop_page.snapshot['id'] == active['id']
    assert window.navigation.currentRow() == 5
