from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.data.settings import SettingsManager
from core.exchange import ExchangeManager, create_exchange
from core.exchange.catalog import get_exchange_meta, normalize_exchange_code
from core.i18n import get_language_manager, tr
from core.utils.logger import get_logger
from ui.styles import get_theme_manager, theme_color
from ui.styles.dark_theme import get_dark_theme_stylesheet
from ui.tabs.exchanges_tab import ExchangesTab
from ui.tabs.spread_sniping_tab import SpreadSnipingTab
from ui.utils import ButtonSpamGuard
from ui.widgets.brand_header import NeonLogoWidget
from ui.widgets.status_bar import NetworkStatusBar

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.language_manager = get_language_manager()
        self.theme_manager = get_theme_manager()
        self.settings_manager = SettingsManager()
        self._button_spam_guard = ButtonSpamGuard(cooldown_ms=220, parent=self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._button_spam_guard)

        self._load_ui_preferences()

        self.setWindowTitle(tr("app.title"))
        self.resize(1200, 700)

        self.exchange_manager = ExchangeManager()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._create_top_controls(layout)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.exchanges_tab = ExchangesTab(self.exchange_manager)
        self.exchanges_tab.exchange_added.connect(self._on_exchange_added)
        self.exchanges_tab.exchange_removed.connect(self.exchange_manager.remove_exchange)
        self.tabs.addTab(self.exchanges_tab, tr("tab.exchanges"))

        self.spread_sniping_tab = SpreadSnipingTab(self.exchange_manager)
        self.tabs.addTab(self.spread_sniping_tab, tr("tab.spread_sniping"))

        self.status_bar = NetworkStatusBar()
        layout.addWidget(self.status_bar)

        self.exchange_manager.status_updated.connect(self._on_status_updated)
        self.language_manager.language_changed.connect(self._on_language_changed)
        self.theme_manager.theme_changed.connect(self._on_theme_changed)

        self._apply_theme()
        self._retranslate_ui()

    def _create_top_controls(self, parent_layout):
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        self.left_slot = QWidget()
        top_row.addWidget(self.left_slot, 1)

        self.brand_header = NeonLogoWidget()
        self.brand_header.setLogoSize(58)
        self.brand_header.setLineY(43)
        self.brand_header.setShowLines(True)
        top_row.addWidget(self.brand_header, 0, Qt.AlignmentFlag.AlignCenter)

        self.right_slot = QWidget()
        self.top_controls = QHBoxLayout(self.right_slot)
        self.top_controls.setContentsMargins(0, 0, 0, 0)
        self.top_controls.setSpacing(8)

        self.language_code_label = QLabel()
        self.language_code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.language_code_label.setMinimumWidth(28)
        self.top_controls.addWidget(self.language_code_label)

        self.language_menu = QMenu(self)
        self.language_btn = QToolButton()
        self.language_btn.setText("\U0001F310")
        self.language_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.language_btn.setMenu(self.language_menu)
        self.language_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.language_btn.setFixedSize(38, 32)
        self.top_controls.addWidget(self.language_btn)

        self.settings_menu = QMenu(self)
        self.settings_btn = QToolButton()
        self.settings_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.settings_btn.setMenu(self.settings_menu)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setMinimumWidth(130)
        self.settings_btn.setFixedHeight(32)
        self.top_controls.addWidget(self.settings_btn)

        top_row.addWidget(self.right_slot, 1)
        parent_layout.addLayout(top_row)

        self._build_language_menu()
        self._build_settings_menu()
        self._sync_header_side_widths()

    def _sync_header_side_widths(self):
        if not hasattr(self, "left_slot") or not hasattr(self, "right_slot"):
            return
        self.right_slot.adjustSize()
        width = self.right_slot.sizeHint().width()
        self.left_slot.setMinimumWidth(width)

    def _load_ui_preferences(self):
        saved_language = self.settings_manager.load_ui_language()
        saved_theme = self.settings_manager.load_ui_theme()
        self.language_manager.set_language(saved_language)
        self.theme_manager.set_theme(saved_theme)

    def _build_language_menu(self):
        self.language_menu.clear()
        current = self.language_manager.language
        for code in ("ru", "en"):
            action = self.language_menu.addAction(tr(f"language.{code}"))
            action.setCheckable(True)
            action.setChecked(code == current)
            action.triggered.connect(lambda _checked=False, lang=code: self._set_language(lang))

    def _build_settings_menu(self):
        self.settings_menu.clear()
        self.themes_submenu = self.settings_menu.addMenu(tr("settings.themes_item"))
        current_theme = self.theme_manager.theme_name
        for code in self.theme_manager.available_themes():
            action = self.themes_submenu.addAction(tr(f"theme.{code}"))
            action.setCheckable(True)
            action.setChecked(code == current_theme)
            action.triggered.connect(lambda _checked=False, theme_code=code: self._set_theme(theme_code))

    def _set_language(self, language_code):
        self.language_manager.set_language(language_code)
        self.settings_manager.save_ui_language(self.language_manager.language)

    def _set_theme(self, theme_code):
        self.theme_manager.set_theme(theme_code)
        self.settings_manager.save_ui_theme(self.theme_manager.theme_name)

    def _on_language_changed(self, _language):
        self._retranslate_ui()

    def _on_theme_changed(self, _theme_name):
        self._apply_theme()
        self._build_settings_menu()

    def _apply_theme(self):
        self.setStyleSheet(get_dark_theme_stylesheet())

        self.language_btn.setStyleSheet(
            f"""
            QToolButton {{
                background-color: {theme_color('surface')};
                color: {theme_color('text_primary')};
                border: 1px solid {theme_color('border')};
                border-radius: 10px;
                font-size: 17px;
                font-weight: 600;
                padding: 2px 3px;
            }}
            QToolButton:hover {{
                background-color: {theme_color('surface_alt')};
            }}
        """
        )

        self.language_code_label.setStyleSheet(
            f"""
            QLabel {{
                color: {theme_color('text_primary')};
                font-size: 12px;
                font-weight: 700;
                padding: 0 1px;
            }}
        """
        )

        self.settings_btn.setStyleSheet(
            f"""
            QToolButton {{
                background-color: {theme_color('surface')};
                color: {theme_color('text_primary')};
                border: 1px solid {theme_color('border')};
                border-radius: 10px;
                font-size: 12px;
                font-weight: 600;
                padding: 3px 14px;
            }}
            QToolButton:hover {{
                background-color: {theme_color('surface_alt')};
            }}
        """
        )

        self.language_btn.setFixedSize(46, 34)
        self.settings_btn.setFixedHeight(34)

        if hasattr(self, "brand_header"):
            self.brand_header.apply_theme()

        if hasattr(self, "exchanges_tab"):
            self.exchanges_tab.apply_theme()
        if hasattr(self, "spread_sniping_tab"):
            self.spread_sniping_tab.apply_theme()
        if hasattr(self, "status_bar"):
            self.status_bar.apply_theme()

    def _retranslate_ui(self):
        self.setWindowTitle(tr("app.title"))
        if hasattr(self, "tabs"):
            self.tabs.setTabText(0, tr("tab.exchanges"))
            self.tabs.setTabText(1, tr("tab.spread_sniping"))

        if hasattr(self, "language_btn"):
            self.language_btn.setToolTip(tr("settings.language_tooltip"))
            self.settings_btn.setText(tr("settings.button"))
            self.language_code_label.setText(self.language_manager.language.upper())
            self._build_language_menu()
            self._build_settings_menu()
            self._sync_header_side_widths()

        if hasattr(self, "exchanges_tab"):
            self.exchanges_tab.retranslate_ui()
        if hasattr(self, "spread_sniping_tab"):
            self.spread_sniping_tab.retranslate_ui()
        if hasattr(self, "status_bar"):
            self.status_bar.retranslate_ui()

    def _on_exchange_added(self, name, exchange_type, params):
        type_code = normalize_exchange_code(exchange_type)
        is_existing = self.exchange_manager.get_exchange(name) is not None
        if is_existing and self.exchange_manager.is_exchange_loading(name):
            return

        try:
            exchange = create_exchange(name, type_code, params)
        except Exception as exc:
            detail = str(exc).strip() or tr("main.error.create_connection")
            logger.exception("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ РїРѕРґРєР»СЋС‡РµРЅРёРµ %s (%s): %s", name, type_code, exc)
            self.status_bar.show_error(
                tr("main.error.create_connector", exchange=type_code.upper(), name=name)
            )
            self.exchanges_tab.set_new_panel_error(detail)
            return

        is_existing = self.exchange_manager.get_exchange(name) is not None

        # РќРѕРІСѓСЋ Р±РёСЂР¶Сѓ РґРѕР±Р°РІР»СЏРµРј РІ РјРµРЅРµРґР¶РµСЂ С‚РѕР»СЊРєРѕ РїРѕСЃР»Рµ СѓСЃРїРµС€РЅРѕРіРѕ РїРѕРґРєР»СЋС‡РµРЅРёСЏ.
        if not is_existing and params.get("api_key") and params.get("api_secret"):
            try:
                connected = bool(exchange.connect())
            except Exception as exc:
                detail = str(exc).strip() or tr("main.error.connect_failed_short")
                logger.exception("РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґРєР»СЋС‡РёС‚СЊ РЅРѕРІСѓСЋ Р±РёСЂР¶Сѓ %s (%s): %s", name, type_code, exc)
                self.status_bar.show_error(
                    tr("main.error.connect", exchange=type_code.upper(), name=name)
                )
                self.exchanges_tab.set_new_panel_error(detail)
                return

            if not connected:
                detail = str(getattr(exchange, "last_error", "") or "").strip()
                if not detail:
                    detail = tr("main.error.connect_failed_short")
                self.status_bar.show_error(
                    tr("main.error.connect_failed", exchange=type_code.upper(), name=name)
                )
                self.exchanges_tab.set_new_panel_error(detail)
                return

        if is_existing:
            if not self.exchange_manager.update_exchange(name, exchange):
                self.status_bar.show_error(
                    tr("main.error.update_settings", exchange=type_code.upper(), name=name)
                )
                return

            if params.get("api_key") and params.get("api_secret"):
                self.exchange_manager.connect_exchange_async(name)
        else:
            if not self.exchange_manager.add_exchange(exchange):
                self.status_bar.show_error(
                    tr("main.error.add_exchange", exchange=type_code.upper(), name=name)
                )
                self.exchanges_tab.set_new_panel_error(tr("main.error.add_exchange_short"))

    def _on_status_updated(self, statuses):
        for name, status in statuses.items():
            if status.get("connected", False) or status.get("loading", False):
                continue

            status_text = status.get("status_text", "")
            lower_text = status_text.lower()
            if (
                "РѕС€РёР±РєР°" in lower_text
                or "error" in lower_text
                or "РЅРµ СЂРµР°Р»РёР·РѕРІР°РЅРѕ" in lower_text
                or "not implemented" in lower_text
            ):
                exchange = self.exchange_manager.get_exchange(name)
                type_code = getattr(exchange, "exchange_type", None)
                meta = get_exchange_meta(type_code)
                self.status_bar.show_error(f"{meta['short']} {name}: {status_text}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_header_side_widths()
