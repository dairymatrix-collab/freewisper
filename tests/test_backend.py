"""The sound-card boundary.

PortAudio cannot be tested in CI, but the code that wraps it can: a fake
``sounddevice`` module is injected so the adapter, the error wrapping and
the callback translation are all exercised without hardware.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pytest

from freewisper.audio.backend import DeviceInfo, SoundDeviceBackend


def make_device(
    index: int,
    name: str,
    max_input: int = 1,
    rate: float = 48_000.0,
) -> dict[str, Any]:
    return {
        "index": index,
        "name": name,
        "max_input_channels": max_input,
        "default_samplerate": rate,
        "hostapi": 0,
    }


class FakeStream:
    """Stands in for ``sounddevice.RawInputStream``."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class FakeSoundDevice(ModuleType):
    """A stand-in for the ``sounddevice`` module."""

    def __init__(self, devices: list[dict[str, Any]] | None = None) -> None:
        super().__init__("sounddevice")
        self.devices = devices if devices is not None else []
        self.default = SimpleNamespace(device=(0, 0))
        self.streams: list[FakeStream] = []
        self.query_error: Exception | None = None
        self.open_error: Exception | None = None

    def query_devices(self, index: int | None = None) -> Any:
        if self.query_error is not None:
            raise self.query_error
        if index is not None:
            return self.devices[index]
        return self.devices

    def RawInputStream(self, **kwargs: Any) -> FakeStream:
        if self.open_error is not None:
            raise self.open_error
        stream = FakeStream(**kwargs)
        self.streams.append(stream)
        return stream


@pytest.fixture
def fake_sd(monkeypatch: pytest.MonkeyPatch) -> FakeSoundDevice:
    module = FakeSoundDevice(
        [
            make_device(0, "Built-in", max_input=2),
            make_device(1, "Headset", max_input=0),
            make_device(2, "USB Mic"),
        ]
    )
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return module


def test_only_devices_that_can_capture_are_listed(fake_sd: FakeSoundDevice) -> None:
    backend = SoundDeviceBackend()

    devices = backend.list_inputs()

    assert [device.name for device in devices] == ["Built-in", "USB Mic"]
    assert devices[0].max_input_channels == 2
    assert devices[0].default_sample_rate == pytest.approx(48_000.0)


def test_the_default_input_device_is_resolved(fake_sd: FakeSoundDevice) -> None:
    backend = SoundDeviceBackend()

    device = backend.default_input()

    assert device.name == "Built-in"
    assert device.index == 0


def test_opening_a_stream_starts_it(fake_sd: FakeSoundDevice) -> None:
    backend = SoundDeviceBackend()
    device = backend.list_inputs()[0]

    backend.open_stream(device, 16_000, 1, lambda samples: None)

    assert len(fake_sd.streams) == 1
    stream = fake_sd.streams[0]
    assert stream.started
    assert stream.kwargs["samplerate"] == 16_000
    assert stream.kwargs["device"] == 0


def test_closing_a_stream_stops_and_closes_it(fake_sd: FakeSoundDevice) -> None:
    backend = SoundDeviceBackend()
    backend.open_stream(backend.list_inputs()[0], 16_000, 1, lambda samples: None)

    backend.close_stream()

    stream = fake_sd.streams[0]
    assert stream.stopped
    assert stream.closed


def test_closing_when_nothing_is_open_is_harmless(fake_sd: FakeSoundDevice) -> None:
    backend = SoundDeviceBackend()
    backend.close_stream()
    assert not fake_sd.streams


def test_the_callback_receives_mono_samples(fake_sd: FakeSoundDevice) -> None:
    received: list[np.ndarray] = []
    backend = SoundDeviceBackend()
    backend.open_stream(backend.list_inputs()[0], 16_000, 1, received.append)

    stream = fake_sd.streams[0]
    stereo = np.stack([np.ones(8), np.full(8, 3.0)], axis=1)
    stream.kwargs["callback"](stereo, 8, None, None)  # type: ignore[operator]

    assert len(received) == 1
    assert received[0].shape == (8,)
    assert received[0][0] == pytest.approx(2.0)


def test_a_stream_status_is_reported_not_swallowed(
    fake_sd: FakeSoundDevice, caplog: pytest.LogCaptureFixture
) -> None:
    backend = SoundDeviceBackend()
    backend.open_stream(backend.list_inputs()[0], 16_000, 1, lambda samples: None)

    stream = fake_sd.streams[0]
    with caplog.at_level("WARNING"):
        stream.kwargs["callback"](np.ones(8, dtype=np.float32), 8, None, "overrun")

    assert "overrun" in caplog.text


def test_a_raising_callback_does_not_kill_the_stream(
    fake_sd: FakeSoundDevice, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(samples: np.ndarray) -> None:
        raise RuntimeError("callback exploded")

    backend = SoundDeviceBackend()
    backend.open_stream(backend.list_inputs()[0], 16_000, 1, boom)

    stream = fake_sd.streams[0]
    with caplog.at_level("ERROR"):
        stream.kwargs["callback"](np.ones(8, dtype=np.float32), 8, None, None)  # type: ignore[operator]

    assert "callback exploded" in caplog.text


class _FailingImportFinder:
    """Makes ``import sounddevice`` raise OSError, the way a missing
    PortAudio runtime does."""

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if fullname == "sounddevice":
            raise OSError("PortAudio library not found")
        return None


def test_a_missing_porterror_becomes_an_audio_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PortAudio missing raises OSError, not ImportError — it must be handled."""
    from freewisper.core.errors import AudioError

    monkeypatch.delitem(sys.modules, "sounddevice", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_FailingImportFinder(), *sys.meta_path])

    backend = SoundDeviceBackend()
    with pytest.raises(AudioError, match="audio backend"):
        backend.list_inputs()


def test_a_failing_enumeration_becomes_an_audio_error(
    fake_sd: FakeSoundDevice,
) -> None:
    from freewisper.core.errors import AudioError

    fake_sd.query_error = RuntimeError("no sound")
    backend = SoundDeviceBackend()

    with pytest.raises(AudioError, match="enumerate"):
        backend.list_inputs()


def test_a_failing_open_becomes_an_audio_error(fake_sd: FakeSoundDevice) -> None:
    from freewisper.core.errors import AudioError

    fake_sd.open_error = RuntimeError("device busy")
    backend = SoundDeviceBackend()

    with pytest.raises(AudioError, match="Could not open the microphone"):
        backend.open_stream(backend.list_inputs()[0], 16_000, 1, lambda samples: None)


def test_the_device_info_reads_well() -> None:
    device = DeviceInfo(2, "USB Mic", 1, 44_100.0)
    assert str(device) == "[2] USB Mic"
