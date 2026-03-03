from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon

from core.exchange.catalog import normalize_exchange_code
from core.i18n import tr
from features.spread_sniping.dialogs.connected_exchange_picker_dialog import (
    ConnectedExchangePickerDialog,
)
from ui.widgets.exchange_badge import build_exchange_icon


class SpreadSelectionStateMixin:
    def _trace_selection(self, event, **fields):
        trace = getattr(self, "_trace", None)
        if callable(trace):
            trace(f"selection.{event}", **fields)

    def _set_spread_pending_selection_safe(self):
        setter = getattr(self, "_set_spread_pending_selection", None)
        if callable(setter):
            setter()

    def _persist_spread_selection_safe(self, index):
        persist = getattr(self, "_persist_spread_selection", None)
        if callable(persist):
            persist(index)

    def _refresh_spread_display_safe(self):
        refresh = getattr(self, "_refresh_spread_display", None)
        if callable(refresh):
            refresh()

    def _refresh_trade_controls_safe(self):
        refresh = getattr(self, "_refresh_trade_controls", None)
        if callable(refresh):
            refresh()

    def _refresh_trade_control_safe(self, index):
        refresh = getattr(self, "_refresh_trade_control", None)
        if callable(refresh):
            refresh(index)

    def _on_status_updated(self, _statuses):
        self._refresh_selector_state()
        for column in self._iter_columns():
            self._sync_quote_stream(column.index)
        self._refresh_spread_display_safe()
        self._refresh_trade_controls_safe()

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
        column = self._column(index)
        return column.selected_exchange if column else None

    def _set_selected_exchange(self, index, name, force_reload=False):
        column = self._column(index)
        if column is None:
            return

        new_name = str(name).strip() if name else None
        old_name = column.selected_exchange
        column.selected_exchange = new_name
        self._trace_selection(
            "set_exchange",
            index=index,
            old=old_name or "",
            new=new_name or "",
            force_reload=bool(force_reload),
        )

        if old_name != new_name:
            self._clear_selected_pair(index)

        self._update_selector_texts()
        self._refresh_pair_control(index)
        self._sync_quote_stream(index)
        self._refresh_spread_display_safe()
        self._refresh_trade_control_safe(index)
        self._persist_spread_selection_safe(index)

        if not new_name:
            return

        must_force_reload = bool(force_reload or (old_name == new_name))
        self._ensure_pairs_loaded(new_name, force=must_force_reload)

    def _clear_selected_pair(self, index):
        column = self._column(index)
        if column is None:
            return

        column.selected_pair = None
        clear_own_order = getattr(self, "_clear_own_order", None)
        if callable(clear_own_order):
            clear_own_order(index)

        edit = column.pair_edit
        if edit is not None:
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)

        column.pair_reedit = False
        column.pair_edit_active = False
        column.pair_edit_snapshot_pair = None
        column.pair_edit_snapshot_text = ""
        self._update_pair_input_mode(index)
        self._sync_quote_stream(index)
        self._refresh_spread_display_safe()
        self._refresh_trade_control_safe(index)
        self._persist_spread_selection_safe(index)

    def _set_selected_pair(self, index, pair):
        column = self._column(index)
        if column is None:
            return

        old_pair = column.selected_pair
        new_pair = self._normalize_pair(pair)
        if column.selected_pair != new_pair:
            clear_own_order = getattr(self, "_clear_own_order", None)
            if callable(clear_own_order):
                clear_own_order(index)

        column.selected_pair = new_pair
        self._update_pair_input_mode(index)
        self._sync_quote_stream(index)
        self._refresh_spread_display_safe()
        self._refresh_trade_control_safe(index)
        self._persist_spread_selection_safe(index)
        self._trace_selection(
            "set_pair",
            index=index,
            old=old_pair or "",
            new=new_pair or "",
        )

    def _get_selected_pair(self, index):
        column = self._column(index)
        return column.selected_pair if column else None

    def _refresh_selector_state(self):
        has_connected = bool(self._connected_rows())

        for column in self._iter_columns():
            if column.selector_button is not None:
                column.selector_button.setEnabled(has_connected)

            if column.selected_exchange and self.exchange_manager.get_exchange(column.selected_exchange) is None:
                self._set_selected_exchange(column.index, None)

        self._update_selector_texts()
        self._refresh_pair_controls()
        self._refresh_spread_display_safe()
        self._refresh_trade_controls_safe()

    def _selector_text(self, column):
        key = (
            f"spread.exchange_{column.index}_selected"
            if column.selected_exchange
            else f"spread.exchange_{column.index}_default"
        )
        return tr(key, name=column.selected_exchange) if column.selected_exchange else tr(key)

    def _update_selector_texts(self):
        for column in self._iter_columns():
            btn = column.selector_button
            if btn is None:
                continue

            btn.setText(self._selector_text(column))
            exchange_type = self._exchange_type_for_name(column.selected_exchange)
            if exchange_type:
                btn.setIcon(build_exchange_icon(exchange_type, size=24))
            else:
                btn.setIcon(QIcon())
            btn.setIconSize(QSize(24, 24))

        resize_capsules = getattr(self, "_update_selector_pair_capsule_widths", None)
        if callable(resize_capsules):
            resize_capsules()

    def _open_exchange_menu(self, index):
        self._set_spread_pending_selection_safe()

        rows = self._connected_rows()
        if not rows:
            self._trace_selection("open_menu_skipped", index=index, reason="no_connected_exchanges")
            return

        column = self._column(index)
        if column is None:
            return
        self._trace_selection(
            "open_menu",
            index=index,
            current=column.selected_exchange or "",
            rows=len(rows),
        )

        dialog = ConnectedExchangePickerDialog(
            rows,
            selector_index=index,
            current_name=column.selected_exchange,
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            self._trace_selection("menu_cancelled", index=index)
            return

        if dialog.reset_requested:
            self._trace_selection("menu_reset", index=index, old=column.selected_exchange or "")
            self._set_selected_exchange(index, None)
            return

        chosen_name = dialog.selected_name
        if chosen_name:
            self._trace_selection("menu_selected", index=index, chosen=chosen_name)
            # Even when selecting the same exchange, force pairs refresh.
            self._set_selected_exchange(index, chosen_name, force_reload=True)

    def _refresh_pair_controls(self):
        for column in self._iter_columns():
            self._refresh_pair_control(column.index)

    def _refresh_pair_control(self, index):
        column = self._column(index)
        if column is None:
            return

        edit = column.pair_edit
        if edit is None:
            return

        exchange_name = column.selected_exchange
        if not exchange_name:
            edit.setVisible(False)
            edit.setEnabled(False)
            edit.setPlaceholderText(tr("spread.pair_placeholder"))
            self._update_completer_items(index, [])
            column.pair_reedit = False
            column.pair_edit_active = False
            self._update_pair_input_mode(index)
            self._sync_quote_stream(index)
            return

        edit.setVisible(True)

        if exchange_name in self._pair_loading:
            edit.setEnabled(False)
            edit.setPlaceholderText(tr("spread.pairs_loading"))
            column.pair_reedit = False
            column.pair_edit_active = False
            self._update_pair_input_mode(index)
            self._sync_quote_stream(index)
            return

        pairs = self._pair_cache.get(exchange_name)
        state = self._get_pair_state(exchange_name)

        if pairs is None:
            self._ensure_pairs_loaded(exchange_name)
            if exchange_name in self._pair_loading:
                edit.setEnabled(False)
                edit.setPlaceholderText(tr("spread.pairs_loading"))
                return
            pairs = self._pair_cache.get(exchange_name, [])
            state = self._get_pair_state(exchange_name)

        if not pairs and state in {"error", "transient_empty"} and self._can_retry_pairs(exchange_name):
            self._ensure_pairs_loaded(exchange_name, force=True)
            if exchange_name in self._pair_loading:
                edit.setEnabled(False)
                edit.setPlaceholderText(tr("spread.pairs_loading"))
                return
            pairs = self._pair_cache.get(exchange_name, [])

        if pairs:
            edit.setEnabled(True)
            edit.setPlaceholderText(tr("spread.pair_placeholder"))
            if column.selected_pair and self._normalize_pair(edit.text()) != column.selected_pair:
                edit.blockSignals(True)
                edit.setText(column.selected_pair)
                edit.blockSignals(False)
            if not edit.text().strip():
                self._update_completer_items(index, self._popular_for_exchange(exchange_name))
            self._update_pair_input_mode(index)
            self._sync_quote_stream(index)
        else:
            edit.setEnabled(False)
            edit.setPlaceholderText(tr("spread.pairs_empty"))
            self._update_completer_items(index, [])
            column.pair_reedit = False
            column.pair_edit_active = False
            self._update_pair_input_mode(index)
            self._sync_quote_stream(index)
