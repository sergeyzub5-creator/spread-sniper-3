# Паспорт проекта `spread-sniper-3`

Актуально на: 2 марта 2026  
Корень проекта: `C:\Users\Разраб\projektvscod`

## 1) Назначение проекта

`spread-sniper-3` — desktop-приложение на `PySide6` для подключения крипто-бирж и отображения:
- баланса,
- количества открытых позиций,
- текущего суммарного PnL по открытым позициям.

Интерфейс сейчас ориентирован на русский язык, с готовой архитектурой для переключения языков и тем.

## 2) Технологии

- Язык: `Python 3`
- UI: `PySide6`
- Сеть: `requests`
- Фоновые задачи: `QThreadPool` (`core/utils/thread_pool.py`)
- Логи: `logging` + файл `debug_YYYYMMDD.log`

Зависимости: `requirements.txt`

## 3) Запуск

```powershell
.\venv\Scripts\Activate.ps1
python main.py
```

Точка входа: `main.py`

## 4) Архитектура верхнего уровня

1. `main.py`
- инициализирует логгер и глобальный `exception_hook`,
- загружает настройки языка/темы,
- создаёт `QApplication`,
- устанавливает иконку приложения,
- создаёт и показывает `MainWindow`.

2. `ui/main_window.py`
- создаёт `ExchangeManager`,
- собирает верхний хедер (центрированный неон-логотип + правый блок язык/настройки),
- добавляет вкладки `Биржи` и `Снайпинг спреда`,
- синхронизирует тему/язык через менеджеры,
- показывает нижний статус-бар сети.

3. `core/exchange/manager.py`
- загружает биржи из `data/exchanges.json`,
- ведёт единый реестр подключений,
- выполняет асинхронные подключения,
- эмитит `status_updated` для UI.

4. `ui/tabs/exchanges_tab.py`
- отображает подключенные биржи,
- открывает окно выбора новой биржи,
- открывает отдельное окно ввода API-ключей,
- добавляет биржу в общий список только после успешного подключения.

## 5) Ключевые UI-компоненты

- `ui/widgets/exchange_panel.py`
  - карточка биржи,
  - компактный layout,
  - метрики баланс/позиции/PnL,
  - цветной статус-индикатор (лампочка):
    - зелёный — подключено,
    - жёлтый — подключается,
    - красный — не подключено/ошибка.

- `ui/widgets/brand_header.py`
  - `NeonLogoWidget` (верхний центр),
  - SVG-логотип генерируется в коде,
  - рендер через `QSvgRenderer` в `QPixmap`,
  - неоновые линии и glow-слои,
  - API: `setLogoSize(int)`, `setLineY(int)`, `setShowLines(bool)`.

- `ui/widgets/status_bar.py`
  - индикатор сети,
  - время,
  - короткие сообщения ошибок.

## 6) Иконки и графические ресурсы

- Логотипы бирж: `ui/assets/logos/exchanges/`
- Поддерживаемые расширения: `.png`, `.svg`, `.ico`, `.webp`, `.jpg`, `.jpeg`
- При отсутствии файла используется fallback-бейдж (`ui/widgets/exchange_badge.py`).

Иконка приложения:
- генерируется из того же SVG-лого (`build_neon_app_icon()` в `ui/widgets/brand_header.py`),
- применяется в `main.py` к `QApplication` и `MainWindow`.

## 7) Темы и языки

- Языки: `core/i18n/translations.py`, `core/i18n/language_manager.py`
- Темы: `ui/styles/theme_manager.py`
- Использовать только:
  - `tr("...")` для текста,
  - `theme_color(...)` и `button_style(...)` для цветов/кнопок.

Текущие темы:
- `theme.dark` — тёмная (стандарт)
- `theme.steel` — серая
- `theme.graphite_pro` — светлая

## 8) Безопасность данных

- API-секреты хранятся в `data/exchanges.json` в шифрованном виде.
- На Windows используется DPAPI (`core/data/secrets.py`, префикс `dpapi:`).
- `data/exchanges.json` не коммитится в git.

## 9) Поддерживаемые биржи

Подключаются через `core/exchange/factory.py`:
- Binance
- Bitget
- Bybit
- OKX
- MEXC
- KuCoin
- Gate
- BingX

Для неизвестного типа используется `PlaceholderExchange`.

## 10) Где вносить изменения

- Новая биржа:
  - `core/exchange/<name>.py`
  - `core/exchange/factory.py`
  - `core/exchange/catalog.py`
  - логотип в `ui/assets/logos/exchanges/<name>.png`

- Логика карточки биржи:
  - `ui/widgets/exchange_panel.py`

- Логика вкладки бирж/окна добавления:
  - `ui/tabs/exchanges_tab.py`

- Верхний неон-хедер/лого:
  - `ui/widgets/brand_header.py`
  - размещение в `ui/main_window.py`

- Темы/цвета:
  - `ui/styles/theme_manager.py`

- Языковые строки:
  - `core/i18n/translations.py`

## 11) Runtime-поток

1. Пользователь нажимает «Добавить биржу».
2. Открывается выбор биржи.
3. Открывается отдельное окно ввода ключей.
4. После «Добавить/Подключить» создаётся коннектор через factory.
5. При успешном подключении биржа попадает в общий список.
6. `ExchangeManager` эмитит обновления статусов.
7. Карточки обновляют статус, индикатор, баланс, позиции и PnL.

## 12) Бэкап и служебные команды

Полный бэкап в GitHub:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\github-backup.ps1
```

Снимок проекта в текст:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\snapshot.ps1
```

## 13) Быстрый onboarding

Читать в порядке:
1. `PROJECT_PASSPORT.md`
2. `main.py`
3. `ui/main_window.py`
4. `core/exchange/manager.py`
5. `ui/tabs/exchanges_tab.py`
6. `ui/widgets/exchange_panel.py`
7. `ui/widgets/brand_header.py`
8. `core/exchange/factory.py` + `core/exchange/catalog.py`
