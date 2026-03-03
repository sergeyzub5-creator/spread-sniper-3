from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from core.exchange.catalog import EXCHANGE_ORDER, get_exchange_meta
from core.i18n import tr
from ui.styles import button_style, theme_color
from ui.widgets.exchange_badge import build_exchange_icon
from ui.widgets.exchange_panel import ExchangePanel


class ExchangePickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_code = None
        self.setWindowTitle(tr("exchange_picker.title"))
        self.setMinimumSize(500, 420)
        self.resize(540, 460)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {theme_color('surface')};
                color: {theme_color('text_primary')};
            }}
            QLabel {{
                color: {theme_color('text_primary')};
                font-size: 14px;
                font-weight: bold;
            }}
            QListWidget {{
                background-color: {theme_color('window_bg')};
                border: 1px solid {theme_color('border')};
                border-radius: 10px;
                padding: 6px;
                color: {theme_color('text_primary')};
                font-size: 13px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-radius: 8px;
            }}
            QListWidget::item:hover {{
                background-color: {theme_color('surface_alt')};
            }}
            QListWidget::item:selected {{
                background-color: {theme_color('selection_bg_soft')};
                color: {theme_color('accent')};
            }}
            QPushButton {{
                border-radius: 10px;
                padding: 7px 14px;
                min-width: 110px;
            }}
            QPushButton:disabled {{
                color: {theme_color('text_muted')};
                border-color: {theme_color('border')};
                background-color: {theme_color('surface_alt')};
            }}
        """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel(tr("exchange_picker.prompt"))
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(31, 31))
        self.list_widget.setSpacing(4)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept_selected())

        for code in EXCHANGE_ORDER:
            meta = get_exchange_meta(code)
            item = QListWidgetItem(build_exchange_icon(code, size=31), meta["title"])
            item.setData(Qt.ItemDataRole.UserRole, code)
            self.list_widget.addItem(item)

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        layout.addWidget(self.list_widget)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch()

        self.add_btn = QPushButton(tr("action.add"))
        self.add_btn.clicked.connect(self._accept_selected)
        self.add_btn.setStyleSheet(button_style("primary", padding="7px 14px", bold=True))
        self.add_btn.setEnabled(self.list_widget.currentItem() is not None)
        buttons_row.addWidget(self.add_btn)

        self.cancel_btn = QPushButton(tr("action.cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setStyleSheet(button_style("secondary", padding="7px 14px"))
        buttons_row.addWidget(self.cancel_btn)

        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        layout.addLayout(buttons_row)

    def _on_current_item_changed(self, current, _previous):
        if not hasattr(self, "add_btn"):
            return
        self.add_btn.setEnabled(current is not None)

    def _accept_selected(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_code = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def selected_exchange_code(self):
        return self.selected_code


class NewExchangeDialog(QDialog):
    def __init__(self, exchange_type, parent=None):
        super().__init__(parent)
        meta = get_exchange_meta(exchange_type)
        self.setWindowTitle(tr("exchanges.new_connection_title", title=meta["title"]))
        self.setMinimumSize(900, 320)
        self.resize(980, 360)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {theme_color('surface')};
                color: {theme_color('text_primary')};
            }}
        """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.panel = ExchangePanel(tr("exchanges.new_connection_name"), exchange_type, is_new=True)
        layout.addWidget(self.panel)

