import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter

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
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=0, pool_block=False)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._last_api_error = ""

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
            response = self.session.get(f"{self.base_url}/api/v2/public/time", timeout=self.timeout)
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

    def _request(
        self,
        method,
        path,
        params=None,
        signed=False,
        retry_attempts=None,
        retryable_codes=None,
        retry_delay_sec=0.20,
    ):
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
                self._last_api_error = f"{path}: отсутствуют API-данные для подписанного запроса Bitget"
                logger.error("%s: отсутствуют API-данные для подписанного запроса Bitget", self.name)
                return None

            if not self._is_latin1(self.api_key) or not self._is_latin1(self.api_passphrase):
                msg = "API ключ/пароль Bitget должны быть на латинице"
                self.last_error = msg
                self._last_api_error = f"{path}: {msg}"
                self._emit_error(msg)
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

        retryable = (
            {str(c).strip() for c in retryable_codes}
            if retryable_codes is not None
            else {"40010"}
        )
        try:
            attempts = int(retry_attempts) if retry_attempts is not None else 2
        except (TypeError, ValueError):
            attempts = 2
        attempts = max(1, attempts)
        try:
            retry_delay = max(0.0, float(retry_delay_sec))
        except (TypeError, ValueError):
            retry_delay = 0.20

        for attempt in range(attempts):
            try:
                response = self.session.request(method, url, **request_kwargs)
            except (requests.RequestException, UnicodeError, ValueError) as exc:
                self._last_api_error = f"{path}: сеть ({exc})"
                if attempt + 1 < attempts:
                    time.sleep(retry_delay)
                    continue
                logger.error("Bitget %s %s ошибка запроса: %s", method, path, exc)
                return None
            except Exception as exc:
                self._last_api_error = f"{path}: непредвиденная ошибка ({exc})"
                if attempt + 1 < attempts:
                    time.sleep(retry_delay)
                    continue
                logger.error("Bitget %s %s непредвиденная ошибка: %s", method, path, exc)
                return None

            try:
                payload = response.json()
            except ValueError:
                payload = {"raw": response.text}

            if response.ok and payload.get("code") == "00000":
                self._last_api_error = ""
                return payload

            code = ""
            message = ""
            if isinstance(payload, dict):
                code = str(payload.get("code") or "").strip()
                message = str(payload.get("msg") or "").strip()
            if code and message:
                self._last_api_error = f"{path}: [{code}] {message}"
            elif message:
                self._last_api_error = f"{path}: {message}"
            else:
                self._last_api_error = f"{path}: HTTP {response.status_code}"

            if code in retryable and attempt + 1 < attempts:
                time.sleep(retry_delay)
                continue

            if code == "22002":
                # Expected transient on reduce-close races; keep out of normal runtime noise.
                logger.debug("Bitget %s %s предупреждение %s: %s", method, path, response.status_code, payload)
            elif code in retryable:
                logger.warning("Bitget %s %s таймаут %s: %s", method, path, response.status_code, payload)
            else:
                logger.error("Bitget %s %s ошибка %s: %s", method, path, response.status_code, payload)
            return None

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
            self.last_error = msg
            self._emit_error(msg)
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
            msg = "Bitget недоступна или указан неверный тип продукта"
            self.last_error = msg
            self._emit_error(msg)
            return False

        balance = self._fetch_balance()
        positions = self._fetch_positions()
        if balance is None or positions is None:
            msg = "Ошибка авторизации Bitget"
            self.last_error = msg
            self._emit_error(msg)
            return False

        self.last_error = ""
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

    def get_trading_pairs(self, limit=400):
        url = f"{self.base_url}/api/v2/mix/market/contracts"
        params = {"productType": self.product_type}
        headers = {"Content-Type": "application/json"}
        if self.testnet:
            headers["paptrading"] = "1"

        try:
            response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("%s: Bitget не удалось получить список пар: %s", self.name, exc)
            return super().get_trading_pairs(limit=limit)

        if str(payload.get("code")) != "00000":
            logger.warning("%s: Bitget список пар вернул код %s", self.name, payload.get("code"))
            return super().get_trading_pairs(limit=limit)

        pairs = []
        seen = set()
        for row in payload.get("data") or []:
            status = str(row.get("symbolStatus") or row.get("status") or "").strip().lower()
            if status and status not in {"normal", "listed", "trading"}:
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

    def close_all_positions(self):
        if not self.is_connected:
            return 0

        positions = self._fetch_positions()
        if positions is None:
            raise RuntimeError("Bitget: РЅРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РїРѕР·РёС†РёРё РґР»СЏ Р·Р°РєСЂС‹С‚РёСЏ")

        if not positions:
            self.positions = []
            self.pnl = 0.0
            self._emit_positions_updated()
            self._emit_pnl_updated()
            return 0

        failed = []
        for pos in positions:
            symbol = str(pos.get("symbol", "") or "")
            if not symbol:
                continue
            hold_side = "long" if float(pos.get("size", 0.0)) > 0 else "short"
            payload = {
                "symbol": symbol,
                "productType": self.product_type,
                "holdSide": hold_side,
            }
            response = self._request("POST", "/api/v2/mix/order/close-positions", params=payload, signed=True)
            if response is None:
                failed.append(symbol)

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
            raise RuntimeError(f"Bitget: РЅРµ Р·Р°РєСЂС‹С‚С‹ РїРѕР·РёС†РёРё {', '.join(sorted(set(failed)))}")

        return len(positions)

