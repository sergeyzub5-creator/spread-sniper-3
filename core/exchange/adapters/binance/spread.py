"""Binance helpers used by spread-sniping feature.

This module keeps exchange-specific spread logic outside UI layer.
"""
import math
import time


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


def _extract_filter_value(filters, filter_type, field):
    for row in filters or []:
        if str(row.get("filterType", "")).upper() == str(filter_type).upper():
            return row.get(field)
    return None


def get_spread_qty_constraints(exchange, pair):
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return None

    symbol = _normalize_symbol(pair)
    if not symbol:
        return None

    exchange_info = request("GET", "/fapi/v1/exchangeInfo", signed=False)
    if not isinstance(exchange_info, dict):
        return None

    symbol_info = None
    for row in exchange_info.get("symbols") or []:
        if _normalize_symbol(row.get("symbol")) == symbol:
            symbol_info = row
            break
    if not isinstance(symbol_info, dict):
        return None

    filters = symbol_info.get("filters") or []
    lot_step = _to_float(_extract_filter_value(filters, "LOT_SIZE", "stepSize"))
    lot_min = _to_float(_extract_filter_value(filters, "LOT_SIZE", "minQty"))
    lot_max = _to_float(_extract_filter_value(filters, "LOT_SIZE", "maxQty"))

    if lot_step is None or lot_step <= 0:
        lot_step = lot_min
    if lot_min is None or lot_min <= 0:
        lot_min = lot_step

    if lot_step is None or lot_step <= 0:
        return None

    return {
        "exchange": str(getattr(exchange, "name", "") or "binance"),
        "symbol": symbol,
        "qty_step": float(lot_step),
        "min_qty": float(lot_min or lot_step),
        "max_qty": float(lot_max) if (lot_max is not None and lot_max > 0) else None,
    }


def _resolve_min_notional(filters):
    value = _to_float(_extract_filter_value(filters, "NOTIONAL", "minNotional"))
    if value is not None and value > 0:
        return float(value)
    value = _to_float(_extract_filter_value(filters, "MIN_NOTIONAL", "notional"))
    if value is not None and value > 0:
        return float(value)
    value = _to_float(_extract_filter_value(filters, "MIN_NOTIONAL", "minNotional"))
    if value is not None and value > 0:
        return float(value)
    return None


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


def _is_dual_side_mode(request):
    payload = request("GET", "/fapi/v1/positionSide/dual", signed=True)
    if not isinstance(payload, dict):
        return False
    raw = payload.get("dualSidePosition")
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() == "true"


def _is_dual_side_mode_cached(exchange, request, ttl_sec=8.0):
    now = time.monotonic()
    cache = getattr(exchange, "_spread_binance_dual_mode_cache", None)
    if isinstance(cache, dict):
        cached_until = float(cache.get("until") or 0.0)
        if cached_until > now:
            return bool(cache.get("value"))
    value = _is_dual_side_mode(request)
    setattr(
        exchange,
        "_spread_binance_dual_mode_cache",
        {"until": now + float(max(1.0, ttl_sec)), "value": bool(value)},
    )
    return bool(value)


def _get_exchange_info_cached(exchange, request, ttl_sec=45.0):
    now = time.monotonic()
    cache = getattr(exchange, "_spread_binance_exchange_info_cache", None)
    if isinstance(cache, dict):
        cached_until = float(cache.get("until") or 0.0)
        payload = cache.get("payload")
        if cached_until > now and isinstance(payload, dict):
            return payload

    payload = request("GET", "/fapi/v1/exchangeInfo", signed=False)
    if not isinstance(payload, dict):
        return None
    setattr(
        exchange,
        "_spread_binance_exchange_info_cache",
        {"until": now + float(max(5.0, ttl_sec)), "payload": payload},
    )
    return payload


def _resolve_position_side(side, reduce_only):
    direction = str(side or "").strip().lower()
    if bool(reduce_only):
        # Reduce SHORT by BUY, reduce LONG by SELL.
        return "SHORT" if direction == "buy" else "LONG"
    return "LONG" if direction == "buy" else "SHORT"


def _fetch_reduce_closeable_qty(request, symbol, side, dual_mode):
    payload = request(
        "GET",
        "/fapi/v3/positionRisk",
        signed=True,
        params={"symbol": symbol},
    )
    if not isinstance(payload, list):
        return 0.0

    direction = str(side or "").strip().lower()
    close_long = direction == "sell"
    close_short = direction == "buy"
    total = 0.0
    for row in payload:
        row_symbol = _normalize_symbol(row.get("symbol"))
        if row_symbol != symbol:
            continue
        position_side = str(row.get("positionSide") or "BOTH").upper()
        size = _to_float(row.get("positionAmt"))
        if size is None:
            continue

        if dual_mode:
            if close_long and position_side == "LONG":
                total += abs(float(size))
            elif close_short and position_side == "SHORT":
                total += abs(float(size))
            continue

        if close_long and float(size) > 0:
            total += float(size)
        elif close_short and float(size) < 0:
            total += abs(float(size))
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

    exchange_info = _get_exchange_info_cached(exchange, request)
    if not isinstance(exchange_info, dict):
        return _attach_timing({"ok": False, "error": "exchange_info_unavailable"}, started_ts)

    symbol_info = None
    for row in exchange_info.get("symbols") or []:
        if _normalize_symbol(row.get("symbol")) == symbol:
            symbol_info = row
            break
    if not isinstance(symbol_info, dict):
        return _attach_timing({"ok": False, "error": "symbol_not_found"}, started_ts)

    status = str(symbol_info.get("status") or "").upper()
    if status and status != "TRADING":
        return _attach_timing({"ok": False, "error": "symbol_not_trading", "status": status}, started_ts)

    filters = symbol_info.get("filters") or []
    lot_step = _to_float(_extract_filter_value(filters, "LOT_SIZE", "stepSize"))
    lot_min = _to_float(_extract_filter_value(filters, "LOT_SIZE", "minQty"))
    lot_max = _to_float(_extract_filter_value(filters, "LOT_SIZE", "maxQty"))
    price_tick = _to_float(_extract_filter_value(filters, "PRICE_FILTER", "tickSize"))
    min_notional = _resolve_min_notional(filters)

    aligned_qty = _round_down_to_step(requested_qty, lot_step or 0.0)
    dual_mode = _is_dual_side_mode_cached(exchange, request)
    if bool(reduce_only):
        closeable_qty = _fetch_reduce_closeable_qty(request, symbol, direction, dual_mode)
        if closeable_qty <= 1e-12:
            return _attach_timing({
                "ok": True,
                "skipped": "no_position",
                "exchange": str(getattr(exchange, "name", "") or "binance"),
                "symbol": symbol,
                "side": direction,
                "reduce_only": True,
                "status": "NO_POSITION",
                "requested_qty": float(aligned_qty),
                "executed_qty": 0.0,
            }, started_ts)
        aligned_qty = min(aligned_qty, _round_down_to_step(closeable_qty, lot_step or 0.0))

    if lot_min is not None and lot_min > 0 and aligned_qty < lot_min:
        if bool(reduce_only):
            return _attach_timing({
                "ok": True,
                "skipped": "position_below_min_qty",
                "exchange": str(getattr(exchange, "name", "") or "binance"),
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
            "min_qty": lot_min,
        }, started_ts)
    if lot_max is not None and lot_max > 0 and aligned_qty > lot_max:
        aligned_qty = _round_down_to_step(lot_max, lot_step or 0.0)
    if aligned_qty <= 0:
        return _attach_timing({"ok": False, "error": "qty_rounds_to_zero"}, started_ts)

    best_price = _to_float(best_price_hint)
    if best_price is None or best_price <= 0:
        ticker = request(
            "GET",
            "/fapi/v1/ticker/bookTicker",
            signed=False,
            params={"symbol": symbol},
        )
        if not isinstance(ticker, dict):
            return _attach_timing({"ok": False, "error": "book_ticker_unavailable"}, started_ts)
        best_price = _to_float(ticker.get("askPrice" if direction == "buy" else "bidPrice"))
    if best_price is None or best_price <= 0:
        return _attach_timing({"ok": False, "error": "invalid_best_price"}, started_ts)

    slippage_ratio = max(0.0, float(_to_float(max_slippage_pct) or 0.0)) / 100.0
    if direction == "buy":
        raw_limit_price = best_price * (1.0 + slippage_ratio)
    else:
        raw_limit_price = best_price * (1.0 - slippage_ratio)
    limit_price = _round_price_to_tick(raw_limit_price, price_tick or 0.0, direction)
    if limit_price <= 0:
        return _attach_timing({"ok": False, "error": "invalid_limit_price"}, started_ts)

    if not bool(reduce_only) and min_notional is not None and min_notional > 0:
        order_notional = float(aligned_qty) * float(limit_price)
        if order_notional + 1e-12 < float(min_notional):
            return _attach_timing({
                "ok": False,
                "error": "qty_below_min_notional",
                "requested_qty": requested_qty,
                "aligned_qty": float(aligned_qty),
                "order_notional": float(order_notional),
                "min_notional": float(min_notional),
            }, started_ts)

    qty_text = _format_to_step(aligned_qty, lot_step or 0.0)
    price_text = _format_to_step(limit_price, price_tick or 0.0)
    params = {
        "symbol": symbol,
        "side": "BUY" if direction == "buy" else "SELL",
        "type": "LIMIT",
        "timeInForce": "IOC",
        "quantity": qty_text,
        "price": price_text,
        "newOrderRespType": "RESULT",
    }
    if bool(reduce_only):
        params["reduceOnly"] = "true"

    if dual_mode:
        params["positionSide"] = _resolve_position_side(direction, reduce_only)

    response = request("POST", "/fapi/v1/order", signed=True, params=params)
    ack_ts = time.monotonic()
    if not isinstance(response, dict):
        details = str(getattr(exchange, "_last_api_error", "") or "").strip()
        low_details = details.lower()
        if bool(reduce_only) and ("-2022" in details or "reduceonly order is rejected" in low_details):
            return _attach_timing({
                "ok": True,
                "skipped": "no_position",
                "exchange": str(getattr(exchange, "name", "") or "binance"),
                "symbol": symbol,
                "side": direction,
                "reduce_only": True,
                "status": "NO_POSITION",
                "requested_qty": float(aligned_qty),
                "executed_qty": 0.0,
            }, started_ts, ack_ts=ack_ts)
        if "-4164" in details or "notional must be no smaller" in low_details:
            return _attach_timing({
                "ok": False,
                "error": "qty_below_min_notional",
                "requested_qty": requested_qty,
                "aligned_qty": float(aligned_qty),
                "details": details,
                "min_notional": float(min_notional) if (min_notional is not None and min_notional > 0) else None,
            }, started_ts, ack_ts=ack_ts)
        return _attach_timing({"ok": False, "error": "order_submit_failed", "details": details}, started_ts, ack_ts=ack_ts)

    order_status = str(response.get("status") or "").upper()
    executed_qty = _to_float(response.get("executedQty"))
    if (executed_qty is None or executed_qty <= 0) and order_status == "FILLED":
        executed_qty = _to_float(response.get("origQty"))
    if executed_qty is None:
        executed_qty = 0.0

    if executed_qty <= 0:
        return _attach_timing({
            "ok": False,
            "error": "order_not_filled",
            "status": order_status or "UNKNOWN",
            "order_id": response.get("orderId"),
            "requested_qty": float(aligned_qty),
        }, started_ts, ack_ts=ack_ts)

    avg_price = _to_float(response.get("avgPrice"))
    if avg_price is None or avg_price <= 0:
        avg_price = limit_price

    return _attach_timing({
        "ok": True,
        "exchange": str(getattr(exchange, "name", "") or "binance"),
        "symbol": symbol,
        "side": direction,
        "reduce_only": bool(reduce_only),
        "status": order_status or "UNKNOWN",
        "order_id": response.get("orderId"),
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

    exchange_info = _get_exchange_info_cached(exchange, request)
    if not isinstance(exchange_info, dict):
        return _attach_timing({"ok": False, "error": "exchange_info_unavailable"}, started_ts)

    symbol_info = None
    for row in exchange_info.get("symbols") or []:
        if _normalize_symbol(row.get("symbol")) == symbol:
            symbol_info = row
            break
    if not isinstance(symbol_info, dict):
        return _attach_timing({"ok": False, "error": "symbol_not_found"}, started_ts)

    filters = symbol_info.get("filters") or []
    lot_step = _to_float(_extract_filter_value(filters, "LOT_SIZE", "stepSize"))
    lot_min = _to_float(_extract_filter_value(filters, "LOT_SIZE", "minQty"))
    lot_max = _to_float(_extract_filter_value(filters, "LOT_SIZE", "maxQty"))

    aligned_qty = _round_down_to_step(requested_qty, lot_step or 0.0)
    dual_mode = _is_dual_side_mode_cached(exchange, request)
    closeable_qty = _fetch_reduce_closeable_qty(request, symbol, direction, dual_mode)
    if closeable_qty <= 1e-12:
        return _attach_timing({
            "ok": True,
            "skipped": "no_position",
            "exchange": str(getattr(exchange, "name", "") or "binance"),
            "symbol": symbol,
            "side": direction,
            "reduce_only": True,
            "status": "NO_POSITION",
            "requested_qty": float(aligned_qty),
            "executed_qty": 0.0,
        }, started_ts)
    aligned_qty = min(aligned_qty, _round_down_to_step(closeable_qty, lot_step or 0.0))

    if lot_min is not None and lot_min > 0 and aligned_qty < lot_min:
        return _attach_timing({
            "ok": True,
            "skipped": "position_below_min_qty",
            "exchange": str(getattr(exchange, "name", "") or "binance"),
            "symbol": symbol,
            "side": direction,
            "reduce_only": True,
            "status": "NO_POSITION",
            "requested_qty": requested_qty,
            "aligned_qty": aligned_qty,
            "min_qty": lot_min,
            "executed_qty": 0.0,
        }, started_ts)
    if lot_max is not None and lot_max > 0 and aligned_qty > lot_max:
        aligned_qty = _round_down_to_step(lot_max, lot_step or 0.0)
    if aligned_qty <= 0:
        return _attach_timing({"ok": False, "error": "qty_rounds_to_zero"}, started_ts)

    params = {
        "symbol": symbol,
        "side": "BUY" if direction == "buy" else "SELL",
        "type": "MARKET",
        "quantity": _format_to_step(aligned_qty, lot_step or 0.0),
        "reduceOnly": "true",
        "newOrderRespType": "RESULT",
    }
    if dual_mode:
        params["positionSide"] = _resolve_position_side(direction, reduce_only=True)

    response = request("POST", "/fapi/v1/order", signed=True, params=params)
    ack_ts = time.monotonic()
    if not isinstance(response, dict):
        details = str(getattr(exchange, "_last_api_error", "") or "").strip()
        low_details = details.lower()
        if "-2022" in details or "reduceonly order is rejected" in low_details:
            return _attach_timing({
                "ok": True,
                "skipped": "no_position",
                "exchange": str(getattr(exchange, "name", "") or "binance"),
                "symbol": symbol,
                "side": direction,
                "reduce_only": True,
                "status": "NO_POSITION",
                "requested_qty": float(aligned_qty),
                "executed_qty": 0.0,
            }, started_ts, ack_ts=ack_ts)
        return _attach_timing({"ok": False, "error": "order_submit_failed", "details": details}, started_ts, ack_ts=ack_ts)

    order_status = str(response.get("status") or "").upper()
    executed_qty = _to_float(response.get("executedQty"))
    if (executed_qty is None or executed_qty <= 0) and order_status == "FILLED":
        executed_qty = _to_float(response.get("origQty"))
    if executed_qty is None:
        executed_qty = 0.0

    if executed_qty <= 0:
        return _attach_timing({
            "ok": False,
            "error": "order_not_filled",
            "status": order_status or "UNKNOWN",
            "order_id": response.get("orderId"),
            "requested_qty": float(aligned_qty),
        }, started_ts, ack_ts=ack_ts)

    avg_price = _to_float(response.get("avgPrice"))
    if avg_price is None:
        avg_price = 0.0

    return _attach_timing({
        "ok": True,
        "exchange": str(getattr(exchange, "name", "") or "binance"),
        "symbol": symbol,
        "side": direction,
        "reduce_only": True,
        "status": order_status or "UNKNOWN",
        "order_id": response.get("orderId"),
        "requested_qty": float(aligned_qty),
        "executed_qty": float(executed_qty),
        "avg_price": float(avg_price),
    }, started_ts, ack_ts=ack_ts)
