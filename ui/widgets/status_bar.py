from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel
from PySide6.QtCore import QTimer, Qt
from datetime import datetime
import socket

class NetworkStatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setStyleSheet('''
            QFrame {
                background-color: #0a0c10;
                border-top: 2px solid #2a343c;
                padding: 4px 10px;
            }
            QLabel {
                color: #a0b0c0;
                font-size: 13px;
            }
        ''')
        
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 4, 10, 4)
        
        self.wifi_label = QLabel("🌐 Online")
        self.wifi_label.setStyleSheet("color: #7ec8a6;")
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
        
        self.timer = QTimer()
        self.timer.timeout.connect(self._update)
        self.timer.start(1000)
        self._update()
    
    def _update(self):
        self.time_label.setText(datetime.now().strftime("%H:%M:%S"))
        online = self._is_online()
        if online:
            self.wifi_label.setText("🌐 Online")
            self.wifi_label.setStyleSheet("color: #7ec8a6;")
        else:
            self.wifi_label.setText("⚠️ No Internet")
            self.wifi_label.setStyleSheet("color: #e06c75;")
    
    def _is_online(self):
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False
    
    def show_error(self, message):
        self.error_label.setText(f"⚠️ {message}")
        self.error_label.show()
        QTimer.singleShot(5000, self.error_label.hide)
