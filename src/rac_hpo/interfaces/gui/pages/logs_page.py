from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from ..widgets import card, secondary
from ..workspace_widgets import WorkspaceHeader


class LogsPage(QWidget):
    export_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lines = []
        self.total_events = 0
        self.matched_events = 0
        self._toolbar_wide = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.header = WorkspaceHeader("运行日志 · 当前会话", "实时查看本次会话事件；搜索和清空显示不会改动后端实验日志。")
        layout.addWidget(self.header)
        summary=QHBoxLayout()
        self.total_label=QLabel();self.matched_label=QLabel()
        summary.addWidget(self.total_label);summary.addWidget(self.matched_label);summary.addStretch()
        summary.addWidget(secondary('Asia/Singapore · +08:00'))
        layout.addLayout(summary)
        self._update_counts()
        logs, logs_layout = card("任务事件")
        logs_layout.setSpacing(12)
        self.toolbar = QWidget()
        self.toolbar_layout = QGridLayout(self.toolbar)
        self.toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar_layout.setHorizontalSpacing(8)
        self.toolbar_layout.setVerticalSpacing(8)
        self.filter_edit = QLineEdit()
        self.filter_edit.setMinimumWidth(80)
        self.filter_edit.setPlaceholderText("搜索日志 · 不区分大小写")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._render)
        self.copy_button = QPushButton("复制")
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.view.toPlainText()))
        self.export_button = QPushButton("导出日志")
        self.export_button.clicked.connect(lambda: self.export_requested.emit(self.view.toPlainText()))
        self.clear_button = QPushButton("清空显示")
        self.clear_button.clicked.connect(self.clear_display)
        self.auto_scroll = QCheckBox("自动滚动")
        self.auto_scroll.setChecked(True)
        self.auto_scroll.toggled.connect(self._auto_scroll_changed)
        self._layout_toolbar(False)
        logs_layout.addWidget(self.toolbar)
        logs_layout.addWidget(secondary("清空只移除窗口中的日志，不删除实验、数据库或后端文件。"))
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setMinimumHeight(60)
        self.view.setAccessibleName("当前会话实际任务日志，可搜索、复制与导出")
        logs_layout.addWidget(self.view, 1)
        layout.addWidget(logs, 1)

    def _layout_toolbar(self, wide):
        if wide == self._toolbar_wide:
            return
        self._toolbar_wide = wide
        while self.toolbar_layout.count():
            self.toolbar_layout.takeAt(0)
        self.toolbar_layout.setColumnStretch(0, 1)
        if wide:
            for column, widget in enumerate((self.filter_edit, self.auto_scroll, self.copy_button, self.export_button, self.clear_button)):
                self.toolbar_layout.addWidget(widget, 0, column)
        else:
            self.toolbar_layout.addWidget(self.filter_edit, 0, 0, 1, 4)
            for column, widget in enumerate((self.auto_scroll, self.copy_button, self.export_button, self.clear_button)):
                self.toolbar_layout.addWidget(widget, 1, column)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_toolbar(self.width() >= 600)

    def _update_counts(self):
        self.total_label.setText(f"收到 {self.total_events} 条事件")
        self.matched_label.setText(f"当前匹配 {self.matched_events} 条")

    def append(self, message):
        display_time = datetime.now(timezone(timedelta(hours=8)))
        line = f"{display_time.isoformat(timespec='seconds')}  {message}"
        self.lines.append(line)
        self.total_events += 1
        query = self.filter_edit.text().casefold()
        if query in line.casefold():
            self.matched_events += 1
            scrollbar = self.view.verticalScrollBar()
            previous = scrollbar.value()
            # appendPlainText only inserts new blocks instead of rebuilding prior logs.
            self.view.appendPlainText(line)
            if self.auto_scroll.isChecked():
                scrollbar.setValue(scrollbar.maximum())
            else:
                scrollbar.setValue(previous)
        self._update_counts()

    def _render(self):
        query = self.filter_edit.text().casefold()
        matches = [line for line in self.lines if query in line.casefold()]
        scrollbar = self.view.verticalScrollBar()
        previous = scrollbar.value()
        self.view.setPlainText("\n".join(matches))
        self.matched_events = len(matches)
        scrollbar.setValue(scrollbar.maximum() if self.auto_scroll.isChecked() else min(previous, scrollbar.maximum()))
        self._update_counts()

    def _auto_scroll_changed(self, enabled):
        if enabled:
            self.view.moveCursor(QTextCursor.MoveOperation.End)

    def clear_display(self):
        self.lines.clear()
        self.view.clear()
        self.matched_events = 0
        self._update_counts()
