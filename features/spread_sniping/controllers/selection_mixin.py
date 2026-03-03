from features.spread_sniping.controllers.pair_input_session_mixin import (
    SpreadPairInputSessionMixin,
)
from features.spread_sniping.controllers.pair_loader_mixin import SpreadPairLoaderMixin
from features.spread_sniping.controllers.pair_suggestions_mixin import (
    SpreadPairSuggestionsMixin,
)
from features.spread_sniping.controllers.selection_state_mixin import (
    SpreadSelectionStateMixin,
)


class SpreadSelectionMixin(
    SpreadSelectionStateMixin,
    SpreadPairLoaderMixin,
    SpreadPairSuggestionsMixin,
    SpreadPairInputSessionMixin,
):
    """Aggregate mixin for exchange/pair selection flow."""

