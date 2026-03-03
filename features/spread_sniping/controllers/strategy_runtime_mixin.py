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
    QUOTE_STALE_SEC = 8.0
    NETWORK_STABLE_RESUME_SEC = 2.2
    EMERGENCY_GAP_CONFIRM_SEC = 1.20
    EMERGENCY_AFTER_SUBMIT_SEC = 2.50
