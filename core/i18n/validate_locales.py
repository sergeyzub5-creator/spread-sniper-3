from __future__ import annotations

import json
import sys
from pathlib import Path


LOCALES_DIR = Path(__file__).with_name("locales")
LANGS = ("ru", "en")
WEIRD_MARKERS = set(
    "\u040e\u045e\u0403\u0453\u0402\u0452\u0409\u0459\u040a\u045a\u040b\u045b"
    "\u045f\u0406\u0456\u0407\u0457\u0490\u0491\u00b0\u00b5"
)


def _load_locale(path: Path) -> dict:
    # Locales are stored as ASCII JSON (\uXXXX) to make encoding stable.
    raw = path.read_text(encoding="ascii")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: locale root must be object")
    return data


def _find_weird_values(locale: dict) -> list[str]:
    bad = []
    for key, value in locale.items():
        if not isinstance(value, str):
            continue
        if any(ch in WEIRD_MARKERS for ch in value):
            bad.append(key)
    return bad


def main() -> int:
    locales = {}
    for lang in LANGS:
        path = LOCALES_DIR / f"{lang}.json"
        if not path.exists():
            print(f"[i18n] missing locale file: {path}")
            return 1
        try:
            locales[lang] = _load_locale(path)
        except Exception as exc:
            print(f"[i18n] failed to load {path.name}: {exc}")
            return 1

    base_keys = set(locales["ru"].keys())
    ok = True
    for lang in LANGS:
        keys = set(locales[lang].keys())
        missing = sorted(base_keys - keys)
        extra = sorted(keys - base_keys)
        if missing:
            ok = False
            print(f"[i18n] {lang}: missing keys ({len(missing)}): {missing[:12]}")
        if extra:
            ok = False
            print(f"[i18n] {lang}: extra keys ({len(extra)}): {extra[:12]}")

        weird = _find_weird_values(locales[lang])
        if weird:
            ok = False
            print(f"[i18n] {lang}: suspicious mojibake markers in keys ({len(weird)}): {weird[:12]}")

    if not ok:
        return 1

    print("[i18n] locales are valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
