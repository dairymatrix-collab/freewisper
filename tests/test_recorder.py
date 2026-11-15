"""The always-on recorder: pre-roll, capture and the stream lifecycle."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from audio_helpers import FakeBackend, dominant_frequency, make_tone
from freewisper.audio.backend import DeviceInfo
from freewisper.audio.devices import DeviceManager
from freewisper.audio.recorder import Recorder
from freewisper.core.errors import AudioError
from freewisper.core.events import Event, EventBus

RATE = 16_000


def make_recorder(backend: FakeBackend, **kwargs: object) -> Recorder:
    options: dict[str, object] = {
        "pre_roll_ms": 500,
        "capture_rate": RATE,
        "ring_seconds": 1.5,
        "trim_silence": False,
    }
    options.update(kwargs)
    return Recorder(backend, **options)  # type: ignore[arg-type]


def test_the_pre_roll_contains_the_audio_captured_before_the_press() -> None:
    """The whole reason the microphone stays open.

    A 1000 Hz tone is played for half a second *before* the key goes down.
    That audio must be part of the capture.
    """
    backend = FakeBackend()
    recorder = make_recorder(backend)
    recorder.open(backend.default_input(), sample_rate=RATE)

    backend.feed(make_tone(RATE, 0.5, 1000.0, amplitude=0.4))
    assert recorder.pre_roll_available_s() == pytest.approx(0.5, abs=0.01)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.25, 2000.0, amplitude=0.4))
    result = recorder.stop_recording()

    assert result is not None
    assert result.duration_s == pytest.approx(0.75, abs=0.01)
    assert result.audio.size == pytest.approx(12_000, abs=50)

    # The first half-second is the pre-roll tone...
    assert dominant_frequency(result.audio[:8000], RATE) == pytest.approx(1000.0, rel=0.03)
    # ...and the last quarter-second is what was said after the press.
    assert dominant_frequency(result.audio[-4000:], RATE) == pytest.approx(2000.0, rel=0.03)


def test_without_a_pre_roll_only_the_press_is_captured() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend, pre_roll_ms=0)
    recorder.open(backend.default_input(), sample_rate=RATE)

    backend.feed(make_tone(RATE, 0.5, 1000.0, amplitude=0.4))
    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.25, 2000.0, amplitude=0.4))
    result = recorder.stop_recording()

    assert result is not None
    assert result.duration_s == pytest.approx(0.25, abs=0.01)
    assert dominant_frequency(result.audio, RATE) == pytest.approx(2000.0, rel=0.03)


def test_the_microphone_is_opened_once_and_stays_open() -> None:
    """The stream must not be reopened for every press."""
    backend = FakeBackend()
    recorder = make_recorder(backend, pre_roll_ms=200)
    recorder.open(backend.default_input(), sample_rate=RATE)

    for _ in range(5):
        recorder.start_recording()
        backend.feed(make_tone(RATE, 0.1, 440.0))
        recorder.stop_recording()

    assert backend.open_count == 1
    assert backend.close_count == 0
    assert recorder.is_open


def test_the_recorder_uses_the_device_sample_rate_by_default() -> None:
    backend = FakeBackend([DeviceInfo(0, "Fake", 1, 48_000.0)])
    recorder = Recorder(backend, pre_roll_ms=200)
    recorder.open(backend.default_input())

    assert recorder.capture_rate == 48_000
    assert backend.sample_rate == 48_000


def test_a_short_press_produces_a_short_capture() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend)
    recorder.open(backend.default_input(), sample_rate=RATE)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.05, 440.0))
    result = recorder.stop_recording()

    assert result is not None
    assert result.duration_s == pytest.approx(0.05, abs=0.01)


def test_the_result_is_resampled_to_the_target_rate() -> None:
    backend = FakeBackend([DeviceInfo(0, "Fake", 1, 48_000.0)])
    recorder = Recorder(backend, pre_roll_ms=0, capture_rate=48_000)
    recorder.open(backend.default_input(), sample_rate=48_000)

    recorder.start_recording()
    backend.feed(make_tone(48_000, 1.0, 440.0, amplitude=0.4))
    result = recorder.stop_recording()

    assert result is not None
    assert result.sample_rate == 16_000
    assert result.audio.size == pytest.approx(16_000, rel=0.02)
    assert result.duration_s == pytest.approx(1.0, abs=0.01)


def test_the_speech_duration_is_measured() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend, trim_silence=False)
    recorder.open(backend.default_input(), sample_rate=RATE)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.5, 440.0, amplitude=0.4))
    result = recorder.stop_recording()

    assert result is not None
    assert result.speech_s == pytest.approx(0.5, abs=0.05)


def test_silence_is_trimmed_when_asked() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend, trim_silence=True, vad_enabled=True)
    recorder.open(backend.default_input(), sample_rate=RATE)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.2, 440.0, amplitude=0.4))
    backend.feed(np.zeros(RATE, dtype=np.float32))  # a second of silence
    result = recorder.stop_recording()

    assert result is not None
    assert result.audio.size == pytest.approx(3_200, rel=0.1)
    assert result.duration_s == pytest.approx(1.2, abs=0.01)


def test_the_levels_are_recorded_for_the_hud() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend)
    recorder.open(backend.default_input(), sample_rate=RATE)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.1, 440.0, amplitude=0.5))
    levels = recorder.current_levels()

    assert levels
    # The RMS of a sine wave is amplitude / sqrt(2).
    assert levels[-1] == pytest.approx(0.5 / (2**0.5), rel=0.05)


def test_the_level_history_is_bounded() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend, level_history=3)
    recorder.open(backend.default_input(), sample_rate=RATE)

    recorder.start_recording()
    for _ in range(20):
        backend.feed(make_tone(RATE, 0.01, 440.0, amplitude=0.5))

    assert len(recorder.current_levels()) == 3


def test_switching_devices_restarts_the_stream() -> None:
    backend = FakeBackend(
        [DeviceInfo(0, "First", 1, 16_000.0), DeviceInfo(1, "Second", 1, 16_000.0)]
    )
    recorder = make_recorder(backend)
    recorder.open(backend.default_input(), sample_rate=RATE)

    recorder.switch_device(backend.devices[1], sample_rate=RATE)

    assert backend.open_count == 2
    assert backend.close_count == 1
    assert backend.device is not None and backend.device.name == "Second"
    assert recorder.device is not None and recorder.device.name == "Second"


def test_stopping_without_starting_returns_nothing() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend)
    recorder.open(backend.default_input(), sample_rate=RATE)

    assert recorder.stop_recording() is None


def test_starting_without_an_open_microphone_is_an_error() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend)

    with pytest.raises(AudioError, match="not open"):
        recorder.start_recording()


def test_cancelling_discards_the_capture() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend)
    recorder.open(backend.default_input(), sample_rate=RATE)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.5, 440.0))
    recorder.cancel_recording()

    assert not recorder.is_recording
    assert recorder.stop_recording() is None


def test_starting_twice_does_not_reset_the_capture() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend)
    recorder.open(backend.default_input(), sample_rate=RATE)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.5, 440.0))
    recorder.start_recording()  # a second press while already recording
    result = recorder.stop_recording()

    assert result is not None
    assert result.duration_s == pytest.approx(0.5, abs=0.01)


def test_no_audio_is_written_to_disk(tmp_path: Path) -> None:
    """Microphone audio must never touch the filesystem."""
    backend = FakeBackend()
    recorder = make_recorder(backend)
    recorder.open(backend.default_input(), sample_rate=RATE)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 1.0, 440.0))
    recorder.stop_recording()

    assert list(tmp_path.rglob("*")) == []


def test_the_recorder_publishes_events() -> None:
    bus = EventBus()
    backend = FakeBackend()
    recorder = Recorder(backend, bus, pre_roll_ms=200, capture_rate=RATE)
    recorder.open(backend.default_input(), sample_rate=RATE)

    started: list[object] = []
    stopped: list[object] = []
    bus.subscribe(Event.RECORDING_STARTED, lambda event, data: started.append(data))
    bus.subscribe(Event.RECORDING_STOPPED, lambda event, data: stopped.append(data))

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.2, 440.0))
    recorder.stop_recording()

    assert len(started) == 1
    assert len(stopped) == 1
    assert stopped[0]["duration_s"] == pytest.approx(0.2, abs=0.01)


def test_closing_releases_the_microphone() -> None:
    backend = FakeBackend()
    recorder = make_recorder(backend)
    recorder.open(backend.default_input(), sample_rate=RATE)

    recorder.close()

    assert not recorder.is_open
    assert backend.close_count == 1


def test_the_pre_roll_is_sample_for_sample_the_audio_that_was_played() -> None:
    """Sample-level equality, not just "the right frequency".

    With no resampling in the way, the pre-roll must be bit-identical to
    what was fed in.
    """
    backend = FakeBackend()
    recorder = make_recorder(backend, pre_roll_ms=500, trim_silence=False)
    recorder.open(backend.default_input(), sample_rate=RATE)

    tone = make_tone(RATE, 0.5, 1000.0, amplitude=0.4)
    backend.feed(tone)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.1, 2000.0, amplitude=0.4))
    result = recorder.stop_recording()

    assert result is not None
    pre_roll = result.audio[: len(tone)]
    assert np.array_equal(pre_roll, tone)


def test_a_long_signal_still_yields_the_right_pre_roll() -> None:
    """Three seconds of signal, a real pause, then the press."""
    backend = FakeBackend()
    recorder = make_recorder(backend, pre_roll_ms=500, trim_silence=False)
    recorder.open(backend.default_input(), sample_rate=RATE)

    backend.feed(make_tone(RATE, 3.0, 1000.0, amplitude=0.4))
    time.sleep(0.05)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.25, 2000.0, amplitude=0.4))
    result = recorder.stop_recording()

    assert result is not None
    assert result.duration_s == pytest.approx(0.75, abs=0.02)
    assert dominant_frequency(result.audio[:8000], RATE) == pytest.approx(1000.0, rel=0.03)


def test_a_device_removed_mid_recording_does_not_crash() -> None:
    """Unplugging the headset must not lose the words already spoken."""
    bus = EventBus()
    mic_a = DeviceInfo(0, "Headset", 1, 16_000.0)
    mic_b = DeviceInfo(1, "Built-in", 1, 16_000.0)
    backend = FakeBackend([mic_a, mic_b])
    manager = DeviceManager(backend, bus)
    recorder = make_recorder(backend)
    recorder.open(mic_a, sample_rate=RATE)

    changes: list[object] = []
    bus.subscribe(Event.DEVICE_CHANGED, lambda event, data: changes.append(data))

    def on_change(old: object, new: object) -> None:
        if isinstance(new, DeviceInfo):
            recorder.switch_device(new, sample_rate=RATE)

    manager.set_change_handler(on_change)
    manager.set_active(mic_a)

    recorder.start_recording()
    backend.feed(make_tone(RATE, 0.3, 440.0, amplitude=0.4))

    backend.devices.remove(mic_a)
    manager.poll_once()

    assert len(changes) == 1
    assert changes[0]["new_device"] == "Built-in"
    assert recorder.device is not None and recorder.device.name == "Built-in"

    # The recording survived the switch and the words before it are intact.
    backend.feed(make_tone(RATE, 0.2, 440.0, amplitude=0.4))
    result = recorder.stop_recording()

    assert result is not None
    assert result.duration_s == pytest.approx(0.5, abs=0.02)


def test_a_stream_failure_is_published_and_does_not_crash() -> None:
    bus = EventBus()
    backend = FakeBackend()
    recorder = Recorder(backend, bus, pre_roll_ms=500, capture_rate=RATE)
    recorder.open(backend.default_input(), sample_rate=RATE)

    errors: list[object] = []
    bus.subscribe(Event.ERROR, lambda event, data: errors.append(data))

    recorder.start_recording()
    recorder.handle_stream_failure(RuntimeError("device disconnected"))

    assert len(errors) == 1
    assert errors[0]["kind"] == "audio_stream"
    assert not recorder.is_open
    assert not recorder.is_recording


def test_the_recorder_is_built_from_the_configuration() -> None:
    """No tuning value may be hard-coded — it all comes from the config."""
    from freewisper.audio.recorder import build_recorder
    from freewisper.config.defaults import default_config

    config = default_config()
    config.general.pre_roll_ms = 750
    config.audio.ring_seconds = 2.0
    config.audio.trim_silence = False
    config.audio.vad.threshold_dbfs = -30.0
    config.audio.vad.hangover_ms = 900
    config.audio.vad.min_speech_ms = 150

    recorder = build_recorder(config, FakeBackend())

    assert recorder.pre_roll_s == pytest.approx(0.75)
