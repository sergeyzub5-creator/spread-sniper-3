from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.exchange.catalog import get_exchange_meta, normalize_exchange_code, requires_passphrase
from ui.widgets.exchange_badge import build_exchange_pixmap


class ExchangePanel(QFrame):
    connect_clicked = Signal(str, dict)
    disconnect_clicked = Signal(str)
    remove_clicked = Signal(str)
    cancel_clicked = Signal()

    def __init__(self, exchange_name, exchange_type, is_new=False, parent=None):
        super().__init__(parent)
        self.exchange_name = exchange_name
        self.exchange_type = normalize_exchange_code(exchange_type)
        self.exchange_meta = get_exchange_meta(self.exchange_type)
        self.is_connected = False
        self.testnet = False
        self.is_new = is_new
        self.edit_mode = is_new
        self._last_status_snapshot = None

        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setStyleSheet(
            """
            QFrame {
                border: 1px solid #2a343c;
                border-radius: 4px;
                background-color: #14181c;
                margin: 2px;
                padding: 8px;
            }
        """
        )

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setPixmap(build_exchange_pixmap(self.exchange_type, size=46))
        self.icon_label.setFixedSize(46, 46)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_label = QLabel(self.exchange_name)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setMinimumWidth(80)

        self.status_label = QLabel("Не подключено")
        self.status_label.setStyleSheet("color: #a0b0c0; font-size: 11px;")
        self.status_label.setMinimumWidth(120)

        header.addWidget(self.icon_label)
        header.addWidget(self.name_label)
        header.addWidget(self.status_label)
        header.addStretch()
        layout.addLayout(header)

        self.stats_widget = QWidget()
        stats_layout = QHBoxLayout(self.stats_widget)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(8)
        self.balance_label = QLabel("Баланс: -- USDT")
        self.balance_label.setStyleSheet("color: #7ec8a6; font-size: 12px; font-weight: bold;")
        self.positions_label = QLabel("Позиции: --")
        self.positions_label.setStyleSheet("color: #e5c07b; font-size: 12px;")
        self.pnl_label = QLabel("ПнЛ: 0.00 USDT")
        self.pnl_label.setStyleSheet("color: #a0b0c0; font-size: 12px; font-weight: bold;")
        stats_layout.addWidget(self.balance_label)
        stats_layout.addWidget(self.positions_label)
        stats_layout.addWidget(self.pnl_label)
        stats_layout.addStretch()
        layout.addWidget(self.stats_widget)

        if self.is_new:
            self.stats_widget.setVisible(False)
            self.name_label.setVisible(False)
            self.icon_label.setFixedSize(64, 64)
            self.icon_label.setPixmap(build_exchange_pixmap(self.exchange_type, size=64))
            self.status_label.setText("")
            self.status_label.setVisible(False)

        self.api_group = QGroupBox(f"API-данные · {self.exchange_meta['title']}")
        api_layout = QHBoxLayout()
        api_layout.setSpacing(5)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("API ключ")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setMinimumWidth(180)

        self.api_secret_input = QLineEdit()
        self.api_secret_input.setPlaceholderText("API секрет")
        self.api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_secret_input.setMinimumWidth(180)

        self.passphrase_input = QLineEdit()
        self.passphrase_input.setPlaceholderText("Пароль API")
        self.passphrase_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.passphrase_input.setMinimumWidth(120)

        self.testnet_check = QCheckBox("Демо-режим")
        self.testnet_check.setStyleSheet("color: #e5c07b;")
        self.testnet_check.stateChanged.connect(self._on_testnet_changed)

        api_layout.addWidget(self.api_key_input)
        api_layout.addWidget(self.api_secret_input)
        api_layout.addWidget(self.passphrase_input)
        api_layout.addWidget(self.testnet_check)
        api_layout.addStretch()

        self.api_group.setLayout(api_layout)
        layout.addWidget(self.api_group)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(5)

        self.connect_btn = QPushButton("Подключить")
        self.connect_btn.setMinimumWidth(100)
        self.connect_btn.setStyleSheet(
            """
            QPushButton { background-color: #2a3a5a; color: #7aa2f7; border: 1px solid #7aa2f7; border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background-color: #3a4a7a; }
        """
        )
        self.connect_btn.clicked.connect(self._on_connect)

        self.disconnect_btn = QPushButton("Отключить")
        self.disconnect_btn.setMinimumWidth(100)
        self.disconnect_btn.setStyleSheet(
            """
            QPushButton { background-color: #5a2a2a; color: #e06c75; border: 1px solid #e06c75; border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background-color: #6a3a3a; }
        """
        )
        self.disconnect_btn.clicked.connect(lambda: self.disconnect_clicked.emit(self.exchange_name))

        self.edit_btn = QPushButton("Изменить")
        self.edit_btn.setMinimumWidth(100)
        self.edit_btn.setStyleSheet(
            """
            QPushButton { background-color: #3a3a2a; color: #e5c07b; border: 1px solid #e5c07b; border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background-color: #5a5a3a; }
        """
        )
        self.edit_btn.clicked.connect(lambda: self.set_edit_mode(True))

        self.remove_btn = QPushButton("Удалить")
        self.remove_btn.setMinimumWidth(100)
        self.remove_btn.setStyleSheet(
            """
            QPushButton { background-color: #2a343c; color: #a0b0c0; border: 1px solid #a0b0c0; border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background-color: #3a4a5a; }
        """
        )
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.exchange_name))

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setMinimumWidth(100)
        self.cancel_btn.setStyleSheet(
            """
            QPushButton { background-color: #3a3a2a; color: #e5c07b; border: 1px solid #e5c07b; border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background-color: #5a5a3a; }
        """
        )
        self.cancel_btn.clicked.connect(self._on_cancel)

        button_layout.addWidget(self.connect_btn)
        button_layout.addWidget(self.disconnect_btn)
        button_layout.addWidget(self.edit_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.remove_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.setLayout(layout)
        self._update_passphrase_hint()
        self._update_ui_state()

    def _update_passphrase_hint(self):
        if requires_passphrase(self.exchange_type):
            self.passphrase_input.setPlaceholderText("Пароль API (обязательно)")
        else:
            self.passphrase_input.setPlaceholderText("Пароль API (необязательно)")

    def set_edit_mode(self, edit_mode):
        self.edit_mode = edit_mode
        self._update_ui_state()

    def _update_ui_state(self):
        if self.is_connected:
            self.status_label.setText("Подключено")
            self.status_label.setStyleSheet("color: #7ec8a6; font-size: 11px;")
            self.status_label.setVisible(True)
            self.connect_btn.setVisible(False)
            self.disconnect_btn.setVisible(True)
            self.edit_btn.setVisible(False)
            self.api_group.setVisible(False)
        else:
            if self.is_new:
                self.status_label.setText("")
                self.status_label.setVisible(False)
            else:
                self.status_label.setText("Не подключено")
                self.status_label.setStyleSheet("color: #a0b0c0; font-size: 11px;")
                self.status_label.setVisible(True)
            self.balance_label.setText("Баланс: -- USDT")
            self.positions_label.setText("Позиции: --")
            self._set_pnl_display(0.0, 0)

            if self.edit_mode:
                self.connect_btn.setText("Добавить" if self.is_new else "Подключить")
                self.connect_btn.setVisible(True)
                self.disconnect_btn.setVisible(False)
                self.edit_btn.setVisible(False)
                self.cancel_btn.setVisible(True)
                self.api_group.setVisible(True)
            else:
                self.connect_btn.setVisible(False)
                self.disconnect_btn.setVisible(False)
                self.edit_btn.setVisible(True)
                self.cancel_btn.setVisible(False)
                self.api_group.setVisible(False)

        self.remove_btn.setVisible(not self.is_new)

    def _set_pnl_display(self, pnl, positions_count):
        if positions_count <= 0:
            display_pnl = 0.0
            color = "#a0b0c0"
            text = f"ПнЛ: {display_pnl:,.2f} USDT"
        elif pnl > 0:
            display_pnl = pnl
            color = "#7ec8a6"
            text = f"ПнЛ: +{display_pnl:,.2f} USDT"
        elif pnl < 0:
            display_pnl = pnl
            color = "#e06c75"
            text = f"ПнЛ: {display_pnl:,.2f} USDT"
        else:
            display_pnl = 0.0
            color = "#a0b0c0"
            text = f"ПнЛ: {display_pnl:,.2f} USDT"

        self.pnl_label.setText(text)
        self.pnl_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")

    def _on_cancel(self):
        if self.is_new:
            self.cancel_clicked.emit()
        else:
            self.set_edit_mode(False)

    def _on_testnet_changed(self, state):
        self.testnet = state == Qt.CheckState.Checked.value

    @staticmethod
    def _is_ascii(value):
        try:
            str(value).encode("ascii")
            return True
        except UnicodeEncodeError:
            return False

    def _show_input_error(self, message):
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #e06c75; font-size: 11px;")
        self.status_label.setVisible(True)

    def _on_connect(self):
        if not self.edit_mode:
            return

        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()

        if not api_key or not api_secret:
            self._show_input_error("API ключ и API секрет обязательны")
            return

        if not self._is_ascii(api_key) or not self._is_ascii(api_secret):
            self._show_input_error("Неверный формат ключа: используйте только латиницу")
            return

        params = {
            "api_key": api_key,
            "api_secret": api_secret,
            "testnet": self.testnet,
        }

        if requires_passphrase(self.exchange_type):
            passphrase = self.passphrase_input.text().strip()
            if not passphrase:
                self._show_input_error("Пароль API обязателен")
                return
            if not self._is_ascii(passphrase):
                self._show_input_error("Неверный формат пароля API: используйте только латиницу")
                return
            params["api_passphrase"] = passphrase
        else:
            passphrase = self.passphrase_input.text().strip()
            if passphrase:
                if not self._is_ascii(passphrase):
                    self._show_input_error("Неверный формат пароля API: используйте только латиницу")
                    return
                params["api_passphrase"] = passphrase

        self.connect_clicked.emit(self.exchange_name, params)

    def update_status(self, status):
        if self.is_new:
            return

        snapshot = {
            "connected": bool(status.get("connected", False)),
            "loading": bool(status.get("loading", False)),
            "testnet": bool(status.get("testnet", False)),
            "balance": float(status.get("balance", 0) or 0),
            "positions_count": int(status.get("positions_count", 0) or 0),
            "pnl": float(status.get("pnl", 0) or 0),
            "status_text": str(status.get("status_text", "") or ""),
        }

        if snapshot == self._last_status_snapshot:
            return

        prev_connected = self.is_connected
        self.is_connected = snapshot["connected"]

        if self.is_connected:
            mode = "Демо" if snapshot["testnet"] else "Реал"
            self.status_label.setText(f"Подключено · {mode}")
            self.status_label.setStyleSheet("color: #7ec8a6; font-size: 11px;")
            self.balance_label.setText(f"Баланс: {snapshot['balance']:,.2f} USDT")
            self.positions_label.setText(f"Позиции: {snapshot['positions_count']}")
            self._set_pnl_display(snapshot["pnl"], snapshot["positions_count"])
        else:
            status_text = snapshot["status_text"].strip() or "Не подключено"
            lower_text = status_text.lower()

            if snapshot["loading"]:
                status_text = "Загрузка..."
                color = "#7aa2f7"
            elif "ошибка" in lower_text or "не реализовано" in lower_text:
                color = "#e06c75"
            else:
                color = "#a0b0c0"

            self.status_label.setText(status_text)
            self.status_label.setStyleSheet(f"color: {color}; font-size: 11px;")
            self.balance_label.setText("Баланс: -- USDT")
            self.positions_label.setText("Позиции: --")
            self._set_pnl_display(0.0, 0)

        if prev_connected != self.is_connected:
            self._update_ui_state()

        self._last_status_snapshot = snapshot

    def load_saved_data(self, params):
        if params.get("api_key"):
            self.api_key_input.setText(params["api_key"])
        if params.get("api_secret"):
            self.api_secret_input.setText(params["api_secret"])
        if params.get("api_passphrase"):
            self.passphrase_input.setText(params["api_passphrase"])
        self.testnet_check.setChecked(params.get("testnet", False))
        self.testnet = params.get("testnet", False)
