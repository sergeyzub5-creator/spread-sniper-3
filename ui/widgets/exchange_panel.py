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
from core.i18n import tr
from ui.styles import button_style, theme_color
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

        self._init_ui()
        self.apply_theme()
        self.retranslate_ui()

    def apply_theme(self):
        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setStyleSheet(
            f"""
            QFrame {{
                border: 1px solid {theme_color('border')};
                border-radius: 4px;
                background-color: {theme_color('surface')};
                margin: 2px;
                padding: 8px;
            }}
        """
        )

        if not hasattr(self, "status_label"):
            return

        self.balance_label.setStyleSheet(self._metric_style("success", bold=True))
        self.positions_label.setStyleSheet(self._metric_style("warning"))
        self.testnet_check.setStyleSheet(f"color: {theme_color('warning')};")

        self.connect_btn.setStyleSheet(button_style("primary"))
        self.disconnect_btn.setStyleSheet(button_style("danger"))
        self.edit_btn.setStyleSheet(button_style("warning"))
        self.remove_btn.setStyleSheet(button_style("secondary"))
        self.cancel_btn.setStyleSheet(button_style("warning"))

        if self._last_status_snapshot is not None:
            self.update_status(dict(self._last_status_snapshot), force=True)
        else:
            self._update_ui_state()

    @staticmethod
    def _status_style(color_key):
        return f"color: {theme_color(color_key)}; font-size: 11px;"

    @staticmethod
    def _metric_style(color_key, bold=False):
        weight = "font-weight: bold;" if bold else ""
        return f"color: {theme_color(color_key)}; font-size: 12px; {weight}"

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setPixmap(build_exchange_pixmap(self.exchange_type, size=42))
        self.icon_label.setFixedSize(42, 42)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_label = QLabel(self.exchange_name)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setMinimumWidth(80)

        self.status_label = QLabel(tr("status.disconnected"))
        self.status_label.setStyleSheet(self._status_style("text_muted"))
        self.status_label.setMinimumWidth(140)

        header.addWidget(self.icon_label)
        header.addWidget(self.name_label)
        header.addWidget(self.status_label)
        header.addStretch()
        layout.addLayout(header)

        self.stats_widget = QWidget()
        stats_layout = QHBoxLayout(self.stats_widget)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(8)
        self.balance_label = QLabel(tr("label.balance_empty"))
        self.balance_label.setStyleSheet(self._metric_style("success", bold=True))
        self.positions_label = QLabel(tr("label.positions_empty"))
        self.positions_label.setStyleSheet(self._metric_style("warning"))
        self.pnl_label = QLabel(tr("label.pnl", value="0.00"))
        self.pnl_label.setStyleSheet(self._metric_style("text_muted", bold=True))
        stats_layout.addWidget(self.balance_label)
        stats_layout.addWidget(self.positions_label)
        stats_layout.addWidget(self.pnl_label)
        stats_layout.addStretch()
        layout.addWidget(self.stats_widget)

        if self.is_new:
            self.stats_widget.setVisible(False)
            self.name_label.setVisible(False)
            self.icon_label.setFixedSize(72, 72)
            self.icon_label.setPixmap(build_exchange_pixmap(self.exchange_type, size=72))
            self.status_label.setText("")
            self.status_label.setVisible(False)

        self.api_group = QGroupBox(tr("panel.api_group_title", title=self.exchange_meta["title"]))
        api_layout = QHBoxLayout()
        api_layout.setSpacing(5)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText(tr("panel.api_key_placeholder"))
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setMinimumWidth(180)

        self.api_secret_input = QLineEdit()
        self.api_secret_input.setPlaceholderText(tr("panel.api_secret_placeholder"))
        self.api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_secret_input.setMinimumWidth(180)

        self.passphrase_input = QLineEdit()
        self.passphrase_input.setPlaceholderText(tr("panel.passphrase_optional"))
        self.passphrase_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.passphrase_input.setMinimumWidth(120)

        self.testnet_check = QCheckBox(tr("panel.testnet"))
        self.testnet_check.setStyleSheet(f"color: {theme_color('warning')};")
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

        self.connect_btn = QPushButton(tr("action.connect"))
        self.connect_btn.setMinimumWidth(100)
        self.connect_btn.setStyleSheet(button_style("primary"))
        self.connect_btn.clicked.connect(self._on_connect)

        self.disconnect_btn = QPushButton(tr("action.disconnect"))
        self.disconnect_btn.setMinimumWidth(100)
        self.disconnect_btn.setStyleSheet(button_style("danger"))
        self.disconnect_btn.clicked.connect(lambda: self.disconnect_clicked.emit(self.exchange_name))

        self.edit_btn = QPushButton(tr("action.edit"))
        self.edit_btn.setMinimumWidth(100)
        self.edit_btn.setStyleSheet(button_style("warning"))
        self.edit_btn.clicked.connect(lambda: self.set_edit_mode(True))

        self.remove_btn = QPushButton(tr("action.remove"))
        self.remove_btn.setMinimumWidth(100)
        self.remove_btn.setStyleSheet(button_style("secondary"))
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.exchange_name))

        self.cancel_btn = QPushButton(tr("action.cancel"))
        self.cancel_btn.setMinimumWidth(100)
        self.cancel_btn.setStyleSheet(button_style("warning"))
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
            self.passphrase_input.setPlaceholderText(tr("panel.passphrase_required"))
        else:
            self.passphrase_input.setPlaceholderText(tr("panel.passphrase_optional"))

    def retranslate_ui(self):
        self.exchange_meta = get_exchange_meta(self.exchange_type)
        self.api_group.setTitle(tr("panel.api_group_title", title=self.exchange_meta["title"]))
        self.api_key_input.setPlaceholderText(tr("panel.api_key_placeholder"))
        self.api_secret_input.setPlaceholderText(tr("panel.api_secret_placeholder"))
        self.testnet_check.setText(tr("panel.testnet"))
        self.disconnect_btn.setText(tr("action.disconnect"))
        self.edit_btn.setText(tr("action.edit"))
        self.remove_btn.setText(tr("action.remove"))
        self.cancel_btn.setText(tr("action.cancel"))
        self._update_passphrase_hint()

        if self.is_new:
            self.name_label.setText(tr("exchanges.new_connection_name"))

        if self._last_status_snapshot is not None:
            self.update_status(dict(self._last_status_snapshot), force=True)
        else:
            self._update_ui_state()

    def set_edit_mode(self, edit_mode):
        self.edit_mode = edit_mode
        self._update_ui_state()

    def _update_ui_state(self):
        if self.is_connected:
            self.status_label.setText(tr("status.connected"))
            self.status_label.setStyleSheet(self._status_style("success"))
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
                self.status_label.setText(tr("status.disconnected"))
                self.status_label.setStyleSheet(self._status_style("text_muted"))
                self.status_label.setVisible(True)
            self.balance_label.setText(tr("label.balance_empty"))
            self.positions_label.setText(tr("label.positions_empty"))
            self._set_pnl_display(0.0, 0)

            if self.edit_mode:
                self.connect_btn.setText(tr("action.add") if self.is_new else tr("action.connect"))
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
            color_key = "text_muted"
            text = tr("label.pnl", value=f"{display_pnl:,.2f}")
        elif pnl > 0:
            display_pnl = pnl
            color_key = "success"
            text = tr("label.pnl_positive", value=f"{display_pnl:,.2f}")
        elif pnl < 0:
            display_pnl = pnl
            color_key = "danger"
            text = tr("label.pnl", value=f"{display_pnl:,.2f}")
        else:
            display_pnl = 0.0
            color_key = "text_muted"
            text = tr("label.pnl", value=f"{display_pnl:,.2f}")

        self.pnl_label.setText(text)
        self.pnl_label.setStyleSheet(self._metric_style(color_key, bold=True))

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
        self.status_label.setStyleSheet(self._status_style("danger"))
        self.status_label.setVisible(True)

    def _on_connect(self):
        if not self.edit_mode:
            return

        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()

        if not api_key or not api_secret:
            self._show_input_error(tr("panel.error.required_keys"))
            return

        if not self._is_ascii(api_key) or not self._is_ascii(api_secret):
            self._show_input_error(tr("panel.error.ascii_key"))
            return

        params = {
            "api_key": api_key,
            "api_secret": api_secret,
            "testnet": self.testnet,
        }

        if requires_passphrase(self.exchange_type):
            passphrase = self.passphrase_input.text().strip()
            if not passphrase:
                self._show_input_error(tr("panel.error.required_passphrase"))
                return
            if not self._is_ascii(passphrase):
                self._show_input_error(tr("panel.error.ascii_passphrase"))
                return
            params["api_passphrase"] = passphrase
        else:
            passphrase = self.passphrase_input.text().strip()
            if passphrase:
                if not self._is_ascii(passphrase):
                    self._show_input_error(tr("panel.error.ascii_passphrase"))
                    return
                params["api_passphrase"] = passphrase

        self.connect_clicked.emit(self.exchange_name, params)

    def update_status(self, status, force=False):
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

        if not force and snapshot == self._last_status_snapshot:
            return

        prev_connected = self.is_connected
        self.is_connected = snapshot["connected"]

        if self.is_connected:
            mode = tr("mode.demo") if snapshot["testnet"] else tr("mode.real")
            self.status_label.setText(tr("status.connected_mode", mode=mode))
            self.status_label.setStyleSheet(self._status_style("success"))
            self.balance_label.setText(tr("label.balance", value=f"{snapshot['balance']:,.2f}"))
            self.positions_label.setText(tr("label.positions", value=snapshot["positions_count"]))
            self._set_pnl_display(snapshot["pnl"], snapshot["positions_count"])
        else:
            status_text = snapshot["status_text"].strip() or tr("status.disconnected")
            lower_text = status_text.lower()

            if snapshot["loading"]:
                status_text = tr("status.loading")
                color_key = "accent"
            elif (
                "ошибка" in lower_text
                or "error" in lower_text
                or "не реализовано" in lower_text
                or "not implemented" in lower_text
            ):
                color_key = "danger"
            else:
                color_key = "text_muted"

            self.status_label.setText(status_text)
            self.status_label.setStyleSheet(self._status_style(color_key))
            self.balance_label.setText(tr("label.balance_empty"))
            self.positions_label.setText(tr("label.positions_empty"))
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
