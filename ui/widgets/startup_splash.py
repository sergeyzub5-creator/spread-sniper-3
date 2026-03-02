from math import cos, pi

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSequentialAnimationGroup, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from core.i18n import tr
from ui.widgets.brand_header import render_neon_logo_pixmap


class PulseLogoWidget(QWidget):
    def __init__(self, base_logo_size=92, parent=None):
        super().__init__(parent)
        self._base_logo_size = max(40, int(base_logo_size))
        self._scale = 1.0
        self._logo_px = render_neon_logo_pixmap(self._base_logo_size * 2)
        self.setFixedHeight(126)

    def set_scale(self, scale):
        clamped = max(0.90, min(1.20, float(scale)))
        if abs(clamped - self._scale) < 0.001:
            return
        self._scale = clamped
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w = self._base_logo_size * self._scale
        h = self._base_logo_size * self._scale
        target = QRectF((self.width() - w) / 2.0, (self.height() - h) / 2.0, w, h)
        source = QRectF(0.0, 0.0, float(self._logo_px.width()), float(self._logo_px.height()))
        painter.drawPixmap(target, self._logo_px, source)


class StartupSplash(QWidget):
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_logo_size = 92

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.SplashScreen
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(520, 300)
        self.setWindowOpacity(0.0)

        self._build_ui()
        self._build_animations()

    def _build_ui(self):
        self.setStyleSheet(
            """
            QWidget#SplashRoot {
                background-color: #0b1220;
                border: 1px solid #1e293b;
                border-radius: 14px;
            }
            QLabel#SplashTitle {
                color: #e2e8f0;
                font-size: 26px;
                font-weight: 700;
                letter-spacing: 0.3px;
            }
            QLabel#SplashSubtitle {
                color: #94a3b8;
                font-size: 13px;
            }
            """
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        self.root = QWidget()
        self.root.setObjectName("SplashRoot")
        root_layout.addWidget(self.root)

        layout = QVBoxLayout(self.root)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)
        layout.addStretch()

        self.logo_widget = PulseLogoWidget(base_logo_size=self._base_logo_size)
        layout.addWidget(self.logo_widget)

        self.title_label = QLabel(tr("app.title"))
        self.title_label.setObjectName("SplashTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(tr("status.loading"))
        self.subtitle_label.setObjectName("SplashSubtitle")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subtitle_label)

        layout.addStretch()

    def _build_animations(self):
        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setDuration(1700)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.valueChanged.connect(self._on_pulse)

        self._fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_in.setDuration(260)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_out.setDuration(260)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)

        self._sequence = QSequentialAnimationGroup(self)
        self._sequence.addAnimation(self._fade_in)
        self._sequence.addPause(950)
        self._sequence.addAnimation(self._fade_out)
        self._sequence.finished.connect(self._on_done)

    def _on_pulse(self, value):
        t = float(value)
        # Smooth sinusoidal pulse with moderate amplitude.
        wave = 0.5 - 0.5 * cos(2.0 * pi * t)
        scale = 1.0 + (0.15 * wave)
        self.logo_widget.set_scale(scale)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        self.move(rect.center() - self.rect().center())

    def start(self):
        self._center_on_screen()
        self.show()
        self.raise_()
        self._pulse_anim.start()
        self._sequence.start()

    def _on_done(self):
        self._pulse_anim.stop()
        self.close()
        self.finished.emit()
