from core.exchange.binance import BinanceExchange
from core.exchange.bingx import BingXExchange
from core.exchange.bitget import BitgetExchange
from core.exchange.bybit import BybitExchange
from core.exchange.catalog import normalize_exchange_code
from core.exchange.gate import GateExchange
from core.exchange.kucoin import KuCoinExchange
from core.exchange.mexc import MEXCExchange
from core.exchange.okx import OKXExchange
from core.exchange.placeholder import PlaceholderExchange


def _base_params(params):
    return {
        "api_key": params.get("api_key"),
        "api_secret": params.get("api_secret"),
        "testnet": bool(params.get("testnet", False)),
    }


def _with_passphrase(params):
    payload = _base_params(params)
    if "api_passphrase" in params:
        payload["api_passphrase"] = params.get("api_passphrase")
    return payload


def create_exchange(name, exchange_type, params):
    params = dict(params or {})
    type_code = normalize_exchange_code(exchange_type)
    if type_code == "binance":
        return BinanceExchange(name, **_base_params(params))
    if type_code == "bitget":
        return BitgetExchange(name, **_with_passphrase(params))
    if type_code == "bybit":
        return BybitExchange(name, **_base_params(params))
    if type_code == "okx":
        return OKXExchange(name, **_with_passphrase(params))
    if type_code == "mexc":
        return MEXCExchange(name, **_base_params(params))
    if type_code == "kucoin":
        return KuCoinExchange(name, **_with_passphrase(params))
    if type_code == "gate":
        return GateExchange(name, **_base_params(params))
    if type_code == "bingx":
        return BingXExchange(name, **_base_params(params))
    return PlaceholderExchange(name, type_code, **_with_passphrase(params))
