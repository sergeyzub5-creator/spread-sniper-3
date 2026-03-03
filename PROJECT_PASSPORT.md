# Паспорт проекта `spread-sniper-3`

Актуально на: 3 марта 2026  
Корень проекта: `C:\Users\Разраб\projektvscod`

## 1) Назначение проекта

`spread-sniper-3` — desktop-приложение на `PySide6` для подключения крипто-бирж и отображения:
- баланса,
- количества открытых позиций (в т.ч. по направлениям Long/Short),
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
- теперь тонкий UI-оркестратор вкладки (layout, стили, retranslate),
- бизнес-логика вынесена в `features/exchanges/controllers/*`,
- диалоги подключения вынесены в `features/exchanges/dialogs/*`,
- вкладка связывает сигналы UI с независимыми логическими блоками.

5. `ui/tabs/spread_sniping_tab.py`
- выполняет роль UI-панели/компоновщика (визуальные элементы + привязка сигналов),
- логика и стили вынесены в `features/spread_sniping/controllers/*`,
- сетевые и биржевые блоки вынесены в отдельные модули:
  - `features/spread_sniping/models/column_context.py` (состояние и ссылки UI для колонки),
  - `features/spread_sniping/controllers/theme_mixin.py` (тема/stylesheet вкладки),
  - `features/spread_sniping/controllers/display_mixin.py` (расчёт/режимы отображения спреда),
  - `features/spread_sniping/controllers/selection_mixin.py` (агрегатор selection-блоков),
  - `features/spread_sniping/controllers/selection_state_mixin.py` (state и выбор биржи/пары),
  - `features/spread_sniping/controllers/pair_loader_mixin.py` (асинхронная загрузка/кэш/retry списка пар),
  - `features/spread_sniping/controllers/pair_suggestions_mixin.py` (debounce и ранжирование автокомплита),
  - `features/spread_sniping/controllers/pair_input_session_mixin.py` (UX-сессия ввода пары и popup lifecycle),
  - `features/spread_sniping/controllers/quote_mixin.py` (состояния котировок и управление стримом),
  - `features/spread_sniping/controllers/strategy_mixin.py` (настройки стратегии и синхронизация состояния),
  - `features/spread_sniping/controllers/trade_mixin.py` (временный торговый блок BUY/SELL),
  - `features/spread_sniping/dialogs/connected_exchange_picker_dialog.py` (выбор биржи),
  - `features/spread_sniping/services/binance_book_ticker_stream.py` (WS поток котировок),
  - `features/spread_sniping/services/strategy_engine.py` (расчёт сигналов входа/выхода стратегии),
  - `features/spread_sniping/services/spread_runtime_service.py` (не-UI сценарная логика вкладки),
  - `core/exchange/adapters/binance/spread.py` (Binance-специфика для спреда: пары аккаунта, snapshot bid/ask).

6. `core/exchange/adapters/*`
- слой адаптеров биржевых механизмов по доменам (сейчас добавлен Binance adapter для spread),
- целевая модель развития: для каждой биржи собственная папка адаптера с блоками:
  - `market_data` (цены/стакан),
  - `trading` (типы ордеров, исполнение),
  - `account` (баланс/позиции/права),
  - feature-специфичные фасады (как `spread.py`).

## 4.1) Слои и границы ответственности (обновлено)

1. `ui/*` — только представление и пользовательские действия.
2. `features/*` — сценарии конкретных вкладок/режимов, orchestration и переиспользуемые блоки.
3. `core/exchange/*` — общая биржевая инфраструктура и коннекторы.
4. `core/exchange/adapters/*` — биржевая прикладная логика по направлениям (order/price/book/account).
5. `core/data/*`, `core/i18n/*`, `ui/styles/*` — кросс-срезовые подсистемы.

## 5) Ключевые UI-компоненты

- `ui/widgets/exchange_panel.py`
  - карточка биржи,
  - компактный layout,
  - метрики баланс/позиции/PnL,
  - для позиций поддерживается отображение `Лонг N | Шорт M` цветами направлений,
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
  - индикатор сети в виде иконки Wi-Fi,
  - цветовая логика: online/offline/checking,
  - блок сети и блок времени оформлены в капсулы,
  - увеличенный жирный шрифт времени,
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
- Обязательное правило для новых UI-элементов: сразу добавлять ключи в обе локали `ru` и `en`.
- Языки в меню выбора показываются «на самих себя»: `Русский`, `English`.

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
  - (новый слой) `core/exchange/adapters/<name>/...` для feature/доменной логики
  - логотип в `ui/assets/logos/exchanges/<name>.png`

- Логика карточки биржи:
  - `ui/widgets/exchange_panel.py`

- Логика вкладки бирж/окна добавления:
  - UI-оркестратор: `ui/tabs/exchanges_tab.py`
  - Контроллеры: `features/exchanges/controllers/`
  - Диалоги: `features/exchanges/dialogs/`

- Логика вкладки снайпинга спреда:
  - UI-оркестратор: `ui/tabs/spread_sniping_tab.py`
  - Модель колонки: `features/spread_sniping/models/column_context.py`
  - Контроллеры: `features/spread_sniping/controllers/`
  - Диалоги: `features/spread_sniping/dialogs/`
  - Сервисы вкладки: `features/spread_sniping/services/`
  - Binance adapter для спреда: `core/exchange/adapters/binance/spread.py`

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
8. Закрытие позиций (по одной бирже или массово) выполняется в фоне через `Worker`/`ThreadManager`.
9. Если включен режим быстрой торговли, шаги подтверждения перед торговыми действиями пропускаются.

## 11.1) Архитектурное правило (обязательно)

1. Вкладка в `ui/tabs/*` не содержит биржевой/торговой бизнес-логики.
2. Вкладка должна собираться из блоков `features/*` (mixins/services/models/dialogs).
3. Любой новый сценарий делается как самостоятельный блок в `features/*`, затем подключается в вкладку.
4. Повторное использование блоков между вкладками выполняется импортом зависимостей, без копирования кода.

## 12) Бэкап и служебные команды

Полный бэкап в GitHub:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\github-backup.ps1
```

Опции бэкапа:
- `-StrictI18n` — строгая проверка i18n (включая hardcoded UI-строки).
- `-SkipI18nCheck` — пропустить i18n-проверку перед коммитом.

Проверка переводов вручную:

```powershell
py scripts/check_i18n.py
py scripts/check_i18n.py --strict
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
6. `features/exchanges/controllers/`
7. `features/exchanges/dialogs/`
8. `ui/tabs/spread_sniping_tab.py`
9. `features/spread_sniping/controllers/selection_mixin.py`
10. `features/spread_sniping/controllers/selection_state_mixin.py`
11. `features/spread_sniping/controllers/pair_loader_mixin.py`
12. `features/spread_sniping/controllers/pair_suggestions_mixin.py`
13. `features/spread_sniping/controllers/pair_input_session_mixin.py`
14. `features/spread_sniping/controllers/display_mixin.py`
15. `features/spread_sniping/controllers/strategy_mixin.py`
16. `features/spread_sniping/controllers/theme_mixin.py`
17. `features/spread_sniping/services/spread_runtime_service.py`
18. `core/exchange/adapters/binance/spread.py`
19. `ui/widgets/exchange_panel.py`
20. `ui/widgets/brand_header.py`
21. `core/exchange/factory.py` + `core/exchange/catalog.py`
