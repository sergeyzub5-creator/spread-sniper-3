import socket
from datetime import datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from core.utils.thread_pool import ThreadManager, Worker


class NetworkStatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._online = None
        self._check_in_progress = False

        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            """
            QFrame {
                background-color: #0a0c10;
                border-top: 2px solid #2a343c;
                padding: 4px 10px;
            }
            QLabel {
                color: #a0b0c0;
                font-size: 13px;
            }
        """
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        self.net_indicator = QLabel("")
        self.net_indicator.setFixedSize(10, 10)
        self.net_indicator.setStyleSheet(
            "background-color: #a0b0c0; border: 1px solid #5a6570; border-radius: 5px;"
        )
        layout.addWidget(self.net_indicator)

        self.wifi_label = QLabel("Сеть: проверка...")
        self.wifi_label.setStyleSheet("color: #a0b0c0;")
        layout.addWidget(self.wifi_label)

        layout.addStretch()

        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.time_label)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #e06c75;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.setLayout(layout)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)
        self._update_clock()

        self.network_timer = QTimer(self)
        self.network_timer.timeout.connect(self._trigger_network_check)
        self.network_timer.start(5000)

        self._trigger_network_check()

    def _update_clock(self):
        self.time_label.setText(datetime.now().strftime("%H:%M:%S"))

    @staticmethod
    def _is_online():
        try:
            with socket.create_connection(("8.8.8.8", 53), timeout=1.0):
                return True
        except OSError:
            return False

    def _trigger_network_check(self):
        if self._check_in_progress:
            return
        self._check_in_progress = True

        worker = Worker(self._is_online)
        worker.signals.result.connect(self._on_network_result)
        worker.signals.error.connect(lambda _err: self._on_network_result(False))
        ThreadManager().start(worker)

    def _on_network_result(self, online):
        self._check_in_progress = False
        online = bool(online)
        if self._online is online:
            return

        self._online = online
        if online:
            self.net_indicator.setStyleSheet(
                "background-color: #22c55e; border: 1px solid #15803d; border-radius: 5px;"
            )
            self.wifi_label.setText("Сеть: онлайн")
            self.wifi_label.setStyleSheet("color: #7ec8a6;")
        else:
            self.net_indicator.setStyleSheet(
                "background-color: #ef4444; border: 1px solid #b91c1c; border-radius: 5px;"
            )
            self.wifi_label.setText("Сеть: офлайн")
            self.wifi_label.setStyleSheet("color: #e06c75;")

    def show_error(self, message):
        self.error_label.setText(f"Внимание: {message}")
        self.error_label.show()
        QTimer.singleShot(5000, self.error_label.hide)
