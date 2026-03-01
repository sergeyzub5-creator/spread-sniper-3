from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.data.settings import SettingsManager
from core.exchange import ExchangeManager, create_exchange
from core.exchange.catalog import get_exchange_meta, normalize_exchange_code
from core.i18n import get_language_manager, tr
from core.utils.logger import get_logger
from ui.styles import get_theme_manager
from ui.styles.dark_theme import get_dark_theme_stylesheet
from ui.tabs.exchanges_tab import ExchangesTab
from ui.tabs.spread_sniping_tab import SpreadSnipingTab
from ui.widgets.status_bar import NetworkStatusBar

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.language_manager = get_language_manager()
        self.theme_manager = get_theme_manager()
        self.settings_manager = SettingsManager()

        self._load_ui_preferences()

        self.setWindowTitle(tr("app.title"))
        self.resize(1200, 700)

        self.exchange_manager = ExchangeManager()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        self._create_header_controls(layout)

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

    def _create_header_controls(self, parent_layout):
        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(8)
        self.header_layout.addStretch()

        self.language_title_label = QLabel()
        self.header_layout.addWidget(self.language_title_label)

        self.language_combo = QComboBox()
        self.language_combo.setMinimumWidth(130)
        self.header_layout.addWidget(self.language_combo)

        self.theme_title_label = QLabel()
        self.header_layout.addWidget(self.theme_title_label)

        self.theme_combo = QComboBox()
        self.theme_combo.setMinimumWidth(130)
        self.header_layout.addWidget(self.theme_combo)

        self._fill_language_combo()
        self._fill_theme_combo()

        self.language_combo.currentIndexChanged.connect(self._on_language_combo_changed)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)

        parent_layout.addLayout(self.header_layout)

    def _load_ui_preferences(self):
        saved_language = self.settings_manager.load_ui_language()
        saved_theme = self.settings_manager.load_ui_theme()
        self.language_manager.set_language(saved_language)
        self.theme_manager.set_theme(saved_theme)

    def _fill_language_combo(self):
        current = self.language_manager.language
        ui_ru = current == "ru"

        options = [
            ("ru", "Русский" if ui_ru else "Russian"),
            ("en", "Английский" if ui_ru else "English"),
        ]

        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        for code, label in options:
            self.language_combo.addItem(label, code)
        self._set_combo_value(self.language_combo, current)
        self.language_combo.blockSignals(False)

    def _fill_theme_combo(self):
        current = self.theme_manager.theme_name
        ui_ru = self.language_manager.language == "ru"

        options = [
            ("dark", "Тёмная" if ui_ru else "Dark"),
            ("light", "Светлая" if ui_ru else "Light"),
        ]

        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        for code, label in options:
            self.theme_combo.addItem(label, code)
        self._set_combo_value(self.theme_combo, current)
        self.theme_combo.blockSignals(False)

    @staticmethod
    def _set_combo_value(combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _on_language_combo_changed(self, index):
        language_code = self.language_combo.itemData(index)
        if language_code is None:
            return
        self.language_manager.set_language(str(language_code))
        self.settings_manager.save_ui_language(self.language_manager.language)

    def _on_theme_combo_changed(self, index):
        theme_name = self.theme_combo.itemData(index)
        if theme_name is None:
            return
        self.theme_manager.set_theme(str(theme_name))
        self.settings_manager.save_ui_theme(self.theme_manager.theme_name)

    def _on_language_changed(self, _language):
        self._retranslate_ui()

    def _on_theme_changed(self, _theme_name):
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(get_dark_theme_stylesheet())
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

        if hasattr(self, "language_title_label"):
            if self.language_manager.language == "ru":
                self.language_title_label.setText("Язык:")
                self.theme_title_label.setText("Тема:")
            else:
                self.language_title_label.setText("Language:")
                self.theme_title_label.setText("Theme:")
            self._fill_language_combo()
            self._fill_theme_combo()

        if hasattr(self, "exchanges_tab"):
            self.exchanges_tab.retranslate_ui()
        if hasattr(self, "spread_sniping_tab"):
            self.spread_sniping_tab.retranslate_ui()
        if hasattr(self, "status_bar"):
            self.status_bar.retranslate_ui()

    def _on_exchange_added(self, name, exchange_type, params):
        type_code = normalize_exchange_code(exchange_type)
        try:
            exchange = create_exchange(name, type_code, params)
        except Exception as exc:
            logger.exception("Не удалось создать подключение %s (%s): %s", name, type_code, exc)
            self.status_bar.show_error(
                tr("main.error.create_connector", exchange=type_code.upper(), name=name)
            )
            self.exchanges_tab.set_new_panel_error(tr("main.error.create_connection"))
            return

        is_existing = self.exchange_manager.get_exchange(name) is not None

        # Новую биржу добавляем в менеджер только после успешного подключения.
        if not is_existing and params.get("api_key") and params.get("api_secret"):
            try:
                connected = bool(exchange.connect())
            except Exception as exc:
                logger.exception("Не удалось подключить новую биржу %s (%s): %s", name, type_code, exc)
                self.status_bar.show_error(
                    tr("main.error.connect", exchange=type_code.upper(), name=name)
                )
                self.exchanges_tab.set_new_panel_error(tr("main.error.connect_failed_short"))
                return

            if not connected:
                self.status_bar.show_error(
                    tr("main.error.connect_failed", exchange=type_code.upper(), name=name)
                )
                self.exchanges_tab.set_new_panel_error(tr("main.error.connect_failed_short"))
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
                "ошибка" in lower_text
                or "error" in lower_text
                or "не реализовано" in lower_text
                or "not implemented" in lower_text
            ):
                exchange = self.exchange_manager.get_exchange(name)
                type_code = getattr(exchange, "exchange_type", None)
                meta = get_exchange_meta(type_code)
                self.status_bar.show_error(f"{meta['short']} {name}: {status_text}")

