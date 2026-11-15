"""The ring buffer: bounded memory and correct pre-roll recovery."""

from __future__ import annotations

import numpy as np
import pytest

from freewisper.audio.ring import RingAudioBuffer, as_mono


def test_a_new_buffer_is_empty() -> None:
    ring = RingAudioBuffer(16_000, 1.5)
    assert len(ring) == 0
    assert ring.capacity == 24_000
    assert ring.seconds == pytest.approx(1.5)


def test_memory_never_grows_no_matter_how_much_is_pushed() -> None:
    """The whole point of a ring buffer: the allocation is fixed."""
    ring = RingAudioBuffer(16_000, 1.5)
    before = ring.nbytes

    for _ in range(10):
        ring.push(np.zeros(16_000, dtype=np.float32))

    assert ring.nbytes == before
    assert ring.filled == ring.capacity


def test_snapshot_returns_the_most_recent_audio() -> None:
    ring = RingAudioBuffer(1_000, 1.5)
    for value in range(10):
        ring.push(np.full(100, value, dtype=np.float32))

    snapshot = ring.snapshot(0.5)

    assert len(snapshot) == 500
    assert snapshot[0] == pytest.approx(5.0)
    assert snapshot[-1] == pytest.approx(9.0)


def test_snapshot_returns_less_than_requested_when_the_history_is_short() -> None:
    ring = RingAudioBuffer(1_000, 1.5)
    ring.push(np.zeros(200, dtype=np.float32))

    snapshot = ring.snapshot(0.5)

    assert len(snapshot) == 200


def test_snapshot_of_an_empty_buffer_is_empty() -> None:
    ring = RingAudioBuffer(1_000, 1.5)
    assert len(ring.snapshot(0.5)) == 0


def test_snapshot_of_zero_seconds_is_empty() -> None:
    ring = RingAudioBuffer(1_000, 1.5)
    ring.push(np.ones(100, dtype=np.float32))
    assert len(ring.snapshot(0.0)) == 0


def test_a_chunk_longer_than_the_buffer_keeps_only_its_tail() -> None:
    ring = RingAudioBuffer(100, 1.0)  # 100 samples
    ring.push(np.arange(250, dtype=np.float32))

    snapshot = ring.snapshot(1.0)

    assert len(snapshot) == 100
    assert snapshot[0] == pytest.approx(150.0)
    assert snapshot[-1] == pytest.approx(249.0)


def test_wraparound_keeps_the_order_right() -> None:
    ring = RingAudioBuffer(100, 1.0)
    for value in range(5):
        ring.push(np.full(30, value, dtype=np.float32))

    snapshot = ring.snapshot(0.6)  # 60 samples

    assert len(snapshot) == 60
    assert list(snapshot[:10]) == [3.0] * 10
    assert list(snapshot[-10:]) == [4.0] * 10


def test_clear_empties_the_buffer() -> None:
    ring = RingAudioBuffer(1_000, 1.5)
    ring.push(np.ones(500, dtype=np.float32))
    ring.clear()

    assert len(ring) == 0
    assert len(ring.snapshot(1.0)) == 0


def test_pushing_an_empty_chunk_is_harmless() -> None:
    ring = RingAudioBuffer(1_000, 1.5)
    ring.push(np.zeros(0, dtype=np.float32))
    assert len(ring) == 0


@pytest.mark.parametrize("bad", [0, -1])
def test_a_bad_sample_rate_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="sample_rate"):
        RingAudioBuffer(bad, 1.5)


@pytest.mark.parametrize("bad", [0.0, -0.5])
def test_a_bad_duration_is_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="seconds"):
        RingAudioBuffer(16_000, bad)


def test_stereo_blocks_are_downmixed_to_mono() -> None:
    stereo = np.stack([np.ones(10), np.zeros(10)], axis=1)
    mono = as_mono(stereo)

    assert mono.shape == (10,)
    assert mono[0] == pytest.approx(0.5)


def test_as_mono_copies_rather_than_aliasing() -> None:
    """PortAudio reuses its buffer, so the result must not alias the input."""
    block = np.ones(10, dtype=np.float32)
    mono = as_mono(block)
    block[0] = 99.0

    assert mono[0] == pytest.approx(1.0)
