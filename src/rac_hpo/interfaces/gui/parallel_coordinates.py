"""Parallel coordinates from the recorded search space, with display-only brush."""
import hashlib
import math
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget, QSizePolicy, QToolTip
from .workspace_state import completed_trials, finite_value, objective_value, objective_label
from .theme import TOKENS
PALETTE = ('#1677FF', '#7544B5', '#008080', '#B95E00', '#A83280')

def trial_color(identifier):
    return PALETTE[int.from_bytes(hashlib.sha256(str(identifier).encode()).digest()[:2], 'big') % len(PALETTE)]

class ParallelCoordinates(QWidget):
    brush_changed = Signal(str, float, float)
    observed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = {}
        self.records = []
        self.visible_numbers = []
        self.axes = []
        self.ranges = {}
        self.active_id = None
        self._segments = []
        self._axis_positions = []
        self._drag = None
        self._data_key = None
        self._revision = 0
        self._cache_key = None
        self._base_image = None
        self._record_segments = {}
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName('真实搜索参数平行坐标；键盘筛选使用上方参数范围输入，数据可在 Trials 列表读取')

    def axis_value(self, trial, name):
        if name == 'objective':
            return objective_value(trial)
        value = finite_value(trial.get('params', {}).get(name))
        spec = self.snapshot.get('config', {}).get('optimization', {}).get('search_space', {}).get(name, {})
        if value is not None and spec.get('log'):
            return math.log10(value) if value > 0 else None
        return value

    def set_snapshot(self, snapshot, visible_ids=None, active_id=None):
        key=(id(snapshot),frozenset(visible_ids) if visible_ids is not None else None)
        self.active_id=active_id
        if key==self._data_key:
            self.update()
            return
        self._data_key=key
        self._revision+=1
        self.snapshot = snapshot
        all_records = completed_trials(snapshot.get('trials', []))
        self.records = [t for t in all_records if visible_ids is None or f"{snapshot.get('id')}:{t['number']}" in visible_ids]
        self.visible_numbers = [t['number'] for t in self.records]
        schema = snapshot.get('config', {}).get('optimization', {}).get('search_space', {})
        self.axes = [key for key, spec in schema.items() if isinstance(spec, dict) and spec.get('type', 'float') in ('int', 'float')] + ['objective']
        self.ranges = {}
        for name in self.axes:
            spec = schema.get(name, {})
            values = [self.axis_value(t, name) for t in all_records]
            values = [v for v in values if v is not None]
            if name != 'objective':
                for bound in ('low', 'high'):
                    raw = finite_value(spec.get(bound))
                    if raw is not None and (not spec.get('log') or raw > 0):
                        values.append(math.log10(raw) if spec.get('log') else raw)
            if values:
                low, high = (min(values), max(values))
                if low == high:
                    low, high = (low - 0.5, high + 0.5)
                self.ranges[name] = (low, high)
        self.axes = [a for a in self.axes if a in self.ranges]
        self.update()

    def paintEvent(self, event):
        dpr=self.devicePixelRatioF()
        key=(self.width(),self.height(),dpr,self._revision)
        if key!=self._cache_key:
            self._base_image=QPixmap(round(self.width()*dpr),round(self.height()*dpr))
            self._base_image.setDevicePixelRatio(dpr)
            self._base_image.fill(Qt.GlobalColor.transparent)
            base_painter=QPainter(self._base_image)
            base_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_base(base_painter)
            base_painter.end()
            self._cache_key=key
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0,0,self._base_image)
        if self.active_id:
            painter.setPen(QPen(QColor(trial_color(self.active_id)),3))
            for a,b in self._record_segments.get(self.active_id,[]):
                painter.drawLine(a,b)
        if self._drag:
            name,x,y0,y1=self._drag
            painter.setPen(QPen(QColor(TOKENS['accent']),5))
            painter.drawLine(QPointF(x,y0),QPointF(x,y1))

    def _paint_base(self,painter):
        self._record_segments={}
        self._segments = []
        self._axis_positions = []
        painter.setPen(QColor(TOKENS['secondary']))
        if len(self.axes) < 2 or not self.records:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '暂无可绘制的参数与目标记录\n需要真实搜索空间及完成 Trial')
            return
        rect = QRectF(55, 58, max(1, self.width() - 110), max(1, self.height() - 112))
        for i, name in enumerate(self.axes):
            x = rect.left() + i * rect.width() / (len(self.axes) - 1)
            self._axis_positions.append((name, x, rect))
            painter.setPen(QPen(QColor(TOKENS['border']), 1))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.setPen(QColor(TOKENS['secondary']))
            label = '目标 ' + objective_label(self.snapshot)[0] if name == 'objective' else name
            elided = self.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, max(40, int(rect.width() / len(self.axes))))
            painter.drawText(QRectF(x - 55, 5, 110, 24), Qt.AlignmentFlag.AlignCenter, elided)
            low, high = self.ranges[name]
            spec = self.snapshot.get('config', {}).get('optimization', {}).get('search_space', {}).get(name, {})
            fmt = lambda value: f"{(10 ** value if spec.get('log') else value):.3g}"
            painter.drawText(QRectF(x - 38, 30, 76, 22), Qt.AlignmentFlag.AlignCenter, fmt(high))
            painter.drawText(QRectF(x - 38, rect.bottom() + 4, 76, 22), Qt.AlignmentFlag.AlignCenter, fmt(low))
        for trial in self.records:
            identifier = f"{self.snapshot.get('id')}:{trial['number']}"
            color = QColor(trial_color(identifier))
            color.setAlpha(105)
            painter.setPen(QPen(color, 1))
            last = None
            for name, x, axis_rect in self._axis_positions:
                value = self.axis_value(trial, name)
                if value is None:
                    last = None
                    continue
                low, high = self.ranges[name]
                point = QPointF(x, axis_rect.bottom() - (value - low) / (high - low) * axis_rect.height())
                if last is not None:
                    painter.drawLine(last, point)
                    self._segments.append((last, point, trial, identifier))
                    self._record_segments.setdefault(identifier,[]).append((last,point))
                last = point
        painter.setPen(QColor(TOKENS['secondary']))
        painter.drawText(QRectF(0, self.height() - 25, self.width(), 22), Qt.AlignmentFlag.AlignCenter, f'筛选集合：{len(self.records)} 条完成 Trial · 颜色标识 Trial · 目标越小越好')
    def _hit(self, position):
        best = None
        distance = 8.0
        for a, b, trial, identifier in self._segments:
            dx = b.x() - a.x()
            dy = b.y() - a.y()
            den = dx * dx + dy * dy
            fraction = max(0, min(1, ((position.x() - a.x()) * dx + (position.y() - a.y()) * dy) / den)) if den else 0
            current = math.hypot(position.x() - a.x() - fraction * dx, position.y() - a.y() - fraction * dy)
            if current < distance:
                best = (trial, identifier)
                distance = current
        return best

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        for name, x, rect in self._axis_positions:
            if name != 'objective' and abs(event.position().x() - x) < 10 and rect.contains(event.position()):
                self._drag = (name, x, event.position().y(), event.position().y())
                return
        hit = self._hit(event.position())
        if hit:
            self.observed.emit(hit[1])

    def mouseMoveEvent(self, event):
        if self._drag:
            name, x, y0, _ = self._drag
            self._drag = (name, x, y0, event.position().y())
            self.update()
            return
        hit = self._hit(event.position())
        if hit:
            trial, identifier = hit
            QToolTip.showText(event.globalPosition().toPoint(), f"Trial #{trial['number']} · 目标 {objective_value(trial):.6g}\n" + str(trial.get('params', {})), self)
        else:
            QToolTip.hideText()
            for name, x, rect in self._axis_positions:
                if abs(event.position().x() - x) < 20:
                    QToolTip.showText(event.globalPosition().toPoint(), name, self)
                    break

    def mouseReleaseEvent(self, event):
        if not self._drag:
            return
        name, x, y0, y1 = self._drag
        self._drag = None
        if abs(y1 - y0) < 4:
            self.update()
            return
        rect = next((rect for key, axis_x, rect in self._axis_positions if key == name))
        low, high = self.ranges[name]
        convert = lambda y: low + (1 - min(1, max(0, (y - rect.top()) / rect.height()))) * (high - low)
        a, b = sorted((convert(y0), convert(y1)))
        if self.snapshot['config']['optimization']['search_space'][name].get('log'):
            a, b = (10 ** a, 10 ** b)
        self.brush_changed.emit(name, a, b)
        self.update()

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)
