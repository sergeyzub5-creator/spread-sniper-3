from abc import ABC, abstractmethod
from PySide6.QtCore import QObject, Signal

class BaseExchange(QObject):
    connected = Signal(str)
    disconnected = Signal(str)
    error = Signal(str, str)
    balance_updated = Signal(str, float)
    positions_updated = Signal(str, list)
    pnl_updated = Signal(str, float)
    price_updated = Signal(str, str, dict)
    
    def __init__(self, name, api_key=None, api_secret=None, testnet=False):
        super().__init__()
        self.name = name
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.is_connected = False
        self.balance = 0.0
        self.positions = []
        self.pnl = 0.0
        self.symbols = []
    
    @abstractmethod
    def connect(self): pass
    @abstractmethod
    def disconnect(self): pass
    @abstractmethod
    def subscribe_price(self, symbol): pass
    @abstractmethod
    def unsubscribe_price(self, symbol): pass
    
    def get_status_text(self):
        if self.is_connected:
            mode = "📗 Демо" if self.testnet else "📕 Реал"
            return f"{mode} | Баланс: {self.balance:.2f} USDT | Позиций: {len(self.positions)}"
        return "⭕ Не подключено"
