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
    SpreadQuoteMixin,
    SpreadSelectionMixin,
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
from ui.styles import theme_color


class SpreadSnipingTab(
    SpreadSelectionMixin,
    SpreadQuoteMixin,
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
    QUOTE_PANEL_WIDTH = 540
    SPREAD_VALUE_HEIGHT = 84
    SPREAD_VALUE_WIDTH = 250

    def __init__(self, exchange_manager, parent=None):
        super().__init__(parent)
        self.exchange_manager = exchange_manager
        self.settings_manager = SettingsManager()
        self._spread_armed = True
        self._runtime_service = SpreadRuntimeService(
            exchange_manager=self.exchange_manager,
            popular_pairs=self.POPULAR_PAIRS,
        )

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
                stream.error.connect(lambda _err, idx=column.index: self._on_quote_stream_error(idx))

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._init_ui()
        self.exchange_manager.status_updated.connect(self._on_status_updated)
        self.destroyed.connect(lambda *_args: self._stop_all_quote_streams())

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
        card_layout.addLayout(selectors_row)
        card_layout.addLayout(quotes_row)
        card_layout.addStretch()

        layout.addWidget(self.container)

        self.apply_theme()
        self.retranslate_ui()
        self._restore_spread_selection()
        self._refresh_selector_state()
        self._refresh_spread_display()

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
        self.spread_value_inner = inner
        outer_layout.addWidget(inner)

        stack = QStackedLayout(inner)
        stack.setContentsMargins(12, 6, 12, 6)
        stack.setStackingMode(QStackedLayout.StackingMode.StackOne)

        self.spread_select_btn = QPushButton()
        self.spread_select_btn.setObjectName("spreadActionButton")
        self.spread_select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.spread_select_btn.clicked.connect(self._on_spread_select_clicked)

        self.spread_value_label = QLabel()
        self.spread_value_label.setObjectName("spreadValueLabel")
        self.spread_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

    def apply_theme(self):
        c_surface = theme_color("surface")
        c_window = theme_color("window_bg")
        c_border = theme_color("border")
        c_primary = theme_color("text_primary")
        c_muted = theme_color("text_muted")
        c_alt = theme_color("surface_alt")
        c_accent = theme_color("accent")
        c_success = theme_color("success")
        c_danger = theme_color("danger")
        c_capsule_border = self._rgba(c_accent, 0.52)
        c_capsule_glow = self._rgba(c_accent, 0.18)
        c_capsule_mid = self._rgba(c_alt, 0.95)
        c_capsule_hover = self._rgba(c_accent, 0.24)
        c_cheap_border = self._rgba(c_success, 0.76)
        c_cheap_tone = self._rgba(c_success, 0.20)
        c_cheap_hover = self._rgba(c_success, 0.30)
        c_exp_border = self._rgba(c_danger, 0.76)
        c_exp_tone = self._rgba(c_danger, 0.20)
        c_exp_hover = self._rgba(c_danger, 0.30)

        self.container.setStyleSheet(
            f"""
            QFrame#spreadContainer {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {self._rgba(c_alt, 0.96)},
                    stop: 1 {self._rgba(c_window, 0.98)}
                );
                border: 1px solid {self._rgba(c_border, 0.58)};
                border-radius: 12px;
            }}
            QPushButton#exchangeSelector {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {c_capsule_glow},
                    stop: 0.50 {c_capsule_mid},
                    stop: 1 {c_surface}
                );
                color: {c_primary};
                border: 1px solid {c_capsule_border};
                border-radius: 22px;
                min-height: 44px;
                font-size: 13px;
                font-weight: 700;
                padding: 8px 12px;
            }}
            QPushButton#exchangeSelector:hover {{
                border-color: {c_accent};
                background-color: {c_capsule_hover};
            }}
            QPushButton#exchangeSelector[toneRole="cheap"] {{
                border-color: {c_cheap_border};
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {c_cheap_tone},
                    stop: 0.50 {c_capsule_mid},
                    stop: 1 {c_surface}
                );
            }}
            QPushButton#exchangeSelector[toneRole="cheap"]:hover {{
                border-color: {c_success};
                background-color: {c_cheap_hover};
            }}
            QPushButton#exchangeSelector[toneRole="expensive"] {{
                border-color: {c_exp_border};
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {c_exp_tone},
                    stop: 0.50 {c_capsule_mid},
                    stop: 1 {c_surface}
                );
            }}
            QPushButton#exchangeSelector[toneRole="expensive"]:hover {{
                border-color: {c_danger};
                background-color: {c_exp_hover};
            }}
            QPushButton#exchangeSelector:disabled {{
                color: {c_muted};
                border-color: {c_border};
                background-color: {c_alt};
            }}
            QLineEdit#pairSelector {{
                background-color: {c_alt};
                color: {c_primary};
                border: 1px solid {c_capsule_border};
                border-radius: 14px;
                min-height: 32px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 600;
            }}
            QLineEdit#pairSelector:hover {{
                border-color: {c_accent};
                background-color: {c_capsule_hover};
            }}
            QLineEdit#pairSelector:focus {{
                border-color: {c_accent};
            }}
            QLineEdit#pairSelector:disabled {{
                color: {c_muted};
                border-color: {c_border};
                background-color: {c_surface};
            }}
            QWidget#quotePanel {{
                background-color: transparent;
                border: none;
                border-radius: 0px;
            }}
            QFrame#quoteSideCapsule {{
                background-color: {c_surface};
                border: none;
                border-radius: 8px;
            }}
            QFrame#quoteMidDivider {{
                background-color: {self._rgba(c_border, 0.55)};
                border: none;
                min-height: 18px;
                max-height: 18px;
            }}
            QFrame#spreadCenterColumn {{
                background-color: {self._rgba(c_alt, 0.50)};
                border: 1px solid {self._rgba(c_border, 0.35)};
                border-radius: 18px;
            }}
            QFrame#spreadValueFrame[mode="select"] {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {c_capsule_glow},
                    stop: 0.50 {c_capsule_mid},
                    stop: 1 {c_surface}
                );
                border: 1px solid {c_capsule_border};
                border-radius: 16px;
            }}
            QFrame#spreadValueFrame[mode="spread"] {{
                background-color: transparent;
                border: none;
                border-radius: 16px;
            }}
            QFrame#spreadValueInner[mode="spread"] {{
                background-color: {c_alt};
                border: none;
                border-radius: 14px;
            }}
            QFrame#spreadValueInner[mode="select"] {{
                background-color: transparent;
                border: none;
                border-radius: 16px;
            }}
            QPushButton#spreadActionButton {{
                background-color: transparent;
                color: {c_primary};
                border: none;
                border-radius: 16px;
                font-size: 20px;
                font-weight: 700;
                padding: 6px 12px;
            }}
            QPushButton#spreadActionButton:hover {{
                background-color: {c_capsule_hover};
            }}
            QPushButton#spreadActionButton:disabled {{
                color: {c_muted};
                background-color: transparent;
            }}
            QLabel#spreadValueLabel {{
                color: {c_accent};
                font-size: 56px;
                font-weight: 800;
                letter-spacing: 0.5px;
            }}
            QLabel#spreadValueLabel[empty="true"] {{
                color: {c_muted};
            }}
            QLabel#bidPriceText {{
                color: {theme_color('success')};
                font-size: 11px;
                font-weight: 700;
                padding-left: 4px;
            }}
            QLabel#askPriceText {{
                color: {theme_color('danger')};
                font-size: 11px;
                font-weight: 700;
                padding-left: 4px;
            }}
            QLabel#quoteQtyText {{
                color: {c_primary};
                font-size: 11px;
                font-weight: 700;
                padding-left: 4px;
            }}
        """
        )

        popup_style = f"""
            QListView#pairPopup {{
                background-color: {theme_color('window_bg')};
                color: {c_primary};
                border: 1px solid {c_border};
                border-radius: 8px;
                padding: 4px;
                outline: none;
                font-size: 12px;
            }}
            QListView#pairPopup::item {{
                padding: 6px 8px;
                border-radius: 6px;
            }}
            QListView#pairPopup::item:hover {{
                background-color: {self._rgba(c_accent, 0.20)};
                color: {c_primary};
            }}
            QListView#pairPopup::item:selected {{
                background-color: {theme_color('selection_bg_soft')};
                color: {c_accent};
                border: 1px solid {self._rgba(c_accent, 0.45)};
            }}
        """

        for column in self._iter_columns():
            if column.pair_completer is not None:
                popup = column.pair_completer.popup()
                popup.setObjectName("pairPopup")
                popup.setStyleSheet(popup_style)

    def retranslate_ui(self):
        if hasattr(self, "spread_select_btn"):
            self.spread_select_btn.setText(tr("action.select"))
        self._update_selector_texts()
        self._refresh_pair_controls()
        self._refresh_all_quote_labels()
        self._refresh_spread_display()

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

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_price(value):
        numeric = SpreadSnipingTab._to_float(value)
        if numeric is None:
            return "--"
        text = f"{numeric:.8f}".rstrip("0").rstrip(".")
        return text if text else "0"

    @staticmethod
    def _normalize_pair(value):
        text = str(value or "").strip().upper()
        if not text:
            return ""
        for ch in ("/", "-", "_", " "):
            text = text.replace(ch, "")
        return text

    def _normalize_pairs(self, pairs):
        result = []
        seen = set()
        for raw in pairs or []:
            symbol = self._normalize_pair(raw)
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            result.append(symbol)
        return result

    def _persist_spread_selection(self, index):
        column = self._column(index)
        if column is None:
            return
        self.settings_manager.save_spread_column_selection(
            index=index,
            exchange_name=column.selected_exchange or "",
            pair_symbol=column.selected_pair or "",
        )

    def _restore_spread_selection(self):
        for column in self._iter_columns():
            exchange_name, pair_symbol = self.settings_manager.load_spread_column_selection(column.index)
            normalized_exchange = str(exchange_name or "").strip()
            normalized_pair = self._normalize_pair(pair_symbol)

            if normalized_exchange:
                self._set_selected_exchange(column.index, normalized_exchange)
            else:
                self._set_selected_exchange(column.index, None)

            if normalized_exchange and normalized_pair:
                self._set_selected_pair(column.index, normalized_pair)
                if column.pair_edit is not None:
                    column.pair_edit.blockSignals(True)
                    column.pair_edit.setText(normalized_pair)
                    column.pair_edit.blockSignals(False)

    def _calculate_spread_percent(self):
        state = self._calculate_spread_state()
        return state.get("percent")

    def _calculate_spread_state(self):
        left = self._column(1)
        right = self._column(2)
        if left is None or right is None:
            return {"percent": None, "cheap_index": None, "expensive_index": None}

        if not left.selected_exchange or not right.selected_exchange:
            return {"percent": None, "cheap_index": None, "expensive_index": None}
        if not left.selected_pair or not right.selected_pair:
            return {"percent": None, "cheap_index": None, "expensive_index": None}

        bid_1 = self._to_float(left.quote_bid)
        ask_1 = self._to_float(left.quote_ask)
        bid_2 = self._to_float(right.quote_bid)
        ask_2 = self._to_float(right.quote_ask)
        if not bid_1 or not ask_1 or not bid_2 or not ask_2:
            return {"percent": None, "cheap_index": None, "expensive_index": None}
        if bid_1 <= 0 or ask_1 <= 0 or bid_2 <= 0 or ask_2 <= 0:
            return {"percent": None, "cheap_index": None, "expensive_index": None}

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

        percent = abs(best_edge) * 100.0
        if percent <= 0:
            cheap_index = None
            expensive_index = None

        return {
            "percent": percent,
            "cheap_index": cheap_index,
            "expensive_index": expensive_index,
        }

    def _apply_exchange_tone(self, index, role):
        column = self._column(index)
        if column is None or column.selector_button is None:
            return

        role_value = str(role or "neutral")
        button = column.selector_button
        if button.property("toneRole") == role_value:
            return
        button.setProperty("toneRole", role_value)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _set_spread_pending_selection(self):
        if not getattr(self, "_spread_armed", False):
            return
        self._spread_armed = False
        self._refresh_spread_display()

    def _on_spread_select_clicked(self):
        state = self._calculate_spread_state()
        if state.get("percent") is None:
            return
        self._spread_armed = True
        self._refresh_spread_display()

    def _set_spread_frame_mode(self, mode):
        frame = getattr(self, "spread_value_frame", None)
        inner = getattr(self, "spread_value_inner", None)
        outer_layout = getattr(self, "spread_outer_layout", None)
        stack = getattr(self, "spread_stack", None)
        if frame is None or inner is None:
            return
        mode_value = str(mode or "spread")
        changed = False
        if frame.property("mode") != mode_value:
            frame.setProperty("mode", mode_value)
            frame.style().unpolish(frame)
            frame.style().polish(frame)
            frame.update()
            changed = True
        if inner.property("mode") != mode_value:
            inner.setProperty("mode", mode_value)
            inner.style().unpolish(inner)
            inner.style().polish(inner)
            inner.update()
            changed = True

        if outer_layout is not None:
            if mode_value == "spread":
                outer_layout.setContentsMargins(4, 1, 4, 1)
            else:
                outer_layout.setContentsMargins(0, 0, 0, 0)
        if stack is not None:
            if mode_value == "spread":
                stack.setContentsMargins(12, 6, 12, 6)
            else:
                stack.setContentsMargins(2, 2, 2, 2)

        if not changed:
            return

    def _refresh_spread_display(self):
        label = getattr(self, "spread_value_label", None)
        stack = getattr(self, "spread_stack", None)
        select_btn = getattr(self, "spread_select_btn", None)
        if label is None or stack is None or select_btn is None:
            return

        state = self._calculate_spread_state()
        spread_value = state.get("percent")
        cheap_index = state.get("cheap_index")
        expensive_index = state.get("expensive_index")

        if not self._spread_armed:
            self._set_spread_frame_mode("select")
            stack.setCurrentWidget(select_btn)
            select_btn.setEnabled(spread_value is not None)
            self._apply_exchange_tone(1, "neutral")
            self._apply_exchange_tone(2, "neutral")
            return

        self._set_spread_frame_mode("spread")
        stack.setCurrentWidget(label)

        self._apply_exchange_tone(1, "neutral")
        self._apply_exchange_tone(2, "neutral")
        if cheap_index in {1, 2}:
            self._apply_exchange_tone(cheap_index, "cheap")
        if expensive_index in {1, 2}:
            self._apply_exchange_tone(expensive_index, "expensive")

        is_empty = spread_value is None
        if is_empty:
            label.setText(tr("spread.center_empty"))
        else:
            label.setText(tr("spread.center_value", value=f"{spread_value:.2f}"))

        if label.property("empty") != is_empty:
            label.setProperty("empty", is_empty)
            label.style().unpolish(label)
            label.style().polish(label)
        label.update()

    @staticmethod
    def _rgba(hex_color, alpha):
        color = str(hex_color or "").strip()
        if color.startswith("#") and len(color) == 7:
            try:
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                a = max(0.0, min(1.0, float(alpha)))
                return f"rgba({r}, {g}, {b}, {a:.3f})"
            except ValueError:
                return color
        return color
