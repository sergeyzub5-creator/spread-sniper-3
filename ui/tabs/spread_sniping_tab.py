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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.container = QFrame()

        card_layout = QVBoxLayout(self.container)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        self.title_label = QLabel()
        self.title_label.setObjectName("title")

        selectors_row = self._build_dual_row(self._create_selector_button)
        pairs_row = self._build_dual_row(self._create_pair_input)
        spread_value_row = self._build_center_row(self._create_spread_value_widget())
        quotes_row = self._build_dual_row(self._create_quote_widget)

        self.info_label = QLabel()
        self.info_label.setObjectName("subtitle")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        card_layout.addWidget(self.title_label)
        card_layout.addLayout(selectors_row)
        card_layout.addLayout(spread_value_row)
        card_layout.addLayout(pairs_row)
        card_layout.addLayout(quotes_row)
        card_layout.addWidget(self.info_label)
        card_layout.addStretch()

        layout.addWidget(self.container)
        layout.addStretch()

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

    @staticmethod
    def _build_center_row(center_widget):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch()
        row.addWidget(center_widget, 0, Qt.AlignmentFlag.AlignCenter)
        row.addStretch()
        return row

    def _create_selector_button(self, column):
        btn = QPushButton()
        btn.setObjectName("exchangeSelector")
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
        frame.setFixedHeight(self.SPREAD_VALUE_HEIGHT)
        frame.setMinimumWidth(self.SPREAD_VALUE_WIDTH)

        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 6, 14, 6)
        row.setSpacing(0)

        self.spread_value_label = QLabel()
        self.spread_value_label.setObjectName("spreadValueLabel")
        self.spread_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.spread_value_label)
        return frame

    def _create_quote_widget(self, column):
        frame = QFrame()
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
        bid_qty_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
        ask_qty_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
        c_border = theme_color("border")
        c_primary = theme_color("text_primary")
        c_muted = theme_color("text_muted")
        c_alt = theme_color("surface_alt")
        c_accent = theme_color("accent")
        c_capsule_border = self._rgba(c_accent, 0.52)
        c_capsule_glow = self._rgba(c_accent, 0.18)
        c_capsule_mid = self._rgba(c_alt, 0.95)
        c_capsule_hover = self._rgba(c_accent, 0.24)

        self.container.setStyleSheet(
            f"""
            QFrame {{
                background-color: {c_surface};
                border: 1px solid {c_border};
                border-radius: 6px;
            }}
            QLabel#title {{
                color: {c_primary};
                font-size: 16px;
                font-weight: bold;
            }}
            QLabel#subtitle {{
                color: {c_muted};
                font-size: 13px;
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
            QLineEdit#pairSelector:focus {{
                border-color: {c_accent};
            }}
            QLineEdit#pairSelector:disabled {{
                color: {c_muted};
                border-color: {c_border};
                background-color: {c_surface};
            }}
            QFrame#quotePanel {{
                background-color: {c_alt};
                border: 1px solid {c_border};
                border-radius: 10px;
            }}
            QFrame#quoteSideCapsule {{
                background-color: {c_surface};
                border: 1px solid {c_border};
                border-radius: 8px;
            }}
            QFrame#quoteMidDivider {{
                background-color: {c_border};
                border: none;
                min-height: 18px;
                max-height: 18px;
            }}
            QFrame#spreadValueFrame {{
                background-color: {c_alt};
                border: 1px solid {c_capsule_border};
                border-radius: 16px;
            }}
            QLabel#spreadValueLabel {{
                color: {c_accent};
                font-size: 34px;
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
            }}
            QLabel#askPriceText {{
                color: {theme_color('danger')};
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#quoteQtyText {{
                color: {c_primary};
                font-size: 11px;
                font-weight: 700;
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
            QListView#pairPopup::item:selected {{
                background-color: {theme_color('selection_bg_soft')};
                color: {c_accent};
            }}
        """

        for column in self._iter_columns():
            if column.pair_completer is not None:
                popup = column.pair_completer.popup()
                popup.setObjectName("pairPopup")
                popup.setStyleSheet(popup_style)

    def retranslate_ui(self):
        self.title_label.setText(tr("spread.title"))
        self.info_label.setText(tr("spread.subtitle"))
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
        left = self._column(1)
        right = self._column(2)
        if left is None or right is None:
            return None

        if not left.selected_exchange or not right.selected_exchange:
            return None
        if not left.selected_pair or not right.selected_pair:
            return None

        bid_1 = self._to_float(left.quote_bid)
        ask_1 = self._to_float(left.quote_ask)
        bid_2 = self._to_float(right.quote_bid)
        ask_2 = self._to_float(right.quote_ask)
        if not bid_1 or not ask_1 or not bid_2 or not ask_2:
            return None
        if bid_1 <= 0 or ask_1 <= 0 or bid_2 <= 0 or ask_2 <= 0:
            return None

        spread_a = abs((bid_1 - ask_2) / ask_2) * 100.0
        spread_b = abs((bid_2 - ask_1) / ask_1) * 100.0
        return max(spread_a, spread_b)

    def _refresh_spread_display(self):
        label = getattr(self, "spread_value_label", None)
        if label is None:
            return

        spread_value = self._calculate_spread_percent()
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
