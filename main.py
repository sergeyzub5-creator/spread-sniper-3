#!/usr/bin/env python3
import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from core.utils.logger import setup_logger
from ui.main_window import MainWindow

def exception_hook(exctype, value, tb):
    import traceback
    error_msg = ''.join(traceback.format_exception(exctype, value, tb))
    print("\n❌ КРИТИЧЕСКАЯ ОШИБКА:")
    print(error_msg)
    sys.__excepthook__(exctype, value, tb)

if __name__ == "__main__":
    setup_logger()
    sys.excepthook = exception_hook
    
    app = QApplication(sys.argv)
    app.setApplicationName("Spread Sniper 3")
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())
