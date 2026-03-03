from core.exchange.adapters.binance import (
    fetch_spread_book_ticker_snapshot as fetch_binance_book_ticker_snapshot,
    get_spread_qty_constraints as get_binance_qty_constraints,
    load_spread_account_pairs as load_binance_account_pairs,
    place_spread_limit_fok_order as place_binance_spread_order,
    place_spread_market_reduce_order as place_binance_spread_market_reduce,
)
from core.exchange.adapters.bitget import (
    fetch_spread_book_ticker_snapshot as fetch_bitget_book_ticker_snapshot,
    get_spread_qty_constraints as get_bitget_qty_constraints,
    load_spread_account_pairs as load_bitget_account_pairs,
    place_spread_limit_fok_order as place_bitget_spread_order,
    place_spread_market_reduce_order as place_bitget_spread_market_reduce,
)
from core.exchange.catalog import normalize_exchange_code
import math
import time
from decimal import Decimal, InvalidOperation
from concurrent.futures import ThreadPoolExecutor
from threading import Event


class SpreadRuntimeService:
    """Business logic for spread-sniping tab (without UI dependencies)."""

    _SPREAD_ADAPTERS = {
        "binance": {
            "load_pairs": load_binance_account_pairs,
            "fetch_quote": fetch_binance_book_ticker_snapshot,
            "qty_constraints": get_binance_qty_constraints,
            "place_order": place_binance_spread_order,
            "place_market_reduce": place_binance_spread_market_reduce,
            "strict": True,
        },
        "bitget": {
            "load_pairs": load_bitget_account_pairs,
            "fetch_quote": fetch_bitget_book_ticker_snapshot,
            "qty_constraints": get_bitget_qty_constraints,
            "place_order": place_bitget_spread_order,
            "place_market_reduce": place_bitget_spread_market_reduce,
            "strict": True,
        },
    }
    _HEDGE_ESCALATION_FACTORS = (2.0, 4.0, 6.0)
    _HEDGE_ESCALATION_TIMERS_SEC = (0.6, 1.2, 1.8)
    _HEDGE_ESCALATION_MAX_ATTEMPTS = 3
    _HEDGE_MAX_SLIPPAGE_CAP_PCT = 0.30
    _HEDGE_MIN_FILL_RATIO = 0.98

    def __init__(self, exchange_manager, popular_pairs):
        self.exchange_manager = exchange_manager
        self._popular_pairs = tuple(popular_pairs or ())
        self._qty_constraints_cache = {}
        # Reuse worker threads between steps to avoid per-step pool creation overhead.
        self._hedge_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="spread-hedge")

    def shutdown(self):
        executor = getattr(self, "_hedge_executor", None)
        if executor is None:
            return
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self._hedge_executor = None

    def __del__(self):
        self.shutdown()

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

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _pair_key(value):
        return SpreadRuntimeService._normalize_pair(value)

    def _constraint_key(self, exchange_name, pair):
        return (str(exchange_name or "").strip().lower(), self._pair_key(pair))

    @staticmethod
    def _decimal_to_fraction(value):
        try:
            dec = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None, None
        if dec <= 0:
            return None, None
        tup = dec.as_tuple()
        scale = 10 ** max(0, -int(tup.exponent))
        numerator = int(dec * scale)
        if numerator <= 0:
            return None, None
        gcd = math.gcd(numerator, scale)
        return numerator // gcd, scale // gcd

    @classmethod
    def _common_step(cls, step_a, step_b):
        num_a, den_a = cls._decimal_to_fraction(step_a)
        num_b, den_b = cls._decimal_to_fraction(step_b)
        if not num_a or not den_a or not num_b or not den_b:
            return None
        common_den = math.lcm(den_a, den_b)
        int_a = num_a * (common_den // den_a)
        int_b = num_b * (common_den // den_b)
        step_int = math.lcm(int_a, int_b)
        if step_int <= 0 or common_den <= 0:
            return None
        return float(step_int) / float(common_den)

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

    def get_qty_constraints(self, exchange_name, pair):
        key = self._constraint_key(exchange_name, pair)
        if not key[0] or not key[1]:
            return None
        if key in self._qty_constraints_cache:
            return dict(self._qty_constraints_cache.get(key) or {})

        exchange = self._get_exchange(exchange_name)
        if exchange is None:
            return None

        adapter = self._get_adapter(exchange)
        if not isinstance(adapter, dict):
            return None

        resolver = adapter.get("qty_constraints")
        if not callable(resolver):
            return None
        try:
            payload = resolver(exchange, key[1])
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return None

        min_qty = self._to_float(payload.get("min_qty"))
        qty_step = self._to_float(payload.get("qty_step"))
        if (min_qty is None or min_qty <= 0) and qty_step is not None and qty_step > 0:
            min_qty = qty_step
        if (qty_step is None or qty_step <= 0) and min_qty is not None and min_qty > 0:
            qty_step = min_qty
        if min_qty is None or min_qty <= 0 or qty_step is None or qty_step <= 0:
            return None

        normalized = {
            "exchange": str(payload.get("exchange") or exchange_name or "").strip(),
            "symbol": str(payload.get("symbol") or key[1]).strip().upper(),
            "min_qty": float(min_qty),
            "qty_step": float(qty_step),
            "max_qty": self._to_float(payload.get("max_qty")),
        }
        self._qty_constraints_cache[key] = dict(normalized)
        return dict(normalized)

    def get_common_qty_constraints(self, buy_exchange, buy_pair, sell_exchange, sell_pair):
        first = self.get_qty_constraints(buy_exchange, buy_pair)
        second = self.get_qty_constraints(sell_exchange, sell_pair)
        if not isinstance(first, dict) or not isinstance(second, dict):
            return None

        min_1 = self._to_float(first.get("min_qty"))
        min_2 = self._to_float(second.get("min_qty"))
        step_1 = self._to_float(first.get("qty_step"))
        step_2 = self._to_float(second.get("qty_step"))
        if (
            min_1 is None
            or min_1 <= 0
            or min_2 is None
            or min_2 <= 0
            or step_1 is None
            or step_1 <= 0
            or step_2 is None
            or step_2 <= 0
        ):
            return None

        step_common = self._common_step(step_1, step_2)
        if step_common is None or step_common <= 0:
            return None

        min_common = max(float(min_1), float(min_2))
        return {
            "step_common": float(step_common),
            "min_qty_common": float(min_common),
            "first": first,
            "second": second,
        }

    def place_limit_fok_order(
        self,
        exchange_name,
        pair,
        side,
        qty,
        max_slippage_pct=0.02,
        reduce_only=False,
        best_price_hint=None,
    ):
        exchange = self._get_exchange(exchange_name)
        if exchange is None:
            return {"ok": False, "error": "exchange_not_found"}

        adapter = self._get_adapter(exchange)
        if not isinstance(adapter, dict):
            return {"ok": False, "error": "unsupported"}

        place_fn = adapter.get("place_order")
        if not callable(place_fn):
            return {"ok": False, "error": "unsupported"}

        try:
            result = place_fn(
                exchange=exchange,
                pair=pair,
                side=side,
                qty=qty,
                max_slippage_pct=max_slippage_pct,
                reduce_only=reduce_only,
                best_price_hint=best_price_hint,
            )
        except Exception as exc:
            return {"ok": False, "error": "exception", "details": str(exc)}

        if not isinstance(result, dict):
            return {"ok": False, "error": "invalid_adapter_result"}
        return result

    def place_market_reduce_order(self, exchange_name, pair, side, qty):
        exchange = self._get_exchange(exchange_name)
        if exchange is None:
            return {"ok": False, "error": "exchange_not_found"}

        adapter = self._get_adapter(exchange)
        if not isinstance(adapter, dict):
            return {"ok": False, "error": "unsupported"}

        place_fn = adapter.get("place_market_reduce")
        if not callable(place_fn):
            return {"ok": False, "error": "unsupported"}

        try:
            result = place_fn(
                exchange=exchange,
                pair=pair,
                side=side,
                qty=qty,
            )
        except Exception as exc:
            return {"ok": False, "error": "exception", "details": str(exc)}

        if not isinstance(result, dict):
            return {"ok": False, "error": "invalid_adapter_result"}
        return result

    def execute_hedged_step(
        self,
        action,
        buy_exchange,
        buy_pair,
        sell_exchange,
        sell_pair,
        qty,
        max_slippage_pct=0.02,
        buy_best_price_hint=None,
        sell_best_price_hint=None,
    ):
        step_action = str(action or "").strip().lower()
        requested_qty = float(qty or 0.0)
        if requested_qty <= 0:
            return {"ok": False, "error": "invalid_qty"}
        if step_action not in {"entry", "exit"}:
            return {"ok": False, "error": "invalid_action"}

        reduce_only = step_action == "exit"
        sell_first = step_action == "entry"

        first_leg = {
            "exchange": sell_exchange if sell_first else buy_exchange,
            "pair": sell_pair if sell_first else buy_pair,
            "side": "sell" if sell_first else "buy",
            "best_price_hint": sell_best_price_hint if sell_first else buy_best_price_hint,
        }
        second_leg = {
            "exchange": buy_exchange if sell_first else sell_exchange,
            "pair": buy_pair if sell_first else sell_pair,
            "side": "buy" if sell_first else "sell",
            "best_price_hint": buy_best_price_hint if sell_first else sell_best_price_hint,
        }

        def _extract_leg_timing(result, key):
            if not isinstance(result, dict):
                return 0.0
            value = self._to_float(result.get(key))
            return float(value) if (value is not None and value > 0) else 0.0

        decision_started_ts = time.monotonic()

        def _place_leg_timed(leg, decision_ts, dispatch_ts, start_gate=None):
            if start_gate is not None:
                # Align both leg sends to reduce inter-leg submit skew.
                start_gate.wait(timeout=0.35)
            started = time.monotonic()
            result = self.place_limit_fok_order(
                exchange_name=leg["exchange"],
                pair=leg["pair"],
                side=leg["side"],
                qty=requested_qty,
                max_slippage_pct=max_slippage_pct,
                reduce_only=reduce_only,
                best_price_hint=leg.get("best_price_hint"),
            )
            latency = max(0.0, time.monotonic() - started)
            send_ack = _extract_leg_timing(result, "timing_send_ack_sec")
            ack_fill = _extract_leg_timing(result, "timing_ack_fill_sec")
            submit_total = _extract_leg_timing(result, "timing_total_sec")
            decision_to_send = max(0.0, started - float(decision_ts))
            dispatch_to_send = max(0.0, started - float(dispatch_ts))
            return (
                result,
                latency,
                send_ack,
                ack_fill,
                submit_total,
                started,
                decision_to_send,
                dispatch_to_send,
            )

        # Fast path: submit both legs in parallel for lower end-to-end latency.
        # If one leg fails and another filled on entry, rollback is still applied.
        parallel_submit = (
            str(first_leg.get("exchange") or "").strip().lower()
            != str(second_leg.get("exchange") or "").strip().lower()
        )
        executor = getattr(self, "_hedge_executor", None)
        if parallel_submit and executor is not None:
            send_gate = Event()
            first_dispatch_ts = time.monotonic()
            first_future = executor.submit(_place_leg_timed, first_leg, decision_started_ts, first_dispatch_ts, send_gate)
            second_dispatch_ts = time.monotonic()
            second_future = executor.submit(_place_leg_timed, second_leg, decision_started_ts, second_dispatch_ts, send_gate)
            send_gate.set()
            (
                first_result,
                first_latency_sec,
                first_send_ack_sec,
                first_ack_fill_sec,
                first_submit_total_sec,
                first_send_started_ts,
                first_decision_to_send_sec,
                first_queue_wait_sec,
            ) = first_future.result()
            (
                second_result,
                second_latency_sec,
                second_send_ack_sec,
                second_ack_fill_sec,
                second_submit_total_sec,
                second_send_started_ts,
                second_decision_to_send_sec,
                second_queue_wait_sec,
            ) = second_future.result()
        else:
            first_dispatch_ts = time.monotonic()
            (
                first_result,
                first_latency_sec,
                first_send_ack_sec,
                first_ack_fill_sec,
                first_submit_total_sec,
                first_send_started_ts,
                first_decision_to_send_sec,
                first_queue_wait_sec,
            ) = _place_leg_timed(first_leg, decision_started_ts, first_dispatch_ts)
            second_dispatch_ts = time.monotonic()
            (
                second_result,
                second_latency_sec,
                second_send_ack_sec,
                second_ack_fill_sec,
                second_submit_total_sec,
                second_send_started_ts,
                second_decision_to_send_sec,
                second_queue_wait_sec,
            ) = _place_leg_timed(second_leg, decision_started_ts, second_dispatch_ts)

        send_delta_sec = abs(float(first_send_started_ts) - float(second_send_started_ts))
        dispatch_delta_sec = abs(float(first_dispatch_ts) - float(second_dispatch_ts))
        decision_to_first_dispatch_sec = max(
            0.0,
            min(float(first_dispatch_ts), float(second_dispatch_ts)) - float(decision_started_ts),
        )
        decision_to_all_dispatched_sec = max(
            0.0,
            max(float(first_dispatch_ts), float(second_dispatch_ts)) - float(decision_started_ts),
        )

        timing_payload = {
            "first_latency_sec": float(first_latency_sec),
            "second_latency_sec": float(second_latency_sec),
            "first_send_ack_sec": float(first_send_ack_sec),
            "second_send_ack_sec": float(second_send_ack_sec),
            "first_ack_fill_sec": float(first_ack_fill_sec),
            "second_ack_fill_sec": float(second_ack_fill_sec),
            "first_submit_total_sec": float(first_submit_total_sec),
            "second_submit_total_sec": float(second_submit_total_sec),
            "first_decision_to_send_sec": float(first_decision_to_send_sec),
            "second_decision_to_send_sec": float(second_decision_to_send_sec),
            "first_queue_wait_sec": float(first_queue_wait_sec),
            "second_queue_wait_sec": float(second_queue_wait_sec),
            "legs_send_delta_sec": float(send_delta_sec),
            "legs_dispatch_delta_sec": float(dispatch_delta_sec),
            "decision_to_first_dispatch_sec": float(decision_to_first_dispatch_sec),
            "decision_to_all_dispatched_sec": float(decision_to_all_dispatched_sec),
        }

        def _with_timing(payload):
            out = dict(payload or {})
            out.update(timing_payload)
            return out

        def _exec_qty(result):
            if not isinstance(result, dict):
                return 0.0
            value = self._to_float(result.get("executed_qty"))
            return max(0.0, float(value)) if value is not None else 0.0

        def _opposite_side(side):
            return "buy" if str(side or "").strip().lower() == "sell" else "sell"

        def _panic_unwind(leg, qty):
            unwind_qty = max(0.0, float(qty or 0.0))
            if unwind_qty <= 0:
                return {"ok": False, "error": "invalid_qty", "executed_qty": 0.0}
            return self.place_market_reduce_order(
                exchange_name=leg.get("exchange"),
                pair=leg.get("pair"),
                side=_opposite_side(leg.get("side")),
                qty=unwind_qty,
            )

        def _sleep_to_step(step_started_ts, min_elapsed_sec):
            wait_sec = max(0.0, float(min_elapsed_sec or 0.0) - max(0.0, time.monotonic() - float(step_started_ts)))
            if wait_sec > 0:
                time.sleep(wait_sec)

        executed_1 = _exec_qty(first_result)
        executed_2 = _exec_qty(second_result)
        first_ok = bool(first_result.get("ok"))
        second_ok = bool(second_result.get("ok"))
        tolerance = 1e-12
        first_send_ok = first_ok and executed_1 > tolerance
        second_send_ok = second_ok and executed_2 > tolerance
        hedge_step_started_ts = min(float(first_send_started_ts), float(second_send_started_ts))
        base_slippage = max(0.0, float(self._to_float(max_slippage_pct) or 0.0))
        hedge_escalation = {
            "used": False,
            "attempts": [],
            "filled_qty": 0.0,
            "remaining_qty": 0.0,
            "max_attempts": int(self._HEDGE_ESCALATION_MAX_ATTEMPTS),
            "cap_slippage_pct": float(self._HEDGE_MAX_SLIPPAGE_CAP_PCT),
            "min_fill_ratio": float(self._HEDGE_MIN_FILL_RATIO),
        }
        panic_unwind = {
            "used": False,
            "leg": "",
            "requested_qty": 0.0,
            "executed_qty": 0.0,
            "result": None,
        }

        if step_action == "exit":
            skipped_1 = bool(first_result.get("skipped"))
            skipped_2 = bool(second_result.get("skipped"))
            if skipped_1 and skipped_2:
                return _with_timing({
                    "ok": True,
                    "action": step_action,
                    "requested_qty": requested_qty,
                    "executed_qty": 0.0,
                    "nothing_to_close": True,
                    "first_leg": first_leg,
                    "second_leg": second_leg,
                    "first_result": first_result,
                    "second_result": second_result,
                })
            if (skipped_1 and executed_2 > 0) or (skipped_2 and executed_1 > 0):
                return _with_timing({
                    "ok": True,
                    "action": step_action,
                    "requested_qty": requested_qty,
                    "executed_qty": max(executed_1, executed_2),
                    "unbalanced_close": True,
                    "first_leg": first_leg,
                    "second_leg": second_leg,
                    "first_result": first_result,
                    "second_result": second_result,
                })

        # If only hedge leg filled and primary leg did not, flatten hedge leg immediately.
        if executed_1 <= tolerance and executed_2 > tolerance:
            panic_unwind["used"] = True
            panic_unwind["leg"] = "second"
            panic_unwind["requested_qty"] = float(executed_2)
            unwind_result = _panic_unwind(second_leg, executed_2)
            panic_unwind["result"] = unwind_result
            unwind_exec = _exec_qty(unwind_result)
            panic_unwind["executed_qty"] = float(unwind_exec)
            executed_2 = max(0.0, executed_2 - unwind_exec)
            return _with_timing({
                "ok": False,
                "error": "first_leg_failed",
                "action": step_action,
                "first_leg": first_leg,
                "second_leg": second_leg,
                "first_result": first_result,
                "second_result": second_result,
                "rollback_result": unwind_result,
                "hedge_escalation": hedge_escalation,
                "panic_unwind": panic_unwind,
                "first_executed_final": float(executed_1),
                "second_executed_final": float(executed_2),
                "net_exposure_time_sec": float(max(0.0, time.monotonic() - hedge_step_started_ts)),
            })

        # Second leg is hedge leg: if underfilled or failed, escalate with wider limits.
        imbalance = float(executed_1 - executed_2)
        fill_ratio = float(executed_2 / executed_1) if executed_1 > tolerance else 1.0
        min_fill_ratio = max(0.0, min(1.0, float(self._HEDGE_MIN_FILL_RATIO or 0.0)))
        if executed_1 > tolerance and imbalance > tolerance and fill_ratio + tolerance < min_fill_ratio:
            factors = tuple(self._HEDGE_ESCALATION_FACTORS or ())
            timers = tuple(self._HEDGE_ESCALATION_TIMERS_SEC or ())
            max_attempts = max(0, int(self._HEDGE_ESCALATION_MAX_ATTEMPTS or 0))
            for attempt_idx, factor in enumerate(factors, start=1):
                if attempt_idx > max_attempts:
                    break
                if imbalance <= tolerance:
                    break
                fill_ratio = float(executed_2 / executed_1) if executed_1 > tolerance else 1.0
                if fill_ratio + tolerance >= min_fill_ratio:
                    break
                target_elapsed = timers[min(attempt_idx - 1, max(0, len(timers) - 1))] if timers else 0.0
                _sleep_to_step(hedge_step_started_ts, target_elapsed)

                attempt_slip = base_slippage * max(1.0, float(factor))
                attempt_slip = min(float(self._HEDGE_MAX_SLIPPAGE_CAP_PCT), float(attempt_slip))
                attempt_result = self.place_limit_fok_order(
                    exchange_name=second_leg["exchange"],
                    pair=second_leg["pair"],
                    side=second_leg["side"],
                    qty=float(imbalance),
                    max_slippage_pct=float(attempt_slip),
                    reduce_only=reduce_only,
                    best_price_hint=second_leg.get("best_price_hint"),
                )
                attempt_exec = _exec_qty(attempt_result)
                executed_2 += attempt_exec
                imbalance = float(executed_1 - executed_2)
                fill_ratio = float(executed_2 / executed_1) if executed_1 > tolerance else 1.0
                hedge_escalation["used"] = True
                hedge_escalation["filled_qty"] = float(hedge_escalation.get("filled_qty") or 0.0) + float(attempt_exec)
                hedge_escalation["attempts"].append(
                    {
                        "index": int(attempt_idx),
                        "factor": float(factor),
                        "slippage_pct": float(attempt_slip),
                        "requested_qty": float(max(0.0, imbalance + attempt_exec)),
                        "executed_qty": float(attempt_exec),
                        "ok": bool((attempt_result or {}).get("ok")),
                        "error": str((attempt_result or {}).get("error") or ""),
                        "status": str((attempt_result or {}).get("status") or ""),
                        "fill_ratio": float(fill_ratio),
                    }
                )
                if bool((attempt_result or {}).get("ok")) and attempt_exec > tolerance:
                    second_result = attempt_result
                    second_send_ok = True
                if attempt_exec <= tolerance and not bool((attempt_result or {}).get("ok")):
                    # keep trying next escalation step
                    pass

            hedge_escalation["remaining_qty"] = float(max(0.0, imbalance))

        # Rebalance immediately if one leg still larger (partial fill protection).
        imbalance = float(executed_1 - executed_2)
        if abs(imbalance) > tolerance:
            over_leg_name = "first" if imbalance > 0 else "second"
            over_leg = first_leg if imbalance > 0 else second_leg
            over_qty = abs(float(imbalance))
            panic_unwind["used"] = True
            panic_unwind["leg"] = over_leg_name
            panic_unwind["requested_qty"] = float(over_qty)
            unwind_result = _panic_unwind(over_leg, over_qty)
            panic_unwind["result"] = unwind_result
            unwind_exec = _exec_qty(unwind_result)
            panic_unwind["executed_qty"] = float(unwind_exec)
            if imbalance > 0:
                executed_1 = max(0.0, executed_1 - unwind_exec)
            else:
                executed_2 = max(0.0, executed_2 - unwind_exec)
            imbalance = float(executed_1 - executed_2)

        net_exposure_time_sec = float(max(0.0, time.monotonic() - hedge_step_started_ts))
        executed_qty = min(executed_1, executed_2)
        if executed_qty <= 0 or abs(float(executed_1 - executed_2)) > tolerance:
            return _with_timing({
                "ok": False,
                "error": "hedge_unresolved",
                "action": step_action,
                "first_leg": first_leg,
                "second_leg": second_leg,
                "first_result": first_result,
                "second_result": second_result,
                "first_executed_final": float(executed_1),
                "second_executed_final": float(executed_2),
                "hedge_escalation": hedge_escalation,
                "panic_unwind": panic_unwind,
                "net_exposure_time_sec": net_exposure_time_sec,
            })

        if not first_send_ok and not second_send_ok:
            return _with_timing({
                "ok": False,
                "error": "first_leg_failed",
                "action": step_action,
                "first_leg": first_leg,
                "second_leg": second_leg,
                "first_result": first_result,
                "second_result": second_result,
                "first_executed_final": float(executed_1),
                "second_executed_final": float(executed_2),
                "hedge_escalation": hedge_escalation,
                "panic_unwind": panic_unwind,
                "net_exposure_time_sec": net_exposure_time_sec,
            })

        return _with_timing({
            "ok": True,
            "action": step_action,
            "requested_qty": requested_qty,
            "executed_qty": executed_qty,
            "first_leg": first_leg,
            "second_leg": second_leg,
            "first_result": first_result,
            "second_result": second_result,
            "first_executed_final": float(executed_1),
            "second_executed_final": float(executed_2),
            "hedge_escalation": hedge_escalation,
            "panic_unwind": panic_unwind,
            "net_exposure_time_sec": net_exposure_time_sec,
        })

    def force_close_market(self, buy_exchange, buy_pair, sell_exchange, sell_pair, qty):
        requested_qty = float(qty or 0.0)
        if requested_qty <= 0:
            return {"ok": False, "error": "invalid_qty"}

        buy_close_leg = {
            "exchange": buy_exchange,
            "pair": buy_pair,
            "side": "sell",
        }
        sell_close_leg = {
            "exchange": sell_exchange,
            "pair": sell_pair,
            "side": "buy",
        }

        decision_started_ts = time.monotonic()

        def _place_reduce_timed(leg, decision_ts, dispatch_ts, start_gate=None):
            if start_gate is not None:
                start_gate.wait(timeout=0.35)
            started = time.monotonic()
            result = self.place_market_reduce_order(
                exchange_name=leg["exchange"],
                pair=leg["pair"],
                side=leg["side"],
                qty=requested_qty,
            )
            latency = max(0.0, time.monotonic() - started)
            send_ack = self._to_float((result or {}).get("timing_send_ack_sec"))
            ack_fill = self._to_float((result or {}).get("timing_ack_fill_sec"))
            submit_total = self._to_float((result or {}).get("timing_total_sec"))
            return (
                result,
                latency,
                float(send_ack) if (send_ack is not None and send_ack > 0) else 0.0,
                float(ack_fill) if (ack_fill is not None and ack_fill > 0) else 0.0,
                float(submit_total) if (submit_total is not None and submit_total > 0) else 0.0,
                started,
                max(0.0, started - float(decision_ts)),
                max(0.0, started - float(dispatch_ts)),
            )

        executor = getattr(self, "_hedge_executor", None)
        parallel_submit = (
            str(buy_close_leg.get("exchange") or "").strip().lower()
            != str(sell_close_leg.get("exchange") or "").strip().lower()
        )
        if parallel_submit and executor is not None:
            send_gate = Event()
            buy_dispatch_ts = time.monotonic()
            buy_future = executor.submit(_place_reduce_timed, buy_close_leg, decision_started_ts, buy_dispatch_ts, send_gate)
            sell_dispatch_ts = time.monotonic()
            sell_future = executor.submit(_place_reduce_timed, sell_close_leg, decision_started_ts, sell_dispatch_ts, send_gate)
            send_gate.set()
            (
                result_buy_close,
                buy_close_latency_sec,
                buy_send_ack_sec,
                buy_ack_fill_sec,
                buy_submit_total_sec,
                buy_send_started_ts,
                buy_decision_to_send_sec,
                buy_queue_wait_sec,
            ) = buy_future.result()
            (
                result_sell_close,
                sell_close_latency_sec,
                sell_send_ack_sec,
                sell_ack_fill_sec,
                sell_submit_total_sec,
                sell_send_started_ts,
                sell_decision_to_send_sec,
                sell_queue_wait_sec,
            ) = sell_future.result()
        else:
            buy_dispatch_ts = time.monotonic()
            (
                result_buy_close,
                buy_close_latency_sec,
                buy_send_ack_sec,
                buy_ack_fill_sec,
                buy_submit_total_sec,
                buy_send_started_ts,
                buy_decision_to_send_sec,
                buy_queue_wait_sec,
            ) = _place_reduce_timed(buy_close_leg, decision_started_ts, buy_dispatch_ts)
            sell_dispatch_ts = time.monotonic()
            (
                result_sell_close,
                sell_close_latency_sec,
                sell_send_ack_sec,
                sell_ack_fill_sec,
                sell_submit_total_sec,
                sell_send_started_ts,
                sell_decision_to_send_sec,
                sell_queue_wait_sec,
            ) = _place_reduce_timed(sell_close_leg, decision_started_ts, sell_dispatch_ts)

        close_timing_payload = {
            "buy_close_latency_sec": float(buy_close_latency_sec),
            "sell_close_latency_sec": float(sell_close_latency_sec),
            "buy_send_ack_sec": float(buy_send_ack_sec),
            "sell_send_ack_sec": float(sell_send_ack_sec),
            "buy_ack_fill_sec": float(buy_ack_fill_sec),
            "sell_ack_fill_sec": float(sell_ack_fill_sec),
            "buy_submit_total_sec": float(buy_submit_total_sec),
            "sell_submit_total_sec": float(sell_submit_total_sec),
            "buy_decision_to_send_sec": float(buy_decision_to_send_sec),
            "sell_decision_to_send_sec": float(sell_decision_to_send_sec),
            "buy_queue_wait_sec": float(buy_queue_wait_sec),
            "sell_queue_wait_sec": float(sell_queue_wait_sec),
            "close_legs_send_delta_sec": float(abs(float(buy_send_started_ts) - float(sell_send_started_ts))),
            "close_legs_dispatch_delta_sec": float(abs(float(buy_dispatch_ts) - float(sell_dispatch_ts))),
            "close_decision_to_first_dispatch_sec": float(
                max(
                    0.0,
                    min(float(buy_dispatch_ts), float(sell_dispatch_ts)) - float(decision_started_ts),
                )
            ),
            "close_decision_to_all_dispatched_sec": float(
                max(
                    0.0,
                    max(float(buy_dispatch_ts), float(sell_dispatch_ts)) - float(decision_started_ts),
                )
            ),
        }

        def _with_close_timing(payload):
            out = dict(payload or {})
            out.update(close_timing_payload)
            return out

        ok_buy = bool(result_buy_close.get("ok"))
        ok_sell = bool(result_sell_close.get("ok"))
        if not ok_buy or not ok_sell:
            return _with_close_timing({
                "ok": False,
                "error": "force_close_failed",
                "requested_qty": requested_qty,
                "buy_close_leg": buy_close_leg,
                "sell_close_leg": sell_close_leg,
                "buy_close_result": result_buy_close,
                "sell_close_result": result_sell_close,
            })

        executed_buy = float(result_buy_close.get("executed_qty") or 0.0)
        executed_sell = float(result_sell_close.get("executed_qty") or 0.0)
        skipped_buy = bool(result_buy_close.get("skipped"))
        skipped_sell = bool(result_sell_close.get("skipped"))
        if skipped_buy and skipped_sell:
            return _with_close_timing({
                "ok": True,
                "requested_qty": requested_qty,
                "executed_qty": 0.0,
                "nothing_to_close": True,
                "buy_close_leg": buy_close_leg,
                "sell_close_leg": sell_close_leg,
                "buy_close_result": result_buy_close,
                "sell_close_result": result_sell_close,
            })
        if (skipped_buy and executed_sell > 0) or (skipped_sell and executed_buy > 0):
            return _with_close_timing({
                "ok": True,
                "requested_qty": requested_qty,
                "executed_qty": max(executed_buy, executed_sell),
                "unbalanced_close": True,
                "buy_close_leg": buy_close_leg,
                "sell_close_leg": sell_close_leg,
                "buy_close_result": result_buy_close,
                "sell_close_result": result_sell_close,
            })

        if (executed_buy <= 0) != (executed_sell <= 0):
            return _with_close_timing({
                "ok": False,
                "error": "force_close_unbalanced",
                "requested_qty": requested_qty,
                "buy_close_leg": buy_close_leg,
                "sell_close_leg": sell_close_leg,
                "buy_close_result": result_buy_close,
                "sell_close_result": result_sell_close,
            })

        executed_qty = min(executed_buy, executed_sell)

        return _with_close_timing({
            "ok": True,
            "requested_qty": requested_qty,
            "executed_qty": executed_qty,
            "buy_close_leg": buy_close_leg,
            "sell_close_leg": sell_close_leg,
            "buy_close_result": result_buy_close,
            "sell_close_result": result_sell_close,
        })
