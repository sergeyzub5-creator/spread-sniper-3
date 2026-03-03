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


class KuCoinExchange(BaseExchange):
    exchange_type = "kucoin"

    def __init__(self, name, api_key=None, api_secret=None, api_passphrase=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)
        self.api_passphrase = api_passphrase
        self.base_url = "https://api-sandbox-futures.kucoin.com" if testnet else "https://api-futures.kucoin.com"
        self.timeout = 10
        self.session = requests.Session()

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _sign(self, text):
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            text.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _signed_passphrase(self):
        return self._sign(self.api_passphrase)

    def _request(self, method, path, params=None, signed=False):
        method = method.upper()
        params = dict(params or {})

        query = urlencode(params, doseq=True) if method == "GET" and params else ""
        request_path = f"{path}?{query}" if query else path
        body_text = ""
        if method in {"POST", "PUT"}:
            body_text = json.dumps(params, separators=(",", ":"))

        headers = {"Content-Type": "application/json"}
        if signed:
            if not self.api_key or not self.api_secret or not self.api_passphrase:
                logger.error("%s: отсутствуют API-данные KuCoin", self.name)
                return None

            timestamp_ms = str(int(time.time() * 1000))
            pre_hash = f"{timestamp_ms}{method}{request_path}{body_text}"
            headers.update(
                {
                    "KC-API-KEY": self.api_key,
                    "KC-API-SIGN": self._sign(pre_hash),
                    "KC-API-TIMESTAMP": timestamp_ms,
                    "KC-API-PASSPHRASE": self._signed_passphrase(),
                    "KC-API-KEY-VERSION": "2",
                }
            )

        request_kwargs = {"headers": headers, "timeout": self.timeout}
        if method == "GET":
            request_kwargs["params"] = params
        elif method in {"POST", "PUT"}:
            request_kwargs["data"] = body_text

        try:
            response = self.session.request(method, f"{self.base_url}{path}", **request_kwargs)
        except requests.RequestException as exc:
            logger.error("KuCoin %s %s ошибка запроса: %s", method, path, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        if response.ok and payload.get("code") == "200000":
            return payload

        logger.error(
            "KuCoin %s %s ошибка %s: %s",
            method,
            path,
            response.status_code,
            payload,
        )
        return None

    def _fetch_balance(self):
        payload = self._request(
            "GET",
            "/api/v1/account-overview",
            params={"currency": "USDT"},
            signed=True,
        )
        if not payload:
            return None

        data = payload.get("data") or {}
        # accountEquity is futures equity in selected currency.
        return self._to_float(data.get("accountEquity", data.get("availableBalance")))

    def _fetch_positions(self):
        payload = self._request("GET", "/api/v1/positions", signed=True)
        if not payload:
            return None

        rows = payload.get("data") or []
        positions = []
        for row in rows:
            size = self._to_float(row.get("currentQty", row.get("positionQty")))
            if size == 0:
                continue

            positions.append(
                {
                    "symbol": row.get("symbol", ""),
                    "size": size,
                    "entry_price": self._to_float(row.get("avgEntryPrice", row.get("entryPrice"))),
                    "mark_price": self._to_float(row.get("markPrice")),
                    "pnl": self._to_float(row.get("unrealisedPnl", row.get("unrealizedPnl"))),
                }
            )
        return positions

    def connect(self):
        logger.info("%s запрос на подключение", self.name)

        if not self.api_key or not self.api_secret or not self.api_passphrase:
            msg = "Для KuCoin нужны API ключ, API секрет и пароль API"
            self._emit_error(msg)
            logger.error("%s: %s", self.name, msg)
            return False

        timestamp = self._request("GET", "/api/v1/timestamp")
        if not timestamp:
            self._emit_error("KuCoin недоступна")
            return False

        balance = self._fetch_balance()
        positions = self._fetch_positions()
        if balance is None or positions is None:
            self._emit_error("Ошибка авторизации KuCoin")
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


