#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib.util
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_FILE = ROOT / "core" / "i18n" / "translations.py"
SCAN_DIRS = (ROOT / "ui", ROOT / "core")
IGNORE_DIR_NAMES = {"venv", ".git", "__pycache__", ".idea", ".vscode"}

UI_CONSTRUCTORS = {
    "QLabel",
    "QPushButton",
    "QCheckBox",
    "QGroupBox",
    "QToolButton",
    "QAction",
}
UI_METHODS = {
    "setText",
    "setWindowTitle",
    "setPlaceholderText",
    "setToolTip",
    "addAction",
    "setStatusTip",
}
NON_TEXT_PREFIXES = (
    "http://",
    "https://",
    "qlineargradient(",
    "qradialgradient(",
    "QWidget {",
    "QFrame {",
    "QPushButton {",
)


@dataclass
class RefKey:
    path: Path
    lineno: int
    key: str


@dataclass
class HardcodedText:
    path: Path
    lineno: int
    text: str
    source: str


@dataclass
class ParseError:
    path: Path
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="i18n consistency check")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat hardcoded UI strings as errors (default: warning only)",
    )
    return parser.parse_args()


def load_translations() -> dict:
    if not TRANSLATIONS_FILE.exists():
        raise FileNotFoundError(f"translations file not found: {TRANSLATIONS_FILE}")
    spec = importlib.util.spec_from_file_location("_translations", TRANSLATIONS_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load translations module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    translations = getattr(module, "TRANSLATIONS", None)
    if not isinstance(translations, dict):
        raise RuntimeError("TRANSLATIONS is not a dict")
    return translations


def iter_python_files():
    for base in SCAN_DIRS:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in IGNORE_DIR_NAMES for part in path.parts):
                continue
            yield path


def read_source(path: Path) -> str:
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return path.read_text()


def get_call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def extract_const_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def looks_like_key(text: str) -> bool:
    candidate = (text or "").strip()
    if not candidate or " " in candidate:
        return False
    return all(ch.islower() or ch.isdigit() or ch in "._-" for ch in candidate)


def is_style_literal(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith(NON_TEXT_PREFIXES):
        return True
    if "{" in t and "}" in t and ":" in t:
        return True
    return False


def is_meaningful_ui_text(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if is_style_literal(t):
        return False
    return any(ch.isalpha() for ch in t)


class I18nVisitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.is_ui_file = "ui" in path.parts
        self.refs: list[RefKey] = []
        self.hardcoded: list[HardcodedText] = []

    def visit_Call(self, node: ast.Call):
        call_name = get_call_name(node.func)

        if call_name == "tr" and node.args:
            key = extract_const_string(node.args[0])
            if key:
                self.refs.append(RefKey(path=self.path, lineno=node.lineno, key=key))

        if self.is_ui_file and node.args:
            literal = extract_const_string(node.args[0])
            if literal and is_meaningful_ui_text(literal):
                if looks_like_key(literal):
                    pass
                elif call_name in UI_CONSTRUCTORS:
                    self.hardcoded.append(
                        HardcodedText(
                            path=self.path,
                            lineno=node.lineno,
                            text=literal,
                            source=call_name,
                        )
                    )
                elif call_name in UI_METHODS:
                    self.hardcoded.append(
                        HardcodedText(
                            path=self.path,
                            lineno=node.lineno,
                            text=literal,
                            source=f".{call_name}",
                        )
                    )

        self.generic_visit(node)


def main() -> int:
    args = parse_args()

    try:
        translations = load_translations()
    except Exception as exc:
        print(f"[i18n] ERROR: {exc}")
        return 2

    locales = sorted(k for k, v in translations.items() if isinstance(v, dict))
    if not locales:
        print("[i18n] ERROR: no locales found in TRANSLATIONS")
        return 2

    locale_keys = {loc: set(translations.get(loc, {}).keys()) for loc in locales}
    all_keys = set().union(*locale_keys.values())

    missing_by_locale: dict[str, list[str]] = {}
    for loc in locales:
        missing = sorted(all_keys - locale_keys[loc])
        if missing:
            missing_by_locale[loc] = missing

    refs: list[RefKey] = []
    hardcoded: list[HardcodedText] = []
    parse_errors: list[ParseError] = []

    for path in iter_python_files():
        try:
            src = read_source(path)
            tree = ast.parse(src, filename=str(path))
        except Exception as exc:
            parse_errors.append(ParseError(path=path, error=str(exc)))
            continue

        visitor = I18nVisitor(path)
        visitor.visit(tree)
        refs.extend(visitor.refs)
        hardcoded.extend(visitor.hardcoded)

    missing_refs: list[tuple[RefKey, list[str]]] = []
    for ref in refs:
        missing_locales = [loc for loc in locales if ref.key not in locale_keys[loc]]
        if missing_locales:
            missing_refs.append((ref, missing_locales))

    has_blocking_errors = bool(parse_errors or missing_by_locale or missing_refs or (args.strict and hardcoded))

    if not (parse_errors or missing_by_locale or missing_refs or hardcoded):
        print("[i18n] OK: no missing keys and no hardcoded UI strings found.")
        return 0

    if has_blocking_errors:
        print("[i18n] CHECK FAILED")
    else:
        print("[i18n] CHECK WARNINGS")

    if parse_errors:
        print("\n[i18n] Parse errors in scanned files:")
        for item in parse_errors:
            rel = item.path.relative_to(ROOT)
            print(f"  - {rel}: {item.error}")

    if missing_by_locale:
        print("\n[i18n] Keys missing in locale dictionaries:")
        for loc in sorted(missing_by_locale):
            print(f"  - {loc}: {len(missing_by_locale[loc])} keys missing")
            for key in missing_by_locale[loc][:20]:
                print(f"      {key}")
            if len(missing_by_locale[loc]) > 20:
                print("      ...")

    if missing_refs:
        print("\n[i18n] Missing translation keys used in code:")
        for ref, missing_locales in missing_refs:
            rel = ref.path.relative_to(ROOT)
            locs = ",".join(missing_locales)
            print(f"  - {rel}:{ref.lineno} -> '{ref.key}' (missing in: {locs})")

    if hardcoded:
        print("\n[i18n] Hardcoded UI strings detected (use tr('...')):")
        for item in hardcoded[:200]:
            rel = item.path.relative_to(ROOT)
            sample = item.text.strip().replace("\n", "\\n")
            if len(sample) > 80:
                sample = sample[:77] + "..."
            print(f"  - {rel}:{item.lineno} via {item.source} -> \"{sample}\"")
        if len(hardcoded) > 200:
            print(f"  - ... and {len(hardcoded) - 200} more")
        if not args.strict:
            print("\n[i18n] NOTE: hardcoded strings are warnings. Run with --strict to fail on them.")

    print("\n[i18n] Tip: add missing keys to core/i18n/translations.py for ru/en.")
    return 1 if has_blocking_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
