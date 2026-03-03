from PySide6.QtCore import QModelIndex, QTimer, Qt


class SpreadPairInputSessionMixin:
    def _on_pair_text_edited(self, index, text):
        exchange_name = self._get_selected_exchange(index)
        if not exchange_name or exchange_name in self._pair_loading:
            return

        query = self._normalize_pair(text)
        if query != self._get_selected_pair(index):
            self._set_selected_pair(index, None)

        self._schedule_pair_suggestions(index, query)

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

