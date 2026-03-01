from PySide6.QtCore import QThreadPool, QRunnable, QObject, Signal
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
    
    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            if self.signals:
                self.signals.result.emit(result)
        except Exception as e:
            traceback.print_exc()
            if self.signals:
                self.signals.error.emit(str(e))
        finally:
            if self.signals:
                self.signals.finished.emit()
            self.signals = None

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
