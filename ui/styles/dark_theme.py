from ui.styles.theme_manager import build_app_stylesheet


def get_dark_theme_stylesheet():
    # Backward-compatible wrapper.
    return build_app_stylesheet()

