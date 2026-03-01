from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.exchange.catalog import EXCHANGE_ORDER, get_exchange_meta, normalize_exchange_code
from ui.widgets.exchange_badge import build_exchange_icon
from ui.widgets.exchange_panel import ExchangePanel


class ExchangePickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_code = None
        self.setWindowTitle("Выбор биржи")
        self.setMinimumSize(500, 420)
        self.resize(540, 460)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #14181c;
                color: #e8eef2;
            }
            QLabel {
                color: #e8eef2;
                font-size: 14px;
                font-weight: bold;
            }
            QListWidget {
                background-color: #0f1318;
                border: 1px solid #2a343c;
                border-radius: 6px;
                padding: 6px;
                color: #e8eef2;
                font-size: 13px;
                outline: none;
            }
            QListWidget::item {
                padding: 10px 12px;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #1e2429;
            }
            QListWidget::item:selected {
                background-color: rgba(42, 58, 90, 72);
                color: #7aa2f7;
            }
            QPushButton {
                border-radius: 4px;
                padding: 7px 14px;
                min-width: 110px;
            }
            QPushButton#primaryButton {
                background-color: #2a3a5a;
                color: #7aa2f7;
                border: 1px solid #7aa2f7;
                font-weight: bold;
            }
            QPushButton#primaryButton:hover {
                background-color: #3a4a7a;
            }
            QPushButton#secondaryButton {
                background-color: #2a343c;
                color: #a0b0c0;
                border: 1px solid #a0b0c0;
            }
            QPushButton#secondaryButton:hover {
                background-color: #3a4a5a;
            }
            QPushButton:disabled {
                color: #6c7680;
                border-color: #3b444c;
                background-color: #1c2329;
            }
        """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Выберите биржу для добавления")
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

        self.add_btn = QPushButton("Добавить")
        self.add_btn.setObjectName("primaryButton")
        self.add_btn.clicked.connect(self._accept_selected)
        self.add_btn.setEnabled(self.list_widget.currentItem() is not None)
        buttons_row.addWidget(self.add_btn)

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setObjectName("secondaryButton")
        self.cancel_btn.clicked.connect(self.reject)
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
        self.setWindowTitle(f"Новое подключение: {meta['title']}")
        self.setMinimumSize(900, 320)
        self.resize(980, 360)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #0f1318;
                color: #e8eef2;
            }
        """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.panel = ExchangePanel("Новое подключение", exchange_type, is_new=True)
        layout.addWidget(self.panel)


class ExchangesTab(QWidget):
    exchange_added = Signal(str, str, dict)
    exchange_removed = Signal(str)

    def __init__(self, exchange_manager, parent=None):
        super().__init__(parent)
        self.exchange_manager = exchange_manager
        self.exchange_panels = {}

        self.new_panel = None
        self.new_panel_exchange_type = None
        self.new_panel_exchange_name = None
        self.new_exchange_dialog = None

        self._init_ui()

        self.exchange_manager.exchange_added.connect(self._on_exchange_added)
        self.exchange_manager.exchange_removed.connect(self._on_exchange_removed)
        self.exchange_manager.status_updated.connect(self._update_all_status)

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.add_btn = QPushButton("Добавить биржу")
        self.add_btn.setMinimumWidth(140)
        self.add_btn.setStyleSheet(
            """
            QPushButton { background-color: #2a3a5a; color: #7aa2f7; border: 1px solid #7aa2f7; border-radius: 4px; padding: 6px 12px; font-weight: bold; }
            QPushButton:hover { background-color: #3a4a7a; }
        """
        )
        self.add_btn.clicked.connect(self._add_new_panel)

        controls.addWidget(self.add_btn)
        controls.addStretch()

        connect_buttons = QHBoxLayout()
        connect_buttons.setSpacing(5)

        self.connect_all_btn = QPushButton("Подключить все")
        self.connect_all_btn.setMinimumWidth(130)
        self.connect_all_btn.setStyleSheet(
            """
            QPushButton { background-color: #2a5a3a; color: #7ec8a6; border: 1px solid #7ec8a6; border-radius: 4px; padding: 6px 12px; }
            QPushButton:hover { background-color: #3a6a4a; }
        """
        )
        self.connect_all_btn.clicked.connect(self._connect_all)

        self.disconnect_all_btn = QPushButton("Отключить все")
        self.disconnect_all_btn.setMinimumWidth(130)
        self.disconnect_all_btn.setStyleSheet(
            """
            QPushButton { background-color: #5a2a2a; color: #e06c75; border: 1px solid #e06c75; border-radius: 4px; padding: 6px 12px; }
            QPushButton:hover { background-color: #6a3a3a; }
        """
        )
        self.disconnect_all_btn.clicked.connect(self._disconnect_all)

        connect_buttons.addWidget(self.connect_all_btn)
        connect_buttons.addWidget(self.disconnect_all_btn)
        controls.addLayout(connect_buttons)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #2a343c; border-radius: 4px; background-color: #0a0c10; }"
        )

        self.container = QWidget()
        self.panels_layout = QVBoxLayout(self.container)
        self.panels_layout.setContentsMargins(2, 2, 2, 2)
        self.panels_layout.setSpacing(2)
        self.panels_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.container)

        layout.addLayout(controls)
        layout.addWidget(scroll)
        self.setLayout(layout)

        self._load_existing()

    def _load_existing(self):
        statuses = self.exchange_manager.get_all_status()
        for name, exchange in self.exchange_manager.get_all_exchanges().items():
            self._create_panel(name, exchange, statuses.get(name))

    def _create_panel(self, name, exchange, status=None):
        exchange_type = normalize_exchange_code(getattr(exchange, "exchange_type", None))

        panel = ExchangePanel(name, exchange_type, is_new=False)
        panel.connect_clicked.connect(self._on_panel_connect)
        panel.disconnect_clicked.connect(self._on_panel_disconnect)
        panel.remove_clicked.connect(self._on_panel_remove)

        params = {
            "api_key": exchange.api_key,
            "api_secret": exchange.api_secret,
            "testnet": exchange.testnet,
        }
        if hasattr(exchange, "api_passphrase") and exchange.api_passphrase:
            params["api_passphrase"] = exchange.api_passphrase

        panel.load_saved_data(params)

        if status is None:
            status = {
                "connected": exchange.is_connected,
                "loading": False,
                "testnet": exchange.testnet,
                "balance": exchange.balance,
                "positions_count": len(exchange.positions),
                "pnl": exchange.pnl,
                "status_text": exchange.get_status_text(),
            }
        panel.update_status(status)

        self.panels_layout.addWidget(panel)
        self.exchange_panels[name] = panel

    def _clear_new_panel_state(self):
        self.new_panel = None
        self.new_panel_exchange_type = None
        self.new_panel_exchange_name = None
        self.new_exchange_dialog = None

    def _on_new_dialog_closed(self):
        self._clear_new_panel_state()

    def _add_new_panel(self):
        if self.new_panel is not None and self.new_exchange_dialog is not None:
            self.new_exchange_dialog.raise_()
            self.new_exchange_dialog.activateWindow()
            return

        picker = ExchangePickerDialog(self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return

        exchange_type = picker.selected_exchange_code()
        if not exchange_type:
            return

        dialog = NewExchangeDialog(exchange_type, self)
        panel = dialog.panel
        panel.connect_clicked.connect(self._on_new_panel_connect)
        panel.cancel_clicked.connect(self._cancel_new_panel)
        dialog.finished.connect(lambda _code: self._on_new_dialog_closed())

        self.new_exchange_dialog = dialog
        self.new_panel = panel
        self.new_panel_exchange_type = exchange_type
        self.new_panel_exchange_name = None

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _cancel_new_panel(self):
        dialog = self.new_exchange_dialog
        self._clear_new_panel_state()
        if dialog is not None:
            dialog.close()

    def set_new_panel_error(self, message):
        if self.new_panel is None:
            return
        self.new_panel.status_label.setText(message)
        self.new_panel.status_label.setStyleSheet("color: #e06c75; font-size: 11px;")
        self.new_panel.status_label.setVisible(True)
        if self.new_exchange_dialog is not None:
            self.new_exchange_dialog.raise_()
            self.new_exchange_dialog.activateWindow()

    def _on_new_panel_connect(self, _name, params):
        selected_type = self.new_panel_exchange_type
        if not selected_type and self.new_panel is not None:
            selected_type = self.new_panel.exchange_type
        type_code = normalize_exchange_code(selected_type)

        base_name = get_exchange_meta(type_code)["base_name"]
        final_name = base_name
        counter = 1
        while final_name in self.exchange_panels:
            final_name = f"{base_name}{counter}"
            counter += 1

        self.new_panel_exchange_name = final_name
        if self.new_panel is not None:
            self.new_panel.exchange_name = final_name
            self.new_panel.status_label.setText("Загрузка...")
            self.new_panel.status_label.setStyleSheet("color: #7aa2f7; font-size: 11px;")
            self.new_panel.status_label.setVisible(True)

        self.exchange_added.emit(final_name, type_code, params)

    def _on_panel_connect(self, name, params):
        panel = self.sender()
        if not panel:
            return
        self.exchange_added.emit(name, panel.exchange_type, params)

    def _on_panel_disconnect(self, name):
        exchange = self.exchange_manager.get_exchange(name)
        if exchange:
            exchange.disconnect()
            status = {
                "connected": False,
                "loading": False,
                "testnet": exchange.testnet,
                "balance": 0,
                "positions_count": 0,
                "pnl": 0,
                "status_text": "Отключено",
            }
            if name in self.exchange_panels:
                self.exchange_panels[name].update_status(status)

    def _on_panel_remove(self, name):
        panel = self.exchange_panels.get(name)
        display_name = name
        if panel:
            meta = get_exchange_meta(panel.exchange_type)
            display_name = f"{meta['base_name']} ({name})"
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить биржу {display_name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.exchange_removed.emit(name)

    def _on_exchange_added(self, name):
        exchange = self.exchange_manager.get_exchange(name)
        if exchange and name not in self.exchange_panels:
            status = self.exchange_manager.get_all_status().get(name)
            self._create_panel(name, exchange, status=status)

        if self.new_panel_exchange_name == name:
            self._cancel_new_panel()

    def _on_exchange_removed(self, name):
        if name in self.exchange_panels:
            panel = self.exchange_panels[name]
            panel.hide()
            self.panels_layout.removeWidget(panel)
            panel.deleteLater()
            del self.exchange_panels[name]

    def _update_all_status(self, statuses):
        for name, status in statuses.items():
            if name in self.exchange_panels:
                self.exchange_panels[name].update_status(status)

    def _connect_all(self):
        self.exchange_manager.connect_all_async()

    def _disconnect_all(self):
        self.exchange_manager.disconnect_all()
