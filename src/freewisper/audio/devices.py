"""Input device discovery, selection and hot-plug handling.

A headset can be unplugged mid-dictation. Freewisper keeps a single
always-on stream open, so a device disappearing has to be noticed and
recovered from rather than crashing the app on the next capture.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from freewisper.audio.backend import AudioBackend, DeviceInfo
from freewisper.core.errors import DeviceError
from freewisper.core.events import Event, EventBus

log = logging.getLogger("freewisper.audio.devices")

#: Called with the old and the new device when the active one changes.
DeviceChangeHandler = Callable[[DeviceInfo | None, DeviceInfo | None], None]


class DeviceManager:
    """Resolves the configured device and watches for it disappearing."""

    def __init__(
        self,
        backend: AudioBackend,
        bus: EventBus | None = None,
        *,
        poll_interval: float = 2.0,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError(f"poll_interval must be positive, got {poll_interval}")
        self._backend = backend
        self._bus = bus
        self._poll_interval = float(poll_interval)
        self._active: DeviceInfo | None = None
        self._handler: DeviceChangeHandler | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def list_inputs(self) -> list[DeviceInfo]:
        """Every device that can capture audio."""
        return self._backend.list_inputs()

    def default_input(self) -> DeviceInfo:
        """The system default input device."""
        return self._backend.default_input()

    def resolve(self, index: int | None = None, name_substring: str | None = None) -> DeviceInfo:
        """Turn a configured device selection into a concrete device.

        ``index`` wins over ``name_substring``. When neither is given the
        system default is used.
        """
        if index is not None:
            for device in self.list_inputs():
                if device.index == index:
                    return device
            raise DeviceError(
                f"Microphone {index} was not found. Available devices: "
                + ", ".join(str(d) for d in self.list_inputs())
            )

        if name_substring:
            needle = name_substring.strip().lower()
            if not needle:
                return self.default_input()
            for device in self.list_inputs():
                if needle in device.name.lower():
                    return device
            raise DeviceError(
                f"No microphone matched {name_substring!r}. Available devices: "
                + ", ".join(str(d) for d in self.list_inputs())
            )

        return self.default_input()

    # ------------------------------------------------------------------
    # Active device
    # ------------------------------------------------------------------
    @property
    def active(self) -> DeviceInfo | None:
        """The device currently in use, if any."""
        with self._lock:
            return self._active

    def set_active(self, device: DeviceInfo | None) -> None:
        """Record which device is in use."""
        with self._lock:
            self._active = device

    def set_change_handler(self, handler: DeviceChangeHandler | None) -> None:
        """Register a callback invoked when the active device changes."""
        self._handler = handler

    # ------------------------------------------------------------------
    # Hot-plug monitoring
    # ------------------------------------------------------------------
    @property
    def is_monitoring(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start_monitoring(self) -> None:
        """Start the background thread that watches for device changes."""
        if self.is_monitoring:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop, name="freewisper-device-monitor", daemon=True
        )
        self._thread.start()
        log.info("Device monitoring started (every %.1fs)", self._poll_interval)

    def stop_monitoring(self) -> None:
        """Stop the monitoring thread."""
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def poll_once(self) -> DeviceInfo | None:
        """Check for a device change once. Returns the new device, if it changed.

        Used by the monitoring thread and directly by the tests.
        """
        try:
            devices = self.list_inputs()
        except Exception:
            log.warning("Could not enumerate audio devices", exc_info=True)
            return None

        with self._lock:
            current = self._active
            if current is None:
                return None

            if any(device.index == current.index for device in devices):
                return None

            # The active device is gone. Fall back to any other device that
            # is still present.
            replacement = next(
                (device for device in devices if device.index != current.index), None
            )
            self._active = replacement

        if replacement is None:
            log.error(
                "Microphone %s was removed and no other input device is available",
                current,
            )
        else:
            log.warning("Microphone %s was removed; switched to %s", current, replacement)

        self._publish_change(current, replacement)
        return replacement

    def _publish_change(self, old: DeviceInfo | None, new: DeviceInfo | None) -> None:
        if self._bus is not None:
            self._bus.publish(
                Event.DEVICE_CHANGED,
                old_device=old.name if old else None,
                new_device=new.name if new else None,
                device=new,
            )
        handler = self._handler
        if handler is not None:
            try:
                handler(old, new)
            except Exception:
                log.exception("Device change handler raised")

    def _monitor_loop(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._poll_interval)

    def __enter__(self) -> DeviceManager:
        self.start_monitoring()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop_monitoring()
