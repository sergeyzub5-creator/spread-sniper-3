# Стандарт разработки UI/модулей

Этот файл обязателен для новых вкладок и модулей.

## 1) Языки (i18n)

- Не писать пользовательские строки напрямую в виджетах.
- Все тексты брать через `tr("key")` из `core.i18n`.
- Новые ключи добавлять в `core/i18n/translations.py` сразу для:
  - `ru` (основной язык),
  - `en` (базовый fallback для будущего языкового патча).

Пример:

```python
from core.i18n import tr
label.setText(tr("tab.spread_sniping"))
```

## 2) Темы (theming)

- Не хардкодить цвета в модуле.
- Все цвета брать через `theme_color("token")`.
- Для кнопок использовать `button_style(kind, ...)`.
- Главная тема приложения формируется через `build_app_stylesheet()`.

Пример:

```python
from ui.styles import button_style, theme_color
btn.setStyleSheet(button_style("primary"))
frame.setStyleSheet(f"QFrame {{ border: 1px solid {theme_color('border')}; }}")
```

## 3) Каталог бирж

- Названия бирж не хардкодить в UI.
- Использовать `get_exchange_meta(... )["title"]`.
- Для новых бирж в `core/exchange/catalog.py` указывать `title_key` и добавить переводы в `translations.py`.

## 4) Новая вкладка

Минимальный шаблон:

1. Создать `ui/tabs/<name>_tab.py`.
2. Подключить в `ui/main_window.py` через `self.tabs.addTab(...)`.
3. Все тексты через `tr`.
4. Все цвета/стили через `theme_color`/`button_style`.

## 5) Запрещено

- Жестко задавать пользовательские строки в коде без ключа перевода.
- Жестко задавать hex-цвета в UI-модуле.

