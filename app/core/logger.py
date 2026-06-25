import logging
import sys
from contextlib import contextmanager
from typing import Any, Generator

from app.core.config import settings


class _ColorFormatter(logging.Formatter):
    _COLORS = {
        logging.DEBUG: "\033[37m",       # grey
        logging.INFO: "\033[36m",        # cyan
        logging.WARNING: "\033[33m",     # yellow
        logging.ERROR: "\033[31m",       # red
        logging.CRITICAL: "\033[1;31m",  # bold red
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelno, self._RESET)
        record.levelname = f"{color}{record.levelname:<8}{self._RESET}"
        return super().format(record)


def setup_logging() -> None:
    """Configure root logger. Call once at application startup."""
    log_level = logging.DEBUG if settings.debug else logging.INFO
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ColorFormatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def log_operation(
    logger: logging.Logger,
    operation: str,
    **details: Any,
) -> Generator[None, None, None]:
    """
    Context manager that logs start, success, or failure with traceback.

    Usage:
        with log_operation(logger, "seed products", shop="dummyjson"):
            await do_something()
    """
    context = " | " + " | ".join(f"{k}={v}" for k, v in details.items()) if details else ""
    logger.info(f"[START] {operation}{context}")
    try:
        yield
        logger.info(f"[OK]    {operation}{context}")
    except Exception:
        logger.exception(f"[FAIL]  {operation}{context}")
        raise
