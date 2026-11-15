"""Logging: secret redaction and file rotation."""

from __future__ import annotations

import logging
from pathlib import Path

from freewisper.logging_setup import (
    REDACTED,
    get_logger,
    redact,
    setup_logging,
)

# Built at runtime: a literal credential-shaped string in the source
# would trip GitHub's push protection and block the push.
SECRET = "gsk_" + "abcdef1234567890"


def _flush() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


# ---------------------------------------------------------------------------
# redact()
# ---------------------------------------------------------------------------


def test_redact_removes_a_groq_key() -> None:
    out = redact(f"using key {SECRET} now")
    assert SECRET not in out
    assert REDACTED in out


def test_redact_removes_an_openai_style_key() -> None:
    assert "sk-proj-abcdefghijklmnop" not in redact("sk-proj-abcdefghijklmnop")


def test_redact_removes_a_bearer_token() -> None:
    out = redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abcdef")
    assert "eyJhbGciOiJIUzI1NiJ9abcdef" not in out


def test_redact_keeps_the_key_name_but_drops_the_value() -> None:
    out = redact('{"api_key": "' + SECRET + '"}')
    assert SECRET not in out
    assert "api_key" in out


def test_redact_leaves_clean_text_untouched() -> None:
    text = "nothing secret here, just a normal sentence"
    assert redact(text) == text


def test_redact_handles_empty_input() -> None:
    assert redact("") == ""


# ---------------------------------------------------------------------------
# Log file
# ---------------------------------------------------------------------------


def test_log_file_never_contains_a_secret(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "freewisper.log"
    setup_logging(log_file=log_path, console=False)

    log = get_logger("freewisper.test")
    log.error("sending key %s", SECRET)
    log.error('payload was {"api_key": "%s"}', SECRET)
    _flush()

    text = log_path.read_text(encoding="utf-8")
    assert SECRET not in text
    assert REDACTED in text


def test_log_file_captures_the_message(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "freewisper.log"
    setup_logging(log_file=log_path, console=False)
    get_logger("freewisper.test").info("hello from the test suite")
    _flush()
    assert "hello from the test suite" in log_path.read_text(encoding="utf-8")


def test_traceback_secrets_are_redacted(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "freewisper.log"
    setup_logging(log_file=log_path, console=False)
    log = get_logger("freewisper.test")
    try:
        raise RuntimeError(f"failed while using {SECRET}")
    except RuntimeError:
        log.exception("boom")
    _flush()

    assert SECRET not in log_path.read_text(encoding="utf-8")


def test_log_file_rotates(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "freewisper.log"
    setup_logging(log_file=log_path, console=False, max_bytes=512, backup_count=2)

    log = get_logger("freewisper.test")
    for index in range(200):
        log.info("padding message %d %s", index, "x" * 40)
    _flush()

    rotated = list(log_path.parent.glob("freewisper.log.*"))
    assert rotated, "expected at least one rotated log file"
    assert all(path.stat().st_size <= 2048 for path in rotated)


def test_setup_logging_is_idempotent(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "freewisper.log"
    setup_logging(log_file=log_path, console=False)
    setup_logging(log_file=log_path, console=False)
    handlers = [h for h in logging.getLogger().handlers if getattr(h, "_freewisper_handler", False)]
    assert len(handlers) == 1


def test_console_handler_can_be_disabled(tmp_path: Path) -> None:
    """Only the file handler may be added when the console is turned off."""
    before = {id(h) for h in logging.getLogger().handlers}
    setup_logging(log_file=tmp_path / "logs" / "freewisper.log", console=False)
    added = [h for h in logging.getLogger().handlers if id(h) not in before]

    assert len(added) == 1
    assert isinstance(added[0], logging.FileHandler)


def test_numeric_format_args_are_not_corrupted(tmp_path: Path) -> None:
    """Regression: redacting must not coerce args to ``str``.

    ``log.info("%d", 3)`` raises ``TypeError: %d format: a real number is
    required`` if the argument was stringified.
    """
    log_path = tmp_path / "logs" / "freewisper.log"
    setup_logging(log_file=log_path, console=False)
    log = get_logger("freewisper.test")
    log.info("count=%d ratio=%.2f ok=%s", 3, 1.5, True)
    _flush()

    text = log_path.read_text(encoding="utf-8")
    assert "count=3" in text
    assert "ratio=1.50" in text


def test_string_args_are_still_redacted(tmp_path: Path) -> None:
    """A secret passed as a string argument must still be scrubbed."""
    log_path = tmp_path / "logs" / "freewisper.log"
    setup_logging(log_file=log_path, console=False)
    get_logger("freewisper.test").error("key=%s", SECRET)
    _flush()
    assert SECRET not in log_path.read_text(encoding="utf-8")
