from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QVBoxLayout

from core.i18n import tr
from features.spread_sniping.models import SpreadStrategyConfig, SpreadStrategyState


class SpreadStrategyMixin:
    STRATEGY_FIELD_SPECS = (
        ("entry_threshold_pct", "spread.strategy.entry_threshold"),
        ("exit_threshold_pct", "spread.strategy.exit_threshold"),
        ("target_notional_usdt", "spread.strategy.target_size"),
        ("step_notional_usdt", "spread.strategy.step_size"),
        ("max_slippage_bps", "spread.strategy.max_slippage"),
    )

    def _init_strategy_state(self):
        self._strategy_config = SpreadStrategyConfig()
        self._strategy_state = SpreadStrategyState()
        self._strategy_fields = {}
        self._load_strategy_config()

    def _load_strategy_config(self):
        defaults = self._strategy_config.to_dict()
        payload = self.settings_manager.load_spread_strategy_config(defaults)
        self._strategy_config = SpreadStrategyConfig.from_mapping(payload)
        self._normalize_strategy_config()

    def _normalize_strategy_config(self):
        cfg = self._strategy_config
        cfg.entry_threshold_pct = max(0.0, float(cfg.entry_threshold_pct or 0.0))
        cfg.exit_threshold_pct = max(0.0, float(cfg.exit_threshold_pct or 0.0))
        cfg.max_slippage_bps = max(0.0, float(cfg.max_slippage_bps or 0.0))
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
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.strategy_title_label = QLabel()
        self.strategy_title_label.setObjectName("strategyTitle")
        layout.addWidget(self.strategy_title_label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        self._strategy_field_labels = {}
        for idx, (field_name, label_key) in enumerate(self.STRATEGY_FIELD_SPECS):
            cell = QFrame()
            cell.setObjectName("strategyFieldCell")
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(4)

            label = QLabel()
            label.setObjectName("strategyFieldLabel")
            self._strategy_field_labels[field_name] = (label, label_key)

            edit = QLineEdit()
            edit.setObjectName("strategyField")
            edit.setMaximumWidth(140)
            edit.editingFinished.connect(
                lambda name=field_name: self._on_strategy_field_edited(name)
            )

            self._strategy_fields[field_name] = edit
            cell_layout.addWidget(label)
            cell_layout.addWidget(edit)

            row = idx // 3
            col = idx % 3
            grid.addWidget(cell, row, col)

        layout.addLayout(grid)

        self.strategy_state_label = QLabel()
        self.strategy_state_label.setObjectName("strategyState")
        self.strategy_state_label.setProperty("stateKind", "idle")
        layout.addWidget(self.strategy_state_label)
        return panel

    def _field_precision(self, field_name):
        if field_name in {"entry_threshold_pct", "exit_threshold_pct"}:
            return 3
        if field_name == "target_notional_usdt":
            return 2
        if field_name == "step_notional_usdt":
            return 2
        if field_name == "max_slippage_bps":
            return 2
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

    def _parse_strategy_input(self, field_name, raw_text):
        text = str(raw_text or "").strip().replace(",", ".")
        if not text:
            return None
        try:
            value = float(text)
        except (TypeError, ValueError):
            return None

        if field_name in {"entry_threshold_pct", "exit_threshold_pct", "max_slippage_bps"}:
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
            self._update_strategy_state_label()
            return

        setattr(self._strategy_config, field_name, parsed)
        self._normalize_strategy_config()
        self._persist_strategy_config()
        self._strategy_state.last_error = ""
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
            effective = self._to_float(self._strategy_state.last_spread_pct)
            spread_text = "--" if effective is None else f"{effective:.2f}"
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

        label.setText(text)
        if label.property("stateKind") != state_kind:
            label.setProperty("stateKind", state_kind)
            label.style().unpolish(label)
            label.style().polish(label)
        label.update()

    def _retranslate_strategy_ui(self):
        title = getattr(self, "strategy_title_label", None)
        if title is not None:
            title.setText(tr("spread.strategy.title"))

        for _field_name, pair in getattr(self, "_strategy_field_labels", {}).items():
            label, label_key = pair
            if label is not None:
                label.setText(tr(label_key))

    def _sync_strategy_state_from_spread(self, spread_state):
        state = spread_state if isinstance(spread_state, dict) else {}
        self._strategy_state.phase = str(state.get("phase") or "idle")
        self._strategy_state.last_spread_pct = self._to_float(state.get("effective_edge_pct"))
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
                font-size: 12px;
                font-weight: 700;
                padding-left: 2px;
            }}
            QLabel#strategyFieldLabel {{
                color: {c_muted};
                font-size: 11px;
                font-weight: 600;
                padding-left: 2px;
            }}
            QLineEdit#strategyField {{
                background-color: {self._rgba(c_alt, 0.95)};
                color: {c_primary};
                border: 1px solid {self._rgba(c_border, 0.70)};
                border-radius: 8px;
                min-height: 30px;
                padding: 4px 8px;
                font-size: 12px;
                font-weight: 600;
            }}
            QLineEdit#strategyField:focus {{
                border-color: {c_accent};
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
        """
