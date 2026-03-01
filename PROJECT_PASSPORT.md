# Паспорт проекта `spread-sniper-3`

Актуально на: 2026-03-02  
Корень проекта: `C:\Users\Разраб\projektvscod`

## 1) Что это за проект

`spread-sniper-3` — desktop-приложение на `PySide6` для подключения к фьючерсным API бирж, получения:
- баланса,
- количества открытых позиций,
- текущего суммарного `PnL` по открытым позициям.

UI полностью на русском языке и ориентирован на ручное управление подключениями бирж.

## 2) Технологии и зависимости

- Язык: `Python 3`
- UI: `PySide6`
- Сеть/REST: `requests`
- Асинхронные фоновые задачи: `QThreadPool` (`core/utils/thread_pool.py`)
- Логи: стандартный `logging` + файл `debug_YYYYMMDD.log`

Файл зависимостей: `requirements.txt`

## 3) Как запускать

Рекомендуемый запуск в виртуальном окружении:

```powershell
.\venv\Scripts\Activate.ps1
python main.py
```

Точка входа: `main.py`

## 4) Архитектура верхнего уровня

1. `main.py`:
- инициализирует логгер,
- ставит глобальный `exception_hook`,
- запускает `QApplication`,
- создаёт `MainWindow`.

2. `ui/main_window.py`:
- создаёт `ExchangeManager`,
- создаёт вкладку `Биржи` (`ExchangesTab`),
- связывает сигналы UI и менеджера,
- показывает нижнюю панель статуса сети (`NetworkStatusBar`).

3. `core/exchange/manager.py`:
- загружает сохранённые биржи из `data/exchanges.json`,
- поднимает фоновое автоподключение (без блокировки старта UI),
- хранит реестр подключений,
- эмитит единый статус `status_updated`.

4. `ui/tabs/exchanges_tab.py`:
- рендерит список уже подключенных бирж,
- открывает диалог выбора новой биржи,
- открывает отдельное окно параметров подключения,
- добавляет биржу в список только после успешного подключения.

## 5) Карта проекта и ответственность папок

### `core/`
- бизнес-логика и интеграция с биржами.

### `core/exchange/`
- `base.py`: базовый интерфейс биржи, поля состояния, сигналы.
- `manager.py`: центральный менеджер подключений и статусов.
- `factory.py`: фабрика создания экземпляров бирж по типу.
- `catalog.py`: справочник бирж (код, название, цвет, passphrase, порядок в UI).
- `binance.py`, `bitget.py`, `bybit.py`, `okx.py`, `mexc.py`, `kucoin.py`, `gate.py`, `bingx.py`: рабочие адаптеры REST.
- `placeholder.py`: заглушка для неизвестного/неподдерживаемого типа.
- `coinbase.py`: пустой каркас (фактически не используется фабрикой).

### `core/data/`
- `storage.py`: чтение/запись `data/exchanges.json`, миграция/шифрование секретов.
- `secrets.py`: DPAPI-шифрование/дешифрование секретов (Windows).
- `settings.py`: `QSettings` для локальных настроек.

### `core/utils/`
- `thread_pool.py`: `Worker`, `WorkerSignals`, `ThreadManager`.
- `logger.py`: настройка консольного и файлового логирования.

### `ui/`
- `main_window.py`: основной контейнер приложения.
- `styles/dark_theme.py`: общая тема и стили вкладок.
- `tabs/exchanges_tab.py`: логика вкладки «Биржи».
- `widgets/exchange_panel.py`: карточка одной подключенной биржи.
- `widgets/exchange_badge.py`: иконки/логотипы бирж, масштабирование и fallback.
- `widgets/status_bar.py`: индикатор сети, часы, краткие ошибки.
- `assets/logos/exchanges/`: локальные логотипы бирж (`.png/.svg/.ico/...`).

### `scripts/`
- `github-backup.ps1`: полный git-бэкап (add/commit/push).
- `snapshot.ps1` + `snapshot.bat`: снимок проекта в один файл.
- `codex-safe.cmd`: запуск Codex с безопасными флагами.

### `data/`
- рабочие данные (например `exchanges.json`), в git не коммитятся.

## 6) Основной runtime-поток данных

1. Пользователь нажимает «Добавить биржу».
2. Открывается `ExchangePickerDialog` (выбор типа биржи).
3. Открывается отдельный `NewExchangeDialog` с полями ключей.
4. При `Подключить/Добавить` UI эмитит `exchange_added(name, type, params)`.
5. `MainWindow` создаёт объект биржи через `create_exchange`.
6. Для новой биржи выполняется `connect()`; при успехе она добавляется в `ExchangeManager`.
7. `ExchangeManager` обновляет статусы и сохраняет конфиг в `data/exchanges.json`.
8. `ExchangesTab` получает `status_updated` и обновляет карточки.

## 7) Статусы и отображение в UI

Карточка подключенной биржи (`exchange_panel.py`) показывает:
- статус подключения (`Подключено`, `Не подключено`, `Загрузка...`, ошибка),
- баланс в USDT,
- число позиций,
- `PnL` только по открытым позициям:
  - нет открытых позиций: `0.00 USDT` серым,
  - плюс: зелёным,
  - минус: красным.

## 8) Логотипы и их поведение

Файлы логотипов: `ui/assets/logos/exchanges`

Правила:
- имя файла = код биржи из каталога (`binance.png`, `bitget.png`, ...),
- поддерживаются расширения: `.png`, `.svg`, `.ico`, `.webp`, `.jpg`, `.jpeg`,
- при отсутствии файла используется fallback-бейдж (цвет + короткий код),
- в `exchange_badge.py` есть `_LOGO_SCALE_OVERRIDES` (сейчас отдельная настройка для `bitget`).

Текущие размеры:
- в списке выбора биржи: `31x31`,
- в подключенных биржах: `42x42`,
- в окне нового подключения: `72x72`.

## 9) Безопасность данных

- Секреты (`api_key`, `api_secret`, `api_passphrase`) сохраняются в `data/exchanges.json`.
- На Windows используется DPAPI (`core/data/secrets.py`), формат: префикс `dpapi:...`.
- Старые незашифрованные секреты автоматически мигрируют в шифрованный вид при загрузке.
- `data/exchanges.json` исключён из git (`.gitignore`).

## 10) Поддерживаемые биржи и обязательные поля

Подключаются через `core/exchange/factory.py`:

- Binance: `api_key`, `api_secret`
- Bitget: `api_key`, `api_secret`, `api_passphrase`
- Bybit: `api_key`, `api_secret`
- OKX: `api_key`, `api_secret`, `api_passphrase`
- MEXC: `api_key`, `api_secret`
- KuCoin: `api_key`, `api_secret`, `api_passphrase`
- Gate: `api_key`, `api_secret`
- BingX: `api_key`, `api_secret`

Для неизвестного типа создаётся `PlaceholderExchange` (подключение не реализовано).

## 11) Где править под типовые задачи

- Добавить новую биржу:
  - создать адаптер в `core/exchange/<name>.py`,
  - добавить в `factory.py`,
  - добавить в `catalog.py` (meta + порядок),
  - положить логотип в `ui/assets/logos/exchanges/<name>.png`.

- Изменить логику отображения карточки биржи:
  - `ui/widgets/exchange_panel.py`

- Изменить список выбора бирж/диалоги добавления:
  - `ui/tabs/exchanges_tab.py`

- Изменить тему/эффекты выделения:
  - `ui/styles/dark_theme.py`
  - локальные стили в `ui/tabs/exchanges_tab.py`

- Изменить шифрование/хранение:
  - `core/data/secrets.py`
  - `core/data/storage.py`

## 12) Быстрый onboarding для нового диалога/агента

Прочитать в таком порядке:

1. `PROJECT_PASSPORT.md` (этот файл)
2. `main.py`
3. `ui/main_window.py`
4. `core/exchange/manager.py`
5. `ui/tabs/exchanges_tab.py`
6. `ui/widgets/exchange_panel.py`
7. `core/exchange/factory.py` + `core/exchange/catalog.py`

После этого уже можно безопасно вносить изменения в UI и подключения без полного сканирования всего репозитория.

## 13) Бэкап и служебные команды

Полный бэкап в GitHub:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\github-backup.ps1
```

Снимок проекта в текст:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\snapshot.ps1
```

## 14) Текущий стандарт расширения (тема + языки)

- Централизация языков:
  - `core/i18n/translations.py`
  - `core/i18n/language_manager.py`
  - использовать `from core.i18n import tr`
- Централизация тем:
  - `ui/styles/theme_manager.py`
  - использовать `theme_color(...)`, `button_style(...)`
- Политика для новых модулей:
  - не хардкодить строки/цвета в виджетах,
  - использовать ключи перевода и токены темы.
- Формальный регламент:
  - `DEVELOPMENT_STANDARDS.md`
