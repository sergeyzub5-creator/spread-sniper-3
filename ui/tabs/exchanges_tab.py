from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.exchange.catalog import get_exchange_meta
from core.i18n import tr
from core.utils.logger import get_logger
from features.exchanges.controllers import ExchangesClosePositionsMixin, ExchangesPanelsMixin
from ui.styles import theme_color


class ExchangesTab(ExchangesPanelsMixin, ExchangesClosePositionsMixin, QWidget):
    exchange_added = Signal(str, str, dict)
    exchange_removed = Signal(str)

    def __init__(self, exchange_manager, parent=None):
        super().__init__(parent)
        self._trace_logger = get_logger("ui.exchanges.trace")
        self.exchange_manager = exchange_manager
        self.exchange_panels = {}
        self.fast_trade_mode = False

        self.new_panel = None
        self.new_panel_exchange_type = None
        self.new_panel_exchange_name = None
        self.new_exchange_dialog = None
        self.close_positions_worker = None
        self.single_close_worker = None
        self.single_close_name = None

        self._init_ui()

        self.exchange_manager.exchange_added.connect(self._on_exchange_added)
        self.exchange_manager.exchange_removed.connect(self._on_exchange_removed)
        self.exchange_manager.status_updated.connect(self._update_all_status)

    def set_fast_trade_mode(self, enabled):
        self.fast_trade_mode = bool(enabled)

    def _init_ui(self):
        self.setObjectName("exchangesTabRoot")
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(0)

        self.main_frame = QFrame()
        self.main_frame.setObjectName("exchangesMainFrame")
        root_layout.addWidget(self.main_frame)

        layout = QVBoxLayout(self.main_frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.add_btn = QPushButton(tr("exchanges.add_exchange"))
        self.add_btn.setMinimumWidth(140)
        self.add_btn.setStyleSheet(self._soft_button_style("primary", bold=True))
        self.add_btn.clicked.connect(self._on_add_clicked)
        controls.addWidget(self.add_btn)
        controls.addStretch()

        connect_buttons = QHBoxLayout()
        connect_buttons.setSpacing(5)

        self.connect_all_btn = QPushButton(tr("exchanges.connect_all"))
        self.connect_all_btn.setMinimumWidth(130)
        self.connect_all_btn.setStyleSheet(self._soft_button_style("success"))
        self.connect_all_btn.clicked.connect(self._on_connect_all_clicked)

        self.disconnect_all_btn = QPushButton(tr("exchanges.disconnect_all"))
        self.disconnect_all_btn.setMinimumWidth(130)
        self.disconnect_all_btn.setStyleSheet(self._soft_button_style("danger"))
        self.disconnect_all_btn.clicked.connect(self._on_disconnect_all_clicked)

        self.close_all_positions_btn = QPushButton(f"\u26A0 {tr('action.close_all_positions')}")
        self.close_all_positions_btn.setMinimumWidth(170)
        self.close_all_positions_btn.setStyleSheet(self._soft_button_style("warning", bold=True))
        self.close_all_positions_btn.clicked.connect(self._on_close_all_positions_clicked)

        connect_buttons.addWidget(self.connect_all_btn)
        connect_buttons.addWidget(self.disconnect_all_btn)
        connect_buttons.addWidget(self.close_all_positions_btn)
        controls.addLayout(connect_buttons)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("exchangesScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._apply_scroll_style()

        self.container = QWidget()
        self.container.setObjectName("exchangesPanelsContainer")
        self.panels_layout = QVBoxLayout(self.container)
        self.panels_layout.setContentsMargins(0, 0, 0, 0)
        self.panels_layout.setSpacing(8)
        self.panels_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.container)

        layout.addLayout(controls)
        layout.addWidget(self.scroll)

        self._load_existing()

    def _apply_scroll_style(self):
        if hasattr(self, "scroll"):
            self.scroll.setStyleSheet(
                """
                QScrollArea#exchangesScroll {
                    border: none;
                    background: transparent;
                }
                QScrollArea#exchangesScroll > QWidget > QWidget {
                    background: transparent;
                }
                """
            )

    def apply_theme(self):
        frame_top = self._rgba(theme_color("surface_alt"), 0.96)
        frame_bottom = self._rgba(theme_color("window_bg"), 0.98)
        frame_border = self._rgba(theme_color("border"), 0.58)
        self.setStyleSheet(
            f"""
            QFrame#exchangesMainFrame {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {frame_top},
                    stop: 1 {frame_bottom}
                );
                border: 1px solid {frame_border};
                border-radius: 12px;
            }}
            QWidget#exchangesPanelsContainer {{
                background: transparent;
                border: none;
            }}
            """
        )
        self.add_btn.setStyleSheet(self._soft_button_style("primary", bold=True))
        self.connect_all_btn.setStyleSheet(self._soft_button_style("success"))
        self.disconnect_all_btn.setStyleSheet(self._soft_button_style("danger"))
        self.close_all_positions_btn.setStyleSheet(self._soft_button_style("warning", bold=True))
        self._apply_scroll_style()

        for panel in self.exchange_panels.values():
            panel.apply_theme()

        if self.new_panel is not None:
            self.new_panel.apply_theme()

        if self.new_exchange_dialog is not None:
            self.new_exchange_dialog.setStyleSheet(
                f"""
                QDialog {{
                    background-color: {theme_color('surface')};
                    color: {theme_color('text_primary')};
                }}
            """
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

    def _soft_button_style(self, role, bold=False):
        roles = {
            "primary": (
                self._rgba(theme_color("accent"), 0.14),
                self._rgba(theme_color("accent"), 0.56),
                theme_color("text_primary"),
                self._rgba(theme_color("accent"), 0.22),
            ),
            "success": (
                self._rgba(theme_color("success"), 0.14),
                self._rgba(theme_color("success"), 0.56),
                theme_color("text_primary"),
                self._rgba(theme_color("success"), 0.22),
            ),
            "danger": (
                self._rgba(theme_color("danger"), 0.14),
                self._rgba(theme_color("danger"), 0.56),
                theme_color("text_primary"),
                self._rgba(theme_color("danger"), 0.22),
            ),
            "warning": (
                self._rgba(theme_color("warning"), 0.14),
                self._rgba(theme_color("warning"), 0.58),
                theme_color("text_primary"),
                self._rgba(theme_color("warning"), 0.24),
            ),
        }
        bg, border, text, hover = roles.get(role, roles["primary"])
        pressed = self._rgba(theme_color("surface_alt"), 0.96)
        weight = "700" if bold else "600"
        return (
            f"QPushButton {{ background-color: {bg}; color: {text}; border: 1px solid {border}; "
            f"border-radius: 11px; padding: 6px 12px; font-weight: {weight}; }}"
            f" QPushButton:hover {{ background-color: {hover}; border-color: {border}; }}"
            f" QPushButton:pressed {{ background-color: {pressed}; border-color: {border}; }}"
            f" QPushButton:disabled {{ color: {theme_color('text_muted')}; "
            f"background-color: {self._rgba(theme_color('surface'), 0.55)}; "
            f"border-color: {self._rgba(theme_color('border'), 0.32)}; }}"
        )

    def retranslate_ui(self):
        self.add_btn.setText(tr("exchanges.add_exchange"))
        self.connect_all_btn.setText(tr("exchanges.connect_all"))
        self.disconnect_all_btn.setText(tr("exchanges.disconnect_all"))
        self.close_all_positions_btn.setText(f"\u26A0 {tr('action.close_all_positions')}")

        for panel in self.exchange_panels.values():
            panel.retranslate_ui()

        if self.new_panel is not None:
            self.new_panel.retranslate_ui()

        if self.new_exchange_dialog is not None:
            meta = get_exchange_meta(self.new_panel_exchange_type)
            self.new_exchange_dialog.setWindowTitle(
                tr("exchanges.new_connection_title", title=meta["title"])
            )

    def _trace(self, event, **fields):
        logger = getattr(self, "_trace_logger", None)
        if logger is None:
            return
        details = " | ".join(
            f"{key}={value}"
            for key, value in fields.items()
            if value is not None and str(value).strip() != ""
        )
        if details:
            logger.info("[TRACE] exchanges.%s | %s", str(event or "event"), details)
        else:
            logger.info("[TRACE] exchanges.%s", str(event or "event"))

    def _on_add_clicked(self):
        self._trace("add_click")
        self._add_new_panel()

    def _on_connect_all_clicked(self):
        self._trace("connect_all_click", panels=len(self.exchange_panels))
        self._connect_all()

    def _on_disconnect_all_clicked(self):
        self._trace("disconnect_all_click", panels=len(self.exchange_panels))
        self._disconnect_all()

    def _on_close_all_positions_clicked(self):
        self._trace("close_all_positions_click", panels=len(self.exchange_panels))
        self._close_all_positions()
