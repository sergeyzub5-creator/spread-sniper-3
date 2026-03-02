from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSizePolicy, QWidget


def build_neon_logo_svg(size: int) -> str:
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 100 100">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#19B8FF"/>
      <stop offset="100%" stop-color="#00E0B8"/>
    </linearGradient>
  </defs>

  <path d="M22 30
           C22 22 29 16 38 16
           H74
           C79 16 83 20 83 25
           C83 30 79 34 74 34
           H45
           C38 34 34 37 34 42
           C34 47 38 50 45 50
           H62
           C74 50 82 56 82 67
           C82 78 73 84 62 84
           H26
           C21 84 17 80 17 75
           C17 70 21 66 26 66
           H58
           C65 66 69 63 69 58
           C69 53 65 50 58 50
           H41
           C29 50 22 43 22 30 Z"
        fill="url(#g)"/>

  <path d="M40 26 H71 C74 26 76 28 76 31
           C76 34 74 36 71 36 H45
           C41 36 38 38 38 42
           C38 45 41 47 45 47"
        fill="none" stroke="rgba(0,0,0,0.35)" stroke-width="6" stroke-linecap="round"/>

  <path d="M24 30
           C24 24 30 18 38 18
           H73"
        fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="3" stroke-linecap="round"/>
</svg>
"""


def render_neon_logo_pixmap(size: int) -> QPixmap:
    src_size = max(32, int(size))
    renderer = QSvgRenderer(build_neon_logo_svg(src_size * 2).encode("utf-8"))
    source = QPixmap(src_size * 2, src_size * 2)
    source.fill(Qt.GlobalColor.transparent)
    painter = QPainter(source)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return source.scaled(
        src_size,
        src_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def build_neon_app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
        icon.addPixmap(render_neon_logo_pixmap(size))
    return icon


class NeonLogoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._logo_size = 58
        self._line_y = 43
        self._show_lines = True
        self._logo_px = QPixmap()

        self.setFixedHeight(65)
        self.setMinimumWidth(520)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._rebuild_logo_pixmap()

    def setLogoSize(self, px: int):
        self._logo_size = max(32, int(px))
        self._rebuild_logo_pixmap()
        self.update()

    def setLineY(self, y: int):
        self._line_y = int(y)
        self.update()

    def setShowLines(self, value: bool):
        self._show_lines = bool(value)
        self.update()

    def apply_theme(self):
        # Intentionally static palette for consistent neon look across themes.
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def sizeHint(self):
        return QSize(620, 65)

    def minimumSizeHint(self):
        return QSize(520, 65)

    def _build_svg(self, size: int) -> str:
        return build_neon_logo_svg(size)

    def _rebuild_logo_pixmap(self):
        source_size = self._logo_size * 2
        renderer = QSvgRenderer(self._build_svg(source_size).encode("utf-8"))

        source = QPixmap(source_size, source_size)
        source.fill(Qt.GlobalColor.transparent)

        painter = QPainter(source)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter)
        painter.end()

        self._logo_px = source.scaled(
            self._logo_size,
            self._logo_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    @staticmethod
    def _tinted_pixmap(src: QPixmap, color: QColor) -> QPixmap:
        tinted = QPixmap(src.size())
        tinted.fill(Qt.GlobalColor.transparent)
        p = QPainter(tinted)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawPixmap(0, 0, src)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(tinted.rect(), color)
        p.end()
        return tinted

    def _draw_glow_pixmap(
        self, painter: QPainter, src: QPixmap, rect: QRectF, color: QColor, steps: int, grow_per_step: float
    ):
        if src.isNull():
            return

        tinted = self._tinted_pixmap(src, color)
        for i in range(steps, 0, -1):
            k = float(i) / float(steps)
            rr = rect.adjusted(-i * grow_per_step, -i * grow_per_step, i * grow_per_step, i * grow_per_step)
            painter.save()
            painter.setOpacity(color.alphaF() * (k * 0.60))
            painter.drawPixmap(rr.toRect(), tinted)
            painter.restore()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        center_x = self.width() / 2.0

        if self._show_lines:
            y = float(self._line_y)
            left_x1 = 12.0
            left_x2 = center_x - 22.0
            right_x1 = center_x + 22.0
            right_x2 = float(self.width()) - 12.0

            left_glow = QLinearGradient(left_x1, y, left_x2, y)
            left_glow.setColorAt(0.0, QColor(0, 214, 255, 0))
            left_glow.setColorAt(0.82, QColor(0, 214, 255, 70))
            left_glow.setColorAt(1.0, QColor(0, 214, 255, 92))
            painter.setPen(QPen(left_glow, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(int(left_x1 + 4.0), int(y), int(left_x2 - 4.0), int(y))

            right_glow = QLinearGradient(right_x1, y, right_x2, y)
            right_glow.setColorAt(0.0, QColor(0, 255, 198, 92))
            right_glow.setColorAt(0.18, QColor(0, 255, 198, 70))
            right_glow.setColorAt(1.0, QColor(0, 255, 198, 0))
            painter.setPen(QPen(right_glow, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(int(right_x1 + 4.0), int(y), int(right_x2 - 4.0), int(y))

            left_core = QLinearGradient(left_x1, y, left_x2, y)
            left_core.setColorAt(0.0, QColor(0, 214, 255, 0))
            left_core.setColorAt(0.80, QColor(0, 214, 255, 160))
            left_core.setColorAt(1.0, QColor(0, 214, 255, 220))
            painter.setPen(QPen(left_core, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(int(left_x1), int(y), int(left_x2), int(y))

            right_core = QLinearGradient(right_x1, y, right_x2, y)
            right_core.setColorAt(0.0, QColor(0, 255, 198, 220))
            right_core.setColorAt(0.20, QColor(0, 255, 198, 160))
            right_core.setColorAt(1.0, QColor(0, 255, 198, 0))
            painter.setPen(QPen(right_core, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(int(right_x1), int(y), int(right_x2), int(y))

        logo_rect = QRectF(0, 0, self._logo_size, self._logo_size)
        logo_rect.moveCenter(QPointF(center_x, self._logo_size / 2.0 + 4))

        self._draw_glow_pixmap(
            painter, self._logo_px, logo_rect, QColor(0, 200, 255, 90), steps=10, grow_per_step=1.0
        )
        self._draw_glow_pixmap(
            painter, self._logo_px, logo_rect, QColor(0, 255, 200, 46), steps=14, grow_per_step=1.4
        )

        painter.save()
        painter.setOpacity(0.25)
        shadow_rect = logo_rect.translated(1.2, 1.6)
        painter.drawPixmap(shadow_rect.toRect(), self._logo_px)
        painter.restore()

        painter.drawPixmap(logo_rect.toRect(), self._logo_px)


class BrandHeaderWidget(NeonLogoWidget):
    pass
