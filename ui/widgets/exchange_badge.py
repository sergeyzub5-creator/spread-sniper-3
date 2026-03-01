from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

from core.exchange.catalog import get_exchange_meta, normalize_exchange_code


# ui/widgets -> ui/assets/logos/exchanges
_ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets" / "logos" / "exchanges"
_SUPPORTED_EXTENSIONS = (".png", ".svg", ".ico", ".webp", ".jpg", ".jpeg")


def _resolve_logo_path(exchange_code: str) -> Path | None:
    code = normalize_exchange_code(exchange_code)
    for ext in _SUPPORTED_EXTENSIONS:
        path = _ASSETS_DIR / f"{code}{ext}"
        if path.exists():
            return path
    return None


def _load_logo_pixmap(exchange_code: str, size: int) -> QPixmap | None:
    logo_path = _resolve_logo_path(exchange_code)
    if logo_path is None:
        return None

    pixmap = QPixmap(str(logo_path))
    if pixmap.isNull():
        return None

    # Fill available square more aggressively than KeepAspectRatio.
    scaled = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    if scaled.isNull():
        return None

    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)

    painter = QPainter(result)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return result


def _create_badge_pixmap(exchange_code: str, size: int = 18) -> QPixmap:
    logo_pixmap = _load_logo_pixmap(exchange_code, size)
    if logo_pixmap is not None:
        return logo_pixmap

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
