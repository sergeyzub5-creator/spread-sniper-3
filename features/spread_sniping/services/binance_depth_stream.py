import json
import threading
import time

import websocket
from PySide6.QtCore import QObject, Signal


class BinanceDepthStream(QObject):
    tick = Signal(dict)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._symbol = ""
        self._testnet = False
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._ws = None

    def start(self, symbol, testnet=False):
        new_symbol = str(symbol or "").strip().upper()
        if not new_symbol:
            self.stop()
            return

        same_target = (
            bool(self._thread and self._thread.is_alive())
            and self._symbol == new_symbol
            and self._testnet == bool(testnet)
        )
        if same_target:
            return

        self.stop()
        self._symbol = new_symbol
        self._testnet = bool(testnet)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        ws_obj = None
        with self._lock:
            ws_obj = self._ws
        try:
            if ws_obj is not None:
                ws_obj.close()
        except Exception:
            pass

        thread = self._thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=1.5)
        self._thread = None

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _emit_safe(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def _ws_base_url(self):
        if self._testnet:
            return "wss://fstream.binancefuture.com"
        return "wss://fstream.binance.com"

    @staticmethod
    def _parse_levels(rows, limit=5):
        out = []
        for row in rows or []:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            price = BinanceDepthStream._to_float(row[0])
            qty = BinanceDepthStream._to_float(row[1])
            if price is None or qty is None or price <= 0 or qty <= 0:
                continue
            out.append({"price": price, "qty": qty})
            if len(out) >= int(limit or 1):
                break
        return out

    def _run_loop(self):
        # Partial order-book stream: top levels, high update rate.
        url = f"{self._ws_base_url()}/ws/{self._symbol.lower()}@depth5@100ms"

        while not self._stop_event.is_set():
            ws_app = None
            try:
                ws_app = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                with self._lock:
                    self._ws = ws_app
                ws_app.run_forever(ping_interval=120, ping_timeout=30)
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._emit_safe(self.error, str(exc))
            finally:
                with self._lock:
                    self._ws = None

            if not self._stop_event.is_set():
                time.sleep(0.8)

    def _on_message(self, _ws, message):
        if self._stop_event.is_set():
            return

        try:
            raw = json.loads(message if isinstance(message, str) else message.decode("utf-8"))
        except Exception:
            return

        data = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
        if not isinstance(data, dict):
            return

        symbol = str(data.get("s") or "").upper()
        bids = self._parse_levels(data.get("b"), limit=5)
        asks = self._parse_levels(data.get("a"), limit=5)
        event_time = data.get("E")

        if not symbol:
            return

        self._emit_safe(
            self.tick,
            {
                "symbol": symbol,
                "bids": bids,
                "asks": asks,
                "event_time": event_time,
            },
        )

    def _on_error(self, _ws, error):
        if self._stop_event.is_set():
            return
        self._emit_safe(self.error, str(error))

    def _on_close(self, _ws, _code, _msg):
        return

