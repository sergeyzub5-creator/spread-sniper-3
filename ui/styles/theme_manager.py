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
    # Reserved for future switching without refactoring widgets.
    "light": {
        "window_bg": "#f4f6f8",
        "surface": "#ffffff",
        "surface_alt": "#eef2f6",
        "border": "#c7d0da",
        "text_primary": "#111827",
        "text_muted": "#4b5563",
        "accent": "#2563eb",
        "accent_bg": "#dbeafe",
        "accent_bg_hover": "#bfdbfe",
        "success": "#15803d",
        "success_bg": "#dcfce7",
        "success_bg_hover": "#bbf7d0",
        "danger": "#b91c1c",
        "danger_bg": "#fee2e2",
        "danger_bg_hover": "#fecaca",
        "warning": "#a16207",
        "warning_bg": "#fef3c7",
        "warning_bg_hover": "#fde68a",
        "scroll_bg": "#f4f6f8",
        "selection_bg_soft": "rgba(37, 99, 235, 0.18)",
        "tab_selected_bg": "rgba(219, 234, 254, 0.70)",
        "net_idle": "#94a3b8",
        "net_idle_border": "#64748b",
        "net_online": "#22c55e",
        "net_online_border": "#15803d",
        "net_offline": "#ef4444",
        "net_offline_border": "#b91c1c",
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


_THEME_MANAGER = ThemeManager()


def get_theme_manager() -> ThemeManager:
    return _THEME_MANAGER


def theme_color(key: str, default: str | None = None) -> str:
    return _THEME_MANAGER.color(key, default=default)


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
        "primary": ("accent_bg", "accent", "accent", "accent_bg_hover"),
        "success": ("success_bg", "success", "success", "success_bg_hover"),
        "danger": ("danger_bg", "danger", "danger", "danger_bg_hover"),
        "warning": ("warning_bg", "warning", "warning", "warning_bg_hover"),
        "secondary": ("surface_alt", "text_muted", "text_muted", "border"),
    }
    bg_key, text_key, border_key, hover_key = mapping.get(kind, mapping["secondary"])
    weight = "font-weight: bold;" if bold else ""
    return (
        f"QPushButton {{ background-color: {c[bg_key]}; color: {c[text_key]}; "
        f"border: 1px solid {c[border_key]}; border-radius: 4px; padding: {padding}; {weight}}}"
        f" QPushButton:hover {{ background-color: {c[hover_key]}; }}"
    )

