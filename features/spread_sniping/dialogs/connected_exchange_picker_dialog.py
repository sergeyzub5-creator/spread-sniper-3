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

from core.i18n import tr
from ui.styles import button_style, theme_color
from ui.widgets.exchange_badge import build_exchange_icon


class ConnectedExchangePickerDialog(QDialog):
    def __init__(self, rows, selector_index, current_name=None, parent=None):
        super().__init__(parent)
        self.selected_name = None
        self.reset_requested = False
        self.rows = list(rows or [])
        self.selector_index = selector_index

        self.setWindowTitle(tr("spread.pick_exchange_title"))
        self.setMinimumSize(480, 420)
        self.resize(520, 460)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {theme_color('surface')};
                color: {theme_color('text_primary')};
            }}
            QLabel {{
                color: {theme_color('text_primary')};
                font-size: 14px;
                font-weight: 700;
            }}
            QListWidget {{
                background-color: {theme_color('window_bg')};
                border: 1px solid {theme_color('border')};
                border-radius: 10px;
                padding: 8px;
                color: {theme_color('text_primary')};
                font-size: 13px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-radius: 8px;
                margin: 2px;
            }}
            QListWidget::item:hover {{
                background-color: {theme_color('surface_alt')};
            }}
            QListWidget::item:selected {{
                background-color: {theme_color('selection_bg_soft')};
                color: {theme_color('accent')};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel(tr("spread.pick_exchange_prompt", index=selector_index))
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(28, 28))
        self.list_widget.setSpacing(4)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept_selected())

        current_row_index = -1
        for idx, (name, exchange_type) in enumerate(self.rows):
            item = QListWidgetItem(build_exchange_icon(exchange_type, size=28), name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list_widget.addItem(item)
            if current_name and name == current_name:
                current_row_index = idx

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(current_row_index if current_row_index >= 0 else 0)

        layout.addWidget(self.list_widget)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.select_btn = QPushButton(tr("action.select"))
        self.select_btn.setStyleSheet(button_style("primary", padding="7px 14px", bold=True))
        self.select_btn.setMinimumWidth(120)
        self.select_btn.setEnabled(self.list_widget.currentItem() is not None)
        self.select_btn.clicked.connect(self._accept_selected)
        buttons.addWidget(self.select_btn)

        self.cancel_btn = QPushButton(tr("action.cancel"))
        self.cancel_btn.setStyleSheet(button_style("secondary", padding="7px 14px"))
        self.cancel_btn.setMinimumWidth(120)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)

        self.reset_btn = QPushButton(tr("action.reset"))
        self.reset_btn.setStyleSheet(button_style("warning", padding="7px 14px"))
        self.reset_btn.setMinimumWidth(120)
        self.reset_btn.clicked.connect(self._request_reset)
        self.reset_btn.setVisible(bool(current_name))
        buttons.addWidget(self.reset_btn)

        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        layout.addLayout(buttons)

    def _on_current_item_changed(self, current, _previous):
        self.select_btn.setEnabled(current is not None)

    def _accept_selected(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_name = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _request_reset(self):
        self.selected_name = None
        self.reset_requested = True
        self.accept()

