"""The record of one dictation."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecordingResult:
    """What the recorder hands back when a capture ends.

    ``duration_s`` is the length of the *audio*, not the wall-clock time the
    key was held — they differ on Bluetooth headsets, where the device needs
    time to wake up. Using the audio length keeps the "too short" rule
    honest.
    """

    audio: Any
    duration_s: float
    sample_rate: int = 16_000
    channels: int = 1
    #: How much of the capture was actually speech, as measured by the VAD.
    #: Zero when voice-activity detection is switched off.
    speech_s: float = 0.0


@dataclass
class DictationSession:
    """Everything that happened during one push-to-talk cycle.

    The session is the unit that later becomes a row in the history
    database, and the unit that the pipeline mutates as it moves through
    the stages.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.monotonic)
    released_at: float | None = None

    audio: Any | None = None
    raw_text: str = ""
    cleaned_text: str = ""

    command_id: str | None = None
    app_bundle: str | None = None

    stt_provider: str = ""
    stt_model: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    tier: str = ""

    #: Stage timings in seconds: ``stt``, ``cleanup``, ``inject``, ``total``.
    timings: dict[str, float] = field(default_factory=dict)

    injected: bool = False
    dropped: bool = False
    error: str | None = None

    @property
    def duration_s(self) -> float:
        """How long the utterance lasted."""
        if self.released_at is None:
            return 0.0
        return self.released_at - self.started_at

    @property
    def word_count(self) -> int:
        """Words in the cleaned text."""
        return len([w for w in self.cleaned_text.split() if w])

    def mark(self, stage: str, seconds: float) -> None:
        """Record how long a stage took."""
        self.timings[stage] = seconds

    def to_record(self) -> dict[str, Any]:
        """A flat, storable representation."""
        return {
            "id": self.id,
            "started_at": self.started_at,
            "released_at": self.released_at,
            "raw_text": self.raw_text,
            "cleaned_text": self.cleaned_text,
            "command_id": self.command_id,
            "app_bundle": self.app_bundle,
            "stt_provider": self.stt_provider,
            "stt_model": self.stt_model,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "tier": self.tier,
            "timings": dict(self.timings),
            "injected": self.injected,
            "dropped": self.dropped,
            "error": self.error,
        }
