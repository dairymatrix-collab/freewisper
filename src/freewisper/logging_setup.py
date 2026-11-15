"""Logging setup: a rotating file handler plus secret redaction.

The redaction is applied by a :class:`logging.Formatter` subclass so it
covers the *final rendered* message — including exception tracebacks, which
a record-level filter would miss.

Patterns redacted:

* ``gsk_…`` / ``sk-…`` style provider keys
* ``Bearer <token>`` in an ``Authorization`` header
* ``api_key: <value>`` / ``"api_key" = "<value>"`` in any context
"""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

REDACTED = "***REDACTED***"

#: Values that look like a credential on their own.
_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgsk_[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{6,}"),
)

#: ``<prefix><secret>`` shapes — group 1 is preserved, group 2 is replaced.
_KEYED_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([^\s\"',}]+)"),
    re.compile(r"(?i)(authorization\"?\s*[:=]\s*\"?)([^\s\"',}]+)"),
)

DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%H:%M:%S"

#: Level names we accept. ``logging.getLevelNamesMapping()`` only exists from
#: Python 3.11 and this project supports 3.10, so the table is local.
_LEVEL_NAMES: dict[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def redact(text: str) -> str:
    """Return ``text`` with anything that looks like a credential replaced."""
    if not text:
        return text
    for pattern in _SECRET_VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    for pattern in _KEYED_SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + REDACTED, text)
    return text


class RedactingFormatter(logging.Formatter):
    """Formatter that scrubs secrets from the fully-rendered record."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class RedactingFilter(logging.Filter):
    """Filter that scrubs secrets from the record's message and arguments.

    Complementary to :class:`RedactingFormatter`: this keeps the in-memory
    record clean too, so a handler that formats the record itself (rather
    than going through our formatter) is still protected.

    Only **string** arguments are rewritten. Coercing every argument to
    ``str`` would break numeric format specifiers — ``log.info("%d", 3)``
    would raise ``TypeError: %d format: a real number is required``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, dict):
            record.args = {
                k: (redact(v) if isinstance(v, str) else v) for k, v in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def setup_logging(
    *,
    log_file: Path | None = None,
    level: int | str = logging.INFO,
    console: bool = True,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Logger:
    """Configure the root logger.

    Args:
        log_file: rotating log file path. ``None`` disables file logging.
        level: logging level for the root logger.
        console: whether to also log to stderr.
        max_bytes: rotate the file once it exceeds this size.
        backup_count: how many rotated files to keep.

    Returns:
        The configured root logger.
    """
    if isinstance(level, str):
        level = _LEVEL_NAMES.get(level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Replace any handlers we installed previously, so repeated calls
    # (tests, reloading) do not duplicate output.
    for handler in list(root.handlers):
        if getattr(handler, "_freewisper_handler", False):
            root.removeHandler(handler)
            handler.close()

    formatter = RedactingFormatter(DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT)
    redacting = RedactingFilter()

    if console:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(redacting)
        stream_handler._freewisper_handler = True  # type: ignore[attr-defined]
        root.addHandler(stream_handler)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redacting)
        file_handler._freewisper_handler = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    return root


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger."""
    return logging.getLogger(name)
