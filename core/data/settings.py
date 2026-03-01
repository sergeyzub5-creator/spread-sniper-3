from PySide6.QtCore import QSettings

class SettingsManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.settings = QSettings("spread-sniper-3", "settings")
    
    def save_last_pair(self, position, exchange_name, symbol):
        self.settings.beginGroup("last_pairs")
        self.settings.setValue(f"pos{position}_exchange", exchange_name)
        self.settings.setValue(f"pos{position}_symbol", symbol)
        self.settings.endGroup()
        self.settings.sync()
    
    def load_last_pair(self, position):
        self.settings.beginGroup("last_pairs")
        exchange = self.settings.value(f"pos{position}_exchange", "")
        symbol = self.settings.value(f"pos{position}_symbol", "")
        self.settings.endGroup()
        return exchange, symbol
