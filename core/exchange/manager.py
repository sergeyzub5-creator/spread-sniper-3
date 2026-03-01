from PySide6.QtCore import QObject, Signal
from core.utils.logger import get_logger
from core.data.storage import ExchangeStorage

logger = get_logger(__name__)

class ExchangeManager(QObject):
    exchange_added = Signal(str)
    exchange_removed = Signal(str)
    status_updated = Signal(dict)
    
    def __init__(self):
        super().__init__()
        self.exchanges = {}
        self.storage = ExchangeStorage()
        self._load_saved_exchanges()
    
    def _load_saved_exchanges(self):
        from core.exchange import BinanceExchange, BitgetExchange
        saved_data = self.storage.load_exchanges()
        for name, data in saved_data.items():
            exchange_type = data.get('type')
            params = {
                'api_key': data.get('api_key'),
                'api_secret': data.get('api_secret'),
                'testnet': data.get('testnet', False)
            }
            if exchange_type == 'bitget' and data.get('api_passphrase'):
                params['api_passphrase'] = data.get('api_passphrase')
            
            if exchange_type == 'binance':
                exchange = BinanceExchange(name, **params)
            elif exchange_type == 'bitget':
                exchange = BitgetExchange(name, **params)
            else:
                continue
            
            self.exchanges[name] = exchange
            self.exchange_added.emit(name)
            if params.get('api_key') and params.get('api_secret'):
                exchange.connect()
    
    def _save_exchanges(self):
        self.storage.save_exchanges(self.exchanges)
    
    def add_exchange(self, exchange):
        name = exchange.name
        if name in self.exchanges:
            logger.warning(f"Биржа {name} уже существует")
            return False
        self.exchanges[name] = exchange
        self.exchange_added.emit(name)
        self._save_exchanges()
        return True
    
    def remove_exchange(self, name):
        if name in self.exchanges:
            exchange = self.exchanges[name]
            if exchange.is_connected:
                exchange.disconnect()
            del self.exchanges[name]
            self.exchange_removed.emit(name)
            self._save_exchanges()
            return True
        return False
    
    def get_exchange(self, name):
        return self.exchanges.get(name)
    
    def get_all_exchanges(self):
        return self.exchanges
    
    def get_connected_names(self):
        return [name for name, ex in self.exchanges.items() if ex.is_connected]
    
    def get_all_status(self):
        statuses = {}
        for name, ex in self.exchanges.items():
            statuses[name] = {
                'connected': ex.is_connected,
                'testnet': ex.testnet,
                'balance': ex.balance,
                'positions_count': len(ex.positions),
                'pnl': ex.pnl,
                'status_text': ex.get_status_text()
            }
        return statuses
    
    def disconnect_all(self):
        for exchange in self.exchanges.values():
            if exchange.is_connected:
                exchange.disconnect()
        self._save_exchanges()
