"""Device selection and hot-plug recovery."""

from __future__ import annotations

import time

import pytest

from audio_helpers import FakeBackend
from freewisper.audio.backend import DeviceInfo
from freewisper.audio.devices import DeviceManager
from freewisper.core.errors import DeviceError
from freewisper.core.events import Event, EventBus

MIC_A = DeviceInfo(0, "Built-in Microphone", 2, 44_100.0)
MIC_B = DeviceInfo(3, "USB Headset Mic", 1, 48_000.0)
MIC_C = DeviceInfo(7, "Bluetooth Headset", 1, 16_000.0)


def test_devices_are_listed() -> None:
    manager = DeviceManager(FakeBackend([MIC_A, MIC_B, MIC_C]))

    assert manager.list_inputs() == [MIC_A, MIC_B, MIC_C]


def test_a_device_can_be_resolved_by_index() -> None:
    manager = DeviceManager(FakeBackend([MIC_A, MIC_B, MIC_C]))

    assert manager.resolve(index=3) == MIC_B


def test_a_device_can_be_resolved_by_name() -> None:
    manager = DeviceManager(FakeBackend([MIC_A, MIC_B, MIC_C]))

    assert manager.resolve(name_substring="bluetooth") == MIC_C


def test_the_first_matching_device_wins() -> None:
    """Two devices can match the same substring; the first one is used."""
    manager = DeviceManager(FakeBackend([MIC_A, MIC_B, MIC_C]))

    assert manager.resolve(name_substring="headset") == MIC_B


def test_the_name_match_ignores_case() -> None:
    manager = DeviceManager(FakeBackend([MIC_A, MIC_B, MIC_C]))

    assert manager.resolve(name_substring="USB HEADSET") == MIC_B


def test_the_index_wins_over_the_name() -> None:
    manager = DeviceManager(FakeBackend([MIC_A, MIC_B, MIC_C]))

    assert manager.resolve(index=0, name_substring="headset") == MIC_A


def test_the_default_device_is_used_when_nothing_is_configured() -> None:
    manager = DeviceManager(FakeBackend([MIC_A, MIC_B]))

    assert manager.resolve() == MIC_A


def test_an_unknown_index_is_an_error() -> None:
    manager = DeviceManager(FakeBackend([MIC_A]))

    with pytest.raises(DeviceError, match="was not found"):
        manager.resolve(index=99)


def test_an_unknown_name_is_an_error() -> None:
    manager = DeviceManager(FakeBackend([MIC_A]))

    with pytest.raises(DeviceError, match="No microphone matched"):
        manager.resolve(name_substring="nonexistent")


def test_a_removed_device_is_replaced_and_reported() -> None:
    bus = EventBus()
    backend = FakeBackend([MIC_A, MIC_B])
    manager = DeviceManager(backend, bus)
    manager.set_active(MIC_A)

    changes: list[object] = []
    bus.subscribe(Event.DEVICE_CHANGED, lambda event, data: changes.append(data))

    backend.devices.remove(MIC_A)
    replacement = manager.poll_once()

    assert replacement == MIC_B
    assert manager.active == MIC_B
    assert len(changes) == 1
    assert changes[0]["old_device"] == "Built-in Microphone"
    assert changes[0]["new_device"] == "USB Headset Mic"


def test_a_removed_device_with_no_replacement_is_reported() -> None:
    bus = EventBus()
    backend = FakeBackend([MIC_A])
    manager = DeviceManager(backend, bus)
    manager.set_active(MIC_A)

    changes: list[object] = []
    bus.subscribe(Event.DEVICE_CHANGED, lambda event, data: changes.append(data))

    backend.devices.remove(MIC_A)
    replacement = manager.poll_once()

    assert replacement is None
    assert manager.active is None
    assert len(changes) == 1
    assert changes[0]["new_device"] is None


def test_a_device_that_is_still_present_changes_nothing() -> None:
    bus = EventBus()
    backend = FakeBackend([MIC_A, MIC_B])
    manager = DeviceManager(backend, bus)
    manager.set_active(MIC_A)

    changes: list[object] = []
    bus.subscribe(Event.DEVICE_CHANGED, lambda event, data: changes.append(data))

    assert manager.poll_once() is None
    assert changes == []


def test_the_change_handler_is_called() -> None:
    backend = FakeBackend([MIC_A, MIC_B])
    manager = DeviceManager(backend)
    manager.set_active(MIC_A)

    seen: list[tuple[object, object]] = []
    manager.set_change_handler(lambda old, new: seen.append((old, new)))

    backend.devices.remove(MIC_A)
    manager.poll_once()

    assert len(seen) == 1
    assert seen[0][1] == MIC_B


def test_a_failing_change_handler_does_not_break_the_manager() -> None:
    backend = FakeBackend([MIC_A, MIC_B])
    manager = DeviceManager(backend)
    manager.set_active(MIC_A)

    def boom(old: object, new: object) -> None:
        raise RuntimeError("handler exploded")

    manager.set_change_handler(boom)

    backend.devices.remove(MIC_A)
    assert manager.poll_once() == MIC_B


def test_the_monitoring_thread_notices_a_removal() -> None:
    backend = FakeBackend([MIC_A, MIC_B])
    manager = DeviceManager(backend, poll_interval=0.05)
    manager.set_active(MIC_A)

    manager.start_monitoring()
    try:
        assert manager.is_monitoring
        backend.devices.remove(MIC_A)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and manager.active != MIC_B:
            time.sleep(0.02)
        assert manager.active == MIC_B
    finally:
        manager.stop_monitoring()

    assert not manager.is_monitoring


def test_monitoring_can_be_started_twice_without_two_threads() -> None:
    manager = DeviceManager(FakeBackend([MIC_A]), poll_interval=0.05)
    manager.start_monitoring()
    manager.start_monitoring()
    try:
        assert manager.is_monitoring
    finally:
        manager.stop_monitoring()


def test_a_device_manager_can_be_used_as_a_context_manager() -> None:
    manager = DeviceManager(FakeBackend([MIC_A]), poll_interval=0.05)
    with manager:
        assert manager.is_monitoring
    assert not manager.is_monitoring


def test_a_bad_poll_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="poll_interval"):
        DeviceManager(FakeBackend([MIC_A]), poll_interval=0)
