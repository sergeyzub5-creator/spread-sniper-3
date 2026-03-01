def get_dark_theme_stylesheet():
    return '''
        QMainWindow {
            background-color: #0a0c10;
        }
        QWidget {
            background-color: #0a0c10;
            color: #e8eef2;
            font-family: 'Segoe UI', 'Arial', sans-serif;
        }
        QLabel {
            color: #e8eef2;
        }
        QTabWidget::pane {
            background-color: #14181c;
            border: 1px solid #2a343c;
            border-radius: 6px;
        }
        QTabBar::tab {
            background-color: #1e2429;
            color: #a0b0c0;
            border: 1px solid #2a343c;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            padding: 8px 16px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: rgba(20, 24, 28, 128);
            color: #7aa2f7;
        }
        QPushButton {
            background-color: #1e2429;
            border: 1px solid #2a343c;
            border-radius: 4px;
            padding: 8px 16px;
        }
        QPushButton:hover {
            background-color: #2a343c;
        }
        QLineEdit {
            background-color: #1e2429;
            border: 1px solid #2a343c;
            border-radius: 4px;
            padding: 6px;
        }
    '''
