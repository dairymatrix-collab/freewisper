"""Typed configuration schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from freewisper.config.defaults import (
    DEFAULT_GROQ_MODEL,
    DEFAULT_OLLAMA_MODEL,
    default_config,
)
from freewisper.config.schema import (
    SCHEMA_VERSION,
    FreewisperConfig,
    HotkeyMode,
    HotkeySpec,
    OverlayPosition,
)


def test_schema_version_is_two() -> None:
    assert SCHEMA_VERSION == 2


def test_defaults_are_sane(cfg: FreewisperConfig) -> None:
    assert cfg.general.hotkey.key == "alt_r"
    assert cfg.general.hotkey.mode is HotkeyMode.PUSH_TO_TALK
    assert cfg.general.pre_roll_ms == 500
    assert cfg.general.min_utterance_ms == 300
    assert cfg.general.overlay_position is OverlayPosition.BOTTOM_CENTER
    assert cfg.transcription.model == "base"
    assert cfg.cleanup.tier == "auto"
    assert cfg.context.enabled is False
    assert cfg.privacy.cloud_cleanup is True


def test_default_config_returns_independent_objects() -> None:
    first = default_config()
    second = default_config()
    first.cleanup.dictionary.append(["x", "y"])
    first.commands.clear()
    assert len(second.cleanup.dictionary) == 4
    assert len(second.commands) == 6


def test_hotkey_display_joins_modifiers() -> None:
    spec = HotkeySpec(modifiers=["ctrl", "shift"], key="space")
    assert spec.display() == "ctrl+shift+space"


def test_hotkey_display_without_modifiers() -> None:
    assert HotkeySpec(key="alt_r").display() == "alt_r"


def test_modifiers_are_normalised() -> None:
    spec = HotkeySpec(modifiers=[" Ctrl ", "ctrl", "SHIFT", ""], key="k")
    assert spec.modifiers == ["ctrl", "shift"]


def test_secondary_hotkey_defaults_to_toggle() -> None:
    cfg = default_config()
    assert cfg.general.secondary_hotkey.mode is HotkeyMode.TOGGLE
    assert cfg.general.secondary_hotkey.key == "space"


def test_unknown_keys_are_allowed() -> None:
    cfg = FreewisperConfig.model_validate({"totally_new_field": 42})
    assert cfg.model_extra is not None
    assert cfg.model_extra["totally_new_field"] == 42


def test_describe_reports_the_essentials(cfg: FreewisperConfig) -> None:
    summary = cfg.describe()
    assert summary["hotkey"] == "alt_r"
    assert summary["stt_model"] == "base"
    assert summary["cleanup_tier"] == "auto"
    assert summary["context_enabled"] is False
    assert summary["dictionary_entries"] == 4
    assert summary["commands"] == 6


def test_invalid_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        FreewisperConfig.model_validate({"general": {"pre_roll_ms": "not-a-number"}})


# ---------------------------------------------------------------------------
# Regression guards for provider defaults (see the roadmap, Tier 1).
# ---------------------------------------------------------------------------


def test_default_groq_model_is_a_production_model() -> None:
    """The default must not be a Preview-tier model.

    ``qwen/qwen3.8-27b`` is Preview on Groq ("may be discontinued at short
    notice"), ~2.2x slower, and ~13x more expensive per output token than
    ``openai/gpt-oss-20b``.
    """
    assert DEFAULT_GROQ_MODEL == "openai/gpt-oss-20b"
    assert "qwen" not in DEFAULT_GROQ_MODEL


def test_groq_provider_timeout_is_not_trivially_short() -> None:
    """3 s trips constantly on a large model and silently degrades the user."""
    cfg = default_config()
    groq = next(p for p in cfg.cleanup.providers if p.id == "groq")
    assert groq.timeout_s >= 6.0


def test_ollama_timeout_allows_slow_cpu_models() -> None:
    cfg = default_config()
    ollama = next(p for p in cfg.cleanup.providers if p.id == "ollama")
    assert ollama.timeout_s >= 15.0
    assert ollama.model == DEFAULT_OLLAMA_MODEL


def test_cleanup_chain_order_is_groq_then_ollama_then_rules() -> None:
    cfg = default_config()
    assert [p.id for p in cfg.cleanup.providers] == ["groq", "ollama", "rules"]
