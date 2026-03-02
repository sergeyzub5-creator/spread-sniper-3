# spread-sniper-3

Desktop app on PySide6 for managing exchange API connections (Binance Futures, Bitget Futures).

## Run

```powershell
venv\Scripts\python.exe main.py
```

## API Setup

### Binance USD-M Futures

- Exchange in app: `Binance Futures`
- `Demo mode` ON -> `https://demo-fapi.binance.com`
- `Demo mode` OFF -> `https://fapi.binance.com`
- Required credentials: `API Key`, `API Secret`
- Required API permissions in Binance key settings: futures read access (account/position data).

### Bitget Futures (v2 API)

- Exchange in app: `Bitget Futures`
- Required credentials: `API Key`, `API Secret`, `Passphrase`
- Product type: `USDT-FUTURES`
- `Demo mode` ON sends header `paptrading: 1` (Bitget demo trading mode)
- Required API permissions in Bitget key settings: read access for futures account and positions.

## Connection Behavior

- On connect, app checks public market endpoint first.
- Then app requests private account/position data via signed requests.
- Balance and open positions are loaded immediately after successful auth.

## Security Notes

- Exchange credentials are stored in `data/exchanges.json`.
- On Windows, sensitive fields (`api_key`, `api_secret`, `api_passphrase`) are encrypted with DPAPI before writing to disk.
- DPAPI decryption works for the same Windows user account on the same machine.
- Old plain-text credentials are migrated automatically to encrypted format on next load.
- Use API keys with minimal permissions and IP whitelist when possible.

## Project Layout

- `core/exchange/` - exchange adapters and manager
- `core/data/` - persistence
- `core/i18n/` - language manager and translation dictionaries
- `ui/` - PySide6 interface
- `ui/styles/theme_manager.py` - centralized theme tokens and style builders
- `scripts/` - utility scripts (snapshot, github backup, i18n check, safe codex launcher)

## Development Rules

- `PROJECT_PASSPORT.md` - full architecture map of the project.
- `DEVELOPMENT_STANDARDS.md` - mandatory rules for new modules (themes + languages).

## i18n Check

```powershell
py scripts/check_i18n.py
py scripts/check_i18n.py --strict
```

- `scripts/github-backup.ps1` runs `check_i18n.py` before commit by default.
- Optional flags: `-StrictI18n` (fail on hardcoded UI strings), `-SkipI18nCheck` (skip pre-check).
