"""Small, dependency-free Qt widgets for JARVIS's live desktop dashboard."""
from __future__ import annotations

from collections import deque
import math

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget


class Sparkline(QWidget):
    """Recent measured values; unavailable samples leave the chart empty."""
    def __init__(self, color="#48e0ed", parent=None):
        super().__init__(parent)
        self.values = deque(maxlen=44)
        self.color = QColor(color)
        self.setMinimumSize(80, 28)
        self.setMaximumHeight(32)

    def add_value(self, value):
        if value is not None:
            self.values.append(max(0, min(100, float(value))))
            self.update()

    def paintEvent(self, event):
        if len(self.values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        path = QPainterPath()
        for index, value in enumerate(self.values):
            point = QPointF(index * width / (self.values.maxlen - 1), height - 3 - value / 100 * (height - 6))
            path.moveTo(point) if index == 0 else path.lineTo(point)
        fill = QPainterPath(path)
        fill.lineTo((len(self.values) - 1) * width / (self.values.maxlen - 1), height)
        fill.lineTo(0, height)
        fill.closeSubpath()
        gradient = QLinearGradient(0, 0, 0, height)
        shade = QColor(self.color)
        shade.setAlpha(70)
        gradient.setColorAt(0, shade)
        shade.setAlpha(0)
        gradient.setColorAt(1, shade)
        painter.fillPath(fill, gradient)
        painter.setPen(QPen(self.color, 1.6))
        painter.drawPath(path)


class MicrophoneMeter(QWidget):
    """Display actual recent input levels rather than a simulated audio trace."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = deque([0.0] * 56, maxlen=56)
        self.level = 0.0
        self.clipping = False
        self.setMinimumHeight(26)
        self.setMaximumHeight(26)

    def feed(self, value, clipping=False):
        self.level = max(0.0, min(1.0, float(value)))
        self.clipping = bool(clipping)
        self.samples.append(self.level)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        painter.setPen(QPen(QColor("#193445"), 1))
        painter.drawLine(0, height // 2, width, height // 2)
        step = width / len(self.samples)
        for index, value in enumerate(self.samples):
            # Compress amplitude only for readability; the underlying level is
            # shown numerically and clipping is supplied by the input worker.
            bar = max(2, min(height - 4, math.sqrt(value) * (height - 4)))
            color = QColor("#f2b46e" if self.clipping else "#5cdae4")
            color.setAlpha(70 + int(160 * (index + 1) / len(self.samples)))
            painter.setPen(QPen(color, max(1.5, min(3, step * .45)), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF((index + .5) * step, height / 2 - bar / 2),
                             QPointF((index + .5) * step, height / 2 + bar / 2))


class Reactor(QWidget):
    """Animated interface artwork whose emphasis follows actual app state."""
    def __init__(self):
        super().__init__()
        self.setMinimumSize(230, 135)
        self.setMaximumHeight(320)
        self.phase = 0.0
        self.amplitude = 0.0
        self.mode = "VOICE SETUP"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(40)

    def animate(self):
        self.phase = (self.phase + .45) % 360
        self.amplitude *= .9
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = min(self.width(), self.height()) * .37
        speaking = "SPEAKING" in self.mode
        preparing = any(word in self.mode for word in ("PREPARING", "PROCESSING", "THINKING"))
        sleeping = "SLEEP" in self.mode
        color = QColor("#82a6bd" if sleeping else "#9ac4ff" if preparing else "#62f1e5" if speaking else "#49ddeb")
        glow = QRadialGradient(center, radius * 1.25)
        glow.setColorAt(0, QColor(30, 162, 192, 35))
        glow.setColorAt(.6, QColor(25, 113, 157, 13))
        glow.setColorAt(1, QColor(10, 22, 39, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, radius * 1.25, radius * 1.25)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for factor in (.36, .56, .69, .84, 1.06, 1.2):
            painter.setPen(QPen(QColor(42, 91, 115, 80), .7))
            painter.drawEllipse(center, radius * factor, radius * factor)
        # Radial traces and circuit points give the artwork depth without
        # presenting decorative numbers as real system readings.
        for index in range(72):
            angle = math.radians(index * 5)
            outer = radius * 1.08
            inner = outer - (9 if index % 6 == 0 else 3)
            shade = QColor(color)
            shade.setAlpha(155 if index % 6 == 0 else 55)
            painter.setPen(QPen(shade, 1))
            painter.drawLine(QPointF(center.x() + math.cos(angle) * inner, center.y() + math.sin(angle) * inner),
                             QPointF(center.x() + math.cos(angle) * outer, center.y() + math.sin(angle) * outer))
        for factor, speed, line, span in [(.97, .65, 2, 54), (.81, -.9, 1.3, 83), (.62, .4, 3, 72)]:
            size = radius * factor
            painter.setPen(QPen(QColor(34, 91, 112, 100), line))
            painter.drawEllipse(center, size, size)
            painter.setPen(QPen(color, line, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            rectangle = QRectF(center.x() - size, center.y() - size, size * 2, size * 2)
            for start in (0, 120, 240):
                painter.drawArc(rectangle, int((start + self.phase * speed) * 16), span * 16)
        inner = radius * (.45 + min(self.amplitude, .4) * .08)
        painter.setPen(QPen(QColor(84, 209, 226, 38), 6))
        painter.drawEllipse(center, inner, inner)
        painter.setPen(QPen(QColor(133, 232, 243, 120), .8))
        painter.drawEllipse(center, inner, inner)
        # The center remains still so the name stays legible as rings rotate.
        painter.setPen(QColor("#dbf8ff"))
        painter.setFont(QFont("Segoe UI", max(13, int(radius * .16)), QFont.Weight.DemiBold))
        painter.drawText(QRectF(center.x() - radius, center.y() - 17, radius * 2, 26), Qt.AlignmentFlag.AlignCenter, "J A R V I S")
        painter.setFont(QFont("Segoe UI", 7))
        painter.setPen(QColor("#78a8be"))
        painter.drawText(QRectF(center.x() - radius, center.y() + 11, radius * 2, 19), Qt.AlignmentFlag.AlignCenter, "PERSONAL ASSISTANT")
        painter.setPen(QPen(color, 1))
        for sign in (-1, 1):
            painter.drawLine(QPointF(center.x() + sign * radius * 1.25, center.y()),
                             QPointF(center.x() + sign * radius * 1.1, center.y()))
