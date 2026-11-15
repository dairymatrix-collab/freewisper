"""The dictation pipeline — the five stages, wired to the bus.

This module is the reason the app is testable. It talks to four collaborators
through **protocols only**, so a test can hand it in-memory fakes and assert
on the exact string that would have been injected — with no audio device, no
network, and no GUI.

The stage order is:

    RECORDING → TRANSCRIBING → CLEANING → INJECTING → IDLE

Cancellation is checked at every stage boundary, so a cancelled dictation
never reaches the injector.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Protocol

from .errors import CancelledError
from .events import Event, EventBus
from .session import DictationSession, RecordingResult
from .states import State, StateMachine
from .tasks import CancelToken, TaskRunner

#: The group name used for the exclusive dictation task.
DICTATION_GROUP = "dictation"


class Recorder(Protocol):
    """Captures audio between ``start_recording`` and ``stop_recording``."""

    def start_recording(self) -> None: ...

    def stop_recording(self) -> RecordingResult | None: ...


class Transcriber(Protocol):
    """Turns an audio buffer into text."""

    def transcribe(self, audio: Any) -> str: ...


class Cleaner(Protocol):
    """Turns a raw transcript into clean text."""

    def clean(self, text: str) -> str: ...


class Injector(Protocol):
    """Puts text at the cursor. Returns ``True`` on success."""

    def inject(self, text: str) -> bool: ...


class Pipeline:
    """Orchestrates capture → transcribe → clean → inject."""

    def __init__(
        self,
        bus: EventBus,
        machine: StateMachine,
        recorder: Recorder,
        transcriber: Transcriber,
        cleaner: Cleaner,
        injector: Injector,
        *,
        tasks: TaskRunner | None = None,
        min_utterance_ms: int = 300,
        logger: logging.Logger | None = None,
    ) -> None:
        self._bus = bus
        self._machine = machine
        self._recorder = recorder
        self._transcriber = transcriber
        self._cleaner = cleaner
        self._injector = injector
        self._tasks = tasks if tasks is not None else TaskRunner()
        self._min_utterance_ms = min_utterance_ms
        self._logger = logger or logging.getLogger("freewisper.core.pipeline")

        self._lock = threading.RLock()
        self._generation = 0
        self._recording_started_at: float | None = None
        self._session: DictationSession | None = None
        self._announced_cancel: set[int] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def session(self) -> DictationSession | None:
        """The session currently in flight, if any."""
        with self._lock:
            return self._session

    def arm(self) -> State:
        """Move from ``IDLE`` to ``ARMED`` — waiting for the hotkey."""
        if self._machine.state is State.IDLE:
            return self._machine.transition(State.ARMED)
        return self._machine.state

    def on_hotkey_down(self) -> None:
        """Start a recording."""
        with self._lock:
            current = self._machine.state
            if current in (State.RECORDING,):
                self._logger.debug("Already recording; ignoring the press.")
                return
            if current in (State.TRANSCRIBING, State.CLEANING, State.INJECTING):
                self._logger.info("A previous dictation is still running; ignoring the press.")
                return
            self._generation += 1
            generation = self._generation
            self._session = DictationSession()
            self._recording_started_at = time.monotonic()

        if current is State.IDLE:
            self._machine.transition(State.ARMED)
        self._machine.transition(State.RECORDING)

        try:
            self._recorder.start_recording()
        except Exception as exc:
            self._logger.exception("Could not start recording.")
            self._bus.publish(Event.ERROR, error=exc, kind="recorder_start", generation=generation)
            self._machine.force_idle()
            return

        self._bus.publish(Event.RECORDING_STARTED, session=self._session, generation=generation)

    def on_hotkey_up(self) -> None:
        """Finish the recording and run the rest of the pipeline."""
        with self._lock:
            generation = self._generation
            session = self._session
            self._recording_started_at = None

        if session is None:
            self._logger.debug("Hotkey released without a recording; ignoring.")
            return

        session.released_at = time.monotonic()

        try:
            result = self._recorder.stop_recording()
        except Exception as exc:
            self._logger.exception("Could not stop recording.")
            self._bus.publish(Event.ERROR, error=exc, kind="recorder_stop", session=session)
            self._machine.force_idle()
            return

        duration_ms = result.duration_s * 1000 if result is not None else 0.0
        session.audio = result.audio if result is not None else None
        dropped = result is None or duration_ms < self._min_utterance_ms
        self._bus.publish(
            Event.RECORDING_STOPPED,
            session=session,
            generation=generation,
            duration_ms=duration_ms,
            dropped=dropped,
        )

        if dropped:
            session.dropped = True
            self._logger.info(
                "Dropping a %.0f ms utterance (minimum is %d ms).",
                duration_ms,
                self._min_utterance_ms,
            )
            self._bus.publish(
                Event.UTTERANCE_DROPPED,
                session=session,
                duration_ms=duration_ms,
                reason="too_short",
            )
            self._machine.force_idle()
            return

        if self._machine.state is State.RECORDING:
            self._machine.transition(State.TRANSCRIBING)

        self._tasks.submit(
            self._run_stages,
            name="dictation",
            group=DICTATION_GROUP,
            args=(session, generation),
        )

    def cancel(self) -> bool:
        """Cancel the in-flight dictation, if any.

        The ``CANCELLED`` event is published **immediately**, not when the
        worker next reaches a stage boundary. A provider that is blocked
        (a slow cloud model, a large audio file) would otherwise leave the
        user waiting with no feedback.
        """
        cancelled = self._tasks.cancel_group(DICTATION_GROUP)
        if not cancelled:
            return False
        with self._lock:
            generation = self._generation
            session = self._session
            already = generation in self._announced_cancel
            self._announced_cancel.add(generation)
        if not already:
            self._logger.info("Dictation cancelled by the user.")
            self._bus.publish(Event.CANCELLED, session=session, reason="user")
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _is_current(self, generation: int, token: CancelToken) -> bool:
        """Is this worker still the one we want to finish?"""
        if token.cancelled:
            return False
        with self._lock:
            return self._generation == generation

    def _run_stages(self, session: DictationSession, generation: int, token: CancelToken) -> None:
        """The worker body: transcribe → clean → inject."""
        try:
            token.raise_if_cancelled()
            if not self._is_current(generation, token):
                return

            # --- Stage 1: transcribe -------------------------------------
            started = time.monotonic()
            raw = self._transcriber.transcribe(session.audio)
            session.mark("stt", time.monotonic() - started)
            session.raw_text = raw
            self._bus.publish(Event.TRANSCRIPT_READY, session=session, text=raw)
            if not self._is_current(generation, token):
                return

            # --- Stage 2: clean ------------------------------------------
            self._machine.transition(State.CLEANING)
            started = time.monotonic()
            cleaned = self._cleaner.clean(raw)
            session.mark("cleanup", time.monotonic() - started)
            session.cleaned_text = cleaned
            self._bus.publish(Event.CLEANUP_DONE, session=session, text=cleaned)
            if not self._is_current(generation, token):
                return

            # --- Stage 3: inject -----------------------------------------
            self._machine.transition(State.INJECTING)
            started = time.monotonic()
            injected = bool(self._injector.inject(cleaned))
            session.mark("inject", time.monotonic() - started)
            session.injected = injected

            if injected:
                self._bus.publish(Event.INJECTED, session=session, text=cleaned)
            else:
                self._logger.error("The transcript could not be injected.")
                self._bus.publish(Event.INJECTION_FAILED, session=session, text=cleaned)

        except CancelledError:
            self._logger.info("Dictation cancelled.")
            with self._lock:
                already = generation in self._announced_cancel
                self._announced_cancel.add(generation)
            if not already:
                self._bus.publish(Event.CANCELLED, session=session, reason="worker")
        except Exception as exc:
            self._logger.exception("The dictation pipeline failed.")
            session.error = f"{type(exc).__name__}: {exc}"
            self._bus.publish(Event.ERROR, error=exc, kind="pipeline", session=session)
        finally:
            session.mark("total", session.duration_s)
            self._machine.force_idle()
