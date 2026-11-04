import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from ..widgets import card, fill_table, format_value, page_layout, secondary, table
from ..workspace_widgets import CollapsiblePanel, MetricsGrid, PanelGrid, WorkspaceHeader


class DataPage(QWidget):
    import_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        page, layout = page_layout("", "")
        for _ in range(2):
            layout.takeAt(0).widget().deleteLater()
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(page)
        self.header = WorkspaceHeader("数据管理 · 工业数据", "校验真实文件、来源与固定划分；测试集保持封存。")
        layout.addWidget(self.header)
        self.metrics = MetricsGrid([
            ("dataset", "当前数据集"), ("records", "真实记录数"),
            ("features", "输入特征数"), ("target", "预测目标"), ("unit", "目标单位"),
        ])
        layout.addWidget(self.metrics)
        source, source_layout = card("数据导入与校验")
        self.dataset_combo = QComboBox()
        self.dataset_combo.addItem("UCI 钢铁能耗 · 日历基线", "steel_energy")
        self.dataset_combo.addItem("CNC Milling 2025 · 真实刀具分组", "cnc_milling_2025")
        source_layout.addWidget(self.dataset_combo)
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("默认：datasets/raw/steel_energy/Steel_industry_data.csv")
        self.path_edit.setAccessibleName("真实工业数据 CSV 路径")
        self.dataset_combo.currentIndexChanged.connect(self._dataset_changed)
        self.browse_button = QPushButton("选择文件")
        self.browse_button.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_button)
        source_layout.addLayout(path_row)
        actions = QHBoxLayout()
        self.import_button = QPushButton("导入并校验数据")
        self.import_button.setObjectName("primary")
        self.import_button.clicked.connect(lambda: self.import_requested.emit(self.path_edit.text().strip() or None))
        actions.addWidget(self.import_button)
        actions.addStretch()
        source_layout.addLayout(actions)
        self.summary_label = secondary("尚未导入；指标只在真实校验完成后更新。")
        source_layout.addWidget(self.summary_label)
        source_layout.removeWidget(self.dataset_combo)
        actions.insertWidget(0,self.dataset_combo,1)
        source_layout.removeItem(actions)
        source_layout.insertLayout(1,actions)
        layout.removeWidget(self.metrics)
        layout.addWidget(source)
        layout.addWidget(self.metrics)
        self.panels = PanelGrid()
        split, split_layout = card("固定数据划分")
        self.split_table = table(["划分", "实际记录数"])
        self._size_table(self.split_table, 0)
        split_layout.addWidget(self.split_table)
        self.split_label = secondary("导入后显示实际划分策略。")
        split_layout.addWidget(self.split_label)
        self.panels.add_panel(split)
        regimes, regimes_layout = card("预先定义的工况")
        self.regime_table = table(["工况", "实际记录数"])
        self._size_table(self.regime_table, 0)
        regimes_layout.addWidget(self.regime_table)
        self.group_label = secondary("日期块不等同于独立机床、刀具或生产批次。")
        regimes_layout.addWidget(self.group_label)
        self.panels.add_panel(regimes)
        self.split_section=CollapsiblePanel('固定划分与先验工况')
        self.split_section.content_layout.addWidget(self.panels)
        layout.addWidget(self.split_section)
        fields=CollapsiblePanel("字段与数据来源")
        fields_layout=fields.content_layout
        self.features_label = secondary("输入字段：—")
        fields_layout.addWidget(self.features_label)
        self.feature_units_label = secondary("")
        self.feature_units_label.hide()
        fields_layout.addWidget(self.feature_units_label)
        self.date_range_label = secondary("")
        self.date_range_label.hide()
        fields_layout.addWidget(self.date_range_label)
        self.excluded_label = secondary("排除字段：—")
        fields_layout.addWidget(self.excluded_label)
        self.provenance_label = secondary("来源：—\n许可：—\nSHA-256：—")
        self.provenance_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        fields_layout.addWidget(self.provenance_label)
        self.limitations_label = secondary("限制：—")
        fields_layout.addWidget(self.limitations_label)
        layout.addWidget(fields)
        self.manifest_panel = CollapsiblePanel("完整数据清单 · manifest")
        self.manifest_panel.set_expanded(False)
        self.manifest_view = QPlainTextEdit()
        self.manifest_view.setReadOnly(True)
        self.manifest_view.setPlaceholderText("来源、许可、校验、字段和划分索引将在校验后显示。")
        self.manifest_view.setFixedHeight(260)
        self.manifest_panel.content_layout.addWidget(self.manifest_view)
        layout.addWidget(self.manifest_panel)
        self.quality_panel=CollapsiblePanel('数据质量与工艺分析')
        self.quality_panel.content_layout.addWidget(secondary('尚未提供工业数据质量统计与过程序列。需要字段质量汇总、统计口径及带单位的时间序列；文件通过校验不代表已计算覆盖率或异常率。'))
        layout.addWidget(self.quality_panel)
        layout.addStretch()

    @staticmethod
    def _size_table(widget, count):
        widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setMinimumHeight(0)
        widget.setFixedHeight(widget.horizontalHeader().height() + max(count, 1) * 32 + 8)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择真实工业数据", "", "CSV data (*.csv);;All files (*)")
        if path:
            self.path_edit.setText(path)

    def _dataset_changed(self):
        from rac_hpo.data.registry import DEFAULT_PATHS
        self.path_edit.setText(DEFAULT_PATHS[self.dataset_combo.currentData()])

    def set_busy(self, busy):
        for widget in (self.dataset_combo, self.path_edit, self.browse_button, self.import_button):
            widget.setEnabled(not busy)

    def show_summary(self, summary):
        manifest = summary.get("manifest") or {}
        features = summary.get("feature_names", summary.get("features"))
        count = summary.get("row_count")
        self.metrics.set_metric("dataset", summary.get("dataset_id") or "—")
        self.metrics.set_metric("records", f"{count:,}" if isinstance(count, int) else "—")
        self.metrics.set_metric("features", len(features) if features is not None else "—")
        self.metrics.set_metric("target", summary.get("target") or "—")
        self.metrics.set_metric("unit", summary.get("target_unit") or "—")
        self.summary_label.setText(f"{summary.get('dataset_id') or '—'} · 文件已校验；实际划分与字段见下方。")
        self.header.set_context(summary.get("dataset_id") or "数据校验完成", "validated")
        regimes = summary.get("regimes") or {}
        rows = list(regimes.items()) if isinstance(regimes, dict) else [(str(item), None) for item in regimes]
        fill_table(self.regime_table, rows)
        self._size_table(self.regime_table, len(rows))
        splits = summary.get("split_counts") or {}
        fill_table(self.split_table, list(splits.items()))
        self._size_table(self.split_table, len(splits))
        self.split_label.setText("划分策略：" + str(manifest.get("split_strategy") or "见完整数据清单"))
        self.group_label.setText("分组定义：" + str(manifest.get("group_definition") or "—"))
        self.features_label.setText("输入字段：" + (", ".join(map(str, features)) if features else "—"))
        units = manifest.get("feature_units") or summary.get("feature_units")
        self.feature_units_label.setVisible(bool(units))
        if units:
            display = ", ".join(f"{key}: {value}" for key, value in units.items()) if isinstance(units, dict) else str(units)
            self.feature_units_label.setText("字段单位：" + display)
        date_range = manifest.get("date_range") or summary.get("date_range")
        self.date_range_label.setVisible(bool(date_range))
        if date_range:
            display = json.dumps(date_range, ensure_ascii=False, default=str) if isinstance(date_range, (dict, list)) else str(date_range)
            self.date_range_label.setText("数据时间范围：" + display)
        self.excluded_label.setText("排除字段：" + (", ".join(manifest.get("excluded_fields") or []) or "—"))
        self.provenance_label.setText(
            f"来源：{manifest.get('source_url') or '未核验 / 本地导入'}\n"
            f"许可：{manifest.get('license') or '未知'}\n"
            f"校验状态：{manifest.get('source_verification') or format_value(manifest.get('provenance_verified'))}\n"
            f"SHA-256：{summary.get('source_sha256') or manifest.get('source_sha256') or '—'}"
        )
        limitations = summary.get("limitations") or manifest.get("limitations") or []
        self.limitations_label.setText("限制：\n" + ("\n".join(map(str, limitations)) if limitations else "未提供额外限制说明"))
        self.manifest_view.setPlainText(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
