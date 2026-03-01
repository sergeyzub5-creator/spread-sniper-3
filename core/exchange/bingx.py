import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests

from core.exchange.base import BaseExchange
from core.utils.logger import get_logger

logger = get_logger(__name__)


class BingXExchange(BaseExchange):
    exchange_type = "bingx"

    def __init__(self, name, api_key=None, api_secret=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)
        self.base_url = "https://open-api-vst.bingx.com" if testnet else "https://open-api.bingx.com"
        self.timeout = 10
        self.session = requests.Session()

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _sign(self, params):
        # BingX: sort all parameters by key, build query string, HMAC-SHA256 hex.
        query = urlencode(sorted(params.items()), doseq=True)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return query, signature

    def _request(self, method, path, params=None, signed=False):
        method = method.upper()
        params = dict(params or {})
        headers = {}

        if signed:
            if not self.api_key or not self.api_secret:
                logger.error("%s: отсутствуют API-данные BingX", self.name)
                return None

            params.setdefault("timestamp", int(time.time() * 1000))
            params.setdefault("recvWindow", 5000)
            _, signature = self._sign(params)
            params["signature"] = signature
            headers["X-BX-APIKEY"] = self.api_key

        request_kwargs = {"params": params, "headers": headers, "timeout": self.timeout}

        try:
            response = self.session.request(method, f"{self.base_url}{path}", **request_kwargs)
        except requests.RequestException as exc:
            logger.error("BingX %s %s ошибка запроса: %s", method, path, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        if response.ok and str(payload.get("code")) in {"0", "200"}:
            return payload

        logger.error(
            "BingX %s %s ошибка %s: %s",
            method,
            path,
            response.status_code,
            payload,
        )
        return None

    def _fetch_balance(self):
        payload = self._request("GET", "/openApi/cswap/v1/user/balance", signed=True)
        if not payload:
            return None

        rows = payload.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("list") or rows.get("result") or []

        total = 0.0
        for row in rows:
            asset = str(row.get("asset", row.get("currency", ""))).upper()
            if asset in {"USDT", "USDC", "USD"}:
                total += self._to_float(row.get("equity", row.get("balance")))
        return total

    def _fetch_positions(self):
        payload = self._request("GET", "/openApi/cswap/v1/user/positions", signed=True)
        if not payload:
            return None

        rows = payload.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("list") or rows.get("positions") or []

        positions = []
        for row in rows:
            size = self._to_float(row.get("positionAmt", row.get("holdVol")))
            if size == 0:
                continue

            side = str(row.get("positionSide", "")).lower()
            if side == "short":
                size = -abs(size)

            positions.append(
                {
                    "symbol": row.get("symbol", ""),
                    "size": size,
                    "entry_price": self._to_float(row.get("avgPrice", row.get("openAvgPrice"))),
                    "mark_price": self._to_float(row.get("markPrice", row.get("holdAvgPrice"))),
                    "pnl": self._to_float(row.get("unrealizedProfit", row.get("unrealisedProfit"))),
                }
            )
        return positions

    def connect(self):
        logger.info("%s запрос на подключение", self.name)

        if not self.api_key or not self.api_secret:
            msg = "Для BingX нужны API ключ и API секрет"
            self.error.emit(self.name, msg)
            logger.error("%s: %s", self.name, msg)
            return False

        contracts = self._request("GET", "/openApi/cswap/v1/market/contracts")
        if contracts is None:
            self.error.emit(self.name, "BingX недоступна")
            return False

        balance = self._fetch_balance()
        positions = self._fetch_positions()
        if balance is None or positions is None:
            self.error.emit(self.name, "Ошибка авторизации BingX")
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

