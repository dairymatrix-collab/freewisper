# Architecture

Four layers, one direction. A layer may import from the layers *below* it;
never the other way round.

```
┌────────────────────────────────────────────────────────────┐
│ ui/          Settings dashboard, HUD renderer              │  presentation
├────────────────────────────────────────────────────────────┤
│ platform/    macos/ windows/ linux/                        │  OS integration
├────────────────────────────────────────────────────────────┤
│ providers/   stt/ llm/ inject/                             │  swappable backends
├────────────────────────────────────────────────────────────┤
│ core/        events, states, tasks, pipeline               │  pure logic, zero I/O
└────────────────────────────────────────────────────────────┘
```

## Why this shape

The alternative — a flat package with `if sys.platform ==` branches inside
each module — is what the reference implementation (Likhari) does. It works
until the third platform appears: a macOS fix and a Linux fix start editing
the same 1,300-line file, and the wave-rendering maths ends up written twice.

This layout makes three things true instead of aspirational:

1. **`core/` is pure.** No OS calls, no network, no filesystem, no GUI.
   The orchestration logic is therefore testable with in-memory fakes
   instead of mocks — a full dictation runs in a unit test with no audio
   device and no network.
2. **The rule is executable.** `tests/test_layering.py` parses the `core`
   package with `ast` and fails the build if it imports `tkinter`,
   `sounddevice`, `httpx`, `os`, `sys`, or anything else platform-specific,
   or calls `print()` or `open()`.
3. **A platform fix cannot break another platform.** Each OS owns its own
   package; only the drawing differs.

## Current state

| Layer | Status |
|---|---|
| `core/` | **Built.** Event bus, state machine, task runner, pipeline, session, errors. |
| `config/` | **Built.** Typed schema, atomic store, migration, quarantine. |
| `providers/` | Not started — Phase 4 and 5. |
| `platform/` | Not started — Phase 7 and 8. |
| `ui/` | Not started — Phase 8 and 11. |

## The core layer

### `core/events.py`

A thread-safe publish/subscribe hub. Every meaningful thing that happens is
an `Event`.

- Subscribers are called in **subscription order**, so behaviour is
  deterministic.
- A subscriber that raises is **logged and skipped**. One broken listener
  must never stop the HUD from updating.
- The subscriber list is snapshotted under the lock and called outside it,
  so a subscriber may subscribe, unsubscribe or publish from inside its own
  callback without deadlocking.

### `core/states.py`

The app is in exactly one state at a time, and the legal moves are fixed.

```
IDLE ⇄ ARMED → RECORDING → TRANSCRIBING → CLEANING → INJECTING → IDLE
                                    ↓ any stage
                                  ERROR → IDLE
```

An illegal move raises `InvalidTransition` **and** publishes an `ERROR`
event, so a bug can never leave the app in a meaningless state without
anyone noticing.

### `core/tasks.py`

Long-running work runs on daemon threads with **cooperative** cancellation:
the token is checked at stage boundaries, so a cancelled task stops at the
next checkpoint instead of being killed mid-write.

Tasks can be **exclusive**. Submitting a task with a group name cancels the
in-flight task in that group — pressing the hotkey twice quickly must not
transcribe the same audio twice.

### `core/pipeline.py`

The five stages, wired to the bus. It talks to four collaborators through
**protocols only**:

```python
class Recorder(Protocol):
    def start_recording(self) -> None: ...
    def stop_recording(self) -> RecordingResult | None: ...


class Transcriber(Protocol):
    def transcribe(self, audio: Any) -> str: ...


class Cleaner(Protocol):
    def clean(self, text: str) -> str: ...


class Injector(Protocol):
    def inject(self, text: str) -> bool: ...
```

Because of this, a test can hand the pipeline in-memory fakes and assert on
the exact string that would have landed at the cursor:

```python
h = Harness()
h.dictate()
assert h.events.wait(Event.INJECTED)["text"] == "HELLO WORLD"
assert h.injector.injected == ["HELLO WORLD"]
```

### `core/session.py`

One dictation's record: raw and cleaned text, per-stage timings, which
providers ran, which command matched, and whether the text was injected.
This is the unit that becomes a row in the history database in Phase 10.

### `core/errors.py`

Every deliberate failure derives from `FreewisperError`, so callers can
tell an *expected, handled* failure from a genuine bug.

## Design decisions worth knowing

**Cancellation announces itself immediately.** `Pipeline.cancel()` publishes
`CANCELLED` at once rather than waiting for the worker to reach its next
stage boundary. A provider blocked on a slow cloud model would otherwise
leave the user with no feedback. The worker dedupes so the event still
fires exactly once.

**Duration comes from the audio, not the clock.** `RecordingResult.duration_s`
is the length of the captured audio. On a Bluetooth headset these differ —
the device needs 300–800 ms to wake up — and the "too short" rule has to be
based on how much speech was actually captured.

**The provider chain is data, not code.** The cleanup tiers, their models
and their timeouts live in the config, so a model that a provider retires can
be swapped without touching the pipeline.

**Provider defaults avoid Preview-tier models.** Groq's
`qwen/qwen3.8-27b` is a Preview model ("may be discontinued at short
notice"), roughly 2.2× slower, and about 13× more expensive per output
token than `openai/gpt-oss-20b`. The default is the Production model.

**The HUD never takes keyboard focus.** If it does, the caret stops blinking
and the paste fails silently — the worst possible failure mode. Each
platform has its own defence: `canBecomeKeyWindow → False` on macOS,
`WS_EX_NOACTIVATE` on Windows, `overrideredirect(True)` on X11.
