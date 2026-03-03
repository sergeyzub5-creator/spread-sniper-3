from __future__ import annotations

from features.spread_sniping.models import SpreadStrategyConfig, SpreadStrategyState


class SpreadStrategyExecutionService:
    """Builds execution plan (qty/legs) from spread signal and runtime state."""

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp_non_negative(value):
        numeric = SpreadStrategyExecutionService._to_float(value)
        if numeric is None:
            return 0.0
        return max(0.0, float(numeric))

    def _resolve_target_qty(self, spread_state, config):
        target_qty = self._to_float((spread_state or {}).get("target_qty"))
        if target_qty is not None and target_qty > 0:
            return float(target_qty)

        cfg = config if isinstance(config, SpreadStrategyConfig) else SpreadStrategyConfig()
        expensive_price = self._to_float((spread_state or {}).get("expensive_trade_price"))
        if expensive_price is None or expensive_price <= 0:
            return None
        target_notional = self._to_float(cfg.target_notional_usdt)
        if target_notional is None or target_notional <= 0:
            return None
        return float(target_notional) / float(expensive_price)

    def _resolve_step_qty(self, spread_state, config, target_qty):
        step_qty = self._to_float((spread_state or {}).get("step_qty"))
        if step_qty is not None and step_qty > 0:
            if target_qty is None:
                return float(step_qty)
            return min(float(step_qty), float(target_qty))

        cfg = config if isinstance(config, SpreadStrategyConfig) else SpreadStrategyConfig()
        expensive_price = self._to_float((spread_state or {}).get("expensive_trade_price"))
        if expensive_price is None or expensive_price <= 0:
            return None
        step_notional = self._to_float(cfg.step_notional_usdt)
        if step_notional is None or step_notional <= 0:
            return None

        resolved = float(step_notional) / float(expensive_price)
        if target_qty is None:
            return resolved
        return min(resolved, float(target_qty))

    def build_plan(self, spread_state, config, runtime_state):
        spread = spread_state if isinstance(spread_state, dict) else {}
        cfg = config if isinstance(config, SpreadStrategyConfig) else SpreadStrategyConfig()
        state = runtime_state if isinstance(runtime_state, SpreadStrategyState) else SpreadStrategyState()

        target_qty = self._resolve_target_qty(spread, cfg)
        step_qty = self._resolve_step_qty(spread, cfg, target_qty)
        active_qty = self._clamp_non_negative(getattr(state, "active_hedged_size", 0.0))

        if target_qty is None or target_qty <= 0:
            remaining_entry_qty = 0.0
            entry_complete = False
        else:
            remaining_entry_qty = max(0.0, float(target_qty) - active_qty)
            entry_complete = remaining_entry_qty <= 1e-12

        remaining_exit_qty = max(0.0, active_qty)
        exit_complete = remaining_exit_qty <= 1e-12

        if step_qty is None or step_qty <= 0:
            next_entry_qty = 0.0
            next_exit_qty = 0.0
        else:
            next_entry_qty = min(float(step_qty), remaining_entry_qty)
            next_exit_qty = min(float(step_qty), remaining_exit_qty)

        cheap_index = spread.get("cheap_index")
        expensive_index = spread.get("expensive_index")
        signal = str(spread.get("signal") or "")

        can_execute_entry = signal == "entry" and next_entry_qty > 0
        can_execute_exit = signal == "exit" and next_exit_qty > 0

        position_buy_index = self._to_float(getattr(state, "position_buy_index", None))
        position_sell_index = self._to_float(getattr(state, "position_sell_index", None))
        if position_buy_index is not None:
            position_buy_index = int(position_buy_index)
        if position_sell_index is not None:
            position_sell_index = int(position_sell_index)

        if position_buy_index not in {1, 2}:
            position_buy_index = None
        if position_sell_index not in {1, 2}:
            position_sell_index = None

        # Exit must always close the real opened legs, not recompute by current spread.
        exit_buy_index = position_sell_index if can_execute_exit else None
        exit_sell_index = position_buy_index if can_execute_exit else None

        if can_execute_exit and (exit_buy_index not in {1, 2} or exit_sell_index not in {1, 2}):
            can_execute_exit = False
            exit_buy_index = None
            exit_sell_index = None

        return {
            "target_qty": target_qty,
            "step_qty": step_qty,
            "active_qty": active_qty,
            "remaining_entry_qty": remaining_entry_qty,
            "remaining_exit_qty": remaining_exit_qty,
            "next_entry_qty": next_entry_qty,
            "next_exit_qty": next_exit_qty,
            "entry_complete": entry_complete,
            "exit_complete": exit_complete,
            "can_execute_entry": can_execute_entry,
            "can_execute_exit": can_execute_exit,
            "entry_buy_index": cheap_index if can_execute_entry else None,
            "entry_sell_index": expensive_index if can_execute_entry else None,
            "exit_buy_index": exit_buy_index,
            "exit_sell_index": exit_sell_index,
        }
