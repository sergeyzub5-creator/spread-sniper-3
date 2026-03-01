from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, Signal

class ClickableLabel(QLabel):
    clicked = Signal()
    
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)
