"""Shared pytest fixtures.

Every test runs against an isolated filesystem so that nothing here can
touch the developer's real profile, cache, logs, or API keys.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from freewisper.config.defaults import default_config
from freewisper.config.schema import FreewisperConfig


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect every Freewisper path into a temporary directory."""
    monkeypatch.setenv("FREEWISPER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("FREEWISPER_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("FREEWISPER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("FREEWISPER_DATA_DIR", str(tmp_path / "data"))
    for var in ("FREEWISPER_CONFIG_FILE", "FREEWISPER_LOG_FILE", "FREEWISPER_HISTORY_DB"):
        monkeypatch.delenv(var, raising=False)

    # No provider keys from the ambient environment.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return tmp_path


@pytest.fixture(autouse=True)
def reset_logging() -> None:
    """Restore the root logger's handlers after each test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)


@pytest.fixture()
def cfg() -> FreewisperConfig:
    """A fresh default configuration."""
    return default_config()
