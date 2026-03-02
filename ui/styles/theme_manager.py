from __future__ import annotations

from PySide6.QtCore import QObject, Signal


THEMES = {
    "dark": {
        "window_bg": "#0a0c10",
        "surface": "#14181c",
        "surface_alt": "#1e2429",
        "border": "#2a343c",
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
        "window_bg": "#e3e4e8",
        "surface": "#f0f1f4",
        "surface_alt": "#e8eaef",
        "border": "#c5c9d3",
        "text_primary": "#30384a",
        "text_muted": "#606a7d",
        "accent": "#4e79c7",
        "accent_bg": "#d8e4fb",
        "accent_bg_hover": "#c7d8f6",
        "success": "#4cae9d",
        "success_bg": "#d8efec",
        "success_bg_hover": "#c5e7e1",
        "danger": "#cb6466",
        "danger_bg": "#f8dede",
        "danger_bg_hover": "#f2cfd0",
        "warning": "#9c7a34",
        "warning_bg": "#f3e8cf",
        "warning_bg_hover": "#ebddbe",
        "scroll_bg": "#dde0e6",
        "selection_bg_soft": "rgba(78, 121, 199, 44)",
        "tab_selected_bg": "rgba(216, 228, 251, 180)",
        "net_idle": "#9098a8",
        "net_idle_border": "#737d8f",
        "net_online": "#22c55e",
        "net_online_border": "#15803d",
        "net_offline": "#ef4444",
        "net_offline_border": "#b91c1c",
    },
    "steel": {
        "window_bg": "#2b2c30",
        "surface": "#35373c",
        "surface_alt": "#3f4248",
        "border": "#5c6068",
        "text_primary": "#f0f2f5",
        "text_muted": "#b9bec7",
        "accent": "#9cb3d8",
        "accent_bg": "#505d72",
        "accent_bg_hover": "#5d6b81",
        "success": "#79bfa6",
        "success_bg": "#44635a",
        "success_bg_hover": "#4f7468",
        "danger": "#dc8a90",
        "danger_bg": "#774a51",
        "danger_bg_hover": "#88575f",
        "warning": "#c8ae7a",
        "warning_bg": "#6b5f44",
        "warning_bg_hover": "#7a6d4f",
        "scroll_bg": "#26282c",
        "selection_bg_soft": "rgba(156, 179, 216, 50)",
        "tab_selected_bg": "rgba(80, 93, 114, 160)",
        "net_idle": "#acb1bb",
        "net_idle_border": "#8c939f",
        "net_online": "#22c55e",
        "net_online_border": "#15803d",
        "net_offline": "#ef4444",
        "net_offline_border": "#b91c1c",
        # Button-specific overrides: keep gray theme matte, but controls remain vivid.
        "btn_primary_bg": "#3e71c4",
        "btn_primary_hover": "#5085db",
        "btn_primary_text": "#ffffff",
        "btn_primary_border": "#8eb3ee",
        "btn_success_bg": "#1f8f7d",
        "btn_success_hover": "#2aa792",
        "btn_success_text": "#ffffff",
        "btn_success_border": "#7cd4c3",
        "btn_danger_bg": "#ca4f5c",
        "btn_danger_hover": "#dc6170",
        "btn_danger_text": "#ffffff",
        "btn_danger_border": "#ee9aa3",
        "btn_warning_bg": "#8f6a2e",
        "btn_warning_hover": "#a9813f",
        "btn_warning_text": "#fffdf7",
        "btn_warning_border": "#d2b173",
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
            background-color: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 6px;
        }}
        QTabBar::tab {{
            background-color: {c['surface_alt']};
            color: {c['text_muted']};
            border: 1px solid {c['border']};
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            padding: 8px 16px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background-color: {c['tab_selected_bg']};
            color: {c['accent']};
        }}
        QPushButton {{
            background-color: {c['surface_alt']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 8px 16px;
        }}
        QPushButton:hover {{
            background-color: {c['border']};
        }}
        QLineEdit {{
            background-color: {c['surface_alt']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 6px;
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
