from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap

from core.exchange.catalog import get_exchange_meta, normalize_exchange_code


# ui/widgets -> ui/assets/logos/exchanges
_ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets" / "logos" / "exchanges"
_SUPPORTED_EXTENSIONS = (".png", ".svg", ".ico", ".webp", ".jpg", ".jpeg")
_LOGO_SCALE_OVERRIDES = {
    # Some official assets include large internal safe margins.
    "bitget": 1.35,
}


def _resolve_logo_path(exchange_code: str) -> Path | None:
    code = normalize_exchange_code(exchange_code)
    for ext in _SUPPORTED_EXTENSIONS:
        path = _ASSETS_DIR / f"{code}{ext}"
        if path.exists():
            return path
    return None


def _trim_transparent(image: QImage) -> QImage:
    if image.isNull() or not image.hasAlphaChannel():
        return image

    img = image.convertToFormat(QImage.Format.Format_ARGB32)
    width = img.width()
    height = img.height()

    min_x = width
    min_y = height
    max_x = -1
    max_y = -1

    for y in range(height):
        for x in range(width):
            alpha = (img.pixel(x, y) >> 24) & 0xFF
            if alpha > 0:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

    if max_x < min_x or max_y < min_y:
        return img

    return img.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


def _load_logo_pixmap(exchange_code: str, size: int) -> QPixmap | None:
    normalized_code = normalize_exchange_code(exchange_code)
    logo_path = _resolve_logo_path(normalized_code)
    if logo_path is None:
        return None

    pixmap = QPixmap(str(logo_path))
    if pixmap.isNull():
        return None

    trimmed = _trim_transparent(pixmap.toImage())
    if not trimmed.isNull():
        pixmap = QPixmap.fromImage(trimmed)

    scale_factor = _LOGO_SCALE_OVERRIDES.get(normalized_code, 1.0)
    target_size = max(size, int(round(size * scale_factor)))

    # Force-fill square and optionally zoom for specific logos.
    scaled = pixmap.scaled(
        target_size,
        target_size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
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
