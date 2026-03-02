"""Bitget adapter helpers."""

from core.exchange.adapters.bitget.spread import (
    fetch_spread_book_ticker_snapshot,
    load_spread_account_pairs,
)

__all__ = [
    "load_spread_account_pairs",
    "fetch_spread_book_ticker_snapshot",
]
