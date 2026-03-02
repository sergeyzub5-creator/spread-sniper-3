from time import monotonic

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractButton


class ButtonSpamGuard(QObject):
    """
    Global anti-spam guard for buttons.
    Blocks rapid repeated clicks/keyboard activations per button.
    """

    def __init__(self, cooldown_ms=220, parent=None):
        super().__init__(parent)
        self._cooldown_sec = max(0.05, float(cooldown_ms) / 1000.0)
        self._last_click = {}
        self._tracked = set()

    def _track_object(self, obj):
        key = id(obj)
        if key in self._tracked:
            return key
        self._tracked.add(key)
        obj.destroyed.connect(lambda _=None, k=key: self._forget(k))
        return key

    def _forget(self, key):
        self._last_click.pop(key, None)
        self._tracked.discard(key)

    @staticmethod
    def _is_activation_event(event):
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress:
            return event.button() == Qt.MouseButton.LeftButton
        if etype == QEvent.Type.KeyPress:
            if event.isAutoRepeat():
                return True
            return event.key() in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Space,
            )
        return False

    def eventFilter(self, obj, event):
        if not isinstance(obj, QAbstractButton):
            return False
        if obj.property("click_guard_skip"):
            return False
        if not self._is_activation_event(event):
            return False
        if not obj.isEnabled():
            return False

        key = self._track_object(obj)
        now = monotonic()
        last = self._last_click.get(key, 0.0)
        if now - last < self._cooldown_sec:
            event.accept()
            return True

        self._last_click[key] = now
        return False
