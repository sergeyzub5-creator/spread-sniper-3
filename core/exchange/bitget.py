import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import requests

from core.exchange.base import BaseExchange
from core.utils.logger import get_logger

logger = get_logger(__name__)


class BitgetExchange(BaseExchange):
    exchange_type = "bitget"

    def __init__(self, name, api_key=None, api_secret=None, api_passphrase=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)
        self.api_passphrase = api_passphrase
        self.base_url = "https://api.bitget.com"
        self.timeout = 10
        self.product_type = "USDT-FUTURES"
        self.time_offset = 0
        self.session = requests.Session()

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_latin1(value):
        try:
            str(value).encode("latin-1")
            return True
        except UnicodeEncodeError:
            return False

    def _get_server_time_offset(self):
        try:
            response = requests.get(f"{self.base_url}/api/v2/public/time", timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != "00000":
                return 0
            server_ms = int(payload.get("data", {}).get("serverTime", 0))
            local_ms = int(time.time() * 1000)
            return server_ms - local_ms
        except (requests.RequestException, ValueError, TypeError):
            return 0

    def _build_signature(self, timestamp, method, request_path, body_text):
        pre_hash = f"{timestamp}{method.upper()}{request_path}{body_text}"
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            pre_hash.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _request(self, method, path, params=None, signed=False):
        method = method.upper()
        params = dict(params or {})

        query = urlencode(params, doseq=True) if method == "GET" and params else ""
        request_path = f"{path}?{query}" if query else path
        body_text = ""

        if method in {"POST", "PUT"}:
            body_text = json.dumps(params, separators=(",", ":"))

        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        if self.testnet:
            headers["paptrading"] = "1"

        if signed:
            if not self.api_key or not self.api_secret or not self.api_passphrase:
                logger.error("%s: отсутствуют API-данные для подписанного запроса Bitget", self.name)
                return None

            if not self._is_latin1(self.api_key) or not self._is_latin1(self.api_passphrase):
                self.error.emit(self.name, "API ключ/пароль Bitget должны быть на латинице")
                return None

            timestamp = str(int(time.time() * 1000) + self.time_offset)
            sign = self._build_signature(timestamp, method, request_path, body_text)
            headers.update(
                {
                    "ACCESS-KEY": self.api_key,
                    "ACCESS-SIGN": sign,
                    "ACCESS-PASSPHRASE": self.api_passphrase,
                    "ACCESS-TIMESTAMP": timestamp,
                    "locale": "en-US",
                }
            )

        request_kwargs = {"headers": headers, "timeout": self.timeout}
        if method == "GET":
            request_kwargs["params"] = params
        elif method in {"POST", "PUT"}:
            request_kwargs["data"] = body_text

        try:
            response = self.session.request(method, url, **request_kwargs)
        except (requests.RequestException, UnicodeError, ValueError) as exc:
            logger.error("Bitget %s %s ошибка запроса: %s", method, path, exc)
            return None
        except Exception as exc:
            logger.error("Bitget %s %s непредвиденная ошибка: %s", method, path, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        if response.ok and payload.get("code") == "00000":
            return payload

        logger.error("Bitget %s %s ошибка %s: %s", method, path, response.status_code, payload)
        return None

    def _fetch_balance(self):
        payload = self._request(
            "GET",
            "/api/v2/mix/account/accounts",
            params={"productType": self.product_type},
            signed=True,
        )
        if not payload:
            return None

        data = payload.get("data") or []
        if not data:
            return 0.0

        for row in data:
            margin_coin = str(row.get("marginCoin", "")).upper()
            if margin_coin == "USDT":
                return self._to_float(row.get("usdtEquity", row.get("accountEquity")))

        first = data[0]
        return self._to_float(first.get("usdtEquity", first.get("accountEquity")))

    def _fetch_positions(self):
        payload = self._request(
            "GET",
            "/api/v2/mix/position/all-position",
            params={"productType": self.product_type, "marginCoin": "USDT"},
            signed=True,
        )
        if not payload:
            return None

        positions = []
        for pos in payload.get("data") or []:
            size = self._to_float(pos.get("total"))
            if size == 0:
                continue

            hold_side = str(pos.get("holdSide", "")).lower()
            if hold_side == "short":
                size = -abs(size)

            positions.append(
                {
                    "symbol": pos.get("symbol", ""),
                    "size": size,
                    "entry_price": self._to_float(pos.get("openPriceAvg")),
                    "mark_price": self._to_float(pos.get("markPrice")),
                    "pnl": self._to_float(pos.get("unrealizedPL")),
                }
            )
        return positions

    def connect(self):
        logger.info("%s попытка подключения...", self.name)

        if not self.api_key or not self.api_secret or not self.api_passphrase:
            msg = "Для Bitget нужны API ключ, API секрет и пароль API"
            self.error.emit(self.name, msg)
            logger.error("%s: %s", self.name, msg)
            return False

        self.time_offset = self._get_server_time_offset()

        contracts = self._request(
            "GET",
            "/api/v2/mix/market/contracts",
            params={"productType": self.product_type},
            signed=False,
        )
        if not contracts:
            self.error.emit(self.name, "Bitget недоступна или указан неверный тип продукта")
            return False

        balance = self._fetch_balance()
        positions = self._fetch_positions()
        if balance is None or positions is None:
            self.error.emit(self.name, "Ошибка авторизации Bitget")
            return False

        self.balance = balance
        self.positions = positions
        self.pnl = sum(pos.get("pnl", 0.0) for pos in self.positions)
        self.is_connected = True

        self.connected.emit(self.name)
        self.balance_updated.emit(self.name, self.balance)
        self.positions_updated.emit(self.name, self.positions)
        self.pnl_updated.emit(self.name, self.pnl)
        logger.info("%s подключена", self.name)
        return True

    def disconnect(self):
        self.is_connected = False
        self.disconnected.emit(self.name)
        logger.info("%s отключена", self.name)

    def subscribe_price(self, symbol):
        logger.info("%s подписка на %s", self.name, symbol)

    def unsubscribe_price(self, symbol):
        logger.info("%s отписка от %s", self.name, symbol)

