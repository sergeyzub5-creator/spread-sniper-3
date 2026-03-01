import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

from core.exchange.base import BaseExchange
from core.utils.logger import get_logger

logger = get_logger(__name__)


class OKXExchange(BaseExchange):
    exchange_type = "okx"

    def __init__(self, name, api_key=None, api_secret=None, api_passphrase=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)
        self.api_passphrase = api_passphrase
        self.base_url = "https://www.okx.com"
        self.timeout = 10
        self.session = requests.Session()

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _timestamp_iso():
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _sign(self, timestamp, method, request_path, body_text):
        message = f"{timestamp}{method}{request_path}{body_text}"
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
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

        headers = {"Content-Type": "application/json"}
        if self.testnet:
            headers["x-simulated-trading"] = "1"

        if signed:
            if not self.api_key or not self.api_secret or not self.api_passphrase:
                logger.error("%s: отсутствуют API-данные OKX", self.name)
                return None

            timestamp = self._timestamp_iso()
            headers.update(
                {
                    "OK-ACCESS-KEY": self.api_key,
                    "OK-ACCESS-SIGN": self._sign(timestamp, method, request_path, body_text),
                    "OK-ACCESS-TIMESTAMP": timestamp,
                    "OK-ACCESS-PASSPHRASE": self.api_passphrase,
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
            logger.error("OKX %s %s ошибка запроса: %s", method, path, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        if response.ok and payload.get("code") == "0":
            return payload

        logger.error(
            "OKX %s %s ошибка %s: %s",
            method,
            path,
            response.status_code,
            payload,
        )
        return None

    def _fetch_balance(self):
        payload = self._request(
            "GET",
            "/api/v5/account/balance",
            params={"ccy": "USDT"},
            signed=True,
        )
        if not payload:
            return None

        rows = payload.get("data") or []
        if not rows:
            return 0.0

        details = rows[0].get("details") or []
        if details:
            for item in details:
                if str(item.get("ccy", "")).upper() == "USDT":
                    # Prefer equity when available.
                    return self._to_float(item.get("eq", item.get("cashBal")))

        return self._to_float(rows[0].get("totalEq"))

    def _fetch_positions(self):
        payload = self._request(
            "GET",
            "/api/v5/account/positions",
            params={"instType": "SWAP"},
            signed=True,
        )
        if not payload:
            return None

        positions = []
        for row in payload.get("data") or []:
            size = self._to_float(row.get("pos"))
            if size == 0:
                continue

            side = str(row.get("posSide", "")).lower()
            if side == "short" and size > 0:
                size = -size

            positions.append(
                {
                    "symbol": row.get("instId", ""),
                    "size": size,
                    "entry_price": self._to_float(row.get("avgPx")),
                    "mark_price": self._to_float(row.get("markPx")),
                    "pnl": self._to_float(row.get("upl")),
                }
            )
        return positions

    def connect(self):
        logger.info("%s запрос на подключение", self.name)

        if not self.api_key or not self.api_secret or not self.api_passphrase:
            msg = "Для OKX нужны API ключ, API секрет и пароль API"
            self.error.emit(self.name, msg)
            logger.error("%s: %s", self.name, msg)
            return False

        public_time = self._request("GET", "/api/v5/public/time")
        if not public_time:
            self.error.emit(self.name, "OKX недоступна")
            return False

        balance = self._fetch_balance()
        positions = self._fetch_positions()
        if balance is None or positions is None:
            self.error.emit(self.name, "Ошибка авторизации OKX")
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

