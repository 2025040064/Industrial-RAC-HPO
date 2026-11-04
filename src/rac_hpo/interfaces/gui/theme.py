"""Shared design tokens for the desktop application."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap


TOKENS = {
    "background": "#F7F8FA",
    "card": "#FFFFFF",
    "text": "#17212F",
    "secondary": "#526174",
    "accent": "#1677FF",
    "accent_strong": "#0958D9",
    "control_border": "#7B8798",
    "border": "#E5E7EB",
    "disabled": "#AEAEB2",
    "selection": "#EAF3FF",
    "danger": "#B42318",
    "radius": 6,
    "card_radius": 12,
    "spacing": 16,
    "content_margin": 24,
    # Collapsing sidebar. Separate keys so the navigation rail can follow the
    # specified values without changing the global accent used by buttons.
    "nav_text": "#526174",
    "nav_selected_bg": "#E9F2FF",
    "nav_selected": "#1677FF",
}


def apply_theme(app):
    # Qt's Windows offscreen plugin may have no system font database. Reference
    # fonts already installed on this machine; no font files are bundled/copied.
    font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    if not QFontDatabase.families():
        for filename in ("segoeui.ttf", "seguisb.ttf"):
            path = font_directory / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    if not QFontDatabase.families(QFontDatabase.WritingSystem.SimplifiedChinese):
        for filename in ("msyh.ttc", "msyhbd.ttc"):
            path = font_directory / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    available = set(QFontDatabase.families())
    preferred = (("SF Pro Text", "Helvetica Neue") if sys.platform == "darwin"
                 else ("SF Pro Text", "Segoe UI Variable", "Segoe UI"))
    family = next(
        (name for name in preferred if name in available),
        "sans-serif",
    )
    font = QFont(family, 10)
    fallback_names = (("Heiti SC", "Songti SC") if sys.platform == "darwin"
                      else ("Microsoft YaHei UI", "Microsoft YaHei", "SimSun"))
    fallback = [name for name in fallback_names if name in available]
    font.setFamilies([family, *fallback])
    app.setFont(font)
    t = TOKENS
    app.setStyleSheet(f"""
        QWidget {{ color: {t['text']}; font-size: 13px; }}
        QMainWindow, QWidget#workspace, QScrollArea, QScrollArea > QWidget > QWidget {{
            background: {t['background']};
        }}
        QWidget#topbar {{ background: {t['card']}; border-bottom: 1px solid {t['border']}; }}
        QWidget#sidebar {{ background: {t['card']}; border-right: 1px solid {t['border']}; }}
        QFrame#card {{ background: {t['card']}; border: 1px solid {t['border']};
            border-radius: {t['card_radius']}px; }}
        QFrame#runDetailDrawer {{ background: {t['card']}; border-left: 1px solid {t['border']}; }}
        QLabel#pageTitle {{ font-size: 24px; font-weight: 600; }}
        QLabel#cardTitle {{ font-size: 16px; font-weight: 600; }}
        QLabel#brand {{ font-size: 18px; font-weight: 600; }}
        QLabel#secondary {{ color: {t['secondary']}; }}
        QLabel#statValue {{ font-size: 23px; font-weight: 600; }}
        QLabel#badge {{ background: {t['selection']}; color: {t['accent_strong']};
            border-radius: 10px; padding: 6px 12px; }}
        QLabel#error {{ color: {t['danger']}; }}
        QPushButton {{ background: {t['card']}; border: 1px solid {t['control_border']};
            border-radius: {t['radius']}px; padding: 9px 16px; min-height: 18px; }}
        QPushButton:hover {{ background: {t['background']}; border-color: {t['control_border']}; }}
        QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 2px solid {t['accent']}; }}
        QPushButton#primary {{ background: {t['accent_strong']}; color: white; border-color: {t['accent']}; }}
        QPushButton#primary:hover {{ background: #0069DD; }}
        QPushButton:disabled {{ color: {t['disabled']}; background: {t['background']};
            border-color: {t['border']}; }}
        QPushButton#primary:disabled {{ background: {t['border']}; color: {t['secondary']}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {t['card']}; border: 1px solid {t['control_border']};
            border-radius: 6px; padding: 8px; min-height: 18px; selection-background-color: {t['accent']}; }}
        QComboBox::drop-down {{ border: 0px; width: 24px; }}
        QListWidget#navigation {{ background: transparent; border: none; outline: 0; padding: 0; }}
        QListWidget#navigation::item {{ padding: 0; margin: 0; border: none; }}
        QListWidget#navigation::item:selected {{ background: transparent; }}
        QListWidget#navigation::item:hover {{ background: transparent; }}
        QToolButton#sidebarToggle {{ background: transparent; border: none; border-radius: 8px; }}
        QToolButton#sidebarToggle:hover {{ background: {t['background']}; }}
        QToolButton#sidebarToggle:pressed {{ background: {t['border']}; }}
        QToolButton {{ border: none; background: transparent; padding: 4px;
            text-align: left; font-weight: 600; }}
        QToolButton:hover {{ background: {t['selection']}; border-radius: 6px; }}
        QPlainTextEdit, QTableWidget, QTableView {{ background: {t['card']}; border: 1px solid {t['border']};
            border-radius: 10px; padding: 6px; selection-background-color: {t['selection']};
            selection-color: {t['text']}; gridline-color: {t['border']}; }}
        QTableWidget, QTableView {{ alternate-background-color: #FAFBFC; padding: 0; }}
        QHeaderView::section {{ background: {t['background']}; border: 0;
            border-bottom: 1px solid {t['border']}; padding: 9px; color: {t['secondary']}; }}
        QProgressBar {{ background: {t['border']}; border: none; border-radius: 4px;
            height: 7px; max-height: 7px; }}
        QProgressBar::chunk {{ background: {t['accent']}; border-radius: 4px; }}
        QScrollArea {{ border: 0; }}
        QStatusBar {{ background: {t['card']}; color: {t['secondary']}; border-top: 1px solid {t['border']}; }}
    """)


def navigation_icon(index, color=None, size=24, dpr=1.0):
    """Draw one navigation glyph. Geometry is authored on a 24px grid."""
    pixmap = QPixmap(round(size * dpr), round(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24.0, size / 24.0)
    painter.setPen(QPen(QColor(color or TOKENS["secondary"]), 1.5))
    if index == 0:
        painter.drawRoundedRect(4, 4, 16, 16, 3, 3)
        painter.drawLine(4, 10, 20, 10)
        painter.drawLine(10, 10, 10, 20)
    elif index == 1:
        painter.drawEllipse(4, 4, 16, 16)
        painter.drawLine(10, 8, 16, 12)
        painter.drawLine(16, 12, 10, 16)
        painter.drawLine(10, 16, 10, 8)
    elif index == 2:
        for x, y in ((6, 8), (12, 16), (18, 10)):
            painter.drawLine(x, 3, x, 21)
            painter.setBrush(QColor(TOKENS["card"]))
            painter.drawEllipse(x - 2, y - 2, 4, 4)
    elif index == 3:
        for x, y in ((5, 13), (11, 7), (17, 10)):
            painter.drawRoundedRect(x, y, 3, 20 - y, 1, 1)
    elif index == 5:
        painter.drawArc(4, 4, 16, 16, 35 * 16, 285 * 16)
        painter.drawLine(18, 3, 20, 8)
        painter.drawLine(20, 8, 15, 8)
        painter.drawLine(10, 9, 15, 12)
        painter.drawLine(15, 12, 10, 15)
        painter.drawLine(10, 15, 10, 9)
    else:
        painter.drawRoundedRect(4, 3, 16, 18, 2, 2)
        for y in (8, 12, 16):
            painter.drawLine(8, y, 16, y)
    painter.end()
    return QIcon(pixmap)


def chevron_icon(point_right, color=None, size=16):
    """Small disclosure chevron for the sidebar toggle."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 16.0, size / 16.0)
    pen = QPen(QColor(color or TOKENS["nav_text"]), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    if point_right:
        painter.drawLine(6, 4, 10, 8)
        painter.drawLine(10, 8, 6, 12)
    else:
        painter.drawLine(10, 4, 6, 8)
        painter.drawLine(6, 8, 10, 12)
    painter.end()
    return QIcon(pixmap)
