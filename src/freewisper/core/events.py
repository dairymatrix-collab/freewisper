"""The event bus — the app's nervous system.

Every meaningful thing that happens is published as an :class:`Event`. The
HUD, the tray, the settings window and the log all subscribe to the same
bus, so none of them needs to know about each other.

Rules:

* **Thread-safe.** Publishing may happen from the audio thread, the
  recognition thread, or the UI thread.
* **Never propagates.** A subscriber that raises is logged and skipped; the
  remaining subscribers still receive the event.
* **Deterministic order.** Subscribers are called in subscription order.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

#: A subscriber receives the event and a read-only payload mapping.
Subscriber = Callable[["Event", Mapping[str, Any]], None]


class Event(str, Enum):
    """Everything the app can announce."""

    # Lifecycle
    STATE_CHANGED = "state_changed"
    CONFIG_CHANGED = "config_changed"
    DEVICE_CHANGED = "device_changed"
    ERROR = "error"

    # Capture
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    UTTERANCE_DROPPED = "utterance_dropped"

    # Recognition
    PARTIAL = "partial"
    TRANSCRIPT_READY = "transcript_ready"
    CLEANUP_DONE = "cleanup_done"
    COMMAND_MATCHED = "command_matched"

    # Output
    INJECTED = "injected"
    INJECTION_FAILED = "injection_failed"
    CANCELLED = "cancelled"

    # Providers
    PROVIDER_STATUS = "provider_status"


@dataclass(frozen=True)
class Subscription:
    """A handle returned by :meth:`EventBus.subscribe`."""

    event: Event
    token: str
    callback: Subscriber
    order: int

    def __hash__(self) -> int:
        return hash(self.token)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Subscription):
            return self.token == other.token
        return NotImplemented


class EventBus:
    """A small, thread-safe publish/subscribe hub."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[Event, list[Subscription]] = {}
        self._counter = itertools.count()
        self._logger = logger or logging.getLogger("freewisper.core.events")

    def subscribe(self, event: Event, callback: Subscriber) -> Subscription:
        """Register ``callback`` for ``event``.

        Returns a :class:`Subscription` that can be passed to
        :meth:`unsubscribe`.
        """
        with self._lock:
            order = next(self._counter)
            token = f"{event.value}#{order}"
            subscription = Subscription(event=event, token=token, callback=callback, order=order)
            self._subscribers.setdefault(event, []).append(subscription)
            return subscription

    def unsubscribe(self, target: Subscription | str) -> bool:
        """Remove a subscription. Returns ``True`` if something was removed."""
        token = target.token if isinstance(target, Subscription) else target
        with self._lock:
            for event, subs in self._subscribers.items():
                for index, sub in enumerate(subs):
                    if sub.token == token:
                        del subs[index]
                        if not subs:
                            del self._subscribers[event]
                        return True
        return False

    def publish(self, event: Event, /, **payload: Any) -> int:
        """Publish ``event`` with ``payload``.

        Returns the number of subscribers that handled it without raising.
        Subscriber exceptions are logged, never propagated.
        """
        with self._lock:
            # Snapshot under the lock, call outside it: a subscriber is allowed
            # to subscribe, unsubscribe, or publish from inside its callback.
            subscribers = list(self._subscribers.get(event, ()))

        data: Mapping[str, Any] = payload
        delivered = 0
        for subscription in subscribers:
            try:
                subscription.callback(event, data)
            except Exception:
                self._logger.exception("Event subscriber for %s raised; continuing.", event.value)
                continue
            delivered += 1
        return delivered

    def subscriber_count(self, event: Event | None = None) -> int:
        """How many subscribers are registered (optionally for one event)."""
        with self._lock:
            if event is None:
                return sum(len(subs) for subs in self._subscribers.values())
            return len(self._subscribers.get(event, ()))

    def clear(self) -> None:
        """Drop every subscription. Used by tests and on shutdown."""
        with self._lock:
            self._subscribers.clear()
