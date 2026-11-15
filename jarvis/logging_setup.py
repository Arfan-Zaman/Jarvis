"""Logging system: console plus a rotating file in the data directory.

This is the technical log for developers. The user-facing audit trail is the
`system_events` table (see `jarvis.stores.events`).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import Config

LOGGER_NAME = "jarvis"
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(config: Config, console: bool = True) -> logging.Logger:
    """Configure the `jarvis` logger. Safe to call more than once."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(config.log_level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(FORMAT)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        config.log_dir / "jarvis.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)
    return logger


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)
