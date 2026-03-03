from features.spread_sniping.controllers.strategy_runtime_execution_mixin import (
    SpreadStrategyRuntimeExecutionMixin,
)
from features.spread_sniping.controllers.strategy_runtime_lifecycle_mixin import (
    SpreadStrategyRuntimeLifecycleMixin,
)
from features.spread_sniping.controllers.strategy_runtime_network_mixin import (
    SpreadStrategyRuntimeNetworkMixin,
)
from features.spread_sniping.controllers.strategy_runtime_reconcile_mixin import (
    SpreadStrategyRuntimeReconcileMixin,
)


class SpreadStrategyRuntimeMixin(
    SpreadStrategyRuntimeNetworkMixin,
    SpreadStrategyRuntimeLifecycleMixin,
    SpreadStrategyRuntimeReconcileMixin,
    SpreadStrategyRuntimeExecutionMixin,
):
    STRATEGY_LOOP_INTERVAL_MS = 250
    ENTRY_QUOTE_STALE_SEC = 0.8
    EXIT_QUOTE_STALE_SEC = 8.0
    QUOTE_STALE_SEC = EXIT_QUOTE_STALE_SEC
    NETWORK_STABLE_RESUME_SEC = 2.2
    ENTRY_SIGNAL_HOLD_MS = 500
    EXIT_SIGNAL_HOLD_MS = 500
    COOLDOWN_AFTER_EXIT_MS = 1000
    EMERGENCY_GAP_CONFIRM_SEC = 1.20
    EMERGENCY_AFTER_SUBMIT_SEC = 2.50
