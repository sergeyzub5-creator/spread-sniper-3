from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.exchange.catalog import EXCHANGE_ORDER, get_exchange_meta, normalize_exchange_code
from core.i18n import tr
from core.utils.thread_pool import ThreadManager, Worker
from ui.styles import button_style, theme_color
from ui.widgets.exchange_badge import build_exchange_icon
from ui.widgets.exchange_panel import ExchangePanel


class ExchangePickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_code = None
        self.setWindowTitle(tr("exchange_picker.title"))
        self.setMinimumSize(500, 420)
        self.resize(540, 460)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {theme_color('surface')};
                color: {theme_color('text_primary')};
            }}
            QLabel {{
                color: {theme_color('text_primary')};
                font-size: 14px;
                font-weight: bold;
            }}
            QListWidget {{
                background-color: {theme_color('window_bg')};
                border: 1px solid {theme_color('border')};
                border-radius: 6px;
                padding: 6px;
                color: {theme_color('text_primary')};
                font-size: 13px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-radius: 4px;
            }}
            QListWidget::item:hover {{
                background-color: {theme_color('surface_alt')};
            }}
            QListWidget::item:selected {{
                background-color: {theme_color('selection_bg_soft')};
                color: {theme_color('accent')};
            }}
            QPushButton {{
                border-radius: 4px;
                padding: 7px 14px;
                min-width: 110px;
            }}
            QPushButton:disabled {{
                color: {theme_color('text_muted')};
                border-color: {theme_color('border')};
                background-color: {theme_color('surface_alt')};
            }}
        """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel(tr("exchange_picker.prompt"))
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(31, 31))
        self.list_widget.setSpacing(4)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept_selected())

        for code in EXCHANGE_ORDER:
            meta = get_exchange_meta(code)
            item = QListWidgetItem(build_exchange_icon(code, size=31), meta["title"])
            item.setData(Qt.ItemDataRole.UserRole, code)
            self.list_widget.addItem(item)

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        layout.addWidget(self.list_widget)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch()

        self.add_btn = QPushButton(tr("action.add"))
        self.add_btn.clicked.connect(self._accept_selected)
        self.add_btn.setStyleSheet(button_style("primary", padding="7px 14px", bold=True))
        self.add_btn.setEnabled(self.list_widget.currentItem() is not None)
        buttons_row.addWidget(self.add_btn)

        self.cancel_btn = QPushButton(tr("action.cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setStyleSheet(button_style("secondary", padding="7px 14px"))
        buttons_row.addWidget(self.cancel_btn)

        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        layout.addLayout(buttons_row)

    def _on_current_item_changed(self, current, _previous):
        if not hasattr(self, "add_btn"):
            return
        self.add_btn.setEnabled(current is not None)

    def _accept_selected(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_code = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def selected_exchange_code(self):
        return self.selected_code


class NewExchangeDialog(QDialog):
    def __init__(self, exchange_type, parent=None):
        super().__init__(parent)
        meta = get_exchange_meta(exchange_type)
        self.setWindowTitle(tr("exchanges.new_connection_title", title=meta["title"]))
        self.setMinimumSize(900, 320)
        self.resize(980, 360)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {theme_color('window_bg')};
                color: {theme_color('text_primary')};
            }}
        """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.panel = ExchangePanel(tr("exchanges.new_connection_name"), exchange_type, is_new=True)
        layout.addWidget(self.panel)


class ExchangesTab(QWidget):
    exchange_added = Signal(str, str, dict)
    exchange_removed = Signal(str)

    def __init__(self, exchange_manager, parent=None):
        super().__init__(parent)
        self.exchange_manager = exchange_manager
        self.exchange_panels = {}

        self.new_panel = None
        self.new_panel_exchange_type = None
        self.new_panel_exchange_name = None
        self.new_exchange_dialog = None
        self.close_positions_worker = None
        self.single_close_worker = None
        self.single_close_name = None

        self._init_ui()

        self.exchange_manager.exchange_added.connect(self._on_exchange_added)
        self.exchange_manager.exchange_removed.connect(self._on_exchange_removed)
        self.exchange_manager.status_updated.connect(self._update_all_status)

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.add_btn = QPushButton(tr("exchanges.add_exchange"))
        self.add_btn.setMinimumWidth(140)
        self.add_btn.setStyleSheet(button_style("primary", padding="6px 12px", bold=True))
        self.add_btn.clicked.connect(self._add_new_panel)

        controls.addWidget(self.add_btn)
        controls.addStretch()

        connect_buttons = QHBoxLayout()
        connect_buttons.setSpacing(5)

        self.connect_all_btn = QPushButton(tr("exchanges.connect_all"))
        self.connect_all_btn.setMinimumWidth(130)
        self.connect_all_btn.setStyleSheet(button_style("success", padding="6px 12px"))
        self.connect_all_btn.clicked.connect(self._connect_all)

        self.disconnect_all_btn = QPushButton(tr("exchanges.disconnect_all"))
        self.disconnect_all_btn.setMinimumWidth(130)
        self.disconnect_all_btn.setStyleSheet(button_style("danger", padding="6px 12px"))
        self.disconnect_all_btn.clicked.connect(self._disconnect_all)

        self.close_all_positions_btn = QPushButton("⚠ Закрыть все позиции")
        self.close_all_positions_btn.setMinimumWidth(170)
        self.close_all_positions_btn.setStyleSheet(button_style("warning", padding="6px 12px", bold=True))
        self.close_all_positions_btn.clicked.connect(self._close_all_positions)

        connect_buttons.addWidget(self.connect_all_btn)
        connect_buttons.addWidget(self.disconnect_all_btn)
        connect_buttons.addWidget(self.close_all_positions_btn)
        controls.addLayout(connect_buttons)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._apply_scroll_style()

        self.container = QWidget()
        self.panels_layout = QVBoxLayout(self.container)
        self.panels_layout.setContentsMargins(2, 2, 2, 2)
        self.panels_layout.setSpacing(2)
        self.panels_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.container)

        layout.addLayout(controls)
        layout.addWidget(self.scroll)
        self.setLayout(layout)

        self._load_existing()

    def _apply_scroll_style(self):
        if hasattr(self, "scroll"):
            self.scroll.setStyleSheet(
                f"QScrollArea {{ border: 1px solid {theme_color('border')}; border-radius: 4px; "
                f"background-color: {theme_color('scroll_bg')}; }}"
            )

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
            status = {
                "connected": exchange.is_connected,
                "loading": False,
                "testnet": exchange.testnet,
                "balance": exchange.balance,
                "positions_count": len(exchange.positions),
                "pnl": exchange.pnl,
                "status_text": exchange.get_status_text(),
            }
        panel.update_status(status)
        panel.apply_theme()
        panel.retranslate_ui()

        self.panels_layout.addWidget(panel)
        self.exchange_panels[name] = panel

    def apply_theme(self):
        self.add_btn.setStyleSheet(button_style("primary", padding="6px 12px", bold=True))
        self.connect_all_btn.setStyleSheet(button_style("success", padding="6px 12px"))
        self.disconnect_all_btn.setStyleSheet(button_style("danger", padding="6px 12px"))
        self.close_all_positions_btn.setStyleSheet(button_style("warning", padding="6px 12px", bold=True))
        self._apply_scroll_style()

        for panel in self.exchange_panels.values():
            panel.apply_theme()

        if self.new_panel is not None:
            self.new_panel.apply_theme()

        if self.new_exchange_dialog is not None:
            self.new_exchange_dialog.setStyleSheet(
                f"""
                QDialog {{
                    background-color: {theme_color('window_bg')};
                    color: {theme_color('text_primary')};
                }}
            """
            )

    def retranslate_ui(self):
        self.add_btn.setText(tr("exchanges.add_exchange"))
        self.connect_all_btn.setText(tr("exchanges.connect_all"))
        self.disconnect_all_btn.setText(tr("exchanges.disconnect_all"))
        self.close_all_positions_btn.setText("⚠ Закрыть все позиции")

        for panel in self.exchange_panels.values():
            panel.retranslate_ui()

        if self.new_panel is not None:
            self.new_panel.retranslate_ui()

        if self.new_exchange_dialog is not None:
            meta = get_exchange_meta(self.new_panel_exchange_type)
            self.new_exchange_dialog.setWindowTitle(
                tr("exchanges.new_connection_title", title=meta["title"])
            )

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
        reply = QMessageBox.question(
            self,
            tr("exchanges.confirm_title"),
            tr("exchanges.confirm_remove", name=display_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
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
            ok_btn.setText("ОК")
        box.exec()

    def _show_warning_dialog(self, title, text):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        ok_btn = box.button(QMessageBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("ОК")
        box.exec()

    def _show_wide_report_dialog(self, title, text, warning=False):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        ok_btn = box.button(QMessageBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("ОК")
        # Делаем окно отчета еще уже по ширине (еще в 2 раза).
        box.setStyleSheet("QLabel { min-width: 190px; }")
        box.exec()

    def _confirm_close_all_positions(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Подтверждение")
        box.setText("Закрыть все открытые позиции на всех подключенных биржах?")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        yes_btn = box.button(QMessageBox.StandardButton.Yes)
        no_btn = box.button(QMessageBox.StandardButton.No)
        if yes_btn is not None:
            yes_btn.setText("Да")
        if no_btn is not None:
            no_btn.setText("Отмена")
        return box.exec() == int(QMessageBox.StandardButton.Yes)

    def _close_all_positions(self):
        if self.single_close_worker is not None:
            self._show_warning_dialog("Закрытие позиций", "Дождитесь завершения текущего закрытия позиций.")
            return

        connected = self.exchange_manager.get_connected_names()
        if not connected:
            self._show_info_dialog("Закрытие позиций", "Нет подключенных бирж для закрытия позиций.")
            return

        if not self._confirm_close_all_positions():
            return

        self._set_bulk_controls_enabled(False)
        self.close_all_positions_btn.setText("Закрытие...")

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
            f"Закрыто позиций: {closed_positions}",
            f"Успешно по биржам: {len(ok)}",
            f"С ошибками: {len(failed) + len(unsupported)}",
        ]

        all_errors = {}
        all_errors.update(failed)
        all_errors.update(unsupported)
        if all_errors:
            details = "\n".join(f"- {name}: {msg}" for name, msg in sorted(all_errors.items()))
            lines.append("")
            lines.append("Ошибки:")
            lines.append(details)

        msg = "\n".join(lines)
        if all_errors:
            self._show_wide_report_dialog("Закрытие позиций", msg, warning=True)
        else:
            self._show_wide_report_dialog("Закрытие позиций", msg, warning=False)

    def _on_close_all_positions_error(self, error_text):
        self._show_warning_dialog("Закрытие позиций", f"Ошибка закрытия позиций: {error_text}")

    def _on_close_all_positions_finished(self):
        self.close_positions_worker = None
        self._set_bulk_controls_enabled(True)
        self.close_all_positions_btn.setText("⚠ Закрыть все позиции")

    def _on_panel_close_positions(self, name):
        if self.close_positions_worker is not None:
            self._show_warning_dialog("Закрытие позиций", "Сначала завершите закрытие позиций по всем биржам.")
            return
        if self.single_close_worker is not None:
            self._show_warning_dialog("Закрытие позиций", "Уже выполняется закрытие позиций по другой бирже.")
            return

        exchange = self.exchange_manager.get_exchange(name)
        if exchange is None or not exchange.is_connected:
            self._show_warning_dialog("Закрытие позиций", "Биржа не подключена.")
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Подтверждение")
        box.setText(f"Закрыть все открытые позиции на бирже {name}?")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        yes_btn = box.button(QMessageBox.StandardButton.Yes)
        no_btn = box.button(QMessageBox.StandardButton.No)
        if yes_btn is not None:
            yes_btn.setText("Да")
        if no_btn is not None:
            no_btn.setText("Отмена")
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
        self._show_info_dialog("Закрытие позиций", f"Биржа {name}: закрыто позиций {closed_positions}.")

    def _on_single_close_error(self, error_text):
        self._show_warning_dialog("Закрытие позиций", f"Ошибка закрытия позиций: {error_text}")

    def _on_single_close_finished(self):
        if self.single_close_name:
            self._set_panel_close_enabled(self.single_close_name, True)
        self.single_close_worker = None
        self.single_close_name = None
