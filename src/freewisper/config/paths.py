"""Filesystem locations used by Freewisper.

Every location is overridable through an environment variable so that tests
never touch the real user profile, and so a portable install can be pointed
at a custom directory:

    FREEWISPER_CONFIG_DIR   directory holding config.json
    FREEWISPER_CONFIG_FILE  full path to config.json (wins over the directory)
    FREEWISPER_CACHE_DIR    model downloads and other regenerable data
    FREEWISPER_LOG_DIR      rotating log files
    FREEWISPER_LOG_FILE     full path to the log file (wins over the directory)
    FREEWISPER_DATA_DIR     durable state, e.g. the history database
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "freewisper"
APP_AUTHOR = "freewisper"


def _dirs() -> PlatformDirs:
    """Fresh ``PlatformDirs`` instance (cheap, and cheap to test against)."""
    return PlatformDirs(appname=APP_NAME, appauthor=APP_AUTHOR, roaming=True)


def _override(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    return Path(raw).expanduser()


def config_dir() -> Path:
    """Directory that holds ``config.json``."""
    override = _override("FREEWISPER_CONFIG_DIR")
    if override is not None:
        return override
    return Path(_dirs().user_config_dir)


def config_path() -> Path:
    """Full path to ``config.json``."""
    override = _override("FREEWISPER_CONFIG_FILE")
    if override is not None:
        return override
    return config_dir() / "config.json"


def cache_dir() -> Path:
    """Directory for regenerable data (downloaded speech models)."""
    override = _override("FREEWISPER_CACHE_DIR")
    if override is not None:
        return override
    return Path(_dirs().user_cache_dir)


def models_dir() -> Path:
    """Directory holding downloaded STT models."""
    return cache_dir() / "models"


def log_dir() -> Path:
    """Directory holding rotating log files."""
    override = _override("FREEWISPER_LOG_DIR")
    if override is not None:
        return override
    return Path(_dirs().user_log_dir)


def log_file() -> Path:
    """Full path to the primary log file."""
    override = _override("FREEWISPER_LOG_FILE")
    if override is not None:
        return override
    return log_dir() / "freewisper.log"


def data_dir() -> Path:
    """Directory holding durable state (history database)."""
    override = _override("FREEWISPER_DATA_DIR")
    if override is not None:
        return override
    return Path(_dirs().user_data_dir)


def history_db_path() -> Path:
    """Full path to the SQLite history database."""
    override = _override("FREEWISPER_HISTORY_DB")
    if override is not None:
        return override
    return data_dir() / "history.db"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if needed and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
