from core.exchange.catalog import normalize_exchange_code
from core.i18n import tr
from core.utils.thread_pool import ThreadManager, Worker


class SpreadQuoteMixin:
    def _refresh_all_quote_labels(self):
        for column in self._iter_columns():
            self._apply_quote_text_state(column.index)

    def _apply_quote_text_state(self, index):
        column = self._column(index)
        if column is None:
            return

        bid_label = column.quote_bid_label
        ask_label = column.quote_ask_label
        bid_qty_label = getattr(column, "quote_bid_qty_label", None)
        ask_qty_label = getattr(column, "quote_ask_qty_label", None)
        use_split_capsules = bid_qty_label is not None and ask_qty_label is not None
        if bid_label is None or ask_label is None:
            return

        state = column.quote_state or "empty"
        bid = column.quote_bid
        ask = column.quote_ask
        bid_qty = column.quote_bid_qty
        ask_qty = column.quote_ask_qty

        if state == "live":
            bid_price_text = self._format_price(bid)
            ask_price_text = self._format_price(ask)
            bid_qty_value = self._to_float(bid_qty)
            ask_qty_value = self._to_float(ask_qty)

            if use_split_capsules:
                bid_label.setText(tr("spread.bid_price", value=bid_price_text))
                ask_label.setText(tr("spread.ask_price", value=ask_price_text))
                if bid_qty_value is not None and bid_qty_value > 0:
                    bid_qty_label.setText(tr("spread.qty_value", qty=self._format_price(bid_qty_value)))
                else:
                    bid_qty_label.setText(tr("spread.qty_empty"))
                if ask_qty_value is not None and ask_qty_value > 0:
                    ask_qty_label.setText(tr("spread.qty_value", qty=self._format_price(ask_qty_value)))
                else:
                    ask_qty_label.setText(tr("spread.qty_empty"))
            else:
                if bid_qty_value is not None and bid_qty_value > 0:
                    bid_label.setText(
                        tr(
                            "spread.best_bid_with_qty",
                            value=bid_price_text,
                            qty=self._format_price(bid_qty_value),
                        )
                    )
                else:
                    bid_label.setText(tr("spread.best_bid", value=bid_price_text))

                if ask_qty_value is not None and ask_qty_value > 0:
                    ask_label.setText(
                        tr(
                            "spread.best_ask_with_qty",
                            value=ask_price_text,
                            qty=self._format_price(ask_qty_value),
                        )
                    )
                else:
                    ask_label.setText(tr("spread.best_ask", value=ask_price_text))
            return

        if state == "loading":
            if use_split_capsules:
                bid_label.setText(tr("spread.bid_price_loading"))
                ask_label.setText(tr("spread.ask_price_loading"))
                bid_qty_label.setText(tr("spread.qty_loading"))
                ask_qty_label.setText(tr("spread.qty_loading"))
            else:
                bid_label.setText(tr("spread.best_bid_loading"))
                ask_label.setText(tr("spread.best_ask_loading"))
            return

        if use_split_capsules:
            bid_label.setText(tr("spread.bid_price_empty"))
            ask_label.setText(tr("spread.ask_price_empty"))
            bid_qty_label.setText(tr("spread.qty_empty"))
            ask_qty_label.setText(tr("spread.qty_empty"))
        else:
            bid_label.setText(tr("spread.best_bid_empty"))
            ask_label.setText(tr("spread.best_ask_empty"))

    def _set_quote_state(self, index, state, bid=None, ask=None, bid_qty=None, ask_qty=None):
        column = self._column(index)
        if column is None:
            return

        column.quote_state = str(state or "empty")
        column.quote_bid = bid
        column.quote_ask = ask
        column.quote_bid_qty = bid_qty
        column.quote_ask_qty = ask_qty
        self._apply_quote_text_state(index)
        refresh_spread = getattr(self, "_refresh_spread_display", None)
        if callable(refresh_spread):
            refresh_spread()

    def _show_quote_widget(self, index, visible):
        column = self._column(index)
        if column and column.quote_frame is not None:
            column.quote_frame.setVisible(bool(visible))

    def _stop_all_quote_streams(self):
        for column in self._iter_columns():
            self._stop_quote_stream(column.index)

    def _stop_quote_stream(self, index):
        column = self._column(index)
        if column is None:
            return

        worker = column.quote_snapshot_worker
        column.quote_snapshot_worker = None
        if worker is not None:
            try:
                worker.signals.result.disconnect()
                worker.signals.finished.disconnect()
            except Exception:
                pass

        streams = getattr(column, "quote_streams", None)
        if isinstance(streams, dict) and streams:
            for stream in streams.values():
                if stream is None:
                    continue
                stream.stop()
        else:
            stream = column.quote_stream
            if stream is not None:
                stream.stop()
        column.quote_stream_state = None

    def _sync_quote_stream(self, index):
        column = self._column(index)
        if column is None:
            return

        exchange_name = column.selected_exchange
        pair = column.selected_pair

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
        if exchange_type not in {"binance", "bitget"} or not exchange.is_connected:
            self._stop_quote_stream(index)
            self._set_quote_state(index, "empty")
            return

        desired_state = (
            exchange_name,
            pair,
            exchange_type,
            bool(getattr(exchange, "testnet", False)),
        )
        if column.quote_stream_state == desired_state:
            return

        self._stop_quote_stream(index)
        column.quote_stream_state = desired_state
        self._set_quote_state(index, "loading")
        self._start_quote_snapshot(index, exchange_name, pair)

        stream = None
        streams = getattr(column, "quote_streams", None)
        if isinstance(streams, dict):
            stream = streams.get(exchange_type)
        if stream is None:
            stream = column.quote_stream
        if stream is not None:
            stream.start(pair, testnet=bool(getattr(exchange, "testnet", False)))

    def _start_quote_snapshot(self, index, exchange_name, pair):
        worker = Worker(self._fetch_quote_snapshot_task, exchange_name, pair)

        column = self._column(index)
        if column is None:
            return
        column.quote_snapshot_worker = worker

        worker.signals.result.connect(
            lambda result, idx=index, name=exchange_name, sym=pair: self._on_quote_snapshot_result(
                idx, name, sym, result
            )
        )
        worker.signals.finished.connect(lambda idx=index: self._clear_quote_snapshot_worker(idx))
        ThreadManager().start(worker)

    def _clear_quote_snapshot_worker(self, index):
        column = self._column(index)
        if column is not None:
            column.quote_snapshot_worker = None

    def _fetch_quote_snapshot_task(self, exchange_name, pair):
        return self._runtime_service.fetch_quote_snapshot(exchange_name, pair)

    def _on_quote_snapshot_result(self, index, exchange_name, pair, result):
        column = self._column(index)
        if column is None:
            return

        current = column.quote_stream_state
        if current is None:
            return
        if current[0] != exchange_name or current[1] != pair:
            return
        if not isinstance(result, dict):
            return

        bid = self._to_float(result.get("bid"))
        ask = self._to_float(result.get("ask"))
        bid_qty = self._to_float(result.get("bid_qty"))
        ask_qty = self._to_float(result.get("ask_qty"))
        if bid is None or ask is None:
            return
        self._set_quote_state(index, "live", bid=bid, ask=ask, bid_qty=bid_qty, ask_qty=ask_qty)

    def _on_quote_tick(self, index, payload):
        column = self._column(index)
        if column is None or not isinstance(payload, dict):
            return

        current = column.quote_stream_state
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

        bid = self._to_float(payload.get("bid"))
        ask = self._to_float(payload.get("ask"))
        bid_qty = self._to_float(payload.get("bid_qty"))
        ask_qty = self._to_float(payload.get("ask_qty"))
        if bid is None or ask is None:
            return

        self._set_quote_state(index, "live", bid=bid, ask=ask, bid_qty=bid_qty, ask_qty=ask_qty)

    def _on_quote_stream_error(self, index):
        column = self._column(index)
        if column is None:
            return

        if column.quote_stream_state is None:
            return
        if column.quote_state != "live":
            self._set_quote_state(index, "loading")
