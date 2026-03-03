import time
from difflib import SequenceMatcher

from PySide6.QtCore import QModelIndex, QSize, QTimer, Qt
from PySide6.QtGui import QIcon

from core.exchange.catalog import normalize_exchange_code
from core.i18n import tr
from core.utils.thread_pool import ThreadManager, Worker
from features.spread_sniping.dialogs.connected_exchange_picker_dialog import (
    ConnectedExchangePickerDialog,
)
from ui.widgets.exchange_badge import build_exchange_icon


class SpreadSelectionMixin:
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

    def _get_pair_state(self, exchange_name):
        return str(self._pair_cache_state.get(exchange_name, "unknown") or "unknown")

    def _set_pair_state(self, exchange_name, state):
        self._pair_cache_state[exchange_name] = str(state or "unknown")

    def _can_retry_pairs(self, exchange_name, force=False):
        now = time.monotonic()
        if force:
            self._pair_last_retry_ts[exchange_name] = now
            return True

        cooldown = float(getattr(self, "_pair_retry_cooldown_sec", 2.5) or 2.5)
        last_ts = float(self._pair_last_retry_ts.get(exchange_name, 0.0) or 0.0)
        if now - last_ts < cooldown:
            return False

        self._pair_last_retry_ts[exchange_name] = now
        return True

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

    def _open_exchange_menu(self, index):
        self._set_spread_pending_selection_safe()

        rows = self._connected_rows()
        if not rows:
            return

        column = self._column(index)
        if column is None:
            return

        dialog = ConnectedExchangePickerDialog(
            rows,
            selector_index=index,
            current_name=column.selected_exchange,
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        if dialog.reset_requested:
            self._set_selected_exchange(index, None)
            return

        chosen_name = dialog.selected_name
        if chosen_name:
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

    def _ensure_pairs_loaded(self, exchange_name, force=False):
        if not exchange_name:
            return
        if exchange_name in self._pair_loading:
            return

        has_cache = exchange_name in self._pair_cache
        cache_state = self._get_pair_state(exchange_name)

        if not force:
            if has_cache and cache_state in {"ok", "empty"}:
                return
            if has_cache and cache_state in {"error", "transient_empty"} and not self._can_retry_pairs(exchange_name):
                return
        else:
            self._can_retry_pairs(exchange_name, force=True)

        self._pair_loading.add(exchange_name)
        self._set_pair_state(exchange_name, "loading")
        self._refresh_pair_controls()

        worker = Worker(self._load_pairs_task, exchange_name)
        self._pair_workers[exchange_name] = worker
        worker.signals.result.connect(lambda pairs, name=exchange_name: self._on_pairs_loaded(name, pairs))
        worker.signals.error.connect(lambda _error, name=exchange_name: self._on_pairs_error(name))
        worker.signals.finished.connect(lambda name=exchange_name: self._on_pairs_finished(name))
        ThreadManager().start(worker)

    def _load_pairs_task(self, exchange_name):
        return self._runtime_service.load_pairs(exchange_name)

    def _on_pairs_loaded(self, exchange_name, payload):
        strict = False
        refreshable = False
        pairs = payload
        if isinstance(payload, dict):
            strict = bool(payload.get("strict", False))
            refreshable = bool(payload.get("refreshable", False))
            pairs = payload.get("pairs", [])

        normalized = self._normalize_pairs(pairs)
        if not normalized and not strict:
            normalized = list(self.POPULAR_PAIRS)

        self._pair_cache[exchange_name] = normalized
        if normalized:
            self._pair_popular_cache[exchange_name] = self._build_popular_list(normalized)
            self._set_pair_state(exchange_name, "ok")
        else:
            self._pair_popular_cache[exchange_name] = []
            self._set_pair_state(exchange_name, "transient_empty" if refreshable else "empty")

        for column in self._iter_columns():
            if column.selected_exchange != exchange_name:
                continue
            if column.selected_pair and column.selected_pair not in normalized:
                self._clear_selected_pair(column.index)

    def _on_pairs_error(self, exchange_name):
        if self._runtime_service.is_pairs_source_strict(exchange_name):
            self._pair_cache[exchange_name] = []
            self._pair_popular_cache[exchange_name] = []
        else:
            self._pair_cache[exchange_name] = list(self.POPULAR_PAIRS)
            self._pair_popular_cache[exchange_name] = self._build_popular_list(self.POPULAR_PAIRS)
        self._set_pair_state(exchange_name, "error")

    def _on_pairs_finished(self, exchange_name):
        self._pair_loading.discard(exchange_name)
        self._pair_workers.pop(exchange_name, None)
        self._refresh_pair_controls()
        self._refresh_trade_controls_safe()

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
        if not exchange_name or exchange_name in self._pair_loading:
            return

        query = self._normalize_pair(text)
        if query != self._get_selected_pair(index):
            self._set_selected_pair(index, None)

        self._schedule_pair_suggestions(index, query)

    def _schedule_pair_suggestions(self, index, query):
        timers = getattr(self, "_pair_suggest_timers", None)
        if timers is None:
            timers = {}
            self._pair_suggest_timers = timers

        queries = getattr(self, "_pair_suggest_queries", None)
        if queries is None:
            queries = {}
            self._pair_suggest_queries = queries

        normalized_query = self._normalize_pair(query)
        queries[index] = normalized_query

        timer = timers.get(index)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda idx=index: self._apply_scheduled_pair_suggestions(idx))
            timers[index] = timer

        # Small debounce keeps typing responsive on large pair lists.
        timer.start(55)

    def _apply_scheduled_pair_suggestions(self, index):
        queries = getattr(self, "_pair_suggest_queries", None) or {}
        query = self._normalize_pair(queries.get(index, ""))

        suggestions = self._build_suggestions(index, query)
        self._update_completer_items(index, suggestions)

        column = self._column(index)
        if (
            column is not None
            and suggestions
            and column.pair_completer is not None
            and column.pair_edit is not None
            and column.pair_edit.hasFocus()
        ):
            column.pair_completer.complete()

    def _on_pair_editing_finished(self, index):
        column = self._column(index)
        if column is None:
            return

        if column.pair_accepting:
            self._finish_pair_edit_session(index)
            self._update_pair_input_mode(index)
            return

        edit = column.pair_edit
        if edit is None:
            return

        text = self._normalize_pair(edit.text())
        if not text:
            self._set_selected_pair(index, None)
            self._finish_pair_edit_session(index)
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

        self._finish_pair_edit_session(index)
        self._update_pair_input_mode(index)

    def _on_pair_completer_activated(self, index, value):
        if isinstance(value, QModelIndex):
            pair_text = value.data(Qt.ItemDataRole.DisplayRole)
        else:
            pair_text = str(value)
        self._on_pair_chosen(index, pair_text)

    def _on_pair_chosen(self, index, value):
        column = self._column(index)
        if column is None:
            return

        pair = self._normalize_pair(value)
        if not pair:
            return

        column.pair_accepting = True
        edit = column.pair_edit
        if edit is None:
            return

        edit.blockSignals(True)
        edit.setText(pair)
        edit.blockSignals(False)

        self._set_selected_pair(index, pair)
        self._finish_pair_edit_session(index)
        self._update_pair_input_mode(index)
        self._hide_all_pair_popups()
        edit.clearFocus()

        QTimer.singleShot(0, lambda idx=index: self._clear_pair_accepting(idx))

    def _clear_pair_accepting(self, index):
        column = self._column(index)
        if column is not None:
            column.pair_accepting = False

    def _show_pair_popup(self, index, force_popular=False):
        exchange_name = self._get_selected_exchange(index)
        if not exchange_name or exchange_name in self._pair_loading:
            return

        pairs = self._pairs_for_index(index)
        if not pairs:
            self._ensure_pairs_loaded(exchange_name)
            return

        column = self._column(index)
        if column is None or column.pair_edit is None or column.pair_completer is None:
            return

        if not column.pair_edit.isEnabled():
            return

        query = "" if force_popular else self._normalize_pair(column.pair_edit.text())
        suggestions = self._build_suggestions(index, query)
        if not suggestions:
            return

        self._update_completer_items(index, suggestions)
        column.pair_completer.complete()

    def _on_pair_field_clicked(self, index):
        column = self._column(index)
        if column is None or column.pair_edit is None:
            return

        self._set_spread_pending_selection_safe()

        for other in self._iter_columns():
            if other.index != index:
                self._cancel_pair_edit_session(other.index)

        edit = column.pair_edit
        if not edit.isEnabled():
            return

        self._begin_pair_edit_session(index)
        if column.selected_pair:
            column.pair_reedit = True
            edit.setFocus(Qt.FocusReason.MouseFocusReason)
            edit.selectAll()
        else:
            column.pair_reedit = False

        self._update_pair_input_mode(index)
        QTimer.singleShot(0, lambda idx=index: self._show_pair_popup(idx, force_popular=True))

    def _update_pair_input_mode(self, index):
        column = self._column(index)
        if column is None or column.pair_edit is None:
            return

        edit = column.pair_edit
        if not edit.isVisible() or not edit.isEnabled():
            edit.setReadOnly(True)
            edit.setClearButtonEnabled(False)
            edit.setCursor(Qt.CursorShape.ArrowCursor)
            return

        if not column.pair_edit_active:
            edit.setReadOnly(True)
            edit.setClearButtonEnabled(False)
            edit.setCursor(Qt.CursorShape.PointingHandCursor)
            return

        if column.selected_pair and not column.pair_reedit:
            edit.setReadOnly(True)
            edit.setClearButtonEnabled(False)
            edit.setCursor(Qt.CursorShape.PointingHandCursor)
            return

        edit.setReadOnly(False)
        edit.setClearButtonEnabled(bool(column.selected_pair and column.pair_reedit))
        edit.setCursor(Qt.CursorShape.IBeamCursor)

    def _begin_pair_edit_session(self, index):
        column = self._column(index)
        if column is None or column.pair_edit is None:
            return

        if not column.pair_edit_active:
            snapshot_pair = column.selected_pair
            snapshot_text = snapshot_pair or self._normalize_pair(column.pair_edit.text())
            column.pair_edit_snapshot_pair = snapshot_pair
            column.pair_edit_snapshot_text = snapshot_text
        column.pair_edit_active = True

    def _finish_pair_edit_session(self, index):
        column = self._column(index)
        if column is None:
            return
        column.pair_reedit = False
        column.pair_edit_active = False
        column.pair_edit_snapshot_pair = column.selected_pair
        if column.pair_edit is not None:
            column.pair_edit_snapshot_text = self._normalize_pair(column.pair_edit.text())
        else:
            column.pair_edit_snapshot_text = column.selected_pair or ""

    def _cancel_pair_edit_session(self, index):
        column = self._column(index)
        if column is None or not column.pair_edit_active:
            return False

        edit = column.pair_edit
        restore_pair = column.pair_edit_snapshot_pair
        restore_text = column.pair_edit_snapshot_text or ""

        self._set_selected_pair(index, restore_pair)
        if edit is not None:
            edit.blockSignals(True)
            edit.setText(restore_text)
            edit.blockSignals(False)

        self._finish_pair_edit_session(index)
        self._update_pair_input_mode(index)
        return True

    def _cancel_pair_input_sessions(self):
        canceled_any = False
        for column in self._iter_columns():
            if self._cancel_pair_edit_session(column.index):
                canceled_any = True

        if canceled_any:
            self._hide_all_pair_popups()

    def _hide_all_pair_popups(self):
        for column in self._iter_columns():
            completer = column.pair_completer
            if completer is None:
                continue
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
        for column in self._iter_columns():
            edit = column.pair_edit
            if self._contains_global_point(edit, global_pos):
                return True
            completer = column.pair_completer
            popup = completer.popup() if completer is not None else None
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

        exact = None
        starts = []
        contains = []
        for pair in pairs:
            if pair == q:
                exact = pair
                continue

            if pair.startswith(q):
                starts.append(pair)
                continue

            pos = pair.find(q)
            if pos >= 0:
                contains.append((pos, len(pair), pair))

        starts.sort(key=lambda item: (len(item), item))
        contains.sort(key=lambda item: (item[0], item[1], item[2]))

        result = []
        if exact:
            result.append(exact)
        result.extend(starts)
        result.extend(pair for _pos, _length, pair in contains)
        if len(result) >= self.MAX_SUGGESTIONS or len(q) <= 1:
            return result[: self.MAX_SUGGESTIONS]

        # Fuzzy fallback is bounded to keep UI smooth on very large lists.
        seed = set(result)
        fuzzy = []
        scanned = 0
        first_char = q[0]
        for pair in pairs:
            if pair in seed:
                continue
            if first_char not in pair:
                continue
            scanned += 1
            ratio = SequenceMatcher(None, q, pair).ratio()
            if ratio < 0.45:
                continue
            fuzzy.append((ratio, len(pair), pair))
            if scanned >= 320:
                break

        fuzzy.sort(key=lambda item: (-item[0], item[1], item[2]))
        result.extend(pair for _ratio, _length, pair in fuzzy)
        return result[: self.MAX_SUGGESTIONS]

    def _update_completer_items(self, index, items):
        column = self._column(index)
        if column is None or column.pair_model is None:
            return
        column.pair_model.setStringList(self._normalize_pairs(items))
