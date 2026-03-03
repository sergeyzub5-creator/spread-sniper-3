from __future__ import annotations

import json
from pathlib import Path


_LOCALES_DIR = Path(__file__).with_name("locales")
_SUPPORTED = ("ru", "en")


def _repair_text(value: str) -> str:
    """Best-effort repair if a locale string was saved with wrong encoding."""
    if not isinstance(value, str) or not value:
        return value

    try:
        repaired = value.encode("cp1251").decode("utf-8")
    except Exception:
        return value

    if repaired.count("\ufffd") < value.count("\ufffd"):
        return repaired

    weird_markers = (
        "\u040e\u045e\u0403\u0453\u0402\u0452\u0409\u0459\u040a\u045a\u040b\u045b"
        "\u045f\u0406\u0456\u0407\u0457\u0490\u0491\u00b0\u00b5"
    )
    if any(ch in weird_markers for ch in value):
        return repaired
    if any(token in value for token in ("Ð", "Ñ", "â", "€")):
        return repaired
    return value


def _repair_obj(obj):
    if isinstance(obj, dict):
        return {k: _repair_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_repair_obj(v) for v in obj]
    if isinstance(obj, str):
        return _repair_text(obj)
    return obj


def _load_locale(lang: str) -> dict:
    path = _LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="ascii"))
    except Exception:
        # Manual edits may be UTF-8 with literal non-ASCII text.
        raw = json.loads(path.read_text(encoding="utf-8"))

    return _repair_obj(raw) if isinstance(raw, dict) else {}


TRANSLATIONS = {lang: _load_locale(lang) for lang in _SUPPORTED}
