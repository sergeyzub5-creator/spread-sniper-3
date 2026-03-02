from core.exchange.catalog import normalize_exchange_code
from core.i18n import tr
from core.utils.thread_pool import ThreadManager, Worker


class SpreadOrderBookMixin:
    ORDER_BOOK_LEVELS = 3

    def _refresh_order_book_texts(self):
        for column in self._iter_columns():
            if column.order_book_note_label is not None:
                column.order_book_note_label.setText(tr("spread.temp_order_book_note"))
            self._apply_order_book_text_state(column.index)
            self._apply_own_order_visual(column.index)

    def _normalize_order_book_levels(self, rows, limit=3):
        out = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            price = self._to_float(row.get("price"))
            qty = self._to_float(row.get("qty"))
            if price is None or qty is None or price <= 0 or qty <= 0:
                continue
            out.append({"price": price, "qty": qty})
            if len(out) >= int(limit or 1):
                break
        return out

    def _set_order_book_state(self, index, state, bids=None, asks=None):
        column = self._column(index)
        if column is None:
            return

        column.order_book_state = str(state or "empty")
        column.order_book_bids = self._normalize_order_book_levels(
            bids, limit=self.ORDER_BOOK_LEVELS
        )
        column.order_book_asks = self._normalize_order_book_levels(
            asks, limit=self.ORDER_BOOK_LEVELS
        )
        self._apply_order_book_text_state(index)
        self._apply_own_order_visual(index)

    def _show_order_book_widget(self, index, visible):
        column = self._column(index)
        if column and column.order_book_frame is not None:
            column.order_book_frame.setVisible(bool(visible))

    def _apply_order_book_text_state(self, index):
        column = self._column(index)
        if column is None:
            return

        bid_labels = list(column.order_book_bid_labels or [])
        ask_labels = list(column.order_book_ask_labels or [])
        if not bid_labels or not ask_labels:
            return

        state = str(column.order_book_state or "empty")
        bids = list(column.order_book_bids or [])
        asks = list(column.order_book_asks or [])

        if state == "loading":
            for level in range(1, self.ORDER_BOOK_LEVELS + 1):
                bid_labels[level - 1].setText(
                    tr(
                        "spread.order_book_bid_level",
                        level=level,
                        price=tr("spread.order_book_value_loading"),
                        qty=tr("spread.order_book_value_loading"),
                    )
                )
                ask_labels[level - 1].setText(
                    tr(
                        "spread.order_book_ask_level",
                        level=level,
                        price=tr("spread.order_book_value_loading"),
                        qty=tr("spread.order_book_value_loading"),
                    )
                )
            return

        for level in range(1, self.ORDER_BOOK_LEVELS + 1):
            bid_row = bids[level - 1] if len(bids) >= level else None
            ask_row = asks[level - 1] if len(asks) >= level else None

            bid_price = self._format_price(bid_row.get("price")) if bid_row else "--"
            bid_qty = self._format_price(bid_row.get("qty")) if bid_row else "--"
            ask_price = self._format_price(ask_row.get("price")) if ask_row else "--"
            ask_qty = self._format_price(ask_row.get("qty")) if ask_row else "--"

            bid_labels[level - 1].setText(
                tr("spread.order_book_bid_level", level=level, price=bid_price, qty=bid_qty)
            )
            ask_labels[level - 1].setText(
                tr("spread.order_book_ask_level", level=level, price=ask_price, qty=ask_qty)
            )

    def _stop_all_order_book_streams(self):
        for column in self._iter_columns():
            self._stop_order_book_stream(column.index)

    def _stop_order_book_stream(self, index):
        column = self._column(index)
        if column is None:
            return

        worker = column.order_book_snapshot_worker
        column.order_book_snapshot_worker = None
        if worker is not None:
            try:
                worker.signals.result.disconnect()
                worker.signals.finished.disconnect()
            except Exception:
                pass

        stream = column.order_book_stream
        if stream is not None:
            stream.stop()
        column.order_book_stream_state = None

    def _sync_order_book_stream(self, index):
        column = self._column(index)
        if column is None:
            return

        exchange_name = column.selected_exchange
        pair = column.selected_pair

        if not exchange_name or not pair:
            self._stop_order_book_stream(index)
            self._set_order_book_state(index, "empty")
            self._show_order_book_widget(index, False)
            return

        self._show_order_book_widget(index, True)
        exchange = self.exchange_manager.get_exchange(exchange_name)
        if exchange is None:
            self._stop_order_book_stream(index)
            self._set_order_book_state(index, "empty")
            return

        exchange_type = normalize_exchange_code(getattr(exchange, "exchange_type", None))
        if exchange_type != "binance" or not exchange.is_connected:
            self._stop_order_book_stream(index)
            self._set_order_book_state(index, "empty")
            return

        desired_state = (exchange_name, pair, bool(getattr(exchange, "testnet", False)))
        if column.order_book_stream_state == desired_state:
            return

        self._stop_order_book_stream(index)
        column.order_book_stream_state = desired_state
        self._set_order_book_state(index, "loading")
        self._start_order_book_snapshot(index, exchange_name, pair)

        if column.order_book_stream is not None:
            column.order_book_stream.start(pair, testnet=bool(getattr(exchange, "testnet", False)))

    def _start_order_book_snapshot(self, index, exchange_name, pair):
        worker = Worker(self._fetch_order_book_snapshot_task, exchange_name, pair)

        column = self._column(index)
        if column is None:
            return
        column.order_book_snapshot_worker = worker

        worker.signals.result.connect(
            lambda result, idx=index, name=exchange_name, sym=pair: self._on_order_book_snapshot_result(
                idx, name, sym, result
            )
        )
        worker.signals.finished.connect(lambda idx=index: self._clear_order_book_snapshot_worker(idx))
        ThreadManager().start(worker)

    def _clear_order_book_snapshot_worker(self, index):
        column = self._column(index)
        if column is not None:
            column.order_book_snapshot_worker = None

    def _fetch_order_book_snapshot_task(self, exchange_name, pair):
        return self._runtime_service.fetch_order_book_snapshot(
            exchange_name, pair, levels=self.ORDER_BOOK_LEVELS
        )

    def _on_order_book_snapshot_result(self, index, exchange_name, pair, result):
        column = self._column(index)
        if column is None:
            return

        current = column.order_book_stream_state
        if current is None:
            return
        if current[0] != exchange_name or current[1] != pair:
            return
        if not isinstance(result, dict):
            return

        self._set_order_book_state(
            index,
            "live",
            bids=result.get("bids") or [],
            asks=result.get("asks") or [],
        )

    def _on_order_book_tick(self, index, payload):
        column = self._column(index)
        if column is None or not isinstance(payload, dict):
            return

        current = column.order_book_stream_state
        if current is None:
            return

        selected_exchange = column.selected_exchange
        selected_pair = column.selected_pair
        if not selected_exchange or not selected_pair:
            return
        if current[0] != selected_exchange or current[1] != selected_pair:
            return

        symbol = self._normalize_pair(payload.get("symbol"))
        if symbol and symbol != selected_pair:
            return

        self._set_order_book_state(
            index,
            "live",
            bids=payload.get("bids") or [],
            asks=payload.get("asks") or [],
        )

    def _on_order_book_stream_error(self, index):
        column = self._column(index)
        if column is None:
            return

        if column.order_book_stream_state is None:
            return
        if column.order_book_state != "live":
            self._set_order_book_state(index, "loading")

    def _clear_own_order(self, index):
        column = self._column(index)
        if column is None:
            return
        column.own_order = None
        self._apply_own_order_visual(index)

    def _set_own_order_from_trade_result(self, index, side, result):
        column = self._column(index)
        if column is None:
            return

        data = result if isinstance(result, dict) else {}
        price = self._to_float(data.get("limit_price"))
        if price is None or price <= 0:
            price = self._to_float(data.get("price"))
        if price is None or price <= 0:
            price = self._to_float(data.get("avg_price"))
        if price is None or price <= 0:
            self._clear_own_order(index)
            return

        qty = str(
            data.get("quantity")
            or data.get("executed_qty")
            or data.get("executedQty")
            or data.get("qty")
            or "--"
        )
        status = str(data.get("status") or "NEW").strip().upper()
        symbol = self._normalize_pair(data.get("symbol") or column.selected_pair)
        side_norm = "buy" if str(side or "").strip().lower() == "buy" else "sell"

        column.own_order = {
            "side": side_norm,
            "price": price,
            "qty": qty,
            "status": status,
            "symbol": symbol,
            "order_id": data.get("order_id") or data.get("orderId"),
        }
        self._apply_own_order_visual(index)

    def _prices_match(self, left, right):
        a = self._to_float(left)
        b = self._to_float(right)
        if a is None or b is None:
            return False
        eps = max(abs(a) * 1e-8, 1e-10)
        return abs(a - b) <= eps

    def _refresh_order_level_style(self, label, enabled):
        if label is None:
            return
        label.setProperty("ownLevel", bool(enabled))
        style = label.style()
        if style is not None:
            style.unpolish(label)
            style.polish(label)
        label.update()

    def _apply_own_order_visual(self, index):
        column = self._column(index)
        if column is None:
            return

        own_label = column.order_book_own_label
        bid_labels = list(column.order_book_bid_labels or [])
        ask_labels = list(column.order_book_ask_labels or [])
        if own_label is None or not bid_labels or not ask_labels:
            return

        for label in bid_labels:
            self._refresh_order_level_style(label, False)
        for label in ask_labels:
            self._refresh_order_level_style(label, False)

        own = column.own_order
        if not isinstance(own, dict):
            own_label.setText(tr("spread.order_book_own_none"))
            return

        pair = self._normalize_pair(own.get("symbol"))
        if pair and pair != (column.selected_pair or ""):
            own_label.setText(tr("spread.order_book_own_none"))
            return

        side = str(own.get("side") or "").strip().lower()
        side = "buy" if side == "buy" else "sell"
        side_text = tr("spread.side.buy") if side == "buy" else tr("spread.side.sell")
        price = self._to_float(own.get("price"))
        qty = str(own.get("qty") or "--")
        status = str(own.get("status") or "NEW").strip().upper()
        price_view = self._format_price(price)

        # User-facing logic for spread tab:
        # BUY order is tracked in asks (sell book), SELL order is tracked in bids (buy book).
        levels = list(column.order_book_asks if side == "buy" else column.order_book_bids)
        matched_level = None
        for row_idx, row in enumerate(levels, start=1):
            if self._prices_match(row.get("price"), price):
                matched_level = row_idx
                break

        if matched_level is not None:
            if side == "buy" and len(ask_labels) >= matched_level:
                self._refresh_order_level_style(ask_labels[matched_level - 1], True)
            if side == "sell" and len(bid_labels) >= matched_level:
                self._refresh_order_level_style(bid_labels[matched_level - 1], True)
            own_label.setText(
                tr(
                    "spread.order_book_own_at_level",
                    side=side_text,
                    price=price_view,
                    qty=qty,
                    level=matched_level,
                    status=status,
                )
            )
            return

        own_label.setText(
            tr(
                "spread.order_book_own_outside",
                side=side_text,
                price=price_view,
                qty=qty,
                status=status,
            )
        )
