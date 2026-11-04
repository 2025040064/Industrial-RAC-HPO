"""Fixed 56 logical-pixel navigation with one non-layout tooltip."""
import os
import sys
from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget
from .theme import TOKENS, navigation_icon
RAIL_WIDTH = 56
ICON_SIZE = 20
ITEM_HEIGHT = 44
TOOLTIP_DELAY_MS = 250
TOOLTIP_CLOSE_MS = 100

def industrial_icon(color, dpr):
    pixmap = QPixmap(round(ICON_SIZE * dpr), round(ICON_SIZE * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(ICON_SIZE / 24, ICON_SIZE / 24)
    painter.setPen(QPen(QColor(color), 1.5))
    painter.drawRect(3, 10, 18, 11)
    painter.drawLine(3, 10, 8, 6)
    painter.drawLine(8, 6, 8, 10)
    painter.drawLine(8, 10, 13, 6)
    painter.drawLine(13, 6, 13, 10)
    painter.drawRect(17, 3, 3, 7)
    for x in (7, 12, 17):
        painter.drawLine(x, 14, x, 18)
    painter.end()
    return QIcon(pixmap)

def reduced_motion_enabled():
    """Honour the OS "reduce animation" preference; RAC_HPO_REDUCED_MOTION overrides."""
    override = os.environ.get('RAC_HPO_REDUCED_MOTION')
    if override is not None:
        return override.strip().lower() not in ('0', 'false', 'no', '')
    if sys.platform == 'win32':
        try:
            import ctypes
            enabled = ctypes.c_int(0)
            if ctypes.windll.user32.SystemParametersInfoW(4162, 0, ctypes.byref(enabled), 0):
                return not bool(enabled.value)
        except (AttributeError, OSError):
            pass
    return False

class NavigationDelegate(QStyledItemDelegate):

    def __init__(self, rail):
        super().__init__(rail)
        self.rail = rail

    def sizeHint(self, option, index):
        return QSize(40, ITEM_HEIGHT)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(1, 2, -1, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(Qt.PenStyle.NoPen)
        if selected or hovered:
            painter.setBrush(QColor(TOKENS['nav_selected_bg'] if selected else TOKENS['background']))
            painter.drawRoundedRect(rect, 6, 6)
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(TOKENS['accent']), 2))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)
        icon_rect = option.rect.adjusted((option.rect.width() - ICON_SIZE) // 2, (ITEM_HEIGHT - ICON_SIZE) // 2, 0, 0)
        icon_rect.setSize(QSize(ICON_SIZE, ICON_SIZE))
        color = TOKENS['nav_selected'] if selected else TOKENS['nav_text']
        self.rail.icon_for(index.row(), color).paint(painter, icon_rect)
        painter.restore()

class NavigationRail(QWidget):

    def __init__(self, parent=None, *, footer_text=''):
        super().__init__(parent)
        self.setObjectName('sidebar')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(RAIL_WIDTH)
        self._icon_cache = {}
        self._hover_row = -1
        self._dismissed_row = -1
        self._pending_row = -1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        self.navigation = QListWidget()
        self.navigation.setObjectName('navigation')
        self.navigation.setAccessibleName('主要页面导航')
        self.navigation.setFrameShape(QFrame.Shape.NoFrame)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setUniformItemSizes(True)
        self.navigation.setMouseTracking(True)
        self.navigation.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.navigation.setItemDelegate(NavigationDelegate(self))
        layout.addWidget(self.navigation)
        self.tooltip = QLabel('', self, Qt.WindowType.ToolTip)
        self.tooltip.setTextFormat(Qt.TextFormat.PlainText)
        self.tooltip.setAccessibleName('导航提示')
        self.tooltip.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.tooltip.setStyleSheet('QLabel {background:#17212F;color:white;padding:8px 12px;border-radius:6px;}')
        self.tooltip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._hide_tooltip()
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(TOOLTIP_DELAY_MS)
        self._show_timer.timeout.connect(self._show_tooltip)
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(TOOLTIP_CLOSE_MS)
        self._close_timer.timeout.connect(self._hide_if_outside)
        for widget in (self.navigation, self.navigation.viewport(), self.tooltip):
            widget.installEventFilter(self)
        self.navigation.currentRowChanged.connect(self._focused_row_changed)
        if parent is not None:
            parent.installEventFilter(self)
        self._application_filter_active = False
        self._position()

    def _position(self):
        if self.parentWidget():
            self.setGeometry(0, 0, RAIL_WIDTH, self.parentWidget().height())

    def icon_for(self, row, color):
        dpr = self.devicePixelRatioF()
        key = (row, color, dpr)
        if key not in self._icon_cache:
            self._icon_cache[key] = industrial_icon(color, dpr) if row == 6 else navigation_icon(row, color, ICON_SIZE, dpr=dpr)
        return self._icon_cache[key]

    def _focused_row_changed(self, row):
        if self.navigation.hasFocus():
            self._schedule(row, True)

    def _schedule(self, row, immediate=False):
        if row < 0:
            self._show_timer.stop()
            self._close_timer.start()
            return
        if row != self._pending_row:
            self._dismissed_row = -1
        self._pending_row = row
        self._close_timer.stop()
        if row == self._dismissed_row:
            return
        if immediate:
            self._show_tooltip()
        elif self.tooltip.isVisible():
            self._show_tooltip()
        elif not self._show_timer.isActive():
            self._show_timer.start()

    def _show_tooltip(self):
        item = self.navigation.item(self._pending_row)
        if item is None or not self.isVisible() or self._pending_row == self._dismissed_row:
            return
        self.tooltip.setText(item.text())
        self.tooltip.adjustSize()
        row_rect = self.navigation.visualItemRect(item)
        point = self.navigation.viewport().mapToGlobal(row_rect.topRight())
        screen = self.screen().availableGeometry()
        x = min(point.x() + 12, screen.right() - self.tooltip.width())
        y = min(max(screen.top(), point.y()), screen.bottom() - self.tooltip.height())
        self.tooltip.move(x, y)
        self.tooltip.show()
        if not self._application_filter_active:
            QApplication.instance().installEventFilter(self)
            self._application_filter_active = True

    def _hide_tooltip(self):
        self.tooltip.hide()
        if getattr(self, '_application_filter_active', False):
            QApplication.instance().removeEventFilter(self)
            self._application_filter_active = False

    def _hide_if_outside(self):
        if self.tooltip.underMouse() or self._hover_row >= 0:
            return
        self._hide_tooltip()

    def eventFilter(self, obj, event):
        kind = event.type()
        if obj is self.parentWidget() and kind in (QEvent.Type.Resize, QEvent.Type.Show):
            self._position()
        if self.tooltip.isVisible() and kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress) and (event.key() == Qt.Key.Key_Escape):
            event.accept()
            if kind == QEvent.Type.KeyPress:
                self._hide_tooltip()
                self._show_timer.stop()
                self._dismissed_row = self._pending_row
            return True
        if obj is self.navigation.viewport():
            if kind == QEvent.Type.MouseMove:
                self._hover_row = self.navigation.indexAt(event.position().toPoint()).row()
                self._schedule(self._hover_row)
            elif kind == QEvent.Type.Leave:
                self._hover_row = -1
                self._show_timer.stop()
                self._close_timer.start()
        elif obj is self.navigation:
            if kind == QEvent.Type.FocusIn:
                self._schedule(self.navigation.currentRow(), True)
            elif kind == QEvent.Type.FocusOut:
                self._show_timer.stop()
                if self._hover_row < 0:
                    self._hide_tooltip()
        elif obj is self.tooltip:
            if kind == QEvent.Type.Enter:
                self._close_timer.stop()
            elif kind == QEvent.Type.Leave:
                self._close_timer.start()
        return super().eventFilter(obj, event)

    def hideEvent(self, event):
        self._hide_tooltip()
        self._show_timer.stop()
        self._close_timer.stop()
        super().hideEvent(event)

def build_sidebar_navigation(sidebar, labels):
    sidebar.navigation.clear()
    for label in labels:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, label)
        item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, '打开' + label)
        sidebar.navigation.addItem(item)
    sidebar.navigation.setCurrentRow(0)
