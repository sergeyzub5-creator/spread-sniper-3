import hashlib
import hmac
import math
import time
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter

from core.exchange.base import BaseExchange
from core.utils.logger import get_logger

logger = get_logger(__name__)


class BinanceExchange(BaseExchange):
    exchange_type = "binance"

    def __init__(self, name, api_key=None, api_secret=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)

        # Binance USD-M Futures base URLs from official docs.
        self.rest_url = "https://demo-fapi.binance.com" if testnet else "https://fapi.binance.com"
        self.timeout = 10
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=0, pool_block=False)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        if api_key:
            self.session.headers.update({"X-MBX-APIKEY": api_key})
        self.time_offset = 0
        self._last_api_error = ""

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _get_server_time_offset(self):
        try:
            response = self.session.get(f"{self.rest_url}/fapi/v1/time", timeout=self.timeout)
            response.raise_for_status()
            server_time = response.json().get("serverTime")
            if server_time is None:
                return 0
            local_time = int(time.time() * 1000)
            return int(server_time) - local_time
        except requests.RequestException as exc:
            logger.error("Ошибка получения времени Binance: %s", exc)
            return 0

    def _sign_params(self, params):
        query_string = urlencode(params, doseq=True)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed = dict(params)
        signed["signature"] = signature
        return signed

    def _request(self, method, endpoint, signed=False, params=None, _retried_after_time_sync=False):
        method = method.upper()
        source_params = dict(params or {})
        params = dict(source_params)
        url = f"{self.rest_url}{endpoint}"

        if signed:
            if not self.api_key or not self.api_secret:
                self._last_api_error = "отсутствуют API-данные для подписанного запроса"
                logger.error("%s: отсутствуют API-данные для подписанного запроса", self.name)
                return None
            params.setdefault("recvWindow", 5000)
            params["timestamp"] = int(time.time() * 1000) + self.time_offset
            params = self._sign_params(params)

        request_kwargs = {"timeout": self.timeout}
        if method in {"GET", "DELETE"}:
            request_kwargs["params"] = params
        else:
            # Binance expects form-encoded payload for signed trade requests.
            request_kwargs["data"] = params

        try:
            response = self.session.request(method, url, **request_kwargs)
        except requests.RequestException as exc:
            self._last_api_error = f"{endpoint}: СЃРµС‚СЊ ({exc})"
            logger.error("Binance %s %s ошибка сети: %s", method, endpoint, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        if response.ok:
            self._last_api_error = ""
            return payload

        error_code = None
        error_msg = ""
        if isinstance(payload, dict):
            error_code = payload.get("code")
            error_msg = str(payload.get("msg") or "").strip()
        elif payload is not None:
            error_msg = str(payload)

        # Binance can reject signed requests due to local clock drift.
        # Retry once after server-time sync.
        if signed and str(error_code) == "-1021" and not _retried_after_time_sync:
            self.time_offset = self._get_server_time_offset()
            return self._request(
                method,
                endpoint,
                signed=signed,
                params=source_params,
                _retried_after_time_sync=True,
            )

        if error_msg:
            if error_code is not None:
                self._last_api_error = f"{endpoint}: [{error_code}] {error_msg}"
            else:
                self._last_api_error = f"{endpoint}: {error_msg}"
        else:
            self._last_api_error = f"{endpoint}: HTTP {response.status_code}"

        logger.error("Binance %s %s ошибка %s: %s", method, endpoint, response.status_code, payload)
        return None

    def _fetch_balance(self):
        account = self._request("GET", "/fapi/v2/account", signed=True)
        if account is None:
            return None
        if "assets" not in account:
            return None

        total = 0.0
        for asset in account["assets"]:
            if asset.get("asset") in {"USDT", "BUSD", "USDC"}:
                total += self._to_float(asset.get("walletBalance"))
        return total

    def _fetch_positions(self):
        positions = self._request("GET", "/fapi/v3/positionRisk", signed=True)
        if positions is None:
            return None
        if not positions:
            return []

        open_positions = []
        for pos in positions:
            size = self._to_float(pos.get("positionAmt"))
            if size == 0:
                continue
            open_positions.append(
                {
                    "symbol": pos.get("symbol", ""),
                    "size": size,
                    "entry_price": self._to_float(pos.get("entryPrice")),
                    "mark_price": self._to_float(pos.get("markPrice")),
                    "pnl": self._to_float(pos.get("unRealizedProfit")),
                }
            )
        return open_positions

    def connect(self):
        logger.info("%s попытка подключения...", self.name)

        if not self.api_key or not self.api_secret:
            msg = "Для Binance нужны API ключ и API секрет"
            self.last_error = msg
            self._emit_error(msg)
            logger.error("%s: %s", self.name, msg)
            return False

        self.time_offset = self._get_server_time_offset()
        if self._request("GET", "/fapi/v1/time") is None:
            msg = "Binance недоступна или нет сети"
            self.last_error = msg
            self._emit_error(msg)
            return False

        balance = self._fetch_balance()
        positions = self._fetch_positions()
        if balance is None or positions is None:
            msg = "Ошибка авторизации Binance"
            self.last_error = msg
            self._emit_error(msg)
            return False

        self.last_error = ""
        self.balance = balance
        self.positions = positions
        self.pnl = sum(pos.get("pnl", 0.0) for pos in positions)
        self.is_connected = True

        self._emit_connected()
        self._emit_balance_updated()
        self._emit_positions_updated()
        self._emit_pnl_updated()
        logger.info("%s подключена", self.name)
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
        url = f"{self.rest_url}/fapi/v1/exchangeInfo"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("%s: Binance не удалось получить список пар: %s", self.name, exc)
            return super().get_trading_pairs(limit=limit)

        pairs = []
        seen = set()
        for row in payload.get("symbols") or []:
            status = str(row.get("status", "")).upper()
            if status and status != "TRADING":
                continue

            symbol = self._normalize_symbol(row.get("symbol"))
            if not symbol or symbol in seen:
                continue

            seen.add(symbol)
            pairs.append(symbol)

        if pairs:
            self.symbols = list(pairs)
            limit_value = max(1, int(limit or 1))
            return pairs[:limit_value]
        return super().get_trading_pairs(limit=limit)

    @staticmethod
    def _round_up_to_step(value, step):
        if step <= 0:
            return value
        units = value / step
        rounded = math.ceil(units - 1e-12) * step
        return rounded

    @staticmethod
    def _qty_to_str(value):
        text = f"{float(value):.16f}".rstrip("0").rstrip(".")
        return text if text else "0"

    @staticmethod
    def _step_precision(step):
        if step <= 0:
            return -1
        text = f"{float(step):.16f}".rstrip("0").rstrip(".")
        if "." not in text:
            return 0
        return len(text.split(".", 1)[1])

    def _format_to_step(self, value, step):
        precision = self._step_precision(step)
        if precision < 0:
            return self._qty_to_str(value)
        if precision == 0:
            return str(int(round(float(value))))
        text = f"{float(value):.{precision}f}"
        text = text.rstrip("0").rstrip(".")
        return text if text else "0"

    @staticmethod
    def _round_to_step(value, step):
        if step <= 0:
            return value
        units = value / step
        rounded = round(units) * step
        return rounded

    def _extract_filter_value(self, filters, filter_type, field):
        for f in filters or []:
            if str(f.get("filterType", "")).upper() == str(filter_type).upper():
                return f.get(field)
        return None

    def _is_dual_side_mode(self):
        payload = self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
        if not isinstance(payload, dict):
            return False
        raw = payload.get("dualSidePosition")
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() == "true"
        return bool(raw)

    def open_min_test_position(self, symbol, direction):
        # TEMP: spread-tab market-entry check for order-book validation.
        if not self.is_connected:
            raise RuntimeError("Binance: Р±РёСЂР¶Р° РЅРµ РїРѕРґРєР»СЋС‡РµРЅР°")

        side = str(direction or "").strip().lower()
        if side not in {"buy", "sell"}:
            raise RuntimeError("Binance: РЅРµРІРµСЂРЅРѕРµ РЅР°РїСЂР°РІР»РµРЅРёРµ РѕСЂРґРµСЂР°")

        normalized_symbol = self._normalize_symbol(symbol)
        if not normalized_symbol:
            raise RuntimeError("Binance: РЅРµ СѓРєР°Р·Р°РЅР° С‚РѕСЂРіРѕРІР°СЏ РїР°СЂР°")

        exchange_info = self._request("GET", "/fapi/v1/exchangeInfo", signed=False)
        if not isinstance(exchange_info, dict):
            raise RuntimeError("Binance: РЅРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РїР°СЂР°РјРµС‚СЂС‹ РёРЅСЃС‚СЂСѓРјРµРЅС‚Р°")

        symbol_info = None
        for row in exchange_info.get("symbols") or []:
            row_symbol = self._normalize_symbol(row.get("symbol"))
            if row_symbol == normalized_symbol:
                symbol_info = row
                break
        if symbol_info is None:
            raise RuntimeError(f"Binance: РёРЅСЃС‚СЂСѓРјРµРЅС‚ {normalized_symbol} РЅРµ РЅР°Р№РґРµРЅ")

        status = str(symbol_info.get("status", "")).upper()
        if status and status != "TRADING":
            raise RuntimeError(f"Binance: РёРЅСЃС‚СЂСѓРјРµРЅС‚ {normalized_symbol} РЅРµРґРѕСЃС‚СѓРїРµРЅ РґР»СЏ С‚РѕСЂРіРѕРІР»Рё")

        filters = symbol_info.get("filters") or []
        lot_min = self._to_float(
            self._extract_filter_value(filters, "MARKET_LOT_SIZE", "minQty"),
            default=0.0,
        )
        lot_step = self._to_float(
            self._extract_filter_value(filters, "MARKET_LOT_SIZE", "stepSize"),
            default=0.0,
        )
        if lot_min <= 0:
            lot_min = self._to_float(
                self._extract_filter_value(filters, "LOT_SIZE", "minQty"),
                default=0.0,
            )
        if lot_step <= 0:
            lot_step = self._to_float(
                self._extract_filter_value(filters, "LOT_SIZE", "stepSize"),
                default=0.0,
            )
        lot_max = self._to_float(
            self._extract_filter_value(filters, "MARKET_LOT_SIZE", "maxQty"),
            default=0.0,
        )
        if lot_max <= 0:
            lot_max = self._to_float(
                self._extract_filter_value(filters, "LOT_SIZE", "maxQty"),
                default=0.0,
            )

        min_notional = self._to_float(
            self._extract_filter_value(filters, "MIN_NOTIONAL", "notional"),
            default=0.0,
        )
        price_tick = self._to_float(
            self._extract_filter_value(filters, "PRICE_FILTER", "tickSize"),
            default=0.0,
        )

        qty = lot_min if lot_min > 0 else lot_step
        if qty <= 0:
            raise RuntimeError(f"Binance: РЅРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ РјРёРЅРёРјР°Р»СЊРЅС‹Р№ РѕР±СЉРµРј РґР»СЏ {normalized_symbol}")

        ticker = self._request(
            "GET",
            "/fapi/v1/ticker/bookTicker",
            signed=False,
            params={"symbol": normalized_symbol},
        )
        price = None
        if isinstance(ticker, dict):
            price_field = "askPrice" if side == "buy" else "bidPrice"
            price = self._to_float(ticker.get(price_field), default=0.0)
            if price <= 0:
                price = self._to_float(ticker.get("price"), default=0.0)
        if not price or price <= 0:
            raise RuntimeError("Binance: РЅРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ Р»СѓС‡С€СѓСЋ С†РµРЅСѓ РґР»СЏ LIMIT РѕСЂРґРµСЂР°")
        if price_tick > 0:
            price = self._round_to_step(price, price_tick)
        if not price or price <= 0:
            raise RuntimeError("Binance: СЂР°СЃСЃС‡РёС‚Р°РЅРЅР°СЏ С†РµРЅР° LIMIT РѕСЂРґРµСЂР° РЅРµРєРѕСЂСЂРµРєС‚РЅР°")

        if min_notional > 0 and price and price > 0:
            notional_qty = min_notional / price
            qty = max(qty, notional_qty)

        if lot_step > 0:
            qty = self._round_up_to_step(qty, lot_step)
        if lot_max > 0 and qty > lot_max:
            raise RuntimeError("Binance: РјРёРЅРёРјР°Р»СЊРЅС‹Р№ С‚РµСЃС‚РѕРІС‹Р№ РѕР±СЉРµРј РїСЂРµРІС‹С€Р°РµС‚ РґРѕРїСѓСЃС‚РёРјС‹Р№ РјР°РєСЃРёРјСѓРј")

        qty_str = self._format_to_step(qty, lot_step)
        price_str = self._format_to_step(price, price_tick)
        params = {
            "symbol": normalized_symbol,
            "side": "BUY" if side == "buy" else "SELL",
            "type": "LIMIT",
            "timeInForce": "GTC",
            "price": price_str,
            "quantity": qty_str,
            "newOrderRespType": "RESULT",
        }

        if self._is_dual_side_mode():
            params["positionSide"] = "LONG" if side == "buy" else "SHORT"

        response = self._request("POST", "/fapi/v1/order", signed=True, params=params)
        if response is None:
            details = str(self._last_api_error or "").strip()
            if details:
                raise RuntimeError(f"Binance: РЅРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РєСЂС‹С‚СЊ С‚РµСЃС‚РѕРІСѓСЋ РїРѕР·РёС†РёСЋ ({details})")
            raise RuntimeError("Binance: РЅРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РєСЂС‹С‚СЊ С‚РµСЃС‚РѕРІСѓСЋ РїРѕР·РёС†РёСЋ")

        order_id = response.get("orderId")
        order_status = str(response.get("status") or "").upper()
        executed_qty = self._to_float(response.get("executedQty"), default=0.0)
        avg_price = self._to_float(response.get("avgPrice"), default=0.0)

        # Fast confirm for UI: short polling to catch FILLED right after submit.
        if order_id is not None and order_status != "FILLED":
            for _ in range(5):
                time.sleep(0.12)
                order_state = self._request(
                    "GET",
                    "/fapi/v1/order",
                    signed=True,
                    params={"symbol": normalized_symbol, "orderId": order_id},
                )
                if not isinstance(order_state, dict):
                    continue

                status_candidate = str(order_state.get("status") or "").upper()
                if status_candidate:
                    order_status = status_candidate
                executed_qty = self._to_float(order_state.get("executedQty"), default=executed_qty)
                avg_price = self._to_float(order_state.get("avgPrice"), default=avg_price)
                if order_status == "FILLED":
                    break

        executed_qty_str = qty_str
        if executed_qty and executed_qty > 0:
            executed_qty_str = self._qty_to_str(executed_qty)

        return {
            "symbol": normalized_symbol,
            "side": side,
            "quantity": qty_str,
            "executed_qty": executed_qty_str,
            "status": order_status or "UNKNOWN",
            "avg_price": avg_price,
            "order_type": "LIMIT",
            "limit_price": price_str,
            "order_id": order_id,
        }

    def close_all_positions(self):
        if not self.is_connected:
            return 0

        payload = self._request("GET", "/fapi/v3/positionRisk", signed=True)
        if payload is None:
            raise RuntimeError("Binance: РЅРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РїРѕР·РёС†РёРё РґР»СЏ Р·Р°РєСЂС‹С‚РёСЏ")

        positions = []
        for row in payload:
            amount = self._to_float(row.get("positionAmt"))
            if amount == 0:
                continue
            positions.append(
                {
                    "symbol": row.get("symbol", ""),
                    "amount": amount,
                    "position_side": str(row.get("positionSide", "BOTH") or "BOTH"),
                }
            )

        if not positions:
            self.positions = []
            self.pnl = 0.0
            self._emit_positions_updated()
            self._emit_pnl_updated()
            return 0

        failed = []
        for pos in positions:
            amount = float(pos["amount"])
            qty = f"{abs(amount):.12f}".rstrip("0").rstrip(".")
            if not qty:
                continue

            order_params = {
                "symbol": pos["symbol"],
                "side": "SELL" if amount > 0 else "BUY",
                "type": "MARKET",
                "quantity": qty,
                "reduceOnly": "true",
            }
            if pos["position_side"] and pos["position_side"] != "BOTH":
                order_params["positionSide"] = pos["position_side"]

            response = self._request("POST", "/fapi/v1/order", signed=True, params=order_params)
            if response is None:
                failed.append(pos["symbol"])

        balance = self._fetch_balance()
        positions_after = self._fetch_positions()
        if balance is not None:
            self.balance = balance
            self._emit_balance_updated()
        if positions_after is not None:
            self.positions = positions_after
            self.pnl = sum(pos.get("pnl", 0.0) for pos in positions_after)
            self._emit_positions_updated()
            self._emit_pnl_updated()

        if failed:
            raise RuntimeError(f"Binance: РЅРµ Р·Р°РєСЂС‹С‚С‹ РїРѕР·РёС†РёРё {', '.join(sorted(set(failed)))}")

        return len(positions)

