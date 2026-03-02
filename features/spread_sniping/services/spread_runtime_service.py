from core.exchange.adapters.binance import (
    fetch_spread_book_ticker_snapshot as fetch_binance_book_ticker_snapshot,
    load_spread_account_pairs as load_binance_account_pairs,
)
from core.exchange.adapters.bitget import (
    fetch_spread_book_ticker_snapshot as fetch_bitget_book_ticker_snapshot,
    load_spread_account_pairs as load_bitget_account_pairs,
)
from core.exchange.catalog import normalize_exchange_code


class SpreadRuntimeService:
    """Business logic for spread-sniping tab (without UI dependencies)."""

    _SPREAD_ADAPTERS = {
        "binance": {
            "load_pairs": load_binance_account_pairs,
            "fetch_quote": fetch_binance_book_ticker_snapshot,
            "strict": True,
        },
        "bitget": {
            "load_pairs": load_bitget_account_pairs,
            "fetch_quote": fetch_bitget_book_ticker_snapshot,
            "strict": True,
        },
    }

    def __init__(self, exchange_manager, popular_pairs):
        self.exchange_manager = exchange_manager
        self._popular_pairs = tuple(popular_pairs or ())

    @staticmethod
    def _normalize_pair(value):
        text = str(value or "").strip().upper()
        if not text:
            return ""
        for ch in ("/", "-", "_", " "):
            text = text.replace(ch, "")
        return text

    def _normalize_pairs(self, pairs):
        result = []
        seen = set()
        for raw in pairs or []:
            symbol = self._normalize_pair(raw)
            if symbol and symbol not in seen:
                seen.add(symbol)
                result.append(symbol)
        return result

    def _get_exchange(self, exchange_name):
        if not exchange_name:
            return None
        return self.exchange_manager.get_exchange(exchange_name)

    def _get_adapter(self, exchange):
        if exchange is None:
            return None
        exchange_type = normalize_exchange_code(getattr(exchange, "exchange_type", None))
        return self._SPREAD_ADAPTERS.get(exchange_type)

    def is_pairs_source_strict(self, exchange_name):
        exchange = self._get_exchange(exchange_name)
        adapter = self._get_adapter(exchange)
        if not isinstance(adapter, dict):
            return False
        return bool(adapter.get("strict", False))

    def load_pairs(self, exchange_name):
        exchange = self._get_exchange(exchange_name)
        if exchange is None:
            return {"pairs": [], "strict": False}

        adapter = self._get_adapter(exchange)
        if isinstance(adapter, dict):
            load_fn = adapter.get("load_pairs")
            strict = bool(adapter.get("strict", False))
            pairs = []
            if callable(load_fn):
                try:
                    pairs = self._normalize_pairs(load_fn(exchange))
                except Exception:
                    pairs = []
            return {"pairs": pairs, "strict": strict, "refreshable": strict and not bool(pairs)}

        getter = getattr(exchange, "get_trading_pairs", None)
        if callable(getter):
            try:
                pairs = getter(limit=1200)
            except Exception:
                pairs = []
        else:
            pairs = []

        normalized = self._normalize_pairs(pairs)
        if normalized:
            return {"pairs": normalized, "strict": False}

        fallback = []
        for pos in exchange.positions or []:
            symbol = self._normalize_pair(pos.get("symbol"))
            if symbol and symbol not in fallback:
                fallback.append(symbol)
        for symbol in self._popular_pairs:
            if symbol not in fallback:
                fallback.append(symbol)
        return {"pairs": fallback, "strict": False}

    def fetch_quote_snapshot(self, exchange_name, pair):
        exchange = self._get_exchange(exchange_name)
        if exchange is None:
            return None

        adapter = self._get_adapter(exchange)
        if isinstance(adapter, dict):
            fetch_fn = adapter.get("fetch_quote")
            if callable(fetch_fn):
                try:
                    return fetch_fn(exchange, pair)
                except Exception:
                    return None
        return None
