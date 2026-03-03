from __future__ import annotations

from PySide6.QtGui import QFont, QFontMetrics


def numeric_monospace_font(base_font: QFont) -> QFont:
    font = QFont(base_font)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    return font


def apply_stable_numeric_label(label, sample_texts, extra_padding=18):
    if label is None:
        return

    font = numeric_monospace_font(label.font())
    label.setFont(font)

    metrics = QFontMetrics(font)
    width = 0
    for sample in sample_texts or []:
        width = max(width, metrics.horizontalAdvance(str(sample or "")))

    if width > 0:
        label.setMinimumWidth(width + int(extra_padding))

