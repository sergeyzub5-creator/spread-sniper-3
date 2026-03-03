from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QLineEdit


class InputFocusGuard(QObject):
    """
    Global guard: clicking outside active input field exits input mode.
    Works for QLineEdit-based inputs across the whole app.
    """

    @staticmethod
    def _event_global_pos(event):
        if hasattr(event, "globalPosition"):
            try:
                return event.globalPosition().toPoint()
            except Exception:
                return None
        if hasattr(event, "globalPos"):
            try:
                return event.globalPos()
            except Exception:
                return None
        return None

    @staticmethod
    def _contains_global_point(widget, global_pos):
        if widget is None or global_pos is None or not widget.isVisible():
            return False
        top_left = widget.mapToGlobal(widget.rect().topLeft())
        local = global_pos - top_left
        return widget.rect().contains(local)

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.MouseButtonPress:
            return False

        app = QApplication.instance()
        if app is None:
            return False

        focused = app.focusWidget()
        if not isinstance(focused, QLineEdit):
            return False

        # Optional escape hatch for fields that should keep focus.
        if focused.property("input_focus_guard_skip"):
            return False

        global_pos = self._event_global_pos(event)
        if global_pos is None:
            return False

        if self._contains_global_point(focused, global_pos):
            return False

        completer = focused.completer()
        popup = completer.popup() if completer is not None else None
        if self._contains_global_point(popup, global_pos):
            return False

        focused.clearFocus()
        return False

