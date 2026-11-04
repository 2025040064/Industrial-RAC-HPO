"""Small presentation widgets; no training or storage dependencies."""

import math
import time

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractScrollArea, QFrame, QHeaderView, QLabel, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .theme import TOKENS


class WheelGuard(QObject):
    """Let the wheel scroll the page unless the pointer deliberately rests on an input.

    Qt lets a spin box or combo box grab the wheel while merely hovered, so scrolling a
    long page silently rewrites the search algorithm or the trial budget. Blocking the
    wheel outright makes the page stutter whenever the cursor crosses an input, so this
    guard waits for a short dwell instead: a passing cursor scrolls the page as usual,
    a resting cursor may adjust the value.
    """

    DWELL_MS = 500

    def __init__(self, parent=None, dwell_ms=None):
        super().__init__(parent)
        self.dwell_ms = self.DWELL_MS if dwell_ms is None else dwell_ms
        self._entered_at = {}

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.Enter:
            self._entered_at[watched] = time.monotonic()
        elif kind == QEvent.Type.Leave:
            self._entered_at.pop(watched, None)
        elif kind == QEvent.Type.Wheel:
            # Dwell alone decides: a user who means to adjust the value keeps the pointer
            # there, so focus is not needed and must not be trusted, because Qt can hand
            # focus to an input on show or on Tab without the user ever touching it.
            # Baymard and NN/g both put hover intent at 300-500 ms; the default sits at
            # the conservative end of that band.
            entered = self._entered_at.get(watched)
            dwelled = entered is not None and (time.monotonic() - entered) * 1000.0 >= self.dwell_ms
            if not dwelled:
                self._scroll_ancestor(watched, event)
                event.ignore()
                return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _scroll_ancestor(watched, event):
        """Hand the wheel to the enclosing scroll area so the page keeps moving."""
        area = watched.parent()
        while area is not None and not isinstance(area, QAbstractScrollArea):
            area = area.parent()
        if area is None:
            return
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        bar = area.verticalScrollBar()
        bar.setValue(bar.value() - int(round(steps * bar.singleStep() * 3)))


def secondary(text):
    label = QLabel(text)
    label.setObjectName("secondary")
    label.setWordWrap(True)
    return label


def card(title):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 20)
    layout.setSpacing(TOKENS["spacing"])
    label = QLabel(title)
    label.setObjectName("cardTitle")
    layout.addWidget(label)
    return frame, layout


def page_layout(title, subtitle):
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    layout = QVBoxLayout(content)
    margin = TOKENS["content_margin"]
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(TOKENS["spacing"])
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    layout.addWidget(heading)
    layout.addWidget(secondary(subtitle))
    scroll.setWidget(content)
    outer.addWidget(scroll)
    return page, layout


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().hide()
    widget.setAlternatingRowColors(True)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setMinimumHeight(180)
    return widget


def fill_table(widget, rows):
    widget.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            item = QTableWidgetItem(format_value(value))
            item.setToolTip(str(value) if value is not None else "")
            widget.setItem(row_index, column_index, item)


def format_value(value):
    if value is None or isinstance(value,float) and not math.isfinite(value):
        return "—"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
