"""Bybit helpers used by spread-sniping feature."""

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


def _last_error_text(exchange):
    return str(getattr(exchange, "_last_api_error", "") or "").strip()


def _is_position_idx_mismatch(error_text):
    text = str(error_text or "").strip().lower()
    if not text:
        return False
    return "position idx not match position mode" in text or "positionidx" in text


def _position_rows_cached(exchange, request, symbol, ttl_sec=1.5):
    key = _normalize_symbol(symbol)
    if not key:
        return []

    now = time.monotonic()
    cache = getattr(exchange, "_spread_bybit_positions_cache", None)
    if isinstance(cache, dict):
        item = cache.get(key)
        if isinstance(item, dict) and float(item.get("until") or 0.0) > now:
            rows = item.get("rows")
            if isinstance(rows, list):
                return list(rows)

    payload = request(
        "GET",
        "/v5/position/list",
        params={"category": "linear", "symbol": key},
        signed=True,
    )
    rows = []
    if isinstance(payload, dict):
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        rows = [row for row in (result.get("list") or []) if isinstance(row, dict)]

    if not isinstance(cache, dict):
        cache = {}
    cache[key] = {"until": now + float(max(0.5, ttl_sec)), "rows": list(rows)}
    setattr(exchange, "_spread_bybit_positions_cache", cache)
    return list(rows)


def _is_hedge_mode_rows(rows):
    for row in rows or []:
        idx = _to_float((row or {}).get("positionIdx"))
        if idx is None:
            continue
        idx_int = int(idx)
        if idx_int in (1, 2):
            return True
    return False


def _hedge_position_idx(side, reduce_only):
    direction = str(side or "").strip().lower()
    if bool(reduce_only):
        # Reduce short by BUY (idx=2), reduce long by SELL (idx=1).
        return 2 if direction == "buy" else 1
    # Open/increase long by BUY (idx=1), short by SELL (idx=2).
    return 1 if direction == "buy" else 2


def _resolve_position_idx(exchange, request, symbol, side, reduce_only):
    rows = _position_rows_cached(exchange, request, symbol)
    if _is_hedge_mode_rows(rows):
        return _hedge_position_idx(side, reduce_only)
    return 0


def _query_execution_summary(request, symbol, order_id):
    if not order_id:
        return {}

    payload = request(
        "GET",
        "/v5/execution/list",
        params={"category": "linear", "symbol": symbol, "orderId": order_id, "limit": 50},
        signed=True,
    )
    if not isinstance(payload, dict):
        return {}

    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    rows = result.get("list") or []
    if not rows:
        return {}

    total_qty = 0.0
    total_notional = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        qty = _to_float(row.get("execQty"))
        price = _to_float(row.get("execPrice"))
        if qty is None or qty <= 0:
            continue
        total_qty += float(qty)
        if price is not None and price > 0:
            total_notional += float(price) * float(qty)

    if total_qty <= 0:
        return {}

    avg_price = total_notional / total_qty if total_notional > 0 else None
    return {
        "executed_qty": float(total_qty),
        "avg_price": float(avg_price) if (avg_price is not None and avg_price > 0) else None,
    }


def _round_down_to_step(value, step):
    number = _to_float(value)
    step_val = _to_float(step)
    if number is None or number <= 0:
        return 0.0
    if step_val is None or step_val <= 0:
        return float(number)
    rounded = math.floor(float(number) / float(step_val)) * float(step_val)
    if rounded < 0:
        rounded = 0.0
    return float(rounded)


def _round_price_to_tick(value, tick, side):
    number = _to_float(value)
    tick_val = _to_float(tick)
    if number is None or number <= 0:
        return 0.0
    if tick_val is None or tick_val <= 0:
        return float(number)

    quotient = float(number) / float(tick_val)
    side_norm = str(side or "").strip().lower()
    if side_norm == "buy":
        rounded = math.ceil(quotient) * float(tick_val)
    else:
        rounded = math.floor(quotient) * float(tick_val)
    if rounded < 0:
        rounded = 0.0
    return float(rounded)


def _format_to_step(value, step):
    number = _to_float(value)
    if number is None:
        return "0"

    step_val = _to_float(step)
    if step_val is None or step_val <= 0:
        text = f"{float(number):.12f}"
        text = text.rstrip("0").rstrip(".")
        return text or "0"

    decimals = 0
    sample = f"{float(step_val):.12f}".rstrip("0")
    if "." in sample:
        decimals = len(sample.split(".", 1)[1])

    text = f"{float(number):.{decimals}f}" if decimals > 0 else f"{int(round(float(number)))}"
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def _is_symbol_trading(row):
    status = str((row or {}).get("status") or "").strip().upper()
    if not status:
        return True
    return status in {"TRADING", "TRADING_NORMAL"}


def _load_linear_instruments(request):
    cache = []
    cursor = ""
    for _ in range(8):
        params = {"category": "linear", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        payload = request("GET", "/v5/market/instruments-info", params=params, signed=False)
        if not isinstance(payload, dict):
            break
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        rows = result.get("list") or []
        if rows:
            cache.extend([row for row in rows if isinstance(row, dict)])
        next_cursor = str(result.get("nextPageCursor") or "").strip()
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return cache


def _instruments_cached(exchange, request):
    now = time.monotonic()
    cache = getattr(exchange, "_spread_bybit_instruments_cache", None)
    if isinstance(cache, dict):
        ts = _to_float(cache.get("ts"))
        if ts is not None and (now - float(ts)) <= 30.0:
            rows = cache.get("rows")
            if isinstance(rows, list):
                return rows

    rows = _load_linear_instruments(request)
    setattr(exchange, "_spread_bybit_instruments_cache", {"ts": float(now), "rows": list(rows or [])})
    return list(rows or [])


def _find_instrument(exchange, request, symbol):
    target = _normalize_symbol(symbol)
    if not target:
        return None
    for row in _instruments_cached(exchange, request):
        if _normalize_symbol(row.get("symbol")) == target:
            return row
    return None


def load_spread_account_pairs(exchange):
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return []

    account_ok = False
    for account_type in ("UNIFIED", "CONTRACT"):
        payload = request(
            "GET",
            "/v5/account/wallet-balance",
            params={"accountType": account_type},
            signed=True,
        )
        if isinstance(payload, dict):
            account_ok = True
            break
    if not account_ok:
        return []

    pairs = []
    seen = set()
    for row in _instruments_cached(exchange, request):
        if not _is_symbol_trading(row):
            continue
        symbol = _normalize_symbol(row.get("symbol"))
        if not symbol or symbol in seen:
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

    payload = request(
        "GET",
        "/v5/market/tickers",
        params={"category": "linear", "symbol": symbol},
        signed=False,
    )
    if not isinstance(payload, dict):
        return None

    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    rows = result.get("list") or []
    row = rows[0] if rows and isinstance(rows[0], dict) else None
    if not isinstance(row, dict):
        return None

    bid = _to_float(row.get("bid1Price"))
    ask = _to_float(row.get("ask1Price"))
    bid_qty = _to_float(row.get("bid1Size"))
    ask_qty = _to_float(row.get("ask1Size"))
    if bid is None or ask is None:
        return None

    return {
        "symbol": _normalize_symbol(row.get("symbol") or symbol),
        "bid": bid,
        "ask": ask,
        "bid_qty": bid_qty,
        "ask_qty": ask_qty,
        "event_time": row.get("time") or row.get("ts"),
        "market_type": "linear",
    }


def get_spread_qty_constraints(exchange, pair):
    request = getattr(exchange, "_request", None)
    if not callable(request):
        return None

    symbol = _normalize_symbol(pair)
    if not symbol:
        return None

    instrument = _find_instrument(exchange, request, symbol)
    if not isinstance(instrument, dict):
        return None

    lot = instrument.get("lotSizeFilter") if isinstance(instrument.get("lotSizeFilter"), dict) else {}
    min_qty = _to_float(lot.get("minOrderQty"))
    qty_step = _to_float(lot.get("qtyStep"))
    max_qty = _to_float(lot.get("maxOrderQty"))
    min_notional = _to_float(lot.get("minNotionalValue"))

    if (min_qty is None or min_qty <= 0) and qty_step is not None and qty_step > 0:
        min_qty = qty_step
    if (qty_step is None or qty_step <= 0) and min_qty is not None and min_qty > 0:
        qty_step = min_qty
    if min_qty is None or min_qty <= 0 or qty_step is None or qty_step <= 0:
        return None

    return {
        "exchange": str(getattr(exchange, "name", "") or "bybit"),
        "symbol": symbol,
        "qty_step": float(qty_step),
        "min_qty": float(min_qty),
        "max_qty": float(max_qty) if (max_qty is not None and max_qty > 0) else None,
        "min_notional": float(min_notional) if (min_notional is not None and min_notional > 0) else None,
    }


def _fetch_reduce_closeable_qty(exchange, request, symbol, side):
    rows = _position_rows_cached(exchange, request, symbol)
    if not rows:
        return 0.0
    direction = str(side or "").strip().lower()
    close_long = direction == "sell"
    close_short = direction == "buy"

    total = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _normalize_symbol(row.get("symbol")) != symbol:
            continue
        row_side = str(row.get("side") or "").strip().lower()
        size = _to_float(row.get("size"))
        if size is None or size <= 0:
            continue
        if close_long and row_side == "buy":
            total += float(size)
        elif close_short and row_side == "sell":
            total += float(size)

    return max(0.0, float(total))


def _query_order_state(request, symbol, order_id):
    if not order_id:
        return {}
    for attempt in range(4):
        for open_only in ("0", "1", "2"):
            payload = request(
                "GET",
                "/v5/order/realtime",
                params={"category": "linear", "symbol": symbol, "orderId": order_id, "openOnly": open_only},
                signed=True,
            )
            if not isinstance(payload, dict):
                continue
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            rows = result.get("list") or []
            row = rows[0] if rows and isinstance(rows[0], dict) else None
            if isinstance(row, dict):
                return row
        if attempt < 3:
            time.sleep(0.05 * float(attempt + 1))
    return {}


def _submit_order_with_position_idx(exchange, request, params, side, reduce_only):
    response = request("POST", "/v5/order/create", params=params, signed=True)
    ack_ts = time.monotonic()
    if isinstance(response, dict):
        return response, ack_ts, int(params.get("positionIdx", 0))

    last_error = _last_error_text(exchange)
    if not _is_position_idx_mismatch(last_error):
        return None, ack_ts, int(params.get("positionIdx", 0))

    current_idx = int(params.get("positionIdx", 0))
    if current_idx == 0:
        retry_idx = _hedge_position_idx(side, reduce_only)
    else:
        retry_idx = 0

    retry_params = dict(params)
    retry_params["positionIdx"] = int(retry_idx)
    response_retry = request("POST", "/v5/order/create", params=retry_params, signed=True)
    ack_retry_ts = time.monotonic()
    if isinstance(response_retry, dict):
        return response_retry, ack_retry_ts, int(retry_idx)
    return None, ack_retry_ts, int(retry_idx)


def _build_no_position_reduce_result(exchange, symbol, side, requested_qty):
    return {
        "ok": True,
        "skipped": "no_position",
        "exchange": str(getattr(exchange, "name", "") or "bybit"),
        "symbol": symbol,
        "side": str(side or "").strip().lower(),
        "reduce_only": True,
        "status": "NO_POSITION",
        "requested_qty": float(requested_qty or 0.0),
        "executed_qty": 0.0,
    }


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

    constraints = get_spread_qty_constraints(exchange, symbol)
    if not isinstance(constraints, dict):
        return _attach_timing({"ok": False, "error": "symbol_not_found"}, started_ts)

    qty_step = _to_float(constraints.get("qty_step")) or 0.0
    min_qty = _to_float(constraints.get("min_qty")) or 0.0
    max_qty = _to_float(constraints.get("max_qty"))
    min_notional = _to_float(constraints.get("min_notional"))

    aligned_qty = _round_down_to_step(requested_qty, qty_step)
    if bool(reduce_only):
        closeable_qty = _fetch_reduce_closeable_qty(exchange, request, symbol, direction)
        if closeable_qty <= 1e-12:
            return _attach_timing(_build_no_position_reduce_result(exchange, symbol, direction, aligned_qty), started_ts)
        aligned_qty = min(aligned_qty, _round_down_to_step(closeable_qty, qty_step))

    if min_qty > 0 and aligned_qty < min_qty:
        if bool(reduce_only):
            return _attach_timing(
                {
                    "ok": True,
                    "skipped": "position_below_min_qty",
                    "exchange": str(getattr(exchange, "name", "") or "bybit"),
                    "symbol": symbol,
                    "side": direction,
                    "reduce_only": True,
                    "status": "NO_POSITION",
                    "requested_qty": float(aligned_qty),
                    "executed_qty": 0.0,
                },
                started_ts,
            )
        return _attach_timing(
            {
                "ok": False,
                "error": "qty_below_min",
                "requested_qty": float(requested_qty),
                "aligned_qty": float(aligned_qty),
                "min_qty": float(min_qty),
            },
            started_ts,
        )

    if max_qty is not None and max_qty > 0 and aligned_qty > max_qty:
        aligned_qty = _round_down_to_step(max_qty, qty_step)
    if aligned_qty <= 0:
        return _attach_timing({"ok": False, "error": "qty_rounds_to_zero"}, started_ts)

    quote = fetch_spread_book_ticker_snapshot(exchange, symbol)
    best_price = _to_float(best_price_hint)
    if best_price is None or best_price <= 0:
        best_price = _to_float((quote or {}).get("ask" if direction == "buy" else "bid"))
    if best_price is None or best_price <= 0:
        return _attach_timing({"ok": False, "error": "book_ticker_unavailable"}, started_ts)

    instrument = _find_instrument(exchange, request, symbol) or {}
    price_filter = instrument.get("priceFilter") if isinstance(instrument.get("priceFilter"), dict) else {}
    price_tick = _to_float(price_filter.get("tickSize")) or 0.0

    slippage_ratio = max(0.0, float(_to_float(max_slippage_pct) or 0.0)) / 100.0
    raw_limit_price = best_price * (1.0 + slippage_ratio) if direction == "buy" else best_price * (1.0 - slippage_ratio)
    limit_price = _round_price_to_tick(raw_limit_price, price_tick, direction)
    if limit_price <= 0:
        return _attach_timing({"ok": False, "error": "invalid_limit_price"}, started_ts)

    if (not bool(reduce_only)) and min_notional is not None and min_notional > 0:
        order_notional = float(aligned_qty) * float(limit_price)
        if order_notional + 1e-12 < float(min_notional):
            return _attach_timing(
                {
                    "ok": False,
                    "error": "qty_below_min_notional",
                    "requested_qty": float(requested_qty),
                    "aligned_qty": float(aligned_qty),
                    "order_notional": float(order_notional),
                    "min_notional": float(min_notional),
                },
                started_ts,
            )

    position_idx = _resolve_position_idx(exchange, request, symbol, direction, bool(reduce_only))
    params = {
        "category": "linear",
        "symbol": symbol,
        "side": "Buy" if direction == "buy" else "Sell",
        "orderType": "Limit",
        "timeInForce": "IOC",
        "qty": _format_to_step(aligned_qty, qty_step),
        "price": _format_to_step(limit_price, price_tick),
        "reduceOnly": bool(reduce_only),
        "positionIdx": int(position_idx),
    }
    if bool(reduce_only):
        params["closeOnTrigger"] = True

    response, ack_ts, final_position_idx = _submit_order_with_position_idx(
        exchange,
        request,
        params,
        direction,
        bool(reduce_only),
    )
    if not isinstance(response, dict):
        details = _last_error_text(exchange)
        return _attach_timing({"ok": False, "error": "order_submit_failed", "details": details}, started_ts, ack_ts=ack_ts)

    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    order_id = result.get("orderId")
    order_state = _query_order_state(request, symbol, order_id)
    execution_state = _query_execution_summary(request, symbol, order_id)

    executed_qty = _to_float((order_state or {}).get("cumExecQty"))
    status = str((order_state or {}).get("orderStatus") or (order_state or {}).get("status") or "").strip().upper()
    if executed_qty is None:
        executed_qty = 0.0
    if executed_qty <= 0:
        executed_qty = _to_float((execution_state or {}).get("executed_qty")) or 0.0
    if not status and executed_qty > 0:
        status = "FILLED"

    if executed_qty <= 0:
        return _attach_timing(
            {
                "ok": False,
                "error": "order_not_filled",
                "status": status or "UNKNOWN",
                "order_id": order_id,
                "requested_qty": float(aligned_qty),
            },
            started_ts,
            ack_ts=ack_ts,
        )

    avg_price = _to_float((order_state or {}).get("avgPrice"))
    if avg_price is None or avg_price <= 0:
        avg_price = _to_float((execution_state or {}).get("avg_price"))
    if avg_price is None or avg_price <= 0:
        avg_price = limit_price

    return _attach_timing(
        {
            "ok": True,
            "exchange": str(getattr(exchange, "name", "") or "bybit"),
            "symbol": symbol,
            "side": direction,
            "reduce_only": bool(reduce_only),
            "status": status or "UNKNOWN",
            "order_id": order_id,
            "requested_qty": float(aligned_qty),
            "executed_qty": float(executed_qty),
            "avg_price": float(avg_price),
            "limit_price": float(limit_price),
            "position_idx": int(final_position_idx),
        },
        started_ts,
        ack_ts=ack_ts,
    )


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

    constraints = get_spread_qty_constraints(exchange, symbol)
    if not isinstance(constraints, dict):
        return _attach_timing({"ok": False, "error": "symbol_not_found"}, started_ts)

    qty_step = _to_float(constraints.get("qty_step")) or 0.0
    min_qty = _to_float(constraints.get("min_qty")) or 0.0

    aligned_qty = _round_down_to_step(requested_qty, qty_step)
    closeable_qty = _fetch_reduce_closeable_qty(exchange, request, symbol, direction)
    if closeable_qty <= 1e-12:
        return _attach_timing(_build_no_position_reduce_result(exchange, symbol, direction, aligned_qty), started_ts)
    aligned_qty = min(aligned_qty, _round_down_to_step(closeable_qty, qty_step))

    if min_qty > 0 and aligned_qty < min_qty:
        return _attach_timing(
            {
                "ok": True,
                "skipped": "position_below_min_qty",
                "exchange": str(getattr(exchange, "name", "") or "bybit"),
                "symbol": symbol,
                "side": direction,
                "reduce_only": True,
                "status": "NO_POSITION",
                "requested_qty": float(requested_qty),
                "aligned_qty": float(aligned_qty),
                "min_qty": float(min_qty),
                "executed_qty": 0.0,
            },
            started_ts,
        )
    if aligned_qty <= 0:
        return _attach_timing({"ok": False, "error": "qty_rounds_to_zero"}, started_ts)

    position_idx = _resolve_position_idx(exchange, request, symbol, direction, True)
    params = {
        "category": "linear",
        "symbol": symbol,
        "side": "Buy" if direction == "buy" else "Sell",
        "orderType": "Market",
        "qty": _format_to_step(aligned_qty, qty_step),
        "reduceOnly": True,
        "closeOnTrigger": True,
        "positionIdx": int(position_idx),
    }

    response, ack_ts, final_position_idx = _submit_order_with_position_idx(
        exchange,
        request,
        params,
        direction,
        True,
    )
    if not isinstance(response, dict):
        details = _last_error_text(exchange)
        return _attach_timing({"ok": False, "error": "order_submit_failed", "details": details}, started_ts, ack_ts=ack_ts)

    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    order_id = result.get("orderId")
    order_state = _query_order_state(request, symbol, order_id)
    execution_state = _query_execution_summary(request, symbol, order_id)

    executed_qty = _to_float((order_state or {}).get("cumExecQty"))
    status = str((order_state or {}).get("orderStatus") or (order_state or {}).get("status") or "").strip().upper()
    if executed_qty is None:
        executed_qty = 0.0
    if executed_qty <= 0:
        executed_qty = _to_float((execution_state or {}).get("executed_qty")) or 0.0
    if not status and executed_qty > 0:
        status = "FILLED"

    if executed_qty <= 0:
        return _attach_timing(
            {
                "ok": False,
                "error": "order_not_filled",
                "status": status or "UNKNOWN",
                "order_id": order_id,
                "requested_qty": float(aligned_qty),
            },
            started_ts,
            ack_ts=ack_ts,
        )

    avg_price = _to_float((order_state or {}).get("avgPrice"))
    if avg_price is None or avg_price <= 0:
        avg_price = _to_float((execution_state or {}).get("avg_price"))
    if avg_price is None:
        avg_price = 0.0

    return _attach_timing(
        {
            "ok": True,
            "exchange": str(getattr(exchange, "name", "") or "bybit"),
            "symbol": symbol,
            "side": direction,
            "reduce_only": True,
            "status": status or "UNKNOWN",
            "order_id": order_id,
            "requested_qty": float(aligned_qty),
            "executed_qty": float(executed_qty),
            "avg_price": float(avg_price),
            "position_idx": int(final_position_idx),
        },
        started_ts,
        ack_ts=ack_ts,
    )
