import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests

from core.exchange.base import BaseExchange
from core.utils.logger import get_logger

logger = get_logger(__name__)


class MEXCExchange(BaseExchange):
    exchange_type = "mexc"

    def __init__(self, name, api_key=None, api_secret=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)
        self.base_url = "https://contract.mexc.com"
        self.timeout = 10
        self.session = requests.Session()

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _build_signature(self, timestamp_ms, params):
        # MEXC Futures v1: sign(accessKey + reqTime + sorted_query)
        sorted_query = urlencode(sorted(params.items()), doseq=True)
        target = f"{self.api_key}{timestamp_ms}{sorted_query}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            target.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(self, method, path, params=None, signed=False):
        method = method.upper()
        params = dict(params or {})

        headers = {"Content-Type": "application/json"}
        if signed:
            if not self.api_key or not self.api_secret:
                logger.error("%s: отсутствуют API-данные MEXC", self.name)
                return None

            timestamp_ms = str(int(time.time() * 1000))
            headers.update(
                {
                    "ApiKey": self.api_key,
                    "Request-Time": timestamp_ms,
                    "Signature": self._build_signature(timestamp_ms, params),
                }
            )

        request_kwargs = {"headers": headers, "timeout": self.timeout}
        if method == "GET":
            request_kwargs["params"] = params

        try:
            response = self.session.request(method, f"{self.base_url}{path}", **request_kwargs)
        except requests.RequestException as exc:
            logger.error("MEXC %s %s ошибка запроса: %s", method, path, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        success = payload.get("success")
        code = payload.get("code")
        if response.ok and (success is True or str(code) in {"0", "200"}):
            return payload

        logger.error(
            "MEXC %s %s ошибка %s: %s",
            method,
            path,
            response.status_code,
            payload,
        )
        return None

    def _fetch_balance(self):
        payload = self._request("GET", "/api/v1/private/account/assets", signed=True)
        if not payload:
            return None

        data = payload.get("data")
        if isinstance(data, dict):
            assets = data.get("assets") or data.get("list") or []
        elif isinstance(data, list):
            assets = data
        else:
            assets = []

        total = 0.0
        for row in assets:
            currency = str(row.get("currency", row.get("asset", ""))).upper()
            if currency in {"USDT", "USDC", "USD"}:
                # Prefer available+position margin if both exist, otherwise fallback.
                available = self._to_float(row.get("availableBalance", row.get("available")))
                position_margin = self._to_float(row.get("positionMargin", row.get("frozenBalance")))
                equity = self._to_float(row.get("equity", row.get("balance")))
                total += equity if equity > 0 else available + position_margin
        return total

    def _fetch_positions(self):
        payload = self._request("GET", "/api/v1/private/position/open_positions", signed=True)
        if not payload:
            return None

        data = payload.get("data")
        if isinstance(data, dict):
            rows = data.get("list") or data.get("rows") or []
        elif isinstance(data, list):
            rows = data
        else:
            rows = []

        positions = []
        for row in rows:
            size = self._to_float(row.get("holdVol", row.get("positionAmt")))
            if size == 0:
                continue

            # 1 long, 2 short in MEXC futures v1 payloads.
            position_type = int(self._to_float(row.get("positionType"), default=0))
            if position_type == 2:
                size = -abs(size)

            positions.append(
                {
                    "symbol": row.get("symbol", ""),
                    "size": size,
                    "entry_price": self._to_float(row.get("openAvgPrice", row.get("avgPrice"))),
                    "mark_price": self._to_float(row.get("holdAvgPrice", row.get("markPrice"))),
                    "pnl": self._to_float(row.get("unrealizedProfit", row.get("profit"))),
                }
            )
        return positions

    def connect(self):
        logger.info("%s запрос на подключение", self.name)

        if not self.api_key or not self.api_secret:
            msg = "Для MEXC нужны API ключ и API секрет"
            self._emit_error(msg)
            logger.error("%s: %s", self.name, msg)
            return False

        ping = self._request("GET", "/api/v1/contract/ping")
        if not ping:
            self._emit_error("MEXC недоступна")
            return False

        balance = self._fetch_balance()
        positions = self._fetch_positions()
        if balance is None or positions is None:
            self._emit_error("Ошибка авторизации MEXC")
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


