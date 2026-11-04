"""Offline lifecycle workspace; all operations go through application services."""
from datetime import datetime, timedelta, timezone
import json

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..widgets import card, secondary
from ..workspace_widgets import MetricsGrid, PanelGrid, WorkspaceHeader

STATES = {'CREATED': '待运行', 'TRAINING_INITIAL': '训练初始模型', 'MONITORING': '回放监测',
          'TRAINING_CANDIDATE': '重新调参', 'EVALUATING': '候选门禁',
          'AWAITING_OPTIMIZATION': '未触发优化，可继续观察或演示调参',
          'WAITING_RELEASE': '门禁通过，等待人工切换', 'COMPLETED': '回放完成',
          'DATA_REVIEW': '数据异常，等待检查', 'CANCELLED': '已取消',
          'BUDGET_EXHAUSTED': '训练预算耗尽', 'INTERRUPTED': '执行中断，未自动重训', 'FAILED': '失败'}


class LoopPage(QWidget):
    operation_requested = Signal(str, dict)
    refresh_requested = Signal()
    session_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = {}
        self.busy = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout.addWidget(WorkspaceHeader('自主优化 · 单轮离线闭环',
            'CNC 整刀回放与后验标签释放；所有切换仅作用于本地模拟槽位。'))
        self.status_label = QLabel('尚无会话。先核对预算并授权一次训练，再开始回放。')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.metrics = MetricsGrid([('mode', '数据模式'), ('progress', '已回放周期'),
                                    ('training', '实际训练耗时'), ('gate', '候选门禁')])
        layout.addWidget(self.metrics)
        self.panels = PanelGrid()
        layout.addWidget(self.panels)
        setup, setup_layout = card('新会话 · 固定协议与预算')
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText('CNC Milling 2025 原始 CSV')
        self.path_edit.setMinimumWidth(0)
        source_row = QHBoxLayout()
        source_row.addWidget(self.path_edit, 1)
        browse = QPushButton('选择文件')
        browse.clicked.connect(self._browse)
        source_row.addWidget(browse)
        setup_layout.addLayout(source_row)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.trials_spin = QSpinBox()
        self.trials_spin.setRange(1, 48)
        self.trials_spin.setValue(48)
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(.1, 120)
        self.timeout_spin.setValue(120)
        self.timeout_spin.setSuffix(' s')
        self.budget_spin = QDoubleSpinBox()
        self.budget_spin.setRange(.1, 300)
        self.budget_spin.setValue(300)
        self.budget_spin.setSuffix(' s')
        self.scenario_combo = QComboBox()
        for label, value in [('原始测量回放 · REPLAY', 'natural'),
                             ('模拟缺失传感器 · SIMULATED', 'missing_sensor'),
                             ('模拟特征偏移 · SIMULATED', 'feature_shift')]:
            self.scenario_combo.addItem(label, value)
        form.addRow('RAC-HPO 试验上限', self.trials_spin)
        form.addRow('搜索预算（基线另计）', self.timeout_spin)
        form.addRow('会话训练总预算', self.budget_spin)
        form.addRow('回放场景', self.scenario_combo)
        setup_layout.addLayout(form)
        self.demo_check = QCheckBox('自然变化未触发时，显式演示一次调参')
        setup_layout.addWidget(self.demo_check)
        self.authorize_check = QCheckBox('授权本会话初始训练及一次上述预算内的调参')
        setup_layout.addWidget(self.authorize_check)
        setup_layout.addWidget(secondary('固定 seed=42，LightGBM；整刀结束才释放寿命标签。模拟切换与回滚另行人工确认。'))
        self.start_button = QPushButton('授权并开始新会话')
        self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self._create)
        self.authorize_check.toggled.connect(self._buttons)
        setup_layout.addWidget(self.start_button)
        self.panels.add_panel(setup)
        control, control_layout = card('会话与本地模型槽位')
        history_row = QHBoxLayout()
        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(0)
        self.history_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.history_combo.setMinimumContentsLength(12)
        self.history_combo.currentIndexChanged.connect(self._select)
        history_row.addWidget(self.history_combo, 1)
        refresh = QPushButton('刷新')
        refresh.clicked.connect(self.refresh_requested.emit)
        history_row.addWidget(refresh)
        control_layout.addLayout(history_row)
        self.slot_label = QLabel('冠军 —\n候选 —\n当前活动 —')
        self.slot_label.setWordWrap(True)
        control_layout.addWidget(self.slot_label)
        actions = QGridLayout()
        self.continue_button = QPushButton('继续回放')
        self.manual_button = QPushButton('演示重调参')
        self.promote_button = QPushButton('批准模拟切换')
        self.decline_button = QPushButton('保留冠军')
        self.rollback_button = QPushButton('人工回滚')
        self.export_button = QPushButton('导出会话与审计')
        self.continue_button.clicked.connect(lambda: self._operation('run', manual_demo=False))
        self.manual_button.clicked.connect(lambda: self._operation('run', manual_demo=True))
        self.promote_button.clicked.connect(lambda: self._confirm('promote', '批准切换到门禁通过的候选模型？这只影响本地模拟槽位。'))
        self.decline_button.clicked.connect(lambda: self._operation('decline'))
        self.rollback_button.clicked.connect(lambda: self._confirm('rollback', '确认恢复本会话上一冠军模型？'))
        self.export_button.clicked.connect(lambda: self._operation('export'))
        for index, button in enumerate((self.continue_button, self.manual_button, self.promote_button,
                                         self.decline_button, self.rollback_button, self.export_button)):
            actions.addWidget(button, index//2, index%2)
        control_layout.addLayout(actions)
        control_layout.addWidget(secondary('门禁按数据指纹只消费一次；新建会话不会重置。历史门禁数据不能证明独立外部泛化。'))
        self.panels.add_panel(control)
        tabs = QTabWidget()
        self.timeline = self._text()
        self.evidence = self._text()
        self.protocol_view = self._text()
        self.model_view = self._text()
        for name, widget in [('审计时间轴', self.timeline), ('诊断与门禁', self.evidence),
                             ('模型与参数', self.model_view), ('数据划分', self.protocol_view)]:
            tabs.addTab(widget, name)
        tabs.setMinimumHeight(240)
        layout.addWidget(tabs)
        layout.addWidget(secondary('软件流程演示：每工况仅一把验证/门禁刀具，q=0，无置信区间；未连接生产设备，原测试集保持封存。'))
        self._buttons()

    @staticmethod
    def _text():
        result = QPlainTextEdit()
        result.setReadOnly(True)
        result.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        result.setMinimumWidth(0)
        return result

    def _browse(self):
        filename, _ = QFileDialog.getOpenFileName(self, '选择 CNC 原始数据', self.path_edit.text(), 'CSV (*.csv)')
        if filename:
            self.path_edit.setText(filename)

    def _create(self):
        self.snapshot = {}
        self.operation_requested.emit('create', {'source_path': self.path_edit.text().strip() or None,
            'authorize_training': self.authorize_check.isChecked(),
            'policy': {'max_trials': self.trials_spin.value(), 'timeout_seconds': self.timeout_spin.value(),
                       'training_budget_seconds': self.budget_spin.value(), 'scenario': self.scenario_combo.currentData()},
            'manual_demo': self.demo_check.isChecked()})

    def _select(self):
        identifier = self.history_combo.currentData()
        if identifier:
            self.session_selected.emit(identifier)

    def set_history(self, sessions):
        selected = self.snapshot.get('id')
        self.history_combo.blockSignals(True)
        self.history_combo.clear()
        for session in sessions:
            self.history_combo.addItem(f"{session['id']} · {STATES.get(session['state'], session['state'])}", session['id'])
        if selected:
            self.history_combo.setCurrentIndex(self.history_combo.findData(selected))
        self.history_combo.blockSignals(False)

    def show_session(self, session):
        self.snapshot = session
        self.status_label.setText(f"{session['id']} · {STATES.get(session['state'], session['state'])} · {session['data_mode']}")
        self.metrics.set_metric('mode', session['data_mode'])
        self.metrics.set_metric('progress', len(session.get('predictions', [])), '总计 167 个真实周期')
        self.metrics.set_metric('training', f"{session['training_seconds']:.2f} s", '含初始与候选基线；实际墙钟')
        gate = session.get('gate')
        self.metrics.set_metric('gate', '通过，需人工确认' if gate and gate['passed'] else '拒绝' if gate else '尚未评估')
        self.slot_label.setText('\n'.join(f"{label}：{(session.get(key) or {}).get('experiment_id', '—')}\n"
                                f"SHA-256：{(session.get(key) or {}).get('sha256', '—')[:16]}"
                                for key, label in [('champion', '初始冠军'), ('candidate', '候选'), ('active_model', '当前活动')]))
        self.slot_label.setToolTip(json.dumps(session.get('active_model'), ensure_ascii=False, indent=2))
        lines = []
        for event in session.get('events', []):
            stamp = datetime.fromisoformat(event['timestamp']).astimezone(timezone(timedelta(hours=8)))
            lines.append(f"{stamp:%m-%d %H:%M:%S} · {event['kind']} · {event['actor']} · {event['evidence'].get('to_state', '')}")
        self._replace(self.timeline, '\n'.join(lines) or '尚无事件')
        diagnostics = {'proposal': session.get('proposal'), 'gate': gate,
                       'rollback_suggested': session.get('rollback_suggested'),
                       'monitoring': [e for e in session.get('events', []) if e['kind'] in
                                      {'monitoring_event', 'labels_released', 'data_review_required'}]}
        self._replace(self.evidence, json.dumps(diagnostics, ensure_ascii=False, indent=2))
        self._replace(self.protocol_view, json.dumps(session['protocol'], ensure_ascii=False, indent=2))
        self._replace(self.model_view, json.dumps({key: session.get(key) for key in
            ('policy', 'champion', 'candidate', 'active_model')}, ensure_ascii=False, indent=2))
        self._buttons()

    @staticmethod
    def _replace(widget, text):
        bar = widget.verticalScrollBar()
        old, bottom = bar.value(), bar.value() >= bar.maximum()
        widget.setPlainText(text)
        bar.setValue(bar.maximum() if bottom else old)

    def _operation(self, action, **kwargs):
        if self.snapshot:
            arguments = {'identifier': self.snapshot['id'], **kwargs}
            if action in ('promote', 'rollback', 'decline'):
                arguments['expected_revision'] = self.snapshot['revision']
            self.operation_requested.emit(action, arguments)

    def _confirm(self, action, text):
        if QMessageBox.question(self, '确认本地模拟操作', text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._operation(action)

    def set_busy(self, busy):
        self.busy = busy
        self._buttons()

    def _buttons(self):
        self.start_button.setEnabled(not self.busy and self.authorize_check.isChecked())
        state = self.snapshot.get('state')
        ready = bool(self.snapshot) and not self.busy
        self.continue_button.setEnabled(ready and state in {'CREATED', 'MONITORING', 'AWAITING_OPTIMIZATION'})
        self.manual_button.setEnabled(ready and state == 'AWAITING_OPTIMIZATION')
        self.promote_button.setEnabled(ready and state == 'WAITING_RELEASE')
        self.decline_button.setEnabled(ready and state == 'WAITING_RELEASE')
        self.rollback_button.setEnabled(ready and self.snapshot.get('promoted', False)
                                       and not self.snapshot.get('rolled_back', False)
                                       and state in {'MONITORING', 'COMPLETED'})
        self.export_button.setEnabled(ready)

    def show_error(self, message):
        self.status_label.setText(f'操作失败：{message}')
