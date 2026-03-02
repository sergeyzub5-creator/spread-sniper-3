import json
import os
from copy import deepcopy

from core.data.secrets import decrypt_secret, encrypt_secret, is_encrypted_secret
from core.utils.logger import get_logger

logger = get_logger(__name__)


class ExchangeStorage:
    SENSITIVE_FIELDS = ("api_key", "api_secret", "api_passphrase")

    def __init__(self, file_path="data/exchanges.json"):
        self.file_path = file_path

    def _write_raw_data(self, data):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _encrypt_sensitive(self, data):
        encrypted = dict(data)
        for field in self.SENSITIVE_FIELDS:
            if field in encrypted and encrypted[field] is not None:
                encrypted[field] = encrypt_secret(encrypted[field])
        return encrypted

    def _decrypt_sensitive(self, data):
        decrypted = dict(data)
        for field in self.SENSITIVE_FIELDS:
            if field in decrypted and decrypted[field] is not None:
                try:
                    decrypted[field] = decrypt_secret(decrypted[field])
                except Exception as exc:
                    logger.error("Ошибка расшифровки поля %s: %s", field, exc)
                    decrypted[field] = ""
        return decrypted

    def save_exchanges(self, exchanges):
        try:
            exchanges_data = {}
            for name, ex in exchanges.items():
                ex_type = getattr(ex, "exchange_type", None)
                if ex_type not in {"binance", "bitget"}:
                    ex_type = "binance" if "Binance" in str(type(ex)) else "bitget"

                data = {
                    "type": ex_type,
                    "api_key": ex.api_key,
                    "api_secret": ex.api_secret,
                    "testnet": ex.testnet,
                }
                if ex_type == "bitget" and hasattr(ex, "api_passphrase"):
                    data["api_passphrase"] = ex.api_passphrase

                exchanges_data[name] = self._encrypt_sensitive(data)

            self._write_raw_data(exchanges_data)
            logger.info("💾 Сохранено %s бирж", len(exchanges_data))
            return True
        except Exception as exc:
            logger.error("Ошибка сохранения бирж: %s", exc)
            return False

    def load_exchanges(self):
        try:
            if not os.path.exists(self.file_path):
                return {}

            with open(self.file_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            if not isinstance(raw_data, dict):
                return {}

            decrypted_data = {}
            migration_data = deepcopy(raw_data)
            needs_migration = False

            for name, data in raw_data.items():
                if not isinstance(data, dict):
                    continue

                for field in self.SENSITIVE_FIELDS:
                    value = data.get(field)
                    if isinstance(value, str) and value and not is_encrypted_secret(value):
                        migration_data[name][field] = encrypt_secret(value)
                        needs_migration = True

                decrypted_data[name] = self._decrypt_sensitive(data)

            if needs_migration:
                self._write_raw_data(migration_data)
                logger.info("🔐 Секреты автоматически мигрированы в DPAPI-формат")

            return decrypted_data
        except Exception as exc:
            logger.error("Ошибка загрузки бирж: %s", exc)
            return {}
