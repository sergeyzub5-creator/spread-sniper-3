import hashlib
import hmac
import json
import math
import time
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter

from core.exchange.base import BaseExchange
from core.utils.logger import get_logger

logger = get_logger(__name__)


class BybitExchange(BaseExchange):
    exchange_type = "bybit"

    def __init__(self, name, api_key=None, api_secret=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)
        # In UI, testnet flag is used as "Демо режим".
        # For Bybit demo-trading, the primary host is api-demo.bybit.com.
        self.base_url = "https://api-demo.bybit.com" if testnet else "https://api.bybit.com"
        self.recv_window = "5000"
        self.timeout = 10
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=0, pool_block=False)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._last_api_error = ""
        self._time_offset_ms = 0
        self._instruments_cache = {"ts": 0.0, "rows": []}

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _step_precision(step):
        value = BybitExchange._to_float(step, default=0.0)
        if value <= 0:
            return -1
        text = f"{float(value):.16f}".rstrip("0").rstrip(".")
        if "." not in text:
            return 0
        return len(text.split(".", 1)[1])

    def _format_to_step(self, value, step):
        precision = self._step_precision(step)
        if precision < 0:
            text = f"{float(value):.16f}"
        elif precision == 0:
            text = str(int(round(float(value))))
        else:
            text = f"{float(value):.{precision}f}"
        text = text.rstrip("0").rstrip(".")
        return text if text else "0"

    @staticmethod
    def _round_up_to_step(value, step):
        number = BybitExchange._to_float(value, default=0.0)
        step_value = BybitExchange._to_float(step, default=0.0)
        if number <= 0 or step_value <= 0:
            return float(number)
        units = math.ceil((float(number) / float(step_value)) - 1e-12)
        return float(units) * float(step_value)

    @staticmethod
    def _round_to_tick(value, tick, side):
        number = BybitExchange._to_float(value, default=0.0)
        tick_value = BybitExchange._to_float(tick, default=0.0)
        if number <= 0 or tick_value <= 0:
            return float(number)
        ratio = float(number) / float(tick_value)
        if str(side or "").strip().lower() == "buy":
            units = math.ceil(ratio - 1e-12)
        else:
            units = math.floor(ratio + 1e-12)
        return float(units) * float(tick_value)

    @staticmethod
    def _is_position_idx_mismatch(error_text):
        text = str(error_text or "").strip().lower()
        if not text:
            return False
        return "position idx not match position mode" in text or "positionidx" in text

    def _sign(self, timestamp, payload_text):
        payload = f"{timestamp}{self.api_key}{self.recv_window}{payload_text}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(self, method, path, params=None, signed=False, _retried_after_sync=False):
        method = str(method or "GET").upper()
        params = dict(params or {})
        source_params = dict(params)
        url = f"{self.base_url}{path}"

        headers = {}
        query_items = sorted(params.items())
        query_text = urlencode(query_items, doseq=True)
        body_text = json.dumps(params, separators=(",", ":"), ensure_ascii=False)
        payload_text = query_text if method == "GET" else body_text

        if signed:
            if not self.api_key or not self.api_secret:
                logger.error("%s: отсутствуют API-данные", self.name)
                self._last_api_error = "missing_api_credentials"
                return None

            timestamp = str(int(time.time() * 1000))
            if self._time_offset_ms:
                timestamp = str(int(time.time() * 1000 + int(self._time_offset_ms)))
            headers.update(
                {
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-TIMESTAMP": timestamp,
                    "X-BAPI-RECV-WINDOW": self.recv_window,
                    "X-BAPI-SIGN-TYPE": "2",
                    "X-BAPI-SIGN": self._sign(timestamp, payload_text),
                }
            )

        request_kwargs = {
            "params": query_items if method == "GET" else None,
            "data": body_text if method != "GET" else None,
            "timeout": self.timeout,
            "headers": headers,
        }
        if method != "GET":
            headers.setdefault("Content-Type", "application/json")

        try:
            response = self.session.request(method, url, **request_kwargs)
        except requests.RequestException as exc:
            logger.error("Bybit %s %s ошибка запроса: %s", method, path, exc)
            self._last_api_error = str(exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        if response.ok and payload.get("retCode") == 0:
            self._last_api_error = ""
            return payload

        ret_code = payload.get("retCode") if isinstance(payload, dict) else None
        ret_msg = payload.get("retMsg") if isinstance(payload, dict) else None
        if signed and not _retried_after_sync and str(ret_code) in {"10002", "10016"}:
            # Request timestamp drift / temporary service restart: sync time and retry once.
            self._probe_and_set_time_offset()
            return self._request(
                method=method,
                path=path,
                params=source_params,
                signed=signed,
                _retried_after_sync=True,
            )

        self._last_api_error = f"http_status={response.status_code}, retCode={ret_code}, retMsg={ret_msg}, payload={payload}"
        logger.error(
            "Bybit %s %s ошибка %s: %s",
            method,
            path,
            response.status_code,
            payload,
        )
        return None

    @staticmethod
    def _is_auth_error_text(error_text):
        text = str(error_text or "").strip().lower()
        if not text:
            return False
        markers = (
            "http_status=401",
            "unauthor",
            "invalid api",
            "permission denied",
            "apikey",
            "api key",
            "signature",
            "retcode=10003",
            "retcode=10004",
            "retcode=10005",
            "retcode=33004",
        )
        return any(marker in text for marker in markers)

    def _candidate_base_urls(self):
        if bool(self.testnet):
            # Demo mode: only demo/testnet endpoints.
            return (
                "https://api-demo.bybit.com",
                "https://api-testnet.bybit.com",
            )
        # Real mode: only production endpoints (no demo).
        return (
            "https://api.bybit.com",
            "https://api.bytick.com",
        )

    def _probe_and_set_time_offset(self):
        market = self._request("GET", "/v5/market/time")
        if not market:
            return False
        try:
            result = market.get("result") if isinstance(market.get("result"), dict) else {}
            server_sec = result.get("timeSecond")
            if server_sec is not None:
                server_ms = int(float(server_sec) * 1000.0)
                self._time_offset_ms = int(server_ms - int(time.time() * 1000))
        except Exception:
            self._time_offset_ms = 0
        return True

    def _load_linear_instruments(self):
        now = time.monotonic()
        cached_ts = float((self._instruments_cache or {}).get("ts") or 0.0)
        cached_rows = (self._instruments_cache or {}).get("rows") or []
        if (now - cached_ts) <= 30.0 and isinstance(cached_rows, list) and cached_rows:
            return list(cached_rows)

        rows = []
        cursor = ""
        for _ in range(8):
            params = {"category": "linear", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            payload = self._request("GET", "/v5/market/instruments-info", params=params, signed=False)
            if not isinstance(payload, dict):
                break
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            page_rows = result.get("list") or []
            rows.extend([row for row in page_rows if isinstance(row, dict)])
            next_cursor = str(result.get("nextPageCursor") or "").strip()
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        self._instruments_cache = {"ts": float(now), "rows": list(rows)}
        return list(rows)

    def _find_linear_instrument(self, symbol):
        target = self._normalize_symbol(symbol)
        if not target:
            return None
        for row in self._load_linear_instruments():
            if self._normalize_symbol(row.get("symbol")) == target:
                return row
        return None

    def _query_order_state(self, symbol, order_id):
        if not order_id:
            return {}
        normalized = self._normalize_symbol(symbol)
        for _ in range(4):
            for open_only in ("0", "1", "2"):
                payload = self._request(
                    "GET",
                    "/v5/order/realtime",
                    params={
                        "category": "linear",
                        "symbol": normalized,
                        "orderId": str(order_id),
                        "openOnly": open_only,
                    },
                    signed=True,
                )
                if not isinstance(payload, dict):
                    continue
                result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
                rows = result.get("list") or []
                row = rows[0] if rows and isinstance(rows[0], dict) else None
                if isinstance(row, dict):
                    return row
            time.sleep(0.05)
        return {}

    def _position_idx_for_order(self, symbol, side, reduce_only=False):
        payload = self._request(
            "GET",
            "/v5/position/list",
            params={"category": "linear", "symbol": self._normalize_symbol(symbol)},
            signed=True,
        )
        rows = []
        if isinstance(payload, dict):
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            rows = [row for row in (result.get("list") or []) if isinstance(row, dict)]

        is_hedge_mode = False
        for row in rows:
            position_idx = int(self._to_float(row.get("positionIdx"), default=0) or 0)
            if position_idx in (1, 2):
                is_hedge_mode = True
                break

        if not is_hedge_mode:
            return 0

        direction = str(side or "").strip().lower()
        if bool(reduce_only):
            return 2 if direction == "buy" else 1
        return 1 if direction == "buy" else 2

    def _submit_order_with_position_idx_fallback(self, params, side, reduce_only=False):
        response = self._request("POST", "/v5/order/create", params=params, signed=True)
        if isinstance(response, dict):
            return response

        if not self._is_position_idx_mismatch(self._last_api_error):
            return None

        retry_params = dict(params)
        current_idx = int(retry_params.get("positionIdx", 0) or 0)
        if current_idx == 0:
            direction = str(side or "").strip().lower()
            if bool(reduce_only):
                retry_params["positionIdx"] = 2 if direction == "buy" else 1
            else:
                retry_params["positionIdx"] = 1 if direction == "buy" else 2
        else:
            retry_params["positionIdx"] = 0
        return self._request("POST", "/v5/order/create", params=retry_params, signed=True)

    def _fetch_balance(self):
        payload = None
        for account_type in ("UNIFIED", "CONTRACT"):
            payload = self._request(
                "GET",
                "/v5/account/wallet-balance",
                params={"accountType": account_type},
                signed=True,
            )
            if payload:
                break
        if not payload:
            return None

        result = payload.get("result", {})
        account_rows = result.get("list") or []
        if not account_rows:
            return 0.0

        coins = account_rows[0].get("coin") or []
        total = 0.0
        for coin in coins:
            if str(coin.get("coin", "")).upper() in {"USDT", "USDC", "USD"}:
                total += self._to_float(coin.get("walletBalance"))
        return total

    def _fetch_positions(self):
        payload = self._request(
            "GET",
            "/v5/position/list",
            params={"category": "linear", "settleCoin": "USDT"},
            signed=True,
        )
        if not payload:
            return None

        result = payload.get("result", {})
        rows = result.get("list") or []
        positions = []
        for row in rows:
            size = self._to_float(row.get("size"))
            if size == 0:
                continue

            side = str(row.get("side", "")).lower()
            if side == "sell":
                size = -abs(size)
            position_idx = int(self._to_float(row.get("positionIdx"), default=0) or 0)

            positions.append(
                {
                    "symbol": row.get("symbol", ""),
                    "size": size,
                    "side": side,
                    "position_idx": position_idx,
                    "entry_price": self._to_float(row.get("avgPrice")),
                    "mark_price": self._to_float(row.get("markPrice")),
                    "pnl": self._to_float(row.get("unrealisedPnl")),
                }
            )
        return positions

    def connect(self):
        logger.info("%s запрос на подключение", self.name)

        if not self.api_key or not self.api_secret:
            msg = "Для Bybit нужны API ключ и API секрет"
            self._emit_error(msg)
            logger.error("%s: %s", self.name, msg)
            return False

        balance = None
        positions = None
        last_error = ""
        selected_url = ""
        for base_url in self._candidate_base_urls():
            self.base_url = str(base_url)
            self._time_offset_ms = 0
            if not self._probe_and_set_time_offset():
                last_error = str(self._last_api_error or "")
                continue
            bal = self._fetch_balance()
            pos = self._fetch_positions()
            if bal is not None and pos is not None:
                balance = bal
                positions = pos
                selected_url = self.base_url
                break
            last_error = str(self._last_api_error or "")
            if not self._is_auth_error_text(last_error):
                # Non-auth failure: no point rotating domains aggressively.
                break

        if balance is None or positions is None:
            mode_hint = "testnet" if bool(self.testnet) else "mainnet/demo"
            hint = f"Bybit авторизация не прошла ({mode_hint}). Проверьте, что ключ создан для правильного окружения."
            if last_error:
                hint = f"{hint} Детали: {last_error}"
            self._emit_error(hint)
            return False

        self.balance = balance
        self.positions = positions
        self.pnl = sum(pos.get("pnl", 0.0) for pos in self.positions)
        self.is_connected = True

        self._emit_connected()
        self._emit_balance_updated()
        self._emit_positions_updated()
        self._emit_pnl_updated()
        logger.info("%s подключена (base=%s)", self.name, selected_url or self.base_url)
        return True

    def disconnect(self):
        self.is_connected = False
        self._emit_disconnected()
        logger.info("%s отключена", self.name)

    def subscribe_price(self, symbol):
        logger.info("%s подписка на %s", self.name, symbol)

    def unsubscribe_price(self, symbol):
        logger.info("%s отписка от %s", self.name, symbol)

    def get_trading_pairs(self, limit=400):
        rows = self._load_linear_instruments()
        pairs = []
        seen = set()
        for row in rows:
            status = str(row.get("status") or "").strip().upper()
            if status and status not in {"TRADING", "TRADING_NORMAL"}:
                continue
            symbol = self._normalize_symbol(row.get("symbol"))
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            pairs.append(symbol)

        if pairs:
            self.symbols = list(pairs)
            return pairs[: max(1, int(limit or 1))]
        return super().get_trading_pairs(limit=limit)

    def open_min_test_position(self, symbol, direction):
        # TEMP: spread-tab order routing verification for Bybit adapter.
        if not self.is_connected:
            raise RuntimeError("Bybit: биржа не подключена")

        side = str(direction or "").strip().lower()
        if side not in {"buy", "sell"}:
            raise RuntimeError("Bybit: неверное направление ордера")

        normalized_symbol = self._normalize_symbol(symbol)
        if not normalized_symbol:
            raise RuntimeError("Bybit: не указана торговая пара")

        instrument = self._find_linear_instrument(normalized_symbol)
        if not isinstance(instrument, dict):
            raise RuntimeError(f"Bybit: инструмент {normalized_symbol} не найден")

        status = str(instrument.get("status") or "").strip().upper()
        if status and status not in {"TRADING", "TRADING_NORMAL"}:
            raise RuntimeError(f"Bybit: инструмент {normalized_symbol} недоступен для торговли")

        lot = instrument.get("lotSizeFilter") if isinstance(instrument.get("lotSizeFilter"), dict) else {}
        price_filter = instrument.get("priceFilter") if isinstance(instrument.get("priceFilter"), dict) else {}

        min_qty = self._to_float(lot.get("minOrderQty"))
        qty_step = self._to_float(lot.get("qtyStep"))
        max_qty = self._to_float(lot.get("maxOrderQty"))
        min_notional = self._to_float(lot.get("minNotionalValue"))
        tick_size = self._to_float(price_filter.get("tickSize"))

        if (min_qty is None or min_qty <= 0) and qty_step is not None and qty_step > 0:
            min_qty = qty_step
        if (qty_step is None or qty_step <= 0) and min_qty is not None and min_qty > 0:
            qty_step = min_qty
        if min_qty is None or min_qty <= 0 or qty_step is None or qty_step <= 0:
            raise RuntimeError(f"Bybit: не удалось определить минимальный объём для {normalized_symbol}")

        ticker = self._request(
            "GET",
            "/v5/market/tickers",
            params={"category": "linear", "symbol": normalized_symbol},
            signed=False,
        )
        if not isinstance(ticker, dict):
            raise RuntimeError("Bybit: не удалось получить best bid/ask")
        result = ticker.get("result") if isinstance(ticker.get("result"), dict) else {}
        rows = result.get("list") or []
        row = rows[0] if rows and isinstance(rows[0], dict) else None
        if not isinstance(row, dict):
            raise RuntimeError("Bybit: тикер не содержит данных по инструменту")

        best_price = self._to_float(row.get("ask1Price") if side == "buy" else row.get("bid1Price"))
        if best_price is None or best_price <= 0:
            raise RuntimeError("Bybit: лучшая цена недоступна")

        qty = float(min_qty)
        if min_notional is not None and min_notional > 0 and best_price > 0:
            qty = max(qty, float(min_notional) / float(best_price))
        qty = self._round_up_to_step(qty, qty_step)
        if max_qty is not None and max_qty > 0 and qty > max_qty:
            raise RuntimeError("Bybit: минимальный тестовый объём превышает maxOrderQty")

        slippage = 0.0002  # 0.02%
        raw_limit = best_price * (1.0 + slippage) if side == "buy" else best_price * (1.0 - slippage)
        limit_price = self._round_to_tick(raw_limit, tick_size, side)
        if limit_price <= 0:
            raise RuntimeError("Bybit: некорректная limit-цена")

        position_idx = self._position_idx_for_order(normalized_symbol, side, reduce_only=False)
        params = {
            "category": "linear",
            "symbol": normalized_symbol,
            "side": "Buy" if side == "buy" else "Sell",
            "orderType": "Limit",
            "timeInForce": "IOC",
            "qty": self._format_to_step(qty, qty_step),
            "price": self._format_to_step(limit_price, tick_size),
            "reduceOnly": False,
            "positionIdx": int(position_idx),
        }

        response = self._submit_order_with_position_idx_fallback(params, side, reduce_only=False)
        if not isinstance(response, dict):
            details = str(self._last_api_error or "").strip()
            raise RuntimeError(f"Bybit: не удалось открыть тестовую позицию ({details})")

        result = response.get("result") if isinstance(response.get("result"), dict) else {}
        order_id = result.get("orderId")
        order_state = self._query_order_state(normalized_symbol, order_id)

        executed_qty = self._to_float((order_state or {}).get("cumExecQty"))
        status_text = str((order_state or {}).get("orderStatus") or "").strip().upper()
        if executed_qty is None:
            executed_qty = 0.0
        if not status_text:
            status_text = "UNKNOWN"

        return {
            "symbol": normalized_symbol,
            "side": side,
            "quantity": self._format_to_step(qty, qty_step),
            "executed_qty": self._format_to_step(executed_qty, qty_step),
            "status": status_text,
            "avg_price": self._to_float((order_state or {}).get("avgPrice")),
            "order_type": "LIMIT",
            "limit_price": self._format_to_step(limit_price, tick_size),
            "order_id": order_id,
            "position_idx": int(position_idx),
        }

    def close_all_positions(self):
        if not self.is_connected:
            return 0

        positions = self._fetch_positions()
        if positions is None:
            raise RuntimeError("Bybit: не удалось получить позиции для закрытия")

        if not positions:
            self.positions = []
            self.pnl = 0.0
            self._emit_positions_updated()
            self._emit_pnl_updated()
            return 0

        failed = []
        closed = 0
        for pos in positions:
            symbol = self._normalize_symbol(pos.get("symbol"))
            size = self._to_float(pos.get("size"))
            if not symbol or size is None or size == 0:
                continue

            close_side = "sell" if float(size) > 0 else "buy"
            qty_abs = abs(float(size))
            instrument = self._find_linear_instrument(symbol)
            lot = instrument.get("lotSizeFilter") if isinstance(instrument, dict) else {}
            qty_step = self._to_float(lot.get("qtyStep"))
            if qty_step is not None and qty_step > 0:
                qty_abs = math.floor((qty_abs / qty_step) + 1e-12) * qty_step
            if qty_abs <= 0:
                continue

            position_idx = int(self._to_float(pos.get("position_idx"), default=0) or 0)
            params = {
                "category": "linear",
                "symbol": symbol,
                "side": "Sell" if close_side == "sell" else "Buy",
                "orderType": "Market",
                "qty": self._format_to_step(qty_abs, qty_step),
                "reduceOnly": True,
                "closeOnTrigger": True,
                "positionIdx": int(position_idx),
            }
            response = self._submit_order_with_position_idx_fallback(params, close_side, reduce_only=True)
            if not isinstance(response, dict):
                failed.append(symbol)
                continue
            closed += 1

        balance = self._fetch_balance()
        positions_after = self._fetch_positions()
        if balance is not None:
            self.balance = balance
            self._emit_balance_updated()
        if positions_after is not None:
            self.positions = positions_after
            self.pnl = sum(pos.get("pnl", 0.0) for pos in self.positions)
            self._emit_positions_updated()
            self._emit_pnl_updated()

        if failed:
            raise RuntimeError(f"Bybit: не удалось закрыть позиции {', '.join(sorted(set(failed)))}")

        return int(closed)
