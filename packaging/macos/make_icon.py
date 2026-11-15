"""Render AppIcon.icns with Qt; no binary asset is kept in the repository.

Accent-blue rounded square (theme TOKENS["accent"]) with a white
best-so-far convergence curve and trial points, i.e. what the app shows.
Usage: python make_icon.py OUTPUT_DIR   (needs macOS iconutil)
"""
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

SIZES = (16, 32, 128, 256, 512)


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 1024, size / 1024)
    # macOS Big Sur grid: 824px tile centred on a 1024 canvas.
    tile = QRectF(100, 100, 824, 824)
    gradient = QLinearGradient(tile.topLeft(), tile.bottomRight())
    gradient.setColorAt(0, QColor("#3B8CFF"))
    gradient.setColorAt(1, QColor("#0958D9"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(tile, 185, 185)

    painter.setPen(QPen(QColor(255, 255, 255, 70), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for y in (370, 520, 670):
        painter.drawLine(QPointF(250, y), QPointF(774, y))
    points = [QPointF(250, 300), QPointF(340, 420), QPointF(430, 500), QPointF(530, 580),
              QPointF(640, 630), QPointF(774, 650)]
    curve = QPainterPath(points[0])
    for point in points[1:]:
        curve.lineTo(point)
    painter.setPen(QPen(QColor("white"), 46, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(curve)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 150))
    # Trials never beat the best-so-far curve, so every point sits above it.
    for x, y in ((310, 250), (400, 330), (480, 280), (600, 450), (700, 520)):
        painter.drawEllipse(QPointF(x, y), 22, 22)
    painter.setBrush(QColor("#FFC53D"))
    painter.drawEllipse(QPointF(774, 650), 50, 50)
    painter.end()
    return image


def main(output: Path) -> Path:
    app = QGuiApplication.instance() or QGuiApplication([])
    iconset = output / "AppIcon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        render(size).save(str(iconset / f"icon_{size}x{size}.png"))
        render(size * 2).save(str(iconset / f"icon_{size}x{size}@2x.png"))
    target = output / "AppIcon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True)
    del app
    return target


if __name__ == "__main__":
    print(main(Path(sys.argv[1]).resolve()))
