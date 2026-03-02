from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
import traceback


class WorkerSignals(QObject):
    finished = Signal()
    error = Signal(str)
    result = Signal(object)


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def _safe_emit(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            # Receiver/signal object may already be deleted during app shutdown.
            pass

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            if self.signals:
                self._safe_emit(self.signals.result, result)
        except Exception as e:
            traceback.print_exc()
            if self.signals:
                self._safe_emit(self.signals.error, str(e))
        finally:
            if self.signals:
                self._safe_emit(self.signals.finished)


class ThreadManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.pool = QThreadPool()
            cls._instance.pool.setMaxThreadCount(4)
        return cls._instance

    def start(self, worker):
        self.pool.start(worker)

    def clear(self):
        self.pool.clear()

    def wait_for_done(self):
        self.pool.waitForDone()
