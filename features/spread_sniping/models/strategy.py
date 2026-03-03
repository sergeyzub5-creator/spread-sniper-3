from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpreadStrategyConfig:
    """Persistent user configuration for spread strategy."""

    entry_threshold_pct: float = 0.20
    exit_threshold_pct: float = 0.08
    target_notional_usdt: float = 100.0
    step_notional_usdt: float = 20.0
    max_slippage_pct: float = 0.02

    def to_dict(self):
        return {
            "entry_threshold_pct": float(self.entry_threshold_pct),
            "exit_threshold_pct": float(self.exit_threshold_pct),
            "target_notional_usdt": float(self.target_notional_usdt),
            "step_notional_usdt": float(self.step_notional_usdt),
            "max_slippage_pct": float(self.max_slippage_pct),
        }

    @classmethod
    def from_mapping(cls, payload):
        source = payload if isinstance(payload, dict) else {}
        # Backward compatibility: old keys are migrated to USDT notionals.
        if "target_notional_usdt" not in source and "target_position_size" in source:
            migrated = dict(source)
            migrated["target_notional_usdt"] = source.get("target_position_size")
            source = migrated
        if "step_notional_usdt" not in source and "step_position_size" in source:
            migrated = dict(source)
            migrated["step_notional_usdt"] = source.get("step_position_size")
            source = migrated
        # Backward compatibility: old slippage in bps -> percent.
        if "max_slippage_pct" not in source and "max_slippage_bps" in source:
            migrated = dict(source)
            try:
                migrated["max_slippage_pct"] = float(source.get("max_slippage_bps", 0.0)) / 100.0
            except (TypeError, ValueError):
                migrated["max_slippage_pct"] = cls().max_slippage_pct
            source = migrated

        cfg = cls()
        for field_name, default_value in cfg.to_dict().items():
            raw = source.get(field_name, default_value)
            try:
                setattr(cfg, field_name, float(raw))
            except (TypeError, ValueError):
                setattr(cfg, field_name, float(default_value))
        return cfg


@dataclass
class SpreadStrategyState:
    """Runtime strategy state (stage 1: informational only)."""

    is_running: bool = False
    phase: str = "idle"
    active_hedged_size: float = 0.0
    last_spread_pct: float | None = None
    last_error: str = ""
    target_qty: float | None = None
    step_qty: float | None = None
    remaining_entry_qty: float = 0.0
    remaining_exit_qty: float = 0.0
    next_entry_qty: float = 0.0
    next_exit_qty: float = 0.0
    entry_buy_index: int | None = None
    entry_sell_index: int | None = None
    exit_buy_index: int | None = None
    exit_sell_index: int | None = None
    position_buy_index: int | None = None
    position_sell_index: int | None = None
    position_buy_exchange: str | None = None
    position_sell_exchange: str | None = None
    position_buy_pair: str | None = None
    position_sell_pair: str | None = None
    leg1_exchange: str = ""
    leg1_pair: str = ""
    leg1_qty: float = 0.0
    leg1_pnl: float = 0.0
    leg1_direction: str = "flat"
    leg2_exchange: str = ""
    leg2_pair: str = ""
    leg2_qty: float = 0.0
    leg2_pnl: float = 0.0
    leg2_direction: str = "flat"
    unbalanced_qty: float = 0.0
    session_exchange_1: str | None = None
    session_exchange_2: str | None = None
    session_start_balance: float | None = None
    session_end_balance: float | None = None
    session_pnl_balance: float | None = None
