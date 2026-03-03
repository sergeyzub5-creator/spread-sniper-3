import time

from core.i18n import tr
from core.utils.logger import get_logger
from core.utils.thread_pool import ThreadManager, Worker

logger = get_logger(__name__)


class SpreadStrategyRuntimeExecutionMixin:
    def _on_strategy_force_close_clicked(self):
        if self._strategy_cycle_busy:
            self._trace_runtime("force_close_skip", reason="strategy_busy")
            return
        if self._strategy_force_close_worker is not None:
            self._trace_runtime("force_close_skip", reason="force_close_busy")
            return

        active_qty = float(self._strategy_state.active_hedged_size or 0.0)
        if active_qty <= 1e-12:
            self._trace_runtime("force_close_skip", reason="no_active_position")
            self._set_strategy_status(tr("spread.strategy.error.no_position"))
            self._update_strategy_state_label()
            return

        buy_exchange = str(self._strategy_state.position_buy_exchange or "").strip()
        sell_exchange = str(self._strategy_state.position_sell_exchange or "").strip()
        buy_pair = str(self._strategy_state.position_buy_pair or "").strip()
        sell_pair = str(self._strategy_state.position_sell_pair or "").strip()
        if not buy_exchange or not sell_exchange or not buy_pair or not sell_pair:
            self._trace_runtime("force_close_skip", reason="position_context_missing")
            self._set_strategy_status(tr("spread.strategy.error.position_context_missing"))
            self._update_strategy_state_label()
            return

        self._strategy_defer_session_finalize = True
        self._stop_strategy_loop(reason="force_close")
        self._strategy_cycle_busy = True
        self._update_strategy_toggle_button()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()

        payload = {
            "buy_exchange": buy_exchange,
            "buy_pair": buy_pair,
            "sell_exchange": sell_exchange,
            "sell_pair": sell_pair,
            "qty": active_qty,
        }
        self._trace_runtime("force_close_submit", **payload)
        self._mark_strategy_submit()
        worker = Worker(self._force_close_market_task, payload)
        self._strategy_force_close_worker = worker
        worker.signals.result.connect(self._on_strategy_force_close_result)
        worker.signals.error.connect(self._on_strategy_force_close_error)
        worker.signals.finished.connect(self._on_strategy_force_close_finished)
        ThreadManager().start(worker)

    def _on_strategy_loop_tick(self):
        if not self._strategy_state.is_running:
            return
        if self._strategy_cycle_busy:
            return

        error_text = self._validate_strategy_prerequisites()
        if error_text:
            self._trace_runtime("loop_stop", reason="prerequisites_failed", details=error_text)
            self._set_strategy_status(error_text)
            self._stop_strategy_loop(reason="prerequisites_failed")
            return

        same_pos_error = self._ensure_same_position_context()
        if same_pos_error:
            self._trace_runtime("loop_stop", reason="position_context_mismatch", details=same_pos_error)
            self._set_strategy_status(same_pos_error)
            self._stop_strategy_loop(reason="position_context_mismatch")
            return

        spread_state = self._calculate_spread_state()
        spread_state = self._runtime_apply_ack_throttle_to_spread(spread_state)
        self._sync_strategy_state_from_spread(spread_state)
        self._clear_resolved_transient_notice()
        if self._maybe_start_emergency_leg_close():
            return
        if self._has_pending_emergency_candidate():
            now_ts = time.monotonic()
            if (now_ts - float(self._strategy_emergency_gate_trace_ts or 0.0)) >= 1.0:
                candidate = self._strategy_emergency_candidate if isinstance(self._strategy_emergency_candidate, dict) else {}
                age = max(0.0, now_ts - float(self._to_float(candidate.get("start_ts")) or now_ts))
                self._trace_runtime(
                    "loop_gate_emergency_candidate",
                    lost_index=candidate.get("lost_index"),
                    survivor_index=candidate.get("survivor_index"),
                    age=f"{age:.3f}",
                )
                self._strategy_emergency_gate_trace_ts = now_ts
            return
        if self._runtime_gate_cycle():
            return
        if self._maybe_start_reconcile(spread_state):
            return
        self._apply_strategy_signal_hysteresis()
        phase = str(self._strategy_state.phase or "")

        action = None
        qty = 0.0
        buy_index = None
        sell_index = None

        if phase == "entry_signal":
            action = "entry"
            qty = float(self._strategy_state.next_entry_qty or 0.0)
            buy_index = self._strategy_state.entry_buy_index
            sell_index = self._strategy_state.entry_sell_index
            qty *= float(getattr(self, "_runtime_ack_entry_chunk_mult", 1.0) or 1.0)
        elif phase == "exit_signal":
            action = "exit"
            qty = float(self._strategy_state.next_exit_qty or 0.0)
            buy_index = self._strategy_state.exit_buy_index
            sell_index = self._strategy_state.exit_sell_index

        if not action or qty <= 0:
            return

        buy_exchange = ""
        buy_pair = ""
        sell_exchange = ""
        sell_pair = ""

        if action == "entry":
            stale_indexes = self._runtime_entry_stale_quote_indexes()
            if stale_indexes:
                reason_text = tr(
                    "spread.strategy.net_reason.stale_quotes",
                    indexes=", ".join(str(v) for v in stale_indexes),
                )
                self._trace_runtime(
                    "entry_blocked_reason",
                    reason="quote_stale",
                    indexes=",".join(str(v) for v in stale_indexes),
                    stale_sec=f"{float(getattr(self, 'ENTRY_QUOTE_STALE_SEC', 0.8) or 0.8):.3f}",
                )
                self._set_strategy_status(
                    tr("spread.strategy.warn.net_degraded", reason=reason_text),
                    code="entry_quote_stale",
                )
                self._update_strategy_state_label()
                return
            if buy_index not in {1, 2} or sell_index not in {1, 2}:
                return
            buy_col = self._column(buy_index)
            sell_col = self._column(sell_index)
            if buy_col is None or sell_col is None:
                return
            if not buy_col.selected_exchange or not buy_col.selected_pair:
                return
            if not sell_col.selected_exchange or not sell_col.selected_pair:
                return
            buy_exchange = buy_col.selected_exchange
            buy_pair = buy_col.selected_pair
            sell_exchange = sell_col.selected_exchange
            sell_pair = sell_col.selected_pair
        else:
            # Exit legs must be opposite to entry:
            # close long on buy-exchange with SELL, close short on sell-exchange with BUY.
            buy_exchange = str(self._strategy_state.position_sell_exchange or "").strip()
            buy_pair = str(self._strategy_state.position_sell_pair or "").strip()
            sell_exchange = str(self._strategy_state.position_buy_exchange or "").strip()
            sell_pair = str(self._strategy_state.position_buy_pair or "").strip()
            buy_index = self._strategy_state.position_sell_index
            sell_index = self._strategy_state.position_buy_index
            if not buy_exchange or not sell_exchange or not buy_pair or not sell_pair:
                self._trace_runtime("loop_stop", reason="position_context_missing_on_exit")
                self._set_strategy_status(tr("spread.strategy.error.position_context_missing"))
                self._stop_strategy_loop(reason="position_context_missing_on_exit")
                return
            leg1_qty = float(self._to_float(getattr(self._strategy_state, "leg1_qty", 0.0)) or 0.0)
            leg2_qty = float(self._to_float(getattr(self._strategy_state, "leg2_qty", 0.0)) or 0.0)
            tol = float(self._strategy_reconcile_tolerance())
            if max(leg1_qty, leg2_qty) <= tol:
                # Local runtime context still has active size, but both actual legs are flat.
                # Skip redundant reduce-only submits and normalize state immediately.
                self._trace_runtime(
                    "loop_exit_skip_flat_legs",
                    leg1_qty=f"{leg1_qty:.12f}",
                    leg2_qty=f"{leg2_qty:.12f}",
                    tol=f"{tol:.12f}",
                )
                self._strategy_state.active_hedged_size = 0.0
                self._clear_position_context()
                self._clear_strategy_status()
                self._refresh_spread_display()
                return

        buy_best_price_hint = self._resolve_strategy_best_price_hint(buy_index, "buy")
        sell_best_price_hint = self._resolve_strategy_best_price_hint(sell_index, "sell")
        adaptive_order = self._runtime_choose_first_exchange(buy_exchange, sell_exchange)
        preferred_first_exchange = str((adaptive_order or {}).get("first_exchange") or "").strip()
        adaptive_reason = str((adaptive_order or {}).get("reason") or "").strip()
        left_stats = (adaptive_order or {}).get("left") or {}
        right_stats = (adaptive_order or {}).get("right") or {}
        self._trace_runtime(
            "adaptive_first_leg",
            action=action,
            first_exchange=preferred_first_exchange,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            buy_p95=left_stats.get("p95_sec"),
            sell_p95=right_stats.get("p95_sec"),
            buy_samples=left_stats.get("samples"),
            sell_samples=right_stats.get("samples"),
            reason=adaptive_reason,
        )

        self._strategy_cycle_busy = True
        self._update_strategy_toggle_button()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()

        payload = {
            "action": action,
            "buy_index": int(buy_index) if buy_index in {1, 2} else None,
            "sell_index": int(sell_index) if sell_index in {1, 2} else None,
            "buy_exchange": buy_exchange,
            "buy_pair": buy_pair,
            "sell_exchange": sell_exchange,
            "sell_pair": sell_pair,
            "qty": qty,
            "max_slippage_pct": float(self._strategy_config.max_slippage_pct or 0.0),
            "buy_best_price_hint": buy_best_price_hint,
            "sell_best_price_hint": sell_best_price_hint,
            "preferred_first_exchange": preferred_first_exchange,
            "adaptive_first_reason": adaptive_reason,
            "adaptive_buy_p95_sec": left_stats.get("p95_sec"),
            "adaptive_sell_p95_sec": right_stats.get("p95_sec"),
            "adaptive_buy_samples": left_stats.get("samples"),
            "adaptive_sell_samples": right_stats.get("samples"),
        }
        self._trace_runtime(
            "step_submit",
            action=payload.get("action"),
            buy_exchange=payload.get("buy_exchange"),
            buy_pair=payload.get("buy_pair"),
            sell_exchange=payload.get("sell_exchange"),
            sell_pair=payload.get("sell_pair"),
            qty=payload.get("qty"),
            buy_index=payload.get("buy_index"),
            sell_index=payload.get("sell_index"),
            slippage_pct=payload.get("max_slippage_pct"),
            buy_best_price_hint=payload.get("buy_best_price_hint"),
            sell_best_price_hint=payload.get("sell_best_price_hint"),
            preferred_first_exchange=payload.get("preferred_first_exchange"),
            adaptive_first_reason=payload.get("adaptive_first_reason"),
            adaptive_buy_p95_sec=payload.get("adaptive_buy_p95_sec"),
            adaptive_sell_p95_sec=payload.get("adaptive_sell_p95_sec"),
            adaptive_buy_samples=payload.get("adaptive_buy_samples"),
            adaptive_sell_samples=payload.get("adaptive_sell_samples"),
        )
        self._strategy_last_step_payload = dict(payload)
        self._mark_strategy_submit()

        worker = Worker(self._execute_strategy_step_task, payload)
        self._strategy_worker = worker
        worker.signals.result.connect(self._on_strategy_step_result)
        worker.signals.error.connect(self._on_strategy_step_error)
        worker.signals.finished.connect(self._on_strategy_step_finished)
        ThreadManager().start(worker)

    def _execute_strategy_step_task(self, payload):
        data = payload if isinstance(payload, dict) else {}
        result = self._runtime_service.execute_hedged_step(
            action=data.get("action"),
            buy_exchange=data.get("buy_exchange"),
            buy_pair=data.get("buy_pair"),
            sell_exchange=data.get("sell_exchange"),
            sell_pair=data.get("sell_pair"),
            qty=data.get("qty"),
            max_slippage_pct=data.get("max_slippage_pct"),
            buy_best_price_hint=data.get("buy_best_price_hint"),
            sell_best_price_hint=data.get("sell_best_price_hint"),
            preferred_first_exchange=data.get("preferred_first_exchange"),
            adaptive_first_reason=data.get("adaptive_first_reason"),
        )
        if isinstance(result, dict):
            result.setdefault("buy_index", data.get("buy_index"))
            result.setdefault("sell_index", data.get("sell_index"))
            result.setdefault("buy_exchange", data.get("buy_exchange"))
            result.setdefault("sell_exchange", data.get("sell_exchange"))
            result.setdefault("buy_pair", data.get("buy_pair"))
            result.setdefault("sell_pair", data.get("sell_pair"))
            result.setdefault("preferred_first_exchange", data.get("preferred_first_exchange"))
            result.setdefault("adaptive_first_reason", data.get("adaptive_first_reason"))
            result.setdefault("adaptive_buy_p95_sec", data.get("adaptive_buy_p95_sec"))
            result.setdefault("adaptive_sell_p95_sec", data.get("adaptive_sell_p95_sec"))
            result.setdefault("adaptive_buy_samples", data.get("adaptive_buy_samples"))
            result.setdefault("adaptive_sell_samples", data.get("adaptive_sell_samples"))
        return result

    def _on_strategy_step_result(self, result):
        data = result if isinstance(result, dict) else {}
        self._runtime_record_send_ack_from_step(data)
        self._remember_leg_constraints(data.get("first_leg"), data.get("first_result"), source="step_first")
        self._remember_leg_constraints(data.get("second_leg"), data.get("second_result"), source="step_second")
        if not bool(data.get("ok")):
            self._trace_runtime(
                "step_result_fail",
                action=data.get("action"),
                error=data.get("error"),
                first_result=data.get("first_result"),
                second_result=data.get("second_result"),
                rollback_result=data.get("rollback_result"),
                first_latency_sec=data.get("first_latency_sec"),
                second_latency_sec=data.get("second_latency_sec"),
                first_send_ack_sec=data.get("first_send_ack_sec"),
                second_send_ack_sec=data.get("second_send_ack_sec"),
                first_ack_fill_sec=data.get("first_ack_fill_sec"),
                second_ack_fill_sec=data.get("second_ack_fill_sec"),
                first_submit_total_sec=data.get("first_submit_total_sec"),
                second_submit_total_sec=data.get("second_submit_total_sec"),
                net_exposure_time_sec=data.get("net_exposure_time_sec"),
                hedge_escalation=data.get("hedge_escalation"),
                panic_unwind=data.get("panic_unwind"),
                first_decision_to_send_sec=data.get("first_decision_to_send_sec"),
                second_decision_to_send_sec=data.get("second_decision_to_send_sec"),
                first_queue_wait_sec=data.get("first_queue_wait_sec"),
                second_queue_wait_sec=data.get("second_queue_wait_sec"),
                legs_send_delta_sec=data.get("legs_send_delta_sec"),
                legs_dispatch_delta_sec=data.get("legs_dispatch_delta_sec"),
                decision_to_first_dispatch_sec=data.get("decision_to_first_dispatch_sec"),
                decision_to_all_dispatched_sec=data.get("decision_to_all_dispatched_sec"),
                first_exchange=data.get("first_exchange"),
                second_exchange=data.get("second_exchange"),
                execution_order_mode=data.get("execution_order_mode"),
                preferred_first_exchange=data.get("preferred_first_exchange"),
                adaptive_first_reason=data.get("adaptive_first_reason"),
            )
            net_reason = self._runtime_extract_network_reason_from_step(data)
            if net_reason:
                self._runtime_set_degraded(
                    tr("spread.strategy.net_reason.order_error", error=net_reason),
                    source="step_result",
                )
                self._update_strategy_state_label()
                return
            if self._handle_entry_min_limit_lock(data):
                return
            if self._is_transient_step_miss(data):
                self._set_strategy_status(tr("spread.strategy.warn.step_miss"), code="step_miss")
                self._update_strategy_state_label()
                return
            if self._is_recoverable_step_failure(data):
                self._bind_position_context_from_step(data)
                self._set_strategy_status(tr("spread.strategy.warn.recoverable_retry"), code="recoverable_retry")
                self._refresh_strategy_exchanges_after_step(data)
                self._update_strategy_state_label()
                return
            self._set_strategy_status(self._format_strategy_step_error(data))
            self._stop_strategy_loop(reason="step_result_fail")
            return

        action = str(data.get("action") or "").strip().lower()
        executed_qty = float(data.get("executed_qty") or 0.0)
        self._trace_runtime(
            "step_result_ok",
            action=action,
            executed_qty=executed_qty,
            requested_qty=data.get("requested_qty"),
            nothing_to_close=bool(data.get("nothing_to_close")),
            unbalanced_close=bool(data.get("unbalanced_close")),
            first_latency_sec=data.get("first_latency_sec"),
            second_latency_sec=data.get("second_latency_sec"),
            first_send_ack_sec=data.get("first_send_ack_sec"),
            second_send_ack_sec=data.get("second_send_ack_sec"),
            first_ack_fill_sec=data.get("first_ack_fill_sec"),
            second_ack_fill_sec=data.get("second_ack_fill_sec"),
            first_submit_total_sec=data.get("first_submit_total_sec"),
            second_submit_total_sec=data.get("second_submit_total_sec"),
            net_exposure_time_sec=data.get("net_exposure_time_sec"),
            hedge_escalation=data.get("hedge_escalation"),
            panic_unwind=data.get("panic_unwind"),
            first_decision_to_send_sec=data.get("first_decision_to_send_sec"),
            second_decision_to_send_sec=data.get("second_decision_to_send_sec"),
            first_queue_wait_sec=data.get("first_queue_wait_sec"),
            second_queue_wait_sec=data.get("second_queue_wait_sec"),
            legs_send_delta_sec=data.get("legs_send_delta_sec"),
            legs_dispatch_delta_sec=data.get("legs_dispatch_delta_sec"),
            decision_to_first_dispatch_sec=data.get("decision_to_first_dispatch_sec"),
            decision_to_all_dispatched_sec=data.get("decision_to_all_dispatched_sec"),
            first_exchange=data.get("first_exchange"),
            second_exchange=data.get("second_exchange"),
            execution_order_mode=data.get("execution_order_mode"),
            preferred_first_exchange=data.get("preferred_first_exchange"),
            adaptive_first_reason=data.get("adaptive_first_reason"),
        )
        if executed_qty <= 0 and not (action == "exit" and bool(data.get("nothing_to_close"))):
            self._set_strategy_status(tr(
                "spread.strategy.error.execution_failed",
                reason="invalid_executed_qty",
            ))
            self._stop_strategy_loop(reason="invalid_executed_qty")
            return

        if action == "entry":
            self._strategy_state.active_hedged_size = float(self._strategy_state.active_hedged_size or 0.0) + executed_qty
            try:
                buy_idx = int(data.get("buy_index"))
            except (TypeError, ValueError):
                buy_idx = None
            try:
                sell_idx = int(data.get("sell_index"))
            except (TypeError, ValueError):
                sell_idx = None
            self._strategy_state.position_buy_index = buy_idx if buy_idx in {1, 2} else None
            self._strategy_state.position_sell_index = sell_idx if sell_idx in {1, 2} else None
            self._strategy_state.position_buy_exchange = str(data.get("buy_exchange") or "").strip() or None
            self._strategy_state.position_sell_exchange = str(data.get("sell_exchange") or "").strip() or None
            self._strategy_state.position_buy_pair = str(data.get("buy_pair") or "").strip().upper() or None
            self._strategy_state.position_sell_pair = str(data.get("sell_pair") or "").strip().upper() or None
        elif action == "exit":
            if bool(data.get("nothing_to_close")):
                self._strategy_state.active_hedged_size = 0.0
                self._clear_position_context()
                self._arm_entry_cooldown_after_exit()
                self._clear_strategy_status()
                self._refresh_spread_display()
                self._refresh_strategy_exchanges_after_step(data)
                return
            current = float(self._strategy_state.active_hedged_size or 0.0)
            self._strategy_state.active_hedged_size = max(0.0, current - executed_qty)
            if self._strategy_state.active_hedged_size <= 1e-12:
                self._clear_position_context()
            self._arm_entry_cooldown_after_exit()

        self._clear_strategy_status()
        self._refresh_spread_display()
        self._refresh_strategy_exchanges_after_step(data)

    def _refresh_strategy_exchanges_after_step(self, step_result):
        names = set()
        first = (step_result.get("first_leg") or {}) if isinstance(step_result, dict) else {}
        second = (step_result.get("second_leg") or {}) if isinstance(step_result, dict) else {}
        for leg in (first, second):
            name = str(leg.get("exchange") or "").strip()
            if name:
                names.add(name)

        for name in sorted(names):
            self._refresh_strategy_exchange_async(name, reason="post_step", force=False)

    def _on_strategy_step_error(self, error_text):
        self._trace_runtime("step_task_error", error=str(error_text or "").strip() or "unknown")
        if self._is_network_fault_text(error_text):
            self._runtime_set_degraded(
                tr("spread.strategy.net_reason.order_error", error=self._normalize_runtime_error_text(error_text)),
                source="step_task",
            )
            self._update_strategy_state_label()
            return
        self._set_strategy_status(tr(
            "spread.strategy.error.execution_failed",
            reason=str(error_text or "").strip() or "unknown",
        ))
        self._stop_strategy_loop(reason="step_task_error")

    def _on_strategy_step_finished(self):
        self._strategy_worker = None
        self._strategy_last_step_payload = None
        self._strategy_cycle_busy = False
        self._trace_runtime("step_finished")
        self._update_strategy_toggle_button()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()

    def _force_close_market_task(self, payload):
        data = payload if isinstance(payload, dict) else {}
        return self._runtime_service.force_close_market(
            buy_exchange=data.get("buy_exchange"),
            buy_pair=data.get("buy_pair"),
            sell_exchange=data.get("sell_exchange"),
            sell_pair=data.get("sell_pair"),
            qty=data.get("qty"),
        )

    def _on_strategy_force_close_result(self, result):
        data = result if isinstance(result, dict) else {}
        if not bool(data.get("ok")):
            self._trace_runtime(
                "force_close_result_fail",
                error=data.get("error"),
                buy_close_result=data.get("buy_close_result"),
                sell_close_result=data.get("sell_close_result"),
            )
            self._set_strategy_status(self._format_strategy_step_error(data))
            self._update_strategy_state_label()
            return

        self._trace_runtime(
            "force_close_result_ok",
            requested_qty=data.get("requested_qty"),
            executed_qty=data.get("executed_qty"),
            nothing_to_close=bool(data.get("nothing_to_close")),
            unbalanced_close=bool(data.get("unbalanced_close")),
        )
        self._strategy_state.active_hedged_size = 0.0
        self._clear_position_context()
        self._clear_entry_target_lock(reason="force_closed")
        self._arm_entry_cooldown_after_exit()
        self._clear_strategy_status()
        self._refresh_spread_display()
        self._refresh_strategy_exchanges_after_step(
            {
                "first_leg": data.get("buy_close_leg") or {},
                "second_leg": data.get("sell_close_leg") or {},
            }
        )

    def _on_strategy_force_close_error(self, error_text):
        self._trace_runtime("force_close_task_error", error=str(error_text or "").strip() or "unknown")
        self._set_strategy_status(tr(
            "spread.strategy.error.force_close_failed",
            reason=str(error_text or "").strip() or "unknown",
        ))
        self._update_strategy_state_label()

    def _on_strategy_force_close_finished(self):
        self._strategy_force_close_worker = None
        self._strategy_cycle_busy = False
        self._capture_strategy_session_finish(reason="force_close")
        self._strategy_defer_session_finalize = False
        self._trace_runtime("force_close_finished")
        self._update_strategy_toggle_button()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()
        self._update_strategy_state_label()

    def _runtime_apply_ack_throttle_to_spread(self, spread_state):
        state = dict(spread_state or {})
        snapshot = self._runtime_ack_mode_snapshot()
        mode = str(snapshot.get("mode") or "green").strip().lower()
        entry_boost_pct = float(snapshot.get("entry_boost_pct") or 0.0)
        entry_chunk_mult = max(0.0, float(snapshot.get("entry_chunk_mult") or 1.0))
        pause_active = bool(snapshot.get("pause_active"))

        self._runtime_ack_entry_chunk_mult = entry_chunk_mult
        self._runtime_ack_mode_name = mode

        effective_entry_threshold = float(self._strategy_config.entry_threshold_pct or 0.0) + float(entry_boost_pct)
        state["entry_threshold_effective_pct"] = float(effective_entry_threshold)
        state["ack_mode"] = mode
        state["ack_send_ack_p95_sec"] = float(snapshot.get("p95_sec") or 0.0)
        state["ack_send_ack_samples"] = int(snapshot.get("samples") or 0)
        state["ack_pause_active"] = bool(pause_active)
        state["ack_chunk_mult"] = float(entry_chunk_mult)

        signal = str(state.get("signal") or "").strip().lower()
        effective_edge = float(self._to_float(state.get("effective_edge_pct")) or 0.0)
        if signal == "entry":
            if pause_active:
                state["signal"] = None
                state["phase"] = "wait_entry"
                now_ts = time.monotonic()
                last_ts = float(getattr(self, "_runtime_ack_guard_last_trace_ts", 0.0) or 0.0)
                # Limit repetitive trace spam while RED pause is active.
                if (now_ts - last_ts) >= 1.0:
                    self._trace_runtime(
                        "ack_guard_block_entry",
                        mode=mode,
                        reason="red_pause",
                        p95=f"{float(snapshot.get('p95_sec') or 0.0):.3f}",
                        pause_left_sec=f"{float(snapshot.get('pause_left_sec') or 0.0):.2f}",
                    )
                    self._runtime_ack_guard_last_trace_ts = now_ts
            elif effective_edge + 1e-12 < effective_entry_threshold:
                state["signal"] = None
                state["phase"] = "wait_entry"
                self._trace_runtime(
                    "ack_guard_raise_entry_threshold",
                    mode=mode,
                    edge=f"{effective_edge:.4f}",
                    threshold=f"{effective_entry_threshold:.4f}",
                )
        return state
