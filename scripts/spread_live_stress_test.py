#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.data.settings import SettingsManager
from core.i18n import get_language_manager, tr
from core.utils.logger import get_logger, setup_logger
from core.utils.thread_pool import ThreadManager
from ui.main_window import MainWindow
from ui.styles import get_theme_manager


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _percentile(values, pct):
    series = [float(v) for v in (values or []) if isinstance(v, (int, float))]
    if not series:
        return 0.0
    if len(series) == 1:
        return float(series[0])
    p = max(0.0, min(100.0, float(pct)))
    ordered = sorted(series)
    rank = (len(ordered) - 1) * (p / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def _utc_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class SpreadLiveStressRunner(QObject):
    def __init__(self, app, duration_sec, inject_leg_drop, leg_drop_interval_sec, report_path, status_path):
        super().__init__()
        self.app = app
        self.duration_sec = max(10, int(duration_sec))
        self.inject_leg_drop = bool(inject_leg_drop)
        self.leg_drop_interval_sec = max(20, int(leg_drop_interval_sec))
        self.report_path = report_path
        self.status_path = status_path
        self.logger = get_logger("spread.stress_test")

        self.window = None
        self.tab = None
        self.started_ts = 0.0
        self.stop_requested = False
        self.start_attempts = 0
        self.pending_submit = None
        self.completed_trades = []
        self.status_events = []
        self.trace_events = []
        self.snapshots = []
        self.injected_events = []
        self.counters = {
            "step_submit": 0,
            "step_ok": 0,
            "step_fail": 0,
            "network_degraded": 0,
            "network_resumed": 0,
            "recoverable_retry": 0,
            "step_miss": 0,
            "leg_lost": 0,
            "leg_lost_closed": 0,
            "emergency_verify_failed": 0,
            "forced_close_ok": 0,
            "forced_close_fail": 0,
        }
        self._finalized = False
        self._run_started_mono = 0.0
        self._run_started_iso = ""
        self._run_finished_iso = ""
        self._last_summary_status = ""
        self._debug_log_path = None
        self._debug_log_offset = 0
        self._hooked = False

        self.start_timer = QTimer(self)
        self.start_timer.setInterval(2500)
        self.start_timer.timeout.connect(self._try_start_strategy)

        self.finish_timer = QTimer(self)
        self.finish_timer.setSingleShot(True)
        self.finish_timer.timeout.connect(self._finish_run)

        self.snapshot_timer = QTimer(self)
        self.snapshot_timer.setInterval(1000)
        self.snapshot_timer.timeout.connect(self._capture_snapshot)

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1500)
        self.status_timer.timeout.connect(self._write_status)

        self.leg_drop_timer = QTimer(self)
        self.leg_drop_timer.setInterval(self.leg_drop_interval_sec * 1000)
        self.leg_drop_timer.timeout.connect(self._inject_leg_drop_if_possible)

    def run(self):
        self._run_started_mono = time.monotonic()
        self._run_started_iso = _utc_iso()
        self._prepare_log_tail_tracking()
        self._write_status(extra={"phase": "boot"})

        self.window = MainWindow()
        self.window.exchange_manager.connect_all_async()
        self.tab = self.window.spread_sniping_tab
        self._install_hooks()

        self.start_timer.start()
        self.finish_timer.start(self.duration_sec * 1000)
        self.snapshot_timer.start()
        self.status_timer.start()
        if self.inject_leg_drop:
            self.leg_drop_timer.start()

        self.logger.info("stress_test.started duration_sec=%s", self.duration_sec)

    def _install_hooks(self):
        if self._hooked or self.tab is None:
            return
        self._hooked = True

        original_trace = self.tab._trace

        def traced(event, **fields):
            try:
                self._on_trace_event(event, fields)
            except Exception:
                self.logger.exception("stress_test.trace_hook_error")
            return original_trace(event, **fields)

        self.tab._trace = traced

        original_step_result = self.tab._on_strategy_step_result

        def step_result_hook(result):
            try:
                self._on_step_result(result)
            except Exception:
                self.logger.exception("stress_test.step_result_hook_error")
            return original_step_result(result)

        self.tab._on_strategy_step_result = step_result_hook

        original_force_close_result = self.tab._on_strategy_force_close_result

        def force_close_result_hook(result):
            data = result if isinstance(result, dict) else {}
            if bool(data.get("ok")):
                self.counters["forced_close_ok"] += 1
            else:
                self.counters["forced_close_fail"] += 1
            return original_force_close_result(result)

        self.tab._on_strategy_force_close_result = force_close_result_hook

        original_set_status = self.tab._set_strategy_status

        def set_status_hook(message, code=None):
            code_norm = str(code or "").strip().lower()
            self.status_events.append(
                {
                    "ts": _utc_iso(),
                    "code": code_norm,
                    "message": str(message or ""),
                }
            )
            if code_norm == "recoverable_retry":
                self.counters["recoverable_retry"] += 1
            elif code_norm == "step_miss":
                self.counters["step_miss"] += 1
            elif code_norm == "leg_lost":
                self.counters["leg_lost"] += 1
            elif code_norm == "leg_lost_closed":
                self.counters["leg_lost_closed"] += 1
            return original_set_status(message, code)

        self.tab._set_strategy_status = set_status_hook

    def _prepare_log_tail_tracking(self):
        day = datetime.now().strftime("%Y%m%d")
        path = os.path.join(PROJECT_ROOT, "logs", f"debug_{day}.log")
        self._debug_log_path = path
        try:
            self._debug_log_offset = os.path.getsize(path)
        except OSError:
            self._debug_log_offset = 0

    def _tail_debug_log(self):
        path = self._debug_log_path
        if not path:
            return []
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                f.seek(self._debug_log_offset, os.SEEK_SET)
                text = f.read()
        except OSError:
            return []
        if not text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _on_trace_event(self, event, fields):
        name = str(event or "")
        data = dict(fields or {})
        now_iso = _utc_iso()
        if len(self.trace_events) < 4000:
            self.trace_events.append({"ts": now_iso, "event": name, "fields": data})

        if name == "strategy.network_degraded":
            self.counters["network_degraded"] += 1
        elif name == "strategy.network_resumed":
            self.counters["network_resumed"] += 1
        elif name == "strategy.emergency_close_verify_failed":
            self.counters["emergency_verify_failed"] += 1

        if name != "strategy.step_submit":
            return

        spread_state = self.tab._calculate_spread_state() if self.tab is not None else {}
        self.pending_submit = {
            "submitted_at_ts": time.monotonic(),
            "submitted_at": now_iso,
            "action": str(data.get("action") or "").strip().lower(),
            "buy_exchange": str(data.get("buy_exchange") or "").strip(),
            "buy_pair": str(data.get("buy_pair") or "").strip().upper(),
            "sell_exchange": str(data.get("sell_exchange") or "").strip(),
            "sell_pair": str(data.get("sell_pair") or "").strip().upper(),
            "buy_index": int(data.get("buy_index") or 0) if str(data.get("buy_index") or "").strip() else None,
            "sell_index": int(data.get("sell_index") or 0) if str(data.get("sell_index") or "").strip() else None,
            "requested_qty": _safe_float(data.get("qty"), 0.0),
            "signal_percent_abs": _safe_float((spread_state or {}).get("percent"), 0.0),
            "signal_raw_edge_pct": _safe_float((spread_state or {}).get("raw_edge_pct"), 0.0),
            "signal_effective_edge_pct": _safe_float((spread_state or {}).get("effective_edge_pct"), 0.0),
            "signal_phase": str((spread_state or {}).get("phase") or ""),
        }
        self.counters["step_submit"] += 1

    def _extract_fill_edge(self, result):
        data = result if isinstance(result, dict) else {}
        first_leg = data.get("first_leg") if isinstance(data.get("first_leg"), dict) else {}
        second_leg = data.get("second_leg") if isinstance(data.get("second_leg"), dict) else {}
        first_res = data.get("first_result") if isinstance(data.get("first_result"), dict) else {}
        second_res = data.get("second_result") if isinstance(data.get("second_result"), dict) else {}
        legs = [(first_leg, first_res), (second_leg, second_res)]
        sell_avg = None
        buy_avg = None
        sell_leg = None
        buy_leg = None
        for leg, leg_res in legs:
            side = str(leg.get("side") or "").strip().lower()
            avg_price = _safe_float(leg_res.get("avg_price"), 0.0)
            if avg_price <= 0:
                continue
            if side == "sell" and sell_avg is None:
                sell_avg = avg_price
                sell_leg = leg
            elif side == "buy" and buy_avg is None:
                buy_avg = avg_price
                buy_leg = leg
        edge_pct = None
        if buy_avg and buy_avg > 0 and sell_avg and sell_avg > 0:
            edge_pct = ((sell_avg - buy_avg) / buy_avg) * 100.0
        return {
            "sell_avg_price": sell_avg,
            "buy_avg_price": buy_avg,
            "sell_leg": sell_leg or {},
            "buy_leg": buy_leg or {},
            "fill_edge_pct": edge_pct,
            "first_result": first_res,
            "second_result": second_res,
        }

    def _on_step_result(self, result):
        data = result if isinstance(result, dict) else {}
        pending = dict(self.pending_submit or {})
        now_iso = _utc_iso()
        now_ts = time.monotonic()
        latency_sec = None
        if pending:
            latency_sec = max(0.0, now_ts - float(pending.get("submitted_at_ts") or now_ts))
        fill = self._extract_fill_edge(data)

        record = {
            "result_at": now_iso,
            "action": str(data.get("action") or pending.get("action") or "").strip().lower(),
            "ok": bool(data.get("ok")),
            "error": str(data.get("error") or "").strip(),
            "requested_qty": _safe_float(data.get("requested_qty"), pending.get("requested_qty", 0.0)),
            "executed_qty": _safe_float(data.get("executed_qty"), 0.0),
            "nothing_to_close": bool(data.get("nothing_to_close")),
            "unbalanced_close": bool(data.get("unbalanced_close")),
            "latency_sec": latency_sec,
            "first_latency_sec": _safe_float(data.get("first_latency_sec"), 0.0),
            "second_latency_sec": _safe_float(data.get("second_latency_sec"), 0.0),
            "first_send_ack_sec": _safe_float(data.get("first_send_ack_sec"), 0.0),
            "second_send_ack_sec": _safe_float(data.get("second_send_ack_sec"), 0.0),
            "first_ack_fill_sec": _safe_float(data.get("first_ack_fill_sec"), 0.0),
            "second_ack_fill_sec": _safe_float(data.get("second_ack_fill_sec"), 0.0),
            "first_submit_total_sec": _safe_float(data.get("first_submit_total_sec"), 0.0),
            "second_submit_total_sec": _safe_float(data.get("second_submit_total_sec"), 0.0),
            "first_decision_to_send_sec": _safe_float(data.get("first_decision_to_send_sec"), 0.0),
            "second_decision_to_send_sec": _safe_float(data.get("second_decision_to_send_sec"), 0.0),
            "first_queue_wait_sec": _safe_float(data.get("first_queue_wait_sec"), 0.0),
            "second_queue_wait_sec": _safe_float(data.get("second_queue_wait_sec"), 0.0),
            "legs_send_delta_sec": _safe_float(data.get("legs_send_delta_sec"), 0.0),
            "legs_dispatch_delta_sec": _safe_float(data.get("legs_dispatch_delta_sec"), 0.0),
            "decision_to_first_dispatch_sec": _safe_float(data.get("decision_to_first_dispatch_sec"), 0.0),
            "decision_to_all_dispatched_sec": _safe_float(data.get("decision_to_all_dispatched_sec"), 0.0),
            "net_exposure_time_sec": _safe_float(data.get("net_exposure_time_sec"), 0.0),
            "hedge_escalation": dict(data.get("hedge_escalation") or {}) if isinstance(data.get("hedge_escalation"), dict) else {},
            "panic_unwind": dict(data.get("panic_unwind") or {}) if isinstance(data.get("panic_unwind"), dict) else {},
            "signal": {
                "submitted_at": pending.get("submitted_at"),
                "raw_edge_pct": pending.get("signal_raw_edge_pct"),
                "percent_abs": pending.get("signal_percent_abs"),
                "effective_edge_pct": pending.get("signal_effective_edge_pct"),
                "phase": pending.get("signal_phase"),
            },
            "routing": {
                "buy_exchange": pending.get("buy_exchange") or data.get("buy_exchange"),
                "buy_pair": pending.get("buy_pair") or data.get("buy_pair"),
                "sell_exchange": pending.get("sell_exchange") or data.get("sell_exchange"),
                "sell_pair": pending.get("sell_pair") or data.get("sell_pair"),
                "buy_index": pending.get("buy_index") or data.get("buy_index"),
                "sell_index": pending.get("sell_index") or data.get("sell_index"),
            },
            "fill": {
                "edge_pct": fill.get("fill_edge_pct"),
                "sell_avg_price": fill.get("sell_avg_price"),
                "buy_avg_price": fill.get("buy_avg_price"),
            },
            "legs": {
                "first_leg": data.get("first_leg"),
                "second_leg": data.get("second_leg"),
                "first_result": fill.get("first_result"),
                "second_result": fill.get("second_result"),
                "rollback_result": data.get("rollback_result"),
            },
        }
        self.completed_trades.append(record)
        if bool(data.get("ok")):
            self.counters["step_ok"] += 1
        else:
            self.counters["step_fail"] += 1
        self.pending_submit = None

    def _spread_ready(self):
        if self.tab is None:
            return False, "tab_missing"
        state = self.tab._calculate_spread_state()
        if state.get("percent") is None:
            return False, "spread_no_data"
        return True, ""

    def _ensure_spread_armed(self):
        if self.tab is None:
            return False
        if bool(getattr(self.tab, "_spread_armed", False)):
            return True
        ready, _reason = self._spread_ready()
        if not ready:
            return False
        self.tab._on_spread_select_clicked()
        return bool(getattr(self.tab, "_spread_armed", False))

    def _try_start_strategy(self):
        if self.stop_requested or self.tab is None:
            return
        if self.started_ts > 0:
            return
        self.start_attempts += 1
        armed = self._ensure_spread_armed()
        check = self.tab._validate_strategy_prerequisites()
        if check:
            self._last_summary_status = f"ожидание старта: {check}"
            if self.start_attempts % 4 == 0:
                self.logger.info("stress_test.start_wait attempt=%s reason=%s armed=%s", self.start_attempts, check, armed)
            return
        self.tab._on_strategy_start_clicked()
        if bool(self.tab._strategy_state.is_running):
            self.started_ts = time.monotonic()
            self._last_summary_status = "стратегия запущена"
            self.logger.info("stress_test.strategy_started attempt=%s", self.start_attempts)
        else:
            self._last_summary_status = "клик старт, но runtime не запущен"
            self.logger.warning("stress_test.start_click_no_run attempt=%s", self.start_attempts)

    def _capture_snapshot(self):
        if self.tab is None:
            return
        spread_state = self.tab._calculate_spread_state()
        st = self.tab._strategy_state
        snap = {
            "ts": _utc_iso(),
            "running": bool(st.is_running),
            "phase": str(st.phase or ""),
            "active_hedged_size": _safe_float(st.active_hedged_size, 0.0),
            "target_qty": _safe_float(st.target_qty, 0.0),
            "step_qty": _safe_float(st.step_qty, 0.0),
            "next_entry_qty": _safe_float(st.next_entry_qty, 0.0),
            "next_exit_qty": _safe_float(st.next_exit_qty, 0.0),
            "leg1_qty": _safe_float(st.leg1_qty, 0.0),
            "leg2_qty": _safe_float(st.leg2_qty, 0.0),
            "unbalanced_qty": _safe_float(st.unbalanced_qty, 0.0),
            "leg1_direction": str(st.leg1_direction or "flat"),
            "leg2_direction": str(st.leg2_direction or "flat"),
            "spread_percent_abs": _safe_float((spread_state or {}).get("percent"), 0.0),
            "spread_raw_edge_pct": _safe_float((spread_state or {}).get("raw_edge_pct"), 0.0),
            "strategy_notice_code": str(getattr(self.tab, "_strategy_notice_code", "") or ""),
            "strategy_notice_text": str(getattr(st, "last_error", "") or ""),
            "spread_armed": bool(getattr(self.tab, "_spread_armed", False)),
        }
        if len(self.snapshots) < 12000:
            self.snapshots.append(snap)

    def _inject_leg_drop_if_possible(self):
        if self.stop_requested or self.tab is None:
            return
        if not bool(self.tab._strategy_state.is_running):
            return
        if bool(getattr(self.tab, "_strategy_cycle_busy", False)):
            return

        st = self.tab._strategy_state
        leg_qty = _safe_float(st.leg1_qty, 0.0)
        if leg_qty <= 0:
            return
        side = "sell" if str(st.leg1_direction or "").strip().lower() == "long" else "buy"
        if str(st.leg1_direction or "").strip().lower() not in {"long", "short"}:
            return

        step_qty = _safe_float(st.step_qty, 0.0)
        drop_qty = max(leg_qty * 0.22, step_qty * 0.80, 0.0)
        drop_qty = min(drop_qty, leg_qty * 0.90)
        if drop_qty <= 0:
            return

        exchange_name = str(st.leg1_exchange or "").strip()
        pair = str(st.leg1_pair or "").strip().upper()
        if not exchange_name or not pair:
            return

        result = self.tab._runtime_service.place_market_reduce_order(
            exchange_name=exchange_name,
            pair=pair,
            side=side,
            qty=drop_qty,
        )
        payload = {
            "ts": _utc_iso(),
            "kind": "inject_leg_drop",
            "exchange": exchange_name,
            "pair": pair,
            "side": side,
            "requested_qty": drop_qty,
            "result": result if isinstance(result, dict) else {"ok": False, "error": "invalid_result"},
        }
        self.injected_events.append(payload)
        self.logger.info(
            "stress_test.inject_leg_drop exchange=%s pair=%s side=%s qty=%.8f ok=%s",
            exchange_name,
            pair,
            side,
            float(drop_qty),
            bool((result or {}).get("ok")),
        )

    def _build_debug_log_stats(self):
        lines = self._tail_debug_log()
        if not lines:
            return {
                "new_lines": 0,
                "error_lines": 0,
                "warning_lines": 0,
                "patterns": {},
                "sample": [],
            }
        patterns = {
            "binance_fok_5021": 0,
            "binance_notional_4164": 0,
            "bitget_no_position_22002": 0,
            "rate_limit_429": 0,
            "request_timed_out": 0,
        }
        rate_limit_re = re.compile(
            r"(code['\"]?\s*:\s*['\"]?429['\"]?)|(\b(?:ошибка|error)\s+429\b)|(too many requests)",
            re.IGNORECASE,
        )
        error_lines = 0
        warning_lines = 0
        sample = []
        for line in lines:
            lower = line.lower()
            if " - error - " in lower:
                error_lines += 1
            if " - warning - " in lower:
                warning_lines += 1
            if "-5021" in line:
                patterns["binance_fok_5021"] += 1
            if "-4164" in line:
                patterns["binance_notional_4164"] += 1
            if "22002" in line:
                patterns["bitget_no_position_22002"] += 1
            if rate_limit_re.search(line):
                patterns["rate_limit_429"] += 1
            if "timed out" in lower or "request timed out" in lower:
                patterns["request_timed_out"] += 1
            if (" - error - " in lower or " - warning - " in lower) and len(sample) < 60:
                sample.append(line)
        return {
            "new_lines": len(lines),
            "error_lines": error_lines,
            "warning_lines": warning_lines,
            "patterns": patterns,
            "sample": sample,
        }

    def _write_status(self, extra=None):
        if not self.status_path:
            return
        elapsed = max(0.0, time.monotonic() - float(self._run_started_mono or time.monotonic()))
        payload = {
            "ts": _utc_iso(),
            "phase": "running" if not self.stop_requested else "finishing",
            "elapsed_sec": elapsed,
            "duration_sec": self.duration_sec,
            "strategy_started": bool(self.started_ts > 0),
            "running_now": bool(self.tab._strategy_state.is_running) if self.tab is not None else False,
            "status_text": self._last_summary_status,
            "counters": dict(self.counters),
            "completed_trades": len(self.completed_trades),
            "snapshots": len(self.snapshots),
            "inject_events": len(self.injected_events),
        }
        if extra:
            payload.update(dict(extra))
        try:
            os.makedirs(os.path.dirname(self.status_path), exist_ok=True)
            with open(self.status_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _build_summary(self):
        successful = [r for r in self.completed_trades if r.get("ok")]
        failed = [r for r in self.completed_trades if not r.get("ok")]
        entry_ok = [r for r in successful if r.get("action") == "entry"]
        exit_ok = [r for r in successful if r.get("action") == "exit"]
        fill_edges = [r.get("fill", {}).get("edge_pct") for r in successful]
        fill_edges = [float(v) for v in fill_edges if isinstance(v, (int, float))]
        latencies = [r.get("latency_sec") for r in self.completed_trades]
        latencies = [float(v) for v in latencies if isinstance(v, (int, float))]
        first_latencies = [r.get("first_latency_sec") for r in self.completed_trades]
        first_latencies = [float(v) for v in first_latencies if isinstance(v, (int, float)) and float(v) > 0]
        second_latencies = [r.get("second_latency_sec") for r in self.completed_trades]
        second_latencies = [float(v) for v in second_latencies if isinstance(v, (int, float)) and float(v) > 0]
        send_ack_all = []
        ack_fill_all = []
        submit_total_all = []
        decision_to_send_all = []
        queue_wait_all = []
        legs_send_delta_all = []
        legs_dispatch_delta_all = []
        decision_to_first_dispatch_all = []
        decision_to_all_dispatched_all = []
        net_exposure_times = []
        exchange_timing = {}
        partial_fill_legs = 0
        partial_fill_trades = 0
        escalation_used_trades = 0
        escalation_attempts_total = 0
        escalation_filled_qty_total = 0.0
        panic_unwind_used_trades = 0

        def _append_exchange_timing(exchange_name, send_ack, ack_fill, submit_total, decision_to_send, queue_wait):
            ex_name = str(exchange_name or "").strip()
            if not ex_name:
                return
            bucket = exchange_timing.setdefault(
                ex_name,
                {
                    "send_ack_sec": [],
                    "ack_fill_sec": [],
                    "submit_total_sec": [],
                    "decision_to_send_sec": [],
                    "queue_wait_sec": [],
                    "partial_fill_legs": 0,
                    "legs_total": 0,
                },
            )
            if send_ack > 0:
                bucket["send_ack_sec"].append(float(send_ack))
                send_ack_all.append(float(send_ack))
            if ack_fill > 0:
                bucket["ack_fill_sec"].append(float(ack_fill))
                ack_fill_all.append(float(ack_fill))
            if submit_total > 0:
                bucket["submit_total_sec"].append(float(submit_total))
                submit_total_all.append(float(submit_total))
            if decision_to_send > 0:
                bucket["decision_to_send_sec"].append(float(decision_to_send))
                decision_to_send_all.append(float(decision_to_send))
            if queue_wait > 0:
                bucket["queue_wait_sec"].append(float(queue_wait))
                queue_wait_all.append(float(queue_wait))
            bucket["legs_total"] += 1

        for trade in self.completed_trades:
            trade_partial = False
            first_leg = (trade.get("legs") or {}).get("first_leg") or {}
            second_leg = (trade.get("legs") or {}).get("second_leg") or {}
            first_res = (trade.get("legs") or {}).get("first_result") or {}
            second_res = (trade.get("legs") or {}).get("second_result") or {}

            first_send_ack = _safe_float(trade.get("first_send_ack_sec"), 0.0)
            second_send_ack = _safe_float(trade.get("second_send_ack_sec"), 0.0)
            first_ack_fill = _safe_float(trade.get("first_ack_fill_sec"), 0.0)
            second_ack_fill = _safe_float(trade.get("second_ack_fill_sec"), 0.0)
            first_submit_total = _safe_float(trade.get("first_submit_total_sec"), 0.0)
            second_submit_total = _safe_float(trade.get("second_submit_total_sec"), 0.0)
            first_decision_to_send = _safe_float(trade.get("first_decision_to_send_sec"), 0.0)
            second_decision_to_send = _safe_float(trade.get("second_decision_to_send_sec"), 0.0)
            first_queue_wait = _safe_float(trade.get("first_queue_wait_sec"), 0.0)
            second_queue_wait = _safe_float(trade.get("second_queue_wait_sec"), 0.0)
            legs_send_delta = _safe_float(trade.get("legs_send_delta_sec"), 0.0)
            legs_dispatch_delta = _safe_float(trade.get("legs_dispatch_delta_sec"), 0.0)
            decision_to_first_dispatch = _safe_float(trade.get("decision_to_first_dispatch_sec"), 0.0)
            decision_to_all_dispatched = _safe_float(trade.get("decision_to_all_dispatched_sec"), 0.0)
            net_exposure_sec = _safe_float(trade.get("net_exposure_time_sec"), 0.0)

            if legs_send_delta >= 0:
                legs_send_delta_all.append(float(legs_send_delta))
            if legs_dispatch_delta >= 0:
                legs_dispatch_delta_all.append(float(legs_dispatch_delta))
            if decision_to_first_dispatch >= 0:
                decision_to_first_dispatch_all.append(float(decision_to_first_dispatch))
            if decision_to_all_dispatched >= 0:
                decision_to_all_dispatched_all.append(float(decision_to_all_dispatched))
            if net_exposure_sec > 0:
                net_exposure_times.append(float(net_exposure_sec))

            escalation = trade.get("hedge_escalation") if isinstance(trade.get("hedge_escalation"), dict) else {}
            if bool(escalation.get("used")):
                escalation_used_trades += 1
                attempts = escalation.get("attempts") if isinstance(escalation.get("attempts"), list) else []
                escalation_attempts_total += len(attempts)
                escalation_filled_qty_total += _safe_float(escalation.get("filled_qty"), 0.0)

            panic = trade.get("panic_unwind") if isinstance(trade.get("panic_unwind"), dict) else {}
            if bool(panic.get("used")):
                panic_unwind_used_trades += 1

            _append_exchange_timing(
                first_leg.get("exchange"),
                first_send_ack,
                first_ack_fill,
                first_submit_total,
                first_decision_to_send,
                first_queue_wait,
            )
            _append_exchange_timing(
                second_leg.get("exchange"),
                second_send_ack,
                second_ack_fill,
                second_submit_total,
                second_decision_to_send,
                second_queue_wait,
            )

            for leg_ex, leg_res in (
                (str(first_leg.get("exchange") or "").strip(), first_res),
                (str(second_leg.get("exchange") or "").strip(), second_res),
            ):
                req = _safe_float((leg_res or {}).get("requested_qty"), 0.0)
                exe = _safe_float((leg_res or {}).get("executed_qty"), 0.0)
                if req > 0 and exe > 0 and exe + 1e-12 < req:
                    partial_fill_legs += 1
                    trade_partial = True
                    if leg_ex:
                        bucket = exchange_timing.setdefault(
                            leg_ex,
                            {
                                "send_ack_sec": [],
                                "ack_fill_sec": [],
                                "submit_total_sec": [],
                                "decision_to_send_sec": [],
                                "queue_wait_sec": [],
                                "partial_fill_legs": 0,
                                "legs_total": 0,
                            },
                        )
                        bucket["partial_fill_legs"] = int(bucket.get("partial_fill_legs") or 0) + 1
            if trade_partial:
                partial_fill_trades += 1
        abs_signal_edges = []
        for r in self.completed_trades:
            val = r.get("signal", {}).get("raw_edge_pct")
            if isinstance(val, (int, float)):
                abs_signal_edges.append(float(val))

        def _avg(values):
            return (sum(values) / len(values)) if values else 0.0

        exchange_timing_summary = {}
        for ex_name, bucket in exchange_timing.items():
            send_vals = bucket.get("send_ack_sec") or []
            fill_vals = bucket.get("ack_fill_sec") or []
            submit_vals = bucket.get("submit_total_sec") or []
            decision_vals = bucket.get("decision_to_send_sec") or []
            queue_vals = bucket.get("queue_wait_sec") or []
            exchange_timing_summary[ex_name] = {
                "legs_total": int(bucket.get("legs_total") or 0),
                "partial_fill_legs": int(bucket.get("partial_fill_legs") or 0),
                "send_ack_sec": {
                    "avg": _avg(send_vals),
                    "p50": _percentile(send_vals, 50),
                    "p95": _percentile(send_vals, 95),
                    "p99": _percentile(send_vals, 99),
                    "max": max(send_vals) if send_vals else 0.0,
                },
                "ack_fill_sec": {
                    "avg": _avg(fill_vals),
                    "p50": _percentile(fill_vals, 50),
                    "p95": _percentile(fill_vals, 95),
                    "p99": _percentile(fill_vals, 99),
                    "max": max(fill_vals) if fill_vals else 0.0,
                },
                "submit_total_sec": {
                    "avg": _avg(submit_vals),
                    "p50": _percentile(submit_vals, 50),
                    "p95": _percentile(submit_vals, 95),
                    "p99": _percentile(submit_vals, 99),
                    "max": max(submit_vals) if submit_vals else 0.0,
                },
                "decision_to_send_sec": {
                    "avg": _avg(decision_vals),
                    "p50": _percentile(decision_vals, 50),
                    "p95": _percentile(decision_vals, 95),
                    "p99": _percentile(decision_vals, 99),
                    "max": max(decision_vals) if decision_vals else 0.0,
                },
                "queue_wait_sec": {
                    "avg": _avg(queue_vals),
                    "p50": _percentile(queue_vals, 50),
                    "p95": _percentile(queue_vals, 95),
                    "p99": _percentile(queue_vals, 99),
                    "max": max(queue_vals) if queue_vals else 0.0,
                },
            }

        return {
            "run_started_at": self._run_started_iso,
            "run_finished_at": self._run_finished_iso or _utc_iso(),
            "duration_sec_requested": self.duration_sec,
            "duration_sec_actual": max(0.0, time.monotonic() - float(self._run_started_mono or time.monotonic())),
            "started_successfully": bool(self.started_ts > 0),
            "counts": {
                "trades_total": len(self.completed_trades),
                "trades_ok": len(successful),
                "trades_failed": len(failed),
                "entry_ok": len(entry_ok),
                "exit_ok": len(exit_ok),
                "snapshots": len(self.snapshots),
                "inject_events": len(self.injected_events),
                "partial_fill_trades": int(partial_fill_trades),
                "partial_fill_legs": int(partial_fill_legs),
            },
            "metrics": {
                "avg_signal_raw_edge_pct": _avg(abs_signal_edges),
                "avg_fill_edge_pct": _avg(fill_edges),
                "max_fill_edge_pct": max(fill_edges) if fill_edges else 0.0,
                "min_fill_edge_pct": min(fill_edges) if fill_edges else 0.0,
                "avg_latency_sec": _avg(latencies),
                "max_latency_sec": max(latencies) if latencies else 0.0,
                "avg_first_leg_latency_sec": _avg(first_latencies),
                "max_first_leg_latency_sec": max(first_latencies) if first_latencies else 0.0,
                "avg_second_leg_latency_sec": _avg(second_latencies),
                "max_second_leg_latency_sec": max(second_latencies) if second_latencies else 0.0,
                "latency_total_sec": {
                    "p50": _percentile(latencies, 50),
                    "p95": _percentile(latencies, 95),
                    "p99": _percentile(latencies, 99),
                },
                "send_ack_sec": {
                    "avg": _avg(send_ack_all),
                    "p50": _percentile(send_ack_all, 50),
                    "p95": _percentile(send_ack_all, 95),
                    "p99": _percentile(send_ack_all, 99),
                    "max": max(send_ack_all) if send_ack_all else 0.0,
                },
                "ack_fill_sec": {
                    "avg": _avg(ack_fill_all),
                    "p50": _percentile(ack_fill_all, 50),
                    "p95": _percentile(ack_fill_all, 95),
                    "p99": _percentile(ack_fill_all, 99),
                    "max": max(ack_fill_all) if ack_fill_all else 0.0,
                },
                "submit_total_sec": {
                    "avg": _avg(submit_total_all),
                    "p50": _percentile(submit_total_all, 50),
                    "p95": _percentile(submit_total_all, 95),
                    "p99": _percentile(submit_total_all, 99),
                    "max": max(submit_total_all) if submit_total_all else 0.0,
                },
                "net_exposure_time_sec": {
                    "avg": _avg(net_exposure_times),
                    "p50": _percentile(net_exposure_times, 50),
                    "p95": _percentile(net_exposure_times, 95),
                    "p99": _percentile(net_exposure_times, 99),
                    "max": max(net_exposure_times) if net_exposure_times else 0.0,
                    "unhedged_over_1s": int(sum(1 for v in net_exposure_times if float(v) > 1.0)),
                    "unhedged_over_2s": int(sum(1 for v in net_exposure_times if float(v) > 2.0)),
                },
                "decision_to_send_sec": {
                    "avg": _avg(decision_to_send_all),
                    "p50": _percentile(decision_to_send_all, 50),
                    "p95": _percentile(decision_to_send_all, 95),
                    "p99": _percentile(decision_to_send_all, 99),
                    "max": max(decision_to_send_all) if decision_to_send_all else 0.0,
                },
                "queue_wait_sec": {
                    "avg": _avg(queue_wait_all),
                    "p50": _percentile(queue_wait_all, 50),
                    "p95": _percentile(queue_wait_all, 95),
                    "p99": _percentile(queue_wait_all, 99),
                    "max": max(queue_wait_all) if queue_wait_all else 0.0,
                },
                "legs_send_delta_sec": {
                    "avg": _avg(legs_send_delta_all),
                    "p50": _percentile(legs_send_delta_all, 50),
                    "p95": _percentile(legs_send_delta_all, 95),
                    "p99": _percentile(legs_send_delta_all, 99),
                    "max": max(legs_send_delta_all) if legs_send_delta_all else 0.0,
                },
                "legs_dispatch_delta_sec": {
                    "avg": _avg(legs_dispatch_delta_all),
                    "p50": _percentile(legs_dispatch_delta_all, 50),
                    "p95": _percentile(legs_dispatch_delta_all, 95),
                    "p99": _percentile(legs_dispatch_delta_all, 99),
                    "max": max(legs_dispatch_delta_all) if legs_dispatch_delta_all else 0.0,
                },
                "decision_to_first_dispatch_sec": {
                    "avg": _avg(decision_to_first_dispatch_all),
                    "p50": _percentile(decision_to_first_dispatch_all, 50),
                    "p95": _percentile(decision_to_first_dispatch_all, 95),
                    "p99": _percentile(decision_to_first_dispatch_all, 99),
                    "max": max(decision_to_first_dispatch_all) if decision_to_first_dispatch_all else 0.0,
                },
                "decision_to_all_dispatched_sec": {
                    "avg": _avg(decision_to_all_dispatched_all),
                    "p50": _percentile(decision_to_all_dispatched_all, 50),
                    "p95": _percentile(decision_to_all_dispatched_all, 95),
                    "p99": _percentile(decision_to_all_dispatched_all, 99),
                    "max": max(decision_to_all_dispatched_all) if decision_to_all_dispatched_all else 0.0,
                },
                "hedge_escalation": {
                    "used_trades": int(escalation_used_trades),
                    "attempts_total": int(escalation_attempts_total),
                    "filled_qty_total": float(escalation_filled_qty_total),
                },
                "panic_unwind": {
                    "used_trades": int(panic_unwind_used_trades),
                },
            },
            "timing_by_exchange": exchange_timing_summary,
            "counters": dict(self.counters),
        }

    def _finish_run(self):
        if self._finalized:
            return
        self._finalized = True
        self.stop_requested = True
        self._run_finished_iso = _utc_iso()
        self._last_summary_status = "завершение теста"
        self._write_status(extra={"phase": "finishing"})

        try:
            if self.tab is not None and bool(self.tab._strategy_state.is_running):
                self.tab._on_strategy_stop_clicked()
        except Exception:
            self.logger.exception("stress_test.stop_strategy_error")

        # Two-pass close: first strategy force-close (if any active size), then global fallback.
        try:
            if self.tab is not None:
                self.tab._on_strategy_force_close_clicked()
        except Exception:
            self.logger.exception("stress_test.force_close_error")

        QTimer.singleShot(4500, self._finalize_after_cleanup)

    def _finalize_after_cleanup(self):
        if self.window is not None:
            try:
                summary = self.window.exchange_manager.close_all_positions()
                self.injected_events.append({"ts": _utc_iso(), "kind": "close_all_positions", "summary": summary})
            except Exception:
                self.logger.exception("stress_test.close_all_positions_error")

            try:
                self.window.exchange_manager.disconnect_all(manual=False)
            except Exception:
                self.logger.exception("stress_test.disconnect_all_error")

            try:
                self.window.exchange_manager.shutdown(wait_for_tasks=True)
            except Exception:
                self.logger.exception("stress_test.exchange_shutdown_error")

        try:
            ThreadManager().wait_for_done()
        except Exception:
            pass

        report = {
            "summary": self._build_summary(),
            "completed_trades": self.completed_trades,
            "status_events": self.status_events,
            "inject_events": self.injected_events,
            "debug_log": self._build_debug_log_stats(),
            "snapshots_sample_head": self.snapshots[:600],
            "snapshots_sample_tail": self.snapshots[-600:] if len(self.snapshots) > 600 else [],
        }
        os.makedirs(os.path.dirname(self.report_path), exist_ok=True)
        with open(self.report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        self._write_status(
            extra={
                "phase": "done",
                "report_path": self.report_path,
                "completed_trades": len(self.completed_trades),
            }
        )
        print(self.report_path)
        self.app.quit()


def parse_args():
    parser = argparse.ArgumentParser(description="30m live spread strategy stress test runner")
    parser.add_argument("--duration-min", type=float, default=30.0, help="Test duration in minutes")
    parser.add_argument("--inject-leg-drop", type=int, default=1, help="1 to enable periodic forced leg drop, 0 to disable")
    parser.add_argument("--leg-drop-interval-sec", type=int, default=420, help="Interval for leg-drop injection")
    parser.add_argument("--report-path", type=str, default="", help="Path to output JSON report")
    parser.add_argument("--status-path", type=str, default="", help="Path to status JSON")
    return parser.parse_args()


def main():
    args = parse_args()
    os.chdir(PROJECT_ROOT)
    setup_logger()

    settings = SettingsManager()
    get_language_manager().set_language(settings.load_ui_language())
    get_theme_manager().set_theme(settings.load_ui_theme())

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    app.setApplicationName(tr("app.title"))
    app.setStyle("Fusion")

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = args.report_path.strip() or os.path.join(PROJECT_ROOT, "logs", f"spread_stress_report_{now}.json")
    status_path = args.status_path.strip() or os.path.join(PROJECT_ROOT, "logs", "spread_stress_status.json")

    runner = SpreadLiveStressRunner(
        app=app,
        duration_sec=int(max(0.2, float(args.duration_min)) * 60),
        inject_leg_drop=bool(int(args.inject_leg_drop)),
        leg_drop_interval_sec=int(args.leg_drop_interval_sec),
        report_path=report_path,
        status_path=status_path,
    )
    runner.run()
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print(traceback.format_exc())
        raise
