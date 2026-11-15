"""The dictation pipeline, driven entirely by in-memory fakes.

No audio device, no network, no GUI — just the orchestration logic and the
exact string that would have landed at the cursor.
"""

from __future__ import annotations

import threading
import time

from freewisper.core.events import Event, EventBus
from freewisper.core.pipeline import Pipeline
from freewisper.core.session import RecordingResult
from freewisper.core.states import State, StateMachine
from freewisper.core.tasks import TaskRunner

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRecorder:
    """Hands back a fixed recording."""

    def __init__(self, duration_s: float = 2.0, audio: object = b"audio") -> None:
        self.duration_s = duration_s
        self.audio = audio
        self.started = False
        self.stopped = False

    def start_recording(self) -> None:
        self.started = True

    def stop_recording(self) -> RecordingResult:
        self.stopped = True
        return RecordingResult(audio=self.audio, duration_s=self.duration_s)


class FakeTranscriber:
    """Returns a fixed transcript, or blocks until released."""

    def __init__(self, text: str = "hello world", block: bool = False) -> None:
        self.text = text
        self.block = block
        self.release = threading.Event()
        self.calls = 0

    def transcribe(self, audio: object) -> str:
        self.calls += 1
        if self.block:
            self.release.wait(10.0)
        return self.text


class FakeCleaner:
    """Upper-cases the text so we can tell the stages apart."""

    def __init__(self, transform: str | None = None) -> None:
        self.transform = transform
        self.calls = 0

    def clean(self, text: str) -> str:
        self.calls += 1
        return self.transform if self.transform is not None else text.upper()


class FakeInjector:
    """Records what was injected."""

    def __init__(self, succeed: bool = True) -> None:
        self.succeed = succeed
        self.injected: list[str] = []

    def inject(self, text: str) -> bool:
        self.injected.append(text)
        return self.succeed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class EventRecorder:
    """Subscribes to every event **up front**.

    The pipeline runs in milliseconds, so a helper that subscribes *after*
    the action would race with it and miss the event. Recording from the
    start removes the race entirely.
    """

    def __init__(self, bus: EventBus) -> None:
        self._events: list[tuple[Event, dict]] = []
        self._condition = threading.Condition()
        for event in Event:
            bus.subscribe(event, self._handler)

    def _handler(self, event: Event, payload: dict) -> None:
        with self._condition:
            self._events.append((event, dict(payload)))
            self._condition.notify_all()

    def wait(self, event: Event, timeout: float = 3.0) -> dict:
        """Block until ``event`` was published; return its payload."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                for seen_event, payload in self._events:
                    if seen_event is event:
                        return payload
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(
                        f"timed out waiting for {event.value}; saw "
                        f"{[e.value for e, _ in self._events]}"
                    )
                self._condition.wait(remaining)

    def seen(self, event: Event) -> list[dict]:
        """Every payload published for ``event``."""
        with self._condition:
            return [payload for seen_event, payload in self._events if seen_event is event]

    def count(self, event: Event) -> int:
        """How many times ``event`` was published."""
        return len(self.seen(event))

    def order(self) -> list[Event]:
        """The events in publication order."""
        with self._condition:
            return [event for event, _ in self._events]


class Harness:
    """A pipeline plus its fakes and a recorder, wired together."""

    def __init__(
        self,
        *,
        recorder: FakeRecorder | None = None,
        transcriber: FakeTranscriber | None = None,
        cleaner: FakeCleaner | None = None,
        injector: FakeInjector | None = None,
        min_utterance_ms: int = 300,
    ) -> None:
        self.bus = EventBus()
        self.machine = StateMachine(self.bus)
        self.recorder = recorder or FakeRecorder()
        self.transcriber = transcriber or FakeTranscriber()
        self.cleaner = cleaner or FakeCleaner()
        self.injector = injector or FakeInjector()
        self.pipeline = Pipeline(
            self.bus,
            self.machine,
            self.recorder,
            self.transcriber,
            self.cleaner,
            self.injector,
            tasks=TaskRunner(),
            min_utterance_ms=min_utterance_ms,
        )
        # Subscribe before anything can happen.
        self.events = EventRecorder(self.bus)

    def dictate(self) -> None:
        """One full press-and-release."""
        self.pipeline.on_hotkey_down()
        self.pipeline.on_hotkey_up()


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_a_full_run_injects_the_cleaned_text() -> None:
    h = Harness()

    h.dictate()
    payload = h.events.wait(Event.INJECTED)

    assert payload["text"] == "HELLO WORLD"
    assert h.injector.injected == ["HELLO WORLD"]
    assert h.transcriber.calls == 1
    assert h.cleaner.calls == 1
    assert h.recorder.started is True
    assert h.recorder.stopped is True


def test_each_stage_publishes_its_event_in_order() -> None:
    h = Harness()

    h.dictate()
    h.events.wait(Event.INJECTED)

    published = h.events.order()
    assert published.index(Event.RECORDING_STARTED) < published.index(Event.RECORDING_STOPPED)
    assert published.index(Event.RECORDING_STOPPED) < published.index(Event.TRANSCRIPT_READY)
    assert published.index(Event.TRANSCRIPT_READY) < published.index(Event.CLEANUP_DONE)
    assert published.index(Event.CLEANUP_DONE) < published.index(Event.INJECTED)


def test_the_raw_transcript_is_published_before_the_cleaned_one() -> None:
    h = Harness()

    h.dictate()
    h.events.wait(Event.INJECTED)

    assert h.events.seen(Event.TRANSCRIPT_READY)[0]["text"] == "hello world"
    assert h.events.seen(Event.CLEANUP_DONE)[0]["text"] == "HELLO WORLD"


def test_the_state_walks_the_full_path() -> None:
    h = Harness()

    h.dictate()
    h.events.wait(Event.INJECTED)
    time.sleep(0.05)

    targets = [payload["target"] for payload in h.events.seen(Event.STATE_CHANGED)]
    assert State.RECORDING in targets
    assert State.TRANSCRIBING in targets
    assert State.CLEANING in targets
    assert State.INJECTING in targets
    assert h.machine.state is State.IDLE


def test_the_session_records_the_timings_and_text() -> None:
    h = Harness()

    h.dictate()
    payload = h.events.wait(Event.INJECTED)

    session = payload["session"]
    assert session.raw_text == "hello world"
    assert session.cleaned_text == "HELLO WORLD"
    assert session.injected is True
    assert session.timings["stt"] >= 0.0
    assert session.timings["cleanup"] >= 0.0
    assert "total" in session.timings


def test_the_pipeline_uses_no_io() -> None:
    """The whole point: the pipeline is exercisable with no device present."""
    h = Harness()
    h.dictate()
    h.events.wait(Event.INJECTED)
    assert h.injector.injected == ["HELLO WORLD"]


# ---------------------------------------------------------------------------
# Dropping and failing
# ---------------------------------------------------------------------------


def test_a_short_utterance_is_dropped() -> None:
    h = Harness(recorder=FakeRecorder(duration_s=0.1), min_utterance_ms=300)

    h.dictate()
    payload = h.events.wait(Event.UTTERANCE_DROPPED)

    assert payload["duration_ms"] < 300
    assert payload["reason"] == "too_short"
    assert h.transcriber.calls == 0
    assert h.injector.injected == []
    assert h.events.count(Event.INJECTED) == 0


def test_the_stop_event_says_that_the_utterance_was_dropped() -> None:
    """``RECORDING_STOPPED`` carries ``dropped=True`` for a short utterance."""
    h = Harness(recorder=FakeRecorder(duration_s=0.1), min_utterance_ms=300)

    h.dictate()
    stopped = h.events.wait(Event.RECORDING_STOPPED)

    assert stopped["dropped"] is True
    assert stopped["duration_ms"] < 300


def test_the_stop_event_says_that_the_utterance_was_kept() -> None:
    h = Harness(recorder=FakeRecorder(duration_s=1.0), min_utterance_ms=300)

    h.dictate()
    stopped = h.events.wait(Event.RECORDING_STOPPED)

    assert stopped["dropped"] is False


def test_a_short_utterance_never_reaches_the_transcriber_or_the_injector() -> None:
    """The Phase-3 rule: too short means no STT call and no injection."""
    h = Harness(recorder=FakeRecorder(duration_s=0.29), min_utterance_ms=300)

    h.dictate()
    h.events.wait(Event.UTTERANCE_DROPPED)

    assert h.transcriber.calls == 0
    assert h.injector.injected == []
    assert h.events.count(Event.INJECTED) == 0
    assert h.events.count(Event.TRANSCRIPT_READY) == 0


def test_a_utterance_exactly_at_the_minimum_is_kept() -> None:
    h = Harness(recorder=FakeRecorder(duration_s=0.3), min_utterance_ms=300)

    h.dictate()
    h.events.wait(Event.INJECTED)

    assert h.transcriber.calls == 1
    assert h.injector.injected == ["HELLO WORLD"]


def test_a_failed_injection_is_reported() -> None:
    h = Harness(injector=FakeInjector(succeed=False))

    h.dictate()
    h.events.wait(Event.INJECTION_FAILED)

    assert h.injector.injected == ["HELLO WORLD"]
    assert h.events.count(Event.INJECTED) == 0


def test_a_transcriber_exception_publishes_an_error_and_does_not_crash() -> None:
    class Exploding(FakeTranscriber):
        def transcribe(self, audio: object) -> str:
            raise RuntimeError("no audio device")

    h = Harness(transcriber=Exploding())

    h.dictate()
    payload = h.events.wait(Event.ERROR)

    assert payload["kind"] == "pipeline"
    assert h.injector.injected == []


def test_a_recorder_failure_does_not_crash() -> None:
    class Exploding(FakeRecorder):
        def start_recording(self) -> None:
            raise RuntimeError("device busy")

    h = Harness(recorder=Exploding())

    h.dictate()
    payload = h.events.wait(Event.ERROR)

    assert payload["kind"] == "recorder_start"
    assert h.injector.injected == []


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancelling_mid_pipeline_publishes_cancelled_and_never_injects() -> None:
    h = Harness(transcriber=FakeTranscriber(block=True))

    h.pipeline.on_hotkey_down()
    h.pipeline.on_hotkey_up()
    time.sleep(0.1)

    try:
        assert h.pipeline.cancel() is True
        # The event fires immediately, even though the provider is still
        # blocked — the user must not wait for the model to come back.
        payload = h.events.wait(Event.CANCELLED, timeout=1.0)
        assert payload["reason"] == "user"
    finally:
        h.transcriber.release.set()

    time.sleep(0.2)
    assert h.injector.injected == []


def test_no_injected_event_fires_after_a_cancellation() -> None:
    h = Harness(transcriber=FakeTranscriber(block=True))

    h.pipeline.on_hotkey_down()
    h.pipeline.on_hotkey_up()
    time.sleep(0.1)
    try:
        h.pipeline.cancel()
        h.events.wait(Event.CANCELLED, timeout=1.0)
    finally:
        h.transcriber.release.set()

    time.sleep(0.3)

    assert h.events.count(Event.INJECTED) == 0
    assert h.injector.injected == []


def test_the_cancelled_event_is_published_only_once() -> None:
    h = Harness(transcriber=FakeTranscriber(block=True))

    h.pipeline.on_hotkey_down()
    h.pipeline.on_hotkey_up()
    time.sleep(0.1)
    try:
        h.pipeline.cancel()
        h.events.wait(Event.CANCELLED, timeout=1.0)
    finally:
        h.transcriber.release.set()

    time.sleep(0.3)
    assert h.events.count(Event.CANCELLED) == 1


def test_cancelling_when_nothing_is_running_returns_false() -> None:
    h = Harness()
    assert h.pipeline.cancel() is False


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_a_press_while_busy_is_ignored() -> None:
    h = Harness(transcriber=FakeTranscriber(block=True))

    h.pipeline.on_hotkey_down()
    h.pipeline.on_hotkey_up()
    time.sleep(0.1)

    before = h.events.count(Event.RECORDING_STARTED)
    h.pipeline.on_hotkey_down()

    assert h.events.count(Event.RECORDING_STARTED) == before
    h.transcriber.release.set()


def test_a_double_press_does_not_start_two_recordings() -> None:
    h = Harness()

    h.pipeline.on_hotkey_down()
    h.pipeline.on_hotkey_down()

    assert h.events.count(Event.RECORDING_STARTED) == 1


def test_releasing_without_recording_is_harmless() -> None:
    h = Harness()

    h.pipeline.on_hotkey_up()

    assert h.injector.injected == []
    assert h.events.count(Event.INJECTED) == 0
