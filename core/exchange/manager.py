from PySide6.QtCore import QObject, QTimer, Signal

from core.exchange.catalog import normalize_exchange_code
from core.exchange.factory import create_exchange
from core.utils.logger import get_logger
from core.utils.thread_pool import ThreadManager, Worker

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
        self._loading_exchanges = set()
        self._connect_workers = {}
        self._refresh_workers = {}
        self._refresh_unsupported = set()
        self._disconnect_on_connect = set()

        self._load_saved_exchanges()
        self._emit_status_updated(force=True)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(600)
        self._refresh_timer.timeout.connect(self._refresh_connected_async)
        self._refresh_timer.start()

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

    def _on_exchange_connected(self, name):
        exchange = self.exchanges.get(name)
        if exchange and name in self._disconnect_on_connect:
            # Late connect completed after manual disconnect: force back to disconnected.
            exchange.auto_connect = False
            self._loading_exchanges.discard(name)
            self._refresh_unsupported.discard(name)
            if exchange.is_connected:
                exchange.disconnect()
            self._emit_status_updated(force=True)
            return

        if exchange:
            exchange.last_error = ""
        self._loading_exchanges.discard(name)
        self._refresh_unsupported.discard(name)
        self._start_refresh_worker(name)
        self._emit_status_updated()

    def _on_exchange_disconnected(self, name):
        self._loading_exchanges.discard(name)
        self._refresh_unsupported.discard(name)
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

    def _on_connect_worker_error(self, name, error_text):
        logger.error("Ошибка фонового подключения %s: %s", name, error_text)
        exchange = self.exchanges.get(name)
        if exchange and not exchange.last_error:
            exchange.last_error = str(error_text)
        self._emit_status_updated()

    def _on_connect_worker_finished(self, name):
        self._loading_exchanges.discard(name)
        self._connect_workers.pop(name, None)
        exchange = self.exchanges.get(name)
        if exchange and exchange.is_connected:
            self._start_refresh_worker(name)
        self._emit_status_updated(force=True)

    def _on_refresh_worker_finished(self, name):
        self._refresh_workers.pop(name, None)

    def _refresh_exchange_task(self, name):
        exchange = self.exchanges.get(name)
        if exchange is None or not exchange.is_connected:
            return {"status": "skip"}

        try:
            exchange.refresh_state()
            return {"status": "ok"}
        except NotImplementedError:
            return {"status": "unsupported"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _on_refresh_worker_result(self, name, result):
        result = result or {}
        status = result.get("status")
        exchange = self.exchanges.get(name)
        if exchange is None:
            return

        if status == "ok":
            if exchange.last_error:
                exchange.last_error = ""
                self._emit_status_updated(force=True)
            return
        if status == "unsupported":
            self._refresh_unsupported.add(name)
            return

        if status == "error":
            message = str(result.get("error") or "?????? ?????????? ?????????")
            exchange.last_error = message
            logger.error("%s: ?????? refresh_state: %s", name, message)
            self._emit_status_updated(force=True)

    def _start_connect_worker(self, name):
        exchange = self.exchanges.get(name)
        if exchange is None:
            return False
        if name in self._loading_exchanges:
            return False
        if exchange.is_connected:
            return False

        if not exchange.api_key or not exchange.api_secret:
            return False

        self._loading_exchanges.add(name)
        self._emit_status_updated(force=True)

        worker = Worker(exchange.connect)
        self._connect_workers[name] = worker
        worker.signals.error.connect(lambda err, ex_name=name: self._on_connect_worker_error(ex_name, err))
        worker.signals.finished.connect(lambda ex_name=name: self._on_connect_worker_finished(ex_name))
        ThreadManager().start(worker)
        return True

    def _load_saved_exchanges(self):
        saved_data = self.storage.load_exchanges()
        for name, data in saved_data.items():
            exchange_type = normalize_exchange_code(data.get("type"))
            params = {
                "api_key": data.get("api_key"),
                "api_secret": data.get("api_secret"),
                "testnet": data.get("testnet", False),
            }
            auto_connect = bool(data.get("auto_connect", True))
            if data.get("api_passphrase"):
                params["api_passphrase"] = data.get("api_passphrase")

            exchange = create_exchange(name, exchange_type, params)
            exchange.auto_connect = auto_connect
            self.exchanges[name] = exchange
            self._wire_exchange_signals(exchange)
            self.exchange_added.emit(name)

            if exchange.auto_connect and params.get("api_key") and params.get("api_secret"):
                self._start_connect_worker(name)

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
            logger.warning("Биржа %s уже существует", name)
            return False

        exchange.auto_connect = True
        self.exchanges[name] = exchange
        self._wire_exchange_signals(exchange)
        self.exchange_added.emit(name)
        self._save_exchanges()
        self._emit_status_updated(force=True)
        return True

    def update_exchange(self, name, exchange):
        if name not in self.exchanges:
            return False

        self._loading_exchanges.discard(name)
        self._disconnect_on_connect.discard(name)

        old_exchange = self.exchanges[name]
        if old_exchange.is_connected:
            old_exchange.disconnect()
        self._unwire_exchange_signals(old_exchange)

        exchange.auto_connect = True
        self.exchanges[name] = exchange
        self._wire_exchange_signals(exchange)
        self._save_exchanges()
        self._emit_status_updated(force=True)
        return True

    def remove_exchange(self, name):
        if name not in self.exchanges:
            return False

        self._loading_exchanges.discard(name)
        self._disconnect_on_connect.discard(name)
        self._connect_workers.pop(name, None)
        self._refresh_workers.pop(name, None)
        self._refresh_unsupported.discard(name)

        exchange = self.exchanges[name]
        if exchange.is_connected:
            exchange.disconnect()

        self._unwire_exchange_signals(exchange)
        del self.exchanges[name]
        self.exchange_removed.emit(name)
        self._save_exchanges()
        self._emit_status_updated(force=True)
        return True

    def connect_exchange_async(self, name):
        exchange = self.exchanges.get(name)
        if exchange is None:
            return False
        self._disconnect_on_connect.discard(name)
        exchange.auto_connect = True
        self._save_exchanges()
        return self._start_connect_worker(name)

    def connect_all_async(self):
        for name in self.exchanges.keys():
            exchange = self.exchanges.get(name)
            if exchange is not None:
                self._disconnect_on_connect.discard(name)
                exchange.auto_connect = True
            self._start_connect_worker(name)
        self._save_exchanges()

    def disconnect_exchange(self, name, manual=False):
        exchange = self.exchanges.get(name)
        if exchange is None:
            return False

        if manual:
            exchange.auto_connect = False
            self._disconnect_on_connect.add(name)

        if exchange.is_connected:
            exchange.disconnect()
        else:
            self._loading_exchanges.discard(name)
            self._emit_status_updated(force=True)

        self._save_exchanges()
        return True

    def _start_refresh_worker(self, name):
        exchange = self.exchanges.get(name)
        if exchange is None:
            return False
        if name in self._disconnect_on_connect:
            return False
        if not exchange.is_connected:
            return False
        if name in self._loading_exchanges:
            return False
        if name in self._refresh_workers:
            return False
        if name in self._refresh_unsupported:
            return False

        worker = Worker(self._refresh_exchange_task, name)
        self._refresh_workers[name] = worker
        worker.signals.result.connect(
            lambda result, ex_name=name: self._on_refresh_worker_result(ex_name, result)
        )
        worker.signals.finished.connect(lambda ex_name=name: self._on_refresh_worker_finished(ex_name))
        ThreadManager().start(worker)
        return True

    def _refresh_connected_async(self):
        for name, exchange in self.exchanges.items():
            if exchange.is_connected and name not in self._disconnect_on_connect:
                self._start_refresh_worker(name)

    def get_exchange(self, name):
        return self.exchanges.get(name)

    def is_exchange_loading(self, name):
        return name in self._loading_exchanges or name in self._connect_workers

    def get_all_exchanges(self):
        return self.exchanges

    def get_connected_names(self):
        return [name for name, ex in self.exchanges.items() if ex.is_connected]

    def get_all_status(self):
        statuses = {}
        for name, ex in self.exchanges.items():
            loading = name in self._loading_exchanges
            status_text = ex.get_status_text()
            if loading and not ex.is_connected:
                status_text = "Загрузка..."

            statuses[name] = {
                "connected": ex.is_connected,
                "loading": loading,
                "testnet": ex.testnet,
                "balance": ex.balance,
                "positions_count": len(ex.positions),
                "pnl": ex.pnl,
                "status_text": status_text,
            }
        return statuses

    def disconnect_all(self, manual=False):
        for name, exchange in self.exchanges.items():
            if manual:
                exchange.auto_connect = False
                self._disconnect_on_connect.add(name)
            if exchange.is_connected:
                exchange.disconnect()

        self._loading_exchanges.clear()
        self._connect_workers.clear()
        self._refresh_workers.clear()
        self._refresh_unsupported.clear()
        self._save_exchanges()
        self._emit_status_updated(force=True)

    def close_all_positions(self):
        summary = {
            "ok": [],
            "failed": {},
            "unsupported": {},
            "disconnected": [],
            "closed_positions": 0,
        }

        for name, exchange in self.exchanges.items():
            if not exchange.is_connected:
                summary["disconnected"].append(name)
                continue

            try:
                closed_count = exchange.close_all_positions()
                summary["ok"].append(name)
                summary["closed_positions"] += int(closed_count or 0)
                exchange.last_error = ""
            except NotImplementedError as exc:
                message = str(exc) or "Закрытие позиций не реализовано"
                summary["unsupported"][name] = message
                exchange.last_error = message
            except Exception as exc:
                message = str(exc) or "Ошибка закрытия позиций"
                summary["failed"][name] = message
                exchange.last_error = message
                logger.error("%s: ошибка закрытия всех позиций: %s", name, message)

        self._emit_status_updated(force=True)
        return summary

    def close_positions_for_exchange(self, name):
        exchange = self.exchanges.get(name)
        if exchange is None:
            raise RuntimeError(f"Биржа {name} не найдена")
        if not exchange.is_connected:
            raise RuntimeError(f"Биржа {name} не подключена")

        closed_count = exchange.close_all_positions()
        exchange.last_error = ""
        self._emit_status_updated(force=True)
        return {"name": name, "closed_positions": int(closed_count or 0)}
