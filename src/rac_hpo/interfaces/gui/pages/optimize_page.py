"""Experiment workspace; receives real snapshots from the application shell."""
import copy
import json
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QDoubleSpinBox, QVBoxLayout, QWidget
from ..charts import ExperimentChart
from ..parallel_coordinates import ParallelCoordinates
from ..workbench_widgets import ResponsiveWorkspace, ComparisonPanel
from ..widgets import card, format_value, secondary
from ..workspace_state import completed_trials, objective_label, objective_value, search_trials, status_label, WorkspaceViewState, filtered_trial_ids, trial_view_records, finite_value, display_time
from ..workspace_widgets import CollapsiblePanel, MetricsGrid, PanelGrid, RecordTable, RunDetailDrawer, WorkspaceHeader

class ChartPanel(QFrame):
    maximize_requested = Signal(str)

    def __init__(self, title, kind, parameter=False, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setObjectName('card')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName('cardTitle')
        header.addWidget(self.title_label, 1)
        self.maximize_button = QPushButton('放大')
        self.maximize_button.setToolTip(f'最大化查看{title}')
        self.maximize_button.clicked.connect(lambda: self.maximize_requested.emit(kind))
        header.addWidget(self.maximize_button)
        layout.addLayout(header)
        self.parameter_combo = QComboBox() if parameter else None
        if self.parameter_combo is not None:
            self.parameter_combo.setMinimumWidth(0)
            self.parameter_combo.setAccessibleName('选择真实搜索超参数')
            layout.addWidget(self.parameter_combo)
        self.chart = ExperimentChart(kind)
        layout.addWidget(self.chart)

class OptimizePage(QWidget):
    start_requested = Signal(str, dict)
    cancel_requested = Signal()
    export_requested = Signal(str)
    history_requested = Signal(str)
    return_current_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.trials = []
        self.experiment_id = None
        self.active_experiment_id = None
        self._snapshot = {}
        self._snapshots = {}
        self._historical = False
        self._task_state = 'idle'
        self._elapsed_seconds = None
        self._maximized = []
        self.view_state = WorkspaceViewState()
        self._view_states = {}
        self._changing_context = False
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setMinimumWidth(0)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.header = WorkspaceHeader('超参数优化', '固定数据划分与真实训练 · 目标越小越好')
        self.return_button = QPushButton('返回当前任务')
        self.return_button.clicked.connect(self.return_current_requested)
        self.return_button.hide()
        self.export_button = QPushButton('导出实验')
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        self.header.actions.addWidget(self.return_button)
        self.header.actions.addWidget(self.export_button)
        layout.addWidget(self.header)
        history_row = QHBoxLayout()
        history_row.addWidget(secondary('历史搜索'))
        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(0)
        self.history_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.history_combo.setAccessibleName('选择历史搜索实验')
        self.history_combo.addItem('暂无历史搜索', None)
        self.history_combo.currentIndexChanged.connect(self._history_selected)
        history_row.addWidget(self.history_combo, 1)
        layout.addLayout(history_row)
        self.metrics = MetricsGrid([('best', '最佳搜索目标'), ('mae', '最佳验证 MAE'), ('trials', '已保存搜索试验'), ('status', '任务状态')])
        layout.addWidget(self.metrics)
        elapsed_row = QHBoxLayout()
        self.elapsed_caption = QLabel('实验总耗时')
        self.elapsed_value = QLabel('—')
        elapsed_row.addWidget(self.elapsed_caption)
        elapsed_row.addWidget(self.elapsed_value)
        elapsed_row.addStretch()
        layout.addLayout(elapsed_row)
        self.config_panel = CollapsiblePanel('搜索配置')
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        self.algorithm_combo = QComboBox()
        for name, algorithm in (('Optuna TPE', 'tpe'), ('Random Search', 'random'), ('TPE + 固定鲁棒目标', 'tpe_robust'), ('RAC-HPO · 工况与成本', 'rac_hpo')):
            self.algorithm_combo.addItem(name, algorithm)
        self.algorithm_combo.setMinimumContentsLength(12)
        self.algorithm_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.algorithm_combo.setMinimumWidth(0)
        self.trials_spin = QSpinBox()
        self.trials_spin.setRange(1, 10000)
        self.trials_spin.setValue(12)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 86400)
        self.timeout_spin.setValue(120)
        self.timeout_spin.setSuffix(' 秒')
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2147483647)
        self.seed_spin.setValue(42)
        for index, (title, widget) in enumerate((('搜索算法', self.algorithm_combo), ('次数上限', self.trials_spin), ('时间预算', self.timeout_spin), ('随机种子', self.seed_spin))):
            row, column = divmod(index, 2)
            label = QLabel(title)
            label.setBuddy(widget)
            form.addWidget(label, row, column * 2)
            form.addWidget(widget, row, column * 2 + 1)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        self.config_panel.content_layout.addLayout(form)
        self.algorithm_note = secondary('')
        self.config_panel.content_layout.addWidget(self.algorithm_note)
        self.algorithm_combo.currentIndexChanged.connect(self._algorithm_changed)
        self._algorithm_changed()
        self.start_button = QPushButton('开始真实搜索')
        self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self._start)
        self.cancel_button = QPushButton('取消任务')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.config_panel.actions.addWidget(self.start_button)
        self.config_panel.actions.addWidget(self.cancel_button)
        self.config_panel.actions.addStretch()
        self.config_panel.set_expanded(False)
        self.new_task_label = secondary('新任务数据：项目默认文件；查看历史不会更改新任务配置。')
        self.config_panel.layout().addWidget(self.new_task_label)
        layout.addWidget(self.config_panel)
        self.result_label = secondary('尚未运行搜索')
        layout.addWidget(self.result_label)
        self.error_label = QLabel()
        self.error_label.setObjectName('error')
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.panel_grid = PanelGrid()
        self.chart_panels = {}
        for title, kind in (('优化历史', 'history'), ('各试验目标分布', 'distribution'), ('超参数与目标关系', 'parameter'), ('状态与任务进度', 'status')):
            panel = ChartPanel(title, kind, parameter=kind == 'parameter')
            panel.maximize_requested.connect(self.maximize_chart)
            self.chart_panels[kind] = panel
            self.panel_grid.add_panel(panel)
        self.chart = self.chart_panels['history'].chart
        self.distribution_chart = self.chart_panels['distribution'].chart
        self.parameter_chart = self.chart_panels['parameter'].chart
        self.status_chart = self.chart_panels['status'].chart
        self.parameter_combo = self.chart_panels['parameter'].parameter_combo
        self.parameter_combo.currentTextChanged.connect(self._parameter_changed)
        self.analysis_section = CollapsiblePanel('优化分析')
        self.parallel_panel = QFrame()
        self.parallel_panel.setObjectName('card')
        parallel_layout = QVBoxLayout(self.parallel_panel)
        parallel_header = QHBoxLayout()
        parallel_header.addWidget(secondary('真实参数平行坐标 · 拖拽轴或输入范围'), 1)
        self.parallel_maximize = QPushButton('放大')
        self.parallel_maximize.clicked.connect(self.maximize_parallel)
        parallel_header.addWidget(self.parallel_maximize)
        parallel_layout.addLayout(parallel_header)
        brush_row = QGridLayout()
        self.brush_parameter = QComboBox()
        self.brush_parameter.setAccessibleName('刷选参数')
        self.brush_low = QDoubleSpinBox()
        self.brush_high = QDoubleSpinBox()
        for control, title in ((self.brush_low, '刷选下限'), (self.brush_high, '刷选上限')):
            control.setRange(-1e+100, 1e+100)
            control.setDecimals(8)
            control.setAccessibleName(title)
            control.setMinimumWidth(0)
        self.apply_brush_button = QPushButton('应用范围')
        self.clear_brush_button = QPushButton('清除刷选')
        self.apply_brush_button.clicked.connect(self._apply_brush_inputs)
        self.clear_brush_button.clicked.connect(self.clear_brush)
        self.brush_parameter.currentTextChanged.connect(self._brush_parameter_changed)
        brush_row.addWidget(self.brush_parameter, 0, 0, 1, 2)
        brush_row.addWidget(self.brush_low, 1, 0)
        brush_row.addWidget(self.brush_high, 1, 1)
        brush_row.addWidget(self.apply_brush_button, 0, 2)
        brush_row.addWidget(self.clear_brush_button, 1, 2)
        parallel_layout.addLayout(brush_row)
        self.brush_label = secondary('未启用参数刷选；范围仅影响显示。')
        parallel_layout.addWidget(self.brush_label)
        self.parallel_chart = ParallelCoordinates()
        parallel_layout.addWidget(self.parallel_chart)
        self.parallel_chart.brush_changed.connect(self.set_brush)
        self.parallel_chart.observed.connect(self._observe_identifier)
        importance, importance_layout = card('超参数重要性')
        importance_layout.addWidget(secondary('尚未提供参数重要性及相关性结果。需要已保存的方法、目标与统计结果；代理排序质量不是参数重要性。'))
        importance_layout.addStretch()
        parallel_grid = PanelGrid()
        parallel_grid.add_panel(self.parallel_panel)
        parallel_grid.add_panel(importance)
        self.analysis_section.content_layout.addWidget(parallel_grid)
        self.analysis_section.content_layout.addWidget(secondary('优化历史：完整任务累计最优，筛选仅高亮；分布与参数图：筛选集合。'))
        self.analysis_section.content_layout.addWidget(self.panel_grid)
        layout.addWidget(self.analysis_section)
        runs = QFrame()
        runs.setObjectName('card')
        runs_layout = QVBoxLayout(runs)
        runs_layout.setContentsMargins(12, 12, 12, 12)
        runs_layout.setSpacing(8)
        title = QLabel('Trials · 搜索试验')
        title.setObjectName('cardTitle')
        runs_layout.addWidget(title)
        self.trial_table = RecordTable([('number', '试验'), ('status', '状态'), ('objective', '目标值'), ('mae', '验证 MAE'), ('duration_seconds', '试验耗时 / 秒'), ('decision', '实际搜索决策')], filter_fields=('status',))
        self.trial_table.enable_workbench(('number', 'status', 'objective'))
        self.trial_table.view.setColumnWidth(1, 48)
        self.trial_table.view.setColumnWidth(2, 80)
        self.trial_table.record_selected.connect(self._observe_trial)
        self.trial_table.details_requested.connect(self._open_trial)
        self.trial_table.filtered_changed.connect(self._sync_filters)
        self.trial_table.checked_changed.connect(self._sync_selection)
        self.trial_compare_button = QPushButton('对比所选 Trial')
        self.trial_compare_button.setEnabled(False)
        self.trial_compare_button.clicked.connect(self.compare_trials)
        runs_layout.addWidget(self.trial_compare_button)
        runs_layout.addWidget(self.trial_table)
        self.runs_panel = runs
        self.baseline_label = secondary('默认基线：暂无记录')
        layout.addWidget(self.baseline_label)
        self.diagnostics_panel = CollapsiblePanel('最优参数与搜索诊断')
        self.params_view = QPlainTextEdit()
        self.params_view.setReadOnly(True)
        self.params_view.setMaximumHeight(220)
        self.params_view.setPlaceholderText('完成真实试验后显示实际最优参数、指标与搜索诊断。')
        self.diagnostics_panel.content_layout.addWidget(self.params_view)
        self.diagnostics_panel.set_expanded(False)
        layout.addWidget(self.diagnostics_panel)
        self.comparison = ComparisonPanel()
        self.comparison.hide()
        layout.addWidget(self.comparison)
        layout.addStretch()
        self.scroll.setWidget(content)
        self.workbench = ResponsiveWorkspace(self.runs_panel, self.scroll, 'Trials')
        wrapper.addWidget(self.workbench)
        self.drawer = RunDetailDrawer(self)
        self.drawer.export_requested.connect(self.export_requested)
        self.drawer.view_experiment_requested.connect(self.history_requested)

    def _start(self):
        self.start_requested.emit(self.algorithm_combo.currentData(), {'optimization': {'max_trials': self.trials_spin.value(), 'timeout_seconds': self.timeout_spin.value()}, 'experiment': {'seed': self.seed_spin.value()}})

    def set_data_context(self, dataset):
        self.new_task_label.setText(f'新任务数据：{dataset}；查看历史不会更改新任务配置。')

    def _algorithm_changed(self):
        algorithm = self.algorithm_combo.currentData()
        if algorithm == 'rac_hpo' and self.trials_spin.value() < 32:
            self.trials_spin.setValue(48)
        self.algorithm_note.setText('RAC-HPO 先完成 16 次初始化；证据或代理质量不足时回退 TPE。建议至少 32 次，真实诊断随试验保存。' if algorithm == 'rac_hpo' else 'Random / TPE 按验证 MAE 选择；固定鲁棒搜索按无量纲 J 选择。默认基线不计入次数上限。')

    def set_busy(self, busy, cancellable=False):
        for widget in (self.start_button, self.algorithm_combo, self.trials_spin, self.timeout_spin, self.seed_spin):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(cancellable)

    def set_task_state(self, state):
        self._task_state = state
        self._update_cancel_text()
        if state == 'cancelling':
            self.cancel_button.setEnabled(False)
        if self.experiment_id and self.experiment_id == self.active_experiment_id and (not self._historical):
            self._render_metrics()

    def set_active_experiment(self, identifier):
        if identifier != self.active_experiment_id:
            self._elapsed_seconds = None
        self.active_experiment_id = identifier
        self.return_button.setVisible(bool(identifier and identifier != self.experiment_id))
        self._update_cancel_text()

    def _update_cancel_text(self):
        other_view = bool(self.active_experiment_id and self.active_experiment_id != self.experiment_id)
        self.cancel_button.setText('取消中…' if self._task_state == 'cancelling' else '取消当前任务' if other_view else '取消任务')
        self.cancel_button.setToolTip(f'取消当前后台任务：{self.active_experiment_id}' if other_view else '请求后等待后端确认取消并保存')

    def set_elapsed(self, seconds):
        if self.experiment_id and self.experiment_id == self.active_experiment_id and (not self._historical) and (self._snapshot.get('status') in ('running', 'starting')):
            self._elapsed_seconds = seconds
            self._set_elapsed_display(f'{seconds:.1f} 秒', '任务已用（实时计时）')

    def _set_elapsed_display(self, value, caption):
        self.elapsed_value.setText(str(value) if value is not None else '—')
        self.elapsed_caption.setText(caption)

    def set_history(self, experiments):
        searches = [result for result in experiments if result.get('algorithm') != 'baseline']
        searches.sort(key=lambda result: result.get('created_at') or '', reverse=True)
        with QSignalBlocker(self.history_combo):
            self.history_combo.clear()
            self.history_combo.addItem('选择历史搜索…' if searches else '暂无历史搜索', None)
            for result in searches:
                text = f"{display_time(result.get('created_at'))} · {result.get('algorithm', '—')} · {status_label(result.get('status'))} · {result.get('id', '—')}"
                self.history_combo.addItem(text, result.get('id'))
                self.history_combo.setItemData(self.history_combo.count() - 1, text, Qt.ItemDataRole.ToolTipRole)
            index = self.history_combo.findData(self.experiment_id)
            self.history_combo.setCurrentIndex(max(0, index))

    def _history_selected(self, index):
        identifier = self.history_combo.itemData(index)
        if identifier:
            self.history_requested.emit(identifier)

    def reset_progress(self):
        self.experiment_id = None
        self._snapshot = {}
        self._historical = False
        self._elapsed_seconds = None
        self.view_state = WorkspaceViewState()
        self.trial_table.extra_filter = self.view_state.matches
        self.trial_table.checked_ids = self.view_state.selected_ids
        self.trial_table.reset_context()
        self.comparison.hide()
        self.trials = []
        for key in self.metrics.cards:
            self.metrics.set_metric(key, None, '')
        self._set_elapsed_display('—', '等待任务')
        self.trial_table.set_records([])
        for panel in self.chart_panels.values():
            panel.chart.set_snapshot({})
            panel.chart.set_loading()
        self.params_view.clear()
        self.result_label.setText('正在启动，等待后端保存真实训练结果…')
        self.header.set_context('新搜索 · 准备中')
        self.baseline_label.setText('默认基线：等待真实记录')
        self.error_label.hide()
        self.export_button.setEnabled(False)
        self.return_button.hide()
        self.drawer.hide()

    def show_trials(self, trials):
        snapshot = {**self._snapshot, 'trials': trials}
        self.trials = search_trials(trials)
        self._snapshot = snapshot
        if self.experiment_id:
            self._snapshots[self.experiment_id] = copy.deepcopy(snapshot)
        self._render_records()
        self._render_charts()
        self._render_metrics()

    def show_result(self, result, historical=False):
        snapshot = copy.deepcopy(result)
        if self.experiment_id != snapshot.get('id'):
            self.drawer.close_drawer()
            self._changing_context = True
            self.view_state = WorkspaceViewState(context_id=snapshot.get('id'))
            self._view_states[snapshot.get('id')] = self.view_state
            self.trial_table.extra_filter = self.view_state.matches
            self.trial_table.reset_context()
            self.trial_table.checked_ids = self.view_state.selected_ids
            self.comparison.hide()
            self._changing_context = False
        self.experiment_id = snapshot.get('id')
        self._snapshot = snapshot
        self._historical = historical
        if self.experiment_id:
            self._snapshots[self.experiment_id] = snapshot
        self.trials = search_trials(snapshot.get('trials', []))
        self.return_button.setVisible(bool(self.active_experiment_id and self.active_experiment_id != self.experiment_id))
        self._update_cancel_text()
        with QSignalBlocker(self.history_combo):
            self.history_combo.setCurrentIndex(max(0, self.history_combo.findData(self.experiment_id)))
        self._render_metrics()
        self._render_records()
        self._render_charts()
        self._render_details()
        self.drawer.update_experiment(snapshot)
        for dialog in list(self._maximized):
            if dialog.experiment_id == self.experiment_id:
                self._update_maximized(dialog, snapshot)
        self.export_button.setEnabled(bool(self.experiment_id))
        failure = snapshot.get('failure_reason')
        self.error_label.setVisible(bool(failure))
        self.error_label.setText(f'任务失败：{failure}' if snapshot.get('status') == 'failed' and failure else str(failure or ''))

    def update_snapshot(self, result, active=False):
        snapshot = copy.deepcopy(result)
        identifier = snapshot.get('id')
        if not identifier:
            return
        self._snapshots[identifier] = snapshot
        if active:
            self.set_active_experiment(identifier)
        for dialog in list(self._maximized):
            if dialog.experiment_id == identifier:
                self._update_maximized(dialog, snapshot)
        if self.experiment_id == identifier or (self.experiment_id is None and active):
            self.show_result(snapshot, historical=self._historical if self.experiment_id else False)

    def show_error(self, message):
        self.error_label.setText(f'任务失败：{message}')
        self.error_label.show()

    def _render_metrics(self):
        result = self._snapshot
        label, unit = objective_label(result)
        completed = completed_trials(result.get('trials', []))
        best = min((objective_value(trial) for trial in completed), default=None)
        best_trial = min(completed, key=objective_value) if completed else None
        mae_trials = [t for t in completed if finite_value((t.get('metrics') or {}).get('overall_mae')) is not None]
        mae_trial = min(mae_trials, key=lambda t: float(t['metrics']['overall_mae'])) if mae_trials else None
        self.metrics.set_metric('mae', f"{format_value(mae_trial['metrics']['overall_mae'])} {result.get('target_unit') or '单位未记录'}" if mae_trial else None, f"Trial #{mae_trial['number']} · 验证集" if mae_trial else '暂无有效完成 Trial')
        maximum = result.get('config', {}).get('optimization', {}).get('max_trials')
        self.metrics.set_metric('best', f'{format_value(best)} {label}' if best is not None else None, f'{label} · {unit} · 越小越好' + (f" · Trial #{best_trial['number']}" if best_trial else ''))
        self.metrics.set_metric('trials', f'{len(self.trials)} / {format_value(maximum)}', f'完成 {len(completed)} 条 · 已保存 / 次数上限，不含基线')
        elapsed = result.get('duration_seconds')
        state = result.get('status')
        live = self.experiment_id and self.experiment_id == self.active_experiment_id and (not self._historical) and (state in ('running', 'starting'))
        if live:
            self._set_elapsed_display(f'{self._elapsed_seconds:.1f} 秒' if self._elapsed_seconds is not None else None, '任务已用（实时计时）')
        else:
            self._set_elapsed_display(f'{format_value(elapsed)} 秒' if elapsed is not None else None, '实验总耗时（保存时）' if state == 'running' else '实验总耗时（已保存）')
        if self.experiment_id == self.active_experiment_id and (not self._historical) and (state == 'running') and (self._task_state == 'cancelling'):
            state = 'cancelling'
        caption = '历史记录' if self._historical else '当前查看实验'
        self.metrics.set_metric('status', status_label(state), caption)
        context = '历史实验' if self._historical else '当前实验'
        self.header.set_context(f"{context} · {self.experiment_id or '等待实验 ID'} · {status_label(state)}", state or '')

    def _render_records(self):
        label, unit = objective_label(self._snapshot)
        target_unit = self._snapshot.get('target_unit') or '单位未记录'
        self.trial_table.columns[2] = ('objective', f'目标 {label} / {unit}')
        self.trial_table.columns[3] = ('mae', f'验证 MAE / {target_unit}')
        self.trial_table.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 2, 3)
        self.trial_table.set_records(trial_view_records(self._snapshot))

    def _render_charts(self):
        names = sorted({name for trial in self.trials for name in trial.get('params', {})})
        selected = self.parameter_combo.currentText()
        with QSignalBlocker(self.parameter_combo):
            self.parameter_combo.clear()
            self.parameter_combo.addItems(names)
            index = self.parameter_combo.findText(selected)
            self.parameter_combo.setCurrentIndex(max(0, index) if names else -1)
        visible = filtered_trial_ids(self._snapshot, self.view_state)
        for kind, panel in self.chart_panels.items():
            data = self._snapshot if kind in ('history', 'status') else {**self._snapshot, 'trials': [t for t in self.trials if f"{self.experiment_id}:{t['number']}" in visible]}
            panel.chart.set_snapshot(data, self.parameter_combo.currentText() or None)
            panel.chart.set_display_state(visible, self.view_state.active_record_id)
        self.parallel_chart.set_snapshot(self._snapshot, visible, self.view_state.active_record_id)
        schema = self._snapshot.get('config', {}).get('optimization', {}).get('search_space', {})
        names = [key for key, spec in schema.items() if isinstance(spec, dict) and spec.get('type', 'float') in ('int', 'float')]
        selected = self.brush_parameter.currentText()
        with QSignalBlocker(self.brush_parameter):
            self.brush_parameter.clear()
            self.brush_parameter.addItems(names)
            self.brush_parameter.setCurrentIndex(max(0, self.brush_parameter.findText(selected)))
        if selected != self.brush_parameter.currentText():
            self._brush_parameter_changed(self.brush_parameter.currentText())

    def _parameter_changed(self, name):
        self._render_charts()

    def _render_details(self):
        result = self._snapshot
        best = next((trial for trial in self.trials if trial['number'] == result.get('best_trial')), {})
        self.params_view.setPlainText(json.dumps({'search_diagnostics': result.get('search_diagnostics'), 'best_params': result.get('best_params'), 'metrics': result.get('metrics'), 'best_trial_selection': best.get('selection')}, ensure_ascii=False, indent=2, default=str))
        baseline = next((trial for trial in result.get('trials', []) if trial.get('number') == -1), None)
        if baseline:
            unit = result.get('target_unit') or '单位未记录'
            duration_label = '基线训练流程耗时' if baseline.get('status') == 'completed' else '基线尝试耗时'
            self.baseline_label.setText(f"默认基线（试验 -1）：{status_label(baseline.get('status'))} · 验证 MAE {format_value(baseline.get('metrics', {}).get('overall_mae'))} {unit} · {duration_label} {format_value(baseline.get('duration_seconds'))} 秒 · 不参与搜索排名")
        else:
            self.baseline_label.setText('默认基线：尚无已保存记录')
        self.result_label.setText(f"{result.get('algorithm', '—')} · 目标 {objective_label(result)[0]} · 基线耗时 {format_value(result.get('baseline_duration_seconds'))} 秒 · 搜索耗时 {format_value(result.get('search_duration_seconds'))} 秒")

    def _open_trial(self, record):
        if not record:
            return
        trial = next((trial for trial in self.trials if trial['number'] == record.get('number')), None)
        if trial is not None:
            self.drawer.show_trial(self._snapshot, trial)

    def _export(self):
        if self.experiment_id:
            self.export_requested.emit(self.experiment_id)

    def maximize_chart(self, kind):
        if kind not in self.chart_panels:
            return
        source = self.chart_panels[kind]
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{source.title_label.text()} · {self.experiment_id or '暂无实验'}")
        dialog.resize(1100, 700)
        dialog.setMinimumSize(600, 400)
        dialog.experiment_id = self.experiment_id
        dialog.chart_kind = kind
        layout = QVBoxLayout(dialog)
        header = QHBoxLayout()
        header.addWidget(secondary(self.experiment_id or '暂无实验'), 1)
        close = QPushButton('关闭 · Esc')
        close.clicked.connect(dialog.close)
        header.addWidget(close)
        layout.addLayout(header)
        dialog.parameter_combo = None
        if kind == 'parameter':
            dialog.parameter_combo = QComboBox()
            layout.addWidget(dialog.parameter_combo)
        dialog.chart = ExperimentChart(kind)
        layout.addWidget(dialog.chart, 1)
        dialog.parameter = self.parameter_combo.currentText() or None
        self._update_maximized(dialog, self._snapshot)
        if dialog.parameter_combo is not None:
            dialog.parameter_combo.currentTextChanged.connect(lambda name: self._max_parameter_changed(dialog, name))
        self._maximized.append(dialog)
        dialog.finished.connect(lambda: self._forget_maximized(dialog))
        dialog.finished.connect(dialog.deleteLater)
        dialog.show()

    def _max_parameter_changed(self, dialog, name):
        dialog.parameter = name
        self._update_maximized(dialog, self._snapshots.get(dialog.experiment_id, {}))

    def _forget_maximized(self, dialog):
        if dialog in self._maximized:
            self._maximized.remove(dialog)
        dialog.setParent(None)

    def _update_maximized(self, dialog, snapshot):
        parameter = dialog.parameter
        if dialog.parameter_combo is not None:
            names = sorted({name for trial in search_trials(snapshot.get('trials', [])) for name in trial.get('params', {})})
            parameter = dialog.parameter_combo.currentText() or parameter
            with QSignalBlocker(dialog.parameter_combo):
                dialog.parameter_combo.clear()
                dialog.parameter_combo.addItems(names)
                dialog.parameter_combo.setCurrentIndex(max(0, dialog.parameter_combo.findText(parameter or '')))
            parameter = dialog.parameter_combo.currentText() or None
        state = self._view_states.get(dialog.experiment_id, WorkspaceViewState())
        visible = filtered_trial_ids(snapshot, state)
        if getattr(dialog, 'chart_kind', None) == 'parallel':
            dialog.chart.set_snapshot(snapshot, visible, state.active_record_id)
        else:
            data = snapshot if dialog.chart_kind in ('history', 'status') else {**snapshot, 'trials': [t for t in search_trials(snapshot.get('trials', [])) if f"{dialog.experiment_id}:{t['number']}" in visible]}
            dialog.chart.set_snapshot(data, parameter)
            dialog.chart.set_display_state(visible, state.active_record_id)

    def _sync_filters(self):
        if self._changing_context:
            return
        self.view_state.filters = {'query': self.trial_table.search_edit.text(), 'fields': {key: combo.currentData() for key, combo in self.trial_table.filters.items()}}
        if hasattr(self, 'parallel_chart'):
            self._render_charts()
            for dialog in self._maximized:
                if dialog.experiment_id == self.experiment_id:
                    self._update_maximized(dialog, self._snapshot)

    def _sync_selection(self):
        if not hasattr(self, 'trial_compare_button'):
            return
        self.trial_compare_button.setEnabled(2 <= len(self.trial_table.checked_ids) <= 8)
        if hasattr(self, 'comparison') and self.comparison.isVisible():
            self.compare_trials()

    def _observe_identifier(self, identifier):
        self._observe_context(self.experiment_id, identifier)

    def _observe_context(self, experiment_id, identifier):
        state = self._view_states.get(experiment_id, self.view_state)
        state.active_record_id = identifier
        if experiment_id == self.experiment_id:
            self.trial_table.observe(identifier)
            self._render_charts()
        for dialog in self._maximized:
            if dialog.experiment_id == experiment_id:
                self._update_maximized(dialog, self._snapshots.get(experiment_id, {}))

    def _observe_trial(self, record):
        if record:
            self._observe_identifier(record.get('_id'))

    def compare_trials(self):
        records = [t for t in self.trials if f"{self.experiment_id}:{t['number']}" in self.trial_table.checked_ids]
        self.comparison.set_records(records, trials=True, unit=self._snapshot.get('target_unit'))
        self.comparison.show()
        self.scroll.ensureWidgetVisible(self.comparison)

    def _brush_parameter_changed(self, name):
        spec = self._snapshot.get('config', {}).get('optimization', {}).get('search_space', {}).get(name, {})
        bounds = self.view_state.brush.get(name, (spec.get('low', 0), spec.get('high', 1)))
        self.brush_low.setValue(finite_value(bounds[0]) or 0)
        self.brush_high.setValue(finite_value(bounds[1]) or 1)

    def _apply_brush_inputs(self):
        self.set_brush(self.brush_parameter.currentText(), self.brush_low.value(), self.brush_high.value())

    def set_brush(self, name, low, high):
        self._set_context_brush(self.experiment_id, name, low, high)

    def _set_context_brush(self, identifier, name, low, high):
        if not name or finite_value(low) is None or finite_value(high) is None or (low > high):
            self.brush_label.setText('范围无效：下限须不大于上限。')
            return
        state = self._view_states.get(identifier, self.view_state)
        state.brush[name] = (low, high)
        if identifier == self.experiment_id:
            self.brush_label.setText('刷选：' + '；'.join((f'{key} ∈ [{a:.6g}, {b:.6g}]' for key, (a, b) in state.brush.items())))
            self.trial_table._refresh()
        for dialog in self._maximized:
            if dialog.experiment_id == identifier:
                self._update_maximized(dialog, self._snapshots.get(identifier, {}))

    def clear_brush(self):
        self.view_state.brush.clear()
        self.brush_label.setText('未启用参数刷选；范围仅影响显示。')
        self.trial_table._refresh()

    def maximize_parallel(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('平行坐标 · ' + str(self.experiment_id))
        dialog.resize(1100, 700)
        dialog.experiment_id = self.experiment_id
        dialog.chart_kind = 'parallel'
        dialog.parameter = None
        dialog.parameter_combo = None
        layout = QVBoxLayout(dialog)
        close = QPushButton('关闭 · Esc')
        close.clicked.connect(dialog.close)
        layout.addWidget(close)
        layout.addWidget(secondary('参数轴拖拽刷选；此窗口绑定打开时的实验，筛选与对应工作台共享。'))
        dialog.chart = ParallelCoordinates()
        layout.addWidget(dialog.chart, 1)
        dialog.chart.brush_changed.connect(lambda name, low, high: self._set_context_brush(dialog.experiment_id, name, low, high))
        dialog.chart.observed.connect(lambda identifier: self._observe_context(dialog.experiment_id, identifier))
        self._maximized.append(dialog)
        dialog.finished.connect(lambda: self._forget_maximized(dialog))
        dialog.finished.connect(dialog.deleteLater)
        self._update_maximized(dialog, self._snapshot)
        dialog.show()

    def closeEvent(self, event):
        for dialog in list(self._maximized):
            dialog.close()
        super().closeEvent(event)
