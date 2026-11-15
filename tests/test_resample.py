"""Downmixing and resampling."""

from __future__ import annotations

import numpy as np
import pytest

from audio_helpers import dominant_frequency, make_tone
from freewisper.audio.resample import (
    TARGET_SAMPLE_RATE,
    _resample_linear,
    prepare_for_stt,
    resample_to_target,
    to_mono,
)


def test_to_mono_averages_the_channels() -> None:
    stereo = np.stack([np.ones(100), np.full(100, 3.0)], axis=1)
    mono = to_mono(stereo)

    assert mono.shape == (100,)
    assert mono[0] == pytest.approx(2.0)


def test_resampling_to_the_same_rate_changes_nothing() -> None:
    audio = make_tone(16_000, 0.5, 440.0)
    out = resample_to_target(audio, 16_000, 16_000)

    assert out.size == audio.size
    assert np.array_equal(out, audio)


def test_resampling_48k_to_16k_shortens_the_audio_by_thirds() -> None:
    audio = make_tone(48_000, 1.0, 440.0)
    out = resample_to_target(audio, 48_000, TARGET_SAMPLE_RATE)

    assert out.size == pytest.approx(16_000, rel=0.01)


def test_resampling_16k_to_48k_triples_the_audio() -> None:
    audio = make_tone(16_000, 1.0, 440.0)
    out = resample_to_target(audio, 16_000, 48_000)

    assert out.size == pytest.approx(48_000, rel=0.01)


def test_resampling_keeps_the_pitch() -> None:
    audio = make_tone(48_000, 1.0, 440.0, amplitude=0.5)
    out = resample_to_target(audio, 48_000, TARGET_SAMPLE_RATE)

    assert dominant_frequency(out, TARGET_SAMPLE_RATE) == pytest.approx(440.0, rel=0.02)


def test_resampling_empty_audio_gives_empty_audio() -> None:
    assert resample_to_target(np.zeros(0, dtype=np.float32), 48_000, 16_000).size == 0


@pytest.mark.parametrize("bad", [0, -1])
def test_a_bad_source_rate_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="source_rate"):
        resample_to_target(make_tone(16_000, 0.1, 440.0), bad)


def test_a_bad_target_rate_is_rejected() -> None:
    with pytest.raises(ValueError, match="target_rate"):
        resample_to_target(make_tone(16_000, 0.1, 440.0), 16_000, 0)


def test_prepare_for_stt_downmixes_and_resamples_in_one_step() -> None:
    stereo = np.stack([make_tone(48_000, 0.5, 440.0), make_tone(48_000, 0.5, 440.0)], axis=1)

    out = prepare_for_stt(stereo, 48_000)

    assert out.size == pytest.approx(8_000, rel=0.02)
    assert out.dtype == np.float32


def test_the_numpy_fallback_produces_the_right_length() -> None:
    """The fallback exists so the app still works without SciPy."""
    audio = make_tone(48_000, 1.0, 440.0, amplitude=0.5)

    out = _resample_linear(audio, 48_000, 16_000)

    assert out.size == pytest.approx(16_000, rel=0.01)
    assert dominant_frequency(out, 16_000) == pytest.approx(440.0, rel=0.05)
