"""Structured logging configuration."""

import logging
import sys
from typing import Any

from app.core.config import settings


def setup_logging() -> None:
    """Configure application logging."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    # Reduce noise from third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the given module name."""
    return logging.getLogger(name)


def log_request(logger: logging.Logger, method: str, path: str, **extra: Any) -> None:
    """Log an incoming request."""
    logger.info("Request: %s %s", method, path, extra=extra)


def log_error(logger: logging.Logger, message: str, exc_info: bool = True) -> None:
    """Log an error with optional traceback."""
    logger.error(message, exc_info=exc_info)
