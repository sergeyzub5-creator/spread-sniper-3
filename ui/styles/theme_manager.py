from __future__ import annotations

from PySide6.QtCore import QObject, Signal


THEMES = {
    "dark": {
        "window_bg": "#07090d",
        "surface": "#10141a",
        "surface_alt": "#181e26",
        "border": "#34404a",
        "text_primary": "#e8eef2",
        "text_muted": "#a0b0c0",
        "accent": "#7aa2f7",
        "accent_bg": "#2a3a5a",
        "accent_bg_hover": "#3a4a7a",
        "success": "#7ec8a6",
        "success_bg": "#2a5a3a",
        "success_bg_hover": "#3a6a4a",
        "danger": "#e06c75",
        "danger_bg": "#5a2a2a",
        "danger_bg_hover": "#6a3a3a",
        "warning": "#e5c07b",
        "warning_bg": "#3a3a2a",
        "warning_bg_hover": "#5a5a3a",
        "scroll_bg": "#0a0c10",
        "selection_bg_soft": "rgba(42, 58, 90, 72)",
        "tab_selected_bg": "rgba(20, 24, 28, 128)",
        "net_idle": "#a0b0c0",
        "net_idle_border": "#5a6570",
        "net_online": "#22c55e",
        "net_online_border": "#15803d",
        "net_offline": "#ef4444",
        "net_offline_border": "#b91c1c",
    },
    "graphite_pro": {
        "window_bg": "#d6dbe3",
        "surface": "#cbd2dd",
        "surface_alt": "#b8c1cf",
        "border": "#8e9cad",
        "text_primary": "#1f2735",
        "text_muted": "#4d596c",
        "accent": "#4c79bd",
        "accent_bg": "#c6d5ec",
        "accent_bg_hover": "#b7c9e6",
        "success": "#418f7e",
        "success_bg": "#c0ddd6",
        "success_bg_hover": "#b3d4cc",
        "danger": "#b56a74",
        "danger_bg": "#eac8cd",
        "danger_bg_hover": "#e0b8c0",
        "warning": "#9f7633",
        "warning_bg": "#e8d8b6",
        "warning_bg_hover": "#dfcc9f",
        "scroll_bg": "#c7ced9",
        "selection_bg_soft": "rgba(76, 121, 189, 48)",
        "tab_selected_bg": "rgba(76, 121, 189, 102)",
        "net_idle": "#7f8ca0",
        "net_idle_border": "#657286",
        "net_online": "#22c55e",
        "net_online_border": "#15803d",
        "net_offline": "#ef4444",
        "net_offline_border": "#b91c1c",
        "btn_primary_bg": "#5d86c8",
        "btn_primary_hover": "#6f97d7",
        "btn_primary_text": "#ffffff",
        "btn_primary_border": "#95b2df",
        "btn_success_bg": "#4b9a88",
        "btn_success_hover": "#5aa997",
        "btn_success_text": "#ffffff",
        "btn_success_border": "#83c2b4",
        "btn_danger_bg": "#bf6f78",
        "btn_danger_hover": "#ce808a",
        "btn_danger_text": "#ffffff",
        "btn_danger_border": "#d9a0a8",
        "btn_warning_bg": "#9f844f",
        "btn_warning_hover": "#b0925f",
        "btn_warning_text": "#fffdf7",
        "btn_warning_border": "#ccb07f",
    },
    "steel": {
        "window_bg": "#1d2025",
        "surface": "#272c33",
        "surface_alt": "#323840",
        "border": "#5a626e",
        "text_primary": "#eef2f8",
        "text_muted": "#a9b4c4",
        "accent": "#8fa6c8",
        "accent_bg": "#3a4657",
        "accent_bg_hover": "#46556a",
        "success": "#69a997",
        "success_bg": "#394f4b",
        "success_bg_hover": "#435e58",
        "danger": "#c2868e",
        "danger_bg": "#5c464a",
        "danger_bg_hover": "#6b5358",
        "warning": "#b49a69",
        "warning_bg": "#585140",
        "warning_bg_hover": "#66604e",
        "scroll_bg": "#1b1e24",
        "selection_bg_soft": "rgba(146, 160, 180, 38)",
        "tab_selected_bg": "rgba(78, 86, 98, 156)",
        "net_idle": "#98a3b4",
        "net_idle_border": "#798496",
        "net_online": "#22c55e",
        "net_online_border": "#15803d",
        "net_offline": "#ef4444",
        "net_offline_border": "#b91c1c",
        # Button-specific overrides: keep gray theme matte, but controls remain vivid.
        "btn_primary_bg": "#4f79bf",
        "btn_primary_hover": "#5d89d2",
        "btn_primary_text": "#ffffff",
        "btn_primary_border": "#86a7db",
        "btn_success_bg": "#3f8a78",
        "btn_success_hover": "#4a9a87",
        "btn_success_text": "#ffffff",
        "btn_success_border": "#77b8aa",
        "btn_danger_bg": "#b86670",
        "btn_danger_hover": "#c57983",
        "btn_danger_text": "#ffffff",
        "btn_danger_border": "#d89ca3",
        "btn_warning_bg": "#957744",
        "btn_warning_hover": "#a78a55",
        "btn_warning_text": "#fffdf7",
        "btn_warning_border": "#bea372",
    },
}


class ThemeManager(QObject):
    theme_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._theme_name = "dark"

    @property
    def theme_name(self) -> str:
        return self._theme_name

    def set_theme(self, theme_name: str) -> bool:
        name = (theme_name or "").strip().lower()
        if not name or name not in THEMES:
            return False
        if name == self._theme_name:
            return False
        self._theme_name = name
        self.theme_changed.emit(name)
        return True

    def colors(self) -> dict:
        return THEMES.get(self._theme_name, THEMES["dark"])

    def color(self, key: str, default: str | None = None) -> str:
        palette = self.colors()
        if key in palette:
            return palette[key]
        if default is not None:
            return default
        return THEMES["dark"].get(key, "#000000")

    def available_themes(self) -> list[str]:
        return ["dark", "steel", "graphite_pro"]


_THEME_MANAGER = ThemeManager()


def get_theme_manager() -> ThemeManager:
    return _THEME_MANAGER


def theme_color(key: str, default: str | None = None) -> str:
    return _THEME_MANAGER.color(key, default=default)


def available_themes() -> list[str]:
    return _THEME_MANAGER.available_themes()


def build_app_stylesheet() -> str:
    c = get_theme_manager().colors()
    return f"""
        QMainWindow {{
            background-color: {c['window_bg']};
        }}
        QWidget {{
            background-color: {c['window_bg']};
            color: {c['text_primary']};
            font-family: 'Segoe UI', 'Arial', sans-serif;
        }}
        QLabel {{
            color: {c['text_primary']};
        }}
        QTabWidget::pane {{
            background: qlineargradient(
                x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 {c['surface_alt']},
                stop: 1 {c['surface']}
            );
            border-top: 1px solid {c['border']};
            border-left: none;
            border-right: none;
            border-bottom: none;
            border-radius: 0px;
        }}
        QTabBar::tab {{
            background-color: {c['window_bg']};
            color: {c['text_muted']};
            border: 1px solid {c['border']};
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            border-bottom: none;
            padding: 7px 16px;
            margin-right: 4px;
            font-weight: 600;
        }}
        QTabBar::tab:!selected:hover {{
            background-color: {c['surface']};
            color: {c['text_primary']};
            border-color: {c['accent']};
        }}
        QTabBar::tab:selected {{
            background-color: {c['surface_alt']};
            color: {c['accent']};
            border-color: {c['accent']};
        }}
        QTabBar::tab:selected:hover {{
            background-color: {c['tab_selected_bg']};
            color: {c['accent']};
            border-color: {c['accent']};
        }}
        QPushButton {{
            background-color: {c['surface_alt']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 8px 16px;
        }}
        QPushButton:hover {{
            background-color: {c['accent_bg']};
            border-color: {c['accent']};
        }}
        QPushButton:pressed {{
            background-color: {c['accent_bg_hover']};
            border-color: {c['accent']};
        }}
        QToolButton {{
            background-color: {c['surface_alt']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            padding: 5px 10px;
        }}
        QToolButton:hover {{
            background-color: {c['accent_bg']};
            border-color: {c['accent']};
        }}
        QToolButton:pressed {{
            background-color: {c['accent_bg_hover']};
            border-color: {c['accent']};
        }}
        QLineEdit {{
            background-color: {c['surface_alt']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 6px;
        }}
        QLineEdit:hover {{
            border-color: {c['accent']};
        }}
        QLineEdit:focus {{
            border-color: {c['accent']};
        }}
        QListView::item:hover, QListWidget::item:hover {{
            background-color: {c['selection_bg_soft']};
            border-radius: 6px;
        }}
        QListView::item:selected, QListWidget::item:selected {{
            background-color: {c['selection_bg_soft']};
            color: {c['accent']};
            border-radius: 6px;
        }}
        QMenu {{
            background-color: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 6px;
        }}
        QMenu::item {{
            background-color: transparent;
            color: {c['text_primary']};
            border-radius: 6px;
            padding: 6px 10px;
            margin: 1px 0;
        }}
        QMenu::item:selected {{
            background-color: {c['selection_bg_soft']};
            color: {c['accent']};
        }}
        QMenu::separator {{
            height: 1px;
            background: {c['border']};
            margin: 6px 4px;
        }}
    """


def button_style(kind: str, padding: str = "5px 10px", bold: bool = False) -> str:
    c = get_theme_manager().colors()
    mapping = {
        "primary": (
            "btn_primary_bg",
            "accent_bg",
            "btn_primary_text",
            "accent",
            "btn_primary_border",
            "accent",
            "btn_primary_hover",
            "accent_bg_hover",
        ),
        "success": (
            "btn_success_bg",
            "success_bg",
            "btn_success_text",
            "success",
            "btn_success_border",
            "success",
            "btn_success_hover",
            "success_bg_hover",
        ),
        "danger": (
            "btn_danger_bg",
            "danger_bg",
            "btn_danger_text",
            "danger",
            "btn_danger_border",
            "danger",
            "btn_danger_hover",
            "danger_bg_hover",
        ),
        "warning": (
            "btn_warning_bg",
            "warning_bg",
            "btn_warning_text",
            "warning",
            "btn_warning_border",
            "warning",
            "btn_warning_hover",
            "warning_bg_hover",
        ),
        "secondary": ("surface_alt", "text_muted", "text_muted", "border"),
    }
    if kind == "secondary":
        bg_key, text_key, border_key, hover_key = mapping["secondary"]
    else:
        (
            btn_bg_key,
            fallback_bg_key,
            btn_text_key,
            fallback_text_key,
            btn_border_key,
            fallback_border_key,
            btn_hover_key,
            fallback_hover_key,
        ) = mapping.get(kind, mapping["primary"])
        bg_key = btn_bg_key if btn_bg_key in c else fallback_bg_key
        text_key = btn_text_key if btn_text_key in c else fallback_text_key
        border_key = btn_border_key if btn_border_key in c else fallback_border_key
        hover_key = btn_hover_key if btn_hover_key in c else fallback_hover_key

    weight = "font-weight: bold;" if bold else ""
    return (
        f"QPushButton {{ background-color: {c[bg_key]}; color: {c[text_key]}; "
        f"border: 1px solid {c[border_key]}; border-radius: 4px; padding: {padding}; {weight}}}"
        f" QPushButton:hover {{ background-color: {c[hover_key]}; }}"
    )
