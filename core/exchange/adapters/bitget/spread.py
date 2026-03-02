"""Bitget helpers used by spread-sniping feature.

This module keeps exchange-specific spread logic outside UI layer.
"""

_FUTURES_PRODUCT_TYPES = (
    "USDT-FUTURES",
    "COIN-FUTURES",
    "USDC-FUTURES",
)

_CONTRACT_ACTIVE_STATUSES = {"normal", "listed", "trading"}
_SPOT_ACTIVE_STATUSES = {"online", "normal", "listed", "trading"}


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


def _safe_split_csv(raw):
    text = str(raw or "").strip()
    if not text:
        return []
    return [part.strip().upper() for part in text.split(",") if part.strip()]


def _normalize_margin_coin(value):
    coin = str(value or "").strip().upper()
    if not coin:
        return ""
    # Bitget demo can expose synthetic margin-code variants.
    # Fallback to canonical form (e.g. SUSDT -> USDT) for matching.
    if coin.startswith("S") and len(coin) > 2:
        alt = coin[1:]
        if alt in {"USDT", "USDC", "BTC", "ETH"}:
            return alt
    return coin


def _merge_product_types(primary_type):
    ordered = []
    first = str(primary_type or "").strip().upper()
    if first:
        ordered.append(first)
    for item in _FUTURES_PRODUCT_TYPES:
        if item not in ordered:
            ordered.append(item)
    return ordered


def _add_symbol(seen, out, symbol_value):
    symbol = _normalize_symbol(symbol_value)
    if not symbol or symbol in seen:
        return False
    seen.add(symbol)
    out.append(symbol)
    return True


def load_spread_account_pairs(exchange):
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return []

    pairs = []
    seen = set()

    preferred_product_type = str(getattr(exchange, "product_type", "USDT-FUTURES") or "USDT-FUTURES")
    futures_account_ok = False

    for product_type in _merge_product_types(preferred_product_type):
        account = request(
            "GET",
            "/api/v2/mix/account/accounts",
            params={"productType": product_type},
            signed=True,
        )
        if not isinstance(account, dict):
            continue

        account_rows = account.get("data") or []
        if not account_rows:
            continue

        allowed_margin_coins = set()
        for row in account_rows:
            margin_coin = _normalize_margin_coin(row.get("marginCoin"))
            if margin_coin:
                allowed_margin_coins.add(margin_coin)
        if not allowed_margin_coins:
            continue

        contracts = request(
            "GET",
            "/api/v2/mix/market/contracts",
            params={"productType": product_type},
            signed=False,
        )
        if not isinstance(contracts, dict):
            continue

        futures_account_ok = True
        for row in contracts.get("data") or []:
            status = str(row.get("symbolStatus") or row.get("status") or "").strip().lower()
            if status and status not in _CONTRACT_ACTIVE_STATUSES:
                continue

            margin_coins = [_normalize_margin_coin(v) for v in _safe_split_csv(row.get("supportMarginCoins"))]
            if margin_coins and not (set(margin_coins) & allowed_margin_coins):
                continue

            _add_symbol(seen, pairs, row.get("symbol"))

    # Spot: include only if signed spot-account request succeeds for this API account.
    spot_account = request(
        "GET",
        "/api/v2/spot/account/assets",
        signed=True,
    )
    spot_account_ok = isinstance(spot_account, dict)
    if spot_account_ok:
        spot_symbols = request("GET", "/api/v2/spot/public/symbols", signed=False)
        if isinstance(spot_symbols, dict):
            for row in spot_symbols.get("data") or []:
                status = str(row.get("status") or "").strip().lower()
                if status and status not in _SPOT_ACTIVE_STATUSES:
                    continue
                _add_symbol(seen, pairs, row.get("symbol"))

    # If account-signed checks failed across all venues, return empty (strict account-specific behavior).
    if not futures_account_ok and not spot_account_ok:
        return []

    return pairs


def fetch_spread_book_ticker_snapshot(exchange, pair):
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return None

    symbol = _normalize_symbol(pair)
    if not symbol:
        return None

    preferred_product_type = str(getattr(exchange, "product_type", "USDT-FUTURES") or "USDT-FUTURES")
    for product_type in _merge_product_types(preferred_product_type):
        payload = request(
            "GET",
            "/api/v2/mix/market/ticker",
            params={"symbol": symbol, "productType": product_type},
            signed=False,
        )
        if not isinstance(payload, dict):
            continue

        rows = payload.get("data") or []
        row = rows[0] if rows and isinstance(rows[0], dict) else None
        if not isinstance(row, dict):
            continue

        bid = _to_float(row.get("bidPr"))
        ask = _to_float(row.get("askPr"))
        bid_qty = _to_float(row.get("bidSz"))
        ask_qty = _to_float(row.get("askSz"))
        if bid is None or ask is None:
            continue

        return {
            "symbol": _normalize_symbol(row.get("symbol") or row.get("instId") or symbol),
            "bid": bid,
            "ask": ask,
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "event_time": row.get("ts"),
            "market_type": product_type,
        }

    # Spot fallback.
    spot_payload = request(
        "GET",
        "/api/v2/spot/market/tickers",
        params={"symbol": symbol},
        signed=False,
    )
    if not isinstance(spot_payload, dict):
        return None

    spot_rows = spot_payload.get("data") or []
    row = spot_rows[0] if spot_rows and isinstance(spot_rows[0], dict) else None
    if not isinstance(row, dict):
        return None

    bid = _to_float(row.get("bidPr"))
    ask = _to_float(row.get("askPr"))
    bid_qty = _to_float(row.get("bidSz"))
    ask_qty = _to_float(row.get("askSz"))
    if bid is None or ask is None:
        return None

    return {
        "symbol": _normalize_symbol(row.get("symbol") or row.get("instId") or symbol),
        "bid": bid,
        "ask": ask,
        "bid_qty": bid_qty,
        "ask_qty": ask_qty,
        "event_time": row.get("ts"),
        "market_type": "SPOT",
    }
