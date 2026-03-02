#!/usr/bin/env python3
import sys
import os
from PySide6.QtWidgets import QApplication

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from core.data.settings import SettingsManager
from core.utils.logger import setup_logger
from core.i18n import get_language_manager, tr
from ui.styles import get_theme_manager
from ui.main_window import MainWindow
from ui.widgets.brand_header import build_neon_app_icon
from ui.widgets.startup_splash import StartupSplash

def exception_hook(exctype, value, tb):
    import traceback
    error_msg = ''.join(traceback.format_exception(exctype, value, tb))
    print("\n❌ КРИТИЧЕСКАЯ ОШИБКА:")
    print(error_msg)
    sys.__excepthook__(exctype, value, tb)

if __name__ == "__main__":
    setup_logger()
    sys.excepthook = exception_hook

    settings = SettingsManager()
    get_language_manager().set_language(settings.load_ui_language())
    get_theme_manager().set_theme(settings.load_ui_theme())
    
    app = QApplication(sys.argv)
    app.setApplicationName(tr("app.title"))
    app.setStyle('Fusion')
    app_icon = build_neon_app_icon()
    app.setWindowIcon(app_icon)
    
    window = MainWindow()
    window.setWindowIcon(app_icon)

    splash = StartupSplash()
    splash.finished.connect(window.show)
    splash.start()
    
    sys.exit(app.exec())
