from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.exchange.catalog import get_exchange_meta, normalize_exchange_code, requires_passphrase
from core.i18n import tr
from core.utils.logger import get_logger
from ui.styles import theme_color
from ui.utils import apply_stable_numeric_label, numeric_monospace_font
from ui.widgets.exchange_badge import build_exchange_pixmap

logger = get_logger(__name__)


class StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._fill = QColor("#ef4444")
        self._border = QColor("#dc2626")
        self.setFixedSize(10, 10)

    def set_colors(self, fill, border):
        self._fill = QColor(fill)
        self._border = QColor(border)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(self._border, 1.0))
        p.setBrush(self._fill)
        p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class ExchangePanel(QFrame):
    connect_clicked = Signal(str, dict)
    disconnect_clicked = Signal(str)
    close_positions_clicked = Signal(str)
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
        self.setObjectName("exchangePanel")
        self.setFrameStyle(QFrame.Shape.NoFrame)
        soft_border = self._rgba(theme_color("border"), 0.80)
        soft_field_border = self._rgba(theme_color("border"), 0.54)
        soft_hover_border = self._rgba(theme_color("accent"), 0.70)
        panel_top = self._rgba(theme_color("surface_alt"), 0.96)
        panel_bottom = self._rgba(theme_color("window_bg"), 0.98)
        self.setStyleSheet(
            f"""
            QFrame#exchangePanel {{
                border: 2px solid {soft_border};
                border-radius: 16px;
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {panel_top},
                    stop: 1 {panel_bottom}
                );
                margin: 0px;
                padding: 7px;
            }}
            QGroupBox {{
                border: none;
                margin-top: 0px;
                padding-top: 0px;
                color: {theme_color('text_muted')};
                font-size: 11px;
                font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 2px;
                padding: 0 4px;
            }}
            QLineEdit {{
                background-color: {theme_color('surface')};
                color: {theme_color('text_primary')};
                border: 1px solid {soft_field_border};
                border-radius: 10px;
                padding: 5px 8px;
            }}
            QLineEdit:hover {{
                border-color: {soft_hover_border};
            }}
            QLineEdit:focus {{
                border-color: {soft_hover_border};
            }}
        """
        )

        if not hasattr(self, "status_label"):
            return

        self.balance_label.setStyleSheet(self._metric_capsule_style("success", bold=True))
        self.positions_label.setStyleSheet(self._metric_capsule_style("warning"))
        self.testnet_check.setStyleSheet(f"color: {theme_color('warning')};")
        self._apply_status_container_style()

        self.name_label.setStyleSheet(
            f"""
            color: {theme_color('text_primary')};
            background-color: {self._rgba(theme_color('window_bg'), 0.70)};
            border: 1px solid {self._rgba(theme_color('border'), 0.52)};
            border-radius: 10px;
            padding: 3px 9px;
            """
        )

        self.connect_btn.setStyleSheet(self._soft_button_style("primary"))
        self.disconnect_btn.setStyleSheet(self._soft_button_style("danger"))
        self.close_positions_btn.setStyleSheet(self._soft_button_style("warning"))
        self.edit_btn.setStyleSheet(self._soft_button_style("warning"))
        self.remove_btn.setStyleSheet(self._soft_button_style("secondary"))
        self.cancel_btn.setStyleSheet(self._soft_button_style("secondary"))

        if self._last_status_snapshot is not None:
            self.update_status(dict(self._last_status_snapshot), force=True)
        else:
            self._update_ui_state()

    @staticmethod
    def _status_style(color_key, font_px=10, bold=False):
        weight = "font-weight: 700;" if bold else ""
        return f"color: {theme_color(color_key)}; font-size: {int(font_px)}px; {weight}"

    @staticmethod
    def _metric_style(color_key, bold=False):
        weight = "font-weight: bold;" if bold else ""
        return f"color: {theme_color(color_key)}; font-size: 11px; {weight}"

    @staticmethod
    def _metric_capsule_style(color_key, bold=False):
        weight = "font-weight: 700;" if bold else "font-weight: 600;"
        return (
            f"color: {theme_color(color_key)}; font-size: 11px; {weight} "
            f"background-color: {ExchangePanel._rgba(theme_color('window_bg'), 0.70)}; "
            f"border: 1px solid {ExchangePanel._rgba(theme_color('border'), 0.46)}; border-radius: 10px; "
            "padding: 4px 10px;"
        )

    @staticmethod
    def _rgba(hex_color, alpha):
        color = str(hex_color or "").strip()
        if color.startswith("#") and len(color) == 7:
            try:
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                a = max(0.0, min(1.0, float(alpha)))
                return f"rgba({r}, {g}, {b}, {a:.3f})"
            except ValueError:
                return color
        return color

    def _soft_button_style(self, role):
        roles = {
            "primary": (
                self._rgba(theme_color("accent"), 0.15),
                self._rgba(theme_color("accent"), 0.54),
                theme_color("text_primary"),
                self._rgba(theme_color("accent"), 0.22),
            ),
            "danger": (
                self._rgba(theme_color("danger"), 0.16),
                self._rgba(theme_color("danger"), 0.54),
                theme_color("text_primary"),
                self._rgba(theme_color("danger"), 0.22),
            ),
            "warning": (
                self._rgba(theme_color("warning"), 0.16),
                self._rgba(theme_color("warning"), 0.58),
                theme_color("text_primary"),
                self._rgba(theme_color("warning"), 0.24),
            ),
            "secondary": (
                self._rgba(theme_color("surface"), 0.66),
                self._rgba(theme_color("border"), 0.46),
                theme_color("text_muted"),
                self._rgba(theme_color("surface_alt"), 0.88),
            ),
        }
        bg, border, text, hover = roles.get(role, roles["secondary"])
        pressed = self._rgba(theme_color("surface_alt"), 0.95)
        return (
            f"QPushButton {{ background-color: {bg}; color: {text}; border: 1px solid {border}; "
            "border-radius: 10px; padding: 4px 10px; font-weight: 600; }"
            f" QPushButton:hover {{ background-color: {hover}; border-color: {border}; }}"
            f" QPushButton:pressed {{ background-color: {pressed}; border-color: {border}; }}"
            f" QPushButton:disabled {{ color: {theme_color('text_muted')}; "
            f"background-color: {self._rgba(theme_color('surface'), 0.55)}; "
            f"border-color: {self._rgba(theme_color('border'), 0.30)}; }}"
        )

    @staticmethod
    def _indicator_colors(color_key):
        saturated = {
            "success": ("#22c55e", "#16a34a"),
            "warning": ("#f59e0b", "#d97706"),
            "danger": ("#ef4444", "#dc2626"),
            "text_muted": ("#94a3b8", "#64748b"),
        }
        return saturated.get(
            color_key,
            (theme_color(color_key), theme_color("border")),
        )

    def _apply_status_container_style(self):
        self.status_widget.setStyleSheet(
            f"""
            QWidget#statusWidget {{
                background-color: {self._rgba(theme_color('window_bg'), 0.72)};
                border: 1px solid {self._rgba(theme_color('border'), 0.56)};
                border-radius: 12px;
            }}
        """
        )

    def _set_status_view(self, text, text_color_key, indicator_color_key, emphasize=False):
        font_px = 12 if emphasize else 10
        status_layout = self.status_widget.layout()
        if status_layout is not None:
            v_pad = 1 if emphasize else 3
            status_layout.setContentsMargins(8, v_pad, 8, v_pad)
            status_layout.setSpacing(6 if emphasize else 6)
        self.status_widget.setVisible(True)
        if emphasize:
            self.status_widget.setMinimumWidth(420)
            self.status_widget.setMinimumHeight(24)
            self.status_widget.setMaximumHeight(28)
            self.status_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.status_label.setWordWrap(False)
        else:
            self.status_widget.setMinimumWidth(0)
            self.status_widget.setMinimumHeight(30)
            self.status_widget.setMaximumHeight(30)
            self.status_widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self.status_label.setWordWrap(False)
        self.status_label.setText(text)
        self.status_label.setStyleSheet(self._status_style(text_color_key, font_px=font_px, bold=emphasize))
        self.status_label.setVisible(True)
        fill, border = self._indicator_colors(indicator_color_key)
        self.status_indicator.set_colors(fill, border)
        self.status_indicator.setVisible(True)
        self._apply_metric_width_stability()

    def show_status_message(
        self,
        text,
        text_color_key="text_muted",
        indicator_color_key=None,
        emphasize=False,
    ):
        indicator_key = indicator_color_key or text_color_key
        self._set_status_view(text, text_color_key, indicator_key, emphasize=emphasize)

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.icon_label = QLabel()
        self.icon_label.setPixmap(build_exchange_pixmap(self.exchange_type, size=30))
        self.icon_label.setFixedSize(30, 30)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_label = QLabel(self.exchange_name)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setMinimumWidth(80)

        self.status_label = QLabel(tr("status.disconnected"))
        self.status_label.setStyleSheet(self._status_style("text_muted"))
        self.status_label.setWordWrap(False)

        self.status_indicator = StatusDot()

        self.status_widget = QWidget()
        self.status_widget.setObjectName("statusWidget")
        self.status_widget.setMinimumWidth(0)
        self.status_widget.setMinimumHeight(30)
        self.status_widget.setMaximumHeight(30)
        self.status_widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        status_layout = QHBoxLayout(self.status_widget)
        status_layout.setContentsMargins(10, 4, 10, 4)
        status_layout.setSpacing(6)
        status_layout.addWidget(self.status_indicator)
        status_layout.addWidget(self.status_label)
        self._apply_status_container_style()

        header.addWidget(self.icon_label)
        header.addWidget(self.name_label)
        header.addWidget(self.status_widget)
        header.addStretch()
        layout.addLayout(header)

        self.stats_widget = QWidget()
        stats_layout = QHBoxLayout(self.stats_widget)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(8)
        self.balance_label = QLabel(tr("label.balance_empty"))
        self.balance_label.setStyleSheet(self._metric_capsule_style("success", bold=True))
        self.balance_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.balance_label.setMinimumHeight(28)
        self.positions_label = QLabel(tr("label.positions_empty"))
        self.positions_label.setTextFormat(Qt.TextFormat.RichText)
        self.positions_label.setStyleSheet(self._metric_capsule_style("warning"))
        self.positions_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.positions_label.setMinimumHeight(28)
        self.pnl_label = QLabel(tr("label.pnl", value="0.00"))
        self.pnl_label.setStyleSheet(self._metric_capsule_style("text_muted", bold=True))
        self.pnl_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.pnl_label.setMinimumHeight(28)
        stats_layout.addWidget(self.balance_label)
        stats_layout.addWidget(self.positions_label)
        stats_layout.addWidget(self.pnl_label)
        stats_layout.addStretch()
        layout.addWidget(self.stats_widget)

        if self.is_new:
            self.stats_widget.setVisible(False)
            self.name_label.setVisible(False)
            self.icon_label.setFixedSize(52, 52)
            self.icon_label.setPixmap(build_exchange_pixmap(self.exchange_type, size=52))
            self.status_label.setText("")
            self.status_label.setVisible(False)
            self.status_indicator.setVisible(False)
            self.status_widget.setVisible(False)

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
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(6)

        self.connect_btn = QPushButton(tr("action.connect"))
        self.connect_btn.setMinimumWidth(100)
        self.connect_btn.setStyleSheet(self._soft_button_style("primary"))
        self.connect_btn.clicked.connect(self._on_connect)

        self.disconnect_btn = QPushButton(tr("action.disconnect"))
        self.disconnect_btn.setMinimumWidth(100)
        self.disconnect_btn.setStyleSheet(self._soft_button_style("danger"))
        self.disconnect_btn.clicked.connect(self._on_disconnect_clicked)

        self.close_positions_btn = QPushButton(f"\u26A0 {tr('action.close_positions')}")
        self.close_positions_btn.setMinimumWidth(130)
        self.close_positions_btn.setStyleSheet(self._soft_button_style("warning"))
        self.close_positions_btn.clicked.connect(self._on_close_positions_clicked)

        self.edit_btn = QPushButton(tr("action.edit"))
        self.edit_btn.setMinimumWidth(100)
        self.edit_btn.setStyleSheet(self._soft_button_style("warning"))
        self.edit_btn.clicked.connect(self._on_edit_clicked)

        self.remove_btn = QPushButton(tr("action.remove"))
        self.remove_btn.setMinimumWidth(100)
        self.remove_btn.setStyleSheet(self._soft_button_style("secondary"))
        self.remove_btn.clicked.connect(self._on_remove_clicked)

        self.cancel_btn = QPushButton(tr("action.cancel"))
        self.cancel_btn.setMinimumWidth(100)
        self.cancel_btn.setStyleSheet(self._soft_button_style("secondary"))
        self.cancel_btn.clicked.connect(self._on_cancel)

        button_layout.addWidget(self.connect_btn)
        button_layout.addWidget(self.disconnect_btn)
        button_layout.addWidget(self.close_positions_btn)
        button_layout.addWidget(self.edit_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.remove_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.setLayout(layout)
        self._update_passphrase_hint()
        self._apply_metric_width_stability()
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
        self.connect_btn.setText(tr("action.connect"))
        self.testnet_check.setText(tr("panel.testnet"))
        self.disconnect_btn.setText(tr("action.disconnect"))
        self.close_positions_btn.setText(f"\u26A0 {tr('action.close_positions')}")
        self.edit_btn.setText(tr("action.edit"))
        self.remove_btn.setText(tr("action.remove"))
        self.cancel_btn.setText(tr("action.cancel"))
        self._update_passphrase_hint()
        self._apply_metric_width_stability()

        if self.is_new:
            self.name_label.setText(tr("exchanges.new_connection_name"))

        if self._last_status_snapshot is not None:
            self.update_status(dict(self._last_status_snapshot), force=True)
        else:
            self._update_ui_state()

    def set_edit_mode(self, edit_mode):
        self.edit_mode = edit_mode
        self._update_ui_state()

    def _apply_metric_width_stability(self):
        if not hasattr(self, "balance_label"):
            return

        self.balance_label.setFont(numeric_monospace_font(self.balance_label.font()))
        self.pnl_label.setFont(numeric_monospace_font(self.pnl_label.font()))

        balance_samples = [
            tr("label.balance", value="999,999,999.99"),
            tr("label.balance_empty"),
        ]
        pnl_samples = [
            tr("label.pnl_positive", value="+999,999,999.99"),
            tr("label.pnl", value="-999,999,999.99"),
        ]
        positions_samples = [
            tr("label.positions", value="999"),
            tr(
                "label.positions",
                value=f"{tr('label.long')} 999 | {tr('label.short')} 999",
            ),
            tr("label.positions_empty"),
        ]

        apply_stable_numeric_label(self.balance_label, balance_samples, extra_padding=22)
        apply_stable_numeric_label(self.positions_label, positions_samples, extra_padding=22)
        apply_stable_numeric_label(self.pnl_label, pnl_samples, extra_padding=22)

    def _update_ui_state(self):
        if self.is_connected:
            mode = tr("mode.demo") if self.testnet else tr("mode.real")
            self._set_status_view(tr("status.connected_mode", mode=mode), "success", "success")
            self.connect_btn.setVisible(False)
            self.disconnect_btn.setVisible(True)
            self.close_positions_btn.setVisible(True)
            self.edit_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
            self.api_group.setVisible(False)
        else:
            if self.is_new:
                self.status_label.setText("")
                self.status_label.setVisible(False)
                self.status_indicator.setVisible(False)
                self.status_widget.setVisible(False)
            else:
                self._set_status_view(tr("status.disconnected"), "text_muted", "danger")
            self.balance_label.setText(tr("label.balance_empty"))
            self.positions_label.setText(tr("label.positions_empty"))
            self._set_pnl_display(0.0, 0)

            if self.edit_mode:
                self.connect_btn.setText(tr("action.add") if self.is_new else tr("action.connect"))
                self.connect_btn.setVisible(True)
                self.disconnect_btn.setVisible(False)
                self.close_positions_btn.setVisible(False)
                self.edit_btn.setVisible(False)
                self.cancel_btn.setVisible(True)
                self.api_group.setVisible(True)
            else:
                self.connect_btn.setText(tr("action.connect"))
                self.connect_btn.setVisible(True)
                self.disconnect_btn.setVisible(False)
                self.close_positions_btn.setVisible(False)
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
        self.pnl_label.setStyleSheet(self._metric_capsule_style(color_key, bold=True))

    def _set_positions_display(self, total_count, long_count=0, short_count=0):
        total_count = int(total_count or 0)
        long_count = max(0, int(long_count or 0))
        short_count = max(0, int(short_count or 0))

        if total_count <= 0:
            self.positions_label.setText(tr("label.positions", value="0"))
            self.positions_label.setStyleSheet(self._metric_capsule_style("warning"))
            return

        if long_count <= 0 and short_count <= 0:
            self.positions_label.setText(tr("label.positions", value=str(total_count)))
            self.positions_label.setStyleSheet(self._metric_capsule_style("warning"))
            return

        parts = []
        if long_count > 0:
            parts.append(
                f"<span style='color:{theme_color('success')}; font-weight:700;'>"
                f"{tr('label.long')} {long_count}</span>"
            )
        if long_count > 0 and short_count > 0:
            parts.append(
                f"<span style='color:{theme_color('text_muted')}; font-weight:700;'>"
                f" &nbsp;|&nbsp; </span>"
            )
        if short_count > 0:
            parts.append(
                f"<span style='color:{theme_color('danger')}; font-weight:700;'>"
                f"{tr('label.short')} {short_count}</span>"
            )

        self.positions_label.setText(tr("label.positions", value="".join(parts)))
        self.positions_label.setStyleSheet(self._metric_capsule_style("text_primary", bold=True))

    def _on_cancel(self):
        logger.info(
            "[TRACE] exchange_panel.cancel_click | exchange=%s | is_new=%s",
            self.exchange_name,
            bool(self.is_new),
        )
        if self.is_new:
            self.cancel_clicked.emit()
        else:
            self.set_edit_mode(False)

    def _on_disconnect_clicked(self):
        logger.info("[TRACE] exchange_panel.disconnect_click | exchange=%s", self.exchange_name)
        self.disconnect_clicked.emit(self.exchange_name)

    def _on_close_positions_clicked(self):
        logger.info("[TRACE] exchange_panel.close_positions_click | exchange=%s", self.exchange_name)
        self.close_positions_clicked.emit(self.exchange_name)

    def _on_edit_clicked(self):
        logger.info("[TRACE] exchange_panel.edit_click | exchange=%s", self.exchange_name)
        self.set_edit_mode(True)

    def _on_remove_clicked(self):
        logger.info("[TRACE] exchange_panel.remove_click | exchange=%s", self.exchange_name)
        self.remove_clicked.emit(self.exchange_name)

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
        self.show_status_message(message, "danger", "danger", emphasize=True)

    def _on_connect(self):
        logger.info(
            "[TRACE] exchange_panel.connect_click | exchange=%s | is_new=%s | edit_mode=%s",
            self.exchange_name,
            bool(self.is_new),
            bool(self.edit_mode),
        )
        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()

        if not api_key or not api_secret:
            logger.info(
                "[TRACE] exchange_panel.connect_rejected | exchange=%s | reason=required_keys",
                self.exchange_name,
            )
            if not self.edit_mode and not self.is_new:
                self.set_edit_mode(True)
            self._show_input_error(tr("panel.error.required_keys"))
            return

        if not self._is_ascii(api_key) or not self._is_ascii(api_secret):
            logger.info(
                "[TRACE] exchange_panel.connect_rejected | exchange=%s | reason=non_ascii_key",
                self.exchange_name,
            )
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
                logger.info(
                    "[TRACE] exchange_panel.connect_rejected | exchange=%s | reason=required_passphrase",
                    self.exchange_name,
                )
                self._show_input_error(tr("panel.error.required_passphrase"))
                return
            if not self._is_ascii(passphrase):
                logger.info(
                    "[TRACE] exchange_panel.connect_rejected | exchange=%s | reason=non_ascii_passphrase",
                    self.exchange_name,
                )
                self._show_input_error(tr("panel.error.ascii_passphrase"))
                return
            params["api_passphrase"] = passphrase
        else:
            passphrase = self.passphrase_input.text().strip()
            if passphrase:
                if not self._is_ascii(passphrase):
                    logger.info(
                        "[TRACE] exchange_panel.connect_rejected | exchange=%s | reason=non_ascii_passphrase_optional",
                        self.exchange_name,
                    )
                    self._show_input_error(tr("panel.error.ascii_passphrase"))
                    return
                params["api_passphrase"] = passphrase

        logger.info(
            "[TRACE] exchange_panel.connect_submit | exchange=%s | testnet=%s | passphrase=%s",
            self.exchange_name,
            bool(self.testnet),
            bool(params.get("api_passphrase")),
        )
        self.connect_btn.setEnabled(False)
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
            "long_positions": int(status.get("long_positions", 0) or 0),
            "short_positions": int(status.get("short_positions", 0) or 0),
            "pnl": float(status.get("pnl", 0) or 0),
            "status_text": str(status.get("status_text", "") or ""),
        }

        if not force and snapshot == self._last_status_snapshot:
            return

        prev_connected = self.is_connected
        self.is_connected = snapshot["connected"]
        self.testnet = snapshot["testnet"]
        if self.is_connected:
            self.edit_mode = False
        elif prev_connected:
            self.edit_mode = False

        if self.is_connected:
            status_text = snapshot["status_text"].strip()
            lower_text = status_text.lower()
            if (
                "\u043e\u0448\u0438\u0431\u043a\u0430" in lower_text
                or "error" in lower_text
                or "\u043d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c" in lower_text
                or "timeout" in lower_text
                or "timed out" in lower_text
            ):
                self._set_status_view(status_text, "danger", "danger")
            else:
                mode = tr("mode.demo") if snapshot["testnet"] else tr("mode.real")
                self._set_status_view(tr("status.connected_mode", mode=mode), "success", "success")
            self.balance_label.setText(tr("label.balance", value=f"{snapshot['balance']:,.2f}"))
            self._set_positions_display(
                snapshot["positions_count"],
                snapshot["long_positions"],
                snapshot["short_positions"],
            )
            self._set_pnl_display(snapshot["pnl"], snapshot["positions_count"])
        else:
            status_text = snapshot["status_text"].strip() or tr("status.disconnected")
            lower_text = status_text.lower()

            if snapshot["loading"]:
                status_text = tr("status.loading")
                text_color_key = "warning"
                indicator_key = "warning"
            elif (
                "\u043e\u0448\u0438\u0431\u043a\u0430" in lower_text
                or "error" in lower_text
                or "\u043d\u0435 \u0440\u0435\u0430\u043b\u0438\u0437\u043e\u0432\u0430\u043d\u043e" in lower_text
                or "not implemented" in lower_text
            ):
                text_color_key = "danger"
                indicator_key = "danger"
            else:
                text_color_key = "text_muted"
                indicator_key = "danger"

            self._set_status_view(status_text, text_color_key, indicator_key)
            self.balance_label.setText(tr("label.balance_empty"))
            self.positions_label.setText(tr("label.positions_empty"))
            self._set_pnl_display(0.0, 0)

        if prev_connected != self.is_connected:
            self._update_ui_state()

        is_loading = snapshot["loading"]
        self.connect_btn.setEnabled(not is_loading)
        self.edit_btn.setEnabled(not is_loading)
        self.remove_btn.setEnabled(not is_loading)
        if is_loading:
            self.api_group.setEnabled(False)
        else:
            self.api_group.setEnabled(True)

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

