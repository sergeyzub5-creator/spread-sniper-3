from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtCore import Qt

from core.exchange.catalog import get_exchange_meta


def _create_badge_pixmap(exchange_code: str, size: int = 18) -> QPixmap:
    meta = get_exchange_meta(exchange_code)
    short = meta["short"]
    bg = QColor(meta["color"])

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(0, 0, size, size, 4, 4)

    font = QFont("Segoe UI", max(7, size // 3))
    font.setBold(True)
    painter.setFont(font)

    # Dark logos need a light text color for readability.
    text_color = QColor("#FFFFFF")
    if bg.lightness() > 160:
        text_color = QColor("#111111")
    painter.setPen(text_color)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, short)
    painter.end()
    return pixmap


def build_exchange_icon(exchange_code: str, size: int = 18) -> QIcon:
    return QIcon(_create_badge_pixmap(exchange_code, size=size))


def build_exchange_pixmap(exchange_code: str, size: int = 18) -> QPixmap:
    return _create_badge_pixmap(exchange_code, size=size)
