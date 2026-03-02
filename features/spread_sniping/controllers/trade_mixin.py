from core.exchange.catalog import normalize_exchange_code
from core.i18n import tr
from core.utils.thread_pool import ThreadManager, Worker


class SpreadTradeMixin:
    # ВРЕМЕННЫЙ ТЕСТОВЫЙ БЛОК: ручное открытие минимальной позиции для проверки стакана.
    # Планово будет удален после завершения проверки механики bookTicker/стакана.
    def _refresh_trade_texts(self):
        for column in self._iter_columns():
            if column.trade_note_label is not None:
                column.trade_note_label.setText(tr("spread.temp_trade_note"))
            if column.trade_buy_button is not None:
                column.trade_buy_button.setText(tr("spread.trade_buy"))
            if column.trade_sell_button is not None:
                column.trade_sell_button.setText(tr("spread.trade_sell"))

            state = column.trade_status_state
            if state:
                key, kwargs = state
                self._apply_trade_status(column.index, key, **kwargs)

    def _set_trade_status(self, index, key=None, **kwargs):
        column = self._column(index)
        if column is None:
            return

        if key is None:
            column.trade_status_state = None
            if column.trade_status_label is not None:
                column.trade_status_label.setText("")
            return

        column.trade_status_state = (key, dict(kwargs))
        self._apply_trade_status(index, key, **kwargs)

    def _apply_trade_status(self, index, key, **kwargs):
        column = self._column(index)
        if column is None or column.trade_status_label is None:
            return
        column.trade_status_label.setText(tr(key, **kwargs))

    def _refresh_trade_controls(self):
        for column in self._iter_columns():
            self._refresh_trade_control(column.index)

    def _refresh_trade_control(self, index):
        column = self._column(index)
        if column is None:
            return

        frame = column.trade_frame
        buy_btn = column.trade_buy_button
        sell_btn = column.trade_sell_button
        if frame is None or buy_btn is None or sell_btn is None:
            return

        exchange_name = column.selected_exchange
        pair = column.selected_pair
        exchange = self.exchange_manager.get_exchange(exchange_name) if exchange_name else None
        exchange_type = normalize_exchange_code(getattr(exchange, "exchange_type", None)) if exchange else ""
        can_show = bool(exchange_name and pair and exchange and exchange.is_connected and exchange_type == "binance")

        frame.setVisible(can_show)
        if not can_show:
            self._set_trade_status(index, None)
            return

        buy_btn.setEnabled(not column.trade_busy)
        sell_btn.setEnabled(not column.trade_busy)

        if column.trade_busy:
            self._set_trade_status(index, "spread.trade_opening")
        elif column.trade_status_state is None:
            self._set_trade_status(index, "spread.trade_ready")

    def _on_temp_trade_clicked(self, index, side):
        column = self._column(index)
        if column is None:
            return

        if column.trade_busy:
            return

        exchange_name = column.selected_exchange
        pair = column.selected_pair
        if not exchange_name or not pair:
            self._set_trade_status(index, "spread.trade_select_pair_first")
            return

        exchange = self.exchange_manager.get_exchange(exchange_name)
        if exchange is None or not exchange.is_connected:
            self._set_trade_status(index, "spread.trade_exchange_not_connected")
            return

        exchange_type = normalize_exchange_code(getattr(exchange, "exchange_type", None))
        if exchange_type != "binance":
            self._set_trade_status(index, "spread.trade_binance_only")
            return

        column.trade_busy = True
        self._refresh_trade_control(index)
        self._set_trade_status(index, "spread.trade_opening")

        worker = Worker(self._open_temp_trade_task, exchange_name, pair, side)
        column.trade_worker = worker
        worker.signals.result.connect(lambda result, idx=index, s=side: self._on_temp_trade_result(idx, s, result))
        worker.signals.error.connect(lambda err, idx=index: self._on_temp_trade_error(idx, err))
        worker.signals.finished.connect(lambda idx=index: self._on_temp_trade_finished(idx))
        ThreadManager().start(worker)

    def _open_temp_trade_task(self, exchange_name, pair, side):
        try:
            return self._runtime_service.open_min_test_position(exchange_name, pair, side)
        except RuntimeError as exc:
            err = str(exc or "").strip().lower()
            if err == "exchange_not_connected":
                raise RuntimeError(tr("spread.trade_exchange_not_connected")) from exc
            if err == "unsupported":
                raise RuntimeError(tr("spread.trade_unsupported")) from exc
            raise

    def _on_temp_trade_result(self, index, side, result):
        column = self._column(index)
        if column is None:
            return

        side_key = "spread.side.buy" if str(side).lower() == "buy" else "spread.side.sell"
        side_title = tr(side_key)

        symbol = column.selected_pair or ""
        quantity = "--"
        status = ""
        if isinstance(result, dict):
            symbol = self._normalize_pair(result.get("symbol") or symbol)
            quantity = str(
                result.get("executed_qty")
                or result.get("executedQty")
                or result.get("quantity")
                or result.get("qty")
                or quantity
            )
            status = str(result.get("status") or "").strip().upper()

        qty_view = f"{quantity} | {status}" if status else quantity

        self._set_trade_status(
            index,
            "spread.trade_opened",
            side=side_title,
            symbol=symbol,
            qty=qty_view,
        )
        set_own_order = getattr(self, "_set_own_order_from_trade_result", None)
        if callable(set_own_order):
            set_own_order(index, side, result)

        exchange_name = column.selected_exchange
        exchange = self.exchange_manager.get_exchange(exchange_name) if exchange_name else None
        if exchange is not None and exchange.is_connected:
            try:
                exchange.api_request_async(exchange.refresh_state)
            except Exception:
                pass

    def _on_temp_trade_error(self, index, error_text):
        self._set_trade_status(index, "spread.trade_failed", error=str(error_text or "").strip())

    def _on_temp_trade_finished(self, index):
        column = self._column(index)
        if column is None:
            return

        column.trade_worker = None
        column.trade_busy = False
        self._refresh_trade_control(index)
