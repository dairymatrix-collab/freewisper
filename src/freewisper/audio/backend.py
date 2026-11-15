"""The boundary between Freewisper and the sound card.

Everything above this module talks to :class:`AudioBackend`, a small
protocol. That keeps PortAudio — and its habit of raising ``OSError``
instead of ``ImportError`` when the library is missing — out of the rest of
the codebase, and lets the recorder be tested with a fake backend and no
hardware at all.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from freewisper.audio.ring import as_mono
from freewisper.core.errors import AudioError

FloatArray = NDArray[np.float32]
log = logging.getLogger("freewisper.audio.backend")

#: Called from the audio thread with each block of captured samples.
StreamCallback = Callable[[FloatArray], None]


@dataclass(frozen=True)
class DeviceInfo:
    """One audio input device."""

    index: int
    name: str
    max_input_channels: int = 1
    default_sample_rate: float = 44_100.0
    host_api: str = ""

    def __str__(self) -> str:
        return f"[{self.index}] {self.name}"


@runtime_checkable
class AudioBackend(Protocol):
    """What the rest of the app needs from a sound card."""

    def list_inputs(self) -> list[DeviceInfo]:
        """Every device that can capture audio."""

    def default_input(self) -> DeviceInfo:
        """The system default input device."""

    def open_stream(
        self,
        device: DeviceInfo,
        sample_rate: int,
        channels: int,
        callback: StreamCallback,
    ) -> None:
        """Start capturing, delivering blocks to ``callback``."""

    def close_stream(self) -> None:
        """Stop capturing and release the device."""


class SoundDeviceBackend:
    """PortAudio-backed implementation of :class:`AudioBackend`.

    ``sounddevice`` is imported lazily and only when a device is actually
    needed, so importing Freewisper never requires a working sound card.
    """

    def __init__(self) -> None:
        self._module: Any = None
        self._stream: Any = None

    def _sd(self) -> Any:
        """Import ``sounddevice`` on first use, with a clear error message."""
        if self._module is None:
            try:
                import sounddevice as sd  # optional dependency
            except Exception as exc:  # OSError when PortAudio is missing
                raise AudioError(
                    "Could not load the audio backend. On Linux install "
                    "'portaudio19-dev' and 'python3-sounddevice'; on macOS and "
                    "Windows install the PortAudio runtime that ships with "
                    f"sounddevice. Original error: {exc}"
                ) from exc
            self._module = sd
        return self._module

    def _device_at(self, index: int) -> DeviceInfo:
        sd = self._sd()
        try:
            raw = sd.query_devices(index)
        except Exception as exc:
            raise AudioError(f"Could not query audio device {index}: {exc}") from exc
        return DeviceInfo(
            index=int(raw["index"]) if "index" in raw else index,
            name=str(raw["name"]),
            max_input_channels=int(raw.get("max_input_channels", 1)),
            default_sample_rate=float(raw.get("default_samplerate", 44_100.0)),
            host_api=str(raw.get("hostapi", "")),
        )

    def list_inputs(self) -> list[DeviceInfo]:
        sd = self._sd()
        try:
            devices = sd.query_devices()
        except Exception as exc:
            raise AudioError(f"Could not enumerate audio devices: {exc}") from exc
        found: list[DeviceInfo] = []
        for index, raw in enumerate(devices):
            if int(raw.get("max_input_channels", 0)) <= 0:
                continue
            found.append(
                DeviceInfo(
                    index=index,
                    name=str(raw["name"]),
                    max_input_channels=int(raw.get("max_input_channels", 1)),
                    default_sample_rate=float(raw.get("default_samplerate", 44_100.0)),
                    host_api=str(raw.get("hostapi", "")),
                )
            )
        return found

    def default_input(self) -> DeviceInfo:
        sd = self._sd()
        try:
            index = sd.default.device[0]
        except Exception as exc:
            raise AudioError(f"Could not resolve the default input device: {exc}") from exc
        return self._device_at(int(index))

    def open_stream(
        self,
        device: DeviceInfo,
        sample_rate: int,
        channels: int,
        callback: StreamCallback,
    ) -> None:
        sd = self._sd()

        def _on_audio(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            if status:
                # Underruns and overflows are not fatal, but they mean the
                # capture glitched — the user deserves to know.
                log.warning("Audio stream reported a problem: %s", status)
            try:
                callback(as_mono(indata))
            except Exception:
                log.exception("Audio callback raised; continuing to capture")

        try:
            self._stream = sd.RawInputStream(
                device=device.index,
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                callback=_on_audio,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise AudioError(f"Could not open the microphone {device}: {exc}") from exc
        log.info("Microphone open: %s at %d Hz", device, sample_rate)

    def close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        for action in ("stop", "close"):
            try:
                getattr(stream, action)()
            except Exception:
                log.debug("Ignoring error while closing the audio stream", exc_info=True)
        log.info("Microphone closed")
