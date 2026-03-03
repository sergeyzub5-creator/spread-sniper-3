from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget


class SpreadDesignLabTab(QWidget):
    """Reserved empty tab for future UI/tests."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addStretch(1)

    def apply_theme(self):
        pass

    def retranslate_ui(self):
        pass
