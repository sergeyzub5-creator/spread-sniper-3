from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpreadStrategyConfig:
    """Persistent user configuration for spread strategy."""

    entry_threshold_pct: float = 0.20
    exit_threshold_pct: float = 0.08
    target_notional_usdt: float = 100.0
    step_notional_usdt: float = 20.0
    max_slippage_bps: float = 8.0

    def to_dict(self):
        return {
            "entry_threshold_pct": float(self.entry_threshold_pct),
            "exit_threshold_pct": float(self.exit_threshold_pct),
            "target_notional_usdt": float(self.target_notional_usdt),
            "step_notional_usdt": float(self.step_notional_usdt),
            "max_slippage_bps": float(self.max_slippage_bps),
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
