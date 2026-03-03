import time

from core.i18n import tr
from core.utils.logger import get_logger
from core.utils.thread_pool import ThreadManager, Worker

logger = get_logger(__name__)


class SpreadStrategyRuntimeRecoveryMixin:
    def _build_emergency_leg_close_payload(self):
        state = self._strategy_state
        active_qty = float(self._to_float(getattr(state, "active_hedged_size", 0.0)) or 0.0)
        now = time.monotonic()

        def _remember_snapshot(q1, q2):
            self._strategy_emergency_last_qty = {1: float(q1), 2: float(q2)}
            self._strategy_emergency_last_ts = float(now)

        def _clear_candidate():
            self._strategy_emergency_candidate = None

        if active_qty <= 1e-12:
            _clear_candidate()
            _remember_snapshot(0.0, 0.0)
            return None

        leg_1 = self._leg_state_snapshot(1)
        leg_2 = self._leg_state_snapshot(2)
        qty_1 = max(0.0, float(self._to_float(leg_1.get("qty")) or 0.0))
        qty_2 = max(0.0, float(self._to_float(leg_2.get("qty")) or 0.0))
        tol = max(self._strategy_leg_presence_tolerance(), 1e-8)
        gap = abs(qty_1 - qty_2)
        if gap <= tol:
            _clear_candidate()
            _remember_snapshot(qty_1, qty_2)
            return None

        prev_ts = float(self._strategy_emergency_last_ts or 0.0)
        if prev_ts <= 0:
            _remember_snapshot(qty_1, qty_2)
            return None

        prev_qty_1 = max(0.0, float(self._to_float((self._strategy_emergency_last_qty or {}).get(1)) or 0.0))
        prev_qty_2 = max(0.0, float(self._to_float((self._strategy_emergency_last_qty or {}).get(2)) or 0.0))
        drop_1 = max(0.0, prev_qty_1 - qty_1)
        drop_2 = max(0.0, prev_qty_2 - qty_2)
        rise_1 = max(0.0, qty_1 - prev_qty_1)
        rise_2 = max(0.0, qty_2 - prev_qty_2)

        step_qty = abs(float(self._to_float(getattr(state, "step_qty", 0.0)) or 0.0))
        drop_trigger = max(tol * 2.0, step_qty * 0.40, active_qty * 0.010)

        lost_index = None
        survivor_index = None
        if drop_1 >= drop_trigger and drop_2 <= tol and rise_2 <= tol:
            lost_index, survivor_index = 1, 2
        elif drop_2 >= drop_trigger and drop_1 <= tol and rise_1 <= tol:
            lost_index, survivor_index = 2, 1

        busy_ops = bool(
            self._strategy_cycle_busy
            or self._strategy_worker is not None
            or self._strategy_reconcile_worker is not None
            or self._strategy_force_close_worker is not None
            or self._strategy_emergency_close_worker is not None
        )
        recent_submit_age = now - float(self._strategy_last_submit_ts or 0.0)
        notice_code = str(self._strategy_notice_code or "").strip().lower()
        quiet_ok = (
            (not busy_ops)
            and recent_submit_age >= float(self.EMERGENCY_AFTER_SUBMIT_SEC)
            and notice_code not in {"recoverable_retry", "step_miss"}
        )

        candidate = self._strategy_emergency_candidate if isinstance(self._strategy_emergency_candidate, dict) else None
        if not quiet_ok:
            _clear_candidate()
            _remember_snapshot(qty_1, qty_2)
            return None

        current_lost = None
        current_survivor = None
        if qty_1 + tol < qty_2:
            current_lost, current_survivor = 1, 2
        elif qty_2 + tol < qty_1:
            current_lost, current_survivor = 2, 1

        if current_lost is None:
            _clear_candidate()
            _remember_snapshot(qty_1, qty_2)
            return None

        current_lost_qty = qty_1 if current_lost == 1 else qty_2
        current_survivor_qty = qty_2 if current_lost == 1 else qty_1
        persistent_gap = max(0.0, float(current_survivor_qty) - float(current_lost_qty))
        persistent_trigger = max(drop_trigger, step_qty * 0.80, active_qty * 0.015)
        persistent_imbalance = persistent_gap >= persistent_trigger

        if candidate is None:
            use_lost_index = lost_index
            use_survivor_index = survivor_index
            if use_lost_index is None or use_survivor_index is None:
                if not persistent_imbalance:
                    _remember_snapshot(qty_1, qty_2)
                    return None
                use_lost_index = int(current_lost)
                use_survivor_index = int(current_survivor)
            if use_lost_index is None or use_survivor_index is None:
                _remember_snapshot(qty_1, qty_2)
                return None
            candidate = {
                "lost_index": int(use_lost_index),
                "survivor_index": int(use_survivor_index),
                "start_ts": float(now),
                "lost_qty_after": float(current_lost_qty),
            }
            self._strategy_emergency_candidate = candidate
            _remember_snapshot(qty_1, qty_2)
            return None

        if (
            int(candidate.get("lost_index") or 0) != int(current_lost)
            or int(candidate.get("survivor_index") or 0) != int(current_survivor)
        ):
            use_lost_index = lost_index
            use_survivor_index = survivor_index
            if use_lost_index is None or use_survivor_index is None:
                if not persistent_imbalance:
                    _clear_candidate()
                    _remember_snapshot(qty_1, qty_2)
                    return None
                use_lost_index = int(current_lost)
                use_survivor_index = int(current_survivor)
            if use_lost_index is None or use_survivor_index is None:
                _clear_candidate()
                _remember_snapshot(qty_1, qty_2)
                return None
            candidate = {
                "lost_index": int(use_lost_index),
                "survivor_index": int(use_survivor_index),
                "start_ts": float(now),
                "lost_qty_after": float(current_lost_qty),
            }
            self._strategy_emergency_candidate = candidate
            _remember_snapshot(qty_1, qty_2)
            return None

        # If "lost" leg came back, this was temporary desync, not external close.
        baseline_lost_after = float(self._to_float(candidate.get("lost_qty_after")) or 0.0)
        if current_lost_qty > baseline_lost_after + tol:
            _clear_candidate()
            _remember_snapshot(qty_1, qty_2)
            return None

        confirm_age = now - float(self._to_float(candidate.get("start_ts")) or now)
        if confirm_age < float(self.EMERGENCY_GAP_CONFIRM_SEC):
            _remember_snapshot(qty_1, qty_2)
            return None

        _clear_candidate()
        _remember_snapshot(qty_1, qty_2)

        bigger_leg = leg_2 if current_survivor == 2 else leg_1
        smaller_leg = leg_1 if current_lost == 1 else leg_2
        bigger_qty = float(current_survivor_qty)
        smaller_qty = float(current_lost_qty)
        lost_leg = smaller_leg
        survivor_leg = bigger_leg
        exchange_name = str(survivor_leg.get("exchange") or "").strip()
        pair = str(survivor_leg.get("pair") or "").strip().upper()
        direction = str(survivor_leg.get("direction") or "flat").strip().lower()
        if direction not in {"long", "short"}:
            direction = str(survivor_leg.get("expected_direction") or "flat").strip().lower()
        if direction not in {"long", "short"}:
            return None
        side = "sell" if direction == "long" else "buy"
        # Close only the lost delta: partial loss -> partial emergency close.
        close_qty = max(0.0, min(float(gap), float(bigger_qty)))
        if not exchange_name or not pair or close_qty <= tol:
            return None

        return {
            "exchange": exchange_name,
            "pair": pair,
            "side": side,
            "qty": close_qty,
            "gap_qty": float(gap),
            "lost_qty": float(smaller_qty),
            "survivor_qty": float(bigger_qty),
            "lost_index": int(lost_leg.get("index") or 0),
            "lost_exchange": str(lost_leg.get("exchange") or "").strip(),
            "lost_pair": str(lost_leg.get("pair") or "").strip().upper(),
            "survivor_index": int(survivor_leg.get("index") or 0),
            "survivor_direction": direction,
            "survivor_qty_before_close": float(bigger_qty),
        }

    def _start_emergency_leg_close(self, payload):
        data = payload if isinstance(payload, dict) else {}
        exchange_name = str(data.get("exchange") or "").strip()
        pair = str(data.get("pair") or "").strip().upper()
        side = str(data.get("side") or "").strip().lower()
        qty = float(self._to_float(data.get("qty")) or 0.0)
        if not exchange_name or not pair or side not in {"buy", "sell"} or qty <= 0:
            return False
        if self._strategy_cycle_busy or self._strategy_emergency_close_worker is not None:
            return False

        self._strategy_defer_session_finalize = True
        self._stop_strategy_loop()
        self._strategy_cycle_busy = True
        self._update_strategy_toggle_button()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()

        self._trace_runtime(
            "emergency_close_submit",
            exchange=exchange_name,
            pair=pair,
            side=side,
            qty=qty,
            gap_qty=data.get("gap_qty"),
            lost_qty=data.get("lost_qty"),
            survivor_qty=data.get("survivor_qty"),
            lost_index=data.get("lost_index"),
            lost_exchange=data.get("lost_exchange"),
            lost_pair=data.get("lost_pair"),
        )
        self._set_strategy_status(
            tr(
                "spread.strategy.warn.leg_lost_emergency_close",
                lost_exchange=data.get("lost_exchange") or f"#{data.get('lost_index') or '?'}",
                lost_pair=data.get("lost_pair") or "--",
                exchange=exchange_name,
                pair=pair,
                qty=f"{float(qty):.6f}",
            ),
            code="leg_lost",
        )
        self._update_strategy_state_label()

        worker = Worker(self._execute_emergency_leg_close_task, dict(data))
        self._strategy_emergency_close_worker = worker
        worker.signals.result.connect(self._on_emergency_leg_close_result)
        worker.signals.error.connect(self._on_emergency_leg_close_error)
        worker.signals.finished.connect(self._on_emergency_leg_close_finished)
        ThreadManager().start(worker)
        return True

    def _maybe_start_emergency_leg_close(self):
        if self._strategy_cycle_busy or self._strategy_emergency_close_worker is not None:
            return False
        payload = self._build_emergency_leg_close_payload()
        if payload is None:
            return False
        return bool(self._start_emergency_leg_close(payload))

    def _has_pending_emergency_candidate(self):
        candidate = self._strategy_emergency_candidate if isinstance(self._strategy_emergency_candidate, dict) else None
        if not isinstance(candidate, dict):
            return False
        try:
            lost_index = int(candidate.get("lost_index") or 0)
            survivor_index = int(candidate.get("survivor_index") or 0)
        except (TypeError, ValueError):
            return False
        return lost_index in {1, 2} and survivor_index in {1, 2}

    def _refresh_exchange_state_for_emergency_verify(self, exchange_name):
        name = str(exchange_name or "").strip()
        if not name:
            return False
        exchange = self.exchange_manager.get_exchange(name)
        if exchange is None or not bool(getattr(exchange, "is_connected", False)):
            return False
        try:
            exchange.refresh_state()
            return True
        except Exception as exc:
            self._trace_runtime(
                "emergency_verify_refresh_error",
                exchange=name,
                error=self._normalize_runtime_error_text(exc),
            )
            return False

    def _refresh_strategy_legs_for_emergency_verify(self, result_data):
        data = result_data if isinstance(result_data, dict) else {}
        names = []
        for key in ("exchange", "lost_exchange"):
            name = str(data.get(key) or "").strip()
            if name and name not in names:
                names.append(name)
        state = getattr(self, "_strategy_state", None)
        if state is not None:
            for attr in ("leg1_exchange", "leg2_exchange"):
                name = str(getattr(state, attr, "") or "").strip()
                if name and name not in names:
                    names.append(name)
        for name in names:
            self._refresh_exchange_state_for_emergency_verify(name)

    def _execute_emergency_leg_close_task(self, payload):
        data = payload if isinstance(payload, dict) else {}
        result = self._runtime_service.place_market_reduce_order(
            exchange_name=data.get("exchange"),
            pair=data.get("pair"),
            side=data.get("side"),
            qty=data.get("qty"),
        )
        if isinstance(result, dict):
            result.setdefault("exchange", data.get("exchange"))
            result.setdefault("pair", data.get("pair"))
            result.setdefault("side", data.get("side"))
            result.setdefault("qty", data.get("qty"))
            result.setdefault("gap_qty", data.get("gap_qty"))
            result.setdefault("lost_qty", data.get("lost_qty"))
            result.setdefault("survivor_qty", data.get("survivor_qty"))
            result.setdefault("lost_exchange", data.get("lost_exchange"))
            result.setdefault("lost_pair", data.get("lost_pair"))
            result.setdefault("lost_index", data.get("lost_index"))
        return result

    def _on_emergency_leg_close_result(self, result):
        data = result if isinstance(result, dict) else {}
        if not bool(data.get("ok")):
            self._trace_runtime(
                "emergency_close_result_fail",
                error=data.get("error"),
                details=data.get("details"),
                exchange=data.get("exchange"),
                pair=data.get("pair"),
                side=data.get("side"),
                qty=data.get("qty"),
            )
            self._set_strategy_status(
                tr(
                    "spread.strategy.error.leg_lost_emergency_failed",
                    reason=str(data.get("details") or data.get("error") or "unknown"),
                )
            )
            self._update_strategy_state_label()
            return

        self._trace_runtime(
            "emergency_close_result_ok",
            exchange=data.get("exchange"),
            pair=data.get("pair"),
            side=data.get("side"),
            qty=data.get("qty"),
            executed_qty=data.get("executed_qty"),
            skipped=data.get("skipped"),
            gap_qty=data.get("gap_qty"),
        )
        self._clear_entry_target_lock(reason="leg_lost_emergency_closed")
        self._refresh_strategy_legs_for_emergency_verify(data)
        self._refresh_strategy_exchanges_after_step(
            {
                "first_leg": {
                    "exchange": data.get("exchange"),
                    "pair": data.get("pair"),
                    "side": data.get("side"),
                }
            }
        )
        sync_legs = getattr(self, "_sync_strategy_observed_legs", None)
        if callable(sync_legs):
            sync_legs()

        leg1_qty = float(self._to_float(getattr(self._strategy_state, "leg1_qty", 0.0)) or 0.0)
        leg2_qty = float(self._to_float(getattr(self._strategy_state, "leg2_qty", 0.0)) or 0.0)
        remaining_qty = max(0.0, min(leg1_qty, leg2_qty))
        tol = self._strategy_leg_presence_tolerance()
        post_gap = abs(leg1_qty - leg2_qty)

        if post_gap > tol:
            self._trace_runtime(
                "emergency_close_verify_failed",
                gap_qty=post_gap,
                leg1_qty=leg1_qty,
                leg2_qty=leg2_qty,
                tol=tol,
                exchange=data.get("exchange"),
                pair=data.get("pair"),
            )
            self._set_strategy_status(
                tr(
                    "spread.strategy.error.leg_lost_emergency_failed",
                    reason=f"verify_gap={post_gap:.6f}",
                )
            )
            self._update_strategy_state_label()
            return

        if remaining_qty <= tol:
            self._strategy_state.active_hedged_size = 0.0
            self._clear_position_context()
        else:
            self._strategy_state.active_hedged_size = float(remaining_qty)
            leg1_dir = str(getattr(self._strategy_state, "leg1_direction", "flat") or "flat").strip().lower()
            leg2_dir = str(getattr(self._strategy_state, "leg2_direction", "flat") or "flat").strip().lower()
            if leg1_dir == "long" and leg2_dir == "short":
                self._strategy_state.position_buy_index = 1
                self._strategy_state.position_sell_index = 2
            elif leg1_dir == "short" and leg2_dir == "long":
                self._strategy_state.position_buy_index = 2
                self._strategy_state.position_sell_index = 1
            if self._strategy_state.position_buy_index == 1:
                self._strategy_state.position_buy_exchange = str(getattr(self._strategy_state, "leg1_exchange", "") or "").strip() or self._strategy_state.position_buy_exchange
                self._strategy_state.position_buy_pair = str(getattr(self._strategy_state, "leg1_pair", "") or "").strip().upper() or self._strategy_state.position_buy_pair
            elif self._strategy_state.position_buy_index == 2:
                self._strategy_state.position_buy_exchange = str(getattr(self._strategy_state, "leg2_exchange", "") or "").strip() or self._strategy_state.position_buy_exchange
                self._strategy_state.position_buy_pair = str(getattr(self._strategy_state, "leg2_pair", "") or "").strip().upper() or self._strategy_state.position_buy_pair
            if self._strategy_state.position_sell_index == 1:
                self._strategy_state.position_sell_exchange = str(getattr(self._strategy_state, "leg1_exchange", "") or "").strip() or self._strategy_state.position_sell_exchange
                self._strategy_state.position_sell_pair = str(getattr(self._strategy_state, "leg1_pair", "") or "").strip().upper() or self._strategy_state.position_sell_pair
            elif self._strategy_state.position_sell_index == 2:
                self._strategy_state.position_sell_exchange = str(getattr(self._strategy_state, "leg2_exchange", "") or "").strip() or self._strategy_state.position_sell_exchange
                self._strategy_state.position_sell_pair = str(getattr(self._strategy_state, "leg2_pair", "") or "").strip().upper() or self._strategy_state.position_sell_pair

        self._set_strategy_status(
            tr(
                "spread.strategy.info.leg_lost_emergency_done",
                exchange=str(data.get("exchange") or ""),
                pair=str(data.get("pair") or ""),
                qty=f"{float(self._to_float(data.get('executed_qty')) or 0.0):.6f}",
            ),
            code="leg_lost_closed",
        )
        self._refresh_spread_display()
        self._update_strategy_state_label()

    def _on_emergency_leg_close_error(self, error_text):
        self._trace_runtime("emergency_close_task_error", error=str(error_text or "").strip() or "unknown")
        self._set_strategy_status(
            tr(
                "spread.strategy.error.leg_lost_emergency_failed",
                reason=str(error_text or "").strip() or "unknown",
            )
        )
        self._update_strategy_state_label()

    def _on_emergency_leg_close_finished(self):
        self._strategy_emergency_close_worker = None
        self._strategy_cycle_busy = False
        self._capture_strategy_session_finish(reason="leg_lost_emergency_close")
        self._strategy_defer_session_finalize = False
        self._trace_runtime("emergency_close_finished")
        self._update_strategy_toggle_button()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()
        self._update_strategy_state_label()

    def _maybe_start_reconcile(self, spread_state):
        if self._strategy_cycle_busy or self._strategy_reconcile_worker is not None:
            return False
        payload = self._build_reconcile_payload(spread_state)
        now = time.monotonic()
        if payload is None:
            self._strategy_desync_since_ts = None
            return False
        if self._strategy_desync_since_ts is None:
            self._strategy_desync_since_ts = now
            return False
        if (now - self._strategy_desync_since_ts) < 1.2:
            return False
        if (now - float(self._strategy_last_submit_ts or 0.0)) < 0.8:
            return False

        self._strategy_cycle_busy = True
        self._trace_runtime(
            "reconcile_submit",
            mode=payload.get("mode"),
            index=payload.get("index"),
            exchange=payload.get("exchange"),
            pair=payload.get("pair"),
            side=payload.get("side"),
            qty=payload.get("qty"),
            gap=payload.get("gap"),
        )
        self._mark_strategy_submit()
        self._update_strategy_toggle_button()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()
        self._set_strategy_status(tr("spread.strategy.warn.recoverable_retry"), code="recoverable_retry")
        self._update_strategy_state_label()

        worker = Worker(self._execute_strategy_reconcile_task, payload)
        self._strategy_reconcile_worker = worker
        worker.signals.result.connect(self._on_strategy_reconcile_result)
        worker.signals.error.connect(self._on_strategy_reconcile_error)
        worker.signals.finished.connect(self._on_strategy_reconcile_finished)
        ThreadManager().start(worker)
        return True

    def _execute_strategy_reconcile_task(self, payload):
        data = payload if isinstance(payload, dict) else {}
        mode = str(data.get("mode") or "").strip().lower()
        if mode == "topup":
            result = self._runtime_service.place_limit_fok_order(
                exchange_name=data.get("exchange"),
                pair=data.get("pair"),
                side=data.get("side"),
                qty=data.get("qty"),
                max_slippage_pct=data.get("max_slippage_pct"),
                reduce_only=False,
            )
        elif mode == "trim":
            result = self._runtime_service.place_market_reduce_order(
                exchange_name=data.get("exchange"),
                pair=data.get("pair"),
                side=data.get("side"),
                qty=data.get("qty"),
            )
        else:
            result = {"ok": False, "error": "invalid_reconcile_mode"}
        if isinstance(result, dict):
            result.setdefault("reconcile_mode", mode)
            result.setdefault("exchange", data.get("exchange"))
            result.setdefault("pair", data.get("pair"))
            result.setdefault("side", data.get("side"))
            result.setdefault("qty", data.get("qty"))
            result.setdefault("index", data.get("index"))
        return result

    def _on_strategy_reconcile_result(self, result):
        data = result if isinstance(result, dict) else {}
        self._remember_leg_constraints(
            {
                "exchange": data.get("exchange"),
                "pair": data.get("pair"),
            },
            data,
            source="reconcile_result",
        )
        if not bool(data.get("ok")):
            error_code = str(data.get("error") or "").strip()
            self._trace_runtime(
                "reconcile_result_fail",
                error=error_code or "unknown",
                exchange=data.get("exchange"),
                pair=data.get("pair"),
                side=data.get("side"),
                qty=data.get("qty"),
                details=data.get("details"),
            )
            net_reason = self._runtime_extract_network_reason_from_result(data)
            if net_reason:
                self._runtime_set_degraded(
                    tr("spread.strategy.net_reason.order_error", error=net_reason),
                    source="reconcile_result",
                )
                self._update_strategy_state_label()
                return
            if error_code in {"order_not_filled", "order_submit_failed", "qty_below_min_notional", "qty_below_min", "qty_rounds_to_zero"}:
                self._set_strategy_status(tr("spread.strategy.warn.step_miss"), code="step_miss")
            else:
                self._set_strategy_status(tr(
                    "spread.strategy.error.execution_failed",
                    reason=error_code or "reconcile_failed",
                ))
            self._update_strategy_state_label()
            return

        skipped_reason = str(data.get("skipped") or "").strip()
        executed_qty = float(self._to_float(data.get("executed_qty")) or 0.0)
        if skipped_reason or executed_qty <= 1e-12:
            self._trace_runtime(
                "reconcile_result_retry",
                skipped=skipped_reason or "",
                executed_qty=executed_qty,
                exchange=data.get("exchange"),
                pair=data.get("pair"),
                side=data.get("side"),
                qty=data.get("qty"),
            )
            if self._strategy_desync_since_ts is None:
                self._strategy_desync_since_ts = time.monotonic()
            self._set_strategy_status(tr("spread.strategy.warn.recoverable_retry"), code="recoverable_retry")
            self._refresh_strategy_exchanges_after_step(
                {
                    "first_leg": {
                        "exchange": data.get("exchange"),
                        "pair": data.get("pair"),
                        "side": data.get("side"),
                    }
                }
            )
            self._update_strategy_state_label()
            return

        self._strategy_desync_since_ts = None
        self._trace_runtime(
            "reconcile_result_ok",
            mode=data.get("reconcile_mode"),
            executed_qty=executed_qty,
            exchange=data.get("exchange"),
            pair=data.get("pair"),
            side=data.get("side"),
            qty=data.get("qty"),
        )
        self._clear_strategy_status()
        self._refresh_spread_display()
        self._refresh_strategy_exchanges_after_step(
            {
                "first_leg": {
                    "exchange": data.get("exchange"),
                    "pair": data.get("pair"),
                    "side": data.get("side"),
                }
            }
        )

    def _on_strategy_reconcile_error(self, error_text):
        self._trace_runtime("reconcile_task_error", error=str(error_text or "").strip() or "unknown")
        if self._is_network_fault_text(error_text):
            self._runtime_set_degraded(
                tr("spread.strategy.net_reason.order_error", error=self._normalize_runtime_error_text(error_text)),
                source="reconcile_task",
            )
            self._update_strategy_state_label()
            return
        self._set_strategy_status(tr(
            "spread.strategy.error.execution_failed",
            reason=str(error_text or "").strip() or "reconcile_error",
        ))
        self._update_strategy_state_label()

    def _on_strategy_reconcile_finished(self):
        self._strategy_reconcile_worker = None
        self._strategy_cycle_busy = False
        self._trace_runtime("reconcile_finished")
        self._update_strategy_toggle_button()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()
        self._update_strategy_state_label()

    @staticmethod
    @staticmethod
    def _is_recoverable_step_failure(step_result):
        code = str((step_result or {}).get("error") or "").strip()
        return code in {"first_leg_failed", "second_leg_failed"}

    def _bind_position_context_from_step(self, step_result):
        data = step_result if isinstance(step_result, dict) else {}
        try:
            buy_idx = int(data.get("buy_index"))
        except (TypeError, ValueError):
            buy_idx = None
        try:
            sell_idx = int(data.get("sell_index"))
        except (TypeError, ValueError):
            sell_idx = None
        self._strategy_state.position_buy_index = buy_idx if buy_idx in {1, 2} else self._strategy_state.position_buy_index
        self._strategy_state.position_sell_index = sell_idx if sell_idx in {1, 2} else self._strategy_state.position_sell_index
        buy_exchange = str(data.get("buy_exchange") or "").strip()
        sell_exchange = str(data.get("sell_exchange") or "").strip()
        buy_pair = str(data.get("buy_pair") or "").strip().upper()
        sell_pair = str(data.get("sell_pair") or "").strip().upper()
        if buy_exchange:
            self._strategy_state.position_buy_exchange = buy_exchange
        if sell_exchange:
            self._strategy_state.position_sell_exchange = sell_exchange
        if buy_pair:
            self._strategy_state.position_buy_pair = buy_pair
        if sell_pair:
            self._strategy_state.position_sell_pair = sell_pair

