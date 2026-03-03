import time

from core.i18n import tr
from core.utils.logger import get_logger
from core.utils.thread_pool import ThreadManager, Worker

logger = get_logger(__name__)


class SpreadStrategyRuntimeConstraintsMixin:
    def _constraint_key(self, exchange_name, pair):
        return (
            str(exchange_name or "").strip().lower(),
            self._norm_pair(pair),
        )

    def _remember_min_qty_hint(self, exchange_name, pair, min_qty, source=None):
        qty = self._to_float(min_qty)
        if qty is None or qty <= 0:
            return
        key = self._constraint_key(exchange_name, pair)
        if not key[0] or not key[1]:
            return
        previous = self._to_float(self._strategy_min_qty_hints.get(key))
        if previous is None or qty > previous:
            self._strategy_min_qty_hints[key] = float(qty)
            self._trace_runtime(
                "min_qty_hint_set",
                exchange=exchange_name,
                pair=pair,
                min_qty=float(qty),
                source=source or "",
            )

    def _known_min_qty_hint(self, exchange_name, pair):
        key = self._constraint_key(exchange_name, pair)
        return float(self._to_float(self._strategy_min_qty_hints.get(key)) or 0.0)

    def _extract_min_qty_from_result(self, order_result):
        payload = order_result if isinstance(order_result, dict) else {}
        direct = self._to_float(payload.get("min_qty"))
        if direct is not None and direct > 0:
            return float(direct)

        order_notional = self._to_float(payload.get("order_notional"))
        min_notional = self._to_float(payload.get("min_notional"))
        aligned_qty = self._to_float(payload.get("aligned_qty"))
        if (
            order_notional is not None
            and order_notional > 0
            and min_notional is not None
            and min_notional > 0
            and aligned_qty is not None
            and aligned_qty > 0
        ):
            estimated = float(aligned_qty) * (float(min_notional) / float(order_notional))
            if estimated > 0:
                return estimated
        return None

    def _remember_leg_constraints(self, leg, order_result, source=None):
        leg_data = leg if isinstance(leg, dict) else {}
        result = order_result if isinstance(order_result, dict) else {}
        exchange_name = str(leg_data.get("exchange") or result.get("exchange") or "").strip()
        pair = str(leg_data.get("pair") or result.get("pair") or "").strip().upper()
        min_qty = self._extract_min_qty_from_result(result)
        if min_qty is not None:
            self._remember_min_qty_hint(exchange_name, pair, min_qty, source=source or "order_result")

    @staticmethod
    @staticmethod
    def _is_qty_constraint_error_code(error_code):
        code = str(error_code or "").strip().lower()
        return code in {"qty_below_min", "qty_below_min_notional", "qty_rounds_to_zero"}

    def _handle_entry_min_limit_lock(self, step_result):
        data = step_result if isinstance(step_result, dict) else {}
        if str(data.get("action") or "").strip().lower() != "entry":
            return False

        active_qty = float(self._to_float(getattr(self._strategy_state, "active_hedged_size", 0.0)) or 0.0)
        remaining_entry = float(self._to_float(getattr(self._strategy_state, "remaining_entry_qty", 0.0)) or 0.0)
        if active_qty <= 1e-12 or remaining_entry <= 1e-12:
            return False

        min_candidates = []
        for leg_key, result_key in (("first_leg", "first_result"), ("second_leg", "second_result")):
            leg = data.get(leg_key) or {}
            result = data.get(result_key) or {}
            self._remember_leg_constraints(leg, result, source=f"{leg_key}_failed")
            if not self._is_qty_constraint_error_code(result.get("error")):
                continue
            hint = self._extract_min_qty_from_result(result)
            if hint is not None and hint > 0:
                min_candidates.append(float(hint))

        if not min_candidates:
            first_leg = data.get("first_leg") or {}
            second_leg = data.get("second_leg") or {}
            hint_1 = self._known_min_qty_hint(first_leg.get("exchange"), first_leg.get("pair"))
            hint_2 = self._known_min_qty_hint(second_leg.get("exchange"), second_leg.get("pair"))
            if hint_1 > 0:
                min_candidates.append(float(hint_1))
            if hint_2 > 0:
                min_candidates.append(float(hint_2))

        if not min_candidates:
            return False

        required_min = max(min_candidates)
        if remaining_entry > (required_min * 1.05):
            return False

        self._strategy_entry_target_lock_qty = float(active_qty)
        self._trace_runtime(
            "entry_lock_by_min",
            active_qty=active_qty,
            remaining_entry=remaining_entry,
            min_required=required_min,
        )
        self._set_strategy_status(
            tr(
                "spread.strategy.warn.entry_locked_by_min",
                remaining=f"{remaining_entry:.6f}",
                min_qty=f"{required_min:.6f}",
            ),
            code="entry_locked",
        )
        self._refresh_spread_display()
        self._refresh_strategy_exchanges_after_step(data)
        self._update_strategy_state_label()
        return True

    def _validate_strategy_prerequisites(self):
        left = self._column(1)
        right = self._column(2)
        if left is None or right is None:
            return tr("spread.strategy.error.select_exchanges")

        if not left.selected_exchange or not right.selected_exchange:
            return tr("spread.strategy.error.select_exchanges")

        if not left.selected_pair or not right.selected_pair:
            return tr("spread.strategy.error.select_pairs")
        if not bool(getattr(self, "_spread_armed", False)):
            return tr("spread.strategy.error.arm_spread")

        left_exchange = self.exchange_manager.get_exchange(left.selected_exchange)
        right_exchange = self.exchange_manager.get_exchange(right.selected_exchange)
        if left_exchange is None or right_exchange is None:
            return tr("spread.strategy.error.exchange_missing")
        if not left_exchange.is_connected or not right_exchange.is_connected:
            return tr("spread.strategy.error.exchange_not_connected")
        return ""

    @staticmethod
    @staticmethod
    def _format_strategy_step_error(step_result):
        result = step_result if isinstance(step_result, dict) else {}
        code = str(result.get("error") or "").strip()
        if code == "first_leg_failed":
            leg = result.get("first_leg") or {}
            details = result.get("first_result") or {}
            return tr(
                "spread.strategy.error.first_leg_failed",
                exchange=str(leg.get("exchange") or "?"),
                reason=str(details.get("error") or "unknown"),
            )
        if code == "second_leg_failed":
            leg = result.get("second_leg") or {}
            details = result.get("second_result") or {}
            return tr(
                "spread.strategy.error.second_leg_failed",
                exchange=str(leg.get("exchange") or "?"),
                reason=str(details.get("error") or "unknown"),
            )
        if code == "force_close_unbalanced":
            return tr("spread.strategy.error.force_close_unbalanced")
        return tr("spread.strategy.error.execution_failed", reason=code or "unknown")

    @staticmethod
    @staticmethod
    def _is_transient_step_miss(step_result):
        result = step_result if isinstance(step_result, dict) else {}
        if str(result.get("error") or "") not in {"first_leg_failed", "second_leg_failed"}:
            return False
        leg_payload = result.get("first_result") if result.get("error") == "first_leg_failed" else result.get("second_result")
        if not isinstance(leg_payload, dict):
            return False
        inner_error = str(leg_payload.get("error") or "").strip()
        if inner_error == "order_not_filled":
            return True
        if inner_error != "order_submit_failed":
            return False
        details = str(leg_payload.get("details") or "").lower()
        return ("-5021" in details) or ("fok" in details and "rejected" in details)

    def _build_reconcile_payload(self, spread_state):
        state = self._strategy_state
        leg1 = self._leg_state_snapshot(1)
        leg2 = self._leg_state_snapshot(2)
        qty_1 = float(leg1.get("qty") or 0.0)
        qty_2 = float(leg2.get("qty") or 0.0)
        gap = abs(qty_1 - qty_2)
        tol = self._strategy_reconcile_tolerance()

        if max(qty_1, qty_2) <= tol or gap <= tol:
            return None

        smaller = leg1 if qty_1 <= qty_2 else leg2
        bigger = leg2 if qty_1 <= qty_2 else leg1
        smaller_qty = float(smaller.get("qty") or 0.0)
        bigger_qty = float(bigger.get("qty") or 0.0)

        effective_edge = float(self._to_float((spread_state or {}).get("effective_edge_pct")) or 0.0)
        entry_threshold = float(self._strategy_config.entry_threshold_pct or 0.0)
        target_qty = float(self._to_float(getattr(state, "target_qty", 0.0)) or 0.0)

        can_topup = (
            effective_edge >= entry_threshold
            and target_qty > tol
            and smaller_qty < (target_qty - tol)
            and str(smaller.get("expected_direction") or "flat") in {"long", "short"}
        )

        if can_topup:
            side = "buy" if str(smaller.get("expected_direction")) == "long" else "sell"
            qty = min(gap, max(0.0, target_qty - smaller_qty))
            leg = smaller
            mode = "topup"
        else:
            # Full rebalance mode: if we cannot top-up safely, trim oversized leg.
            # For reduce orders use only ACTUAL observed leg direction.
            observed_direction = str(bigger.get("direction") or "flat").strip().lower()
            direction = observed_direction
            if direction not in {"long", "short"}:
                return None
            side = "sell" if direction == "long" else "buy"
            qty = gap
            leg = bigger
            mode = "trim"

        qty = max(0.0, float(qty or 0.0))
        if qty <= tol:
            return None

        exchange_name = str(leg.get("exchange") or "").strip()
        pair = str(leg.get("pair") or "").strip().upper()
        if not exchange_name or not pair:
            return None

        leg_min_qty = self._known_min_qty_hint(exchange_name, pair)
        if leg_min_qty > 0 and qty + tol < leg_min_qty:
            fallback = None
            if mode == "topup":
                observed_direction = str(bigger.get("direction") or "flat").strip().lower()
                if observed_direction in {"long", "short"}:
                    trim_side = "sell" if observed_direction == "long" else "buy"
                    trim_exchange = str(bigger.get("exchange") or "").strip()
                    trim_pair = str(bigger.get("pair") or "").strip().upper()
                    trim_min_qty = self._known_min_qty_hint(trim_exchange, trim_pair)
                    trim_qty = gap
                    if (
                        trim_exchange
                        and trim_pair
                        and trim_qty > tol
                        and (trim_min_qty <= 0 or trim_qty + tol >= trim_min_qty)
                    ):
                        fallback = {
                            "mode": "trim",
                            "index": int(bigger.get("index") or 0),
                            "exchange": trim_exchange,
                            "pair": trim_pair,
                            "side": trim_side,
                            "qty": float(trim_qty),
                            "gap": gap,
                            "max_slippage_pct": float(self._strategy_config.max_slippage_pct or 0.0),
                        }
            elif mode == "trim" and can_topup:
                topup_exchange = str(smaller.get("exchange") or "").strip()
                topup_pair = str(smaller.get("pair") or "").strip().upper()
                topup_side = "buy" if str(smaller.get("expected_direction")) == "long" else "sell"
                topup_qty = min(gap, max(0.0, target_qty - smaller_qty))
                topup_min_qty = self._known_min_qty_hint(topup_exchange, topup_pair)
                if (
                    topup_exchange
                    and topup_pair
                    and topup_qty > tol
                    and (topup_min_qty <= 0 or topup_qty + tol >= topup_min_qty)
                ):
                    fallback = {
                        "mode": "topup",
                        "index": int(smaller.get("index") or 0),
                        "exchange": topup_exchange,
                        "pair": topup_pair,
                        "side": topup_side,
                        "qty": float(topup_qty),
                        "gap": gap,
                        "max_slippage_pct": float(self._strategy_config.max_slippage_pct or 0.0),
                    }

            if fallback is not None:
                self._trace_runtime(
                    "reconcile_fallback_mode",
                    from_mode=mode,
                    to_mode=fallback.get("mode"),
                    gap=gap,
                    failed_min_qty=leg_min_qty,
                )
                return fallback

            self._trace_runtime(
                "reconcile_skip_below_min",
                mode=mode,
                exchange=exchange_name,
                pair=pair,
                qty=qty,
                min_qty=leg_min_qty,
                gap=gap,
            )
            return None

        return {
            "mode": mode,
            "index": int(leg.get("index") or 0),
            "exchange": exchange_name,
            "pair": pair,
            "side": side,
            "qty": qty,
            "gap": gap,
            "max_slippage_pct": float(self._strategy_config.max_slippage_pct or 0.0),
        }

