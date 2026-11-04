"""Small presentation widgets; no training or storage dependencies."""

import math

from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QLabel, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .theme import TOKENS


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
