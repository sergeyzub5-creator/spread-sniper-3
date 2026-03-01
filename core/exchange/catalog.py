from __future__ import annotations

from typing import Dict

from core.i18n import tr


EXCHANGE_ALIASES = {
    "kukoin": "kucoin",
    "gateio": "gate",
    "gate.io": "gate",
    "okex": "okx",
}


EXCHANGE_CATALOG: Dict[str, dict] = {
    "binance": {
        "code": "binance",
        "title": "Binance Futures",
        "base_name": "Binance",
        "short": "BN",
        "color": "#F3BA2F",
        "requires_passphrase": False,
    },
    "bitget": {
        "code": "bitget",
        "title": "Bitget Futures",
        "base_name": "Bitget",
        "short": "BG",
        "color": "#00C1D4",
        "requires_passphrase": True,
    },
    "bybit": {
        "code": "bybit",
        "title": "Bybit Futures",
        "base_name": "Bybit",
        "short": "BY",
        "color": "#F7A600",
        "requires_passphrase": False,
    },
    "okx": {
        "code": "okx",
        "title": "OKX Futures",
        "base_name": "OKX",
        "short": "OK",
        "color": "#111111",
        "requires_passphrase": True,
    },
    "mexc": {
        "code": "mexc",
        "title": "MEXC Futures",
        "base_name": "MEXC",
        "short": "MX",
        "color": "#2EC5B6",
        "requires_passphrase": False,
    },
    "kucoin": {
        "code": "kucoin",
        "title": "KuCoin Futures",
        "base_name": "KuCoin",
        "short": "KC",
        "color": "#1FC7A3",
        "requires_passphrase": True,
    },
    "gate": {
        "code": "gate",
        "title": "Gate Futures",
        "base_name": "Gate",
        "short": "GT",
        "color": "#2F54EB",
        "requires_passphrase": False,
    },
    "bingx": {
        "code": "bingx",
        "title": "BingX Futures",
        "base_name": "BingX",
        "short": "BX",
        "color": "#005BFF",
        "requires_passphrase": False,
    },
}


EXCHANGE_ORDER = [
    "binance",
    "bitget",
    "bybit",
    "okx",
    "mexc",
    "kucoin",
    "gate",
    "bingx",
]


def normalize_exchange_code(exchange_code: str | None) -> str:
    if not exchange_code:
        return "unknown"
    code = exchange_code.strip().lower()
    return EXCHANGE_ALIASES.get(code, code)


def get_exchange_meta(exchange_code: str | None) -> dict:
    code = normalize_exchange_code(exchange_code)
    if code in EXCHANGE_CATALOG:
        return dict(EXCHANGE_CATALOG[code])
    return {
        "code": code,
        "title": tr("exchange.unknown.title"),
        "base_name": tr("exchange.unknown.base_name"),
        "short": "EX",
        "color": "#6C7A89",
        "requires_passphrase": False,
    }


def is_known_exchange_type(exchange_code: str | None) -> bool:
    code = normalize_exchange_code(exchange_code)
    return code in EXCHANGE_CATALOG


def requires_passphrase(exchange_code: str | None) -> bool:
    return bool(get_exchange_meta(exchange_code).get("requires_passphrase", False))
