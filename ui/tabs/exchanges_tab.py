from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal

from core.exchange.catalog import (
    EXCHANGE_ORDER,
    get_exchange_meta,
    normalize_exchange_code,
)
from ui.widgets.exchange_badge import build_exchange_icon
from ui.widgets.exchange_panel import ExchangePanel


class ExchangesTab(QWidget):
    exchange_added = Signal(str, str, dict)
    exchange_removed = Signal(str)

    def __init__(self, exchange_manager, parent=None):
        super().__init__(parent)
        self.exchange_manager = exchange_manager
        self.exchange_panels = {}
        self.new_panel = None

        self._init_ui()

        self.exchange_manager.exchange_added.connect(self._on_exchange_added)
        self.exchange_manager.exchange_removed.connect(self._on_exchange_removed)
        self.exchange_manager.status_updated.connect(self._update_all_status)

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.type_combo = QComboBox()
        self._populate_exchange_types()
        self.type_combo.setMinimumWidth(220)
        self.type_combo.setStyleSheet(
            """
            QComboBox { background-color: #1e2429; color: #e8eef2; border: 1px solid #2a343c; border-radius: 4px; padding: 5px; }
        """
        )

        self.add_btn = QPushButton("➕ Добавить биржу")
        self.add_btn.setMinimumWidth(130)
        self.add_btn.setStyleSheet(
            """
            QPushButton { background-color: #2a3a5a; color: #7aa2f7; border: 1px solid #7aa2f7; border-radius: 4px; padding: 6px 12px; font-weight: bold; }
            QPushButton:hover { background-color: #3a4a7a; }
        """
        )
        self.add_btn.clicked.connect(self._add_new_panel)

        controls.addWidget(QLabel("Новая биржа:"))
        controls.addWidget(self.type_combo)
        controls.addWidget(self.add_btn)
        controls.addStretch()

        connect_buttons = QHBoxLayout()
        connect_buttons.setSpacing(5)

        self.connect_all_btn = QPushButton("🔌 Подключить все")
        self.connect_all_btn.setMinimumWidth(130)
        self.connect_all_btn.setStyleSheet(
            """
            QPushButton { background-color: #2a5a3a; color: #7ec8a6; border: 1px solid #7ec8a6; border-radius: 4px; padding: 6px 12px; }
            QPushButton:hover { background-color: #3a6a4a; }
        """
        )
        self.connect_all_btn.clicked.connect(self._connect_all)

        self.disconnect_all_btn = QPushButton("🔌 Отключить все")
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

    def _populate_exchange_types(self):
        self.type_combo.clear()
        for code in EXCHANGE_ORDER:
            meta = get_exchange_meta(code)
            self.type_combo.addItem(build_exchange_icon(code), meta["title"], userData=code)

    def _load_existing(self):
        for name, exchange in self.exchange_manager.get_all_exchanges().items():
            self._create_panel(name, exchange)

    def _create_panel(self, name, exchange):
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

        status = {
            "connected": exchange.is_connected,
            "testnet": exchange.testnet,
            "balance": exchange.balance,
            "positions_count": len(exchange.positions),
            "pnl": exchange.pnl,
            "status_text": exchange.get_status_text(),
        }
        panel.update_status(status)

        self.panels_layout.addWidget(panel)
        self.exchange_panels[name] = panel

    def _add_new_panel(self):
        if self.new_panel is not None:
            return

        exchange_type = self.type_combo.currentData()
        panel = ExchangePanel("Новое подключение", exchange_type, is_new=True)
        panel.connect_clicked.connect(self._on_new_panel_connect)
        panel.cancel_clicked.connect(self._cancel_new_panel)

        self.new_panel = panel
        self.panels_layout.insertWidget(0, panel)

    def _cancel_new_panel(self):
        if self.new_panel:
            self.new_panel.hide()
            self.panels_layout.removeWidget(self.new_panel)
            self.new_panel.deleteLater()
            self.new_panel = None

    def _on_new_panel_connect(self, _name, params):
        type_code = normalize_exchange_code(self.type_combo.currentData())
        base_name = get_exchange_meta(type_code)["base_name"]
        final_name = base_name
        counter = 1
        while final_name in self.exchange_panels:
            final_name = f"{base_name}{counter}"
            counter += 1

        self.exchange_added.emit(final_name, type_code, params)
        self._cancel_new_panel()

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
            self._create_panel(name, exchange)

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
        for exchange in self.exchange_manager.get_all_exchanges().values():
            if not exchange.is_connected:
                exchange.connect()

    def _disconnect_all(self):
        self.exchange_manager.disconnect_all()
