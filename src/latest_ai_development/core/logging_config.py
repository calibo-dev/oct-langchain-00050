"""Simple application logging setup."""

import logging

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(log_level: str) -> None:
    """Configure simple console logging for the application."""
    level_name = log_level.strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        force=True,
    )
