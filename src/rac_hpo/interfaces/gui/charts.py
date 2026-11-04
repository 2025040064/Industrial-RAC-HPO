"""Native QPainter experiment panels; no storage, training, or synthetic data."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from .theme import TOKENS
from .widgets import format_value
from .workspace_state import (
    completed_trials, finite_value, objective_label, objective_value, search_trials,
)


class ExperimentChart(QWidget):
    """Resize paints cached records; hover never asks the backend for data."""

    def __init__(self, kind="history", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.snapshot = {}
        self.values = []
        self.trial_numbers = []
        self.best_values = []
        self.parameter = None
        self.log_scale = False
        self.loading = False
        self.visible_ids = None
        self.active_id = None
        self._hits = []
        self.setMouseTracking(True)
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName({
            "history": "真实试验目标与累计最优曲线", "distribution": "真实试验目标分布",
            "parameter": "实际搜索参数与目标关系", "status": "已保存试验状态与次数上限",
        }[kind])

    def set_snapshot(self, snapshot, parameter=None):
        self.snapshot = snapshot
        if parameter is not None:
            self.parameter = parameter
        self.loading = False
        completed = completed_trials(snapshot.get("trials", []))
        self.values = [objective_value(trial) for trial in completed]
        self.trial_numbers = [trial["number"] for trial in completed]
        self.best_values = []
        for value in self.values:
            self.best_values.append(min(self.best_values[-1], value) if self.best_values else value)
        specification = snapshot.get("config", {}).get("optimization", {}).get("search_space", {})
        self.log_scale = bool(specification.get(self.parameter, {}).get("log", False))
        self.update()

    def set_display_state(self, visible_ids, active_id):
        self.visible_ids=visible_ids
        self.active_id=active_id
        self.update()

    def set_loading(self, loading=True):
        self.loading = loading
        self.update()

    def _text(self, painter, rect, text, alignment=Qt.AlignmentFlag.AlignCenter):
        painter.setPen(QColor(TOKENS["secondary"]))
        painter.drawText(QRectF(rect), alignment, text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hits = []
        if self.loading:
            self._text(painter, self.rect(), "等待后端保存真实试验…")
            return
        if self.kind == "status":
            self._paint_status(painter)
            return
        if not self.values:
            self._text(painter, self.rect(), "暂无已完成的搜索试验\n默认基线不计入此图")
            return
        bottom_space = 124 if self.kind == "history" else 104
        rect = QRectF(72, 38, max(1, self.width() - 98), max(1, self.height() - bottom_space))
        label, unit = objective_label(self.snapshot)
        if self.kind == "history":
            self._paint_history(painter, rect, label, unit)
        elif self.kind == "distribution":
            self._paint_distribution(painter, rect, label, unit)
        else:
            self._paint_parameter(painter, rect, label, unit)

    def _axes(self, painter, rect, xlow, xhigh, ylow, yhigh, xlabel, ylabel,
              xformatter=None, yformatter=None):
        xformatter = xformatter or (lambda value: f"{value:.4g}")
        yformatter = yformatter or (lambda value: f"{value:.4g}")
        painter.setPen(QPen(QColor(TOKENS["border"]), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.topLeft(), rect.bottomLeft())
        for fraction in (0.0, 0.5, 1.0):
            y = rect.bottom() - rect.height() * fraction
            painter.setPen(QPen(QColor(TOKENS["border"]), 1))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            self._text(painter, QRectF(0, y - 9, 63, 18),
                       yformatter(ylow + fraction * (yhigh - ylow)), Qt.AlignmentFlag.AlignRight)
            x = rect.left() + fraction * rect.width()
            self._text(painter, QRectF(x - 36, rect.bottom() + 5, 72, 20),
                       xformatter(xlow + fraction * (xhigh - xlow)))
        self._text(painter, QRectF(rect.left(), 2, rect.width(), 24), ylabel,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._text(painter, QRectF(rect.left(), rect.bottom() + 29, rect.width(), 26), xlabel)

    @staticmethod
    def _range(values):
        low, high = min(values), max(values)
        margin = (high - low) * 0.08 if high > low else max(abs(high) * 0.08, 0.05)
        return low - margin, high + margin

    @staticmethod
    def _point(rect, x, y, xlow, xhigh, ylow, yhigh):
        return QPointF(rect.left() + (x - xlow) / (xhigh - xlow) * rect.width(),
                       rect.bottom() - (y - ylow) / (yhigh - ylow) * rect.height())

    def _trial_tip(self, trial):
        label, unit = objective_label(self.snapshot)
        mae = trial.get("metrics", {}).get("overall_mae")
        return (f"试验 #{trial['number']}\n目标 {label}: {format_value(objective_value(trial))} ({unit})\n"
                f"验证 MAE: {format_value(mae)} ({self.snapshot.get('target_unit') or '单位未记录'})\n"
                f"试验耗时: {format_value(trial.get('duration_seconds'))} 秒")

    def _paint_history(self, painter, rect, label, unit):
        xlow, xhigh = self.trial_numbers[0], self.trial_numbers[-1]
        if xhigh == xlow:
            xlow, xhigh = xlow - 0.5, xhigh + 0.5
        ylow, yhigh = self._range(self.values)
        self._axes(painter, rect, xlow, xhigh, ylow, yhigh, "真实试验编号", f"目标 {label} ({unit})",
                   xformatter=lambda value: f"{value:g}")
        for values, color, width in ((self.values, "#94A3B8", 1),
                                      (self.best_values, TOKENS["accent"], 2)):
            points = [self._point(rect, x, y, xlow, xhigh, ylow, yhigh)
                      for x, y in zip(self.trial_numbers, values)]
            path = QPainterPath(points[0])
            for point in points[1:]:
                path.lineTo(point)
            painter.setPen(QPen(QColor(color), width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setBrush(QColor(color))
            for point in points:
                painter.drawEllipse(point, 3, 3)
        for trial in completed_trials(self.snapshot.get("trials", [])):
            point = self._point(rect, trial["number"], objective_value(trial), xlow, xhigh, ylow, yhigh)
            identifier=f"{self.snapshot.get('id')}:{trial['number']}"
            if self.visible_ids is not None and identifier in self.visible_ids:
                painter.setPen(QPen(QColor(TOKENS['accent']),2))
                painter.setBrush(QColor(TOKENS['card']))
                painter.drawEllipse(point,5 if identifier==self.active_id else 3.5,5 if identifier==self.active_id else 3.5)
            self._hits.append((QRectF(point.x() - 9, point.y() - 9, 18, 18), self._trial_tip(trial)))
        self._text(painter, QRectF(rect.left(), self.height() - 20, rect.width(), 18),
                   "灰：本次目标    蓝：累计最优（越小越好）")

    def _paint_distribution(self, painter, rect, label, unit):
        xlow, xhigh = min(self.values), max(self.values)
        if xhigh == xlow:
            delta = max(abs(xlow) * 0.05, 0.05)
            xlow, xhigh = xlow - delta, xhigh + delta
        bins = max(1, min(12, math.ceil(math.sqrt(len(self.values)))))
        groups = [[] for _ in range(bins)]
        for trial in completed_trials(self.snapshot.get("trials", [])):
            index = min(bins - 1, int((objective_value(trial) - xlow) / (xhigh - xlow) * bins))
            groups[index].append(trial)
        ymax = max(len(group) for group in groups)
        self._axes(painter, rect, xlow, xhigh, 0, max(1, ymax), f"目标 {label} ({unit})", "试验数量（次）",
                   yformatter=lambda value: f"{value:g}")
        width = rect.width() / bins
        for index, group in enumerate(groups):
            bar = QRectF(rect.left() + width * index + 2,
                         rect.bottom() - len(group) / max(1, ymax) * rect.height(),
                         max(1, width - 4), len(group) / max(1, ymax) * rect.height())
            painter.fillRect(bar, QColor(TOKENS["accent"]))
            lower = xlow + index / bins * (xhigh - xlow)
            upper = xlow + (index + 1) / bins * (xhigh - xlow)
            self._hits.append((bar, f"目标范围: {lower:.6g} – {upper:.6g} ({unit})\n"
                               f"已完成试验: {len(group)} 次\n编号: "
                               + ", ".join(str(trial["number"]) for trial in group)))

    def _paint_parameter(self, painter, rect, label, unit):
        trials = [trial for trial in completed_trials(self.snapshot.get("trials", []))
                  if self.parameter in trial.get("params", {})]
        if not trials:
            self._text(painter, self.rect(), "当前参数暂无已完成试验记录")
            return
        raw_values = [trial["params"][self.parameter] for trial in trials]
        numeric = all(finite_value(value) is not None for value in raw_values)
        if numeric:
            usable = [(trial, finite_value(value)) for trial, value in zip(trials, raw_values)
                      if not self.log_scale or float(value) > 0]
            xvalues = [math.log10(value) if self.log_scale else value for _, value in usable]
            trials = [trial for trial, _ in usable]
            formatter = ((lambda value: f"{10 ** value:.3g}") if self.log_scale else None)
        else:
            categories = list(dict.fromkeys(str(value) for value in raw_values))
            xvalues = [categories.index(str(value)) for value in raw_values]
            formatter = lambda value: categories[round(value)] if 0 <= round(value) < len(categories) else ""
        if not xvalues:
            self._text(painter, self.rect(), "该对数参数没有正数记录，无法绘图")
            return
        xlow, xhigh = self._range(xvalues)
        ylow, yhigh = self._range([objective_value(trial) for trial in trials])
        self._axes(painter, rect, xlow, xhigh, ylow, yhigh,
                   f"{self.parameter}" + ("（对数刻度）" if self.log_scale else ""),
                   f"目标 {label} ({unit})", xformatter=formatter)
        painter.setPen(QPen(QColor(TOKENS["accent"]), 1))
        painter.setBrush(QColor(TOKENS["accent"]))
        for xvalue, trial in zip(xvalues, trials):
            point = self._point(rect, xvalue, objective_value(trial), xlow, xhigh, ylow, yhigh)
            painter.drawEllipse(point, 4, 4)
            tip = f"{self.parameter}: {format_value(trial['params'][self.parameter])}\n{self._trial_tip(trial)}"
            self._hits.append((QRectF(point.x() - 9, point.y() - 9, 18, 18), tip))

    def _paint_status(self, painter):
        records = search_trials(self.snapshot.get("trials", []))
        if not records and not self.snapshot.get("id"):
            self._text(painter, self.rect(), "暂无搜索任务\n状态与次数来自已保存试验")
            return
        counts = [sum(record.get("status") in aliases for record in records)
                  for aliases in (("completed", "COMPLETE"), ("failed", "FAIL"), ("cancelled",))]
        counts.append(len(records) - sum(counts))
        rect = QRectF(72, 35, max(1, self.width() - 104), max(1, self.height() - 115))
        upper = max(1, max(counts))
        colors = (TOKENS["accent"], "#D92D20", "#F79009", "#94A3B8")
        for index, (name, count, color) in enumerate(zip(("完成", "失败", "取消", "其他"), counts, colors)):
            y = rect.top() + index * rect.height() / 4
            self._text(painter, QRectF(0, y, 62, 24), name, Qt.AlignmentFlag.AlignRight)
            track = QRectF(rect.left(), y, rect.width(), 22)
            painter.fillRect(track, QColor(TOKENS["background"]))
            painter.fillRect(QRectF(track.left(), y, track.width() * count / upper, 22), QColor(color))
            self._text(painter, QRectF(rect.right() + 4, y, 30, 24), str(count))
            self._hits.append((track, f"{name}: {count} 次（已保存的真实试验）"))
        maximum = self.snapshot.get("config", {}).get("optimization", {}).get("max_trials")
        self._text(painter, QRectF(0, self.height() - 67, self.width(), 26),
                   f"已保存搜索试验：{len(records)} / {format_value(maximum)} 次")
        self._text(painter, QRectF(0, self.height() - 38, self.width(), 30),
                   "次数上限不代表时间进度；默认基线不计入")

    def mouseMoveEvent(self, event):
        position = event.position()
        for rect, tip in self._hits:
            if rect.contains(position):
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)
