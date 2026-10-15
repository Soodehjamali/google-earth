"""Structured logging configuration."""

import logging
import re
import sys


class TileTokenMaskingFilter(logging.Filter):
    """Mask sensitive cryptographic tile tokens from access and application logs."""

    _PATH_TOKEN_PATTERN = re.compile(r"(/tiles/)[^/\s?#]+")
    _QUERY_TOKEN_PATTERN = re.compile(r"(?i)([\?&](?:tile_)?token=)[^&\s#]+")

    @classmethod
    def mask_text(cls, text: str) -> str:
        """Apply masking for path segment and query parameter tokens."""
        if not isinstance(text, str):
            return text
        text = cls._PATH_TOKEN_PATTERN.sub(r"\g<1>***MASKED***", text)
        text = cls._QUERY_TOKEN_PATTERN.sub(r"\g<1>***MASKED***", text)
        return text

    @classmethod
    def _mask_value(cls, val):
        if isinstance(val, str):
            return cls.mask_text(val)
        if isinstance(val, dict):
            return {k: cls._mask_value(v) for k, v in val.items()}
        if isinstance(val, tuple):
            return tuple(cls._mask_value(item) for item in val)
        if isinstance(val, list):
            return [cls._mask_value(item) for item in val]
        return val

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.mask_text(record.msg)
        if record.args:
            record.args = self._mask_value(record.args)
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
    for logger_name in ("uvicorn.access", "uvicorn", ""):
        log = logging.getLogger(logger_name)
        log.addFilter(token_filter)
        for handler in log.handlers:
            handler.addFilter(token_filter)

    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger instance."""
    return logging.getLogger(name)

