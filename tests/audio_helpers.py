"""Shared helpers for the audio tests.

Synthetic signals and a fake sound card, so the whole audio layer can be
tested on a machine with no microphone and no PortAudio.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from freewisper.audio.backend import DeviceInfo

FloatArray = NDArray[np.float32]


def make_tone(
    sample_rate: int,
    seconds: float,
    frequency: float,
    amplitude: float = 0.3,
    phase: float = 0.0,
) -> FloatArray:
    """A pure sine wave."""
    count = int(sample_rate * seconds)
    t = np.arange(count, dtype=np.float64) / sample_rate
    return (amplitude * np.sin(2.0 * np.pi * frequency * t + phase)).astype(np.float32)


def make_silence(sample_rate: int, seconds: float) -> FloatArray:
    """Digital silence."""
    return np.zeros(int(sample_rate * seconds), dtype=np.float32)


def dominant_frequency(samples: FloatArray, sample_rate: int) -> float:
    """The loudest frequency in ``samples``, found with an FFT."""
    if len(samples) == 0:
        return 0.0
    window = np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64) * window))
    freqs = np.fft.rfftfreq(len(samples), 1.0 / sample_rate)
    return float(freqs[int(np.argmax(spectrum))])


class FakeBackend:
    """An :class:`~freewisper.audio.backend.AudioBackend` with no hardware.

    Audio is injected by calling :meth:`feed`, exactly as PortAudio's
    callback thread would deliver it.
    """

    def __init__(self, devices: list[DeviceInfo] | None = None) -> None:
        self.devices: list[DeviceInfo] = (
            list(devices)
            if devices is not None
            else [DeviceInfo(0, "Fake Microphone", 1, 16_000.0)]
        )
        self.opened = False
        self.open_count = 0
        self.close_count = 0
        self.device: DeviceInfo | None = None
        self.sample_rate = 0
        self.channels = 0
        self._callback: Callable[[FloatArray], None] | None = None

    # -- AudioBackend ---------------------------------------------------
    def list_inputs(self) -> list[DeviceInfo]:
        return list(self.devices)

    def default_input(self) -> DeviceInfo:
        return self.devices[0]

    def open_stream(
        self,
        device: DeviceInfo,
        sample_rate: int,
        channels: int,
        callback: Callable[[FloatArray], None],
    ) -> None:
        self.opened = True
        self.open_count += 1
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self._callback = callback

    def close_stream(self) -> None:
        self.opened = False
        self.close_count += 1
        self._callback = None

    # -- test helpers ---------------------------------------------------
    def feed(self, samples: FloatArray) -> None:
        """Deliver a block of audio to the recorder, as PortAudio would."""
        if self._callback is None:
            raise RuntimeError("The audio stream is not open")
        self._callback(samples)
