import requests
from core.exchange.base import BaseExchange
from core.utils.logger import get_logger

logger = get_logger(__name__)

class BitgetExchange(BaseExchange):
    def __init__(self, name, api_key=None, api_secret=None, api_passphrase=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)
        self.api_passphrase = api_passphrase
        self.product_type = "susdt-futures" if testnet else "usdt-futures"
    
    def connect(self):
        try:
            url = "https://api.bitget.com/api/v2/mix/market/contracts"
            params = {'productType': self.product_type}
            response = requests.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == '00000':
                    self.is_connected = True
                    self.connected.emit(self.name)
                    logger.info(f"✅ {self.name} подключена")
                    return True
            self.error.emit(self.name, "Ошибка подключения")
            return False
        except Exception as e:
            logger.error(f"Bitget ошибка: {e}")
            return False
    
    def disconnect(self):
        self.is_connected = False
        self.disconnected.emit(self.name)
        logger.info(f"✅ {self.name} отключена")
    
    def subscribe_price(self, symbol):
        logger.info(f"{self.name} подписка на {symbol}")
    
    def unsubscribe_price(self, symbol):
        logger.info(f"{self.name} отписка от {symbol}")
