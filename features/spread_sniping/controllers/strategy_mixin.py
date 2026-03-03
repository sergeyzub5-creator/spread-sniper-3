from __future__ import annotations
import math
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from core.i18n import tr
from features.spread_sniping.models import SpreadStrategyConfig, SpreadStrategyState
from ui.utils import numeric_monospace_font


class SpreadStrategyMixin:
    STRATEGY_FIELD_SPECS = (
        ("entry_threshold_pct", "spread.strategy.entry_threshold"),
        ("exit_threshold_pct", "spread.strategy.exit_threshold"),
        ("target_notional_usdt", "spread.strategy.target_size"),
        ("step_notional_usdt", "spread.strategy.step_size"),
        ("max_slippage_pct", "spread.strategy.max_slippage"),
    )

    def _init_strategy_state(self):
        self._strategy_config = SpreadStrategyConfig()
        self._strategy_state = SpreadStrategyState()
        self._strategy_fields = {}
        self._strategy_qty_trace_last = None
        self._strategy_qty_trace_last_ts = 0.0
        self._load_strategy_config()

    def _trace_strategy_cfg(self, event, **fields):
        trace = getattr(self, "_trace", None)
        if callable(trace):
            trace(f"strategy_cfg.{event}", **fields)

    def _load_strategy_config(self):
        defaults = self._strategy_config.to_dict()
        payload = self.settings_manager.load_spread_strategy_config(defaults)
        self._strategy_config = SpreadStrategyConfig.from_mapping(payload)
        self._normalize_strategy_config()

    def _normalize_strategy_config(self):
        cfg = self._strategy_config
        cfg.entry_threshold_pct = max(0.0, float(cfg.entry_threshold_pct or 0.0))
        cfg.exit_threshold_pct = max(0.0, float(cfg.exit_threshold_pct or 0.0))
        cfg.max_slippage_pct = max(0.0, float(cfg.max_slippage_pct or 0.0))
        cfg.target_notional_usdt = max(1.0, float(cfg.target_notional_usdt or 0.0))
        cfg.step_notional_usdt = max(1.0, float(cfg.step_notional_usdt or 0.0))
        if cfg.step_notional_usdt > cfg.target_notional_usdt:
            cfg.step_notional_usdt = cfg.target_notional_usdt

    def _persist_strategy_config(self):
        self.settings_manager.save_spread_strategy_config(self._strategy_config.to_dict())

    def _create_strategy_panel(self):
        panel = QFrame()
        panel.setObjectName("strategyPanel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self.strategy_title_label = QLabel()
        self.strategy_title_label.setObjectName("strategyTitle")
        layout.addWidget(self.strategy_title_label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        self._strategy_capsules = []
        self._strategy_field_labels = {}
        for idx, (field_name, label_key) in enumerate(self.STRATEGY_FIELD_SPECS):
            cell = QFrame()
            cell.setObjectName("strategyFieldCapsule")
            cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            cell.setMinimumHeight(32)
            self._strategy_capsules.append(cell)
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(8, 3, 8, 3)
            cell_layout.setSpacing(6)

            label = QLabel()
            label.setObjectName("strategyFieldInlineLabel")
            self._strategy_field_labels[field_name] = (label, label_key)

            divider = QFrame()
            divider.setObjectName("strategyFieldDivider")
            divider.setFixedWidth(1)

            edit = QLineEdit()
            edit.setObjectName("strategyFieldInput")
            edit.setMaximumWidth(72)
            edit.setMinimumWidth(56)
            edit.setFixedHeight(24)
            edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            edit.editingFinished.connect(
                lambda name=field_name: self._on_strategy_field_edited(name)
            )

            self._strategy_fields[field_name] = edit
            cell_layout.addWidget(label, 1)
            cell_layout.addWidget(divider, 0)
            cell_layout.addWidget(edit, 0)

            row = 0
            col = idx
            grid.addWidget(cell, row, col)
            grid.setColumnStretch(col, 1)

        layout.addLayout(grid)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(6)
        actions_row.addStretch()

        self.strategy_start_btn = QPushButton()
        self.strategy_start_btn.setObjectName("strategyStartButton")
        self.strategy_start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.strategy_start_btn.setMinimumWidth(126)
        self.strategy_start_btn.clicked.connect(self._on_strategy_start_clicked)
        actions_row.addWidget(self.strategy_start_btn)

        self.strategy_stop_btn = QPushButton()
        self.strategy_stop_btn.setObjectName("strategyStopButton")
        self.strategy_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.strategy_stop_btn.setMinimumWidth(126)
        self.strategy_stop_btn.clicked.connect(self._on_strategy_stop_clicked)
        actions_row.addWidget(self.strategy_stop_btn)

        self.strategy_force_close_btn = QPushButton()
        self.strategy_force_close_btn.setObjectName("strategyForceCloseButton")
        self.strategy_force_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.strategy_force_close_btn.setMinimumWidth(138)
        self.strategy_force_close_btn.clicked.connect(self._on_strategy_force_close_clicked)
        actions_row.addWidget(self.strategy_force_close_btn)

        layout.addLayout(actions_row)

        self.strategy_state_label = QLabel()
        self.strategy_state_label.setObjectName("strategyState")
        self.strategy_state_label.setProperty("stateKind", "idle")
        layout.addWidget(self.strategy_state_label)

        self.strategy_process_label = QLabel()
        self.strategy_process_label.setObjectName("strategyProcessTop")
        self.strategy_process_label.setWordWrap(False)
        process_font = numeric_monospace_font(self.strategy_process_label.font())
        process_font.setBold(True)
        self.strategy_process_label.setFont(process_font)
        layout.addWidget(self.strategy_process_label)

        self.strategy_process_label_bottom = QLabel()
        self.strategy_process_label_bottom.setObjectName("strategyProcessBottom")
        self.strategy_process_label_bottom.setWordWrap(False)
        process_bottom_font = numeric_monospace_font(self.strategy_process_label_bottom.font())
        process_bottom_font.setBold(True)
        self.strategy_process_label_bottom.setFont(process_bottom_font)
        layout.addWidget(self.strategy_process_label_bottom)

        self._update_strategy_toggle_button()
        self._update_strategy_force_close_button()
        self._update_strategy_process_label()
        self._sync_strategy_capsule_sizes()
        return panel

    def _field_precision(self, field_name):
        if field_name in {"entry_threshold_pct", "exit_threshold_pct"}:
            return 3
        if field_name == "target_notional_usdt":
            return 2
        if field_name == "step_notional_usdt":
            return 2
        if field_name == "max_slippage_pct":
            return 3
        return 4

    def _format_strategy_value(self, field_name, value):
        precision = self._field_precision(field_name)
        text = f"{float(value):.{precision}f}".rstrip("0").rstrip(".")
        return text if text else "0"

    def _sync_strategy_fields_from_config(self):
        for field_name, edit in self._strategy_fields.items():
            if not hasattr(self._strategy_config, field_name):
                continue
            edit.blockSignals(True)
            edit.setText(self._format_strategy_value(field_name, getattr(self._strategy_config, field_name)))
            edit.blockSignals(False)
        self._sync_strategy_capsule_sizes()

    def _sync_strategy_capsule_sizes(self):
        labels = getattr(self, "_strategy_field_labels", {})
        edits = getattr(self, "_strategy_fields", {})
        capsules = getattr(self, "_strategy_capsules", [])
        if not labels or not edits or not capsules:
            return

        max_label_width = 0
        for field_name, pair in labels.items():
            label, _key = pair
            if label is None:
                continue
            text = str(label.text() or "").strip()
            if not text:
                continue
            max_label_width = max(max_label_width, label.fontMetrics().horizontalAdvance(text))

        max_value_width = 0
        for field_name, edit in edits.items():
            if edit is None:
                continue
            current_text = str(edit.text() or "").strip()
            sample = current_text or self._format_strategy_value(field_name, getattr(self._strategy_config, field_name, 0))
            max_value_width = max(max_value_width, edit.fontMetrics().horizontalAdvance(sample))

        edit_width = max(56, min(88, max_value_width + 10))
        for edit in edits.values():
            if edit is None:
                continue
            edit.setFixedWidth(edit_width)

        capsule_width = max(120, max_label_width + edit_width + 31)
        for cell in capsules:
            if cell is None:
                continue
            cell.setMinimumWidth(capsule_width)

    def _parse_strategy_input(self, field_name, raw_text):
        text = str(raw_text or "").strip().replace(",", ".")
        if not text:
            return None
        try:
            value = float(text)
        except (TypeError, ValueError):
            return None

        if field_name in {"entry_threshold_pct", "exit_threshold_pct", "max_slippage_pct"}:
            return value if value >= 0 else None
        if field_name == "target_notional_usdt":
            return value if value >= 1.0 else None
        if field_name == "step_notional_usdt":
            return value if value >= 1.0 else None
        return value

    def _asset_qty_from_expensive_price(self, notional_usdt, expensive_price):
        price = self._to_float(expensive_price)
        notional = self._to_float(notional_usdt)
        if price is None or price <= 0 or notional is None or notional <= 0:
            return None
        return float(notional) / float(price)

    def _target_asset_qty_from_expensive_price(self, expensive_price):
        return self._asset_qty_from_expensive_price(
            self._strategy_config.target_notional_usdt, expensive_price
        )

    def _step_asset_qty_from_expensive_price(self, expensive_price):
        return self._asset_qty_from_expensive_price(
            self._strategy_config.step_notional_usdt, expensive_price
        )

    def _equal_leg_qty_from_expensive_price(self, expensive_price):
        target_qty = self._target_asset_qty_from_expensive_price(expensive_price)
        step_qty = self._step_asset_qty_from_expensive_price(expensive_price)
        if target_qty is None or step_qty is None:
            return None
        step_qty = min(step_qty, target_qty)
        if step_qty <= 0 or target_qty <= 0:
            return None
        return {
            "target_qty": target_qty,
            "step_qty": step_qty,
            "buy_qty": step_qty,
            "sell_qty": step_qty,
        }

    def _on_strategy_field_edited(self, field_name):
        edit = self._strategy_fields.get(field_name)
        if edit is None or not hasattr(self._strategy_config, field_name):
            return

        current_value = getattr(self._strategy_config, field_name)
        parsed = self._parse_strategy_input(field_name, edit.text())
        if parsed is None:
            edit.blockSignals(True)
            edit.setText(self._format_strategy_value(field_name, current_value))
            edit.blockSignals(False)
            self._strategy_state.last_error = tr(
                "spread.strategy.invalid_value",
                field=tr(dict(self.STRATEGY_FIELD_SPECS).get(field_name, "")),
            )
            self._trace_strategy_cfg(
                "invalid_value",
                field=field_name,
                raw=edit.text(),
                current=current_value,
            )
            self._update_strategy_state_label()
            return

        setattr(self._strategy_config, field_name, parsed)
        self._normalize_strategy_config()
        self._persist_strategy_config()
        self._strategy_state.last_error = ""
        if field_name in {"target_notional_usdt", "step_notional_usdt"}:
            clear_lock = getattr(self, "_clear_entry_target_lock", None)
            if callable(clear_lock):
                clear_lock(reason=f"config_{field_name}_changed")
        self._trace_strategy_cfg(
            "updated",
            field=field_name,
            value=getattr(self._strategy_config, field_name),
        )
        self._sync_strategy_fields_from_config()
        self._refresh_spread_display()

    def _update_strategy_state_label(self):
        label = getattr(self, "strategy_state_label", None)
        if label is None:
            return

        if str(self._strategy_state.last_error or "").strip():
            text = tr("spread.strategy.status_error", error=self._strategy_state.last_error)
            state_kind = "error"
        else:
            spread_text = self._format_status_spread_value(self._strategy_state.last_spread_pct)
            phase = str(self._strategy_state.phase or "idle")
            if phase == "entry_signal":
                text = tr(
                    "spread.strategy.status_entry_signal",
                    spread=spread_text,
                    threshold=f"{self._strategy_config.entry_threshold_pct:.2f}",
                )
                state_kind = "signal"
            elif phase == "wait_entry":
                text = tr(
                    "spread.strategy.status_wait_entry",
                    spread=spread_text,
                    threshold=f"{self._strategy_config.entry_threshold_pct:.2f}",
                )
                state_kind = "idle"
            elif phase == "exit_signal":
                text = tr(
                    "spread.strategy.status_exit_signal",
                    spread=spread_text,
                    threshold=f"{self._strategy_config.exit_threshold_pct:.2f}",
                )
                state_kind = "signal"
            elif phase == "wait_exit":
                text = tr(
                    "spread.strategy.status_wait_exit",
                    spread=spread_text,
                    threshold=f"{self._strategy_config.exit_threshold_pct:.2f}",
                )
                state_kind = "idle"
            elif phase == "no_data":
                text = tr("spread.strategy.status_no_data")
                state_kind = "idle"
            elif self._strategy_state.is_running:
                text = tr("spread.strategy.status_running")
                state_kind = "running"
            else:
                text = tr("spread.strategy.status_idle")
                state_kind = "idle"

            suffix = self._build_strategy_plan_suffix(phase)
            if suffix:
                text = f"{text}{suffix}"

        label.setText(text)
        if label.property("stateKind") != state_kind:
            label.setProperty("stateKind", state_kind)
            label.style().unpolish(label)
            label.style().polish(label)
        label.update()
        self._update_strategy_toggle_button()
        self._update_strategy_force_close_button()
        self._update_strategy_process_label()

    def _update_strategy_toggle_button(self):
        is_running = bool(getattr(self._strategy_state, "is_running", False))
        is_busy = bool(getattr(self, "_strategy_cycle_busy", False))

        start_btn = getattr(self, "strategy_start_btn", None)
        if start_btn is not None:
            start_btn.setText(tr("spread.strategy.start"))
            start_btn.setEnabled((not is_running) and (not is_busy))
            start_mode = "busy" if is_busy else ("active" if not is_running else "disabled")
            if start_btn.property("mode") != start_mode:
                start_btn.setProperty("mode", start_mode)
                start_btn.style().unpolish(start_btn)
                start_btn.style().polish(start_btn)
            start_btn.update()

        stop_btn = getattr(self, "strategy_stop_btn", None)
        if stop_btn is not None:
            stop_btn.setText(tr("spread.strategy.stop"))
            stop_btn.setEnabled(is_running)
            stop_mode = "busy" if is_busy else ("active" if is_running else "disabled")
            if stop_btn.property("mode") != stop_mode:
                stop_btn.setProperty("mode", stop_mode)
                stop_btn.style().unpolish(stop_btn)
                stop_btn.style().polish(stop_btn)
            stop_btn.update()

        # Backward compatibility if old toggle button is still present in an older layout.
        legacy_btn = getattr(self, "strategy_toggle_btn", None)
        if legacy_btn is not None:
            text = tr("spread.strategy.executing") if is_busy else (tr("spread.strategy.stop") if is_running else tr("spread.strategy.start"))
            mode = "busy" if is_busy else ("stop" if is_running else "start")
            legacy_btn.setText(text)
            legacy_btn.setEnabled(True)
            if legacy_btn.property("mode") != mode:
                legacy_btn.setProperty("mode", mode)
                legacy_btn.style().unpolish(legacy_btn)
                legacy_btn.style().polish(legacy_btn)
            legacy_btn.update()

    def _update_strategy_force_close_button(self):
        button = getattr(self, "strategy_force_close_btn", None)
        if button is None:
            return
        is_busy = bool(getattr(self, "_strategy_cycle_busy", False))
        active_qty = float(self._to_float(getattr(self._strategy_state, "active_hedged_size", 0.0)) or 0.0)
        can_close = active_qty > 1e-12
        button.setText(tr("spread.strategy.force_close"))
        button.setEnabled(can_close and not is_busy)
        mode = "busy" if is_busy else ("active" if can_close else "disabled")
        if button.property("mode") != mode:
            button.setProperty("mode", mode)
            button.style().unpolish(button)
            button.style().polish(button)
        button.update()

    def _strategy_phase_view(self):
        phase = str(getattr(self._strategy_state, "phase", "") or "").strip().lower()
        mapping = {
            "idle": "spread.strategy.phase_idle",
            "no_data": "spread.strategy.phase_no_data",
            "wait_entry": "spread.strategy.phase_wait_entry",
            "entry_signal": "spread.strategy.phase_entry_signal",
            "wait_exit": "spread.strategy.phase_wait_exit",
            "exit_signal": "spread.strategy.phase_exit_signal",
        }
        key = mapping.get(phase)
        return tr(key) if key else phase

    def _strategy_leg_view(self):
        state = self._strategy_state
        buy_name = str(getattr(state, "position_buy_exchange", "") or "").strip()
        sell_name = str(getattr(state, "position_sell_exchange", "") or "").strip()
        buy_pair = str(getattr(state, "position_buy_pair", "") or "").strip().upper()
        sell_pair = str(getattr(state, "position_sell_pair", "") or "").strip().upper()
        if not buy_name or not sell_name:
            return tr("spread.strategy.legs_none")
        return tr(
            "spread.strategy.legs_value",
            buy_exchange=buy_name,
            buy_pair=buy_pair or "--",
            sell_exchange=sell_name,
            sell_pair=sell_pair or "--",
        )

    def _resolve_strategy_leg_context(self, index):
        idx = int(index) if index in {1, 2} else None
        if idx not in {1, 2}:
            return "", ""
        column = self._column(idx)
        exchange_name = str(getattr(column, "selected_exchange", "") or "").strip() if column else ""
        pair_symbol = self._normalize_pair(getattr(column, "selected_pair", "") if column else "")

        state = self._strategy_state
        buy_idx = getattr(state, "position_buy_index", None)
        sell_idx = getattr(state, "position_sell_index", None)
        if not exchange_name:
            if buy_idx == idx:
                exchange_name = str(getattr(state, "position_buy_exchange", "") or "").strip()
            elif sell_idx == idx:
                exchange_name = str(getattr(state, "position_sell_exchange", "") or "").strip()
        if not pair_symbol:
            if buy_idx == idx:
                pair_symbol = self._normalize_pair(getattr(state, "position_buy_pair", ""))
            elif sell_idx == idx:
                pair_symbol = self._normalize_pair(getattr(state, "position_sell_pair", ""))
        return exchange_name, pair_symbol

    def _observe_strategy_leg(self, index):
        exchange_name, pair_symbol = self._resolve_strategy_leg_context(index)
        qty = 0.0
        pnl = 0.0
        net_size = 0.0
        if exchange_name and pair_symbol:
            exchange = self.exchange_manager.get_exchange(exchange_name)
            positions = list(getattr(exchange, "positions", []) or []) if exchange is not None else []
            for pos in positions:
                symbol = self._normalize_pair(pos.get("symbol"))
                if symbol != pair_symbol:
                    continue
                size = self._to_float(pos.get("size"))
                leg_pnl = self._to_float(pos.get("pnl"))
                if size is not None:
                    net_size += float(size)
                if leg_pnl is not None:
                    pnl += float(leg_pnl)
            qty = abs(float(net_size))

        if net_size > 1e-12:
            direction = "long"
        elif net_size < -1e-12:
            direction = "short"
        else:
            direction = "flat"

        return {
            "exchange": exchange_name,
            "pair": pair_symbol,
            "qty": float(qty),
            "pnl": float(pnl),
            "direction": direction,
        }

    def _sync_strategy_observed_legs(self):
        if not hasattr(self, "_strategy_state"):
            return
        state = self._strategy_state
        leg1 = self._observe_strategy_leg(1)
        leg2 = self._observe_strategy_leg(2)

        state.leg1_exchange = str(leg1.get("exchange") or "")
        state.leg1_pair = str(leg1.get("pair") or "")
        state.leg1_qty = float(leg1.get("qty") or 0.0)
        state.leg1_pnl = float(leg1.get("pnl") or 0.0)
        state.leg1_direction = str(leg1.get("direction") or "flat")

        state.leg2_exchange = str(leg2.get("exchange") or "")
        state.leg2_pair = str(leg2.get("pair") or "")
        state.leg2_qty = float(leg2.get("qty") or 0.0)
        state.leg2_pnl = float(leg2.get("pnl") or 0.0)
        state.leg2_direction = str(leg2.get("direction") or "flat")

        state.unbalanced_qty = abs(state.leg1_qty - state.leg2_qty)
        observed_active = max(state.leg1_qty, state.leg2_qty)
        if observed_active <= 1e-12:
            if not bool(getattr(state, "is_running", False)):
                state.active_hedged_size = 0.0
        else:
            state.active_hedged_size = float(observed_active)

    @staticmethod
    def _strategy_direction_view(direction):
        text = str(direction or "").strip().lower()
        if text == "long":
            return str(tr("spread.strategy.dir.long") or "").ljust(5)
        if text == "short":
            return str(tr("spread.strategy.dir.short") or "").ljust(5)
        return str(tr("spread.strategy.dir.flat") or "").ljust(5)

    @staticmethod
    def _format_strategy_pnl(value, decimals=2, width=None, signed=False):
        try:
            pnl = float(value)
        except (TypeError, ValueError):
            pnl = 0.0
        if signed:
            text = f"{float(pnl):+.{int(decimals)}f}"
        else:
            text = f"{float(pnl):.{int(decimals)}f}"
        return text.rjust(int(width)) if width else text

    def _update_strategy_process_label(self):
        label_top = getattr(self, "strategy_process_label", None)
        label_bottom = getattr(self, "strategy_process_label_bottom", None)
        if label_top is None:
            return
        state = self._strategy_state

        phase_text = str(self._strategy_phase_view() or "").strip().ljust(18)
        active_text = self._format_strategy_qty(state.active_hedged_size, decimals=4, width=11)
        target_text = self._format_strategy_qty(state.target_qty, decimals=4, width=11)
        wait_entry_text = self._format_strategy_qty(state.remaining_entry_qty, decimals=4, width=11)
        wait_exit_text = self._format_strategy_qty(state.remaining_exit_qty, decimals=4, width=11)
        next_entry_text = self._format_strategy_qty(state.next_entry_qty, decimals=4, width=11)
        next_exit_text = self._format_strategy_qty(state.next_exit_qty, decimals=4, width=11)
        target_text_plain = self._format_strategy_qty(state.target_qty, decimals=4, width=10)

        leg1_exchange = str(getattr(state, "leg1_exchange", "") or "--")
        leg1_pair = str(getattr(state, "leg1_pair", "") or "--")
        leg1_dir = self._strategy_direction_view(getattr(state, "leg1_direction", "flat"))
        leg1_qty = self._format_strategy_qty(getattr(state, "leg1_qty", 0.0), decimals=4, width=10)
        leg1_pnl = self._format_strategy_pnl(getattr(state, "leg1_pnl", 0.0), decimals=2, width=10)

        leg2_exchange = str(getattr(state, "leg2_exchange", "") or "--")
        leg2_pair = str(getattr(state, "leg2_pair", "") or "--")
        leg2_dir = self._strategy_direction_view(getattr(state, "leg2_direction", "flat"))
        leg2_qty = self._format_strategy_qty(getattr(state, "leg2_qty", 0.0), decimals=4, width=10)
        leg2_pnl = self._format_strategy_pnl(getattr(state, "leg2_pnl", 0.0), decimals=2, width=10)

        session_start = self._format_strategy_pnl(
            getattr(state, "session_start_balance", 0.0), decimals=2, width=11
        )
        session_end = self._format_strategy_pnl(
            getattr(state, "session_end_balance", 0.0), decimals=2, width=11
        )
        session_pnl = self._format_strategy_pnl(
            getattr(state, "session_pnl_balance", 0.0), decimals=2, width=9, signed=True
        )

        top_text = tr(
            "spread.strategy.process_line_top",
            phase=phase_text,
            active=active_text,
            target=target_text,
            wait_entry=wait_entry_text,
            wait_exit=wait_exit_text,
            next_entry=next_entry_text,
            next_exit=next_exit_text,
        )
        top_text = f"{top_text}   |   {tr('spread.strategy.session_pnl_short', start=session_start, end=session_end, pnl=session_pnl)}"
        bottom_text = tr(
            "spread.strategy.process_line_bottom_legs",
            leg1_exchange=leg1_exchange,
            leg1_pair=leg1_pair,
            leg1_direction=leg1_dir,
            leg1_qty=leg1_qty,
            leg1_target=target_text_plain,
            leg1_pnl=leg1_pnl,
            leg2_exchange=leg2_exchange,
            leg2_pair=leg2_pair,
            leg2_direction=leg2_dir,
            leg2_qty=leg2_qty,
            leg2_target=target_text_plain,
            leg2_pnl=leg2_pnl,
        )
        label_top.setText(top_text)
        label_top.update()
        if label_bottom is not None:
            label_bottom.setText(bottom_text)
            label_bottom.update()

    def _format_status_spread_value(self, value):
        spread = self._to_float(value)
        if spread is None:
            return "0.00"
        return f"{abs(spread):.2f}"

    def _format_strategy_qty(self, value, decimals=4, width=None):
        qty = self._to_float(value)
        if qty is None:
            text = f"{0.0:.{int(decimals)}f}"
            return text.rjust(int(width)) if width else text
        text = f"{float(qty):.{int(decimals)}f}"
        return text.rjust(int(width)) if width else text

    def _build_strategy_plan_suffix(self, phase):
        phase_name = str(phase or "")
        state = self._strategy_state

        if phase_name in {"entry_signal", "wait_entry"}:
            step_value = state.next_entry_qty or state.step_qty
            remaining_value = state.remaining_entry_qty
        elif phase_name in {"exit_signal", "wait_exit"}:
            step_value = state.next_exit_qty or state.step_qty
            remaining_value = state.remaining_exit_qty
        else:
            step_value = None
            remaining_value = None

        chunks = []
        target_qty = self._to_float(state.target_qty)
        if target_qty is not None and target_qty > 0:
            chunks.append(
                tr(
                    "spread.strategy.position_progress",
                    active=self._format_strategy_qty(state.active_hedged_size),
                    target=self._format_strategy_qty(target_qty),
                )
            )

        if step_value is not None and remaining_value is not None:
            chunks.append(
                tr(
                    "spread.strategy.step_remaining",
                    step=self._format_strategy_qty(step_value),
                    remaining=self._format_strategy_qty(remaining_value),
                )
            )

        if not chunks:
            return ""
        return " " + " ".join(chunks)

    def _resolve_common_entry_qty_constraints(self):
        runtime = getattr(self, "_runtime_service", None)
        if runtime is None or not hasattr(runtime, "get_common_qty_constraints"):
            return None
        left = self._column(1)
        right = self._column(2)
        if left is None or right is None:
            return None
        left_ex = str(getattr(left, "selected_exchange", "") or "").strip()
        right_ex = str(getattr(right, "selected_exchange", "") or "").strip()
        left_pair = self._normalize_pair(getattr(left, "selected_pair", ""))
        right_pair = self._normalize_pair(getattr(right, "selected_pair", ""))
        if not left_ex or not right_ex or not left_pair or not right_pair:
            return None
        try:
            return runtime.get_common_qty_constraints(left_ex, left_pair, right_ex, right_pair)
        except Exception:
            return None

    @staticmethod
    def _align_qty_down(value, step):
        if step is None or step <= 0:
            return float(value)
        return math.floor((float(value) / float(step)) + 1e-12) * float(step)

    @staticmethod
    def _align_qty_up(value, step):
        if step is None or step <= 0:
            return float(value)
        return math.ceil((float(value) / float(step)) - 1e-12) * float(step)

    def _quantize_target_qty(self, raw_target_qty, step_common, min_common):
        target = float(self._to_float(raw_target_qty) or 0.0)
        step = float(self._to_float(step_common) or 0.0)
        min_qty = float(self._to_float(min_common) or 0.0)
        if target <= 0 or step <= 0:
            return target
        min_qty = max(min_qty, step)

        lower = self._align_qty_down(target, step)
        upper = self._align_qty_up(target, step)

        candidates = []
        for qty in (lower, upper):
            if qty < min_qty:
                continue
            candidates.append(float(qty))
        if not candidates:
            return float(min_qty)
        candidates = sorted(set(candidates))
        return min(candidates, key=lambda q: (abs(q - target), q > target, q))

    def _quantize_step_qty(self, raw_step_qty, target_qty, step_common, min_common):
        target = float(self._to_float(target_qty) or 0.0)
        if target <= 0:
            return 0.0
        step = float(self._to_float(step_common) or 0.0)
        min_qty = float(self._to_float(min_common) or 0.0)
        if step <= 0:
            step = target
        min_qty = max(min_qty, step)

        raw = float(self._to_float(raw_step_qty) or 0.0)
        if raw <= 0:
            raw = step

        quantized = self._align_qty_down(raw, step)
        if quantized < min_qty:
            quantized = self._align_qty_up(min_qty, step)
        if quantized > target:
            quantized = self._align_qty_down(target, step)
            if quantized <= 0:
                quantized = target
        return float(max(0.0, quantized))

    def _apply_common_qty_constraints_to_plan(self, spread_state, plan):
        if not isinstance(plan, dict):
            return plan

        constraints = self._resolve_common_entry_qty_constraints()
        if not isinstance(constraints, dict):
            return plan

        step_common = float(self._to_float(constraints.get("step_common")) or 0.0)
        min_common = float(self._to_float(constraints.get("min_qty_common")) or 0.0)
        if step_common <= 0 or min_common <= 0:
            return plan

        target_raw = self._to_float(plan.get("target_qty"))
        if target_raw is None or target_raw <= 0:
            return plan

        active_qty = float(self._to_float(plan.get("active_qty")) or 0.0)
        target_qty = self._quantize_target_qty(target_raw, step_common, min_common)
        if target_qty < active_qty:
            target_qty = active_qty

        step_raw = self._to_float(plan.get("step_qty"))
        step_qty = self._quantize_step_qty(step_raw, target_qty, step_common, min_common)
        if step_qty <= 0:
            step_qty = min(target_qty, max(min_common, step_common))

        remaining_entry = max(0.0, target_qty - active_qty)
        remaining_exit = max(0.0, active_qty)
        next_entry = min(step_qty, remaining_entry) if remaining_entry > 0 else 0.0
        next_exit = min(step_qty, remaining_exit) if remaining_exit > 0 else 0.0

        signal = str((spread_state or {}).get("signal") or "").strip().lower()
        can_execute_entry = signal == "entry" and next_entry > 0
        can_execute_exit = signal == "exit" and next_exit > 0

        adjusted = dict(plan)
        adjusted["target_qty"] = float(target_qty)
        adjusted["step_qty"] = float(step_qty)
        adjusted["remaining_entry_qty"] = float(remaining_entry)
        adjusted["remaining_exit_qty"] = float(remaining_exit)
        adjusted["next_entry_qty"] = float(next_entry)
        adjusted["next_exit_qty"] = float(next_exit)
        adjusted["can_execute_entry"] = bool(can_execute_entry)
        adjusted["can_execute_exit"] = bool(can_execute_exit)
        if can_execute_entry:
            adjusted["entry_buy_index"] = (spread_state or {}).get("cheap_index")
            adjusted["entry_sell_index"] = (spread_state or {}).get("expensive_index")
        else:
            adjusted["entry_buy_index"] = None
            adjusted["entry_sell_index"] = None

        trace = getattr(self, "_trace", None)
        if callable(trace):
            trace_key = (
                round(float(target_raw), 8),
                round(float(adjusted["target_qty"]), 8),
                round(float(step_raw or 0.0), 8),
                round(float(adjusted["step_qty"]), 8),
                round(float(step_common), 8),
                round(float(min_common), 8),
            )
            last_key = getattr(self, "_strategy_qty_trace_last", None)
            now_ts = time.monotonic()
            last_ts = float(getattr(self, "_strategy_qty_trace_last_ts", 0.0) or 0.0)
            if trace_key != last_key or (now_ts - last_ts) >= 2.0:
                trace(
                    "strategy.qty_quantized",
                    target_raw=target_raw,
                    target_aligned=adjusted["target_qty"],
                    step_raw=step_raw,
                    step_aligned=adjusted["step_qty"],
                    step_common=step_common,
                    min_common=min_common,
                )
                self._strategy_qty_trace_last = trace_key
                self._strategy_qty_trace_last_ts = now_ts
        return adjusted

    def _retranslate_strategy_ui(self):
        title = getattr(self, "strategy_title_label", None)
        if title is not None:
            title.setText(tr("spread.strategy.title"))

        for _field_name, pair in getattr(self, "_strategy_field_labels", {}).items():
            label, label_key = pair
            if label is not None:
                label.setText(tr(label_key))
        self._update_strategy_toggle_button()
        self._update_strategy_force_close_button()
        self._update_strategy_process_label()
        self._sync_strategy_capsule_sizes()

    def _sync_strategy_state_from_spread(self, spread_state):
        state = spread_state if isinstance(spread_state, dict) else {}
        self._sync_strategy_observed_legs()
        self._strategy_state.phase = str(state.get("phase") or "idle")

        planner = getattr(self, "_strategy_execution_service", None)
        if planner is not None:
            plan = planner.build_plan(state, self._strategy_config, self._strategy_state)
        else:
            plan = {}

        plan = self._apply_common_qty_constraints_to_plan(state, plan)

        lock_getter = getattr(self, "_get_entry_target_lock_qty", None)
        locked_target_qty = lock_getter() if callable(lock_getter) else None
        if locked_target_qty is not None:
            plan = dict(plan)
            active_qty = float(self._to_float(plan.get("active_qty")) or 0.0)
            effective_target = max(float(locked_target_qty), active_qty)
            plan["target_qty"] = effective_target
            plan["remaining_entry_qty"] = 0.0
            plan["next_entry_qty"] = 0.0
            plan["can_execute_entry"] = False

        self._strategy_state.target_qty = self._to_float(plan.get("target_qty"))
        self._strategy_state.step_qty = self._to_float(plan.get("step_qty"))
        self._strategy_state.remaining_entry_qty = max(
            0.0, float(self._to_float(plan.get("remaining_entry_qty")) or 0.0)
        )
        self._strategy_state.remaining_exit_qty = max(
            0.0, float(self._to_float(plan.get("remaining_exit_qty")) or 0.0)
        )
        self._strategy_state.next_entry_qty = max(
            0.0, float(self._to_float(plan.get("next_entry_qty")) or 0.0)
        )
        self._strategy_state.next_exit_qty = max(
            0.0, float(self._to_float(plan.get("next_exit_qty")) or 0.0)
        )
        self._strategy_state.entry_buy_index = plan.get("entry_buy_index")
        self._strategy_state.entry_sell_index = plan.get("entry_sell_index")
        self._strategy_state.exit_buy_index = plan.get("exit_buy_index")
        self._strategy_state.exit_sell_index = plan.get("exit_sell_index")

        if self._strategy_state.phase == "entry_signal" and not bool(plan.get("can_execute_entry")):
            self._strategy_state.phase = "wait_entry"
        elif self._strategy_state.phase == "exit_signal" and not bool(plan.get("can_execute_exit")):
            self._strategy_state.phase = "wait_exit"

        spread_visible = bool(getattr(self, "_spread_armed", True))
        if spread_visible:
            self._strategy_state.last_spread_pct = self._to_float(state.get("percent"))
        else:
            # Keep status text in sync with center spread capsule: hidden there -> hidden here.
            self._strategy_state.last_spread_pct = None
        self._update_strategy_state_label()

    def _strategy_theme_qss(self, c_surface, c_border, c_alt, c_primary, c_muted, c_success, c_danger, c_accent):
        return f"""
            QFrame#strategyPanel {{
                background-color: {self._rgba(c_surface, 0.72)};
                border: 1px solid {self._rgba(c_border, 0.48)};
                border-radius: 10px;
            }}
            QLabel#strategyTitle {{
                color: {c_primary};
                font-size: 11px;
                font-weight: 700;
                padding-left: 2px;
            }}
            QFrame#strategyFieldCapsule {{
                background: qlineargradient(
                    x1: 1, y1: 0, x2: 0, y2: 0,
                    stop: 0 {self._rgba(c_surface, 0.70)},
                    stop: 1 {self._rgba(c_alt, 0.94)}
                );
                border: 1px solid {self._rgba(c_border, 0.68)};
                border-radius: 8px;
            }}
            QLabel#strategyFieldInlineLabel {{
                color: {c_muted};
                font-size: 10px;
                font-weight: 600;
                padding-left: 2px;
                padding-right: 2px;
            }}
            QFrame#strategyFieldDivider {{
                background-color: {self._rgba(c_border, 0.62)};
                border: none;
                min-height: 14px;
                max-height: 14px;
            }}
            QLineEdit#strategyFieldInput {{
                background-color: transparent;
                color: {c_primary};
                border: none;
                min-height: 22px;
                padding: 0 2px;
                font-size: 13px;
                font-weight: 700;
            }}
            QLineEdit#strategyFieldInput:focus {{
                color: {c_accent};
            }}
            QLabel#strategyState {{
                color: {c_muted};
                font-size: 11px;
                font-weight: 600;
                padding: 2px 2px 0 2px;
            }}
            QLabel#strategyState[stateKind="running"] {{
                color: {c_success};
            }}
            QLabel#strategyState[stateKind="signal"] {{
                color: {c_accent};
            }}
            QLabel#strategyState[stateKind="error"] {{
                color: {c_danger};
            }}
            QLabel#strategyProcessTop {{
                color: {c_primary};
                font-size: 24px;
                font-weight: 700;
                padding: 6px 4px 2px 4px;
                min-height: 34px;
            }}
            QLabel#strategyProcessBottom {{
                color: {c_primary};
                font-size: 24px;
                font-weight: 700;
                padding: 2px 4px 6px 4px;
                min-height: 34px;
            }}
            QPushButton#strategyStartButton {{
                background-color: {self._rgba(c_alt, 0.92)};
                color: {c_primary};
                border: 1px solid {self._rgba(c_border, 0.76)};
                border-radius: 8px;
                min-height: 26px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 700;
            }}
            QPushButton#strategyStartButton:hover {{
                border-color: {self._rgba(c_accent, 0.80)};
            }}
            QPushButton#strategyStartButton[mode="active"] {{
                background-color: {self._rgba(c_success, 0.18)};
                border-color: {self._rgba(c_success, 0.62)};
            }}
            QPushButton#strategyStartButton[mode="disabled"] {{
                color: {self._rgba(c_muted, 0.92)};
            }}
            QPushButton#strategyStartButton[mode="busy"] {{
                background-color: {self._rgba(c_accent, 0.18)};
                border-color: {self._rgba(c_accent, 0.72)};
            }}
            QPushButton#strategyStopButton {{
                background-color: {self._rgba(c_alt, 0.92)};
                color: {c_primary};
                border: 1px solid {self._rgba(c_border, 0.76)};
                border-radius: 8px;
                min-height: 26px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 700;
            }}
            QPushButton#strategyStopButton:hover {{
                border-color: {self._rgba(c_accent, 0.80)};
            }}
            QPushButton#strategyStopButton[mode="active"] {{
                background-color: {self._rgba(c_danger, 0.18)};
                border-color: {self._rgba(c_danger, 0.62)};
            }}
            QPushButton#strategyStopButton[mode="disabled"] {{
                color: {self._rgba(c_muted, 0.92)};
            }}
            QPushButton#strategyStopButton[mode="busy"] {{
                background-color: {self._rgba(c_accent, 0.18)};
                border-color: {self._rgba(c_accent, 0.72)};
            }}
            QPushButton#strategyForceCloseButton {{
                background-color: {self._rgba(c_alt, 0.92)};
                color: {c_primary};
                border: 1px solid {self._rgba(c_border, 0.76)};
                border-radius: 8px;
                min-height: 26px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 700;
            }}
            QPushButton#strategyForceCloseButton[mode="active"] {{
                background-color: rgba(255, 188, 67, 0.24);
                border-color: rgba(255, 188, 67, 0.78);
                color: {c_primary};
            }}
            QPushButton#strategyForceCloseButton[mode="busy"] {{
                background-color: {self._rgba(c_accent, 0.18)};
                border-color: {self._rgba(c_accent, 0.72)};
            }}
            QPushButton#strategyForceCloseButton:disabled {{
                color: {self._rgba(c_muted, 0.92)};
            }}
        """
