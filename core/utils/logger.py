import logging
import os
import sys
from datetime import datetime


class _TraceOnlyFilter(logging.Filter):
    def filter(self, record):
        try:
            return str(record.getMessage()).startswith("[TRACE]")
        except Exception:
            return False


class _NoTraceFilter(logging.Filter):
    def filter(self, record):
        try:
            return not str(record.getMessage()).startswith("[TRACE]")
        except Exception:
            return True


def setup_logger(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setStream(open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1))
    # Keep terminal readable: TRACE goes to dedicated file.
    console.addFilter(_NoTraceFilter())
    logger.addHandler(console)

    try:
        logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(logs_dir, exist_ok=True)

        file_handler = logging.FileHandler(
            os.path.join(logs_dir, f"debug_{datetime.now().strftime('%Y%m%d')}.log"),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        trace_handler = logging.FileHandler(
            os.path.join(logs_dir, f"trace_{datetime.now().strftime('%Y%m%d')}.log"),
            encoding="utf-8",
        )
        trace_handler.setFormatter(formatter)
        trace_handler.addFilter(_TraceOnlyFilter())
        logger.addHandler(trace_handler)
    except OSError:
        # Keep console logging even if file logging cannot be initialized.
        pass

    return logger


def get_logger(name):
    return logging.getLogger(name)
