from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer

from core.utils.logger import get_logger, get_runtime_log_path

logger = get_logger(__name__)


def _utc_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class OvernightReportRecorder(QObject):
    """Continuous recorder for live overnight runs.

    Writes JSONL events continuously, plus a compact status JSON updated every few seconds.
    """

    def __init__(self, spread_tab, status_bar=None, parent=None):
        super().__init__(parent)
        self._tab = spread_tab
        self._status_bar = status_bar
        self._trace_original = None
        self._started_mono = time.monotonic()
        self._started_iso = _utc_iso()
        self._stopped = False

        self._counts = {
            "events": 0,
            "snapshots": 0,
            "strategy_started": 0,
            "strategy_stopped": 0,
            "auto_restart_scheduled": 0,
            "auto_restart_attempt": 0,
            "auto_restart_success": 0,
            "step_ok": 0,
            "step_fail": 0,
        }

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        logs_dir = os.path.join(project_root, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        self.report_path = get_runtime_log_path()
        self._write_event("session_started", version=1, report_path=self.report_path)

        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setInterval(1000)
        self._snapshot_timer.timeout.connect(self._on_snapshot_tick)
        self._snapshot_timer.start()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._write_status)
        self._status_timer.start()

        self._install_trace_hook()
        self._write_status()
        self._set_indicator(True)
        logger.info("Overnight recorder started: %s", self.report_path)

    def _set_indicator(self, active):
        bar = self._status_bar
        if bar is None:
            return
        setter = getattr(bar, "set_recording_state", None)
        if callable(setter):
            setter(bool(active), tooltip=self.report_path if active else "")

    def _install_trace_hook(self):
        tab = self._tab
        if tab is None:
            return
        original = getattr(tab, "_trace", None)
        if not callable(original):
            return
        self._trace_original = original

        def wrapped(event, **fields):
            try:
                self._on_trace(event, fields)
            except Exception:
                logger.exception("Overnight recorder trace hook error")
            return original(event, **fields)

        tab._trace = wrapped

    def _restore_trace_hook(self):
        tab = self._tab
        if tab is None:
            return
        original = self._trace_original
        if callable(original):
            tab._trace = original
        self._trace_original = None

    def _write_event(self, event_type, **payload):
        if self._stopped:
            return
        row = {
            "ts": _utc_iso(),
            "event": str(event_type or "event"),
            "payload": dict(payload or {}),
        }
        try:
            logger.info("[OVERNIGHT] %s", json.dumps(row, ensure_ascii=False))
            self._counts["events"] = int(self._counts.get("events", 0) or 0) + 1
        except Exception:
            logger.exception("Overnight recorder write failed")

    def _on_trace(self, event, fields):
        name = str(event or "")
        data = dict(fields or {})
        self._write_event("trace", name=name, fields=data)

        if name == "strategy.started":
            self._counts["strategy_started"] += 1
        elif name == "strategy.stopped":
            self._counts["strategy_stopped"] += 1
        elif name == "strategy.auto_restart_scheduled":
            self._counts["auto_restart_scheduled"] += 1
        elif name == "strategy.auto_restart_attempt":
            self._counts["auto_restart_attempt"] += 1
        elif name == "strategy.auto_restart_success":
            self._counts["auto_restart_success"] += 1
        elif name == "strategy.step_result_ok":
            self._counts["step_ok"] += 1
        elif name == "strategy.step_result_fail":
            self._counts["step_fail"] += 1

    def _on_snapshot_tick(self):
        tab = self._tab
        if tab is None:
            return
        state = getattr(tab, "_strategy_state", None)
        if state is None:
            return
        spread = {}
        calc = getattr(tab, "_calculate_spread_state", None)
        if callable(calc):
            try:
                spread = dict(calc() or {})
            except Exception:
                spread = {}
        snap = {
            "running": bool(getattr(state, "is_running", False)),
            "phase": str(getattr(state, "phase", "") or ""),
            "active_hedged_size": _safe_float(getattr(state, "active_hedged_size", 0.0), 0.0),
            "target_qty": _safe_float(getattr(state, "target_qty", 0.0), 0.0),
            "step_qty": _safe_float(getattr(state, "step_qty", 0.0), 0.0),
            "next_entry_qty": _safe_float(getattr(state, "next_entry_qty", 0.0), 0.0),
            "next_exit_qty": _safe_float(getattr(state, "next_exit_qty", 0.0), 0.0),
            "leg1_qty": _safe_float(getattr(state, "leg1_qty", 0.0), 0.0),
            "leg2_qty": _safe_float(getattr(state, "leg2_qty", 0.0), 0.0),
            "unbalanced_qty": _safe_float(getattr(state, "unbalanced_qty", 0.0), 0.0),
            "spread_abs_pct": _safe_float(spread.get("percent"), 0.0),
            "spread_raw_edge_pct": _safe_float(spread.get("raw_edge_pct"), 0.0),
            "spread_effective_edge_pct": _safe_float(spread.get("effective_edge_pct"), 0.0),
            "spread_phase": str(spread.get("phase") or ""),
            "notice_code": str(getattr(tab, "_strategy_notice_code", "") or ""),
            "notice_text": str(getattr(state, "last_error", "") or ""),
        }
        self._counts["snapshots"] = int(self._counts.get("snapshots", 0) or 0) + 1
        self._write_event("snapshot", **snap)

    def _write_status(self):
        if self._stopped:
            return
        tab = self._tab
        running = bool(getattr(getattr(tab, "_strategy_state", None), "is_running", False)) if tab is not None else False
        payload = {
            "started_at": self._started_iso,
            "report_path": self.report_path,
            "elapsed_sec": max(0.0, time.monotonic() - float(self._started_mono)),
            "strategy_running": running,
            "counts": dict(self._counts),
        }
        self._write_event("status", **payload)

    def stop(self, reason="shutdown"):
        if self._stopped:
            return
        try:
            self._snapshot_timer.stop()
            self._status_timer.stop()
        except Exception:
            pass
        self._restore_trace_hook()
        try:
            self._write_event(
                "session_finished",
                reason=str(reason or "shutdown"),
                elapsed_sec=max(0.0, time.monotonic() - float(self._started_mono)),
                counts=dict(self._counts),
            )
        except Exception:
            pass
        try:
            self._write_event(
                "status",
                phase="done",
                started_at=self._started_iso,
                report_path=self.report_path,
                elapsed_sec=max(0.0, time.monotonic() - float(self._started_mono)),
                counts=dict(self._counts),
            )
        except Exception:
            pass
        self._stopped = True
        self._set_indicator(False)
        logger.info("Overnight recorder stopped: %s", self.report_path)
