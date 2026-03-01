from core.exchange.base import BaseExchange
from core.exchange.catalog import get_exchange_meta, normalize_exchange_code


class PlaceholderExchange(BaseExchange):
    def __init__(
        self,
        name,
        exchange_type,
        api_key=None,
        api_secret=None,
        api_passphrase=None,
        testnet=False,
    ):
        super().__init__(name, api_key, api_secret, testnet)
        self.exchange_type = normalize_exchange_code(exchange_type)
        self.api_passphrase = api_passphrase
        self.last_error = ""

    def connect(self):
        self.is_connected = False
        title = get_exchange_meta(self.exchange_type)["title"]
        self.last_error = f"{title}: подключение пока не реализовано"
        self.error.emit(self.name, self.last_error)

    def disconnect(self):
        self.is_connected = False
        self.last_error = ""
        self.disconnected.emit(self.name)

    def subscribe_price(self, symbol):
        return None

    def unsubscribe_price(self, symbol):
        return None

    def get_status_text(self):
        if self.last_error:
            return f"Ошибка: {self.last_error}"
        return super().get_status_text()
