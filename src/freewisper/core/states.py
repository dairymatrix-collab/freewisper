"""The application state machine.

The app has exactly one state at a time, and the legal moves between states
are fixed. An illegal move raises :class:`InvalidTransition` **and**
publishes an error, so a bug can never silently leave the app in a
meaningless state.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import InvalidTransition
from .events import Event, EventBus


class State(str, Enum):
    """Where the app currently is."""

    IDLE = "idle"
    ARMED = "armed"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    CLEANING = "cleaning"
    INJECTING = "injecting"
    ERROR = "error"


#: The only legal moves. Everything else raises.
LEGAL_TRANSITIONS: dict[State, frozenset[State]] = {
    State.IDLE: frozenset({State.ARMED, State.ERROR}),
    State.ARMED: frozenset({State.RECORDING, State.IDLE, State.ERROR}),
    State.RECORDING: frozenset({State.TRANSCRIBING, State.IDLE, State.ERROR}),
    State.TRANSCRIBING: frozenset({State.CLEANING, State.IDLE, State.ERROR}),
    State.CLEANING: frozenset({State.INJECTING, State.IDLE, State.ERROR}),
    State.INJECTING: frozenset({State.IDLE, State.ERROR}),
    State.ERROR: frozenset({State.IDLE}),
}


@dataclass(frozen=True)
class Transition:
    """A recorded state change."""

    source: State
    target: State
    at: float


class StateMachine:
    """Guards the application's state and announces every change."""

    def __init__(
        self,
        bus: EventBus,
        *,
        initial: State = State.IDLE,
        logger: logging.Logger | None = None,
    ) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._state = initial
        self._history: list[Transition] = []
        self._hooks: list[Callable[[State, State], None]] = []
        self._logger = logger or logging.getLogger("freewisper.core.states")

    @property
    def state(self) -> State:
        """The current state."""
        with self._lock:
            return self._state

    @property
    def history(self) -> tuple[Transition, ...]:
        """Every transition so far, oldest first."""
        with self._lock:
            return tuple(self._history)

    def can(self, target: State) -> bool:
        """Is a move to ``target`` legal right now?"""
        with self._lock:
            return target in LEGAL_TRANSITIONS[self._state]

    def on_transition(self, hook: Callable[[State, State], None]) -> None:
        """Register a callback invoked after every successful transition."""
        with self._lock:
            self._hooks.append(hook)

    def transition(self, target: State, /, **payload: Any) -> State:
        """Move to ``target``.

        Raises:
            InvalidTransition: if the move is not legal from the current
                state. The error is published on the bus before raising.
        """
        with self._lock:
            source = self._state
            if target not in LEGAL_TRANSITIONS[source]:
                error = InvalidTransition(f"illegal transition {source.value} -> {target.value}")
                self._logger.error("%s", error)
                self._bus.publish(
                    Event.ERROR,
                    error=error,
                    source=source,
                    target=target,
                    kind="invalid_transition",
                )
                raise error
            self._state = target
            self._history.append(Transition(source=source, target=target, at=time.monotonic()))
            hooks = list(self._hooks)

        self._bus.publish(
            Event.STATE_CHANGED,
            source=source,
            target=target,
            previous=source,
            current=target,
            **payload,
        )
        for hook in hooks:
            try:
                hook(source, target)
            except Exception:
                self._logger.exception("State transition hook raised.")
        return target

    def force_idle(self) -> State:
        """Return to ``IDLE`` from wherever we are.

        Used by the shutdown path and by the error handler, where the normal
        transition rules must not apply.
        """
        with self._lock:
            source = self._state
            if source is State.IDLE:
                return source
            self._state = State.IDLE
            self._history.append(Transition(source=source, target=State.IDLE, at=time.monotonic()))
        self._bus.publish(
            Event.STATE_CHANGED,
            source=source,
            target=State.IDLE,
            previous=source,
            current=State.IDLE,
            forced=True,
        )
        return State.IDLE
