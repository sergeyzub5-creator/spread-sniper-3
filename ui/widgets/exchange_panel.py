from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QCheckBox, QGroupBox)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

class ExchangePanel(QFrame):
    connect_clicked = Signal(str, dict)
    disconnect_clicked = Signal(str)
    remove_clicked = Signal(str)
    cancel_clicked = Signal()
    
    def __init__(self, exchange_name, exchange_type, is_new=False, parent=None):
        super().__init__(parent)
        self.exchange_name = exchange_name
        self.exchange_type = exchange_type
        self.is_connected = False
        self.testnet = False
        self.is_new = is_new
        self.edit_mode = is_new
        
        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setStyleSheet("""
            QFrame {
                border: 1px solid #2a343c;
                border-radius: 4px;
                background-color: #14181c;
                margin: 2px;
                padding: 8px;
            }
        """)
        
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        
        header = QHBoxLayout()
        self.name_label = QLabel(self.exchange_name)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setMinimumWidth(80)
        
        self.status_label = QLabel("⭕ Не подключено")
        self.status_label.setStyleSheet("color: #a0b0c0; font-size: 11px;")
        self.status_label.setMinimumWidth(100)
        
        header.addWidget(self.name_label)
        header.addWidget(self.status_label)
        header.addStretch()
        layout.addLayout(header)
        
        stats_layout = QHBoxLayout()
        self.balance_label = QLabel("💰 Баланс: -- USDT")
        self.balance_label.setStyleSheet("color: #7ec8a6; font-size: 12px; font-weight: bold;")
        self.positions_label = QLabel("📊 Позиции: --")
        self.positions_label.setStyleSheet("color: #e5c07b; font-size: 12px;")
        stats_layout.addWidget(self.balance_label)
        stats_layout.addWidget(self.positions_label)
        stats_layout.addStretch()
        layout.addLayout(stats_layout)
        
        self.api_group = QGroupBox("API данные")
        api_layout = QHBoxLayout()
        api_layout.setSpacing(5)
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("API Key")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setMinimumWidth(180)
        
        self.api_secret_input = QLineEdit()
        self.api_secret_input.setPlaceholderText("API Secret")
        self.api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_secret_input.setMinimumWidth(180)
        
        self.passphrase_input = QLineEdit()
        self.passphrase_input.setPlaceholderText("Passphrase")
        self.passphrase_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.passphrase_input.setMinimumWidth(120)
        
        self.testnet_check = QCheckBox("Демо режим")
        self.testnet_check.setStyleSheet("color: #e5c07b;")
        self.testnet_check.stateChanged.connect(self._on_testnet_changed)
        
        api_layout.addWidget(self.api_key_input)
        api_layout.addWidget(self.api_secret_input)
        api_layout.addWidget(self.passphrase_input)
        api_layout.addWidget(self.testnet_check)
        api_layout.addStretch()
        
        self.api_group.setLayout(api_layout)
        layout.addWidget(self.api_group)
        
        button_layout = QHBoxLayout()
        button_layout.setSpacing(5)
        
        self.connect_btn = QPushButton("🔌 Подключить")
        self.connect_btn.setMinimumWidth(100)
        self.connect_btn.setStyleSheet("""
            QPushButton { background-color: #2a3a5a; color: #7aa2f7; border: 1px solid #7aa2f7; border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background-color: #3a4a7a; }
        """)
        self.connect_btn.clicked.connect(self._on_connect)
        
        self.disconnect_btn = QPushButton("🔌 Отключить")
        self.disconnect_btn.setMinimumWidth(100)
        self.disconnect_btn.setStyleSheet("""
            QPushButton { background-color: #5a2a2a; color: #e06c75; border: 1px solid #e06c75; border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background-color: #6a3a3a; }
        """)
        self.disconnect_btn.clicked.connect(lambda: self.disconnect_clicked.emit(self.exchange_name))
        
        self.edit_btn = QPushButton("✏️ Редактировать")
        self.edit_btn.setMinimumWidth(100)
        self.edit_btn.setStyleSheet("""
            QPushButton { background-color: #3a3a2a; color: #e5c07b; border: 1px solid #e5c07b; border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background-color: #5a5a3a; }
        """)
        self.edit_btn.clicked.connect(lambda: self.set_edit_mode(True))
        
        self.remove_btn = QPushButton("🗑️ Удалить")
        self.remove_btn.setMinimumWidth(100)
        self.remove_btn.setStyleSheet("""
            QPushButton { background-color: #2a343c; color: #a0b0c0; border: 1px solid #a0b0c0; border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background-color: #3a4a5a; }
        """)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.exchange_name))
        
        button_layout.addWidget(self.connect_btn)
        button_layout.addWidget(self.disconnect_btn)
        button_layout.addWidget(self.edit_btn)
        button_layout.addWidget(self.remove_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        self._update_passphrase_hint()
        self._update_ui_state()
    
    def _update_passphrase_hint(self):
        if self.exchange_type == 'Bitget':
            self.passphrase_input.setPlaceholderText("Passphrase (обязательно)")
        else:
            self.passphrase_input.setPlaceholderText("Passphrase (опционально)")
    
    def set_edit_mode(self, edit_mode):
        self.edit_mode = edit_mode
        self._update_ui_state()
    
    def _update_ui_state(self):
        if self.is_connected:
            self.status_label.setText("✅ Подключено")
            self.status_label.setStyleSheet("color: #7ec8a6; font-size: 11px;")
            self.connect_btn.setVisible(False)
            self.disconnect_btn.setVisible(True)
            self.edit_btn.setVisible(False)
            self.api_group.setVisible(False)
        else:
            self.status_label.setText("⭕ Не подключено")
            self.status_label.setStyleSheet("color: #a0b0c0; font-size: 11px;")
            self.balance_label.setText("💰 Баланс: -- USDT")
            self.positions_label.setText("📊 Позиции: --")
            
            if self.edit_mode:
                self.connect_btn.setText("💾 Сохранить" if self.is_new else "🔌 Подключить")
                self.connect_btn.setVisible(True)
                self.disconnect_btn.setVisible(False)
                self.edit_btn.setVisible(False)
                self.api_group.setVisible(True)
            else:
                self.connect_btn.setVisible(False)
                self.disconnect_btn.setVisible(False)
                self.edit_btn.setVisible(True)
                self.api_group.setVisible(False)
        
        self.remove_btn.setVisible(True)
    
    def _on_testnet_changed(self, state):
        self.testnet = (state == Qt.CheckState.Checked.value)
    
    def _on_connect(self):
        if not self.edit_mode:
            return
        
        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()
        
        if not api_key or not api_secret:
            self.status_label.setText("❌ API Key и Secret обязательны")
            self.status_label.setStyleSheet("color: #e06c75; font-size: 11px;")
            return
        
        params = {
            'api_key': api_key,
            'api_secret': api_secret,
            'testnet': self.testnet
        }
        
        if self.exchange_type == 'Bitget':
            passphrase = self.passphrase_input.text().strip()
            if not passphrase:
                self.status_label.setText("❌ Passphrase обязателен")
                self.status_label.setStyleSheet("color: #e06c75; font-size: 11px;")
                return
            params['api_passphrase'] = passphrase
        else:
            passphrase = self.passphrase_input.text().strip()
            if passphrase:
                params['api_passphrase'] = passphrase
        
        self.connect_clicked.emit(self.exchange_name, params)
    
    def update_status(self, status):
        self.is_connected = status.get('connected', False)
        
        if self.is_connected:
            mode = "📗 Демо" if status.get('testnet') else "📕 Реал"
            self.status_label.setText(f"✅ {mode}")
            self.status_label.setStyleSheet("color: #7ec8a6; font-size: 11px;")
            
            balance = status.get('balance', 0)
            self.balance_label.setText(f"💰 Баланс: {balance:,.2f} USDT")
            
            pos_count = status.get('positions_count', 0)
            self.positions_label.setText(f"📊 Позиции: {pos_count}")
        
        self._update_ui_state()
    
    def load_saved_data(self, params):
        if params.get('api_key'):
            self.api_key_input.setText(params['api_key'])
        if params.get('api_secret'):
            self.api_secret_input.setText(params['api_secret'])
        if params.get('api_passphrase'):
            self.passphrase_input.setText(params['api_passphrase'])
        self.testnet_check.setChecked(params.get('testnet', False))
        self.testnet = params.get('testnet', False)
