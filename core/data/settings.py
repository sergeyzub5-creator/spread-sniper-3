from PySide6.QtCore import QSettings


class SettingsManager:
    _instance = None

    UI_LANGUAGE_KEY = "ui/language"
    UI_THEME_KEY = "ui/theme"
    FAST_TRADE_MODE_KEY = "trading/fast_mode"
    SPREAD_EXCHANGE_KEY_TMPL = "spread/col{index}/exchange"
    SPREAD_PAIR_KEY_TMPL = "spread/col{index}/pair"
    SPREAD_STRATEGY_KEY_TMPL = "spread/strategy/{name}"

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

    def set_value(self, key, value):
        self.settings.setValue(key, value)
        self.settings.sync()

    def get_value(self, key, default=""):
        return self.settings.value(key, default)

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

    def save_ui_language(self, language_code):
        self.set_value(self.UI_LANGUAGE_KEY, str(language_code or "ru"))

    def load_ui_language(self):
        return str(self.get_value(self.UI_LANGUAGE_KEY, "ru") or "ru")

    def save_ui_theme(self, theme_name):
        self.set_value(self.UI_THEME_KEY, str(theme_name or "dark"))

    def load_ui_theme(self):
        return str(self.get_value(self.UI_THEME_KEY, "dark") or "dark")

    def save_fast_trade_mode(self, enabled):
        self.set_value(self.FAST_TRADE_MODE_KEY, bool(enabled))

    def load_fast_trade_mode(self):
        value = self.get_value(self.FAST_TRADE_MODE_KEY, False)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def save_spread_column_selection(self, index, exchange_name, pair_symbol):
        idx = int(index)
        exchange_key = self.SPREAD_EXCHANGE_KEY_TMPL.format(index=idx)
        pair_key = self.SPREAD_PAIR_KEY_TMPL.format(index=idx)
        self.set_value(exchange_key, str(exchange_name or "").strip())
        self.set_value(pair_key, str(pair_symbol or "").strip())

    def load_spread_column_selection(self, index):
        idx = int(index)
        exchange_key = self.SPREAD_EXCHANGE_KEY_TMPL.format(index=idx)
        pair_key = self.SPREAD_PAIR_KEY_TMPL.format(index=idx)
        exchange_name = str(self.get_value(exchange_key, "") or "").strip()
        pair_symbol = str(self.get_value(pair_key, "") or "").strip()
        return exchange_name, pair_symbol

    def save_spread_strategy_config(self, config_dict):
        payload = config_dict if isinstance(config_dict, dict) else {}
        for key, value in payload.items():
            name = str(key or "").strip()
            if not name:
                continue
            settings_key = self.SPREAD_STRATEGY_KEY_TMPL.format(name=name)
            self.set_value(settings_key, value)

    def load_spread_strategy_config(self, default_dict=None):
        defaults = default_dict if isinstance(default_dict, dict) else {}
        result = dict(defaults)
        for key in defaults.keys():
            name = str(key or "").strip()
            if not name:
                continue
            settings_key = self.SPREAD_STRATEGY_KEY_TMPL.format(name=name)
            result[name] = self.get_value(settings_key, defaults[key])
        return result
