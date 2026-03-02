import time

from PySide6.QtCore import QObject, Signal

from core.i18n import tr
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

        # Persisted user intent: whether this exchange should auto-connect on app start.
        self.auto_connect = True

        # Fast metrics refresh: positions/pnl every cycle, balance throttled.
        self.balance_refresh_interval_sec = 3.0
        self._last_balance_refresh_ts = 0.0

    @staticmethod
    def _normalize_symbol(value):
        text = str(value or "").strip().upper()
        if not text:
            return ""
        for ch in ("-", "_", " ", "/"):
            text = text.replace(ch, "")
        return text

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def subscribe_price(self, symbol):
        raise NotImplementedError

    def unsubscribe_price(self, symbol):
        raise NotImplementedError

    def get_trading_pairs(self, limit=400):
        pairs = []
        seen = set()

        for raw in self.symbols or []:
            symbol = self._normalize_symbol(raw)
            if symbol and symbol not in seen:
                seen.add(symbol)
                pairs.append(symbol)

        for pos in self.positions or []:
            symbol = self._normalize_symbol(pos.get("symbol"))
            if symbol and symbol not in seen:
                seen.add(symbol)
                pairs.append(symbol)

        if not pairs:
            pairs = [
                "BTCUSDT",
                "ETHUSDT",
                "SOLUSDT",
                "BNBUSDT",
                "XRPUSDT",
                "DOGEUSDT",
                "ADAUSDT",
                "TRXUSDT",
                "LTCUSDT",
                "LINKUSDT",
                "AVAXUSDT",
                "DOTUSDT",
            ]

        limit_value = max(1, int(limit or 1))
        return pairs[:limit_value]

    def close_all_positions(self):
        raise NotImplementedError(
            "\u0417\u0430\u043a\u0440\u044b\u0442\u0438\u0435 \u043f\u043e\u0437\u0438\u0446\u0438\u0439 \u0434\u043b\u044f "
            "\u044d\u0442\u043e\u0439 \u0431\u0438\u0440\u0436\u0438 \u043d\u0435 \u0440\u0435\u0430\u043b\u0438\u0437\u043e\u0432\u0430\u043d\u043e"
        )

    def refresh_state(self):
        if not self.is_connected:
            return False

        fetch_positions = getattr(self, "_fetch_positions", None)
        if not callable(fetch_positions):
            raise NotImplementedError(
                "\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u044f "
                "\u0434\u043b\u044f \u044d\u0442\u043e\u0439 \u0431\u0438\u0440\u0436\u0438 \u043d\u0435 \u0440\u0435\u0430\u043b\u0438\u0437\u043e\u0432\u0430\u043d\u043e"
            )

        positions = fetch_positions()
        if positions is None:
            raise RuntimeError(
                "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0431\u043d\u043e\u0432\u0438\u0442\u044c "
                "\u0434\u0430\u043d\u043d\u044b\u0435 \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430"
            )

        self.positions = list(positions or [])
        self.pnl = sum(float(pos.get("pnl", 0.0) or 0.0) for pos in self.positions)
        self.positions_updated.emit(self.name, self.positions)
        self.pnl_updated.emit(self.name, self.pnl)

        fetch_balance = getattr(self, "_fetch_balance", None)
        if callable(fetch_balance):
            now = time.monotonic()
            need_balance_refresh = (
                self._last_balance_refresh_ts <= 0
                or (now - self._last_balance_refresh_ts) >= float(self.balance_refresh_interval_sec)
            )
            if need_balance_refresh:
                balance = fetch_balance()
                if balance is not None:
                    self.balance = float(balance or 0.0)
                    self.balance_updated.emit(self.name, self.balance)
                    self._last_balance_refresh_ts = now

        return True

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
        if self.last_error:
            return f"\u041e\u0448\u0438\u0431\u043a\u0430: {self.last_error}"
        if self.is_connected:
            mode = tr("mode.demo") if self.testnet else tr("mode.real")
            balance = tr("label.balance", value=f"{self.balance:.2f}")
            positions = tr("label.positions", value=len(self.positions))
            return f"{mode} | {balance} | {positions}"
        return tr("status.disconnected")
