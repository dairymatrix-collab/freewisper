"""Configuration storage: atomicity, secret hygiene, migration, quarantine."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from freewisper.config.defaults import default_config
from freewisper.config.schema import FreewisperConfig
from freewisper.config.store import (
    SECRET_KEYS,
    load_config,
    migrate,
    save_config,
    strip_secrets,
)

# Assembled at runtime so no credential-shaped literal is committed
# (GitHub push protection flags those).
SECRET = "gsk_" + "abcdef1234567890"


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_round_trip_preserves_the_document(tmp_path: Path) -> None:
    cfg = default_config()
    target = save_config(cfg, tmp_path / "config.json")
    loaded = load_config(target)
    assert loaded.model_dump(mode="json") == cfg.model_dump(mode="json")


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "config.json"
    save_config(default_config(), target)
    assert target.is_file()


def test_saved_file_is_readable_json(tmp_path: Path) -> None:
    target = save_config(default_config(), tmp_path / "config.json")
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["general"]["hotkey"]["key"] == "alt_r"


def test_unknown_keys_survive_a_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"future_option": {"nested": True}}), encoding="utf-8")
    loaded = load_config(target)
    assert loaded.model_extra is not None
    assert loaded.model_extra["future_option"] == {"nested": True}

    out = save_config(loaded, target)
    assert "future_option" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------


def test_failed_write_leaves_the_original_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "config.json"
    save_config(default_config(), target)
    original = target.read_text(encoding="utf-8")

    import freewisper.config.store as store

    def exploding_replace(src: Any, dst: Any) -> None:
        raise OSError("simulated crash before the rename")

    monkeypatch.setattr(store.os, "replace", exploding_replace)

    with pytest.raises(OSError):
        save_config(default_config(), target)

    assert target.read_text(encoding="utf-8") == original
    assert not (tmp_path / "config.json.tmp").exists()


def test_no_temp_file_is_left_behind_after_a_successful_save(tmp_path: Path) -> None:
    target = save_config(default_config(), tmp_path / "config.json")
    assert not (tmp_path / "config.json.tmp").exists()
    assert target.is_file()


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_secrets_never_reach_disk(tmp_path: Path) -> None:
    raw = {
        "api_key": SECRET,
        "groq_api_key": SECRET,
        "general": {"password": "hunter2"},
        "cleanup": {"providers": [{"id": "groq", "type": "groq", "client_secret": "s3cr3t-value"}]},
    }
    cfg = FreewisperConfig.model_validate(raw)
    target = save_config(cfg, tmp_path / "config.json")
    text = target.read_text(encoding="utf-8")

    assert SECRET not in text
    assert "hunter2" not in text
    assert "s3cr3t-value" not in text


def test_secrets_are_stripped_on_load_too(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"api_key": SECRET, "general": {}}), encoding="utf-8")
    loaded = load_config(target)

    dumped = json.dumps(loaded.model_dump(mode="json"))
    assert SECRET not in dumped


def test_strip_secrets_walks_lists_and_dicts() -> None:
    payload: dict[str, Any] = {
        "api_key": SECRET,
        "nested": [{"password": "hunter2"}, {"safe": "value"}],
        "safe": "value",
    }
    strip_secrets(payload)
    assert "api_key" not in payload
    assert "password" not in payload["nested"][0]
    assert payload["nested"][1]["safe"] == "value"
    assert payload["safe"] == "value"


def test_hotkey_is_not_mistaken_for_a_secret() -> None:
    payload = {"hotkey": "alt_r", "key": "value"}
    strip_secrets(payload)
    assert payload["hotkey"] == "alt_r"
    assert payload["key"] == "value"


def test_secret_key_list_does_not_include_hotkey() -> None:
    assert "hotkey" not in SECRET_KEYS
    assert "key" not in SECRET_KEYS


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


V1_DOCUMENT: dict[str, Any] = {
    "hotkey": "Key.alt_r",
    "pre_roll_ms": 250,
    "input_device": 3,
    "overlay_enabled": False,
    "start_on_login": True,
    "transcription": {"model": "small", "preview_enabled": False},
    "format": {
        "tier": "groq",
        "groq_model": "openai/gpt-oss-20b",
        "ollama_model": "llama3.2:3b",
    },
    "dictionary": [["kubernetes", "K8s"]],
}


def test_migrates_a_v1_document(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps(V1_DOCUMENT), encoding="utf-8")
    cfg = load_config(target)

    assert cfg.schema_version == 2
    assert cfg.general.hotkey.key == "alt_r"
    assert cfg.general.hotkey.mode.value == "push_to_talk"
    assert cfg.general.pre_roll_ms == 250
    assert cfg.general.overlay_enabled is False
    assert cfg.general.start_on_login is True
    assert cfg.audio.device == 3
    assert cfg.transcription.model == "small"
    assert cfg.transcription.preview.enabled is False
    assert cfg.cleanup.tier == "groq"
    assert cfg.cleanup.dictionary == [["kubernetes", "K8s"]]


def test_migration_carries_provider_models_across(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps(V1_DOCUMENT), encoding="utf-8")
    cfg = load_config(target)

    by_id = {p.id: p for p in cfg.cleanup.providers}
    assert by_id["groq"].model == "openai/gpt-oss-20b"
    assert by_id["ollama"].model == "llama3.2:3b"
    assert "rules" in by_id


def test_migrate_is_idempotent() -> None:
    once = migrate(dict(V1_DOCUMENT))
    twice = migrate(dict(once))
    assert once["schema_version"] == 2
    assert twice["schema_version"] == 2


def test_migration_drops_legacy_api_key_fields() -> None:
    document = dict(V1_DOCUMENT)
    document["format"] = {**V1_DOCUMENT["format"], "api_key": SECRET}  # type: ignore[index]
    migrated = migrate(document)
    assert "api_key" not in migrated["cleanup"]
    assert SECRET not in json.dumps(migrated)


def test_unknown_future_version_does_not_crash() -> None:
    migrated = migrate({"schema_version": 99, "something": 1})
    assert migrated["schema_version"] == 2
    assert migrated["something"] == 1


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "nope.json")
    assert cfg.schema_version == 2
    assert cfg.general.hotkey.key == "alt_r"


def test_corrupt_json_returns_defaults(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text("{not json at all", encoding="utf-8")
    cfg = load_config(target)
    assert cfg.schema_version == 2


def test_invalid_document_is_quarantined_not_deleted(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"general": {"pre_roll_ms": "not-a-number"}}), encoding="utf-8")

    cfg = load_config(target)

    assert cfg.schema_version == 2
    quarantine = tmp_path / "config.json.invalid"
    assert quarantine.is_file()
    assert "not-a-number" in quarantine.read_text(encoding="utf-8")
    assert not target.exists()


def test_non_object_json_returns_defaults(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_config(target).schema_version == 2


def test_saved_config_is_readable_by_a_fresh_process(tmp_path: Path) -> None:
    """The file on disk must be valid JSON to an outside reader."""
    target = save_config(default_config(), tmp_path / "config.json")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys;print(json.load(open(sys.argv[1]))['schema_version'])",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "2"
