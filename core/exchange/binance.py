import time
import hmac
import hashlib
from urllib.parse import urlencode
import requests
from core.exchange.base import BaseExchange
from core.utils.logger import get_logger

logger = get_logger(__name__)

class BinanceExchange(BaseExchange):
    def __init__(self, name, api_key=None, api_secret=None, testnet=False):
        super().__init__(name, api_key, api_secret, testnet)
        
        if testnet:
            self.rest_url = "https://testnet.binancefuture.com"
        else:
            self.rest_url = "https://fapi.binance.com"
        
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({'X-MBX-APIKEY': api_key})
        
        self.time_offset = self._get_server_time_offset()
    
    def _get_server_time_offset(self):
        try:
            response = requests.get(f"{self.rest_url}/fapi/v1/time")
            if response.status_code == 200:
                server_time = response.json().get('serverTime')
                local_time = int(time.time() * 1000)
                return server_time - local_time
        except Exception as e:
            logger.error(f"Ошибка получения времени сервера: {e}")
        return 0
    
    def _sign_request(self, params):
        if not self.api_secret:
            return params
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        params['signature'] = signature
        return params
    
    def _request(self, method, endpoint, signed=False, params=None):
        if params is None:
            params = {}
        url = f"{self.rest_url}{endpoint}"
        
        if signed:
            params['timestamp'] = int(time.time() * 1000) + self.time_offset
            params = self._sign_request(params)
        
        try:
            if method == 'GET':
                response = self.session.get(url, params=params)
            else:
                response = self.session.post(url, json=params)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Binance API ошибка {response.status_code}: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Binance ошибка запроса: {e}")
            return None
    
    def _fetch_balance(self):
        try:
            account = self._request('GET', '/fapi/v2/account', signed=True)
            if account and 'assets' in account:
                total = 0
                for asset in account['assets']:
                    if asset['asset'] in ['USDT', 'BUSD', 'USDC']:
                        total += float(asset['walletBalance'])
                return total
            return 0
        except Exception as e:
            logger.error(f"Ошибка получения баланса: {e}")
            return 0
    
    def _fetch_positions(self):
        try:
            positions = self._request('GET', '/fapi/v2/positionRisk', signed=True)
            if positions:
                open_positions = []
                for pos in positions:
                    if float(pos.get('positionAmt', 0)) != 0:
                        open_positions.append({
                            'symbol': pos['symbol'],
                            'size': float(pos['positionAmt']),
                            'entry_price': float(pos['entryPrice']),
                            'mark_price': float(pos['markPrice']),
                            'pnl': float(pos['unRealizedProfit'])
                        })
                return open_positions
            return []
        except Exception as e:
            logger.error(f"Ошибка получения позиций: {e}")
            return []
    
    def connect(self):
        logger.info(f"{self.name} попытка подключения...")
        self.time_offset = self._get_server_time_offset()
        info = self._request('GET', '/fapi/v1/exchangeInfo')
        
        if info:
            self.is_connected = True
            self.connected.emit(self.name)
            self.balance = self._fetch_balance()
            self.positions = self._fetch_positions()
            self.balance_updated.emit(self.name, self.balance)
            self.positions_updated.emit(self.name, self.positions)
            total_pnl = sum(p.get('pnl', 0) for p in self.positions)
            self.pnl = total_pnl
            self.pnl_updated.emit(self.name, total_pnl)
            logger.info(f"✅ {self.name} подключена")
            return True
        else:
            self.error.emit(self.name, "Ошибка подключения")
            return False
    
    def disconnect(self):
        self.is_connected = False
        self.disconnected.emit(self.name)
        logger.info(f"✅ {self.name} отключена")
    
    def subscribe_price(self, symbol):
        logger.info(f"{self.name} подписка на {symbol}")
    
    def unsubscribe_price(self, symbol):
        logger.info(f"{self.name} отписка от {symbol}")
