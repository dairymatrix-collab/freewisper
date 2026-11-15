"""Typed configuration schema for Freewisper (pydantic v2).

Design rules enforced here:

* **Forward compatible.** Every model allows extra keys, so a config written
  by a newer Freewisper still loads on an older one (and is preserved on save).
* **Versioned.** ``schema_version`` drives migrations in :mod:`freewisper.config.store`.
* **No secrets.** API keys are never modelled here — they live in the OS
  keychain. See :func:`freewisper.config.store.strip_secrets`.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Bump when the on-disk shape changes in a way that needs a migration.
SCHEMA_VERSION = 2


class _Model(BaseModel):
    """Base model: tolerate unknown keys, keep them on round-trip."""

    model_config = ConfigDict(extra="allow", validate_assignment=True)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class HotkeyMode(str, Enum):
    """How a hotkey triggers a dictation."""

    PUSH_TO_TALK = "push_to_talk"
    TOGGLE = "toggle"


class CleanupProviderType(str, Enum):
    """Kinds of text-cleanup backend."""

    GROQ = "groq"
    OLLAMA = "ollama"
    RULES = "rules"
    OPENAI_COMPAT = "openai_compat"
    ANTHROPIC = "anthropic"
    LLAMA_CPP = "llama_cpp"


class CommandMode(str, Enum):
    """How a command's trigger phrase is matched."""

    PREFIX = "prefix"
    CONTAINS = "contains"


class OverlayPosition(str, Enum):
    """Where the floating HUD is placed."""

    BOTTOM_CENTER = "bottom_center"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    TOP_CENTER = "top_center"
    FOLLOW_CURSOR = "follow_cursor"


# ---------------------------------------------------------------------------
# Leaf models
# ---------------------------------------------------------------------------


class HotkeySpec(_Model):
    """A single hotkey: modifiers plus a base key."""

    mode: HotkeyMode = HotkeyMode.PUSH_TO_TALK
    modifiers: list[str] = Field(default_factory=list)
    key: str = "alt_r"

    @field_validator("modifiers")
    @classmethod
    def _normalise_modifiers(cls, value: list[str]) -> list[str]:
        """Lower-case, de-duplicate, and keep a stable order."""
        seen: list[str] = []
        for mod in value:
            mod = mod.strip().lower()
            if mod and mod not in seen:
                seen.append(mod)
        return seen

    def display(self) -> str:
        """Human-readable form, e.g. ``ctrl+shift+space``."""
        parts = [*self.modifiers, self.key]
        return "+".join(p for p in parts if p)


class VadConfig(_Model):
    """Energy-based voice-activity detection."""

    enabled: bool = True
    threshold_dbfs: float = -42.0
    hangover_ms: int = 600
    min_speech_ms: int = 200


class PreviewConfig(_Model):
    """Live streaming preview (never injected)."""

    enabled: bool = True
    engine: str = "vosk"
    model: str = "vosk-model-small-en-us-0.15"


class AudioConfig(_Model):
    """Input device and voice-activity detection."""

    device: int | str | None = None
    channels: int | str = "auto"
    #: Remove leading and trailing silence before the audio reaches the
    #: speech-to-text model.
    trim_silence: bool = True
    #: How much audio the always-on ring buffer holds. Must be at least as
    #: long as ``general.pre_roll_ms``.
    ring_seconds: float = 1.5
    vad: VadConfig = Field(default_factory=VadConfig)


class TranscriptionConfig(_Model):
    """Speech-to-text engine selection."""

    provider: str = "auto"
    model: str = "base"
    compute_type: str = "int8"
    device: str = "auto"
    beam_size: int = 1
    vad_filter: bool = False
    hotwords_from_dictionary: bool = True
    preview: PreviewConfig = Field(default_factory=PreviewConfig)


class CleanupProviderConfig(_Model):
    """One rung of the cleanup failover chain."""

    id: str
    type: CleanupProviderType
    model: str | None = None
    url: str | None = None
    enabled: bool = True
    timeout_s: float = 15.0


def default_cleanup_providers() -> list[CleanupProviderConfig]:
    """The default failover chain: cloud → local → deterministic.

    The Groq entry points at ``openai/gpt-oss-20b``, a *Production* model.
    ``qwen/qwen3.8-27b`` is Preview tier ("may be discontinued at short
    notice"), roughly 2.2x slower, and ~13x more expensive per output token,
    so it must not be the default.

    The Groq timeout is 6 s rather than 3 s: a large model routinely needs
    longer, and a timeout silently downgrades the user to a worse tier.
    """
    return [
        CleanupProviderConfig(
            id="groq",
            type=CleanupProviderType.GROQ,
            model="openai/gpt-oss-20b",
            timeout_s=6.0,
        ),
        CleanupProviderConfig(
            id="ollama",
            type=CleanupProviderType.OLLAMA,
            model="llama3.2:3b",
            timeout_s=15.0,
        ),
        CleanupProviderConfig(id="rules", type=CleanupProviderType.RULES, timeout_s=1.0),
    ]


class CleanupConfig(_Model):
    """The cleanup tier chain plus the personal dictionary and snippets."""

    tier: str = "auto"
    providers: list[CleanupProviderConfig] = Field(default_factory=default_cleanup_providers)
    system_prompt: str | None = None
    length_guard_ratio: float = 1.5
    dictionary: list[list[str]] = Field(default_factory=list)
    snippets: dict[str, str] = Field(default_factory=dict)


class CommandConfig(_Model):
    """A macro: trigger phrase → prompt template → transformed text."""

    id: str
    triggers: list[str] = Field(default_factory=list)
    mode: CommandMode = CommandMode.PREFIX
    prompt: str
    provider: str | None = None
    model: str | None = None
    enabled: bool = True
    allow_expansion: bool = False


class ProfileConfig(_Model):
    """Per-application overrides, resolved from the focused app."""

    style: str = "general"
    dictionary: str | None = None
    normalize: bool = True
    smart_quotes: bool = True
    context: bool = False
    cleanup_provider: str | None = None


class GeneralConfig(_Model):
    """Hotkeys, timing, and window behaviour."""

    hotkey: HotkeySpec = Field(default_factory=HotkeySpec)
    secondary_hotkey: HotkeySpec = Field(
        default_factory=lambda: HotkeySpec(
            mode=HotkeyMode.TOGGLE, modifiers=["ctrl", "shift"], key="space"
        )
    )
    undo_hotkey: HotkeySpec = Field(
        default_factory=lambda: HotkeySpec(modifiers=["ctrl", "alt"], key="z")
    )
    pre_roll_ms: int = 500
    min_utterance_ms: int = 300
    overlay_enabled: bool = True
    overlay_position: OverlayPosition = OverlayPosition.BOTTOM_CENTER
    start_on_login: bool = False
    language: str = "en"


class ContextConfig(_Model):
    """Focused-window context (off by default — it can leave the machine)."""

    enabled: bool = False
    max_chars: int = 500
    provider: str | None = None


class HistoryConfig(_Model):
    """Dictation history retention."""

    enabled: bool = True
    max_rows: int = 5000
    retention_days: int = 30


class PrivacyConfig(_Model):
    """What is allowed to leave the machine."""

    cloud_cleanup: bool = True
    redact_before_cloud: bool = False


class FreewisperConfig(_Model):
    """Root configuration document."""

    schema_version: int = SCHEMA_VERSION
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
    commands: list[CommandConfig] = Field(default_factory=list)
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)
    context: ContextConfig = Field(default_factory=ContextConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)

    @model_validator(mode="after")
    def _check_pre_roll_fits_the_ring(self) -> FreewisperConfig:
        """The ring buffer has to be able to hold the whole pre-roll.

        Silently shrinking the pre-roll would lose the audio the user
        deliberately configured to keep, so this is a hard error rather than
        a silent adjustment.
        """
        ring_ms = self.audio.ring_seconds * 1000.0
        if self.general.pre_roll_ms > ring_ms:
            raise ValueError(
                f"general.pre_roll_ms ({self.general.pre_roll_ms}) is longer than "
                f"audio.ring_seconds ({self.audio.ring_seconds:g} s = {ring_ms:g} ms). "
                "Increase audio.ring_seconds or reduce general.pre_roll_ms."
            )
        return self

    def describe(self) -> dict[str, Any]:
        """Compact summary used by ``freewisper run --dry-run`` and ``freewisper doctor``."""
        return {
            "schema_version": self.schema_version,
            "hotkey": self.general.hotkey.display(),
            "secondary_hotkey": self.general.secondary_hotkey.display(),
            "pre_roll_ms": self.general.pre_roll_ms,
            "min_utterance_ms": self.general.min_utterance_ms,
            "language": self.general.language,
            "stt_provider": self.transcription.provider,
            "stt_model": self.transcription.model,
            "preview_enabled": self.transcription.preview.enabled,
            "cleanup_tier": self.cleanup.tier,
            "cleanup_providers": [p.id for p in self.cleanup.providers],
            "commands": len(self.commands),
            "profiles": len(self.profiles),
            "dictionary_entries": len(self.cleanup.dictionary),
            "snippets": len(self.cleanup.snippets),
            "context_enabled": self.context.enabled,
            "cloud_cleanup": self.privacy.cloud_cleanup,
        }
