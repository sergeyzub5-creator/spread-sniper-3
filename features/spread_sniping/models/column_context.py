from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SpreadColumnContext:
    index: int

    selected_exchange: Optional[str] = None
    selected_pair: Optional[str] = None

    pair_accepting: bool = False
    pair_reedit: bool = False
    pair_edit_active: bool = False
    pair_edit_snapshot_pair: Optional[str] = None
    pair_edit_snapshot_text: str = ""

    quote_state: str = "empty"
    quote_bid: Optional[float] = None
    quote_ask: Optional[float] = None
    quote_bid_qty: Optional[float] = None
    quote_ask_qty: Optional[float] = None
    quote_stream_state: Optional[tuple] = None
    order_book_state: str = "empty"
    order_book_bids: list = field(default_factory=list)
    order_book_asks: list = field(default_factory=list)
    order_book_stream_state: Optional[tuple] = None
    own_order: Optional[dict] = None

    trade_status_state: Optional[tuple] = None
    trade_busy: bool = False

    selector_button: Any = None
    pair_edit: Any = None
    pair_model: Any = None
    pair_completer: Any = None

    quote_frame: Any = None
    quote_bid_label: Any = None
    quote_ask_label: Any = None
    quote_bid_qty_label: Any = None
    quote_ask_qty_label: Any = None

    order_book_frame: Any = None
    order_book_note_label: Any = None
    order_book_bid_labels: list = field(default_factory=list)
    order_book_ask_labels: list = field(default_factory=list)
    order_book_own_label: Any = None

    trade_frame: Any = None
    trade_note_label: Any = None
    trade_buy_button: Any = None
    trade_sell_button: Any = None
    trade_status_label: Any = None

    quote_stream: Any = None
    quote_streams: dict = field(default_factory=dict)
    quote_snapshot_worker: Any = None
    order_book_stream: Any = None
    order_book_snapshot_worker: Any = None
    trade_worker: Any = None
