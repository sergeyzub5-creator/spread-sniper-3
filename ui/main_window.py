from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTabWidget
from PySide6.QtCore import Qt
from core.exchange import ExchangeManager
from ui.styles.dark_theme import get_dark_theme_stylesheet
from ui.widgets.status_bar import NetworkStatusBar
from ui.tabs.exchanges_tab import ExchangesTab

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Spread Sniper 3")
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
        self.tabs.addTab(self.exchanges_tab, "📊 Биржи")
        
        self.status_bar = NetworkStatusBar()
        layout.addWidget(self.status_bar)
        
        self.exchange_manager.status_updated.connect(self._on_status_updated)
    
    def _on_exchange_added(self, name, exchange_type, params):
        from core.exchange import BinanceExchange, BitgetExchange
        
        if exchange_type == 'binance':
            exchange = BinanceExchange(name, **params)
        elif exchange_type == 'bitget':
            exchange = BitgetExchange(name, **params)
        else:
            return
        
        self.exchange_manager.add_exchange(exchange)
        if params.get('api_key') and params.get('api_secret'):
            exchange.connect()
    
    def _on_status_updated(self, statuses):
        for name, status in statuses.items():
            if not status.get('connected', False):
                status_text = status.get('status_text', '')
                if 'ошибка' in status_text.lower():
                    self.status_bar.show_error(f"{name}: {status_text}")

