import time
from collections import deque

from PySide6.QtCore import QTimer

from core.i18n import tr
from core.utils.logger import get_logger
from core.utils.thread_pool import ThreadManager, Worker

logger = get_logger(__name__)


class SpreadStrategyRuntimeLifecycleMixin:
    def _init_strategy_runtime(self):
        self._strategy_cycle_busy = False
        self._strategy_worker = None
        self._strategy_last_step_payload = None
        self._strategy_force_close_worker = None
        self._strategy_emergency_close_worker = None
        self._strategy_reconcile_worker = None
        self._strategy_desync_since_ts = None
        self._strategy_last_submit_ts = 0.0
        self._strategy_notice_code = None
        self._strategy_notice_ts = 0.0
        self._strategy_entry_target_lock_qty = None
        self._strategy_min_qty_hints = {}
        self._strategy_defer_session_finalize = False
        self._strategy_emergency_last_qty = {1: 0.0, 2: 0.0}
        self._strategy_emergency_last_ts = 0.0
        self._strategy_emergency_candidate = None
        self._strategy_emergency_gate_trace_ts = 0.0
        self._runtime_quote_last_live_ts = {1: 0.0, 2: 0.0}
        self._runtime_network_degraded = False
        self._runtime_network_degraded_reason = ""
        self._runtime_network_degraded_since_ts = 0.0
        self._runtime_last_network_fault_ts = 0.0
        self._strategy_exchange_refresh_min_sec = 2.0
        self._strategy_exchange_last_refresh_ts = {}
        self._runtime_send_ack_samples = deque()
        self._runtime_send_ack_window_sec = 90.0
        self._runtime_ack_mode = "green"
        self._runtime_ack_mode_last_trace = ""
        self._runtime_ack_red_pause_until_ts = 0.0
        self._runtime_ack_red_pause_sec = 45.0
        self._runtime_ack_guard_last_trace_ts = 0.0

        self._strategy_timer = QTimer(self)
        self._strategy_timer.setInterval(self.STRATEGY_LOOP_INTERVAL_MS)
        self._strategy_timer.timeout.connect(self._on_strategy_loop_tick)
        self._trace_runtime("runtime_init", loop_ms=self.STRATEGY_LOOP_INTERVAL_MS)

    def _clear_position_context(self):
        self._strategy_state.position_buy_index = None
        self._strategy_state.position_sell_index = None
        self._strategy_state.position_buy_exchange = None
        self._strategy_state.position_sell_exchange = None
        self._strategy_state.position_buy_pair = None
        self._strategy_state.position_sell_pair = None
        self._clear_entry_target_lock()

    def _norm_pair(self, value):
        normalizer = getattr(self, "_normalize_pair", None)
        if callable(normalizer):
            return str(normalizer(value) or "").strip().upper()
        return str(value or "").strip().upper()

    def _strategy_session_exchange_names(self):
        state = getattr(self, "_strategy_state", None)
        names = []
        if state is not None:
            names.extend(
                [
                    str(getattr(state, "session_exchange_1", "") or "").strip(),
                    str(getattr(state, "session_exchange_2", "") or "").strip(),
                ]
            )

        if not any(names):
            left = self._column(1)
            right = self._column(2)
            names = [
                str(getattr(left, "selected_exchange", "") or "").strip() if left is not None else "",
                str(getattr(right, "selected_exchange", "") or "").strip() if right is not None else "",
            ]

        cleaned = []
        for name in names:
            if name and name not in cleaned:
                cleaned.append(name)
        return tuple(cleaned[:2])

    def _strategy_sum_exchange_balances(self, exchange_names):
        total = 0.0
        used = []
        for raw_name in exchange_names or ():
            name = str(raw_name or "").strip()
            if not name:
                continue
            exchange = self.exchange_manager.get_exchange(name)
            if exchange is None:
                continue
            balance = self._to_float(getattr(exchange, "balance", None))
            if balance is None:
                continue
            total += float(balance)
            used.append(name)
        if not used:
            return None, ()
        return float(total), tuple(used)

    def _capture_strategy_session_start(self):
        state = getattr(self, "_strategy_state", None)
        if state is None:
            return
        left = self._column(1)
        right = self._column(2)
        names = (
            str(getattr(left, "selected_exchange", "") or "").strip() if left is not None else "",
            str(getattr(right, "selected_exchange", "") or "").strip() if right is not None else "",
        )
        total, used = self._strategy_sum_exchange_balances(names)
        state.session_exchange_1 = used[0] if len(used) > 0 else None
        state.session_exchange_2 = used[1] if len(used) > 1 else None
        state.session_start_balance = total
        state.session_end_balance = total
        state.session_pnl_balance = 0.0 if total is not None else None
        self._trace_runtime(
            "session_start",
            exchange_1=state.session_exchange_1 or "",
            exchange_2=state.session_exchange_2 or "",
            start_balance=state.session_start_balance,
        )

    def _capture_strategy_session_finish(self, reason="stop"):
        state = getattr(self, "_strategy_state", None)
        if state is None:
            return
        names = self._strategy_session_exchange_names()
        total, used = self._strategy_sum_exchange_balances(names)
        if used:
            state.session_exchange_1 = used[0] if len(used) > 0 else None
            state.session_exchange_2 = used[1] if len(used) > 1 else None
        state.session_end_balance = total
        start_balance = self._to_float(getattr(state, "session_start_balance", None))
        if total is None or start_balance is None:
            state.session_pnl_balance = None
        else:
            state.session_pnl_balance = float(total) - float(start_balance)
        self._trace_runtime(
            "session_finish",
            reason=str(reason or "stop"),
            exchange_1=state.session_exchange_1 or "",
            exchange_2=state.session_exchange_2 or "",
            start_balance=state.session_start_balance,
            end_balance=state.session_end_balance,
            pnl=state.session_pnl_balance,
        )

    def _build_selection_signature(self):
        left = self._column(1)
        right = self._column(2)
        if left is None or right is None:
            return None
        left_ex = str(left.selected_exchange or "").strip()
        right_ex = str(right.selected_exchange or "").strip()
        left_pair = self._norm_pair(left.selected_pair)
        right_pair = self._norm_pair(right.selected_pair)
        if not left_ex or not right_ex or not left_pair or not right_pair:
            return None
        return frozenset({(left_ex, left_pair), (right_ex, right_pair)})

    def _build_position_signature(self):
        buy_ex = str(self._strategy_state.position_buy_exchange or "").strip()
        sell_ex = str(self._strategy_state.position_sell_exchange or "").strip()
        buy_pair = self._norm_pair(self._strategy_state.position_buy_pair)
        sell_pair = self._norm_pair(self._strategy_state.position_sell_pair)
        if not buy_ex or not sell_ex or not buy_pair or not sell_pair:
            return None
        return frozenset({(buy_ex, buy_pair), (sell_ex, sell_pair)})

    def _ensure_same_position_context(self):
        active_qty = float(self._strategy_state.active_hedged_size or 0.0)
        if active_qty <= 1e-12:
            return ""

        selection_sig = self._build_selection_signature()
        if selection_sig is None:
            return tr("spread.strategy.error.select_pairs")

        position_sig = self._build_position_signature()
        if position_sig is None:
            # Backward-safe: if there is active runtime size but context is missing,
            # bind it to current selected pair/exchanges.
            left = self._column(1)
            right = self._column(2)
            if left is None or right is None:
                return tr("spread.strategy.error.position_context_missing")
            self._strategy_state.position_buy_exchange = str(left.selected_exchange or "").strip() or None
            self._strategy_state.position_sell_exchange = str(right.selected_exchange or "").strip() or None
            self._strategy_state.position_buy_pair = self._norm_pair(left.selected_pair) or None
            self._strategy_state.position_sell_pair = self._norm_pair(right.selected_pair) or None
            return ""

        if selection_sig != position_sig:
            return tr("spread.strategy.error.other_position_active")
        return ""

    def _shutdown_strategy_runtime(self):
        timer = getattr(self, "_strategy_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        self._strategy_cycle_busy = False
        self._strategy_worker = None
        self._strategy_last_step_payload = None
        self._strategy_force_close_worker = None
        self._strategy_emergency_close_worker = None
        self._strategy_reconcile_worker = None
        self._strategy_desync_since_ts = None
        self._strategy_last_submit_ts = 0.0
        self._strategy_notice_code = None
        self._strategy_notice_ts = 0.0
        self._clear_entry_target_lock()
        self._strategy_min_qty_hints = {}
        self._strategy_defer_session_finalize = False
        self._strategy_emergency_last_qty = {1: 0.0, 2: 0.0}
        self._strategy_emergency_last_ts = 0.0
        self._strategy_emergency_candidate = None
        self._strategy_emergency_gate_trace_ts = 0.0
        self._runtime_quote_last_live_ts = {1: 0.0, 2: 0.0}
        self._runtime_network_degraded = False
        self._runtime_network_degraded_reason = ""
        self._runtime_network_degraded_since_ts = 0.0
        self._runtime_last_network_fault_ts = 0.0
        self._strategy_exchange_last_refresh_ts = {}
        self._runtime_send_ack_samples = deque()
        self._runtime_ack_mode = "green"
        self._runtime_ack_mode_last_trace = ""
        self._runtime_ack_red_pause_until_ts = 0.0
        self._runtime_ack_guard_last_trace_ts = 0.0
        runtime_service = getattr(self, "_runtime_service", None)
        runtime_shutdown = getattr(runtime_service, "shutdown", None)
        if callable(runtime_shutdown):
            runtime_shutdown()
        if hasattr(self, "_strategy_state"):
            self._strategy_state.is_running = False
        update_btn = getattr(self, "_update_strategy_toggle_button", None)
        if callable(update_btn):
            update_btn()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()
        self._trace_runtime("runtime_shutdown")

    def _on_strategy_toggle_clicked(self):
        if not hasattr(self, "_strategy_state"):
            return
        if self._strategy_state.is_running:
            self._stop_strategy_loop()
        else:
            self._start_strategy_loop()

    def _on_strategy_start_clicked(self):
        if not hasattr(self, "_strategy_state"):
            return
        if self._strategy_state.is_running:
            self._trace_runtime("start_click_skip", reason="already_running")
            return
        self._trace_runtime("start_click")
        self._start_strategy_loop()

    def _on_strategy_stop_clicked(self):
        if not hasattr(self, "_strategy_state"):
            return
        if not self._strategy_state.is_running:
            self._trace_runtime("stop_click_skip", reason="already_stopped")
            return
        self._trace_runtime("stop_click")
        self._stop_strategy_loop()

    def _start_strategy_loop(self):
        error_text = self._validate_strategy_prerequisites()
        if error_text:
            self._trace_runtime("start_rejected", reason=error_text)
            self._set_strategy_status(error_text)
            self._update_strategy_state_label()
            return

        same_pos_error = self._ensure_same_position_context()
        if same_pos_error:
            self._trace_runtime("start_rejected", reason=same_pos_error)
            self._set_strategy_status(same_pos_error)
            self._update_strategy_state_label()
            return

        self._clear_strategy_status()
        if float(self._strategy_state.active_hedged_size or 0.0) <= 1e-12:
            self._clear_position_context()
        self._strategy_defer_session_finalize = False
        self._capture_strategy_session_start()
        now_ts = time.monotonic()
        for idx in self._selected_runtime_indexes():
            column = self._column(idx)
            if column is None:
                continue
            if str(getattr(column, "quote_state", "") or "").strip().lower() == "live":
                if float(self._runtime_quote_last_live_ts.get(idx) or 0.0) <= 0:
                    self._runtime_quote_last_live_ts[idx] = now_ts
        self._strategy_state.is_running = True
        self._strategy_cycle_busy = False
        leg_1 = self._leg_state_snapshot(1)
        leg_2 = self._leg_state_snapshot(2)
        self._strategy_emergency_last_qty = {
            1: max(0.0, float(self._to_float(leg_1.get("qty")) or 0.0)),
            2: max(0.0, float(self._to_float(leg_2.get("qty")) or 0.0)),
        }
        self._strategy_emergency_last_ts = time.monotonic()
        self._strategy_emergency_candidate = None
        self._strategy_emergency_gate_trace_ts = 0.0
        self._update_strategy_toggle_button()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()
        self._update_strategy_state_label()
        self._strategy_timer.start()
        self._trace_runtime(
            "started",
            active_qty=float(self._strategy_state.active_hedged_size or 0.0),
            target_qty=getattr(self._strategy_state, "target_qty", 0.0),
            step_qty=getattr(self._strategy_state, "step_qty", 0.0),
        )
        self._on_strategy_loop_tick()

    def _stop_strategy_loop(self):
        prev_running = bool(getattr(self._strategy_state, "is_running", False))
        self._strategy_state.is_running = False
        if hasattr(self, "_strategy_timer"):
            self._strategy_timer.stop()
        self._strategy_cycle_busy = False
        self._strategy_worker = None
        self._strategy_emergency_close_worker = None
        self._strategy_reconcile_worker = None
        self._strategy_desync_since_ts = None
        self._strategy_emergency_last_qty = {1: 0.0, 2: 0.0}
        self._strategy_emergency_last_ts = 0.0
        self._strategy_emergency_candidate = None
        self._strategy_emergency_gate_trace_ts = 0.0
        self._runtime_clear_degraded()
        self._runtime_last_network_fault_ts = 0.0
        self._strategy_exchange_last_refresh_ts = {}
        self._runtime_send_ack_samples = deque()
        self._runtime_ack_mode = "green"
        self._runtime_ack_mode_last_trace = ""
        self._runtime_ack_red_pause_until_ts = 0.0
        self._runtime_ack_guard_last_trace_ts = 0.0
        if str(self._strategy_notice_code or "").strip().lower() in {"step_miss", "recoverable_retry", "network_degraded", "network_recovered", "leg_lost", "leg_lost_closed"}:
            self._clear_strategy_status()
        self._update_strategy_toggle_button()
        update_force_btn = getattr(self, "_update_strategy_force_close_button", None)
        if callable(update_force_btn):
            update_force_btn()
        if prev_running and not bool(getattr(self, "_strategy_defer_session_finalize", False)):
            self._capture_strategy_session_finish(reason="stop")
        self._update_strategy_state_label()
        if prev_running:
            self._trace_runtime(
                "stopped",
                active_qty=float(self._strategy_state.active_hedged_size or 0.0),
                phase=str(getattr(self._strategy_state, "phase", "") or ""),
            )

    def _clear_entry_target_lock(self, reason=None):
        was_locked = self._strategy_entry_target_lock_qty is not None
        self._strategy_entry_target_lock_qty = None
        if was_locked:
            self._trace_runtime("entry_lock_cleared", reason=reason or "manual")

    def _get_entry_target_lock_qty(self):
        value = self._to_float(getattr(self, "_strategy_entry_target_lock_qty", None))
        if value is None or value <= 0:
            return None
        return float(value)

    def _set_strategy_status(self, message, code=None):
        text = str(message or "")
        prev_text = str(getattr(self._strategy_state, "last_error", "") or "")
        self._strategy_state.last_error = text
        normalized = str(code or "").strip().lower()
        self._strategy_notice_code = normalized or None
        self._strategy_notice_ts = time.monotonic() if self._strategy_notice_code else 0.0
        if text != prev_text or normalized:
            self._trace_runtime("status", code=normalized or "none", text=text)

    def _clear_strategy_status(self):
        self._set_strategy_status("", code=None)

    def _clear_resolved_transient_notice(self):
        code = str(self._strategy_notice_code or "").strip().lower()
        if code == "leg_lost_closed":
            age = max(0.0, time.monotonic() - float(self._strategy_notice_ts or 0.0))
            if age >= 6.0:
                self._clear_strategy_status()
                self._update_strategy_state_label()
            return
        if code == "network_recovered":
            age = max(0.0, time.monotonic() - float(self._strategy_notice_ts or 0.0))
            if age >= 3.0:
                self._clear_strategy_status()
                self._update_strategy_state_label()
            return
        if code not in {"step_miss", "recoverable_retry"}:
            return

        state = self._strategy_state
        tol = self._strategy_reconcile_tolerance()
        desync = abs(float(self._to_float(getattr(state, "unbalanced_qty", 0.0)) or 0.0)) > tol
        phase = str(getattr(state, "phase", "") or "").strip().lower()
        pending_qty = 0.0
        if phase == "entry_signal":
            pending_qty = float(self._to_float(getattr(state, "next_entry_qty", 0.0)) or 0.0)
        elif phase == "exit_signal":
            pending_qty = float(self._to_float(getattr(state, "next_exit_qty", 0.0)) or 0.0)

        age = max(0.0, time.monotonic() - float(self._strategy_notice_ts or 0.0))
        should_clear = False
        if code == "recoverable_retry":
            should_clear = (not desync) or (age >= 8.0)
        elif code == "step_miss":
            no_active_retry = phase not in {"entry_signal", "exit_signal"} or pending_qty <= tol
            should_clear = (not desync and no_active_retry) or (age >= 6.0)

        if should_clear:
            self._clear_strategy_status()
            self._update_strategy_state_label()

    def _mark_strategy_submit(self):
        self._strategy_last_submit_ts = time.monotonic()

    def _expected_direction_for_leg(self, index):
        idx = int(index) if index in {1, 2} else None
        if idx not in {1, 2}:
            return "flat"
        state = self._strategy_state
        if int(getattr(state, "position_buy_index", 0) or 0) == idx:
            return "long"
        if int(getattr(state, "position_sell_index", 0) or 0) == idx:
            return "short"
        return "flat"

    def _leg_state_snapshot(self, index):
        state = self._strategy_state
        if int(index) == 1:
            exchange = str(getattr(state, "leg1_exchange", "") or "")
            pair = str(getattr(state, "leg1_pair", "") or "")
            qty = float(self._to_float(getattr(state, "leg1_qty", 0.0)) or 0.0)
            direction = str(getattr(state, "leg1_direction", "flat") or "flat").strip().lower()
        else:
            exchange = str(getattr(state, "leg2_exchange", "") or "")
            pair = str(getattr(state, "leg2_pair", "") or "")
            qty = float(self._to_float(getattr(state, "leg2_qty", 0.0)) or 0.0)
            direction = str(getattr(state, "leg2_direction", "flat") or "flat").strip().lower()
        if (not exchange or not pair) and hasattr(self, "_resolve_strategy_leg_context"):
            try:
                fallback_exchange, fallback_pair = self._resolve_strategy_leg_context(index)
            except Exception:
                fallback_exchange, fallback_pair = "", ""
            exchange = exchange or str(fallback_exchange or "")
            pair = pair or str(fallback_pair or "")
        return {
            "index": int(index),
            "exchange": exchange,
            "pair": str(pair or "").strip().upper(),
            "qty": max(0.0, qty),
            "direction": direction if direction in {"long", "short"} else "flat",
            "expected_direction": self._expected_direction_for_leg(index),
        }

    def _strategy_reconcile_tolerance(self):
        state = self._strategy_state
        step_qty = abs(float(self._to_float(getattr(state, "step_qty", 0.0)) or 0.0))
        target_qty = abs(float(self._to_float(getattr(state, "target_qty", 0.0)) or 0.0))
        candidates = [1e-8]
        if step_qty > 0:
            candidates.append(step_qty * 0.20)
        if target_qty > 0:
            candidates.append(target_qty * 0.005)
        leg_hints = []
        leg1 = self._leg_state_snapshot(1)
        leg2 = self._leg_state_snapshot(2)
        hint_1 = self._known_min_qty_hint(leg1.get("exchange"), leg1.get("pair"))
        hint_2 = self._known_min_qty_hint(leg2.get("exchange"), leg2.get("pair"))
        if hint_1 > 0:
            leg_hints.append(hint_1)
        if hint_2 > 0:
            leg_hints.append(hint_2)
        if leg_hints:
            # If exact equalization is below exchange minimums, do not spam retries forever.
            candidates.append(min(leg_hints) * 0.95)
        return max(candidates)

    def _strategy_leg_presence_tolerance(self):
        state = self._strategy_state
        step_qty = abs(float(self._to_float(getattr(state, "step_qty", 0.0)) or 0.0))
        target_qty = abs(float(self._to_float(getattr(state, "target_qty", 0.0)) or 0.0))
        candidates = [1e-8]
        if step_qty > 0:
            candidates.append(step_qty * 0.20)
        if target_qty > 0:
            candidates.append(target_qty * 0.002)
        return max(candidates)

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _resolve_strategy_best_price_hint(self, index, side):
        idx = int(index) if index in {1, 2} else None
        if idx not in {1, 2}:
            return None
        column = self._column(idx)
        if column is None:
            return None
        direction = str(side or "").strip().lower()
        if direction == "buy":
            raw = getattr(column, "quote_ask", None)
        elif direction == "sell":
            raw = getattr(column, "quote_bid", None)
        else:
            return None
        price = self._to_float(raw)
        if price is None or price <= 0:
            return None
        return float(price)

