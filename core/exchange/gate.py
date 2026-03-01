import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import requests

from core.exchange.base import BaseExchange
from core.utils.logger import get_logger

logger = get_logger(__name__)


class GateExchange(BaseExchange):
    exchange_type = "gate"

    def __init__(self, name, api_key=None, api_secret=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)
        self.base_url = "https://fx-api-testnet.gateio.ws" if testnet else "https://api.gateio.ws"
        self.timeout = 10
        self.session = requests.Session()
        self.settle = "usdt"

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sha512_hex(text):
        return hashlib.sha512(text.encode("utf-8")).hexdigest()

    def _sign(self, method, path, query_string, body_text, timestamp):
        sign_payload = f"{method}\n{path}\n{query_string}\n{self._sha512_hex(body_text)}\n{timestamp}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            sign_payload.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()

    def _request(self, method, path, params=None, signed=False):
        method = method.upper()
        params = dict(params or {})

        query_string = urlencode(params, doseq=True) if method == "GET" and params else ""
        body_text = ""
        if method in {"POST", "PUT"}:
            body_text = json.dumps(params, separators=(",", ":"))

        headers = {"Content-Type": "application/json"}
        if signed:
            if not self.api_key or not self.api_secret:
                logger.error("%s: missing Gate credentials", self.name)
                return None

            timestamp = str(int(time.time()))
            headers.update(
                {
                    "KEY": self.api_key,
                    "Timestamp": timestamp,
                    "SIGN": self._sign(method, path, query_string, body_text, timestamp),
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
            logger.error("Gate %s %s request failed: %s", method, path, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        if response.ok:
            return payload

        logger.error(
            "Gate %s %s error %s: %s",
            method,
            path,
            response.status_code,
            payload,
        )
        return None

    def _fetch_balance(self):
        payload = self._request(
            "GET",
            f"/api/v4/futures/{self.settle}/accounts",
            signed=True,
        )
        if not payload:
            return None

        # Gate futures account object.
        return self._to_float(payload.get("total", payload.get("available")))

    def _fetch_positions(self):
        payload = self._request(
            "GET",
            f"/api/v4/futures/{self.settle}/positions",
            signed=True,
        )
        if not payload or not isinstance(payload, list):
            return None

        positions = []
        for row in payload:
            size = self._to_float(row.get("size"))
            if size == 0:
                continue

            positions.append(
                {
                    "symbol": row.get("contract", ""),
                    "size": size,
                    "entry_price": self._to_float(row.get("entry_price")),
                    "mark_price": self._to_float(row.get("mark_price")),
                    "pnl": self._to_float(row.get("unrealised_pnl", row.get("unrealized_pnl"))),
                }
            )
        return positions

    def connect(self):
        logger.info("%s connect requested", self.name)

        if not self.api_key or not self.api_secret:
            msg = "Gate requires API key and API secret"
            self.error.emit(self.name, msg)
            logger.error("%s: %s", self.name, msg)
            return False

        contracts = self._request("GET", f"/api/v4/futures/{self.settle}/contracts")
        if contracts is None:
            self.error.emit(self.name, "Gate is unavailable")
            return False

        balance = self._fetch_balance()
        positions = self._fetch_positions()
        if balance is None or positions is None:
            self.error.emit(self.name, "Gate authentication failed")
            return False

        self.balance = balance
        self.positions = positions
        self.pnl = sum(pos.get("pnl", 0.0) for pos in self.positions)
        self.is_connected = True

        self.connected.emit(self.name)
        self.balance_updated.emit(self.name, self.balance)
        self.positions_updated.emit(self.name, self.positions)
        self.pnl_updated.emit(self.name, self.pnl)
        logger.info("%s connected", self.name)
        return True

    def disconnect(self):
        self.is_connected = False
        self.disconnected.emit(self.name)
        logger.info("%s disconnected", self.name)

    def subscribe_price(self, symbol):
        logger.info("%s subscribe %s", self.name, symbol)

    def unsubscribe_price(self, symbol):
        logger.info("%s unsubscribe %s", self.name, symbol)
