from PySide6.QtWidgets import QDialog, QMessageBox

from core.exchange.catalog import get_exchange_meta, normalize_exchange_code
from core.i18n import tr
from features.exchanges.dialogs import ExchangePickerDialog, NewExchangeDialog
from ui.widgets.exchange_panel import ExchangePanel


class ExchangesPanelsMixin:
    def _load_existing(self):
        statuses = self.exchange_manager.get_all_status()
        for name, exchange in self.exchange_manager.get_all_exchanges().items():
            self._create_panel(name, exchange, statuses.get(name))

    def _create_panel(self, name, exchange, status=None):
        exchange_type = normalize_exchange_code(getattr(exchange, "exchange_type", None))

        panel = ExchangePanel(name, exchange_type, is_new=False)
        panel.connect_clicked.connect(self._on_panel_connect)
        panel.disconnect_clicked.connect(self._on_panel_disconnect)
        panel.close_positions_clicked.connect(self._on_panel_close_positions)
        panel.remove_clicked.connect(self._on_panel_remove)

        params = {
            "api_key": exchange.api_key,
            "api_secret": exchange.api_secret,
            "testnet": exchange.testnet,
        }
        if hasattr(exchange, "api_passphrase") and exchange.api_passphrase:
            params["api_passphrase"] = exchange.api_passphrase

        panel.load_saved_data(params)

        if status is None:
            long_count, short_count = self.exchange_manager._count_position_directions(exchange.positions)
            status = {
                "connected": exchange.is_connected,
                "loading": False,
                "testnet": exchange.testnet,
                "balance": exchange.balance,
                "positions_count": len(exchange.positions),
                "long_positions": long_count,
                "short_positions": short_count,
                "pnl": exchange.pnl,
                "status_text": exchange.get_status_text(),
            }
        panel.update_status(status)
        panel.apply_theme()
        panel.retranslate_ui()

        self.panels_layout.addWidget(panel)
        self.exchange_panels[name] = panel

    def _clear_new_panel_state(self):
        self.new_panel = None
        self.new_panel_exchange_type = None
        self.new_panel_exchange_name = None
        self.new_exchange_dialog = None

    def _on_new_dialog_closed(self):
        self._clear_new_panel_state()

    def _add_new_panel(self):
        if self.new_panel is not None and self.new_exchange_dialog is not None:
            self.new_exchange_dialog.raise_()
            self.new_exchange_dialog.activateWindow()
            return

        picker = ExchangePickerDialog(self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return

        exchange_type = picker.selected_exchange_code()
        if not exchange_type:
            return

        dialog = NewExchangeDialog(exchange_type, self)
        panel = dialog.panel
        panel.connect_clicked.connect(self._on_new_panel_connect)
        panel.cancel_clicked.connect(self._cancel_new_panel)
        dialog.finished.connect(lambda _code: self._on_new_dialog_closed())

        self.new_exchange_dialog = dialog
        self.new_panel = panel
        self.new_panel_exchange_type = exchange_type
        self.new_panel_exchange_name = None

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _cancel_new_panel(self):
        dialog = self.new_exchange_dialog
        self._clear_new_panel_state()
        if dialog is not None:
            dialog.close()

    def set_new_panel_error(self, message):
        if self.new_panel is None:
            return
        self.new_panel.connect_btn.setEnabled(True)
        self.new_panel.show_status_message(message, "danger", "danger", emphasize=True)
        if self.new_exchange_dialog is not None:
            self.new_exchange_dialog.raise_()
            self.new_exchange_dialog.activateWindow()

    def _on_new_panel_connect(self, _name, params):
        if self.new_panel is not None:
            self.new_panel.connect_btn.setEnabled(False)

        selected_type = self.new_panel_exchange_type
        if not selected_type and self.new_panel is not None:
            selected_type = self.new_panel.exchange_type
        type_code = normalize_exchange_code(selected_type)

        base_name = get_exchange_meta(type_code)["base_name"]
        final_name = base_name
        counter = 1
        while final_name in self.exchange_panels:
            final_name = f"{base_name}{counter}"
            counter += 1

        self.new_panel_exchange_name = final_name
        if self.new_panel is not None:
            self.new_panel.exchange_name = final_name
            self.new_panel.show_status_message(tr("status.loading"), "warning", "warning")

        self.exchange_added.emit(final_name, type_code, params)

    def _on_panel_connect(self, name, params):
        panel = self.sender()
        if not panel:
            return
        if self.exchange_manager.is_exchange_loading(name):
            panel.show_status_message(tr("status.loading"), "warning", "warning")
            panel.connect_btn.setEnabled(False)
            return
        panel.connect_btn.setEnabled(False)
        self.exchange_added.emit(name, panel.exchange_type, params)

    def _on_panel_disconnect(self, name):
        self.exchange_manager.disconnect_exchange(name, manual=True)

    def _on_panel_remove(self, name):
        panel = self.exchange_panels.get(name)
        display_name = name
        if panel:
            meta = get_exchange_meta(panel.exchange_type)
            display_name = f"{meta['base_name']} ({name})"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("exchanges.confirm_title"))
        box.setText(tr("exchanges.confirm_remove", name=display_name))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        yes_btn = box.button(QMessageBox.StandardButton.Yes)
        no_btn = box.button(QMessageBox.StandardButton.No)
        if yes_btn is not None:
            yes_btn.setText(tr("action.yes"))
        if no_btn is not None:
            no_btn.setText(tr("action.no"))
        if box.exec() == int(QMessageBox.StandardButton.Yes):
            self.exchange_removed.emit(name)

    def _on_exchange_added(self, name):
        exchange = self.exchange_manager.get_exchange(name)
        if exchange and name not in self.exchange_panels:
            status = self.exchange_manager.get_all_status().get(name)
            self._create_panel(name, exchange, status=status)

        if self.new_panel_exchange_name == name:
            self._cancel_new_panel()

    def _on_exchange_removed(self, name):
        if name in self.exchange_panels:
            panel = self.exchange_panels[name]
            panel.hide()
            self.panels_layout.removeWidget(panel)
            panel.deleteLater()
            del self.exchange_panels[name]

    def _update_all_status(self, statuses):
        for name, status in statuses.items():
            if name in self.exchange_panels:
                self.exchange_panels[name].update_status(status)

    def _connect_all(self):
        self.exchange_manager.connect_all_async()

    def _disconnect_all(self):
        self.exchange_manager.disconnect_all(manual=True)

