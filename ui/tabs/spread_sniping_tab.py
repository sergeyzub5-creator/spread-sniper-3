from __future__ import annotations

from PySide6.QtCore import QEvent, QStringListModel, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from core.data.settings import SettingsManager
from core.i18n import tr
from features.spread_sniping.controllers import (
    SpreadDisplayMixin,
    SpreadQuoteMixin,
    SpreadSelectionMixin,
    SpreadStrategyMixin,
    SpreadStrategyRuntimeMixin,
    SpreadThemeMixin,
)
from features.spread_sniping.models import SpreadColumnContext
from features.spread_sniping.services.bitget_book_ticker_stream import (
    BitgetBookTickerStream,
)
from features.spread_sniping.services.binance_book_ticker_stream import (
    BinanceBookTickerStream,
)
from features.spread_sniping.services.spread_runtime_service import (
    SpreadRuntimeService,
)
from features.spread_sniping.services.strategy_engine import SpreadStrategyEngine
from features.spread_sniping.services.strategy_execution_service import (
    SpreadStrategyExecutionService,
)
from core.utils.logger import get_logger
from ui.utils import apply_stable_numeric_label, numeric_monospace_font


class SpreadSnipingTab(
    SpreadThemeMixin,
    SpreadDisplayMixin,
    SpreadSelectionMixin,
    SpreadQuoteMixin,
    SpreadStrategyRuntimeMixin,
    SpreadStrategyMixin,
    QWidget,
):
    POPULAR_PAIRS = (
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "XRPUSDT",
        "DOGEUSDT",
        "ADAUSDT",
        "TRXUSDT",
        "LTCUSDT",
        "LINKUSDT",
        "AVAXUSDT",
        "DOTUSDT",
    )

    MAX_SUGGESTIONS = 40
    POPULAR_SUGGESTIONS = 12
    COLUMN_WIDTH = 250
    COLUMN_WIDTH_MIN = 180
    QUOTE_PANEL_WIDTH = 540
    QUOTE_PANEL_WIDTH_MIN = 430
    SPREAD_VALUE_HEIGHT = 84
    SPREAD_VALUE_WIDTH = 250
    SUPPORTED_SPREAD_VARIANTS = (
        "neon_frame",
        "glass_slate",
        "signal_split",
        "minimal_pro",
    )
    def __init__(self, exchange_manager, parent=None):
        super().__init__(parent)
        self._trace_logger = get_logger("spread.trace")
        self.exchange_manager = exchange_manager
        self.settings_manager = SettingsManager()
        self._spread_armed = True
        self._spread_visual_variant = "signal_split"
        self._runtime_service = SpreadRuntimeService(
            exchange_manager=self.exchange_manager,
            popular_pairs=self.POPULAR_PAIRS,
        )
        self._strategy_engine = SpreadStrategyEngine()
        self._strategy_execution_service = SpreadStrategyExecutionService()
        self._init_strategy_state()
        self._init_strategy_runtime()

        self._columns = [SpreadColumnContext(index=1), SpreadColumnContext(index=2)]
        self._columns_map = {column.index: column for column in self._columns}

        self._pair_cache = {}
        self._pair_popular_cache = {}
        self._pair_cache_state = {}
        self._pair_last_retry_ts = {}
        self._pair_retry_cooldown_sec = 2.5
        self._pair_loading = set()
        self._pair_workers = {}

        for column in self._iter_columns():
            binance_stream = BinanceBookTickerStream(self)
            bitget_stream = BitgetBookTickerStream(self)

            column.quote_streams = {
                "binance": binance_stream,
                "bitget": bitget_stream,
            }

            for stream in column.quote_streams.values():
                stream.tick.connect(lambda payload, idx=column.index: self._on_quote_tick(idx, payload))
                stream.error.connect(lambda err, idx=column.index: self._on_quote_stream_error(idx, err))

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._init_ui()
        self.exchange_manager.status_updated.connect(self._on_status_updated)
        self.destroyed.connect(lambda *_args: self._stop_all_quote_streams())
        self.destroyed.connect(lambda *_args: self._shutdown_strategy_runtime())

    @staticmethod
    def _trace_format_fields(fields):
        parts = []
        for key, value in (fields or {}).items():
            if value is None:
                continue
            text = str(value).replace("\n", " ").strip()
            if not text:
                continue
            if len(text) > 240:
                text = f"{text[:237]}..."
            parts.append(f"{key}={text}")
        return " | ".join(parts)

    def _trace(self, event, **fields):
        logger = getattr(self, "_trace_logger", None)
        if logger is None:
            return
        suffix = self._trace_format_fields(fields)
        if suffix:
            logger.info("[TRACE] %s | %s", str(event or "event"), suffix)
        else:
            logger.info("[TRACE] %s", str(event or "event"))

    def _iter_columns(self):
        return self._columns

    def _column(self, index):
        return self._columns_map.get(int(index))

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self.container = QFrame()
        self.container.setObjectName("spreadContainer")

        card_layout = QVBoxLayout(self.container)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(8)

        selectors_row = self._build_selectors_with_spread_row()
        quotes_row = self._build_dual_row(self._create_quote_widget)
        strategy_panel = self._create_strategy_panel()
        card_layout.addLayout(selectors_row)
        card_layout.addLayout(quotes_row)
        card_layout.addWidget(strategy_panel)
        card_layout.addStretch()

        layout.addWidget(self.container)

        self.apply_theme()
        self.retranslate_ui()
        self._restore_spread_selection()
        self._update_selector_pair_capsule_widths()
        self._update_quote_panel_width()
        self._refresh_selector_state()
        self._refresh_spread_display()
        self._sync_strategy_fields_from_config()
        self._update_strategy_state_label()

    def _build_dual_row(self, widget_factory):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        columns = self._iter_columns()
        for pos, column in enumerate(columns):
            half = QWidget()
            half_layout = QHBoxLayout(half)
            if pos == 0:
                half_layout.setContentsMargins(0, 0, 8, 0)
            else:
                half_layout.setContentsMargins(8, 0, 0, 0)
            half_layout.setSpacing(0)
            half_layout.addStretch()
            half_layout.addWidget(widget_factory(column), 0)
            half_layout.addStretch()
            row.addWidget(half, 1)
        return row

    def _build_dual_row_with_center_gap(self, widget_factory, center_gap_width):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        columns = self._iter_columns()
        if len(columns) < 2:
            return row

        left_half = QWidget()
        left_layout = QHBoxLayout(left_half)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addStretch()
        left_layout.addWidget(widget_factory(columns[0]), 0)
        left_layout.addStretch()

        right_half = QWidget()
        right_layout = QHBoxLayout(right_half)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addStretch()
        right_layout.addWidget(widget_factory(columns[1]), 0)
        right_layout.addStretch()

        center_gap = QWidget()
        center_gap.setFixedWidth(max(1, int(center_gap_width or 1)))

        row.addWidget(left_half, 1)
        row.addWidget(center_gap, 0, Qt.AlignmentFlag.AlignCenter)
        row.addWidget(right_half, 1)
        return row

    def _build_selectors_with_spread_row(self):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        columns = self._iter_columns()
        if len(columns) < 2:
            return row

        left_half = QWidget()
        left_layout = QVBoxLayout(left_half)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(self._create_selector_button(columns[0]), 0, Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self._create_pair_input(columns[0]), 0, Qt.AlignmentFlag.AlignCenter)

        right_half = QWidget()
        right_layout = QVBoxLayout(right_half)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(self._create_selector_button(columns[1]), 0, Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self._create_pair_input(columns[1]), 0, Qt.AlignmentFlag.AlignCenter)

        center_column = QFrame()
        center_column.setObjectName("spreadCenterColumn")
        center_column.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        center_column.setMinimumWidth(self.SPREAD_VALUE_WIDTH + 14)

        center_layout = QVBoxLayout(center_column)
        center_layout.setContentsMargins(7, 4, 7, 4)
        center_layout.setSpacing(0)
        center_layout.addStretch()
        center_layout.addWidget(self._create_spread_value_widget(), 0, Qt.AlignmentFlag.AlignCenter)
        center_layout.addStretch()

        row.addWidget(left_half, 1)
        row.addWidget(center_column, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(right_half, 1)
        return row

    def _create_selector_button(self, column):
        btn = QPushButton()
        btn.setObjectName("exchangeSelector")
        btn.setProperty("toneRole", "neutral")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedWidth(self.COLUMN_WIDTH)
        btn.clicked.connect(lambda _checked=False, idx=column.index: self._open_exchange_menu(idx))
        column.selector_button = btn
        return btn

    def _create_pair_input(self, column):
        edit = QLineEdit()
        edit.setObjectName("pairSelector")
        edit.setFixedWidth(self.COLUMN_WIDTH)
        edit.setVisible(False)
        edit.setEnabled(False)
        edit.setClearButtonEnabled(False)
        edit.installEventFilter(self)

        model = QStringListModel(self)
        completer = QCompleter(model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.setMaxVisibleItems(12)
        completer.activated.connect(
            lambda value, idx=column.index: self._on_pair_completer_activated(idx, value)
        )
        edit.setCompleter(completer)

        edit.textEdited.connect(lambda text, idx=column.index: self._on_pair_text_edited(idx, text))
        edit.editingFinished.connect(lambda idx=column.index: self._on_pair_editing_finished(idx))

        column.pair_edit = edit
        column.pair_model = model
        column.pair_completer = completer
        return edit

    def _create_spread_value_widget(self):
        frame = QFrame()
        frame.setObjectName("spreadValueFrame")
        frame.setProperty("mode", "spread")
        frame.setProperty("variant", self._spread_visual_variant)
        frame.setProperty("edgeTone", "neutral")
        frame.setMinimumHeight(self.SPREAD_VALUE_HEIGHT)
        frame.setMinimumWidth(self.SPREAD_VALUE_WIDTH)
        frame.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.spread_value_frame = frame

        outer_layout = QVBoxLayout(frame)
        outer_layout.setContentsMargins(4, 1, 4, 1)
        outer_layout.setSpacing(0)
        self.spread_outer_layout = outer_layout

        inner = QFrame()
        inner.setObjectName("spreadValueInner")
        inner.setProperty("mode", "spread")
        inner.setProperty("variant", self._spread_visual_variant)
        self.spread_value_inner = inner
        outer_layout.addWidget(inner)

        stack = QStackedLayout(inner)
        stack.setContentsMargins(12, 6, 12, 6)
        stack.setStackingMode(QStackedLayout.StackingMode.StackOne)

        self.spread_select_btn = QPushButton()
        self.spread_select_btn.setObjectName("spreadActionButton")
        self.spread_select_btn.setProperty("variant", self._spread_visual_variant)
        self.spread_select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.spread_select_btn.clicked.connect(self._on_spread_select_clicked)

        self.spread_value_label = QLabel()
        self.spread_value_label.setObjectName("spreadValueLabel")
        self.spread_value_label.setProperty("variant", self._spread_visual_variant)
        self.spread_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spread_value_label.setFont(numeric_monospace_font(self.spread_value_label.font()))
        stack.addWidget(self.spread_select_btn)
        stack.addWidget(self.spread_value_label)
        self.spread_stack = stack
        return frame

    def _create_quote_widget(self, column):
        frame = QWidget()
        frame.setObjectName("quotePanel")
        frame.setFixedWidth(self.QUOTE_PANEL_WIDTH)
        frame.setVisible(False)

        row = QHBoxLayout(frame)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(8)

        bid_capsule = QFrame()
        bid_capsule.setObjectName("quoteSideCapsule")
        bid_capsule_row = QHBoxLayout(bid_capsule)
        bid_capsule_row.setContentsMargins(8, 3, 8, 3)
        bid_capsule_row.setSpacing(8)

        bid_price_label = QLabel()
        bid_price_label.setObjectName("bidPriceText")
        bid_price_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bid_price_label.setText(tr("spread.bid_price_empty"))

        bid_sep = QFrame()
        bid_sep.setObjectName("quoteMidDivider")
        bid_sep.setFixedWidth(1)

        bid_qty_label = QLabel()
        bid_qty_label.setObjectName("quoteQtyText")
        bid_qty_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bid_qty_label.setText(tr("spread.qty_empty"))
        apply_stable_numeric_label(
            bid_price_label,
            [
                tr("spread.bid_price", value="999999.12345678"),
                tr("spread.bid_price_loading"),
                tr("spread.bid_price_empty"),
            ],
        )
        apply_stable_numeric_label(
            bid_qty_label,
            [
                tr("spread.qty_value", qty="999.99M USDT"),
                tr("spread.qty_loading"),
                tr("spread.qty_empty"),
            ],
        )

        bid_capsule_row.addWidget(bid_price_label, 1)
        bid_capsule_row.addWidget(bid_sep, 0)
        bid_capsule_row.addWidget(bid_qty_label, 1)

        ask_capsule = QFrame()
        ask_capsule.setObjectName("quoteSideCapsule")
        ask_capsule_row = QHBoxLayout(ask_capsule)
        ask_capsule_row.setContentsMargins(8, 3, 8, 3)
        ask_capsule_row.setSpacing(8)

        ask_price_label = QLabel()
        ask_price_label.setObjectName("askPriceText")
        ask_price_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ask_price_label.setText(tr("spread.ask_price_empty"))

        ask_sep = QFrame()
        ask_sep.setObjectName("quoteMidDivider")
        ask_sep.setFixedWidth(1)

        ask_qty_label = QLabel()
        ask_qty_label.setObjectName("quoteQtyText")
        ask_qty_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ask_qty_label.setText(tr("spread.qty_empty"))
        apply_stable_numeric_label(
            ask_price_label,
            [
                tr("spread.ask_price", value="999999.12345678"),
                tr("spread.ask_price_loading"),
                tr("spread.ask_price_empty"),
            ],
        )
        apply_stable_numeric_label(
            ask_qty_label,
            [
                tr("spread.qty_value", qty="999.99M USDT"),
                tr("spread.qty_loading"),
                tr("spread.qty_empty"),
            ],
        )

        ask_capsule_row.addWidget(ask_price_label, 1)
        ask_capsule_row.addWidget(ask_sep, 0)
        ask_capsule_row.addWidget(ask_qty_label, 1)

        row.addWidget(bid_capsule, 1)
        row.addWidget(ask_capsule, 1)

        column.quote_frame = frame
        column.quote_bid_label = bid_price_label
        column.quote_ask_label = ask_price_label
        column.quote_bid_qty_label = bid_qty_label
        column.quote_ask_qty_label = ask_qty_label
        return frame

    @staticmethod
    def _clamp_int(value, low, high):
        number = int(round(float(value)))
        return max(int(low), min(int(high), number))

    def _text_width(self, widget, text):
        target = widget if widget is not None else self
        return max(0, target.fontMetrics().horizontalAdvance(str(text or "")))

    def _estimate_selector_pair_width(self):
        selector_probe = next(
            (column.selector_button for column in self._iter_columns() if column.selector_button is not None),
            None,
        )
        pair_probe = next((column.pair_edit for column in self._iter_columns() if column.pair_edit is not None), None)

        selector_texts = [tr("spread.exchange_1_default"), tr("spread.exchange_2_default")]
        pair_texts = [tr("spread.pair_placeholder"), tr("spread.pairs_loading"), tr("spread.pairs_empty")]
        for column in self._iter_columns():
            selector_texts.append(self._selector_text(column))
            if column.selected_exchange:
                selector_texts.append(column.selected_exchange)
            if column.selected_pair:
                pair_texts.append(column.selected_pair)

        selector_px = max(self._text_width(selector_probe, text) for text in selector_texts)
        pair_px = max(self._text_width(pair_probe, text) for text in pair_texts)

        selector_width = selector_px + 74  # icon + paddings + side margins
        pair_width = pair_px + 34
        target_width = max(selector_width, pair_width)
        return self._clamp_int(target_width, self.COLUMN_WIDTH_MIN, self.COLUMN_WIDTH)

    def _update_selector_pair_capsule_widths(self):
        width = self._estimate_selector_pair_width()
        for column in self._iter_columns():
            if column.selector_button is not None and column.selector_button.width() != width:
                column.selector_button.setFixedWidth(width)
            if column.pair_edit is not None and column.pair_edit.width() != width:
                column.pair_edit.setFixedWidth(width)

    def _estimate_quote_panel_width(self):
        price_probe = next(
            (column.quote_bid_label for column in self._iter_columns() if column.quote_bid_label is not None),
            None,
        )
        qty_probe = next(
            (column.quote_bid_qty_label for column in self._iter_columns() if column.quote_bid_qty_label is not None),
            None,
        )
        price_texts = [
            tr("spread.bid_price", value="999999.12345678"),
            tr("spread.ask_price", value="999999.12345678"),
            tr("spread.bid_price_loading"),
            tr("spread.ask_price_loading"),
            tr("spread.bid_price_empty"),
            tr("spread.ask_price_empty"),
        ]
        qty_texts = [
            tr("spread.qty_value", qty="999.99M USDT"),
            tr("spread.qty_loading"),
            tr("spread.qty_empty"),
        ]
        price_width = max(self._text_width(price_probe, text) for text in price_texts)
        qty_width = max(self._text_width(qty_probe, text) for text in qty_texts)

        side_capsule = (8 + 8) + price_width + qty_width + 1 + (8 * 2) + 4
        panel_width = (4 + 4) + (side_capsule * 2) + 8 + 6
        return self._clamp_int(panel_width, self.QUOTE_PANEL_WIDTH_MIN, self.QUOTE_PANEL_WIDTH)

    def _update_quote_panel_width(self):
        width = self._estimate_quote_panel_width()
        for column in self._iter_columns():
            if column.quote_frame is not None and column.quote_frame.width() != width:
                column.quote_frame.setFixedWidth(width)

    def retranslate_ui(self):
        if hasattr(self, "spread_select_btn"):
            self.spread_select_btn.setText(tr("action.select"))
        for column in self._iter_columns():
            apply_stable_numeric_label(
                column.quote_bid_label,
                [
                    tr("spread.bid_price", value="999999.12345678"),
                    tr("spread.bid_price_loading"),
                    tr("spread.bid_price_empty"),
                ],
            )
            apply_stable_numeric_label(
                column.quote_ask_label,
                [
                    tr("spread.ask_price", value="999999.12345678"),
                    tr("spread.ask_price_loading"),
                    tr("spread.ask_price_empty"),
                ],
            )
            apply_stable_numeric_label(
                column.quote_bid_qty_label,
                [
                    tr("spread.qty_value", qty="999.99M USDT"),
                    tr("spread.qty_loading"),
                    tr("spread.qty_empty"),
                ],
            )
            apply_stable_numeric_label(
                column.quote_ask_qty_label,
                [
                    tr("spread.qty_value", qty="999.99M USDT"),
                    tr("spread.qty_loading"),
                    tr("spread.qty_empty"),
                ],
            )
        self._retranslate_strategy_ui()
        self._update_selector_texts()
        self._update_selector_pair_capsule_widths()
        self._refresh_pair_controls()
        self._update_quote_panel_width()
        self._refresh_all_quote_labels()
        self._refresh_spread_display()
        self._update_strategy_state_label()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            click_index = None
            for column in self._iter_columns():
                if watched is column.pair_edit:
                    click_index = column.index
                    break

            if click_index is not None:
                self._on_pair_field_clicked(click_index)
            else:
                global_pos = self._extract_global_pos(event)
                if global_pos is not None and not self._is_pair_area_click(global_pos):
                    self._cancel_pair_input_sessions()
                    self._hide_all_pair_popups()
        return super().eventFilter(watched, event)
