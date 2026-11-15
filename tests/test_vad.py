"""Voice activity detection: what counts as speech, and what does not."""

from __future__ import annotations

import numpy as np
import pytest

from audio_helpers import make_silence, make_tone
from freewisper.audio.vad import (
    amplitude_to_dbfs,
    find_speech,
    has_speech,
    speech_duration,
    trim_silence,
)

RATE = 16_000


def test_speech_is_found_between_two_silent_stretches() -> None:
    audio = np.concatenate(
        [
            make_silence(RATE, 1.0),
            make_tone(RATE, 1.0, 440.0, amplitude=0.3),
            make_silence(RATE, 1.0),
        ]
    )

    intervals = find_speech(audio, RATE)

    assert len(intervals) == 1
    assert intervals[0].start == pytest.approx(1.0, abs=0.05)
    assert intervals[0].end == pytest.approx(2.0, abs=0.05)


def test_silence_alone_contains_no_speech() -> None:
    audio = make_silence(RATE, 3.0)

    assert find_speech(audio, RATE) == []
    assert not has_speech(audio, RATE)
    assert speech_duration(audio, RATE) == 0.0


def test_speech_alone_contains_speech() -> None:
    audio = make_tone(RATE, 2.0, 300.0, amplitude=0.3)

    intervals = find_speech(audio, RATE)

    assert len(intervals) == 1
    assert intervals[0].duration == pytest.approx(2.0, abs=0.05)


def test_a_ten_millisecond_blip_is_rejected() -> None:
    """A key tap must not be mistaken for speech."""
    audio = np.concatenate([make_silence(RATE, 0.5), make_tone(RATE, 0.01, 440.0, amplitude=0.9)])

    assert find_speech(audio, RATE) == []
    assert not has_speech(audio, RATE)


def test_a_blip_shorter_than_the_minimum_is_rejected_but_a_longer_one_is_not() -> None:
    just_under = np.concatenate(
        [make_silence(RATE, 0.2), make_tone(RATE, 0.19, 440.0, amplitude=0.5)]
    )
    just_over = np.concatenate(
        [make_silence(RATE, 0.2), make_tone(RATE, 0.25, 440.0, amplitude=0.5)]
    )

    assert find_speech(just_under, RATE) == []
    assert len(find_speech(just_over, RATE)) == 1


def test_a_short_pause_is_bridged_by_the_hangover() -> None:
    audio = np.concatenate(
        [
            make_tone(RATE, 0.5, 440.0, amplitude=0.3),
            make_silence(RATE, 0.3),
            make_tone(RATE, 0.5, 440.0, amplitude=0.3),
        ]
    )

    intervals = find_speech(audio, RATE, hangover_ms=600)

    assert len(intervals) == 1
    assert intervals[0].duration == pytest.approx(1.3, abs=0.05)


def test_a_long_pause_is_not_bridged() -> None:
    audio = np.concatenate(
        [
            make_tone(RATE, 0.5, 440.0, amplitude=0.3),
            make_silence(RATE, 1.5),
            make_tone(RATE, 0.5, 440.0, amplitude=0.3),
        ]
    )

    intervals = find_speech(audio, RATE, hangover_ms=600)

    assert len(intervals) == 2


def test_a_quiet_tone_below_the_threshold_is_not_speech() -> None:
    """-60 dBFS is below the -42 dBFS threshold."""
    quiet = make_tone(RATE, 1.0, 440.0, amplitude=0.001)
    assert amplitude_to_dbfs(0.001) < -42.0
    assert find_speech(quiet, RATE) == []


def test_a_loud_tone_above_the_threshold_is_speech() -> None:
    loud = make_tone(RATE, 1.0, 440.0, amplitude=0.5)
    assert amplitude_to_dbfs(0.5) > -42.0
    assert len(find_speech(loud, RATE)) == 1


def test_empty_audio_is_handled() -> None:
    empty = np.zeros(0, dtype=np.float32)

    assert find_speech(empty, RATE) == []
    assert not has_speech(empty, RATE)
    assert trim_silence(empty, RATE).size == 0


def test_trim_silence_removes_the_leading_and_trailing_quiet() -> None:
    audio = np.concatenate(
        [
            make_silence(RATE, 0.5),
            make_tone(RATE, 1.0, 440.0, amplitude=0.3),
            make_silence(RATE, 0.5),
        ]
    )

    trimmed = trim_silence(audio, RATE)

    assert trimmed.size == pytest.approx(RATE, rel=0.05)
    assert np.abs(trimmed).max() == pytest.approx(0.3, rel=0.05)


def test_trim_silence_keeps_the_gaps_inside_the_speech() -> None:
    audio = np.concatenate(
        [
            make_silence(RATE, 0.3),
            make_tone(RATE, 0.4, 440.0, amplitude=0.3),
            make_silence(RATE, 0.3),
            make_tone(RATE, 0.4, 440.0, amplitude=0.3),
            make_silence(RATE, 0.3),
        ]
    )

    trimmed = trim_silence(audio, RATE)

    # 0.4 + 0.3 + 0.4 of speech, not 0.4 + 0.4.
    assert trimmed.size == pytest.approx(int(RATE * 1.1), rel=0.08)


def test_trim_silence_on_pure_silence_gives_nothing_back() -> None:
    assert trim_silence(make_silence(RATE, 1.0), RATE).size == 0


def test_speech_duration_sums_the_intervals() -> None:
    audio = np.concatenate(
        [
            make_tone(RATE, 1.0, 440.0, amplitude=0.3),
            make_silence(RATE, 1.0),
            make_tone(RATE, 1.0, 440.0, amplitude=0.3),
        ]
    )

    assert speech_duration(audio, RATE) == pytest.approx(2.0, abs=0.1)


def test_the_threshold_is_configurable() -> None:
    """A tone that is quiet by default can still be detected when asked."""
    quiet = make_tone(RATE, 1.0, 440.0, amplitude=0.005)

    assert find_speech(quiet, RATE, threshold_dbfs=-42.0) == []
    assert len(find_speech(quiet, RATE, threshold_dbfs=-60.0)) == 1


def test_amplitude_to_dbfs_handles_silence() -> None:
    assert amplitude_to_dbfs(0.0) == pytest.approx(-120.0)
    assert amplitude_to_dbfs(1.0) == pytest.approx(0.0)
