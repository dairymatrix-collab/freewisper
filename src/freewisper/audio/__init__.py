"""Audio capture: pre-roll, voice activity detection and level metering.

The package is split into a hardware-independent half — the ring buffer, the
VAD, the level meter and the resampler — and a hardware half that talks to
PortAudio. Only the latter knows that sound cards exist.
"""

from __future__ import annotations

from freewisper.audio.backend import (
    AudioBackend,
    DeviceInfo,
    SoundDeviceBackend,
    StreamCallback,
)
from freewisper.audio.devices import DeviceManager
from freewisper.audio.levels import LevelMeter
from freewisper.audio.recorder import Recorder
from freewisper.audio.resample import (
    TARGET_SAMPLE_RATE,
    prepare_for_stt,
    resample_to_target,
    to_mono,
)
from freewisper.audio.ring import RingAudioBuffer, as_mono
from freewisper.audio.vad import (
    SpeechInterval,
    amplitude_to_dbfs,
    find_speech,
    has_speech,
    speech_duration,
    trim_silence,
)

__all__ = [
    "TARGET_SAMPLE_RATE",
    "AudioBackend",
    "DeviceInfo",
    "DeviceManager",
    "LevelMeter",
    "Recorder",
    "RingAudioBuffer",
    "SoundDeviceBackend",
    "SpeechInterval",
    "StreamCallback",
    "amplitude_to_dbfs",
    "as_mono",
    "find_speech",
    "has_speech",
    "prepare_for_stt",
    "resample_to_target",
    "speech_duration",
    "to_mono",
    "trim_silence",
]
