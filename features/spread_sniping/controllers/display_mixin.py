from core.i18n import tr


class SpreadDisplayMixin:
    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_price(value):
        numeric = SpreadDisplayMixin._to_float(value)
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
            return {
                "percent": None,
                "effective_edge_pct": None,
                "cheap_index": None,
                "expensive_index": None,
                "signal": None,
                "phase": "no_data",
            }

        if not left.selected_exchange or not right.selected_exchange:
            return {
                "percent": None,
                "effective_edge_pct": None,
                "cheap_index": None,
                "expensive_index": None,
                "signal": None,
                "phase": "no_data",
            }
        if not left.selected_pair or not right.selected_pair:
            return {
                "percent": None,
                "effective_edge_pct": None,
                "cheap_index": None,
                "expensive_index": None,
                "signal": None,
                "phase": "no_data",
            }

        return self._strategy_engine.evaluate(
            left_bid=left.quote_bid,
            left_ask=left.quote_ask,
            right_bid=right.quote_bid,
            right_ask=right.quote_ask,
            config=self._strategy_config,
            state=self._strategy_state,
        )

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

    def _set_spread_edge_tone(self, cheap_index, expensive_index):
        frame = getattr(self, "spread_value_frame", None)
        if frame is None:
            return

        tone = "neutral"
        if cheap_index == 1 and expensive_index == 2:
            tone = "left_cheap"
        elif cheap_index == 2 and expensive_index == 1:
            tone = "right_cheap"

        if frame.property("edgeTone") == tone:
            return
        frame.setProperty("edgeTone", tone)
        frame.style().unpolish(frame)
        frame.style().polish(frame)
        frame.update()

    @classmethod
    def _normalize_spread_variant(cls, variant_code):
        code = str(variant_code or "").strip().lower()
        if code in cls.SUPPORTED_SPREAD_VARIANTS:
            return code
        return "neon_frame"

    def spread_visual_variant(self):
        return self._spread_visual_variant

    @staticmethod
    def _repolish_widget(widget):
        if widget is None:
            return
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _apply_spread_visual_variant(self):
        variant = self._spread_visual_variant
        frame = getattr(self, "spread_value_frame", None)
        inner = getattr(self, "spread_value_inner", None)
        action_btn = getattr(self, "spread_select_btn", None)
        value_label = getattr(self, "spread_value_label", None)
        for widget in (frame, inner, action_btn, value_label):
            if widget is None:
                continue
            if widget.property("variant") == variant:
                continue
            widget.setProperty("variant", variant)
            self._repolish_widget(widget)

    def set_spread_visual_variant(self, variant_code):
        normalized = self._normalize_spread_variant(variant_code)
        if normalized == self._spread_visual_variant:
            return
        self._spread_visual_variant = normalized
        self._apply_spread_visual_variant()
        self.apply_theme()
        self._refresh_spread_display()

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
                outer_layout.setContentsMargins(2, 2, 2, 2)
            else:
                outer_layout.setContentsMargins(0, 0, 0, 0)
        if stack is not None:
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
        self._sync_strategy_state_from_spread(state)

        if not self._spread_armed:
            self._set_spread_frame_mode("select")
            stack.setCurrentWidget(select_btn)
            select_btn.setEnabled(spread_value is not None)
            self._apply_exchange_tone(1, "neutral")
            self._apply_exchange_tone(2, "neutral")
            self._set_spread_edge_tone(None, None)
            return

        self._set_spread_frame_mode("spread")
        stack.setCurrentWidget(label)

        self._apply_exchange_tone(1, "neutral")
        self._apply_exchange_tone(2, "neutral")
        if cheap_index in {1, 2}:
            self._apply_exchange_tone(cheap_index, "cheap")
        if expensive_index in {1, 2}:
            self._apply_exchange_tone(expensive_index, "expensive")
        self._set_spread_edge_tone(cheap_index, expensive_index)

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
