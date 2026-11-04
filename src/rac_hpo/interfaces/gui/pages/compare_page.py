"""Run browsing and explicit side-by-side inspection of saved experiments."""
import json
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget
from ..widgets import card, secondary
from ..workspace_state import display_time, status_label, WorkspaceViewState
from ..workspace_widgets import RecordTable, RunDetailDrawer, WorkspaceHeader, CollapsiblePanel, MetricsGrid
from ..workbench_widgets import ResponsiveWorkspace, ComparisonPanel

class ComparePage(QWidget):
    refresh_requested = Signal()
    detail_requested = Signal(str)
    export_requested = Signal(str)
    view_experiment_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.experiments = []
        self.experiment_id = None
        self.view_state = WorkspaceViewState()
        self._comparing = False
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        history, history_layout = card('Runs · 真实实验')
        self.refresh_button = QPushButton('刷新实验记录')
        self.refresh_button.clicked.connect(self.refresh_requested)
        history_layout.addWidget(self.refresh_button)
        self.history_table = RecordTable([('id', '实验 ID'), ('created_at', '创建时间 / +08:00'), ('dataset_id', '数据集'), ('algorithm', '算法'), ('status', '状态'), ('overall_mae', '验证 MAE'), ('target_unit', '目标单位'), ('robust_objective', '固定 J · 无量纲'), ('duration_seconds', '总耗时 / s'), ('trial_count', '搜索试验数')], filter_fields=('algorithm', 'status'))
        self.history_table.enable_workbench(('id', 'algorithm', 'status'))
        self.history_table.checked_ids = self.view_state.selected_ids
        self.history_table.view.setColumnWidth(1, 150)
        self.history_table.record_selected.connect(self._select)
        self.history_table.details_requested.connect(lambda r: self.detail_requested.emit(str(r['_id'])))
        self.history_table.checked_changed.connect(self._selection_changed)
        history_layout.addWidget(self.history_table, 1)
        self.compare_button = QPushButton('刷新并排对比（勾选后自动显示）')
        self.compare_button.setEnabled(False)
        self.compare_button.clicked.connect(self.compare_selected)
        history_layout.addWidget(self.compare_button)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setMinimumWidth(0)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.header = WorkspaceHeader('实验对比', '横向滚动左侧列表可直接看全部指标；点某行查看单条；勾选 2–8 条自动并排核对。')
        self.export_button = QPushButton('导出查看中的实验')
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_selected)
        self.view_button = QPushButton('进入优化工作区')
        self.view_button.setEnabled(False)
        self.view_button.clicked.connect(lambda: self.view_experiment_requested.emit(self.experiment_id))
        self.header.actions.addWidget(self.export_button)
        layout.addWidget(self.header)
        self.metrics = MetricsGrid([('dataset', '数据集'), ('algorithm', '算法'), ('mae', '当前观察 · 验证 MAE'), ('j', '当前观察 · 固定 J')])
        for _key in ('dataset', 'algorithm', 'mae', 'j'):
            self.metrics.set_metric(_key, None, '点左侧行查看')
        layout.addWidget(self.metrics)
        self.overview = CollapsiblePanel('当前观察 Run')
        self.overview_label = secondary('尚未选择。点左侧列表的任意一行（点文字，不是方框）查看单条详情；勾选方框用于并排对比。')
        self.overview.content_layout.addWidget(self.overview_label)
        self.overview.actions.addWidget(self.view_button)
        self.detail_button = QPushButton('查看完整详情')
        self.detail_button.setEnabled(False)
        self.detail_button.clicked.connect(lambda: self.detail_requested.emit(self.experiment_id))
        self.overview.actions.addWidget(self.detail_button)
        self.params = QPlainTextEdit()
        self.params.setReadOnly(True)
        self.params.setMaximumHeight(220)
        self.params.setPlaceholderText('此处显示保存的参数与固定目标，不生成新统计。')
        self.overview.content_layout.addWidget(self.params)
        layout.addWidget(self.overview)
        self.comparison = ComparisonPanel()
        self.comparison.hide()
        layout.addWidget(self.comparison)
        info, info_layout = card('指标口径')
        info_layout.addWidget(secondary('MAE 使用每条实验的目标单位；J 无量纲。当前接口未提供固定划分与目标/特征版本证据，因此跨 Run 仅并排查看，不给出排名或胜出结论。'))
        layout.addWidget(info)
        layout.addStretch()
        self.scroll.setWidget(content)
        self.workbench = ResponsiveWorkspace(history, self.scroll, 'Runs')
        wrapper.addWidget(self.workbench)
        self.drawer = RunDetailDrawer(self)
        self.drawer.export_requested.connect(self.export_requested)
        self.drawer.view_experiment_requested.connect(self.view_experiment_requested)

    def show_experiments(self, experiments):
        self.experiments = list(experiments)
        records = []
        for experiment in self.experiments:
            metrics = experiment.get('metrics') or {}
            records.append({**experiment, '_id': experiment['id'], 'created_at': display_time(experiment.get('created_at')), 'overall_mae': metrics.get('overall_mae'), 'robust_objective': metrics.get('robust_objective')})
        self.history_table.set_records(records)
        if self.experiment_id:
            record = next((r for r in records if r['_id'] == self.experiment_id), None)
            if record:
                self._select(record)
        else:
            self.header.set_context(f'{len(records)} 个真实实验', 'history')
        self._selection_changed()

    def _select(self, record):
        self.experiment_id = str(record['_id'])
        self.view_state.active_record_id = self.experiment_id
        self.export_button.setEnabled(True)
        self.detail_button.setEnabled(True)
        self.view_button.setEnabled(record.get('algorithm') != 'baseline')
        self.header.set_context(self.experiment_id + ' · ' + status_label(record.get('status')))
        metrics = record.get('metrics') or {}
        unit = record.get('target_unit') or '单位未记录'
        self.metrics.set_metric('dataset', record.get('dataset_id'), '观察中')
        self.metrics.set_metric('algorithm', record.get('algorithm'), '观察中')
        self.metrics.set_metric('mae', metrics.get('overall_mae'), unit)
        self.metrics.set_metric('j', metrics.get('robust_objective'), '无量纲')
        self.overview_label.setText(f"{self.experiment_id}\n创建时间：{record.get('created_at') or '—'}\n数据 SHA-256：{record.get('data_sha256') or '未提供'}")
        self.params.setPlainText(json.dumps({'best_params': record.get('best_params'), 'fixed_objective': record.get('fixed_objective'), 'config': record.get('config')}, ensure_ascii=False, indent=2, default=str))

    def _selection_changed(self):
        count = len(self.history_table.checked_ids)
        self.compare_button.setEnabled(2 <= count <= 8)
        if 2 <= count <= 8:
            # Showing the table immediately removes the "I checked boxes but see nothing" trap.
            self.compare_selected()
        elif count < 2:
            self._comparing = False
            self.comparison.hide()

    def compare_selected(self):
        self._comparing = True
        records = [r for r in self.experiments if r.get('id') in self.history_table.checked_ids]
        self.comparison.set_records(records)
        self.comparison.show()
        self.scroll.ensureWidgetVisible(self.comparison)

    def _export_selected(self):
        if self.experiment_id:
            self.export_requested.emit(self.experiment_id)

    def show_detail(self, result):
        self.drawer.show_experiment(result)
