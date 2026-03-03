"""Bitget helpers used by spread-sniping feature.

This module keeps exchange-specific spread logic outside UI layer.
"""
import math
import time

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


def _attach_timing(payload, started_ts, ack_ts=None, done_ts=None):
    data = dict(payload or {})
    end_ts = float(done_ts if done_ts is not None else time.monotonic())
    ack_value = float(ack_ts if ack_ts is not None else end_ts)
    send_ack = max(0.0, ack_value - float(started_ts))
    ack_fill = max(0.0, end_ts - ack_value)
    total = max(0.0, end_ts - float(started_ts))
    data["timing_send_ack_sec"] = float(send_ack)
    data["timing_ack_fill_sec"] = float(ack_fill)
    data["timing_total_sec"] = float(total)
    return data


def _last_error_text(exchange):
    return str(getattr(exchange, "_last_api_error", "") or "").strip()


def _is_no_position_error(error_text):
    text = str(error_text or "").strip().lower()
    if not text:
        return False
    return ("22002" in text) or ("no position to close" in text)


def _build_no_position_reduce_result(exchange, symbol, side, requested_qty):
    return {
        "ok": True,
        "skipped": "no_position",
        "exchange": str(getattr(exchange, "name", "") or "bitget"),
        "symbol": symbol,
        "side": str(side or "").strip().lower(),
        "reduce_only": True,
        "status": "NO_POSITION",
        "requested_qty": float(requested_qty or 0.0),
        "executed_qty": 0.0,
    }


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


def _round_down_to_step(value, step):
    if step is None or step <= 0:
        return float(value)
    units = math.floor((float(value) / float(step)) + 1e-12)
    return units * float(step)


def _round_price_to_tick(value, tick, side):
    if tick is None or tick <= 0:
        return float(value)
    ratio = float(value) / float(tick)
    if str(side).lower() == "buy":
        units = math.ceil(ratio - 1e-12)
    else:
        units = math.floor(ratio + 1e-12)
    return units * float(tick)


def _step_precision(step):
    if step is None or step <= 0:
        return -1
    text = f"{float(step):.16f}".rstrip("0").rstrip(".")
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1])


def _format_to_step(value, step):
    precision = _step_precision(step)
    if precision < 0:
        text = f"{float(value):.16f}"
    elif precision == 0:
        text = f"{int(round(float(value)))}"
    else:
        text = f"{float(value):.{precision}f}"
    text = text.rstrip("0").rstrip(".")
    return text if text else "0"


def _resolve_price_tick(contract_row):
    row = contract_row if isinstance(contract_row, dict) else {}
    price_place = row.get("pricePlace")
    price_end_step = row.get("priceEndStep")
    try:
        place = int(price_place)
    except (TypeError, ValueError):
        place = None
    end_step = _to_float(price_end_step)
    if place is None or place < 0:
        return end_step if end_step and end_step > 0 else None
    if end_step is None or end_step <= 0:
        end_step = 1.0
    return float(end_step) * (10.0 ** (-place))


def _load_contract_info(exchange, request, symbol, preferred_product_type, ttl_sec=45.0):
    now = time.monotonic()
    cache = getattr(exchange, "_spread_bitget_contract_cache", None)
    normalized_symbol = _normalize_symbol(symbol)
    if isinstance(cache, dict):
        cached_until = float(cache.get("until") or 0.0)
        symbols = cache.get("symbols")
        if cached_until > now and isinstance(symbols, dict):
            item = symbols.get(normalized_symbol)
            if isinstance(item, dict):
                return item.get("product_type"), item.get("contract")

    symbols = {}
    for product_type in _merge_product_types(preferred_product_type):
        contracts = request(
            "GET",
            "/api/v2/mix/market/contracts",
            params={"productType": product_type},
            signed=False,
        )
        if not isinstance(contracts, dict):
            continue
        for row in contracts.get("data") or []:
            row_symbol = _normalize_symbol(row.get("symbol"))
            if not row_symbol:
                continue
            symbols[row_symbol] = {"product_type": product_type, "contract": row}

    setattr(
        exchange,
        "_spread_bitget_contract_cache",
        {"until": now + float(max(5.0, ttl_sec)), "symbols": symbols},
    )
    item = symbols.get(normalized_symbol)
    if isinstance(item, dict):
        return item.get("product_type"), item.get("contract")
    return None, None


def get_spread_qty_constraints(exchange, pair):
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return None

    symbol = _normalize_symbol(pair)
    if not symbol:
        return None

    preferred_product_type = str(getattr(exchange, "product_type", "USDT-FUTURES") or "USDT-FUTURES")
    _product_type, contract = _load_contract_info(exchange, request, symbol, preferred_product_type)
    if not isinstance(contract, dict):
        return None

    qty_step = _to_float(contract.get("sizeMultiplier"))
    min_qty = _to_float(contract.get("minTradeNum"))
    max_qty = _to_float(contract.get("maxTradeNum"))

    if qty_step is None or qty_step <= 0:
        qty_step = min_qty
    if min_qty is None or min_qty <= 0:
        min_qty = qty_step
    if qty_step is None or qty_step <= 0:
        return None

    return {
        "exchange": str(getattr(exchange, "name", "") or "bitget"),
        "symbol": symbol,
        "qty_step": float(qty_step),
        "min_qty": float(min_qty or qty_step),
        "max_qty": float(max_qty) if (max_qty is not None and max_qty > 0) else None,
    }


def _is_hedge_mode(request, symbol, product_type, margin_coin):
    payload = request(
        "GET",
        "/api/v2/mix/account/account",
        params={
            "symbol": symbol,
            "productType": product_type,
            "marginCoin": margin_coin,
        },
        signed=True,
    )
    if not isinstance(payload, dict):
        return False
    data = payload.get("data") or {}
    mode = str(data.get("posMode") or data.get("positionMode") or "").strip().lower()
    return mode in {"hedge_mode", "hedge", "double_hold"}


def _is_hedge_mode_cached(exchange, request, symbol, product_type, margin_coin, ttl_sec=8.0):
    now = time.monotonic()
    cache = getattr(exchange, "_spread_bitget_hedge_mode_cache", None)
    cache_key = (
        _normalize_symbol(symbol),
        str(product_type or "").strip().upper(),
        _normalize_margin_coin(margin_coin),
    )
    if isinstance(cache, dict):
        item = cache.get(cache_key)
        if isinstance(item, dict) and float(item.get("until") or 0.0) > now:
            return bool(item.get("mode"))
    mode = _is_hedge_mode(request, symbol, product_type, margin_coin)
    if not isinstance(cache, dict):
        cache = {}
    cache[cache_key] = {"until": now + float(max(1.0, ttl_sec)), "mode": bool(mode)}
    setattr(exchange, "_spread_bitget_hedge_mode_cache", cache)
    return bool(mode)


def _query_order_state(request, symbol, product_type, order_id):
    if not order_id:
        return {}
    for attempt in range(2):
        payload = request(
            "GET",
            "/api/v2/mix/order/detail",
            params={
                "symbol": symbol,
                "productType": product_type,
                "orderId": str(order_id),
            },
            signed=True,
        )
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict) and data:
                status = _extract_order_status(data, "")
                if status in {"FILLED", "FULL_FILL", "SUCCESS", "CANCELED", "CANCELLED", "REJECTED", "FAILED"}:
                    return data
                return data
        if attempt == 0:
            time.sleep(0.06)
    return {}


def _extract_filled_qty(order_data, fallback):
    for key in ("baseVolume", "filledQty", "filledSize", "size", "accBaseVolume"):
        value = _to_float((order_data or {}).get(key))
        if value is not None and value > 0:
            return value
    return float(fallback or 0.0)


def _extract_order_status(order_data, fallback):
    status = str((order_data or {}).get("state") or (order_data or {}).get("status") or "").strip()
    if status:
        return status.upper()
    return str(fallback or "UNKNOWN").upper()


def _fetch_reduce_closeable_qty(request, symbol, product_type, margin_coin, side):
    payload = request(
        "GET",
        "/api/v2/mix/position/all-position",
        params={"productType": product_type, "marginCoin": margin_coin},
        signed=True,
    )
    if not isinstance(payload, dict):
        return 0.0
    rows = payload.get("data") or []
    direction = str(side or "").strip().lower()
    close_long = direction == "sell"
    close_short = direction == "buy"
    total = 0.0
    for row in rows:
        if _normalize_symbol(row.get("symbol")) != symbol:
            continue
        hold_side = str(row.get("holdSide") or "").strip().lower()
        qty = _to_float(row.get("total"))
        if qty is None:
            continue
        qty_abs = abs(float(qty))
        if close_long and hold_side == "long":
            total += qty_abs
        elif close_short and hold_side == "short":
            total += qty_abs
    return max(0.0, float(total))


def place_spread_limit_fok_order(
    exchange,
    pair,
    side,
    qty,
    max_slippage_pct=0.02,
    reduce_only=False,
    best_price_hint=None,
):
    started_ts = time.monotonic()
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return _attach_timing({"ok": False, "error": "request_unavailable"}, started_ts)

    if not bool(getattr(exchange, "is_connected", False)):
        return _attach_timing({"ok": False, "error": "exchange_not_connected"}, started_ts)

    symbol = _normalize_symbol(pair)
    direction = str(side or "").strip().lower()
    requested_qty = _to_float(qty)
    if not symbol:
        return _attach_timing({"ok": False, "error": "invalid_symbol"}, started_ts)
    if direction not in {"buy", "sell"}:
        return _attach_timing({"ok": False, "error": "invalid_side"}, started_ts)
    if requested_qty is None or requested_qty <= 0:
        return _attach_timing({"ok": False, "error": "invalid_qty"}, started_ts)

    preferred_product_type = str(getattr(exchange, "product_type", "USDT-FUTURES") or "USDT-FUTURES")
    product_type, contract = _load_contract_info(exchange, request, symbol, preferred_product_type)
    if not product_type or not isinstance(contract, dict):
        return _attach_timing({"ok": False, "error": "symbol_not_found"}, started_ts)

    status = str(contract.get("symbolStatus") or contract.get("status") or "").strip().lower()
    if status and status not in _CONTRACT_ACTIVE_STATUSES:
        return _attach_timing({"ok": False, "error": "symbol_not_trading", "status": status}, started_ts)

    qty_step = _to_float(contract.get("sizeMultiplier"))
    min_qty = _to_float(contract.get("minTradeNum"))
    if qty_step is None or qty_step <= 0:
        qty_step = min_qty

    aligned_qty = _round_down_to_step(requested_qty, qty_step or 0.0)
    margin_coin = str(contract.get("quoteCoin") or "USDT").upper()
    if bool(reduce_only):
        closeable_qty = _fetch_reduce_closeable_qty(
            request=request,
            symbol=symbol,
            product_type=product_type,
            margin_coin=margin_coin,
            side=direction,
        )
        if closeable_qty <= 1e-12:
            return _attach_timing(_build_no_position_reduce_result(exchange, symbol, direction, aligned_qty), started_ts)
        aligned_qty = min(aligned_qty, _round_down_to_step(closeable_qty, qty_step or 0.0))

    if min_qty is not None and min_qty > 0 and aligned_qty < min_qty:
        if bool(reduce_only):
            return _attach_timing({
                "ok": True,
                "skipped": "position_below_min_qty",
                "exchange": str(getattr(exchange, "name", "") or "bitget"),
                "symbol": symbol,
                "side": direction,
                "reduce_only": True,
                "status": "NO_POSITION",
                "requested_qty": float(aligned_qty),
                "executed_qty": 0.0,
            }, started_ts)
        return _attach_timing({
            "ok": False,
            "error": "qty_below_min",
            "requested_qty": requested_qty,
            "aligned_qty": aligned_qty,
            "min_qty": min_qty,
        }, started_ts)
    if aligned_qty <= 0:
        return _attach_timing({"ok": False, "error": "qty_rounds_to_zero"}, started_ts)

    best_price = _to_float(best_price_hint)
    if best_price is None or best_price <= 0:
        ticker = request(
            "GET",
            "/api/v2/mix/market/ticker",
            params={"symbol": symbol, "productType": product_type},
            signed=False,
        )
        if not isinstance(ticker, dict):
            return _attach_timing({"ok": False, "error": "book_ticker_unavailable"}, started_ts)

        ticker_row = None
        rows = ticker.get("data") or []
        if rows and isinstance(rows[0], dict):
            ticker_row = rows[0]
        if not isinstance(ticker_row, dict):
            return _attach_timing({"ok": False, "error": "book_ticker_unavailable"}, started_ts)
        best_price = _to_float(ticker_row.get("askPr" if direction == "buy" else "bidPr"))
    if best_price is None or best_price <= 0:
        return _attach_timing({"ok": False, "error": "invalid_best_price"}, started_ts)

    slippage_ratio = max(0.0, float(_to_float(max_slippage_pct) or 0.0)) / 100.0
    if direction == "buy":
        raw_limit_price = best_price * (1.0 + slippage_ratio)
    else:
        raw_limit_price = best_price * (1.0 - slippage_ratio)

    price_tick = _resolve_price_tick(contract)
    limit_price = _round_price_to_tick(raw_limit_price, price_tick or 0.0, direction)
    if limit_price <= 0:
        return _attach_timing({"ok": False, "error": "invalid_limit_price"}, started_ts)

    qty_text = _format_to_step(aligned_qty, qty_step or 0.0)
    price_text = _format_to_step(limit_price, price_tick or 0.0)

    params = {
        "symbol": symbol,
        "productType": product_type,
        "marginMode": "crossed",
        "marginCoin": margin_coin,
        "side": direction,
        "orderType": "limit",
        "force": "ioc",
        "size": qty_text,
        "price": price_text,
    }

    hedge_mode = _is_hedge_mode_cached(exchange, request, symbol, product_type, margin_coin)
    if hedge_mode:
        params["tradeSide"] = "close" if bool(reduce_only) else "open"
    elif bool(reduce_only):
        params["reduceOnly"] = "YES"

    response = request(
        "POST",
        "/api/v2/mix/order/place-order",
        params=params,
        signed=True,
        retry_attempts=1,
        retryable_codes=(),
        retry_delay_sec=0.0,
    )
    ack_ts = time.monotonic()
    if not isinstance(response, dict):
        details = _last_error_text(exchange)
        if bool(reduce_only) and _is_no_position_error(details):
            alt_direction = "sell" if direction == "buy" else "buy"
            retry_params = dict(params)
            retry_params["side"] = alt_direction
            retry_response = request(
                "POST",
                "/api/v2/mix/order/place-order",
                params=retry_params,
                signed=True,
                retry_attempts=1,
                retryable_codes=(),
                retry_delay_sec=0.0,
            )
            if isinstance(retry_response, dict):
                response = retry_response
                direction = alt_direction
            else:
                retry_details = _last_error_text(exchange)
                if _is_no_position_error(retry_details):
                    return _attach_timing(_build_no_position_reduce_result(exchange, symbol, direction, aligned_qty), started_ts, ack_ts=ack_ts)
                details = retry_details or details
                return _attach_timing({"ok": False, "error": "order_submit_failed", "details": details}, started_ts, ack_ts=ack_ts)
        else:
            return _attach_timing({"ok": False, "error": "order_submit_failed", "details": details}, started_ts, ack_ts=ack_ts)

    payload = response.get("data") if isinstance(response.get("data"), dict) else {}
    order_id = payload.get("orderId") or payload.get("ordId")
    payload_status = _extract_order_status(payload, payload.get("status"))
    if payload_status in {"FILLED", "FULL_FILL", "SUCCESS", "CANCELED", "CANCELLED", "REJECTED", "FAILED"}:
        order_state = payload
    else:
        order_state = _query_order_state(request, symbol, product_type, order_id)
        if not isinstance(order_state, dict) or not order_state:
            order_state = payload
    order_status = _extract_order_status(order_state, payload_status)
    executed_qty = _extract_filled_qty(order_state, fallback=0.0)
    if executed_qty <= 0 and order_status in {"FILLED", "FULL_FILL", "SUCCESS"}:
        executed_qty = float(aligned_qty)

    if executed_qty <= 0:
        return _attach_timing({
            "ok": False,
            "error": "order_not_filled",
            "status": order_status or "UNKNOWN",
            "order_id": order_id,
            "requested_qty": float(aligned_qty),
        }, started_ts, ack_ts=ack_ts)

    avg_price = _to_float(order_state.get("priceAvg")) or _to_float(order_state.get("avgPrice"))
    if avg_price is None or avg_price <= 0:
        avg_price = limit_price

    return _attach_timing({
        "ok": True,
        "exchange": str(getattr(exchange, "name", "") or "bitget"),
        "symbol": symbol,
        "side": direction,
        "reduce_only": bool(reduce_only),
        "status": order_status or "UNKNOWN",
        "order_id": order_id,
        "requested_qty": float(aligned_qty),
        "executed_qty": float(executed_qty),
        "avg_price": float(avg_price),
        "limit_price": float(limit_price),
    }, started_ts, ack_ts=ack_ts)


def place_spread_market_reduce_order(exchange, pair, side, qty):
    started_ts = time.monotonic()
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return _attach_timing({"ok": False, "error": "request_unavailable"}, started_ts)

    if not bool(getattr(exchange, "is_connected", False)):
        return _attach_timing({"ok": False, "error": "exchange_not_connected"}, started_ts)

    symbol = _normalize_symbol(pair)
    direction = str(side or "").strip().lower()
    requested_qty = _to_float(qty)
    if not symbol:
        return _attach_timing({"ok": False, "error": "invalid_symbol"}, started_ts)
    if direction not in {"buy", "sell"}:
        return _attach_timing({"ok": False, "error": "invalid_side"}, started_ts)
    if requested_qty is None or requested_qty <= 0:
        return _attach_timing({"ok": False, "error": "invalid_qty"}, started_ts)

    preferred_product_type = str(getattr(exchange, "product_type", "USDT-FUTURES") or "USDT-FUTURES")
    product_type, contract = _load_contract_info(exchange, request, symbol, preferred_product_type)
    if not product_type or not isinstance(contract, dict):
        return _attach_timing({"ok": False, "error": "symbol_not_found"}, started_ts)

    qty_step = _to_float(contract.get("sizeMultiplier"))
    min_qty = _to_float(contract.get("minTradeNum"))
    if qty_step is None or qty_step <= 0:
        qty_step = min_qty

    aligned_qty = _round_down_to_step(requested_qty, qty_step or 0.0)
    margin_coin = str(contract.get("quoteCoin") or "USDT").upper()
    closeable_qty = _fetch_reduce_closeable_qty(
        request=request,
        symbol=symbol,
        product_type=product_type,
        margin_coin=margin_coin,
        side=direction,
    )
    if closeable_qty <= 1e-12:
        return _attach_timing(_build_no_position_reduce_result(exchange, symbol, direction, aligned_qty), started_ts)
    aligned_qty = min(aligned_qty, _round_down_to_step(closeable_qty, qty_step or 0.0))

    if min_qty is not None and min_qty > 0 and aligned_qty < min_qty:
        return _attach_timing({
            "ok": True,
            "skipped": "position_below_min_qty",
            "exchange": str(getattr(exchange, "name", "") or "bitget"),
            "symbol": symbol,
            "side": direction,
            "reduce_only": True,
            "status": "NO_POSITION",
            "requested_qty": requested_qty,
            "aligned_qty": aligned_qty,
            "min_qty": min_qty,
            "executed_qty": 0.0,
        }, started_ts)
    if aligned_qty <= 0:
        return _attach_timing({"ok": False, "error": "qty_rounds_to_zero"}, started_ts)

    params = {
        "symbol": symbol,
        "productType": product_type,
        "marginMode": "crossed",
        "marginCoin": margin_coin,
        "side": direction,
        "orderType": "market",
        "size": _format_to_step(aligned_qty, qty_step or 0.0),
    }
    hedge_mode = _is_hedge_mode_cached(exchange, request, symbol, product_type, margin_coin)
    if hedge_mode:
        params["tradeSide"] = "close"
    else:
        params["reduceOnly"] = "YES"

    response = request(
        "POST",
        "/api/v2/mix/order/place-order",
        params=params,
        signed=True,
        retry_attempts=1,
        retryable_codes=(),
        retry_delay_sec=0.0,
    )
    ack_ts = time.monotonic()
    if not isinstance(response, dict):
        details = _last_error_text(exchange)
        if _is_no_position_error(details):
            alt_direction = "sell" if direction == "buy" else "buy"
            retry_params = dict(params)
            retry_params["side"] = alt_direction
            retry_response = request(
                "POST",
                "/api/v2/mix/order/place-order",
                params=retry_params,
                signed=True,
                retry_attempts=1,
                retryable_codes=(),
                retry_delay_sec=0.0,
            )
            if isinstance(retry_response, dict):
                response = retry_response
                direction = alt_direction
            else:
                retry_details = _last_error_text(exchange)
                if _is_no_position_error(retry_details):
                    return _attach_timing(_build_no_position_reduce_result(exchange, symbol, direction, aligned_qty), started_ts, ack_ts=ack_ts)
                details = retry_details or details
                return _attach_timing({"ok": False, "error": "order_submit_failed", "details": details}, started_ts, ack_ts=ack_ts)
        else:
            return _attach_timing({"ok": False, "error": "order_submit_failed", "details": details}, started_ts, ack_ts=ack_ts)

    payload = response.get("data") if isinstance(response.get("data"), dict) else {}
    order_id = payload.get("orderId") or payload.get("ordId")
    payload_status = _extract_order_status(payload, payload.get("status"))
    if payload_status in {"FILLED", "FULL_FILL", "SUCCESS", "CANCELED", "CANCELLED", "REJECTED", "FAILED"}:
        order_state = payload
    else:
        order_state = _query_order_state(request, symbol, product_type, order_id)
        if not isinstance(order_state, dict) or not order_state:
            order_state = payload
    order_status = _extract_order_status(order_state, payload_status)
    executed_qty = _extract_filled_qty(order_state, fallback=0.0)
    if executed_qty <= 0 and order_status in {"FILLED", "FULL_FILL", "SUCCESS"}:
        executed_qty = float(aligned_qty)

    if executed_qty <= 0:
        return _attach_timing({
            "ok": False,
            "error": "order_not_filled",
            "status": order_status or "UNKNOWN",
            "order_id": order_id,
            "requested_qty": float(aligned_qty),
        }, started_ts, ack_ts=ack_ts)

    avg_price = _to_float(order_state.get("priceAvg")) or _to_float(order_state.get("avgPrice"))
    if avg_price is None:
        avg_price = 0.0

    return _attach_timing({
        "ok": True,
        "exchange": str(getattr(exchange, "name", "") or "bitget"),
        "symbol": symbol,
        "side": direction,
        "reduce_only": True,
        "status": order_status or "UNKNOWN",
        "order_id": order_id,
        "requested_qty": float(aligned_qty),
        "executed_qty": float(executed_qty),
        "avg_price": float(avg_price),
    }, started_ts, ack_ts=ack_ts)
