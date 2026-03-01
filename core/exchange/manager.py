from PySide6.QtCore import QObject, Signal

from core.exchange.factory import create_exchange
from core.exchange.catalog import normalize_exchange_code
from core.utils.logger import get_logger

logger = get_logger(__name__)


class ExchangeManager(QObject):
    exchange_added = Signal(str)
    exchange_removed = Signal(str)
    status_updated = Signal(dict)

    def __init__(self):
        super().__init__()
        # Import here to avoid circular imports at module import time.
        from core.data.storage import ExchangeStorage

        self.exchanges = {}
        self.storage = ExchangeStorage()
        self._last_statuses = None
        self._load_saved_exchanges()
        self._emit_status_updated(force=True)

    def _safe_disconnect(self, signal, slot):
        try:
            signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass

    def _wire_exchange_signals(self, exchange):
        exchange.connected.connect(self._on_exchange_connected)
        exchange.disconnected.connect(self._on_exchange_disconnected)
        exchange.balance_updated.connect(self._on_exchange_balance_updated)
        exchange.positions_updated.connect(self._on_exchange_positions_updated)
        exchange.pnl_updated.connect(self._on_exchange_pnl_updated)
        exchange.error.connect(self._on_exchange_error)

    def _unwire_exchange_signals(self, exchange):
        self._safe_disconnect(exchange.connected, self._on_exchange_connected)
        self._safe_disconnect(exchange.disconnected, self._on_exchange_disconnected)
        self._safe_disconnect(exchange.balance_updated, self._on_exchange_balance_updated)
        self._safe_disconnect(exchange.positions_updated, self._on_exchange_positions_updated)
        self._safe_disconnect(exchange.pnl_updated, self._on_exchange_pnl_updated)
        self._safe_disconnect(exchange.error, self._on_exchange_error)

    def _on_exchange_connected(self, _name):
        exchange = self.exchanges.get(_name)
        if exchange:
            exchange.last_error = ""
        self._emit_status_updated()

    def _on_exchange_disconnected(self, _name):
        self._emit_status_updated()

    def _on_exchange_balance_updated(self, _name, _balance):
        self._emit_status_updated()

    def _on_exchange_positions_updated(self, _name, _positions):
        self._emit_status_updated()

    def _on_exchange_pnl_updated(self, _name, _pnl):
        self._emit_status_updated()

    def _on_exchange_error(self, name, message):
        logger.error("%s: %s", name, message)
        exchange = self.exchanges.get(name)
        if exchange:
            exchange.last_error = str(message)
        self._emit_status_updated()

    def _load_saved_exchanges(self):
        saved_data = self.storage.load_exchanges()
        for name, data in saved_data.items():
            exchange_type = normalize_exchange_code(data.get("type"))
            params = {
                "api_key": data.get("api_key"),
                "api_secret": data.get("api_secret"),
                "testnet": data.get("testnet", False),
            }
            if data.get("api_passphrase"):
                params["api_passphrase"] = data.get("api_passphrase")

            exchange = create_exchange(name, exchange_type, params)

            self.exchanges[name] = exchange
            self._wire_exchange_signals(exchange)
            self.exchange_added.emit(name)

            if params.get("api_key") and params.get("api_secret"):
                try:
                    exchange.connect()
                except Exception as exc:
                    logger.exception("Failed to connect saved exchange %s: %s", name, exc)

    def _save_exchanges(self):
        self.storage.save_exchanges(self.exchanges)

    def _emit_status_updated(self, force=False):
        statuses = self.get_all_status()
        if not force and statuses == self._last_statuses:
            return
        self._last_statuses = statuses
        self.status_updated.emit(statuses)

    def add_exchange(self, exchange):
        name = exchange.name
        if name in self.exchanges:
            logger.warning("Exchange %s already exists", name)
            return False

        self.exchanges[name] = exchange
        self._wire_exchange_signals(exchange)
        self.exchange_added.emit(name)
        self._save_exchanges()
        self._emit_status_updated(force=True)
        return True

    def update_exchange(self, name, exchange):
        if name not in self.exchanges:
            return False

        old_exchange = self.exchanges[name]
        if old_exchange.is_connected:
            old_exchange.disconnect()
        self._unwire_exchange_signals(old_exchange)

        self.exchanges[name] = exchange
        self._wire_exchange_signals(exchange)
        self._save_exchanges()
        self._emit_status_updated(force=True)
        return True

    def remove_exchange(self, name):
        if name not in self.exchanges:
            return False

        exchange = self.exchanges[name]
        if exchange.is_connected:
            exchange.disconnect()

        self._unwire_exchange_signals(exchange)
        del self.exchanges[name]
        self.exchange_removed.emit(name)
        self._save_exchanges()
        self._emit_status_updated(force=True)
        return True

    def get_exchange(self, name):
        return self.exchanges.get(name)

    def get_all_exchanges(self):
        return self.exchanges

    def get_connected_names(self):
        return [name for name, ex in self.exchanges.items() if ex.is_connected]

    def get_all_status(self):
        statuses = {}
        for name, ex in self.exchanges.items():
            statuses[name] = {
                "connected": ex.is_connected,
                "testnet": ex.testnet,
                "balance": ex.balance,
                "positions_count": len(ex.positions),
                "pnl": ex.pnl,
                "status_text": ex.get_status_text(),
            }
        return statuses

    def disconnect_all(self):
        for exchange in self.exchanges.values():
            if exchange.is_connected:
                exchange.disconnect()
        self._save_exchanges()
        self._emit_status_updated(force=True)
