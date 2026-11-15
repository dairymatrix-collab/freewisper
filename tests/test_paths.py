"""Configuration path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from freewisper.config import paths


def test_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FREEWISPER_CONFIG_DIR", str(tmp_path / "custom"))
    assert paths.config_dir() == tmp_path / "custom"


def test_config_file_override_wins_over_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FREEWISPER_CONFIG_DIR", str(tmp_path / "custom"))
    monkeypatch.setenv("FREEWISPER_CONFIG_FILE", str(tmp_path / "explicit.json"))
    assert paths.config_path() == tmp_path / "explicit.json"


def test_config_path_is_inside_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FREEWISPER_CONFIG_DIR", str(tmp_path / "custom"))
    monkeypatch.delenv("FREEWISPER_CONFIG_FILE", raising=False)
    assert paths.config_path().parent == paths.config_dir()
    assert paths.config_path().name == "config.json"


def test_models_dir_lives_under_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FREEWISPER_CACHE_DIR", str(tmp_path / "cache"))
    assert paths.models_dir() == tmp_path / "cache" / "models"


def test_history_db_lives_under_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FREEWISPER_DATA_DIR", str(tmp_path / "data"))
    assert paths.history_db_path() == tmp_path / "data" / "history.db"


def test_log_file_lives_under_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FREEWISPER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("FREEWISPER_LOG_FILE", raising=False)
    assert paths.log_file() == tmp_path / "logs" / "freewisper.log"


def test_ensure_dir_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c"
    assert paths.ensure_dir(target) == target
    assert target.is_dir()
