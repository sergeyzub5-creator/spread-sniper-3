"""Binance helpers used by spread-sniping feature.

This module keeps exchange-specific spread logic outside UI layer.
"""


def _normalize_symbol(value):
    text = str(value or "").strip().upper()
    if not text:
        return ""
    for ch in ("/", "-", "_", " "):
        text = text.replace(ch, "")
    return text


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_depth_levels(rows, limit=3):
    levels = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = _to_float(row[0])
        qty = _to_float(row[1])
        if price is None or qty is None or price <= 0 or qty <= 0:
            continue
        levels.append({"price": price, "qty": qty})
        if len(levels) >= int(limit or 1):
            break
    return levels


def load_spread_account_pairs(exchange):
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return []

    account = request("GET", "/fapi/v2/account", signed=True)
    if not isinstance(account, dict):
        return []
    if account.get("canTrade") is False:
        return []

    allowed_symbols = set()
    for row in account.get("positions") or []:
        symbol = _normalize_symbol(row.get("symbol"))
        if symbol:
            allowed_symbols.add(symbol)

    brackets = request("GET", "/fapi/v1/leverageBracket", signed=True)
    if isinstance(brackets, list):
        for item in brackets:
            symbol = _normalize_symbol(item.get("symbol"))
            if symbol:
                allowed_symbols.add(symbol)

    # Strict account-specific behavior: pairs source must be signed/account-derived.
    if not allowed_symbols:
        return []

    exchange_info = request("GET", "/fapi/v1/exchangeInfo", signed=False)
    if not isinstance(exchange_info, dict):
        return []

    pairs = []
    seen = set()
    for row in exchange_info.get("symbols") or []:
        status = str(row.get("status", "")).upper()
        if status and status != "TRADING":
            continue

        symbol = _normalize_symbol(row.get("symbol"))
        if not symbol or symbol in seen:
            continue

        if symbol not in allowed_symbols:
            continue

        seen.add(symbol)
        pairs.append(symbol)

    return pairs


def fetch_spread_book_ticker_snapshot(exchange, pair):
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return None

    symbol = _normalize_symbol(pair)
    if not symbol:
        return None

    payload = request("GET", "/fapi/v1/ticker/bookTicker", signed=False, params={"symbol": symbol})
    if not isinstance(payload, dict):
        return None

    bid = _to_float(payload.get("bidPrice"))
    ask = _to_float(payload.get("askPrice"))
    if bid is None or ask is None:
        return None

    return {
        "symbol": _normalize_symbol(payload.get("symbol") or symbol),
        "bid": bid,
        "ask": ask,
    }


def fetch_spread_order_book_snapshot(exchange, pair, levels=3):
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return None

    symbol = _normalize_symbol(pair)
    if not symbol:
        return None

    level_limit = max(3, int(levels or 3))
    payload = request(
        "GET",
        "/fapi/v1/depth",
        signed=False,
        params={"symbol": symbol, "limit": 5},
    )
    if not isinstance(payload, dict):
        return None

    bids = _parse_depth_levels(payload.get("bids"), limit=level_limit)
    asks = _parse_depth_levels(payload.get("asks"), limit=level_limit)
    if not bids and not asks:
        return None

    return {
        "symbol": _normalize_symbol(payload.get("symbol") or symbol),
        "bids": bids[:level_limit],
        "asks": asks[:level_limit],
        "event_time": payload.get("E"),
    }
