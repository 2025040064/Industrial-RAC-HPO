"""Native workspace layout and read-only comparisons; no backend dependencies."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView
from .widgets import secondary, format_value
from .workspace_state import display_time

class ResponsiveWorkspace(QWidget):

    def __init__(self, records, content, title, parent=None):
        super().__init__(parent)
        self.records = records
        self._wide = None
        self._breakpoint = None
        self._saved_width = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.browse_button = QPushButton('浏览 ' + title)
        self.browse_button.setAccessibleName('打开' + title + '列表')
        self.browse_button.clicked.connect(self.open_records)
        layout.addWidget(self.browse_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        records.setMinimumWidth(280)
        records.setMaximumWidth(440)
        self.splitter.addWidget(records)
        self.splitter.addWidget(content)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(self._remember_width)
        layout.addWidget(self.splitter, 1)
        self.list_dialog = QDialog(self)
        self.list_dialog.setWindowTitle(title)
        self.list_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog_layout = QVBoxLayout(self.list_dialog)
        close = QPushButton('关闭列表 · Esc')
        close.clicked.connect(self.list_dialog.close)
        dialog_layout.addWidget(close)
        self.dialog_layout = dialog_layout
        self.list_dialog.finished.connect(lambda: self.browse_button.setFocus())
        self.update_layout()

    def _remember_width(self, *args):
        if self._wide:
            self._saved_width = self.splitter.sizes()[0]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_layout()

    def showEvent(self, event):
        super().showEvent(event)
        self.update_layout()

    def update_layout(self):
        width = self.window().width()
        wide = width >= 1024
        breakpoint = 2 if width >= 1440 else 1 if wide else 0
        if wide == self._wide:
            if wide and breakpoint != self._breakpoint and (self._saved_width is None):
                left = 320 if breakpoint == 2 else 280
                self.splitter.setSizes([left, max(1, self.width() - left)])
            self._breakpoint = breakpoint
            return
        self._breakpoint = breakpoint
        self._wide = wide
        self.browse_button.setVisible(not wide)
        if wide:
            self.list_dialog.hide()
            self.splitter.insertWidget(0, self.records)
            self.records.show()
            left = self._saved_width or (320 if width >= 1440 else 280)
            self.splitter.setSizes([left, max(1, self.width() - left)])
        else:
            self.dialog_layout.addWidget(self.records, 1)
            self.records.show()
            self.list_dialog.hide()

    def open_records(self):
        self.list_dialog.resize(min(480, self.window().width() - 40), max(420, self.window().height() - 48))
        self.list_dialog.open()
        self.records.setFocus()

class ComparisonPanel(QFrame):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('card')
        self.count = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel('所选记录并排查看')
        title.setObjectName('cardTitle')
        layout.addWidget(title)
        self.scope_label = secondary('勾选 2–8 条记录后点击对比；观察行与勾选集合独立。')
        layout.addWidget(self.scope_label)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAccessibleName('真实记录并排查看表')
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(240)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(280)
        layout.addWidget(self.table)

    def set_records(self, records, *, trials=False, unit=None):
        self.count = len(records)
        self.table.clear()
        if not 2 <= len(records) <= 8:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.scope_label.setText('请选择 2–8 条记录；不保留已失效的对比结果。')
            return
        if trials:
            self.scope_label.setText('同一实验的搜索 Trial；所有值来自保存记录，缺失显示 —。')
            fields = [('number', 'Trial'), ('status', '状态'), ('objective', '优化目标'), ('mae', '验证 MAE / ' + str(unit or '单位未记录')), ('duration_seconds', '训练耗时 / s'), ('params', '实际参数')]
            values = [{**r, 'mae': (r.get('metrics') or {}).get('overall_mae')} for r in records]
        else:
            self.scope_label.setText('仅并排查看，不排名：当前接口未提供固定划分与目标/特征版本证据。MAE 按各列单位；J 固定目标定义须另行核对。')
            fields = [('id', '实验 ID'), ('created_at', '创建时间 / Asia/Singapore'), ('dataset_id', '数据集'), ('data_sha256', '数据 SHA-256'), ('model', '模型'), ('algorithm', '算法'), ('status', '状态'), ('unit', 'MAE 单位'), ('mae', '已选模型验证 MAE'), ('j', '已选模型固定 J / 无量纲'), ('duration_seconds', '实验总耗时 / s'), ('budget', '搜索预算'), ('params', '已选参数'), ('fixed_objective', '固定目标定义')]
            values = []
            for r in records:
                config = r.get('config') or {}
                metrics = r.get('metrics') or {}
                values.append({**r, 'created_at': display_time(r.get('created_at')), 'model': config.get('model', {}).get('name'), 'unit': r.get('target_unit'), 'mae': metrics.get('overall_mae'), 'j': metrics.get('robust_objective'), 'budget': config.get('optimization'), 'params': r.get('best_params')})
        self.table.setRowCount(len(fields))
        self.table.setColumnCount(len(values))
        self.table.setVerticalHeaderLabels([title for key, title in fields])
        self.table.setHorizontalHeaderLabels([str(r.get('id') or '#' + str(r.get('number'))) for r in records])
        for col, record in enumerate(values):
            for row, (key, title) in enumerate(fields):
                value = record.get(key)
                text = json.dumps(value, ensure_ascii=False, indent=2, default=str) if isinstance(value, (dict, list)) else format_value(value)
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, col, item)
