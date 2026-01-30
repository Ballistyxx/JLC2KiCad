"""Logging configuration for the JLCPCB Importer plugin."""

import logging
import sys

LOGGER_NAME = "jlcpcb_importer"

_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    """Return the plugin's logger, creating it on first call."""
    global _logger
    if _logger is None:
        _logger = logging.getLogger(LOGGER_NAME)
        if not _logger.handlers:
            _logger.setLevel(logging.DEBUG)
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            _logger.addHandler(handler)
    return _logger


def set_level(level: str) -> None:
    """Set the logging level by name (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""
    logger = get_logger()
    numeric = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric)
    for handler in logger.handlers:
        handler.setLevel(numeric)


def add_file_handler(path: str) -> None:
    """Add a file handler to the plugin logger."""
    logger = get_logger()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
