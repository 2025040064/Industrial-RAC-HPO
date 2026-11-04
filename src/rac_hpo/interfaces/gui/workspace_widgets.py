"""Reusable experiment workspace presentation; no storage or training dependencies."""

import json
import math
import weakref

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QTableView,
    QToolButton, QVBoxLayout, QWidget, QMenu,
)

from .theme import TOKENS
from .widgets import format_value, secondary


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


class ElidedLabel(QLabel):
    """Keep identifiers available to accessibility and tooltips at every width."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self.setAccessibleName(self._full_text)
        self._elide()

    def text(self):
        return self._full_text

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, max(0, self.contentsRect().width()),
        ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def sizeHint(self):
        return QSize(120, super().sizeHint().height())


class WorkspaceHeader(QWidget):
    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        top = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.title_label.setWordWrap(True)
        top.addWidget(self.title_label, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        top.addLayout(self.actions)
        layout.addLayout(top)
        self.subtitle_label = secondary(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))
        layout.addWidget(self.subtitle_label)
        self.status_label = secondary("")
        self.status_label.hide()
        layout.addWidget(self.status_label)

    def set_context(self, text, status=""):
        self.status_label.setText(str(text))
        self.status_label.setToolTip(str(text))
        self.status_label.setObjectName("error" if status == "failed" else "secondary")
        self.status_label.setVisible(bool(text))
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)


class MetricCard(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        self.title_label = ElidedLabel(title)
        self.title_label.setObjectName("secondary")
        self.value_label = ElidedLabel("—")
        self.value_label.setObjectName("statValue")
        self.caption_label = ElidedLabel("")
        self.caption_label.setObjectName("secondary")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.caption_label)


class MetricsGrid(QWidget):
    def __init__(self, specs, parent=None):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(TOKENS["spacing"])
        self.cards = {key: MetricCard(title) for key, title in specs}
        self.column_count = 0
        self._reflow()

    def set_metric(self, key, value, caption=None):
        card = self.cards[key]
        card.value_label.setText(format_value(value))
        if caption is not None:
            card.caption_label.setText(str(caption))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self):
        target = 4 if self.width() >= 900 else 2
        columns = min(target, max(1, len(self.cards)))
        if columns == self.column_count:
            return
        for index in range(self.grid.count()):
            self.grid.takeAt(0)
        for index in range(6):
            self.grid.setColumnStretch(index, int(index < columns))
        for index, card in enumerate(self.cards.values()):
            self.grid.addWidget(card, index // columns, index % columns)
        self.column_count = columns


class PanelGrid(QWidget):
    """Twelve-column grid; rebuild only when crossing the layout breakpoint."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(TOKENS["spacing"])
        for column in range(12):
            self.grid.setColumnStretch(column, 1)
        self.panels = []
        self.column_count = 0
        self._reflow()

    def add_panel(self, widget):
        widget.setMinimumWidth(0)
        self.panels.append(widget)
        self._reflow(force=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self, force=False):
        columns = 2 if self.width() >= 900 else 1
        if self.column_count == columns and not force:
            return
        while self.grid.count():
            self.grid.takeAt(0)
        span = 12 // columns
        for index, panel in enumerate(self.panels):
            self.grid.addWidget(panel, index // columns, (index % columns) * span, 1, span)
        self.column_count = columns


class CollapsiblePanel(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)
        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(True)
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle_button.setAccessibleName(f"展开或折叠{title}")
        layout.addWidget(self.toggle_button)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        layout.addWidget(self.content)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)
        self.toggle_button.toggled.connect(self.set_expanded)

    def set_expanded(self, expanded):
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(expanded)


class _RecordModel(QAbstractTableModel):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.owner.columns) + int(self.owner.workbench_mode)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        record = self.rows[index.row()]
        if self.owner.workbench_mode and index.column() == 0:
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if record.get('_id') in self.owner.checked_ids else Qt.CheckState.Unchecked
            if role == Qt.ItemDataRole.UserRole:return record
            if role == Qt.ItemDataRole.AccessibleTextRole:return '选择 '+str(record.get('_id'))
            return None
        column = index.column() - int(self.owner.workbench_mode)
        value = record.get(self.owner.columns[column][0])
        if role == Qt.ItemDataRole.UserRole:
            return record
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return _json(value) if isinstance(value, (dict, list)) else format_value(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(value, (float, int)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if self.owner.workbench_mode and section == 0:return "选"
            return self.owner.columns[section - int(self.owner.workbench_mode)][1]
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        column -= int(self.owner.workbench_mode)
        if 0 <= column < len(self.owner.columns):
            self.owner.sort_by(self.owner.columns[column][0], order)

    def flags(self,index):
        if self.owner.workbench_mode and index.column()==0:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
        return super().flags(index)

    def setData(self,index,value,role=Qt.ItemDataRole.EditRole):
        if self.owner.workbench_mode and index.column()==0 and role==Qt.ItemDataRole.CheckStateRole:
            self.owner.toggle_checked(self.rows[index.row()].get('_id'))
            return True
        return False


class RecordTable(QWidget):
    """Filter and order raw records before paging; never identify rows by position."""

    record_selected = Signal(object)
    details_requested = Signal(object)
    filtered_changed = Signal()
    checked_changed = Signal()

    def __init__(self, columns, filter_fields=(), parent=None):
        super().__init__(parent)
        self.columns = columns
        self.records = []
        self.workbench_mode = False
        self.checked_ids = set()
        self.extra_filter = None
        self.selection_limit = 8
        self.filtered_count = 0
        self.page_index = 0
        self._sort_key = None
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._selected_id = None
        self._repeat_click_id = None
        self._refreshing = False
        self._filtered = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        toolbar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索记录、参数或 ID")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(80)
        toolbar.addWidget(self.search_edit, 1)
        layout.addLayout(toolbar)
        self.toolbar = toolbar
        self._layout = layout
        filter_bar = QHBoxLayout()
        self.filters = {}
        titles = {"status": "状态", "algorithm": "算法", "dataset_id": "数据集"}
        for spec in filter_fields:
            key, title = spec if isinstance(spec, (list, tuple)) else (spec, titles.get(spec, spec))
            combo = QComboBox()
            combo.setAccessibleName(f"按{title}筛选")
            combo.setProperty("filter_title", title)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
            combo.addItem(f"全部{title}", None)
            combo.currentIndexChanged.connect(self._query_changed)
            self.filters[key] = combo
            filter_bar.addWidget(combo)
        if self.filters:
            filter_bar.addStretch()
            layout.addLayout(filter_bar)
        self.view = QTableView()
        self.model = _RecordModel(self)
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setWordWrap(False)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.verticalHeader().hide()
        self.view.verticalHeader().setDefaultSectionSize(36)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.view.setSortingEnabled(True)
        self.view.setMinimumWidth(0)
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.view.viewport().installEventFilter(self)
        self.view.clicked.connect(self._clicked)
        self.view.activated.connect(self._activated)
        layout.addWidget(self.view)
        pagination = QHBoxLayout()
        self.page_label = secondary("无记录")
        pagination.addWidget(self.page_label, 1)
        self.page_size_combo = QComboBox()
        for size in (25, 50, 100):
            self.page_size_combo.addItem(f"{size} / 页", size)
        self.page_size_combo.setAccessibleName("每页记录数")
        self.page_size_combo.currentIndexChanged.connect(self._query_changed)
        pagination.addWidget(self.page_size_combo)
        self.previous_button = QPushButton("上一页")
        self.next_button = QPushButton("下一页")
        self.previous_button.clicked.connect(lambda: self.set_page(self.page_index - 1))
        self.next_button.clicked.connect(lambda: self.set_page(self.page_index + 1))
        pagination.addWidget(self.previous_button)
        pagination.addWidget(self.next_button)
        layout.addLayout(pagination)
        self.pagination = pagination
        self.search_edit.textChanged.connect(self._query_changed)
        self._refresh()

    @property
    def selected_record(self):
        return next((record for record in self._filtered if record.get("_id") == self._selected_id), None)

    def rowCount(self):
        return self.model.rowCount()

    def set_records(self, records):
        self.records = [dict(record) for record in records]
        for key, combo in self.filters.items():
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(f"全部{combo.property('filter_title')}", None)
            values = {record.get(key) for record in self.records if record.get(key) is not None}
            for value in sorted(values, key=str):
                combo.addItem(str(value), value)
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            combo.blockSignals(False)
        self._refresh()

    def sort_by(self, key, order=Qt.SortOrder.AscendingOrder):
        self._sort_key = key
        self._sort_order = order
        self.page_index = 0
        self._refresh()

    def set_page(self, index):
        size = self.page_size_combo.currentData()
        self.page_index = min(max(0, index), max(0, (self.filtered_count - 1) // size))
        self._refresh()

    def _query_changed(self, *args):
        self.page_index = 0
        self._refresh()

    @staticmethod
    def _missing(value):
        return value is None or isinstance(value, float) and not math.isfinite(value)

    @staticmethod
    def _sort_value(value):
        if isinstance(value, (float, int)):
            return (0, value)
        return (1, str(value).casefold())

    def _refresh(self):
        query = self.search_edit.text().strip().casefold()
        records = [record for record in self.records if (
            (not query or query in _json(record).casefold()) and
            all(combo.currentData() is None or record.get(key) == combo.currentData()
                for key, combo in self.filters.items()) and
            (self.extra_filter is None or self.extra_filter(record))
        )]
        if self._sort_key is not None:
            key = self._sort_key
            available = [record for record in records if not self._missing(record.get(key))]
            missing = [record for record in records if self._missing(record.get(key))]
            available.sort(key=lambda record: self._sort_value(record.get(key)),
                           reverse=self._sort_order == Qt.SortOrder.DescendingOrder)
            records = available + missing
        self._filtered = records
        self.filtered_count = len(records)
        if not self.workbench_mode and not any(record.get("_id") == self._selected_id for record in records):
            self._selected_id = None
        size = self.page_size_combo.currentData()
        total_pages = max(1, (len(records) + size - 1) // size)
        self.page_index = min(self.page_index, total_pages - 1)
        rows = records[self.page_index * size:(self.page_index + 1) * size]
        self._refreshing = True
        self.model.beginResetModel()
        self.model.rows = rows
        self.model.endResetModel()
        for index, record in enumerate(rows):
            if self._selected_id is not None and record.get("_id") == self._selected_id:
                self.view.selectRow(index)
                break
        self._refreshing = False
        self.page_label.setText(f"{len(records)} 条 · {self.page_index + 1}/{total_pages}")
        self.previous_button.setEnabled(self.page_index > 0)
        self.next_button.setEnabled(self.page_index + 1 < total_pages)
        self._fit_height()
        if self.workbench_mode:
            self._update_selection_summary()
        self.filtered_changed.emit()

    def _fit_height(self):
        if self.workbench_mode:
            self.view.setMinimumHeight(90)
            self.view.setMaximumHeight(16777215)
            return
        # Reserve local horizontal-scroll space even before Qt updates its range.
        horizontal = self.view.horizontalScrollBar().sizeHint().height()
        header = max(36, self.view.horizontalHeader().sizeHint().height())
        height = header + max(1, len(self.model.rows)) * 36 + horizontal + 4
        self.view.setFixedHeight(height)

    def _selection_changed(self, *args):
        if self._refreshing:
            return
        indexes = self.view.selectionModel().selectedRows()
        if not indexes:
            self._selected_id = None
            return
        record = self.model.rows[indexes[0].row()]
        self._selected_id = record.get("_id")
        self.record_selected.emit(record)
        if self.workbench_mode:
            self.details_button.setEnabled(True)

    def eventFilter(self, watched, event):
        if self.workbench_mode and watched is self.view.viewport() and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space:
            if self._selected_id is not None:self.toggle_checked(self._selected_id)
            return True
        if watched is self.view.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            index = self.view.indexAt(event.position().toPoint())
            record = index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None
            self._repeat_click_id = (self._selected_id if record and
                                     record.get("_id") == self._selected_id else None)
        return super().eventFilter(watched, event)

    def _clicked(self, index):
        # A changed selection already emitted above. A second click on the same
        # row must reopen a closed drawer without fetching the record twice.
        identifier, self._repeat_click_id = self._repeat_click_id, None
        record = index.data(Qt.ItemDataRole.UserRole)
        if record and identifier is not None and record.get("_id") == identifier:
            self.record_selected.emit(record)

    def _activated(self, index):
        record = index.data(Qt.ItemDataRole.UserRole)
        if record:
            self.record_selected.emit(record)

    def enable_workbench(self, compact_keys=None):
        self.workbench_mode=True
        self._layout.setSpacing(6)
        self.setStyleSheet('QPushButton {padding:6px 8px;min-height:16px;}')
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self._layout.setStretchFactor(self.view,1)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.view.horizontalHeader().setDefaultSectionSize(100)
        self.view.setColumnWidth(0,32)
        self.details_button=QPushButton('查看详情')
        self.details_button.setEnabled(False)
        self.details_button.clicked.connect(self._request_details)
        self.clear_button=QPushButton('清除')
        self.clear_button.setAccessibleName('清除搜索与状态筛选')
        self.clear_button.clicked.connect(self.clear_filters)
        self.columns_button=QPushButton('列')
        menu=QMenu(self.columns_button)
        for i,(key,title) in enumerate(self.columns):
            action=menu.addAction(title); action.setCheckable(True)
            visible=compact_keys is None or key in compact_keys
            action.setChecked(visible); self.view.setColumnHidden(i+1,not visible)
            action.toggled.connect(lambda shown,column=i+1:self.view.setColumnHidden(column,not shown))
        self.columns_button.setMenu(menu)
        self.toolbar.addWidget(self.columns_button)
        self.toolbar.addWidget(self.clear_button)
        actions=QHBoxLayout(); actions.addWidget(self.details_button)
        self.clear_hidden_button=QPushButton('清除隐藏选择')
        self.clear_hidden_button.clicked.connect(self.clear_hidden_selection)
        actions.addWidget(self.clear_hidden_button)
        self._layout.insertLayout(2,actions)
        self.selection_label=secondary('已选择 0 / 8 条；勾选框独立于观察行')
        self._layout.insertWidget(3,self.selection_label)
        self.page_size_combo.hide()
        self.previous_button.setText('‹'); self.next_button.setText('›')
        self.previous_button.setAccessibleName('上一页');self.next_button.setAccessibleName('下一页')
        self.model.beginResetModel();self.model.endResetModel();self._refresh()

    @property
    def hidden_checked_count(self):
        return len(self.checked_ids-{r.get('_id') for r in self._filtered})

    def observe(self, identifier):
        if identifier == self._selected_id:
            return
        index = next((i for i, record in enumerate(self._filtered) if record.get('_id') == identifier), None)
        self._selected_id = identifier
        if index is None:
            self.view.clearSelection()
        elif index // self.page_size_combo.currentData() != self.page_index:
            self.set_page(index // self.page_size_combo.currentData())
        else:
            self._refreshing = True
            self.view.selectRow(index % self.page_size_combo.currentData())
            self._refreshing = False
        self._update_selection_summary()

    def toggle_checked(self,identifier):
        if identifier in self.checked_ids:self.checked_ids.remove(identifier)
        elif len(self.checked_ids)<self.selection_limit:self.checked_ids.add(identifier)
        else:
            self.selection_label.setText('最多选择 8 条；请先取消已有选择')
            return
        self.model.dataChanged.emit(self.model.index(0,0),self.model.index(max(0,self.model.rowCount()-1),0))
        self._update_selection_summary();self.checked_changed.emit()

    def _update_selection_summary(self):
        self.selection_label.setText(f'已选 {len(self.checked_ids)} / 8 · 隐藏 {self.hidden_checked_count}')
        self.clear_hidden_button.setEnabled(self.hidden_checked_count>0)
        self.details_button.setEnabled(self._selected_id is not None)

    def clear_hidden_selection(self):
        self.checked_ids.intersection_update(r.get('_id') for r in self._filtered)
        self._update_selection_summary();self.checked_changed.emit()

    def clear_filters(self):
        self.search_edit.clear()
        for combo in self.filters.values():combo.setCurrentIndex(0)
        self._refresh()

    def reset_context(self):
        self.checked_ids.clear();self._selected_id=None
        self.search_edit.blockSignals(True);self.search_edit.clear();self.search_edit.blockSignals(False)
        for combo in self.filters.values():
            combo.blockSignals(True);combo.setCurrentIndex(0);combo.blockSignals(False)
        self.page_index=0
        self._refresh()
        self.checked_changed.emit()

    def _request_details(self):
        record=next((r for r in self.records if r.get('_id')==self._selected_id),None)
        if record:self.details_requested.emit(record)



class RunDetailDrawer(QFrame):
    """Right-hand overlay bound to an experiment ID, with inline trial drilldown."""

    export_requested = Signal(str)
    view_experiment_requested = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("runDetailDrawer")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.experiment_id = None
        self._experiment = {}
        self._trial_number = None
        self._previous_focus = None
        self.trial_table = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        self.back_button = QPushButton("返回实验")
        self.back_button.clicked.connect(lambda: self.show_experiment(self._experiment))
        self.back_button.hide()
        heading.addWidget(self.back_button)
        self.title_label = QLabel("运行详情")
        self.title_label.setObjectName("cardTitle")
        self.title_label.setWordWrap(True)
        heading.addWidget(self.title_label, 1)
        self.close_button = QPushButton("关闭")
        self.close_button.setAccessibleName("关闭运行详情，快捷键 Escape")
        self.close_button.clicked.connect(self.close_drawer)
        heading.addWidget(self.close_button)
        layout.addLayout(heading)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll, 1)
        self.actions = QHBoxLayout()
        self.export_button = QPushButton("导出实验")
        self.export_button.clicked.connect(lambda: self.export_requested.emit(self.experiment_id))
        self.view_button = QPushButton("在工作区查看")
        self.view_button.clicked.connect(lambda: self.view_experiment_requested.emit(self.experiment_id))
        self.actions.addWidget(self.export_button)
        self.actions.addWidget(self.view_button)
        layout.addLayout(self.actions)
        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._escape_shortcut.activated.connect(self.close_drawer)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._position()
        if self.isVisible() and event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
        ):
            if watched is self or isinstance(watched, QWidget) and self.isAncestorOf(watched):
                backwards = event.key() == Qt.Key.Key_Backtab or bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier,
                )
                self._move_focus(backwards)
                return True
        return super().eventFilter(watched, event)

    def _move_focus(self, backwards):
        candidates = []
        widget = self.nextInFocusChain()
        while widget is not self:
            if (self.isAncestorOf(widget) and widget.isVisible() and widget.isEnabled()
                    and widget.focusPolicy() & Qt.FocusPolicy.TabFocus):
                candidates.append(widget)
            widget = widget.nextInFocusChain()
        if not candidates:
            self.close_button.setFocus()
            return
        focused = QApplication.focusWidget()
        step = -1 if backwards else 1
        index = candidates.index(focused) if focused in candidates else (0 if backwards else -1)
        candidates[(index + step) % len(candidates)].setFocus(
            Qt.FocusReason.BacktabFocusReason if backwards else Qt.FocusReason.TabFocusReason,
        )

    def _position(self):
        host = self.parentWidget()
        width = host.width() if host.window().width() < 1024 else min(480, host.width())
        self.setGeometry(host.width() - width, 0, width, host.height())

    def _open(self):
        opening = not self.isVisible()
        if opening:
            focused = QApplication.focusWidget()
            self._previous_focus = weakref.ref(focused) if focused else None
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)
        self._position()
        self.show()
        self.raise_()
        if opening:
            self.close_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _reset_content(self):
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(14)
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.scroll.setWidget(content)
        self.trial_table = None
        self._sections = {}
        self._raw_panel = None
        self._raw_label = None
        self._raw_record = None

    def _section(self, title, values):
        if title not in self._sections:
            section = QWidget()
            rows = QVBoxLayout(section)
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(5)
            heading = QLabel(title)
            heading.setObjectName("cardTitle")
            rows.addWidget(heading)
            self._sections[title] = (section, rows, {})
            self.content_layout.addWidget(section)
        section, rows, labels = self._sections[title]
        section.setVisible(bool(values))
        for key, label in labels.items():
            label.setVisible(key in values)
        for key, value in values.items():
            display = _json(value) if isinstance(value, (dict, list)) else format_value(value)
            if key not in labels:
                label = QLabel()
                label.setWordWrap(True)
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                label.setMinimumWidth(0)
                rows.addWidget(label)
                labels[key] = label
            labels[key].setText(f"{key}：{display}")
            labels[key].show()

    def _metrics(self, metrics, unit):
        if not metrics:
            self._section("评价指标", {"结果": "尚无已保存的评价指标"})
            self._section("分工况指标", {})
            self._section("分组指标", {})
            return
        names = {"overall_mae": f"验证 MAE ({unit})", "robust_objective": "固定 J（无量纲）"}
        self._section("评价指标", {names.get(key, key): value for key, value in metrics.items()
                                  if key not in {"regimes", "groups"}})
        self._section("分工况指标", metrics.get("regimes", {}))
        self._section("分组指标", metrics.get("groups", {}))

    def _raw(self, record):
        self._raw_record = record
        if self._raw_panel is not None:
            if self._raw_panel.toggle_button.isChecked():
                self._raw_label.setText(_json(record))
            return
        panel = CollapsiblePanel("原始 JSON")
        raw = QLabel()
        raw.setWordWrap(True)
        raw.setTextFormat(Qt.TextFormat.PlainText)
        raw.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        raw.setMinimumWidth(0)
        panel.content_layout.addWidget(raw)
        panel.set_expanded(False)
        panel.toggle_button.toggled.connect(
            lambda expanded: raw.setText(_json(self._raw_record)) if expanded else None,
        )
        self._raw_panel, self._raw_label = panel, raw
        self.content_layout.addWidget(panel)

    def show_experiment(self, result):
        reuse = (self.isVisible() and self._trial_number is None and
                 self.experiment_id == str(result.get("id", "")))
        self._experiment = result
        self.experiment_id = str(result.get("id", ""))
        self._trial_number = None
        self.title_label.setText("实验详情")
        self.back_button.hide()
        if not reuse:
            self._reset_content()
        config = result.get("config", {})
        unit = result.get("target_unit") or "单位未记录"
        self._section("运行", {"ID": self.experiment_id, "状态": result.get("status"),
                               "算法": result.get("algorithm"), "数据集": result.get("dataset_id"),
                               "模型": config.get("model", {}).get("name"),
                               "创建时间": result.get("created_at"), "结束时间": result.get("ended_at")})
        objective_name = "最佳 J（无量纲）" if result.get("algorithm") in {"tpe_robust", "rac_hpo"} else f"最佳 MAE ({unit})"
        self._section("优化结果", {objective_name: result.get("best_value"), "最佳试验编号": result.get("best_trial"),
                                    "最佳迭代数": result.get("best_iteration")})
        self._metrics(result.get("metrics", {}), unit)
        self._section("耗时与种子", {"实验总耗时 (s)": result.get("duration_seconds"),
                                      "基线训练耗时 (s)": result.get("baseline_duration_seconds"),
                                      "搜索耗时 (s)": result.get("search_duration_seconds"),
                                      "随机种子": config.get("experiment", {}).get("seed")})
        self._section("最佳参数", result.get("best_params", {}))
        self._section("候选排序诊断", result.get("search_diagnostics", {}))
        self._section("失败或取消原因", {"原因": result["failure_reason"]} if result.get("failure_reason") else {})
        trials = result.get("trials", [])
        if self.trial_table is None:
            label = QLabel("试验记录 · 选择一行查看参数")
            label.setObjectName("cardTitle")
            label.setWordWrap(True)
            self.content_layout.addWidget(label)
            self.trial_table = RecordTable([("number", "编号"), ("status", "状态"),
                                           ("objective", "J（无量纲）" if result.get("algorithm") in {"tpe_robust", "rac_hpo"}
                                            else f"MAE ({unit})")])
            self.trial_table.record_selected.connect(lambda trial: self.show_trial(self._experiment, trial))
            self.content_layout.addWidget(self.trial_table)
        self.trial_table.set_records([{**trial, "_id": f"{self.experiment_id}:{trial.get('number')}"} for trial in trials])
        self._section("配置", config)
        self._section("产物", result.get("artifacts", {}))
        self._raw(result)
        if not reuse:
            self.content_layout.addStretch()
        self.view_button.setVisible(result.get("algorithm") != "baseline")
        self._open()

    def show_trial(self, experiment, trial):
        trial = next((record for record in experiment.get("trials", [])
                      if record.get("number") == trial.get("number")), trial)
        self._experiment = experiment
        self.experiment_id = str(experiment.get("id", ""))
        self._trial_number = trial.get("number")
        number = trial.get("number")
        self.title_label.setText("默认基线" if number == -1 else f"试验 #{number}")
        self.back_button.show()
        self._reset_content()
        self._section("试验", {"实验 ID": self.experiment_id, "编号": number,
                               "状态": trial.get("status"), "角色": trial.get("role"),
                               "随机种子": trial.get("seed"), "试验耗时 (s)": trial.get("duration_seconds")})
        # Completed records include model construction, fitting and validation;
        # failed/cancelled records contain elapsed wall time up to termination.
        duration_caption = ("成功试验耗时包含模型构建、拟合与验证。" if trial.get("status") == "completed"
                            else "剪枝、失败或取消试验耗时为终止前实际经过的时间。")
        self.content_layout.addWidget(secondary(duration_caption))
        unit = experiment.get("target_unit") or "单位未记录"
        objective_name = "J（无量纲）" if experiment.get("algorithm") in {"tpe_robust", "rac_hpo"} else f"MAE ({unit})"
        self._section("优化目标", {objective_name: trial.get("objective")})
        self._metrics(trial.get("metrics", {}), unit)
        self._section("超参数", trial.get("params", {}))
        self._section("候选选择", trial.get("selection", {}))
        if trial.get("resource"):
            self._section("资源调度", trial["resource"])
        if trial.get("pruning_reason"):
            self._section("剪枝原因", {"原因": trial["pruning_reason"]})
        if trial.get("selection_duration_seconds") is not None:
            self._section("选择耗时", {"耗时 (s)": trial["selection_duration_seconds"]})
        if trial.get("failure_reason"):
            self._section("失败或取消原因", {"原因": trial["failure_reason"]})
        self._raw(trial)
        self.content_layout.addStretch()
        self.view_button.setVisible(experiment.get("algorithm") != "baseline")
        self._open()

    def update_experiment(self, result):
        if not self.isVisible() or result.get("id") != self.experiment_id:
            return
        if self._trial_number is not None:
            trial = next((trial for trial in result.get("trials", []) if trial.get("number") == self._trial_number), None)
            if trial is not None:
                previous = next((item for item in self._experiment.get("trials", [])
                                 if item.get("number") == self._trial_number), None)
                self._experiment = result
                if previous == trial:
                    return
                self.show_trial(result, trial)
                return
        self.show_experiment(result)

    def close_drawer(self):
        self.hide()
        previous = self._previous_focus() if self._previous_focus else None
        if previous is not None:
            try:
                previous.setFocus(Qt.FocusReason.OtherFocusReason)
            except RuntimeError:
                pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_drawer()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.close_drawer()
        event.accept()
