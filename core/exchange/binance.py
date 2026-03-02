import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests

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
        if api_key:
            self.session.headers.update({"X-MBX-APIKEY": api_key})
        self.time_offset = self._get_server_time_offset()

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

    def _request(self, method, endpoint, signed=False, params=None):
        method = method.upper()
        params = dict(params or {})
        url = f"{self.rest_url}{endpoint}"

        if signed:
            if not self.api_key or not self.api_secret:
                logger.error("%s: отсутствуют API credentials для signed-запроса", self.name)
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
            logger.error("Binance %s %s ошибка сети: %s", method, endpoint, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        if response.ok:
            return payload

        logger.error("Binance %s %s ошибка %s: %s", method, endpoint, response.status_code, payload)
        return None

    def _fetch_balance(self):
        account = self._request("GET", "/fapi/v2/account", signed=True)
        if not account or "assets" not in account:
            return 0.0

        total = 0.0
        for asset in account["assets"]:
            if asset.get("asset") in {"USDT", "BUSD", "USDC"}:
                total += self._to_float(asset.get("walletBalance"))
        return total

    def _fetch_positions(self):
        positions = self._request("GET", "/fapi/v3/positionRisk", signed=True)
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
            msg = "API Key и API Secret обязательны для Binance"
            self.error.emit(self.name, msg)
            logger.error("%s: %s", self.name, msg)
            return False

        self.time_offset = self._get_server_time_offset()
        if self._request("GET", "/fapi/v1/time") is None:
            self.error.emit(self.name, "Binance недоступна или нет сети")
            return False

        balance = self._fetch_balance()
        positions = self._fetch_positions()

        # If private calls fail, balance stays 0 and positions empty.
        self.balance = balance
        self.positions = positions
        self.pnl = sum(pos.get("pnl", 0.0) for pos in positions)
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
