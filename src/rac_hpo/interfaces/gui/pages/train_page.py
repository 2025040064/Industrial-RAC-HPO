import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout, QLabel, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..widgets import card, fill_table, format_value, page_layout, secondary, table
from ..workspace_widgets import CollapsiblePanel, MetricsGrid, PanelGrid, WorkspaceHeader


class TrainPage(QWidget):
    start_requested = Signal(dict)
    cancel_requested = Signal()
    export_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.experiment_id = None
        page, layout = page_layout("", "")
        for _ in range(2):
            layout.takeAt(0).widget().deleteLater()
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(page)
        self.header = WorkspaceHeader("模型训练", "LightGBM 基线 · 固定训练 / 验证划分，测试集仅供显式最终评估。")
        layout.addWidget(self.header)
        self.metrics = MetricsGrid([
            ("mae", "验证 MAE"), ("objective", "固定鲁棒目标 J"),
            ("training_duration", "实际基线训练耗时"), ("iteration", "最优迭代数"),
        ])
        layout.addWidget(self.metrics)
        self.config_panel = CollapsiblePanel("训练配置")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setSpacing(12)
        form.addRow("模型", QLabel("LightGBM Regressor"))
        self.rounds_spin = QSpinBox()
        self.rounds_spin.setRange(10, 10000)
        self.rounds_spin.setValue(300)
        self.rounds_spin.setAccessibleName("最大树数量")
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2147483647)
        self.seed_spin.setValue(42)
        form.addRow("最大树数量", self.rounds_spin)
        form.addRow("随机种子", self.seed_spin)
        self.config_panel.content_layout.addLayout(form)
        self.config_panel.content_layout.addWidget(secondary("使用数据管理中选择的文件；实际训练配置随实验保存。"))
        self.start_button = QPushButton("开始基线训练")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start)
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.config_panel.actions.addWidget(self.start_button)
        self.config_panel.actions.addWidget(self.cancel_button)
        layout.addWidget(self.config_panel)
        self.error_label = QLabel()
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        result, result_layout = card("真实验证结果")
        self.result_label = QLabel("尚未运行基线训练")
        self.result_label.setWordWrap(True)
        result_layout.addWidget(self.result_label)
        self.duration_label = secondary("实验总耗时：—；包含数据与产物处理，不等同于基线训练耗时。")
        result_layout.addWidget(self.duration_label)
        self.export_button = QPushButton("导出本次实验")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(lambda: self.export_requested.emit(self.experiment_id))
        result_layout.addWidget(self.export_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(result)
        self.panels = PanelGrid()
        regimes, regime_layout = card("分工况验证指标")
        self.regime_table = table(["工况", "验证样本", "MAE / 目标单位"])
        self._size_table(self.regime_table, 0)
        regime_layout.addWidget(self.regime_table)
        regime_layout.addWidget(secondary("各工况 MAE 使用目标原始单位；J 是无量纲的固定鲁棒目标。"))
        self.panels.add_panel(regimes)
        params, params_layout = card("实际模型参数")
        self.params_table = table(["参数", "实际值"])
        self._size_table(self.params_table, 0)
        params_layout.addWidget(self.params_table)
        self.panels.add_panel(params)
        self.validation_section=CollapsiblePanel('模型验证与工况表现')
        self.validation_section.content_layout.addWidget(self.panels)
        layout.addWidget(self.validation_section)
        self.diagnostics_section=CollapsiblePanel('预测诊断与模型解释')
        self.diagnostics_section.content_layout.addWidget(secondary('暂无逐样本预测、残差或特征重要性读取接口。需要 sampleId、评估集、模型版本与已对齐的预测/实际值；当前仅展示已保存的验证聚合指标。'))
        layout.addWidget(self.diagnostics_section)
        self.detail_panel = CollapsiblePanel("完整训练结果与复现信息")
        self.detail_panel.set_expanded(False)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFixedHeight(280)
        self.detail.setPlaceholderText("训练完成后展示实际保存的指标、参数和产物。")
        self.detail_panel.content_layout.addWidget(self.detail)
        layout.addWidget(self.detail_panel)
        layout.addStretch()

    @staticmethod
    def _size_table(widget, count):
        widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setMinimumHeight(0)
        widget.setFixedHeight(widget.horizontalHeader().height() + max(count, 1) * 32 + 8)

    def _start(self):
        self.error_label.hide()
        self.start_requested.emit({
            "model": {"n_estimators": self.rounds_spin.value()},
            "experiment": {"seed": self.seed_spin.value()},
        })

    def reset_progress(self):
        self.experiment_id = None
        self.export_button.setEnabled(False)
        for key in self.metrics.cards:
            self.metrics.set_metric(key, "—", "")
        for widget in (self.regime_table, self.params_table):
            fill_table(widget, [])
            self._size_table(widget, 0)
        self.regime_table.setHorizontalHeaderLabels(["工况", "验证样本", "MAE / 目标单位"])
        self.result_label.setText("新训练正在启动；等待后端保存真实结果。")
        self.duration_label.setText("实验总耗时：—；等待后端保存。")
        self.detail.clear()
        self.error_label.clear()
        self.error_label.hide()
        self.header.set_context("等待后端开始训练", "running")

    def set_busy(self, busy, cancellable=False):
        for widget in (self.start_button, self.rounds_spin, self.seed_spin):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(cancellable)

    def set_task_state(self, state):
        labels = {"running": "正在后台训练", "cancelling": "取消中 · 等待后端确认", "idle": "就绪"}
        self.header.set_context(labels.get(state, state), state)
        if state == "cancelling":
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("取消中…")
        else:
            self.cancel_button.setText("取消任务")
        if state == "running":
            self.error_label.hide()

    def show_error(self, message):
        self.error_label.setText(str(message))
        self.error_label.show()
        self.header.set_context("训练失败", "failed")

    def show_result(self, result):
        self.experiment_id = result.get("id")
        metrics = result.get("metrics") or {}
        unit = result.get("target_unit") or "单位未提供"
        mae = metrics.get("overall_mae")
        objective = metrics.get("robust_objective")
        training_duration = result.get("baseline_duration_seconds")
        self.metrics.set_metric("mae", f"{format_value(mae)} {unit}" if mae is not None else "—")
        self.metrics.set_metric("objective", f"{format_value(objective)} · 无量纲" if objective is not None else "—")
        self.metrics.set_metric("training_duration", f"{format_value(training_duration)} s" if training_duration is not None else "—")
        self.metrics.set_metric("iteration", format_value(result.get("best_iteration")))
        self.result_label.setText(f"{self.experiment_id or '—'} · 验证 MAE {format_value(mae)} {unit}")
        self.duration_label.setText(f"实验总耗时：{format_value(result.get('duration_seconds'))} s · 包含初始化与产物处理")
        status = result.get("status") or "unknown"
        self.header.set_context(f"{self.experiment_id or '实验结果'} · {status}", status)
        regimes = metrics.get("regimes") or {}
        fill_table(self.regime_table, [(key, item.get("samples"), f"{format_value(item.get('mae'))} {unit}") for key, item in regimes.items()])
        self.regime_table.setHorizontalHeaderLabels(["工况", "验证样本", f"MAE / {unit}"])
        self._size_table(self.regime_table, len(regimes))
        params = result.get("best_params") or {}
        fill_table(self.params_table, list(params.items()))
        self._size_table(self.params_table, len(params))
        self.detail.setPlainText(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        self.export_button.setEnabled(bool(self.experiment_id))
        if result.get("failure_reason"):
            self.error_label.setText(str(result["failure_reason"]))
            self.error_label.show()
        else:
            self.error_label.hide()
