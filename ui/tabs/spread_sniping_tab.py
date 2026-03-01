from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from core.i18n import tr
from ui.styles import theme_color


class SpreadSnipingTab(QWidget):
    def __init__(self, exchange_manager, parent=None):
        super().__init__(parent)
        self.exchange_manager = exchange_manager
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.container = QFrame()

        card_layout = QVBoxLayout(self.container)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(8)

        self.title_label = QLabel()
        self.title_label.setObjectName("title")

        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("subtitle")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.subtitle_label)
        card_layout.addStretch()

        layout.addWidget(self.container)
        layout.addStretch()

        self.apply_theme()
        self.retranslate_ui()

    def apply_theme(self):
        c_surface = theme_color("surface")
        c_border = theme_color("border")
        c_primary = theme_color("text_primary")
        c_muted = theme_color("text_muted")
        self.container.setStyleSheet(
            f"""
            QFrame {{
                background-color: {c_surface};
                border: 1px solid {c_border};
                border-radius: 6px;
            }}
            QLabel#title {{
                color: {c_primary};
                font-size: 16px;
                font-weight: bold;
            }}
            QLabel#subtitle {{
                color: {c_muted};
                font-size: 13px;
            }}
        """
        )

    def retranslate_ui(self):
        self.title_label.setText(tr("spread.title"))
        self.subtitle_label.setText(tr("spread.subtitle"))
