import time

from core.i18n import tr
from core.utils.logger import get_logger

logger = get_logger(__name__)


class SpreadStrategyRuntimeNetworkMixin:
    def _trace_runtime(self, event, **fields):
        trace = getattr(self, "_trace", None)
        if callable(trace):
            trace(f"strategy.{event}", **fields)
            return
        raw = []
        for key, value in (fields or {}).items():
            if value is None:
                continue
            raw.append(f"{key}={value}")
        if raw:
            logger.info("[TRACE] strategy.%s | %s", event, " | ".join(raw))
        else:
            logger.info("[TRACE] strategy.%s", event)

    @staticmethod
    def _normalize_runtime_error_text(value):
        text = str(value or "").replace("\n", " ").strip()
        if len(text) > 220:
            return f"{text[:217]}..."
        return text

    @staticmethod
    def _is_network_fault_text(error_text):
        text = str(error_text or "").strip().lower()
        if not text:
            return False
        markers = (
            "timeout",
            "timed out",
            "read timed out",
            "connection reset",
            "connection aborted",
            "connection refused",
            "temporary failure",
            "temporarily unavailable",
            "bad gateway",
            "gateway timeout",
            "service unavailable",
            "remote end closed",
            "network is unreachable",
            "winerror 10054",
            "winerror 10060",
            "winerror 10061",
            "max retries exceeded",
            "proxy error",
        )
        return any(marker in text for marker in markers)

    def _remember_runtime_quote_live(self, index):
        idx = int(index) if index in {1, 2} else None
        if idx not in {1, 2}:
            return
        self._runtime_quote_last_live_ts[idx] = time.monotonic()

    def _selected_runtime_indexes(self):
        selected = []
        for idx in (1, 2):
            column = self._column(idx)
            if column is None:
                continue
            if str(getattr(column, "selected_exchange", "") or "").strip() and str(getattr(column, "selected_pair", "") or "").strip():
                selected.append(idx)
        return tuple(selected)

    def _is_runtime_quote_fresh(self, index, now_ts=None):
        idx = int(index) if index in {1, 2} else None
        if idx not in {1, 2}:
            return False
        column = self._column(idx)
        if column is None or str(getattr(column, "quote_state", "") or "").strip().lower() != "live":
            return False
        ts = float(self._runtime_quote_last_live_ts.get(idx) or 0.0)
        if ts <= 0:
            return False
        now_value = float(now_ts if now_ts is not None else time.monotonic())
        return (now_value - ts) <= float(self.QUOTE_STALE_SEC)

    def _runtime_stale_quote_indexes(self, now_ts=None):
        now_value = float(now_ts if now_ts is not None else time.monotonic())
        stale = []
        for idx in self._selected_runtime_indexes():
            if not self._is_runtime_quote_fresh(idx, now_value):
                stale.append(idx)
        return tuple(stale)

    def _runtime_set_degraded(self, reason, source="runtime"):
        reason_text = self._normalize_runtime_error_text(reason)
        now = time.monotonic()
        if not reason_text:
            reason_text = tr("spread.strategy.net_reason.unknown")
        if self._runtime_network_degraded and reason_text == str(self._runtime_network_degraded_reason or ""):
            self._runtime_last_network_fault_ts = now
            return
        self._runtime_network_degraded = True
        self._runtime_network_degraded_reason = reason_text
        if self._runtime_network_degraded_since_ts <= 0:
            self._runtime_network_degraded_since_ts = now
        self._runtime_last_network_fault_ts = now
        self._trace_runtime("network_degraded", source=source, reason=reason_text)
        self._set_strategy_status(
            tr("spread.strategy.warn.net_degraded", reason=reason_text),
            code="network_degraded",
        )

    def _runtime_clear_degraded(self):
        self._runtime_network_degraded = False
        self._runtime_network_degraded_reason = ""
        self._runtime_network_degraded_since_ts = 0.0

    def _runtime_can_resume(self):
        if not self._runtime_network_degraded:
            return True
        now = time.monotonic()
        stale = self._runtime_stale_quote_indexes(now)
        if stale:
            return False
        fault_age = now - float(self._runtime_last_network_fault_ts or 0.0)
        return fault_age >= float(self.NETWORK_STABLE_RESUME_SEC)

    def _runtime_refresh_selected_exchanges(self):
        names = []
        for idx in (1, 2):
            column = self._column(idx)
            if column is None:
                continue
            name = str(getattr(column, "selected_exchange", "") or "").strip()
            if name and name not in names:
                names.append(name)
        for name in names:
            self._refresh_strategy_exchange_async(name, reason="network_resume", force=True)

    def _refresh_strategy_exchange_async(self, name, reason="runtime", force=False):
        exchange_name = str(name or "").strip()
        if not exchange_name:
            return False
        exchange = self.exchange_manager.get_exchange(exchange_name)
        if exchange is None or not bool(getattr(exchange, "is_connected", False)):
            return False

        now = time.monotonic()
        last_ts = float(self._strategy_exchange_last_refresh_ts.get(exchange_name) or 0.0)
        min_interval = max(0.0, float(getattr(self, "_strategy_exchange_refresh_min_sec", 2.0) or 0.0))
        if (not force) and last_ts > 0 and (now - last_ts) < min_interval:
            self._trace_runtime(
                "refresh_exchange_state_skip_throttle",
                exchange=exchange_name,
                reason=reason,
                elapsed=f"{(now - last_ts):.3f}",
                min_interval=f"{min_interval:.3f}",
            )
            return False

        try:
            exchange.api_request_async(exchange.refresh_state)
            self._strategy_exchange_last_refresh_ts[exchange_name] = now
            self._trace_runtime("refresh_exchange_state", exchange=exchange_name, reason=reason, force=bool(force))
            return True
        except Exception:
            self._trace_runtime("refresh_exchange_state_error", exchange=exchange_name, reason=reason)
            return False

    def _runtime_gate_cycle(self):
        stale_indexes = self._runtime_stale_quote_indexes()
        if stale_indexes:
            self._runtime_set_degraded(
                tr("spread.strategy.net_reason.stale_quotes", indexes=", ".join(str(v) for v in stale_indexes)),
                source="quote_stale",
            )

        if not self._runtime_network_degraded:
            return False

        if self._runtime_can_resume():
            self._runtime_clear_degraded()
            self._set_strategy_status(tr("spread.strategy.info.net_recovered"), code="network_recovered")
            self._runtime_refresh_selected_exchanges()
            self._update_strategy_state_label()
            self._trace_runtime("network_resumed")
            return False

        if str(self._strategy_notice_code or "").strip().lower() != "network_degraded":
            self._set_strategy_status(
                tr("spread.strategy.warn.net_degraded", reason=self._runtime_network_degraded_reason or tr("spread.strategy.net_reason.unknown")),
                code="network_degraded",
            )
            self._update_strategy_state_label()
        return True

    def _runtime_extract_network_reason_from_result(self, result_payload):
        payload = result_payload if isinstance(result_payload, dict) else {}
        details = self._normalize_runtime_error_text(payload.get("details"))
        error = self._normalize_runtime_error_text(payload.get("error"))
        status = self._normalize_runtime_error_text(payload.get("status"))
        if details and self._is_network_fault_text(details):
            return details
        merged = " ".join(chunk for chunk in (error, status) if chunk).strip()
        if merged and self._is_network_fault_text(merged):
            return merged
        return ""

    def _runtime_extract_network_reason_from_step(self, step_result):
        payload = step_result if isinstance(step_result, dict) else {}
        for key in ("first_result", "second_result", "rollback_result"):
            reason = self._runtime_extract_network_reason_from_result(payload.get(key))
            if reason:
                return reason
        return ""

    @staticmethod
    def _runtime_percentile(values, pct):
        series = [float(v) for v in (values or []) if isinstance(v, (int, float))]
        if not series:
            return 0.0
        if len(series) == 1:
            return float(series[0])
        ordered = sorted(series)
        p = max(0.0, min(100.0, float(pct)))
        rank = (len(ordered) - 1) * (p / 100.0)
        lo = int(rank)
        hi = min(lo + 1, len(ordered) - 1)
        frac = rank - lo
        return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)

    def _runtime_record_send_ack_from_step(self, step_result):
        payload = step_result if isinstance(step_result, dict) else {}
        now_ts = time.monotonic()
        samples = getattr(self, "_runtime_send_ack_samples", None)
        if samples is None:
            return

        for leg_key, ack_key in (("first_leg", "first_send_ack_sec"), ("second_leg", "second_send_ack_sec")):
            leg = payload.get(leg_key) if isinstance(payload.get(leg_key), dict) else {}
            exchange_name = str(leg.get("exchange") or "").strip() or "unknown"
            ack_val = self._to_float(payload.get(ack_key))
            if ack_val is None or ack_val <= 0:
                continue
            samples.append((float(now_ts), exchange_name, float(ack_val)))

        self._runtime_trim_send_ack_samples(now_ts)

    def _runtime_trim_send_ack_samples(self, now_ts=None):
        samples = getattr(self, "_runtime_send_ack_samples", None)
        if samples is None:
            return
        now_value = float(now_ts if now_ts is not None else time.monotonic())
        window_sec = max(30.0, float(getattr(self, "_runtime_send_ack_window_sec", 90.0) or 90.0))
        while samples and (now_value - float(samples[0][0])) > window_sec:
            samples.popleft()

    def _runtime_ack_mode_snapshot(self):
        now_ts = time.monotonic()
        self._runtime_trim_send_ack_samples(now_ts)
        samples = list(getattr(self, "_runtime_send_ack_samples", ()) or ())
        values = [float(item[2]) for item in samples if len(item) >= 3]
        p95 = self._runtime_percentile(values, 95)
        p50 = self._runtime_percentile(values, 50)
        mode = "green"
        if p95 > 1.5:
            mode = "red"
        elif p95 > 0.8:
            mode = "yellow"

        pause_until = float(getattr(self, "_runtime_ack_red_pause_until_ts", 0.0) or 0.0)
        pause_sec = max(5.0, float(getattr(self, "_runtime_ack_red_pause_sec", 45.0) or 45.0))
        pause_active = False
        if mode == "red":
            if now_ts >= pause_until:
                pause_until = now_ts + pause_sec
                self._runtime_ack_red_pause_until_ts = pause_until
            pause_active = now_ts < pause_until
        else:
            self._runtime_ack_red_pause_until_ts = 0.0

        if mode == "yellow":
            entry_boost = 0.20
            chunk_mult = 0.50
        elif mode == "red":
            entry_boost = 0.45
            chunk_mult = 0.25
        else:
            entry_boost = 0.0
            chunk_mult = 1.0

        last_mode = str(getattr(self, "_runtime_ack_mode", "green") or "green")
        if mode != last_mode:
            self._runtime_ack_mode = mode
            self._trace_runtime(
                "ack_mode_changed",
                mode=mode,
                prev=last_mode,
                p50=f"{p50:.3f}",
                p95=f"{p95:.3f}",
                samples=len(values),
                pause_active=bool(pause_active),
                pause_left_sec=f"{max(0.0, pause_until - now_ts):.2f}",
            )

        return {
            "mode": mode,
            "p50_sec": float(p50),
            "p95_sec": float(p95),
            "samples": int(len(values)),
            "entry_boost_pct": float(entry_boost),
            "entry_chunk_mult": float(chunk_mult),
            "pause_active": bool(pause_active),
            "pause_left_sec": float(max(0.0, pause_until - now_ts)),
        }

    def _on_runtime_quote_live(self, index):
        self._remember_runtime_quote_live(index)

    def _on_runtime_quote_error(self, index, error_text=""):
        if not bool(getattr(self._strategy_state, "is_running", False)):
            self._trace_runtime(
                "stream_error_ignored",
                index=index,
                error=self._normalize_runtime_error_text(error_text),
            )
            return
        reason = self._normalize_runtime_error_text(error_text)
        if not reason:
            reason = tr("spread.strategy.net_reason.stream_generic")
        else:
            reason = tr("spread.strategy.net_reason.stream_error", error=reason)
        self._runtime_set_degraded(reason, source=f"stream_{index}")
        if bool(getattr(self._strategy_state, "is_running", False)):
            self._update_strategy_state_label()

