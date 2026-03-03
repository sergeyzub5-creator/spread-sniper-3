from PySide6.QtWidgets import QMessageBox

from core.i18n import tr
from core.utils.thread_pool import ThreadManager, Worker


class ExchangesClosePositionsMixin:
    def _set_panel_close_enabled(self, name, enabled):
        panel = self.exchange_panels.get(name)
        if panel is not None:
            panel.close_positions_btn.setEnabled(enabled)

    def _set_bulk_controls_enabled(self, enabled):
        self.connect_all_btn.setEnabled(enabled)
        self.disconnect_all_btn.setEnabled(enabled)
        self.close_all_positions_btn.setEnabled(enabled)

    def _show_info_dialog(self, title, text):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        ok_btn = box.button(QMessageBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(tr("action.ok"))
        box.exec()

    def _show_warning_dialog(self, title, text):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        ok_btn = box.button(QMessageBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(tr("action.ok"))
        box.exec()

    def _show_wide_report_dialog(self, title, text, warning=False):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        ok_btn = box.button(QMessageBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(tr("action.ok"))
        box.setStyleSheet("QLabel { min-width: 190px; }")
        box.exec()

    def _confirm_close_all_positions(self):
        if self.fast_trade_mode:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("exchanges.confirm_title"))
        box.setText(tr("exchanges.close_positions.confirm_all"))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        yes_btn = box.button(QMessageBox.StandardButton.Yes)
        no_btn = box.button(QMessageBox.StandardButton.No)
        if yes_btn is not None:
            yes_btn.setText(tr("action.yes"))
        if no_btn is not None:
            no_btn.setText(tr("action.no"))
        return box.exec() == int(QMessageBox.StandardButton.Yes)

    def _close_all_positions(self):
        if self.single_close_worker is not None:
            self._show_warning_dialog(
                tr("exchanges.close_positions.title"),
                tr("exchanges.close_positions.wait_bulk"),
            )
            return

        connected = self.exchange_manager.get_connected_names()
        if not connected:
            self._show_info_dialog(
                tr("exchanges.close_positions.title"),
                tr("exchanges.close_positions.no_connected"),
            )
            return

        if not self._confirm_close_all_positions():
            return

        self._set_bulk_controls_enabled(False)
        self.close_all_positions_btn.setText(tr("action.closing"))

        worker = Worker(self.exchange_manager.close_all_positions)
        self.close_positions_worker = worker
        worker.signals.result.connect(self._on_close_all_positions_result)
        worker.signals.error.connect(self._on_close_all_positions_error)
        worker.signals.finished.connect(self._on_close_all_positions_finished)
        ThreadManager().start(worker)

    def _on_close_all_positions_result(self, summary):
        summary = summary or {}
        ok = summary.get("ok", [])
        failed = summary.get("failed", {})
        unsupported = summary.get("unsupported", {})
        closed_positions = int(summary.get("closed_positions", 0) or 0)

        lines = [
            tr("exchanges.close_positions.summary.closed", count=closed_positions),
            tr("exchanges.close_positions.summary.ok", count=len(ok)),
            tr("exchanges.close_positions.summary.failed", count=len(failed) + len(unsupported)),
        ]

        all_errors = {}
        all_errors.update(failed)
        all_errors.update(unsupported)
        if all_errors:
            details = "\n".join(f"- {name}: {msg}" for name, msg in sorted(all_errors.items()))
            lines.append("")
            lines.append(tr("exchanges.close_positions.summary.errors"))
            lines.append(details)

        msg = "\n".join(lines)
        if all_errors:
            self._show_wide_report_dialog(tr("exchanges.close_positions.title"), msg, warning=True)
        else:
            self._show_wide_report_dialog(tr("exchanges.close_positions.title"), msg, warning=False)

    def _on_close_all_positions_error(self, error_text):
        self._show_warning_dialog(
            tr("exchanges.close_positions.title"),
            tr("exchanges.close_positions.error", error=error_text),
        )

    def _on_close_all_positions_finished(self):
        self.close_positions_worker = None
        self._set_bulk_controls_enabled(True)
        self.close_all_positions_btn.setText(f"\u26A0 {tr('action.close_all_positions')}")

    def _on_panel_close_positions(self, name):
        if self.close_positions_worker is not None:
            self._show_warning_dialog(
                tr("exchanges.close_positions.title"),
                tr("exchanges.close_positions.wait_single"),
            )
            return
        if self.single_close_worker is not None:
            self._show_warning_dialog(
                tr("exchanges.close_positions.title"),
                tr("exchanges.close_positions.busy_single"),
            )
            return

        exchange = self.exchange_manager.get_exchange(name)
        if exchange is None or not exchange.is_connected:
            self._show_warning_dialog(
                tr("exchanges.close_positions.title"),
                tr("exchanges.close_positions.exchange_not_connected"),
            )
            return

        if not self.fast_trade_mode:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(tr("exchanges.confirm_title"))
            box.setText(tr("exchanges.close_positions.confirm_single", name=name))
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            yes_btn = box.button(QMessageBox.StandardButton.Yes)
            no_btn = box.button(QMessageBox.StandardButton.No)
            if yes_btn is not None:
                yes_btn.setText(tr("action.yes"))
            if no_btn is not None:
                no_btn.setText(tr("action.no"))
            if box.exec() != int(QMessageBox.StandardButton.Yes):
                return

        self.single_close_name = name
        self._set_panel_close_enabled(name, False)
        worker = Worker(lambda: self.exchange_manager.close_positions_for_exchange(name))
        self.single_close_worker = worker
        worker.signals.result.connect(self._on_single_close_result)
        worker.signals.error.connect(self._on_single_close_error)
        worker.signals.finished.connect(self._on_single_close_finished)
        ThreadManager().start(worker)

    def _on_single_close_result(self, result):
        result = result or {}
        name = result.get("name", self.single_close_name or "")
        closed_positions = int(result.get("closed_positions", 0) or 0)
        self._show_info_dialog(
            tr("exchanges.close_positions.title"),
            tr("exchanges.close_positions.single_result", name=name, count=closed_positions),
        )

    def _on_single_close_error(self, error_text):
        self._show_warning_dialog(
            tr("exchanges.close_positions.title"),
            tr("exchanges.close_positions.error", error=error_text),
        )

    def _on_single_close_finished(self):
        if self.single_close_name:
            self._set_panel_close_enabled(self.single_close_name, True)
        self.single_close_worker = None
        self.single_close_name = None

