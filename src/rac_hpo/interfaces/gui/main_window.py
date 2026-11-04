"""Local experiment workspace; all backend access goes through application services."""

from copy import deepcopy
import json
import multiprocessing
import sys
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QTimer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QProgressBar, QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from rac_hpo.application.experiment_service import ApplicationService
from rac_hpo.application.loop_service import LoopService
from rac_hpo.application.industrial_service import IndustrialService
from rac_hpo import __version__

from .pages.compare_page import ComparePage
from .pages.data_page import DataPage
from .pages.logs_page import LogsPage
from .pages.loop_page import LoopPage
from .pages.industrial_page import IndustrialPage
from .pages.optimize_page import OptimizePage
from .pages.train_page import TrainPage
from .sidebar import RAIL_WIDTH, NavigationRail, build_sidebar_navigation
from .theme import apply_theme
from .widgets import WheelGuard, secondary
from .workspace_widgets import ElidedLabel
from .workspace_state import completed_trials, objective_value, status_label
from .workers import TaskController


class MainWindow(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root).resolve()
        self.service = ApplicationService(self.root)
        self.loop_service = LoopService(self.root)
        self.industrial_service = IndustrialService(self.root)
        self.industrial_active_run_id = None
        self.loop_active_session_id = None
        self._active_task_kind = 'experiment'
        self._loop_refresh_timer = QTimer(self)
        self._loop_refresh_timer.setSingleShot(True)
        self._loop_refresh_timer.setInterval(80)
        self._loop_refresh_timer.timeout.connect(self._refresh_active_loop)
        self.controller = TaskController(self.root, self)
        self.data_path = None
        self._imported_dataset = None
        self._imported_row_count = None
        self.active_algorithm = None
        self.latest_result = None
        self._closing = False
        self._cancelling = False
        self._completed_trials = []
        self._snapshots = {}
        self.active_experiment_id = None
        self._dirty_ids = set()
        self._startup_history_loaded = False
        self._elapsed = QElapsedTimer()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(80)
        self._render_timer.timeout.connect(self._flush_snapshots)
        self.setWindowTitle("智训引擎 · 工业模型训练与超参数优化")
        self.resize(1280, 880)
        self.setMinimumSize(720, 560)
        central = QWidget()
        central.setObjectName("workspace")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        topbar = QWidget()
        topbar.setObjectName("topbar")
        top_layout = QHBoxLayout(topbar)
        topbar.setFixedHeight(56)
        top_layout.setContentsMargins(16, 4, 16, 4)
        brand = QLabel("智训引擎")
        brand.setObjectName("brand")
        top_layout.addWidget(brand)
        self.description = ElidedLabel("LightGBM · 实验工作区")
        self.description.setWordWrap(False)
        top_layout.addWidget(self.description,1)
        top_layout.addStretch()
        self.dataset_badge = ElidedLabel("尚未导入数据")
        self.dataset_badge.setObjectName("badge")
        self.dataset_badge.setMinimumWidth(0)
        self.dataset_badge.setMaximumWidth(320)
        self.dataset_badge.setMinimumWidth(0)
        self.dataset_badge.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        top_layout.addWidget(self.dataset_badge)
        top_layout.addWidget(secondary("本地工作区"))
        outer.addWidget(topbar)
        body = QWidget()
        body.setObjectName("bodyHost")
        body_layout = QHBoxLayout(body)
        # The rail overlays the page, so the content keeps a fixed 56px gutter
        # and never reflows while the panel opens or closes.
        body_layout.setContentsMargins(RAIL_WIDTH, 0, 0, 0)
        body_layout.setSpacing(0)
        content = QVBoxLayout()
        content.setSpacing(0)
        self.task_bar = QWidget()
        task_layout = QHBoxLayout(self.task_bar)
        task_layout.setContentsMargins(24, 8, 24, 8)
        self.task_label = QLabel("就绪")
        self.task_label.setWordWrap(True)
        task_layout.addWidget(self.task_label, 1)
        self.view_active_button = QPushButton("查看当前任务")
        self.view_active_button.clicked.connect(self.return_to_active)
        self.view_active_button.setEnabled(False)
        task_layout.addWidget(self.view_active_button)
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.controller.cancel)
        task_layout.addWidget(self.cancel_button)
        content.addWidget(self.task_bar)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        content.addWidget(self.progress_bar)
        self.pages = QStackedWidget()
        self.data_page = DataPage()
        self.train_page = TrainPage()
        self.optimize_page = OptimizePage()
        self.compare_page = ComparePage()
        self.logs_page = LogsPage()
        self.loop_page = LoopPage()
        self.industrial_page = IndustrialPage()
        from rac_hpo.data.registry import DEFAULT_PATHS
        self.loop_page.path_edit.setText(str(self.root / DEFAULT_PATHS['cnc_milling_2025']))
        for page in (self.data_page, self.train_page, self.optimize_page, self.compare_page, self.logs_page, self.loop_page, self.industrial_page):
            self.pages.addWidget(page)
        content.addWidget(self.pages, 1)
        body_layout.addLayout(content, 1)
        outer.addWidget(body, 1)

        self.sidebar = NavigationRail(body, footer_text=f"LightGBM · Optuna\nApp {__version__}")
        self.navigation = self.sidebar.navigation
        build_sidebar_navigation(
            self.sidebar, ("数据管理", "模型训练", "超参数优化", "实验对比", "运行日志", "自主优化", "工业训练")
        )
        self.sidebar.raise_()

        self.statusBar().showMessage(f"工作区：{self.root}")
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.currentRowChanged.connect(self._update_context)
        self.compare_page.history_table.record_selected.connect(lambda record:self._update_context())
        # Start on 数据管理: the workflow begins with a verified dataset, not with a search.
        self.navigation.setCurrentRow(0)
        self.data_page.import_requested.connect(self.import_dataset)
        self.train_page.start_requested.connect(lambda overrides: self.start_experiment("baseline", overrides))
        self.optimize_page.start_requested.connect(self.start_experiment)
        self.train_page.cancel_requested.connect(self.controller.cancel)
        self.optimize_page.cancel_requested.connect(self.controller.cancel)
        self.train_page.export_requested.connect(self.export_experiment)
        self.optimize_page.export_requested.connect(self.export_experiment)
        self.optimize_page.history_requested.connect(self.open_workspace)
        self.optimize_page.return_current_requested.connect(self.return_to_active)
        self.compare_page.refresh_requested.connect(self.refresh_history)
        self.compare_page.detail_requested.connect(self.show_experiment)
        self.compare_page.export_requested.connect(self.export_experiment)
        self.compare_page.view_experiment_requested.connect(self.open_workspace)
        self.logs_page.export_requested.connect(self.export_logs)
        self.loop_page.operation_requested.connect(self.start_loop_operation)
        self.loop_page.refresh_requested.connect(self.refresh_loop_history)
        self.loop_page.session_selected.connect(self.show_loop_session)
        self.industrial_page.operation_requested.connect(self.start_industrial_operation)
        self.industrial_page.cancel_requested.connect(self.controller.cancel)
        self.industrial_page.refresh_requested.connect(self.refresh_industrial_history)
        self.industrial_page.run_selected.connect(self.show_industrial_run)
        self.industrial_page.compare_requested.connect(self.compare_industrial_runs)
        self.industrial_page.dataset_combo.currentIndexChanged.connect(self._update_context)
        self.controller.progress.connect(self._progress)
        self.controller.finished.connect(self._finished)
        self.controller.failed.connect(self._failed)
        self.controller.state_changed.connect(self._state_changed)
        self.logs_page.append("application_ready")
        self.refresh_history()
        self.refresh_loop_history()
        self.refresh_industrial_history()
        # Scrolling a long page must never edit the algorithm or the trial budget.
        self._wheel_guard = WheelGuard(self)
        for widget_type in (QSpinBox, QDoubleSpinBox, QComboBox):
            for widget in self.findChildren(widget_type):
                widget.installEventFilter(self._wheel_guard)

    def start_industrial_operation(self, operation, arguments):
        if self.controller.running:
            return
        self._active_task_kind = 'industrial'
        self.active_algorithm = None
        if operation == 'run':
            self.industrial_active_run_id = None
            self.view_active_button.setEnabled(False)
        self._start_task('industrial_' + operation, **arguments)

    def refresh_industrial_history(self):
        try:
            records = self.industrial_service.list_runs()
            self.industrial_page.set_history(records)
            if not self.industrial_page.snapshot and records:
                self.show_industrial_run(records[0]['id'])
        except Exception as exc:
            self.industrial_page.show_error(str(exc))
            self.logs_page.append(f'industrial_history_failed error={exc}')

    def show_industrial_run(self, identifier):
        try:
            self.industrial_page.show_result(self.industrial_service.get_run(identifier))
            self._update_context()
        except Exception as exc:
            self.industrial_page.show_error(str(exc))

    def compare_industrial_runs(self, left_id, right_id):
        try:
            self.industrial_page.show_comparison(self.industrial_service.get_run(left_id),
                                                 self.industrial_service.get_run(right_id))
        except Exception as exc:
            self.industrial_page.show_error(str(exc))

    def start_loop_operation(self, operation, arguments):
        if self.controller.running:
            return
        self._active_task_kind = 'loop'
        self.active_algorithm = None
        if operation == 'create':
            self.loop_active_session_id = None
        else:
            self.loop_active_session_id = arguments.get('identifier')
        self._start_task('loop_' + operation, **arguments)

    def refresh_loop_history(self):
        try:
            sessions = self.loop_service.list_sessions()
            self.loop_page.set_history(sessions)
            if not self.loop_page.snapshot and sessions:
                self.show_loop_session(sessions[0]['id'])
        except Exception as exc:
            self.loop_page.show_error(str(exc))

    def show_loop_session(self, identifier):
        try:
            self.loop_page.show_session(self.loop_service.get_session(identifier))
            self._update_context()
        except Exception as exc:
            self.loop_page.show_error(str(exc))

    def _refresh_active_loop(self):
        if self.loop_active_session_id and self.loop_page.snapshot.get('id') in (None, self.loop_active_session_id):
            self.show_loop_session(self.loop_active_session_id)

    def import_dataset(self, path=None):
        if self.controller.running:
            return
        self._pending_data_path = path
        self._active_task_kind = 'experiment'
        self.active_algorithm = None
        self.active_experiment_id = None
        self.view_active_button.setEnabled(False)
        self.optimize_page.set_active_experiment(None)
        self._start_task("prepare", path=path)

    def start_experiment(self, algorithm, overrides=None):
        if self.controller.running:
            return
        self.active_algorithm = algorithm
        self._active_task_kind = 'experiment'
        self.active_experiment_id = None
        self.optimize_page.set_active_experiment(None)
        self._completed_trials = []
        if algorithm != "baseline":
            self.optimize_page.reset_progress()
        else:
            self.train_page.reset_progress()
        self._start_task("run", algorithm=algorithm, data_path=self.data_path, overrides=overrides)

    def _start_task(self, action, **arguments):
        self.task_label.setObjectName("")
        self.task_label.style().unpolish(self.task_label)
        self.task_label.style().polish(self.task_label)
        self.logs_page.append(f"task_started action={action} algorithm={self.active_algorithm or 'data_validation'}")
        try:
            self.controller.start(action, **arguments)
        except Exception as exc:
            self._failed(str(exc), "")

    def _state_changed(self, state):
        busy = state != "idle"
        cancelling = state == "cancelling"
        self._cancelling = cancelling
        cancellable = busy and not cancelling and self.controller.action in {'run', 'loop_run', 'loop_create', 'industrial_run'}
        self.data_page.set_busy(busy)
        self.train_page.set_busy(busy, cancellable and self.controller.action == 'run' and self.active_algorithm == "baseline")
        self.optimize_page.set_busy(busy, cancellable and self.controller.action == 'run' and self.active_algorithm != "baseline")
        self.loop_page.set_busy(busy)
        self.industrial_page.set_busy(busy, cancellable and self.controller.action == 'industrial_run')
        self.cancel_button.setEnabled(cancellable)
        self.task_bar.show()
        self.progress_bar.setVisible(busy)
        self.optimize_page.set_task_state(state)
        if self.active_algorithm == "baseline":
            self.train_page.set_task_state(state)
        if busy and not self._elapsed_timer.isActive():
            self._elapsed.start()
            self._elapsed_timer.start()
        if not busy:
            self._elapsed_timer.stop()
        if cancelling:
            self.task_label.setText("已请求取消，等待当前训练安全结束并保存真实状态…")
            self.logs_page.append("cancellation_requested; waiting_for_backend_acknowledgement")
        elif busy:
            self.progress_bar.setRange(0, 0)
            labels = {'prepare': '正在校验真实数据…', 'industrial_audit': '正在审计工业数据与固定划分…',
                      'industrial_fetch': '正在显式获取公开工业数据…'}
            self.task_label.setText(labels.get(self.controller.action, '正在后台执行真实训练…'))

    def _progress(self, event):
        self.logs_page.append(json.dumps(event, ensure_ascii=False, default=str))
        if self.controller.action.startswith('industrial_'):
            if event.get('type') == 'started':
                self.industrial_active_run_id = event.get('run_id')
                self.view_active_button.setEnabled(bool(self.industrial_active_run_id))
                if self.industrial_page.snapshot.get('id') in (None, self.industrial_active_run_id):
                    self.show_industrial_run(self.industrial_active_run_id)
            self.industrial_page.append_progress(event)
            self.task_label.setText('工业训练 · ' + str(event.get('type', 'running')))
            return
        if self.controller.action.startswith('loop_'):
            if event.get('type') == 'loop_session_created':
                self.loop_active_session_id = event['session_id']
                self.view_active_button.setEnabled(True)
            self.task_label.setText('自主优化 · ' + str(event.get('state') or event.get('kind') or event.get('type')))
            if not self._loop_refresh_timer.isActive():
                self._loop_refresh_timer.start()
            return
        name = event.get("type", event.get("event", event.get("stage", "training")))
        if not self._cancelling:
            labels = {
                "started": "正在准备真实数据与默认基线…",
                "baseline_completed": "默认基线已完成，正在执行搜索…",
                "trial_completed": "已保存一次真实试验，继续检查预算…",
                "finished": "后端已完成，正在保存实验记录…",
                "cancelled": "后端已确认取消，正在保存实验记录…",
                "error": "后端报告训练错误，正在保存实验记录…",
            }
            self.task_label.setText(labels.get(name, str(event.get("message", name))))
        identifier = event.get("experiment_id", self.active_experiment_id)
        if not identifier:
            return
        if name in ("started", "baseline_completed"):
            try:
                snapshot = deepcopy(self.service.get_experiment(identifier))
                previous = self._snapshots.get(identifier, {})
                records = {trial["number"]: trial for trial in snapshot.get("trials", [])}
                records.update({trial["number"]: trial for trial in previous.get("trials", [])})
                snapshot["trials"] = sorted(records.values(), key=lambda trial: trial["number"])
                self._snapshots[identifier] = snapshot
            except Exception as exc:
                self.logs_page.append(f"snapshot_read_failed id={identifier} error={exc}")
        if name == "started":
            self.active_experiment_id = identifier
            self.view_active_button.setEnabled(True)
            if self.active_algorithm != "baseline":
                self.optimize_page.set_active_experiment(identifier)
                if identifier in self._snapshots:
                    self.optimize_page.show_result(self._snapshots[identifier], historical=False)
        snapshot = self._snapshots.get(identifier)
        if snapshot is None:
            return
        if name == "baseline_completed":
            snapshot["baseline_duration_seconds"] = event.get("duration_seconds")
            snapshot["baseline_metrics"] = deepcopy(event.get("metrics", {}))
        trial = event.get("trial")
        if isinstance(trial, dict):
            records = {item["number"]: item for item in snapshot.get("trials", [])}
            records[trial["number"]] = deepcopy(trial)
            snapshot["trials"] = sorted(records.values(), key=lambda item: item["number"])
        successful = completed_trials(snapshot.get("trials", []))
        if successful:
            best = min(successful, key=objective_value)
            snapshot.update(best_value=objective_value(best), best_trial=best["number"],
                            best_params=deepcopy(best.get("params", {})),
                            metrics=deepcopy(best.get("metrics", {})))
        if identifier == self.active_experiment_id:
            self._completed_trials = snapshot.get("trials", [])
            search_trials = [item for item in self._completed_trials if item.get("number", -1) >= 0]
            total = snapshot.get("config", {}).get("optimization", {}).get("max_trials")
            if total and self.active_algorithm != "baseline":
                self.progress_bar.setRange(0, int(total))
                self.progress_bar.setValue(len(search_trials))
        self._dirty_ids.add(identifier)
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _flush_snapshots(self):
        pending, self._dirty_ids = self._dirty_ids, set()
        for identifier in pending:
            snapshot = self._snapshots.get(identifier)
            if snapshot:
                self.compare_page.drawer.update_experiment(snapshot)
            if snapshot and snapshot.get("algorithm") != "baseline":
                self.optimize_page.update_snapshot(
                    snapshot, active=identifier == self.active_experiment_id,
                )

        self._update_context()

    def _tick_elapsed(self):
        if self.controller.running and self.controller.action == 'run' and self.active_algorithm != "baseline" and self._elapsed.isValid():
            self.optimize_page.set_elapsed(self._elapsed.elapsed() / 1000.0)

    def _finished(self, action, result):
        if action.startswith('industrial_'):
            if action == 'industrial_run':
                identifier = result.get('id')
                self.industrial_active_run_id = identifier
                if self.industrial_page.snapshot.get('id') in (None, identifier):
                    self.industrial_page.show_result(result)
                self.view_active_button.setEnabled(bool(identifier))
                self.task_label.setText(f"工业训练 {identifier} · {result.get('status', '')}")
                if result.get('status') == 'failed':
                    self._display_task_error(result.get('failure_reason') or '工业训练失败')
                self.refresh_industrial_history()
            else:
                self.industrial_page.show_audit(result)
                self.task_label.setText('工业数据获取与审计操作已完成')
            self.logs_page.append(f"industrial_finished action={action} status={result.get('status', 'validated')} id={result.get('id', '')}")
            self._update_context()
            if self._closing:
                QTimer.singleShot(0, self.close)
            return
        if action.startswith('loop_'):
            self._loop_refresh_timer.stop()
            if result.get('id'):
                self.loop_active_session_id = result['id']
                if self.loop_page.snapshot.get('id') in (None, result['id']):
                    self.loop_page.show_session(result)
                self.task_label.setText(f"自主优化 {result['id']} · {result['state']}")
                self.view_active_button.setEnabled(True)
            else:
                self.task_label.setText(f"会话已导出：{result.get('export_path', '')}")
            self.refresh_loop_history()
            self.refresh_history()
            self._update_context()
            if self._closing:
                QTimer.singleShot(0, self.close)
            return
        self.latest_result = result
        if action == "prepare":
            self.data_path = self._pending_data_path
            self._imported_dataset=result.get("dataset_id")
            self._imported_row_count=result.get("row_count")
            self.data_page.show_summary(result)
            self.dataset_badge.setText(f"{result.get('dataset_id', '')} · {result.get('row_count', '')} 条")
            self.dataset_badge.setToolTip(self.dataset_badge.text())
            self.optimize_page.set_data_context(result.get("dataset_id") or "已校验文件")
            message = "数据导入与校验完成"
            self.task_label.setText(message)
        else:
            identifier = result.get("id")
            self._snapshots[identifier] = deepcopy(result)
            self._dirty_ids.discard(identifier)
            self.compare_page.drawer.update_experiment(result)
            self.active_experiment_id = identifier
            self.view_active_button.setEnabled(bool(identifier))
            if self.active_algorithm == "baseline":
                self.train_page.show_result(result)
            else:
                self.optimize_page.update_snapshot(result, active=False)
                if self.optimize_page.experiment_id in (None, identifier):
                    self.optimize_page.show_result(result, historical=False)
            status = result.get("status", "unknown")
            message = f"实验 {result.get('id', '')} · {status}"
            self.task_label.setText(message)
            if status == "failed":
                self._display_task_error(result.get("failure_reason") or "后端报告实验失败")
            elif status == "cancelled":
                self.task_label.setText(f"实验已取消并保存：{identifier}")
            self.refresh_history()
        self._update_context()
        self.statusBar().showMessage(message)
        self.logs_page.append(f"task_finished action={action} status={result.get('status', 'validated')} id={result.get('id', '')}")
        if self._closing:
            QTimer.singleShot(0, self.close)

    def _failed(self, message, trace):
        if self.controller.action.startswith('industrial_'):
            self.industrial_page.show_error(message, trace)
            self._display_task_error(message)
            self.logs_page.append(f'industrial_operation_failed error={message}\n{trace}')
            self.refresh_industrial_history()
            if self._closing:
                QTimer.singleShot(0, self.close)
            return
        if self.controller.action.startswith('loop_'):
            self._loop_refresh_timer.stop()
            self._refresh_active_loop()
            self.loop_page.show_error(message)
            self._display_task_error(message)
            self.logs_page.append(f'loop_operation_failed error={message}\n{trace}')
            if self._closing:
                QTimer.singleShot(0, self.close)
            return
        identifier = self.active_experiment_id
        if identifier and identifier in self._snapshots:
            snapshot = self._snapshots[identifier]
            snapshot.update(status="failed", failure_reason=message)
            self._dirty_ids.discard(identifier)
            self.compare_page.drawer.update_experiment(snapshot)
            if self.active_algorithm != "baseline":
                self.optimize_page.update_snapshot(snapshot, active=False)
        if self.active_algorithm == "baseline":
            self.train_page.show_error(message)
        elif self.active_algorithm and self.optimize_page.experiment_id in (None, identifier):
            self.optimize_page.show_error(message)
        self._elapsed_timer.stop()
        self._display_task_error(message)
        self.logs_page.append(f"task_failed error={message}\n{trace}")
        self.refresh_history()
        if self._closing:
            QTimer.singleShot(0, self.close)

    def _display_task_error(self, message):
        self.task_bar.show()
        self.task_label.setObjectName("error")
        self.task_label.style().unpolish(self.task_label)
        self.task_label.style().polish(self.task_label)
        self.task_label.setText(f"任务失败：{message}")
        self.cancel_button.setEnabled(False)
        self.statusBar().showMessage(f"失败：{message}")

    def _operation_error(self, message):
        self.statusBar().showMessage(message)
        self.logs_page.append(f"operation_failed error={message}")
        if not self.controller.running:
            self.task_label.setText(message)

    def refresh_history(self):
        try:
            experiments = self.service.list_experiments()
            self.compare_page.show_experiments(experiments)
            self.optimize_page.set_history(experiments)
            self.train_page.set_baseline_count(
                sum(1 for item in experiments if item.get("algorithm") == "baseline")
            )
            if not self._startup_history_loaded:
                self._startup_history_loaded = True
                latest = next((item for item in sorted(
                    experiments, key=lambda item: item.get("created_at", ""), reverse=True,
                ) if item.get("algorithm") != "baseline"), None)
                if latest:
                    # Load the latest search so it is one click away, without stealing the landing page.
                    self.open_workspace(latest["id"], navigate=False)
        except Exception as exc:
            self.logs_page.append(f"history_read_failed error={exc}")
            self.statusBar().showMessage(f"读取历史实验失败：{exc}")

    def show_experiment(self, experiment_id):
        try:
            self.compare_page.show_detail(self.service.get_experiment(experiment_id))
        except Exception as exc:
            self._operation_error(f"读取实验失败：{exc}")

    def open_workspace(self, experiment_id, navigate=True):
        try:
            if experiment_id == self.active_experiment_id and experiment_id in self._snapshots:
                result = self._snapshots[experiment_id]
            else:
                result = self.service.get_experiment(experiment_id)
                self._snapshots[experiment_id] = deepcopy(result)
            if result.get("algorithm") == "baseline":
                self.train_page.show_result(result)
                if navigate:
                    self.navigation.setCurrentRow(1)
            else:
                active = experiment_id == self.active_experiment_id and self.controller.running
                self.optimize_page.show_result(result, historical=not active)
                if navigate:
                    self.navigation.setCurrentRow(2)
        except Exception as exc:
            self._operation_error(f"打开工作区失败：{exc}")
        self._update_context()

    def _update_context(self,*args):
        page=self.navigation.currentRow()
        if page == 6:
            result = self.industrial_page.snapshot
            self.description.setText(f"工业训练 · {result.get('model_name', '分类任务')} · {result.get('id', '尚无实验')}")
            self.dataset_badge.setText('分类 · ' + str(result.get('dataset_key') or self.industrial_page.dataset_combo.currentData()))
            return
        if page == 5:
            session = self.loop_page.snapshot
            self.description.setText(f"自主优化 · {session.get('id', '尚无会话')} · {session.get('state', '待开始')}")
            self.dataset_badge.setText('CNC · ' + session.get('data_mode', '离线协议'))
            return
        snapshot={}
        if page==2:snapshot=self.optimize_page._snapshot
        elif page==1 and self.train_page.experiment_id:
            snapshot=self._snapshots.get(self.train_page.experiment_id,{})
        elif page==3:
            snapshot=next((r for r in self.compare_page.experiments if r.get('id')==self.compare_page.experiment_id),{})
        if snapshot:
            model=(snapshot.get('config') or {}).get('model',{}).get('name') or '模型未记录'
            self.description.setText(f"{model} · {snapshot.get('id') or '—'} · {status_label(snapshot.get('status'))}")
            self.dataset_badge.setText('查看：'+str(snapshot.get('dataset_id') or '数据集未记录'))
        else:
            self.description.setText('LightGBM · '+self.navigation.currentItem().text() if self.navigation.currentItem() else '实验工作区')
            count=f' · {self._imported_row_count} 条' if self._imported_row_count is not None else ''
            self.dataset_badge.setText('新任务：'+str(self._imported_dataset or '项目默认数据')+count)

    def return_to_active(self):
        if self._active_task_kind == 'industrial' and self.industrial_active_run_id:
            self.show_industrial_run(self.industrial_active_run_id)
            self.navigation.setCurrentRow(6)
            return
        if self._active_task_kind == 'loop' and self.loop_active_session_id:
            self.show_loop_session(self.loop_active_session_id)
            self.navigation.setCurrentRow(5)
            return
        if self.active_experiment_id:
            self.open_workspace(self.active_experiment_id)

    def export_experiment(self, experiment_id, destination=None):
        if not experiment_id:
            return None
        if destination is None:
            destination = QFileDialog.getExistingDirectory(self, "选择实验导出目录", str(self.root / "workspace"))
        if not destination:
            return None
        try:
            path = self.service.export_results(experiment_id, destination)
            self.statusBar().showMessage(f"实验已导出：{path}")
            self.logs_page.append(f"experiment_exported id={experiment_id} path={path}")
            return path
        except Exception as exc:
            self._operation_error(f"导出实验失败：{exc}")
            return None

    def export_logs(self, text):
        path, _ = QFileDialog.getSaveFileName(self, "导出当前显示日志", str(self.root / "workspace" / "logs" / "gui-events.log"), "Log files (*.log)")
        if path:
            try:
                Path(path).write_text(text, encoding="utf-8")
                self.statusBar().showMessage(f"日志已导出：{path}")
            except OSError as exc:
                self._operation_error(f"导出日志失败：{exc}")

    def closeEvent(self, event):
        if self.controller.running:
            self._closing = True
            self.controller.cancel()
            self.task_label.setText("正在等待后台任务结束后关闭窗口…")
            event.ignore()
        else:
            event.accept()


def launch_gui(root):
    multiprocessing.freeze_support()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    apply_theme(app)
    window = MainWindow(root)
    window.show()
    return app.exec()
