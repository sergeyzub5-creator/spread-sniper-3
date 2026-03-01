import json
import os
from core.utils.logger import get_logger

logger = get_logger(__name__)

class ExchangeStorage:
    def __init__(self, file_path="data/exchanges.json"):
        self.file_path = file_path
    
    def save_exchanges(self, exchanges):
        try:
            exchanges_data = {}
            for name, ex in exchanges.items():
                ex_type = "binance" if "Binance" in str(type(ex)) else "bitget"
                data = {
                    'type': ex_type,
                    'api_key': ex.api_key,
                    'api_secret': ex.api_secret,
                    'testnet': ex.testnet
                }
                if ex_type == "bitget" and hasattr(ex, 'api_passphrase'):
                    data['api_passphrase'] = ex.api_passphrase
                exchanges_data[name] = data
            
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(exchanges_data, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Сохранено {len(exchanges_data)} бирж")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения бирж: {e}")
            return False
    
    def load_exchanges(self):
        try:
            if not os.path.exists(self.file_path):
                return {}
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки бирж: {e}")
            return {}
