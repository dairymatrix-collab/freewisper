"""Mono downmixing and sample-rate conversion.

Speech-to-text models expect 16 kHz mono float32. This module is the single
place where audio is converted into that shape.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from numpy.typing import NDArray

from freewisper.audio.ring import as_mono

FloatArray = NDArray[np.float32]

log = logging.getLogger("freewisper.audio.resample")

#: The sample rate every Whisper-family model expects.
TARGET_SAMPLE_RATE = 16_000

_scipy_warned = False


def to_mono(chunk: Any) -> FloatArray:
    """Downmix a multi-channel chunk to mono float32."""
    return as_mono(chunk)


def _resample_linear(audio: FloatArray, source_rate: int, target_rate: int) -> FloatArray:
    """Linear-interpolation resampler, used when SciPy is unavailable.

    SciPy's polyphase filter is materially better for speech, so this is only
    a fallback that keeps the app functional with a slimmer dependency set.
    """
    if len(audio) == 0:
        return np.zeros(0, dtype=np.float32)
    ratio = target_rate / source_rate
    out_len = max(1, round(len(audio) * ratio))
    positions = np.linspace(0.0, len(audio) - 1, num=out_len, dtype=np.float64)
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


def resample_to_target(
    audio: FloatArray,
    source_rate: int,
    target_rate: int = TARGET_SAMPLE_RATE,
) -> FloatArray:
    """Resample mono audio to ``target_rate``.

    Uses :func:`scipy.signal.resample_poly` when SciPy is installed and
    falls back to linear interpolation otherwise.
    """
    global _scipy_warned

    if source_rate <= 0:
        raise ValueError(f"source_rate must be positive, got {source_rate}")
    if target_rate <= 0:
        raise ValueError(f"target_rate must be positive, got {target_rate}")
    if len(audio) == 0:
        return np.zeros(0, dtype=np.float32)
    if source_rate == target_rate:
        return np.ascontiguousarray(audio, dtype=np.float32)

    try:
        from scipy.signal import resample_poly
    except ImportError:
        if not _scipy_warned:
            log.warning(
                "SciPy is not installed; falling back to linear resampling. "
                "Install the 'audio' extra for better resampling quality."
            )
            _scipy_warned = True
        return _resample_linear(audio, source_rate, target_rate)

    from math import gcd

    divisor = gcd(int(source_rate), int(target_rate))
    up = int(target_rate) // divisor
    down = int(source_rate) // divisor
    return np.asarray(resample_poly(audio.astype(np.float64), up, down), dtype=np.float32)


def prepare_for_stt(
    chunk: Any, source_rate: int, target_rate: int = TARGET_SAMPLE_RATE
) -> FloatArray:
    """Downmix and resample a raw capture into the shape STT models want."""
    return resample_to_target(to_mono(chunk), source_rate, target_rate)
