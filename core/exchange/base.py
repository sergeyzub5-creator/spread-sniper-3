from PySide6.QtCore import QObject, Signal

from core.utils.thread_pool import ThreadManager, Worker


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
        self.last_error = ""

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def subscribe_price(self, symbol):
        raise NotImplementedError

    def unsubscribe_price(self, symbol):
        raise NotImplementedError

    def api_request_async(self, api_func, callback=None, error_callback=None, *args, **kwargs):
        def task():
            return api_func(*args, **kwargs)

        worker = Worker(task)
        if callback:
            worker.signals.result.connect(callback)
        if error_callback:
            worker.signals.error.connect(error_callback)
        ThreadManager().start(worker)

    def get_status_text(self):
        if self.is_connected:
            mode = "Демо" if self.testnet else "Реал"
            return f"{mode} | Баланс: {self.balance:.2f} USDT | Позиции: {len(self.positions)}"
        if self.last_error:
            return f"Ошибка: {self.last_error}"
        return "Не подключено"
