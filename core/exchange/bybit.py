import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests

from core.exchange.base import BaseExchange
from core.utils.logger import get_logger

logger = get_logger(__name__)


class BybitExchange(BaseExchange):
    exchange_type = "bybit"

    def __init__(self, name, api_key=None, api_secret=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)
        self.base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
        self.recv_window = "5000"
        self.timeout = 10
        self.session = requests.Session()

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _sign(self, timestamp, query_string):
        payload = f"{timestamp}{self.api_key}{self.recv_window}{query_string}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(self, method, path, params=None, signed=False):
        method = method.upper()
        params = dict(params or {})
        url = f"{self.base_url}{path}"

        headers = {}
        query_string = urlencode(sorted(params.items()), doseq=True)

        if signed:
            if not self.api_key or not self.api_secret:
                logger.error("%s: отсутствуют API-данные", self.name)
                return None

            timestamp = str(int(time.time() * 1000))
            headers.update(
                {
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-TIMESTAMP": timestamp,
                    "X-BAPI-RECV-WINDOW": self.recv_window,
                    "X-BAPI-SIGN-TYPE": "2",
                    "X-BAPI-SIGN": self._sign(timestamp, query_string),
                }
            )

        request_kwargs = {
            "params": params if method == "GET" else None,
            "timeout": self.timeout,
            "headers": headers,
        }

        try:
            response = self.session.request(method, url, **request_kwargs)
        except requests.RequestException as exc:
            logger.error("Bybit %s %s ошибка запроса: %s", method, path, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        if response.ok and payload.get("retCode") == 0:
            return payload

        logger.error(
            "Bybit %s %s ошибка %s: %s",
            method,
            path,
            response.status_code,
            payload,
        )
        return None

    def _fetch_balance(self):
        payload = self._request(
            "GET",
            "/v5/account/wallet-balance",
            params={"accountType": "UNIFIED"},
            signed=True,
        )
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

            positions.append(
                {
                    "symbol": row.get("symbol", ""),
                    "size": size,
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

        market = self._request("GET", "/v5/market/time")
        if not market:
            self._emit_error("Bybit недоступна")
            return False

        balance = self._fetch_balance()
        positions = self._fetch_positions()
        if balance is None or positions is None:
            self._emit_error("Ошибка авторизации Bybit")
            return False

        self.balance = balance
        self.positions = positions
        self.pnl = sum(pos.get("pnl", 0.0) for pos in self.positions)
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


