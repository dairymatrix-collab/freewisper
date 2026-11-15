"""The level meter used by the HUD."""

from __future__ import annotations

import threading

import pytest

from freewisper.audio.levels import LevelMeter


def test_levels_are_kept_oldest_first() -> None:
    meter = LevelMeter(5)
    for value in (0.1, 0.2, 0.3):
        meter.push(value)

    assert meter.levels() == [0.1, 0.2, 0.3]


def test_the_history_is_bounded() -> None:
    meter = LevelMeter(3)
    for value in range(10):
        meter.push(float(value))

    assert meter.levels() == [7.0, 8.0, 9.0]
    assert len(meter) == 3


def test_the_peak_is_the_loudest_level() -> None:
    meter = LevelMeter(5)
    meter.push(0.2)
    meter.push(0.9)
    meter.push(0.4)

    assert meter.peak() == pytest.approx(0.9)
    assert meter.latest() == pytest.approx(0.4)


def test_an_empty_meter_reports_zero() -> None:
    meter = LevelMeter(5)

    assert meter.peak() == 0.0
    assert meter.latest() == 0.0
    assert meter.levels() == []


def test_clearing_empties_the_history() -> None:
    meter = LevelMeter(5)
    meter.push(0.5)
    meter.clear()

    assert meter.levels() == []


def test_a_bad_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="size"):
        LevelMeter(0)


def test_the_meter_is_safe_to_use_from_two_threads() -> None:
    meter = LevelMeter(50)

    def push_many(start: int) -> None:
        for value in range(start, start + 500):
            meter.push(float(value % 10))

    threads = [threading.Thread(target=push_many, args=(i * 10,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(meter) == 50
    assert all(0.0 <= value <= 10.0 for value in meter.levels())
