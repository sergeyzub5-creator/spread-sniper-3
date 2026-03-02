from __future__ import annotations

from difflib import SequenceMatcher
import json
import threading
import time

from PySide6.QtCore import QEvent, QModelIndex, QObject, Signal, QSize, QStringListModel, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
import websocket

from core.exchange.catalog import normalize_exchange_code
from core.i18n import tr
from core.utils.thread_pool import ThreadManager, Worker
from ui.styles import button_style, theme_color
from ui.widgets.exchange_badge import build_exchange_icon


class BinanceBookTickerStream(QObject):
    tick = Signal(dict)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._symbol = ""
        self._testnet = False
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._ws = None

    def start(self, symbol, testnet=False):
        new_symbol = str(symbol or "").strip().upper()
        if not new_symbol:
            self.stop()
            return

        same_target = (
            bool(self._thread and self._thread.is_alive())
            and self._symbol == new_symbol
            and self._testnet == bool(testnet)
        )
        if same_target:
            return

        self.stop()
        self._symbol = new_symbol
        self._testnet = bool(testnet)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        ws_obj = None
        with self._lock:
            ws_obj = self._ws
        try:
            if ws_obj is not None:
                ws_obj.close()
        except Exception:
            pass

        thread = self._thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=1.5)
        self._thread = None

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _emit_safe(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def _ws_base_url(self):
        if self._testnet:
            # Inference from Binance testnet connector examples.
            return "wss://fstream.binancefuture.com"
        return "wss://fstream.binance.com"

    def _run_loop(self):
        url = f"{self._ws_base_url()}/ws/{self._symbol.lower()}@bookTicker"

        while not self._stop_event.is_set():
            ws_app = None
            try:
                ws_app = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                with self._lock:
                    self._ws = ws_app
                ws_app.run_forever(ping_interval=120, ping_timeout=30)
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._emit_safe(self.error, str(exc))
            finally:
                with self._lock:
                    self._ws = None

            if not self._stop_event.is_set():
                time.sleep(0.8)

    def _on_message(self, _ws, message):
        if self._stop_event.is_set():
            return

        try:
            raw = json.loads(message if isinstance(message, str) else message.decode("utf-8"))
        except Exception:
            return

        data = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
        if not isinstance(data, dict):
            return

        bid = self._to_float(data.get("b"))
        ask = self._to_float(data.get("a"))
        bid_qty = self._to_float(data.get("B"))
        ask_qty = self._to_float(data.get("A"))
        symbol = str(data.get("s") or "").upper()
        event_time = data.get("E")

        if not symbol or bid is None or ask is None:
            return

        self._emit_safe(
            self.tick,
            {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "bid_qty": bid_qty,
                "ask_qty": ask_qty,
                "event_time": event_time,
            },
        )

    def _on_error(self, _ws, error):
        if self._stop_event.is_set():
            return
        self._emit_safe(self.error, str(error))

    def _on_close(self, _ws, _code, _msg):
        return


class ConnectedExchangePickerDialog(QDialog):
    def __init__(self, rows, selector_index, current_name=None, parent=None):
        super().__init__(parent)
        self.selected_name = None
        self.reset_requested = False
        self.rows = list(rows or [])
        self.selector_index = selector_index

        self.setWindowTitle(tr("spread.pick_exchange_title"))
        self.setMinimumSize(480, 420)
        self.resize(520, 460)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {theme_color('surface')};
                color: {theme_color('text_primary')};
            }}
            QLabel {{
                color: {theme_color('text_primary')};
                font-size: 14px;
                font-weight: 700;
            }}
            QListWidget {{
                background-color: {theme_color('window_bg')};
                border: 1px solid {theme_color('border')};
                border-radius: 10px;
                padding: 8px;
                color: {theme_color('text_primary')};
                font-size: 13px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-radius: 8px;
                margin: 2px;
            }}
            QListWidget::item:hover {{
                background-color: {theme_color('surface_alt')};
            }}
            QListWidget::item:selected {{
                background-color: {theme_color('selection_bg_soft')};
                color: {theme_color('accent')};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel(tr("spread.pick_exchange_prompt", index=selector_index))
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(28, 28))
        self.list_widget.setSpacing(4)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept_selected())

        current_row_index = -1
        for idx, (name, exchange_type) in enumerate(self.rows):
            item = QListWidgetItem(build_exchange_icon(exchange_type, size=28), name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list_widget.addItem(item)
            if current_name and name == current_name:
                current_row_index = idx

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(current_row_index if current_row_index >= 0 else 0)

        layout.addWidget(self.list_widget)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.select_btn = QPushButton(tr("action.select"))
        self.select_btn.setStyleSheet(button_style("primary", padding="7px 14px", bold=True))
        self.select_btn.setMinimumWidth(120)
        self.select_btn.setEnabled(self.list_widget.currentItem() is not None)
        self.select_btn.clicked.connect(self._accept_selected)
        buttons.addWidget(self.select_btn)

        self.cancel_btn = QPushButton(tr("action.cancel"))
        self.cancel_btn.setStyleSheet(button_style("secondary", padding="7px 14px"))
        self.cancel_btn.setMinimumWidth(120)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)

        self.reset_btn = QPushButton(tr("action.reset"))
        self.reset_btn.setStyleSheet(button_style("warning", padding="7px 14px"))
        self.reset_btn.setMinimumWidth(120)
        self.reset_btn.clicked.connect(self._request_reset)
        self.reset_btn.setVisible(bool(current_name))
        buttons.addWidget(self.reset_btn)

        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        layout.addLayout(buttons)

    def _on_current_item_changed(self, current, _previous):
        self.select_btn.setEnabled(current is not None)

    def _accept_selected(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_name = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _request_reset(self):
        self.selected_name = None
        self.reset_requested = True
        self.accept()


class SpreadSnipingTab(QWidget):
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

    def __init__(self, exchange_manager, parent=None):
        super().__init__(parent)
        self.exchange_manager = exchange_manager

        self.selected_exchange_1 = None
        self.selected_exchange_2 = None
        self.selected_pair_1 = None
        self.selected_pair_2 = None

        self._pair_cache = {}
        self._pair_popular_cache = {}
        self._pair_loading = set()
        self._pair_workers = {}

        self._pair_edits = {}
        self._pair_models = {}
        self._pair_completers = {}
        self._pair_accepting = set()
        self._pair_reedit_mode = set()

        self._quote_frames = {}
        self._quote_bid_labels = {}
        self._quote_ask_labels = {}
        self._quote_snapshot_workers = {}
        self._quote_stream_state = {1: None, 2: None}
        self._quote_values = {
            1: {"state": "empty", "bid": None, "ask": None},
            2: {"state": "empty", "bid": None, "ask": None},
        }
        self._quote_streams = {
            1: BinanceBookTickerStream(self),
            2: BinanceBookTickerStream(self),
        }
        self._quote_streams[1].tick.connect(lambda payload: self._on_quote_tick(1, payload))
        self._quote_streams[2].tick.connect(lambda payload: self._on_quote_tick(2, payload))
        self._quote_streams[1].error.connect(lambda _err: self._on_quote_stream_error(1))
        self._quote_streams[2].error.connect(lambda _err: self._on_quote_stream_error(2))

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._init_ui()
        self.exchange_manager.status_updated.connect(self._on_status_updated)
        self.destroyed.connect(lambda *_args: self._stop_all_quote_streams())

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

        selectors_row = QHBoxLayout()
        selectors_row.setContentsMargins(0, 0, 0, 0)
        selectors_row.setSpacing(0)

        left_half = QWidget()
        left_half_layout = QHBoxLayout(left_half)
        left_half_layout.setContentsMargins(0, 0, 8, 0)
        left_half_layout.setSpacing(0)
        left_half_layout.addStretch()

        self.exchange_1_btn = QPushButton()
        self.exchange_1_btn.setObjectName("exchangeSelector")
        self.exchange_1_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exchange_1_btn.setFixedWidth(250)
        self.exchange_1_btn.clicked.connect(lambda: self._open_exchange_menu(1))
        left_half_layout.addWidget(self.exchange_1_btn, 0)
        left_half_layout.addStretch()

        right_half = QWidget()
        right_half_layout = QHBoxLayout(right_half)
        right_half_layout.setContentsMargins(8, 0, 0, 0)
        right_half_layout.setSpacing(0)
        right_half_layout.addStretch()

        self.exchange_2_btn = QPushButton()
        self.exchange_2_btn.setObjectName("exchangeSelector")
        self.exchange_2_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exchange_2_btn.setFixedWidth(250)
        self.exchange_2_btn.clicked.connect(lambda: self._open_exchange_menu(2))
        right_half_layout.addWidget(self.exchange_2_btn, 0)
        right_half_layout.addStretch()

        selectors_row.addWidget(left_half, 1)
        selectors_row.addWidget(right_half, 1)

        pairs_row = QHBoxLayout()
        pairs_row.setContentsMargins(0, 0, 0, 0)
        pairs_row.setSpacing(0)

        left_pair_half = QWidget()
        left_pair_layout = QHBoxLayout(left_pair_half)
        left_pair_layout.setContentsMargins(0, 0, 8, 0)
        left_pair_layout.setSpacing(0)
        left_pair_layout.addStretch()

        self.exchange_1_pair = self._create_pair_input(1)
        left_pair_layout.addWidget(self.exchange_1_pair, 0)
        left_pair_layout.addStretch()

        right_pair_half = QWidget()
        right_pair_layout = QHBoxLayout(right_pair_half)
        right_pair_layout.setContentsMargins(8, 0, 0, 0)
        right_pair_layout.setSpacing(0)
        right_pair_layout.addStretch()

        self.exchange_2_pair = self._create_pair_input(2)
        right_pair_layout.addWidget(self.exchange_2_pair, 0)
        right_pair_layout.addStretch()

        pairs_row.addWidget(left_pair_half, 1)
        pairs_row.addWidget(right_pair_half, 1)

        quotes_row = QHBoxLayout()
        quotes_row.setContentsMargins(0, 0, 0, 0)
        quotes_row.setSpacing(0)

        left_quote_half = QWidget()
        left_quote_layout = QHBoxLayout(left_quote_half)
        left_quote_layout.setContentsMargins(0, 0, 8, 0)
        left_quote_layout.setSpacing(0)
        left_quote_layout.addStretch()

        self.exchange_1_quote = self._create_quote_widget(1)
        left_quote_layout.addWidget(self.exchange_1_quote, 0)
        left_quote_layout.addStretch()

        right_quote_half = QWidget()
        right_quote_layout = QHBoxLayout(right_quote_half)
        right_quote_layout.setContentsMargins(8, 0, 0, 0)
        right_quote_layout.setSpacing(0)
        right_quote_layout.addStretch()

        self.exchange_2_quote = self._create_quote_widget(2)
        right_quote_layout.addWidget(self.exchange_2_quote, 0)
        right_quote_layout.addStretch()

        quotes_row.addWidget(left_quote_half, 1)
        quotes_row.addWidget(right_quote_half, 1)

        self.info_label = QLabel()
        self.info_label.setObjectName("subtitle")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        card_layout.addWidget(self.title_label)
        card_layout.addLayout(selectors_row)
        card_layout.addLayout(pairs_row)
        card_layout.addLayout(quotes_row)
        card_layout.addWidget(self.info_label)
        card_layout.addStretch()

        layout.addWidget(self.container)
        layout.addStretch()

        self.apply_theme()
        self.retranslate_ui()
        self._refresh_selector_state()

    def _create_pair_input(self, index):
        edit = QLineEdit()
        edit.setObjectName("pairSelector")
        edit.setFixedWidth(250)
        edit.setVisible(False)
        edit.setEnabled(False)
        edit.setClearButtonEnabled(False)
        edit.installEventFilter(self)

        model = QStringListModel(self)
        completer = QCompleter(model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.setMaxVisibleItems(12)
        completer.activated.connect(lambda value, idx=index: self._on_pair_completer_activated(idx, value))
        edit.setCompleter(completer)

        edit.textEdited.connect(lambda text, idx=index: self._on_pair_text_edited(idx, text))
        edit.editingFinished.connect(lambda idx=index: self._on_pair_editing_finished(idx))

        self._pair_edits[index] = edit
        self._pair_models[index] = model
        self._pair_completers[index] = completer
        return edit

    def _create_quote_widget(self, index):
        frame = QFrame()
        frame.setObjectName("quotePanel")
        frame.setFixedWidth(250)
        frame.setVisible(False)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        bid_label = QLabel()
        bid_label.setObjectName("bidQuote")
        bid_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bid_label.setText(tr("spread.best_bid_empty"))

        ask_label = QLabel()
        ask_label.setObjectName("askQuote")
        ask_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ask_label.setText(tr("spread.best_ask_empty"))

        layout.addWidget(bid_label, 1)
        layout.addWidget(ask_label, 1)

        self._quote_frames[index] = frame
        self._quote_bid_labels[index] = bid_label
        self._quote_ask_labels[index] = ask_label
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
            QLabel#bidQuote {{
                color: {theme_color('success')};
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#askQuote {{
                color: {theme_color('danger')};
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
        for completer in self._pair_completers.values():
            popup = completer.popup()
            popup.setObjectName("pairPopup")
            popup.setStyleSheet(popup_style)

    def retranslate_ui(self):
        self.title_label.setText(tr("spread.title"))
        self.info_label.setText(tr("spread.subtitle"))
        self._update_selector_texts()
        self._refresh_pair_controls()
        self._refresh_all_quote_labels()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            click_index = None
            for index, edit in self._pair_edits.items():
                if watched is edit:
                    click_index = index
                    break

            if click_index is not None:
                self._on_pair_field_clicked(click_index)
            else:
                global_pos = self._extract_global_pos(event)
                if global_pos is not None and not self._is_pair_area_click(global_pos):
                    self._hide_all_pair_popups()
        return super().eventFilter(watched, event)

    def _on_status_updated(self, _statuses):
        self._refresh_selector_state()
        self._sync_quote_stream(1)
        self._sync_quote_stream(2)

    def _connected_names(self):
        return sorted(self.exchange_manager.get_connected_names(), key=lambda v: v.lower())

    def _connected_rows(self):
        rows = []
        for name in self._connected_names():
            exchange = self.exchange_manager.get_exchange(name)
            if exchange is None:
                continue
            exchange_type = normalize_exchange_code(getattr(exchange, "exchange_type", None))
            rows.append((name, exchange_type))
        return rows

    def _exchange_type_for_name(self, name):
        if not name:
            return None
        exchange = self.exchange_manager.get_exchange(name)
        if exchange is None:
            return None
        return normalize_exchange_code(getattr(exchange, "exchange_type", None))

    def _get_selected_exchange(self, index):
        return self.selected_exchange_1 if index == 1 else self.selected_exchange_2

    def _set_selected_exchange(self, index, name):
        new_name = str(name).strip() if name else None
        old_name = self._get_selected_exchange(index)
        if index == 1:
            self.selected_exchange_1 = new_name
        else:
            self.selected_exchange_2 = new_name

        if old_name != new_name:
            self._clear_selected_pair(index)

        self._update_selector_texts()
        self._refresh_pair_control(index)
        self._sync_quote_stream(index)

        if new_name:
            self._ensure_pairs_loaded(new_name)

    def _clear_selected_pair(self, index):
        if index == 1:
            self.selected_pair_1 = None
        else:
            self.selected_pair_2 = None

        edit = self._pair_edits.get(index)
        if edit is not None:
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)
        self._pair_reedit_mode.discard(index)
        self._update_pair_input_mode(index)
        self._sync_quote_stream(index)

    def _set_selected_pair(self, index, pair):
        value = self._normalize_pair(pair)
        if index == 1:
            self.selected_pair_1 = value
        else:
            self.selected_pair_2 = value
        self._update_pair_input_mode(index)
        self._sync_quote_stream(index)

    def _get_selected_pair(self, index):
        return self.selected_pair_1 if index == 1 else self.selected_pair_2

    def _refresh_selector_state(self):
        has_connected = bool(self._connected_rows())
        self.exchange_1_btn.setEnabled(has_connected)
        self.exchange_2_btn.setEnabled(has_connected)

        if self.selected_exchange_1 and self.exchange_manager.get_exchange(self.selected_exchange_1) is None:
            self._set_selected_exchange(1, None)
        if self.selected_exchange_2 and self.exchange_manager.get_exchange(self.selected_exchange_2) is None:
            self._set_selected_exchange(2, None)

        self._update_selector_texts()
        self._refresh_pair_controls()

    def _selector_text(self, index):
        if index == 1:
            selected = self.selected_exchange_1
            key = "spread.exchange_1_selected" if selected else "spread.exchange_1_default"
        else:
            selected = self.selected_exchange_2
            key = "spread.exchange_2_selected" if selected else "spread.exchange_2_default"
        return tr(key, name=selected) if selected else tr(key)

    def _update_selector_texts(self):
        self.exchange_1_btn.setText(self._selector_text(1))
        self.exchange_2_btn.setText(self._selector_text(2))

        type_1 = self._exchange_type_for_name(self.selected_exchange_1)
        type_2 = self._exchange_type_for_name(self.selected_exchange_2)

        if type_1:
            self.exchange_1_btn.setIcon(build_exchange_icon(type_1, size=24))
        else:
            self.exchange_1_btn.setIcon(QIcon())
        self.exchange_1_btn.setIconSize(QSize(24, 24))

        if type_2:
            self.exchange_2_btn.setIcon(build_exchange_icon(type_2, size=24))
        else:
            self.exchange_2_btn.setIcon(QIcon())
        self.exchange_2_btn.setIconSize(QSize(24, 24))

    def _open_exchange_menu(self, index):
        rows = self._connected_rows()
        if not rows:
            return

        current = self._get_selected_exchange(index)
        dialog = ConnectedExchangePickerDialog(rows, selector_index=index, current_name=current, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if dialog.reset_requested:
            self._set_selected_exchange(index, None)
            return

        chosen_name = dialog.selected_name
        if not chosen_name:
            return

        self._set_selected_exchange(index, chosen_name)

    def _refresh_pair_controls(self):
        self._refresh_pair_control(1)
        self._refresh_pair_control(2)

    def _refresh_pair_control(self, index):
        edit = self._pair_edits[index]
        exchange_name = self._get_selected_exchange(index)

        if not exchange_name:
            edit.setVisible(False)
            edit.setEnabled(False)
            edit.setPlaceholderText(tr("spread.pair_placeholder"))
            self._update_completer_items(index, [])
            self._pair_reedit_mode.discard(index)
            self._update_pair_input_mode(index)
            self._sync_quote_stream(index)
            return

        edit.setVisible(True)

        if exchange_name in self._pair_loading:
            edit.setEnabled(False)
            edit.setPlaceholderText(tr("spread.pairs_loading"))
            self._pair_reedit_mode.discard(index)
            self._update_pair_input_mode(index)
            self._sync_quote_stream(index)
            return

        pairs = self._pair_cache.get(exchange_name)
        if pairs is None:
            self._ensure_pairs_loaded(exchange_name)
            if exchange_name in self._pair_loading:
                edit.setEnabled(False)
                edit.setPlaceholderText(tr("spread.pairs_loading"))
                return
            pairs = self._pair_cache.get(exchange_name, [])

        if pairs:
            edit.setEnabled(True)
            edit.setPlaceholderText(tr("spread.pair_placeholder"))
            selected_pair = self._get_selected_pair(index)
            if selected_pair and self._normalize_pair(edit.text()) != selected_pair:
                edit.blockSignals(True)
                edit.setText(selected_pair)
                edit.blockSignals(False)
            if not edit.text().strip():
                self._update_completer_items(index, self._popular_for_exchange(exchange_name))
            self._update_pair_input_mode(index)
            self._sync_quote_stream(index)
        else:
            edit.setEnabled(False)
            edit.setPlaceholderText(tr("spread.pairs_empty"))
            self._update_completer_items(index, [])
            self._pair_reedit_mode.discard(index)
            self._update_pair_input_mode(index)
            self._sync_quote_stream(index)

    def _ensure_pairs_loaded(self, exchange_name):
        if not exchange_name:
            return
        if exchange_name in self._pair_cache:
            return
        if exchange_name in self._pair_loading:
            return

        self._pair_loading.add(exchange_name)
        self._refresh_pair_controls()

        worker = Worker(self._load_pairs_task, exchange_name)
        self._pair_workers[exchange_name] = worker
        worker.signals.result.connect(
            lambda pairs, name=exchange_name: self._on_pairs_loaded(name, pairs)
        )
        worker.signals.error.connect(
            lambda _error, name=exchange_name: self._on_pairs_error(name)
        )
        worker.signals.finished.connect(
            lambda name=exchange_name: self._on_pairs_finished(name)
        )
        ThreadManager().start(worker)

    def _load_pairs_task(self, exchange_name):
        exchange = self.exchange_manager.get_exchange(exchange_name)
        if exchange is None:
            return {"pairs": [], "strict": False}

        exchange_type = normalize_exchange_code(getattr(exchange, "exchange_type", None))
        if exchange_type == "binance":
            pairs = self._load_binance_account_pairs(exchange)
            return {"pairs": pairs, "strict": True}

        getter = getattr(exchange, "get_trading_pairs", None)
        if callable(getter):
            try:
                pairs = getter(limit=1200)
            except Exception:
                pairs = []
        else:
            pairs = []

        normalized = self._normalize_pairs(pairs)
        if normalized:
            return normalized

        fallback = []
        for pos in exchange.positions or []:
            symbol = self._normalize_pair(pos.get("symbol"))
            if symbol and symbol not in fallback:
                fallback.append(symbol)
        for symbol in self.POPULAR_PAIRS:
            if symbol not in fallback:
                fallback.append(symbol)
        return {"pairs": fallback, "strict": False}

    def _load_binance_account_pairs(self, exchange):
        request = getattr(exchange, "_request", None)
        if not callable(request):
            return []

        account = request("GET", "/fapi/v2/account", signed=True)
        if not isinstance(account, dict):
            return []
        if account.get("canTrade") is False:
            return []

        exchange_info = request("GET", "/fapi/v1/exchangeInfo", signed=False)
        if not isinstance(exchange_info, dict):
            return []

        allowed_symbols = None
        brackets = request("GET", "/fapi/v1/leverageBracket", signed=True)
        if isinstance(brackets, list):
            allowed = set()
            for item in brackets:
                symbol = self._normalize_pair(item.get("symbol"))
                if symbol:
                    allowed.add(symbol)
            if allowed:
                allowed_symbols = allowed

        pairs = []
        seen = set()
        for row in exchange_info.get("symbols") or []:
            status = str(row.get("status", "")).upper()
            if status and status != "TRADING":
                continue

            symbol = self._normalize_pair(row.get("symbol"))
            if not symbol or symbol in seen:
                continue

            if allowed_symbols is not None and symbol not in allowed_symbols:
                continue

            seen.add(symbol)
            pairs.append(symbol)

        return pairs

    def _on_pairs_loaded(self, exchange_name, payload):
        strict = False
        pairs = payload
        if isinstance(payload, dict):
            strict = bool(payload.get("strict", False))
            pairs = payload.get("pairs", [])

        normalized = self._normalize_pairs(pairs)
        if not normalized and not strict:
            normalized = list(self.POPULAR_PAIRS)

        self._pair_cache[exchange_name] = normalized
        if normalized:
            self._pair_popular_cache[exchange_name] = self._build_popular_list(normalized)
        else:
            self._pair_popular_cache[exchange_name] = []

        for index in (1, 2):
            if self._get_selected_exchange(index) != exchange_name:
                continue

            selected_pair = self._get_selected_pair(index)
            if selected_pair and selected_pair not in normalized:
                self._clear_selected_pair(index)

    def _on_pairs_error(self, exchange_name):
        exchange = self.exchange_manager.get_exchange(exchange_name)
        exchange_type = normalize_exchange_code(getattr(exchange, "exchange_type", None))
        if exchange_type == "binance":
            self._pair_cache[exchange_name] = []
            self._pair_popular_cache[exchange_name] = []
        else:
            self._pair_cache[exchange_name] = list(self.POPULAR_PAIRS)
            self._pair_popular_cache[exchange_name] = self._build_popular_list(self.POPULAR_PAIRS)

    def _on_pairs_finished(self, exchange_name):
        self._pair_loading.discard(exchange_name)
        self._pair_workers.pop(exchange_name, None)
        self._refresh_pair_controls()

    def _pairs_for_index(self, index):
        exchange_name = self._get_selected_exchange(index)
        if not exchange_name:
            return []
        return list(self._pair_cache.get(exchange_name) or [])

    def _popular_for_exchange(self, exchange_name):
        if not exchange_name:
            return []
        popular = self._pair_popular_cache.get(exchange_name)
        if popular is None:
            pairs = self._pair_cache.get(exchange_name) or []
            popular = self._build_popular_list(pairs)
            self._pair_popular_cache[exchange_name] = popular
        return list(popular)

    def _build_popular_list(self, pairs):
        normalized_pairs = self._normalize_pairs(pairs)
        if not normalized_pairs:
            return list(self.POPULAR_PAIRS)

        pair_set = set(normalized_pairs)
        popular = []
        for pair in self.POPULAR_PAIRS:
            if pair in pair_set:
                popular.append(pair)

        for pair in normalized_pairs:
            if pair not in popular:
                popular.append(pair)
            if len(popular) >= self.POPULAR_SUGGESTIONS:
                break

        return popular[: self.POPULAR_SUGGESTIONS]

    def _on_pair_text_edited(self, index, text):
        exchange_name = self._get_selected_exchange(index)
        if not exchange_name:
            return
        if exchange_name in self._pair_loading:
            return

        query = self._normalize_pair(text)
        selected = self._get_selected_pair(index)
        if query != selected:
            self._set_selected_pair(index, None)

        suggestions = self._build_suggestions(index, query)
        self._update_completer_items(index, suggestions)
        if suggestions:
            self._pair_completers[index].complete()

    def _on_pair_editing_finished(self, index):
        if index in self._pair_accepting:
            self._pair_reedit_mode.discard(index)
            self._update_pair_input_mode(index)
            return

        edit = self._pair_edits[index]
        text = self._normalize_pair(edit.text())
        if not text:
            self._set_selected_pair(index, None)
            self._pair_reedit_mode.discard(index)
            self._update_pair_input_mode(index)
            return

        pairs = self._pairs_for_index(index)
        if text in pairs:
            self._set_selected_pair(index, text)
            edit.blockSignals(True)
            edit.setText(text)
            edit.blockSignals(False)
        else:
            suggestions = self._build_suggestions(index, text)
            if suggestions:
                best = suggestions[0]
                edit.blockSignals(True)
                edit.setText(best)
                edit.blockSignals(False)
                self._set_selected_pair(index, best)
            else:
                self._set_selected_pair(index, None)

        self._pair_reedit_mode.discard(index)
        self._update_pair_input_mode(index)

    def _on_pair_completer_activated(self, index, value):
        if isinstance(value, QModelIndex):
            pair_text = value.data(Qt.ItemDataRole.DisplayRole)
        else:
            pair_text = str(value)
        self._on_pair_chosen(index, pair_text)

    def _on_pair_chosen(self, index, value):
        pair = self._normalize_pair(value)
        if not pair:
            return

        self._pair_accepting.add(index)
        edit = self._pair_edits[index]
        edit.blockSignals(True)
        edit.setText(pair)
        edit.blockSignals(False)
        self._set_selected_pair(index, pair)
        self._pair_reedit_mode.discard(index)
        self._update_pair_input_mode(index)
        self._hide_all_pair_popups()
        edit.clearFocus()
        QTimer.singleShot(0, lambda idx=index: self._pair_accepting.discard(idx))

    def _show_pair_popup(self, index, force_popular=False):
        exchange_name = self._get_selected_exchange(index)
        if not exchange_name:
            return

        if exchange_name in self._pair_loading:
            return

        pairs = self._pairs_for_index(index)
        if not pairs:
            self._ensure_pairs_loaded(exchange_name)
            return

        edit = self._pair_edits[index]
        if not edit.isEnabled():
            return

        query = "" if force_popular else self._normalize_pair(edit.text())
        suggestions = self._build_suggestions(index, query)
        if not suggestions:
            return

        self._update_completer_items(index, suggestions)
        self._pair_completers[index].complete()

    def _on_pair_field_clicked(self, index):
        edit = self._pair_edits.get(index)
        if edit is None or not edit.isEnabled():
            return

        if self._get_selected_pair(index):
            self._pair_reedit_mode.add(index)
            self._update_pair_input_mode(index)
            edit.setFocus(Qt.FocusReason.MouseFocusReason)
            edit.selectAll()
        else:
            self._pair_reedit_mode.discard(index)
            self._update_pair_input_mode(index)

        QTimer.singleShot(0, lambda idx=index: self._show_pair_popup(idx, force_popular=True))

    def _update_pair_input_mode(self, index):
        edit = self._pair_edits.get(index)
        if edit is None:
            return
        if not edit.isVisible() or not edit.isEnabled():
            edit.setReadOnly(True)
            edit.setClearButtonEnabled(False)
            return

        has_selected = bool(self._get_selected_pair(index))
        in_reedit = index in self._pair_reedit_mode

        if has_selected and not in_reedit:
            edit.setReadOnly(True)
            edit.setClearButtonEnabled(False)
            return

        edit.setReadOnly(False)
        edit.setClearButtonEnabled(has_selected and in_reedit)

    def _refresh_all_quote_labels(self):
        for index in (1, 2):
            self._apply_quote_text_state(index)

    def _apply_quote_text_state(self, index):
        quote = self._quote_values.get(index, {})
        state = quote.get("state", "empty")
        bid_label = self._quote_bid_labels.get(index)
        ask_label = self._quote_ask_labels.get(index)
        if bid_label is None or ask_label is None:
            return

        if state == "live":
            bid_label.setText(tr("spread.best_bid", value=self._format_price(quote.get("bid"))))
            ask_label.setText(tr("spread.best_ask", value=self._format_price(quote.get("ask"))))
            return

        if state == "loading":
            bid_label.setText(tr("spread.best_bid_loading"))
            ask_label.setText(tr("spread.best_ask_loading"))
            return

        bid_label.setText(tr("spread.best_bid_empty"))
        ask_label.setText(tr("spread.best_ask_empty"))

    def _set_quote_state(self, index, state, bid=None, ask=None):
        self._quote_values[index] = {"state": state, "bid": bid, "ask": ask}
        self._apply_quote_text_state(index)

    def _show_quote_widget(self, index, visible):
        frame = self._quote_frames.get(index)
        if frame is not None:
            frame.setVisible(bool(visible))

    def _stop_all_quote_streams(self):
        for index in (1, 2):
            self._stop_quote_stream(index)

    def _stop_quote_stream(self, index):
        worker = self._quote_snapshot_workers.pop(index, None)
        if worker is not None:
            try:
                worker.signals.result.disconnect()
                worker.signals.finished.disconnect()
            except Exception:
                pass

        stream = self._quote_streams.get(index)
        if stream is not None:
            stream.stop()
        self._quote_stream_state[index] = None

    def _sync_quote_stream(self, index):
        exchange_name = self._get_selected_exchange(index)
        pair = self._get_selected_pair(index)

        if not exchange_name or not pair:
            self._stop_quote_stream(index)
            self._set_quote_state(index, "empty")
            self._show_quote_widget(index, False)
            return

        self._show_quote_widget(index, True)
        exchange = self.exchange_manager.get_exchange(exchange_name)
        if exchange is None:
            self._stop_quote_stream(index)
            self._set_quote_state(index, "empty")
            return

        exchange_type = normalize_exchange_code(getattr(exchange, "exchange_type", None))
        if exchange_type != "binance" or not exchange.is_connected:
            self._stop_quote_stream(index)
            self._set_quote_state(index, "empty")
            return

        desired_state = (exchange_name, pair, bool(getattr(exchange, "testnet", False)))
        if self._quote_stream_state.get(index) == desired_state:
            return

        self._stop_quote_stream(index)
        self._quote_stream_state[index] = desired_state
        self._set_quote_state(index, "loading")
        self._start_quote_snapshot(index, exchange_name, pair)
        self._quote_streams[index].start(pair, testnet=bool(getattr(exchange, "testnet", False)))

    def _start_quote_snapshot(self, index, exchange_name, pair):
        worker = Worker(self._fetch_binance_book_ticker_snapshot_task, exchange_name, pair)
        self._quote_snapshot_workers[index] = worker
        worker.signals.result.connect(
            lambda result, idx=index, name=exchange_name, sym=pair: self._on_quote_snapshot_result(
                idx, name, sym, result
            )
        )
        worker.signals.finished.connect(lambda idx=index: self._quote_snapshot_workers.pop(idx, None))
        ThreadManager().start(worker)

    def _fetch_binance_book_ticker_snapshot_task(self, exchange_name, pair):
        exchange = self.exchange_manager.get_exchange(exchange_name)
        if exchange is None:
            return None

        request = getattr(exchange, "_request", None)
        if not callable(request):
            return None

        payload = request("GET", "/fapi/v1/ticker/bookTicker", signed=False, params={"symbol": pair})
        if not isinstance(payload, dict):
            return None

        bid = self._to_float(payload.get("bidPrice"))
        ask = self._to_float(payload.get("askPrice"))
        if bid is None or ask is None:
            return None

        return {"symbol": self._normalize_pair(payload.get("symbol") or pair), "bid": bid, "ask": ask}

    def _on_quote_snapshot_result(self, index, exchange_name, pair, result):
        current = self._quote_stream_state.get(index)
        if current is None:
            return
        if current[0] != exchange_name or current[1] != pair:
            return
        if not isinstance(result, dict):
            return

        bid = self._to_float(result.get("bid"))
        ask = self._to_float(result.get("ask"))
        if bid is None or ask is None:
            return
        self._set_quote_state(index, "live", bid=bid, ask=ask)

    def _on_quote_tick(self, index, payload):
        if not isinstance(payload, dict):
            return

        current = self._quote_stream_state.get(index)
        if current is None:
            return

        selected_exchange = self._get_selected_exchange(index)
        selected_pair = self._get_selected_pair(index)
        if not selected_exchange or not selected_pair:
            return
        if current[0] != selected_exchange or current[1] != selected_pair:
            return

        symbol = self._normalize_pair(payload.get("symbol"))
        if symbol and symbol != selected_pair:
            return

        bid = self._to_float(payload.get("bid"))
        ask = self._to_float(payload.get("ask"))
        if bid is None or ask is None:
            return

        self._set_quote_state(index, "live", bid=bid, ask=ask)

    def _on_quote_stream_error(self, index):
        if self._quote_stream_state.get(index) is None:
            return
        if self._quote_values.get(index, {}).get("state") != "live":
            self._set_quote_state(index, "loading")

    def _hide_all_pair_popups(self):
        for completer in self._pair_completers.values():
            popup = completer.popup()
            if popup is not None:
                popup.hide()

    def _extract_global_pos(self, event):
        if hasattr(event, "globalPosition"):
            try:
                return event.globalPosition().toPoint()
            except Exception:
                return None
        if hasattr(event, "globalPos"):
            try:
                return event.globalPos()
            except Exception:
                return None
        return None

    def _contains_global_point(self, widget, global_pos):
        if widget is None or not widget.isVisible():
            return False
        top_left = widget.mapToGlobal(widget.rect().topLeft())
        local = global_pos - top_left
        return widget.rect().contains(local)

    def _is_pair_area_click(self, global_pos):
        for edit in self._pair_edits.values():
            if self._contains_global_point(edit, global_pos):
                return True
        for completer in self._pair_completers.values():
            popup = completer.popup()
            if self._contains_global_point(popup, global_pos):
                return True
        return False

    def _build_suggestions(self, index, query):
        pairs = self._pairs_for_index(index)
        if not pairs:
            return []

        q = self._normalize_pair(query)
        if not q:
            exchange_name = self._get_selected_exchange(index)
            return self._popular_for_exchange(exchange_name)

        scored = []
        for pair in pairs:
            if pair == q:
                scored.append(((0, 0, 0.0, pair), pair))
                continue

            if pair.startswith(q):
                score = (1, len(pair) - len(q), 0.0, pair)
                scored.append((score, pair))
                continue

            pos = pair.find(q)
            if pos >= 0:
                score = (2, pos, float(len(pair)), pair)
                scored.append((score, pair))
                continue

            ratio = SequenceMatcher(None, q, pair).ratio()
            if ratio < 0.20:
                continue
            score = (3, 0, 1.0 - ratio, pair)
            scored.append((score, pair))

        scored.sort(key=lambda item: item[0])
        return [pair for _score, pair in scored[: self.MAX_SUGGESTIONS]]

    def _update_completer_items(self, index, items):
        model = self._pair_models[index]
        model.setStringList(self._normalize_pairs(items))

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
