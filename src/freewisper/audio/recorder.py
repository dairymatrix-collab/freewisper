"""The always-on recorder.

The microphone stream is opened once and stays open for the whole session.
Pressing the push-to-talk key does not open a device — it starts *collecting*
from a ring buffer that has been running all along. That is what makes the
pre-roll possible: the audio captured in the half second before the key went
down is still there when the key does.

The recorder never writes audio anywhere. It hands the buffer to the caller
and forgets about it.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np
from numpy.typing import NDArray

from freewisper.audio.backend import AudioBackend, DeviceInfo
from freewisper.audio.levels import LevelMeter
from freewisper.audio.resample import resample_to_target
from freewisper.audio.ring import RingAudioBuffer, as_mono
from freewisper.audio.vad import find_speech, speech_duration, trim_silence
from freewisper.core.errors import AudioError
from freewisper.core.events import Event, EventBus
from freewisper.core.session import RecordingResult

FloatArray = NDArray[np.float32]
log = logging.getLogger("freewisper.audio.recorder")


def _concat(chunks: list[FloatArray]) -> FloatArray:
    """Join a list of mono float32 blocks into one."""
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    if len(chunks) == 1:
        return np.array(chunks[0], dtype=np.float32, copy=True)
    return np.concatenate(chunks).astype(np.float32)


class Recorder:
    """Captures speech through a permanently open microphone stream."""

    def __init__(
        self,
        backend: AudioBackend,
        bus: EventBus | None = None,
        *,
        pre_roll_ms: int = 500,
        target_sample_rate: int = 16_000,
        capture_rate: int | None = None,
        trim_silence: bool = True,
        vad_enabled: bool = True,
        vad_threshold_dbfs: float = -42.0,
        vad_hangover_ms: float = 600.0,
        vad_min_speech_ms: float = 200.0,
        ring_seconds: float = 1.5,
        level_history: int = 5,
    ) -> None:
        if pre_roll_ms < 0:
            raise ValueError(f"pre_roll_ms must not be negative, got {pre_roll_ms}")
        if target_sample_rate <= 0:
            raise ValueError(f"target_sample_rate must be positive, got {target_sample_rate}")

        self._backend = backend
        self._bus = bus
        self._pre_roll_s = pre_roll_ms / 1000.0
        self._target_rate = int(target_sample_rate)
        self._explicit_capture_rate = capture_rate
        self._trim_silence = trim_silence
        self._vad_enabled = vad_enabled
        self._vad_threshold_dbfs = vad_threshold_dbfs
        self._vad_hangover_ms = vad_hangover_ms
        self._vad_min_speech_ms = vad_min_speech_ms
        self._level_history = level_history

        self._capture_rate = int(capture_rate) if capture_rate else 44_100
        # The ring must be able to hold the whole pre-roll, whatever the
        # configured duration is.
        self._ring_seconds = max(float(ring_seconds), self._pre_roll_s + 0.1)
        self._ring = RingAudioBuffer(self._capture_rate, self._ring_seconds)
        self._meter = LevelMeter(level_history)

        self._device: DeviceInfo | None = None
        self._open = False
        self._recording = False
        self._capture: list[FloatArray] = []
        #: Completed capture segments as ``(audio, sample_rate)``. A device
        #: switch mid-recording starts a new segment, because the old audio
        #: was captured at the old device's rate.
        self._segments: list[tuple[FloatArray, int]] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        """True while the microphone stream is running."""
        return self._open

    @property
    def is_recording(self) -> bool:
        """True while a capture is in progress."""
        with self._lock:
            return self._recording

    @property
    def device(self) -> DeviceInfo | None:
        """The microphone currently in use."""
        return self._device

    @property
    def capture_rate(self) -> int:
        """Sample rate the microphone is captured at."""
        return self._capture_rate

    @property
    def target_sample_rate(self) -> int:
        """Sample rate the returned audio is resampled to."""
        return self._target_rate

    @property
    def pre_roll_s(self) -> float:
        """How much audio before the press is kept, in seconds."""
        return self._pre_roll_s

    def pre_roll_available_s(self) -> float:
        """How much history the ring actually holds right now."""
        return self._ring.filled / self._capture_rate if self._capture_rate else 0.0

    def current_levels(self, count: int | None = None) -> list[float]:
        """The most recent RMS levels, oldest first."""
        if count is None:
            return self._meter.levels()
        return self._meter.levels()[-count:]

    # ------------------------------------------------------------------
    # Stream lifecycle
    # ------------------------------------------------------------------
    def open(
        self,
        device: DeviceInfo,
        sample_rate: int | None = None,
        channels: int = 1,
    ) -> None:
        """Open the microphone and keep it open."""
        if self._open:
            self.close()

        rate = sample_rate or self._explicit_capture_rate
        if rate is None:
            rate = round(device.default_sample_rate) or 44_100
        self._capture_rate = int(rate)

        self._ring = RingAudioBuffer(self._capture_rate, self._ring_seconds)
        self._meter.clear()

        self._backend.open_stream(device, self._capture_rate, channels, self._on_audio)
        self._device = device
        self._open = True
        log.info(
            "Recorder armed on %s at %d Hz (pre-roll %.0f ms)",
            device,
            self._capture_rate,
            self._pre_roll_s * 1000,
        )

    def close(self) -> None:
        """Close the microphone."""
        with self._lock:
            self._recording = False
            self._capture.clear()
        self._backend.close_stream()
        self._device = None
        self._open = False

    def switch_device(
        self, device: DeviceInfo, sample_rate: int | None = None, channels: int = 1
    ) -> None:
        """Move to a different microphone, restarting the always-on stream.

        A capture in progress survives the switch: what was already
        recorded is kept as its own segment, because it was captured at the
        old device's sample rate.
        """
        with self._lock:
            was_recording = self._recording
            if was_recording and self._capture:
                self._segments.append((_concat(self._capture), self._capture_rate))
                self._capture = []

        log.info("Switching microphone to %s", device)
        self.close()
        self.open(device, sample_rate, channels)

        if was_recording:
            with self._lock:
                self._recording = True
            log.info("Capture continues on the new microphone")

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------
    def _on_audio(self, samples: Any) -> None:
        """Audio-thread callback: one block of captured samples."""
        # PortAudio reuses its buffer between callbacks, so this must be a
        # copy, not a view.
        mono = as_mono(samples).copy()
        if mono.size == 0:
            return

        self._ring.push(mono)
        self._meter.push(float(np.sqrt(np.mean(np.square(mono)))))

        with self._lock:
            if self._recording:
                self._capture.append(mono)

    def start_recording(self) -> None:
        """Begin collecting audio, including the pre-roll already captured."""
        if not self._open:
            raise AudioError("The microphone is not open; call open() first.")
        with self._lock:
            if self._recording:
                return
            pre_roll = self._ring.snapshot(self._pre_roll_s)
            self._segments = [(pre_roll, self._capture_rate)] if pre_roll.size else []
            self._capture = []
            self._recording = True

        pre_roll_s = len(self._segments[0][0]) / self._capture_rate if self._segments else 0.0
        log.info(
            "Recording started (pre-roll %.2fs of %.2fs available)",
            pre_roll_s,
            self.pre_roll_available_s(),
        )
        self._publish(Event.RECORDING_STARTED, pre_roll_s=pre_roll_s)

    def stop_recording(self) -> RecordingResult | None:
        """Stop collecting and return what was captured.

        Returns ``None`` when no capture was in progress.

        The returned audio is mono, resampled to the target rate and, unless
        disabled, has its leading and trailing silence removed. Because of
        that trimming, ``len(result.audio) / result.sample_rate`` can be
        smaller than ``result.duration_s`` — the latter always reports the
        full captured length.
        """
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            segments = list(self._segments)
            if self._capture:
                segments.append((_concat(self._capture), self._capture_rate))
            self._capture = []
            self._segments = []

        # Each segment was captured at its own rate, so each is resampled
        # on its own before they are joined.
        parts: list[FloatArray] = []
        duration_s = 0.0
        for chunk, rate in segments:
            if chunk.size == 0:
                continue
            parts.append(resample_to_target(chunk, rate, self._target_rate))
            duration_s += len(chunk) / rate

        audio = _concat(parts) if parts else np.zeros(0, dtype=np.float32)

        speech_s = 0.0
        if self._vad_enabled and audio.size:
            speech_s = speech_duration(
                audio,
                self._target_rate,
                threshold_dbfs=self._vad_threshold_dbfs,
                hangover_ms=self._vad_hangover_ms,
                min_speech_ms=self._vad_min_speech_ms,
            )
            if self._trim_silence:
                audio = trim_silence(
                    audio,
                    self._target_rate,
                    threshold_dbfs=self._vad_threshold_dbfs,
                    hangover_ms=self._vad_hangover_ms,
                    min_speech_ms=self._vad_min_speech_ms,
                )

        result = RecordingResult(
            audio=audio,
            duration_s=duration_s,
            sample_rate=self._target_rate,
            channels=1,
            speech_s=speech_s,
        )
        log.info("Recording stopped: %.2fs captured, %.2fs of speech", duration_s, speech_s)
        self._publish(
            Event.RECORDING_STOPPED,
            duration_s=duration_s,
            speech_s=speech_s,
            sample_rate=self._target_rate,
        )
        return result

    def cancel_recording(self) -> None:
        """Abandon the current capture without returning anything."""
        with self._lock:
            was_recording = self._recording
            self._recording = False
            self._capture = []
            self._segments = []
        if was_recording:
            log.info("Recording cancelled")

    def _publish(self, event: Event, **payload: Any) -> None:
        if self._bus is not None:
            self._bus.publish(event, **payload)

    def handle_stream_failure(self, error: BaseException) -> None:
        """Called when the audio stream dies underneath us.

        The capture is abandoned, the microphone is marked closed and the
        failure is published — the app decides whether to switch to another
        device.
        """
        with self._lock:
            was_recording = self._recording
            self._recording = False
            self._capture = []
            self._segments = []
        self._open = False
        log.error("The audio stream failed: %s", error)
        self._publish(Event.ERROR, error=error, kind="audio_stream")
        if was_recording:
            self._publish(Event.UTTERANCE_DROPPED, reason="audio_stream_failed")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def speech_intervals(self, audio: FloatArray, sample_rate: int) -> list[Any]:
        """The speech intervals found in ``audio`` (used by the tests)."""
        if not self._vad_enabled:
            return []
        return find_speech(
            audio,
            sample_rate,
            threshold_dbfs=self._vad_threshold_dbfs,
            hangover_ms=self._vad_hangover_ms,
            min_speech_ms=self._vad_min_speech_ms,
        )

    def __enter__(self) -> Recorder:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def build_recorder(config: Any, backend: AudioBackend, bus: EventBus | None = None) -> Recorder:
    """Build a recorder from the application configuration.

    Every tuning value — the pre-roll length, the ring size, the VAD
    threshold, hangover and minimum speech length — comes from the config
    file. Nothing is hard-coded here, so a user can change the behaviour
    without touching the code.
    """
    general = config.general
    audio = config.audio
    return Recorder(
        backend,
        bus,
        pre_roll_ms=general.pre_roll_ms,
        trim_silence=audio.trim_silence,
        vad_enabled=audio.vad.enabled,
        vad_threshold_dbfs=audio.vad.threshold_dbfs,
        vad_hangover_ms=audio.vad.hangover_ms,
        vad_min_speech_ms=audio.vad.min_speech_ms,
        ring_seconds=audio.ring_seconds,
    )
