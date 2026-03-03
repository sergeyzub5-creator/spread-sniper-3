import json
import threading
import time

import websocket
from PySide6.QtCore import QObject, Signal


class BitgetBookTickerStream(QObject):
    tick = Signal(dict)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._symbol = ""
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._ws = None
        self._ping_thread = None
        self._inst_types = (
            "USDT-FUTURES",
            "COIN-FUTURES",
            "USDC-FUTURES",
            "SPOT",
        )

    def start(self, symbol, testnet=False):
        # Bitget paper/public websocket is mapped to the same public endpoint for ticker channel.
        _ = testnet
        new_symbol = str(symbol or "").strip().upper()
        if not new_symbol:
            self.stop()
            return

        same_target = bool(self._thread and self._thread.is_alive()) and self._symbol == new_symbol
        if same_target:
            return

        self.stop()
        self._symbol = new_symbol
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self, wait=False):
        self._stop_event.set()
        ws_obj = None
        with self._lock:
            ws_obj = self._ws
        try:
            if ws_obj is not None:
                ws_obj.close()
        except Exception:
            pass

        ping_thread = self._ping_thread
        if ping_thread and ping_thread.is_alive() and threading.current_thread() is not ping_thread:
            ping_thread.join(timeout=1.5 if wait else 0.05)
        self._ping_thread = None

        thread = self._thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            # Keep stop non-blocking for UI responsiveness.
            thread.join(timeout=1.5 if wait else 0.05)
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

    @staticmethod
    def _ws_base_url():
        return "wss://ws.bitget.com/v2/ws/public"

    def _start_ping_thread(self):
        self._stop_ping_thread()
        self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._ping_thread.start()

    def _stop_ping_thread(self):
        ping_thread = self._ping_thread
        if ping_thread and ping_thread.is_alive() and threading.current_thread() is not ping_thread:
            ping_thread.join(timeout=0.05)
        self._ping_thread = None

    def _ping_loop(self):
        while not self._stop_event.is_set():
            time.sleep(20.0)
            if self._stop_event.is_set():
                break
            ws_obj = None
            with self._lock:
                ws_obj = self._ws
            if ws_obj is None:
                continue
            try:
                ws_obj.send("ping")
            except Exception:
                break

    def _on_open(self, ws):
        self._start_ping_thread()
        payload = {"op": "subscribe", "args": []}
        for inst_type in self._inst_types:
            payload["args"].append(
                {
                    "instType": inst_type,
                    "channel": "ticker",
                    "instId": self._symbol,
                }
            )
        ws.send(json.dumps(payload, separators=(",", ":")))

    def _run_loop(self):
        url = self._ws_base_url()

        while not self._stop_event.is_set():
            ws_app = None
            try:
                ws_app = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                with self._lock:
                    self._ws = ws_app
                ws_app.run_forever(ping_interval=0)
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._emit_safe(self.error, str(exc))
            finally:
                self._stop_ping_thread()
                with self._lock:
                    self._ws = None

            if not self._stop_event.is_set():
                time.sleep(0.8)

    def _on_message(self, _ws, message):
        if self._stop_event.is_set():
            return

        msg_text = message if isinstance(message, str) else message.decode("utf-8", errors="ignore")
        if not msg_text:
            return
        lower_msg = msg_text.strip().lower()
        if lower_msg in {"pong", "ping"}:
            return

        try:
            payload = json.loads(msg_text)
        except Exception:
            return

        data_rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data_rows, list) or not data_rows:
            return
        arg = payload.get("arg") if isinstance(payload, dict) else None
        market_type = str(arg.get("instType") or "").upper() if isinstance(arg, dict) else ""

        row = data_rows[0] if isinstance(data_rows[0], dict) else None
        if not isinstance(row, dict):
            return

        symbol = str(row.get("instId") or row.get("symbol") or "").upper()
        bid = self._to_float(row.get("bidPr"))
        ask = self._to_float(row.get("askPr"))
        bid_qty = self._to_float(row.get("bidSz"))
        ask_qty = self._to_float(row.get("askSz"))
        event_time = row.get("ts")
        if not symbol or bid is None or ask is None:
            return

        self._emit_safe(
            self.tick,
            {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "bid_qty": bid_qty,
                "ask_qty": ask_qty,
                "event_time": event_time,
                "market_type": market_type,
            },
        )

    def _on_error(self, _ws, error):
        if self._stop_event.is_set():
            return
        self._emit_safe(self.error, str(error))

    def _on_close(self, _ws, _code, _msg):
        return
