from __future__ import annotations

from features.spread_sniping.models import SpreadStrategyConfig, SpreadStrategyState


class SpreadStrategyEngine:
    """Signal evaluation engine for spread strategy (stage 2, no order execution)."""

    POSITION_EPSILON = 1e-8

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _qty_from_notional(notional_usdt, price):
        px = SpreadStrategyEngine._to_float(price)
        notion = SpreadStrategyEngine._to_float(notional_usdt)
        if px is None or px <= 0 or notion is None or notion <= 0:
            return None
        return notion / px

    def evaluate(self, left_bid, left_ask, right_bid, right_ask, config, state):
        cfg = config if isinstance(config, SpreadStrategyConfig) else SpreadStrategyConfig()
        st = state if isinstance(state, SpreadStrategyState) else SpreadStrategyState()

        bid_1 = self._to_float(left_bid)
        ask_1 = self._to_float(left_ask)
        bid_2 = self._to_float(right_bid)
        ask_2 = self._to_float(right_ask)
        if (
            bid_1 is None
            or ask_1 is None
            or bid_2 is None
            or ask_2 is None
            or bid_1 <= 0
            or ask_1 <= 0
            or bid_2 <= 0
            or ask_2 <= 0
        ):
            return {
                "percent": None,
                "raw_edge_pct": None,
                "effective_edge_pct": None,
                "cheap_index": None,
                "expensive_index": None,
                "signal": None,
                "phase": "no_data",
                "expensive_trade_price": None,
                "target_qty": None,
                "step_qty": None,
            }

        edge_1 = (bid_1 - ask_2) / ask_2 if ask_2 else 0.0
        edge_2 = (bid_2 - ask_1) / ask_1 if ask_1 else 0.0

        if edge_1 >= edge_2:
            best_edge = edge_1
            expensive_index = 1
            cheap_index = 2
        else:
            best_edge = edge_2
            expensive_index = 2
            cheap_index = 1

        raw_edge_pct = best_edge * 100.0
        percent = abs(best_edge) * 100.0
        effective_edge_pct = max(raw_edge_pct, 0.0)
        if effective_edge_pct <= 0.0:
            cheap_index = None
            expensive_index = None

        expensive_trade_price = None
        if expensive_index == 1:
            expensive_trade_price = bid_1
        elif expensive_index == 2:
            expensive_trade_price = bid_2

        target_qty = self._qty_from_notional(cfg.target_notional_usdt, expensive_trade_price)
        step_qty = self._qty_from_notional(cfg.step_notional_usdt, expensive_trade_price)
        if target_qty is not None and step_qty is not None:
            step_qty = min(step_qty, target_qty)

        active_qty = max(0.0, float(st.active_hedged_size or 0.0))
        has_hedged_position = active_qty > float(self.POSITION_EPSILON)
        has_target = target_qty is not None and target_qty > 0.0
        need_entry_fill = has_target and (active_qty + 1e-12) < float(target_qty)

        signal = None
        # Exit must work at any moment when there is an open hedge,
        # even if entry target has not been fully collected yet.
        if has_hedged_position and raw_edge_pct <= float(cfg.exit_threshold_pct):
            signal = "exit"
            phase = "exit_signal"
        elif need_entry_fill:
            # Keep accumulating while edge >= entry threshold until target is reached.
            if effective_edge_pct >= float(cfg.entry_threshold_pct):
                signal = "entry"
                phase = "entry_signal"
            else:
                phase = "wait_entry"
        elif has_hedged_position:
            phase = "wait_exit"
        else:
            phase = "wait_entry"

        return {
            "percent": percent,
            "raw_edge_pct": raw_edge_pct,
            "effective_edge_pct": effective_edge_pct,
            "cheap_index": cheap_index,
            "expensive_index": expensive_index,
            "signal": signal,
            "phase": phase,
            "expensive_trade_price": expensive_trade_price,
            "target_qty": target_qty,
            "step_qty": step_qty,
        }
