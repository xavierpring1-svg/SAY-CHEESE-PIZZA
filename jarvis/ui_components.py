"""Small, dependency-free Qt widgets for JARVIS's live desktop dashboard."""
from __future__ import annotations

from collections import deque
import math
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget, QSizePolicy


class Hologram(QWidget):
    """Human hologram with a mouth gated by real speech playback.

    Speech output currently reports playback boundaries, not phonemes. Within
    those boundaries a gentle animation suggests articulation; microphone
    input, thinking, and downloading never animate the mouth.
    """
    MOUTH_POSITION = (.501, .466)
    MOUTH_WIDTH = .13

    def __init__(self, image_path=None, parent=None):
        super().__init__(parent)
        self.setObjectName("hologram")
        self.setMinimumSize(265, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("JARVIS holographic face")
        self.setAccessibleDescription("The mouth moves while JARVIS is speaking.")
        path = image_path or Path(__file__).resolve().parent / "assets" / "hologram.png"
        self.portrait = QPixmap(str(path)) if Path(path).is_file() else QPixmap()
        self._scaled_portrait = QPixmap()
        self.phase = 0.0
        self.mode = "VOICE SETUP"
        self.amplitude = 0.0
        self.speaking = False
        self.mouth_openness = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.animate)

    def set_speaking(self, speaking):
        self.speaking = bool(speaking)
        self.timer.setInterval(40 if self.speaking else 120)
        if not self.speaking:
            # Close immediately, including interruptions and sleep transitions.
            self.mouth_openness = 0.0
        self.update()

    def animate(self):
        self.phase = (self.phase + .04) % (math.pi * 100)
        self.amplitude *= .9
        if self.speaking:
            # Bounded articulation, rather than a simulated microphone meter.
            pulse = abs(math.sin(self.phase * 15) * math.cos(self.phase * 5.7))
            self.mouth_openness = .12 + .88 * pulse
        else:
            self.mouth_openness = 0.0
        if self.isVisible():
            self.update()

    def showEvent(self, event):
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def _portrait_rect(self):
        area = QRectF(9, 0, max(1, self.width() - 18), self.height())
        if self.portrait.isNull():
            ratio = .75
            width = min(area.width(), area.height() * ratio)
        else:
            ratio = self.portrait.width() / self.portrait.height()
            # Fill the panel so the face remains prominent at desktop widths.
            width = max(area.width(), area.height() * ratio)
        height = width / ratio
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        bounds = QRectF(self.rect())
        painter.fillRect(bounds, QColor("#030d17"))
        clip = QPainterPath()
        clip.addRoundedRect(bounds, 7, 7)
        painter.setClipPath(clip)
        rect = self._portrait_rect()
        if self.portrait.isNull():
            self._draw_fallback(painter, rect)
        else:
            size = QSize(max(1, round(rect.width())), max(1, round(rect.height())))
            if self._scaled_portrait.size() != size:
                # Resize the artwork only when the panel size changes.
                self._scaled_portrait = self.portrait.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(rect.topLeft(), self._scaled_portrait)
        # Edge fades blend the portrait into its panel without changing the art.
        fade = QLinearGradient(0, 0, 0, self.height())
        fade.setColorAt(0, QColor(3, 13, 23, 85))
        fade.setColorAt(.16, QColor(3, 13, 23, 0))
        fade.setColorAt(.84, QColor(3, 13, 23, 0))
        fade.setColorAt(1, QColor(3, 13, 23, 135))
        painter.fillRect(bounds, fade)
        self._draw_hud(painter, bounds)
        self._draw_mouth(painter, rect)
        painter.end()

    def _draw_hud(self, painter, bounds):
        cyan = QColor("#42ddeb")
        muted = QColor(48, 135, 167, 90)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(muted, .7))
        painter.drawRoundedRect(bounds.adjusted(1, 1, -1, -1), 7, 7)
        # Reticle corners and circuit lines are artwork, not system telemetry.
        painter.setPen(QPen(cyan, 1.3))
        for x, y, sx, sy in ((10, 10, 1, 1), (self.width() - 10, 10, -1, 1),
                             (10, self.height() - 10, 1, -1),
                             (self.width() - 10, self.height() - 10, -1, -1)):
            painter.drawLine(QPointF(x, y), QPointF(x + sx * 19, y))
            painter.drawLine(QPointF(x, y), QPointF(x, y + sy * 19))
        for side in (-1, 1):
            x = 18 if side == -1 else self.width() - 18
            for index in range(17):
                y = self.height() * .29 + index * 5
                painter.setPen(QPen(QColor(72, 195, 218, 75 if index % 4 else 170), .8))
                painter.drawLine(QPointF(x, y), QPointF(x + side * (5 if index % 4 else 9), y))
        painter.setPen(QColor("#65b8c9"))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(QRectF(16, self.height() - 35, self.width() - 32, 20),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "J.A.R.V.I.S. / PERSONAL ASSISTANT")
        # The moving light remains separate from the speech mouth.
        scan = (math.sin(self.phase * .35) + 1) / 2
        painter.setPen(QPen(QColor(70, 209, 239, 20), 1))
        y = 18 + scan * max(1, self.height() - 60)
        painter.drawLine(QPointF(28, y), QPointF(self.width() - 28, y))

    def _draw_mouth(self, painter, rect):
        if not self.speaking and not self.portrait.isNull():
            # Preserve the original closed mouth completely when silent.
            return
        position = self.MOUTH_POSITION if not self.portrait.isNull() else (.5, .525)
        x = rect.x() + rect.width() * position[0]
        y = rect.y() + rect.height() * position[1]
        half_width = rect.width() * self.MOUTH_WIDTH / 2
        opening = rect.height() * .023 * self.mouth_openness
        mouth = QPainterPath(QPointF(x - half_width, y))
        mouth.cubicTo(x - half_width * .48, y - opening * .65,
                      x + half_width * .48, y - opening * .65, x + half_width, y)
        mouth.cubicTo(x + half_width * .5, y + opening,
                      x - half_width * .5, y + opening, x - half_width, y)
        painter.setBrush(QColor(2, 19, 31, 235))
        painter.setPen(QPen(QColor(65, 222, 255, 90), max(1, rect.width() * .004)))
        painter.drawPath(mouth)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(112, 238, 255, 200), max(.8, rect.width() * .002)))
        painter.drawPath(mouth)
        if opening > rect.height() * .008:
            painter.setPen(QPen(QColor(126, 218, 239, 170), max(1, rect.width() * .003)))
            painter.drawLine(QPointF(x - half_width * .6, y - opening * .22),
                             QPointF(x + half_width * .6, y - opening * .22))

    def _draw_fallback(self, painter, rect):
        """Draw a human-shaped wireframe if an optional asset is unavailable."""
        painter.save()
        painter.translate(rect.x(), rect.y())
        painter.scale(rect.width() / 300, rect.height() / 400)
        center = QPointF(150, 185)
        glow = QRadialGradient(center, 175)
        glow.setColorAt(0, QColor(12, 128, 169, 75))
        glow.setColorAt(.7, QColor(6, 74, 116, 25))
        glow.setColorAt(1, QColor(3, 13, 23, 0))
        painter.fillRect(QRectF(0, 0, 300, 400), glow)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for radius in (111, 123, 133):
            painter.setPen(QPen(QColor(41, 163, 205, 60), .8))
            painter.drawEllipse(QPointF(150, 142), radius, radius)
        bust = QPainterPath(QPointF(17, 399))
        bust.cubicTo(21, 307, 92, 307, 120, 277)
        bust.lineTo(120, 242)
        bust.cubicTo(85, 220, 73, 189, 76, 121)
        bust.cubicTo(73, 47, 95, 35, 147, 33)
        bust.cubicTo(198, 33, 229, 55, 224, 121)
        bust.cubicTo(224, 189, 218, 220, 180, 242)
        bust.lineTo(180, 277)
        bust.cubicTo(219, 309, 280, 316, 283, 399)
        painter.setPen(QPen(QColor(28, 173, 224, 45), 8))
        painter.drawPath(bust)
        painter.setPen(QPen(QColor("#36c8ef"), 1.4))
        painter.drawPath(bust)
        # Curved facial meridians keep the fallback recognizably human.
        for index in range(-3, 4):
            x = 150 + index * 18
            path = QPainterPath(QPointF(x, 67))
            path.cubicTo(x + index * 5, 121, x + index * 3, 203, 150 + index * 9, 236)
            painter.setPen(QPen(QColor(47, 173, 214, 90), .65))
            painter.drawPath(path)
        for y, width in ((83, 50), (102, 61), (128, 69), (153, 70), (178, 62), (202, 46), (225, 31)):
            path = QPainterPath(QPointF(150 - width, y))
            path.quadTo(150, y + 17, 150 + width, y)
            painter.drawPath(path)
        painter.setPen(QPen(QColor("#77e7ff"), 1.5))
        nose = QPainterPath(QPointF(151, 151))
        nose.lineTo(141, 188)
        nose.quadTo(149, 196, 161, 188)
        painter.drawPath(nose)
        for eye_x in (117, 184):
            eye_glow = QRadialGradient(QPointF(eye_x, 145), 18)
            eye_glow.setColorAt(0, QColor(193, 250, 255, 255))
            eye_glow.setColorAt(.2, QColor(48, 213, 255, 245))
            eye_glow.setColorAt(1, QColor(28, 165, 225, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(eye_glow)
            painter.drawEllipse(QPointF(eye_x, 145), 18, 13)
            painter.setPen(QPen(QColor(63, 209, 251, 185), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(eye_x, 145), 13, 5)
        painter.setPen(QPen(QColor(29, 151, 202, 155), .8))
        for side in (-1, 1):
            for index in range(4):
                path = QPainterPath(QPointF(150 + side * 26, 276 + index * 12))
                path.lineTo(150 + side * (68 + index * 8), 315 + index * 13)
                path.lineTo(150 + side * (99 + index * 10), 391)
                painter.drawPath(path)
        chest = QRadialGradient(QPointF(150, 348), 37)
        chest.setColorAt(0, QColor(104, 245, 255, 215))
        chest.setColorAt(.22, QColor(35, 187, 229, 175))
        chest.setColorAt(1, QColor(12, 121, 180, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(chest)
        painter.drawEllipse(QPointF(150, 348), 37, 37)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for radius in (15, 22, 31):
            painter.setPen(QPen(QColor(98, 227, 255, 155), .9))
            painter.drawEllipse(QPointF(150, 348), radius, radius)
        painter.restore()


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
