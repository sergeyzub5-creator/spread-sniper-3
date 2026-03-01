from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from core.i18n.translations import TRANSLATIONS


class LanguageManager(QObject):
    language_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._language = "ru"

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> bool:
        lang = (language or "").strip().lower()
        if not lang or lang not in TRANSLATIONS:
            return False
        if lang == self._language:
            return False
        self._language = lang
        self.language_changed.emit(lang)
        return True

    def translate(self, key: str, **kwargs) -> str:
        lang_dict = TRANSLATIONS.get(self._language, {})
        base_dict = TRANSLATIONS.get("ru", {})
        template = lang_dict.get(key, base_dict.get(key, key))
        if kwargs:
            try:
                return template.format(**kwargs)
            except Exception:
                return template
        return template


_LANGUAGE_MANAGER = LanguageManager()


def get_language_manager() -> LanguageManager:
    return _LANGUAGE_MANAGER


def tr(key: str, **kwargs) -> str:
    return _LANGUAGE_MANAGER.translate(key, **kwargs)

