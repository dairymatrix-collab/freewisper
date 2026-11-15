"""Configuration: typed schema, atomic storage, and filesystem paths."""

from __future__ import annotations

from .defaults import default_config
from .paths import (
    cache_dir,
    config_dir,
    config_path,
    data_dir,
    history_db_path,
    log_dir,
    log_file,
    models_dir,
)
from .schema import SCHEMA_VERSION, FreewisperConfig
from .store import load_config, save_config, strip_secrets

__all__ = [
    "SCHEMA_VERSION",
    "FreewisperConfig",
    "cache_dir",
    "config_dir",
    "config_path",
    "data_dir",
    "default_config",
    "history_db_path",
    "load_config",
    "log_dir",
    "log_file",
    "models_dir",
    "save_config",
    "strip_secrets",
]
