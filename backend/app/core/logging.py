"""Structured logging configuration."""

import logging
import re
import sys


class TileTokenMaskingFilter(logging.Filter):
    """Mask sensitive cryptographic tile tokens from access and application logs."""

    _TOKEN_PATTERN = re.compile(r"(/tiles/)([^/\s?]+)(/\d+/\d+/\d+\.png)")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._TOKEN_PATTERN.sub(r"\1***MASKED***\3", record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._TOKEN_PATTERN.sub(r"\1***MASKED***\3", v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._TOKEN_PATTERN.sub(r"\1***MASKED***\3", a) if isinstance(a, str) else a
                    for a in record.args
                )
        return True


def setup_logging():
    """Configure structured logging for the application."""
    # Imported here to avoid a circular import at module load time.
    from app.core.config import settings

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Mask tile tokens in uvicorn access and application logs
    token_filter = TileTokenMaskingFilter()
    logging.getLogger("uvicorn.access").addFilter(token_filter)
    logging.getLogger("uvicorn").addFilter(token_filter)
    logging.getLogger().addFilter(token_filter)

    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger instance."""
    return logging.getLogger(name)

