from PySide6.QtWidgets import QMainWindow, QTabWidget, QVBoxLayout, QWidget

from core.exchange import ExchangeManager, create_exchange
from core.exchange.catalog import get_exchange_meta, normalize_exchange_code
from core.utils.logger import get_logger
from ui.styles.dark_theme import get_dark_theme_stylesheet
from ui.tabs.exchanges_tab import ExchangesTab
from ui.widgets.status_bar import NetworkStatusBar

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Спред Снайпер 3")
        self.resize(1200, 700)

        self.setStyleSheet(get_dark_theme_stylesheet())

        self.exchange_manager = ExchangeManager()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.exchanges_tab = ExchangesTab(self.exchange_manager)
        self.exchanges_tab.exchange_added.connect(self._on_exchange_added)
        self.exchanges_tab.exchange_removed.connect(self.exchange_manager.remove_exchange)
        self.tabs.addTab(self.exchanges_tab, "Биржи")

        self.status_bar = NetworkStatusBar()
        layout.addWidget(self.status_bar)

        self.exchange_manager.status_updated.connect(self._on_status_updated)

    def _on_exchange_added(self, name, exchange_type, params):
        type_code = normalize_exchange_code(exchange_type)
        try:
            exchange = create_exchange(name, type_code, params)
        except Exception as exc:
            logger.exception("Не удалось создать подключение %s (%s): %s", name, type_code, exc)
            self.status_bar.show_error(f"{type_code.upper()} {name}: не удалось создать коннектор")
            self.exchanges_tab.set_new_panel_error("Не удалось создать подключение")
            return

        is_existing = self.exchange_manager.get_exchange(name) is not None

        # Новую биржу добавляем в менеджер только после успешного подключения.
        if not is_existing and params.get("api_key") and params.get("api_secret"):
            try:
                connected = bool(exchange.connect())
            except Exception as exc:
                logger.exception("Не удалось подключить новую биржу %s (%s): %s", name, type_code, exc)
                self.status_bar.show_error(f"{type_code.upper()} {name}: ошибка подключения")
                self.exchanges_tab.set_new_panel_error("Ошибка подключения")
                return

            if not connected:
                self.status_bar.show_error(f"{type_code.upper()} {name}: не удалось подключиться")
                self.exchanges_tab.set_new_panel_error("Не удалось подключиться")
                return

        if is_existing:
            if not self.exchange_manager.update_exchange(name, exchange):
                self.status_bar.show_error(f"{type_code.upper()} {name}: не удалось обновить настройки")
                return

            if params.get("api_key") and params.get("api_secret"):
                self.exchange_manager.connect_exchange_async(name)
        else:
            if not self.exchange_manager.add_exchange(exchange):
                self.status_bar.show_error(f"{type_code.upper()} {name}: не удалось добавить биржу")
                self.exchanges_tab.set_new_panel_error("Не удалось добавить биржу")

    def _on_status_updated(self, statuses):
        for name, status in statuses.items():
            if status.get("connected", False) or status.get("loading", False):
                continue

            status_text = status.get("status_text", "")
            lower_text = status_text.lower()
            if "ошибка" in lower_text or "не реализовано" in lower_text:
                exchange = self.exchange_manager.get_exchange(name)
                type_code = getattr(exchange, "exchange_type", None)
                meta = get_exchange_meta(type_code)
                self.status_bar.show_error(f"{meta['short']} {name}: {status_text}")
