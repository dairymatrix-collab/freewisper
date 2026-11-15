# Freewisper — Build Spec v1.0

**A production-grade, cross-platform push-to-talk dictation app.**
*Advanced successor to [Likhari](https://github.com/AIwithhassan/likhari-ai) — same soul, rebuilt architecture.*

---

# 0. Hinglish summary — Likhari se kya badlega

Likhari ek **bahut accha v1** hai: 2-model speech pipeline, 3-tier cleanup, hardware resilience, focus-stealing-safe HUD. Uska problem ye nahi ki usme kuch galat hai — problem ye hai ki:

1. **Jo usne promise kiya tha, wo implement nahi hua.** Repo me uska apna spec file hai (`likhari-prompts-to-build-from-scratch.md`) — usme 11 features documented hain jo code me exist hi nahi karte. Sabse bada: **pre-roll buffer** (Bluetooth pe pehla word kat jaata hai), **CUDA detection** (`device="cpu"` hardcoded hai), **file logging** (sirf stderr).
2. **Groq default model risky hai.** `qwen/qwen3.8-27b` Preview-tier model hai — "may be discontinued at short notice" — aur 13× mehnga hai `openai/gpt-oss-20b` se. 3-second timeout ke saath ye constantly trip karega aur users silently degrade ho jayenge.
3. **Architecture flat hai.** `hud.py` 1338 lines hai jisme macOS aur Tk ka code ek hi file me conditional branches hai. Wave math **do jagah duplicate** hai — jabki Likhari ke apne spec ne bola tha *"The wave math must not exist twice."*
4. **Data loss hai.** `main.py:297` latency compute karta hai, log karta hai, phir discard kar deta hai. Stats bhi sirf tab persist hote hain jab user Settings me Save dabaye.
5. **No .gitignore** — jabki README me `.env` me API key documented hai.

Freewisper me hum ye sab fix karenge **aur** 20+ genuinely naye features add karenge: command macros, context-aware cleanup, per-app profiles, snippets, dictation history + re-inject, undo, toggle-mode hotkey, multi-language, plugin providers.

---

# 1. Rules of engagement (ye original spec ko kaam karne wala banaya tha)

Likhari ke author ne 6 prompts likhe aur build hua. Usne baad me likha ki kyun kaam hua. **Ye rules copy mat karo — inhe follow karo:**

1. **Agent code likhta hai, tum build aur locally run karte ho.** Koi desktop app sandbox me test nahi ho sakta. Iska matlab: har phase ke end pe tumhe ek **verification script** milega jo tum locally chalate ho.
2. **Jab kuch brike to symptom report karo, theory nahi.** "Cleanup kaam nahi kar raha" likho, "mujhe lagta hai API key expire ho gayi hai" nahi. Galat theory galat side pe 2 ghante waste karwati hai.
3. **Libraries naam karo.** faster-whisper, sounddevice, pynput, pystray, vosk — sab explicitly specify karo. Khud choose karne do to agent ajeeb dependencies laata hai.
4. **Behaviour describe karo, vibe nahi.** "Hold key, release key, text appears at cursor." Interpret karne ko kuch mat chhodna.
5. **Ye zaroor batao ki kya NAHI karna hai.** "It must not paraphrase or answer." Ye ek line dictation tool aur accidental chatbot me farak banati hai.
6. **Boring stuff pehle poochho.** README, requirements, error log, CI, tests. Baad me poochega to dobara poori build chalani padegi.

**Is spec me har phase ke end pe acceptance criteria hain** — wahi tumhare checklist ka kaam karega.

---

# 2. Naming

Project name **Freewisper** — "free" + "whisper", pointing at free/local Whisper transcription. Yeh naam pakka hai; agar kabhi badalna ho to ek hi jagah se ho jaata hai — `pyproject.toml` me package name, config dir, service ID, tray label, aur display name.

| Item | Value |
|---|---|
| Python package | `freewisper` |
| Distribution | `freewisper` |
| CLI entrypoint | `freewisper` |
| Config dir | `~/.config/freewisper/` (XDG-style, same path on all OSes) |
| Env prefix | `FREEWISPER_*` |
| Service ID (macOS) | `com.freewisper.dictation` |
| Keychain service | `Freewisper` / key `groq_api_key` |
| Tray / app label | `Freewisper` |

---

# 3. Architecture — ye sabse important section hai

## 3.1 Likhari ka problem

Likhari ka `main.py` closure-based wiring use karta hai — `on_press`/`on_release` nested functions, ek `threading.Lock`, aur `state_lock` ke around scattered checks. Iska matlab:

- Core logic test karna mushkil hai (UI/threads se coupled hai).
- Naya feature add karna matlab `main.py` aur `hud.py` me aur surgery.
- `hud.py` me macOS aur Linux ka code ek hi file me — ek platform fix karna doosre ko affect karta hai.

## 3.2 Freewisper ka approach: 4 layers, ek direction

```
┌─────────────────────────────────────────────────────────┐
│  ui/          Settings dashboard, HUD renderer          │  ← presentation
├─────────────────────────────────────────────────────────┤
│  platform/    macos/ windows/ linux/                    │  ← OS integration
│                hotkey, tray, startup, permissions       │
├─────────────────────────────────────────────────────────┤
│  providers/   stt/  llm/  inject/                       │  ← swappable backends
├─────────────────────────────────────────────────────────┤
│  core/        events, state machine, pipeline, session  │  ← pure logic, no I/O
└─────────────────────────────────────────────────────────┘
```

**Rules:**
- `core/` me **koi OS import nahi**, koi network call nahi, koi filesystem nahi. Pure logic. Isi liye 100% testable hai bina mock ke.
- `platform/` me **koi business logic nahi**. Sirf "is OS pe kaise karo".
- `providers/` me har backend ek **protocol** implement karta hai + **entry point** se register hota hai. Naya backend add karna = ek nayi file, core me zero change.
- `ui/` sirf render karta hai, decision nahi leta.

## 3.3 Full file tree

```
freewisper/
├── pyproject.toml
├── README.md
├── LICENSE
├── CHANGELOG.md
├── .gitignore                       # PHASE 1 — non-negotiable
├── .editorconfig
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                   # PHASE 12 — test matrix
│   │   └── release.yml              # PHASE 12 — build artifacts
│   └── ISSUE_TEMPLATE/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PROVIDERS.md
│   ├── COMMANDS.md
│   └── PRIVACY.md
├── src/freewisper/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                       # argparse, subcommands
│   ├── config/
│   │   ├── __init__.py
│   │   ├── paths.py                 # platform dirs
│   │   ├── schema.py                # typed dataclasses + validation
│   │   ├── store.py                 # atomic load/save + migration
│   │   └── defaults.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── events.py                # Event enum + EventBus
│   │   ├── states.py                # State enum + StateMachine
│   │   ├── session.py               # DictationSession dataclass
│   │   ├── pipeline.py              # orchestrates the 5 stages
│   │   ├── tasks.py                 # cancellable task runner
│   │   └── errors.py                # exception taxonomy
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── devices.py               # enumeration, selection, hot-plug
│   │   ├── recorder.py              # always-on stream + ring buffer
│   │   ├── ring.py                  # RingAudioBuffer (pre-roll)
│   │   ├── resample.py              # mono/resample helpers
│   │   ├── vad.py                   # energy VAD + hangover
│   │   └── levels.py                # RMS meter
│   ├── stt/
│   │   ├── __init__.py
│   │   ├── base.py                  # STTProvider protocol + registry
│   │   ├── faster_whisper.py
│   │   ├── mlx_whisper.py           # Apple Silicon / Metal
│   │   ├── whisper_cpp.py
│   │   ├── openai_api.py            # optional cloud STT
│   │   └── vosk_stream.py           # live preview only
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py                  # LLMProvider protocol + registry
│   │   ├── groq.py
│   │   ├── ollama.py
│   │   ├── openai_compat.py         # any OpenAI-compatible endpoint
│   │   ├── llama_cpp_server.py
│   │   └── anthropic.py
│   ├── cleanup/
│   │   ├── __init__.py
│   │   ├── chain.py                 # tier failover
│   │   ├── rules.py                 # tier 3, deterministic
│   │   ├── guard.py                 # hallucination + injection guards
│   │   └── prompts.py               # default prompt library
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── registry.py              # load + match command defs
│   │   ├── builtin.py               # summarize/translate/rewrite/…
│   │   ├── runner.py                # execute a matched command
│   │   └── snippets.py              # text expansion
│   ├── text/
│   │   ├── __init__.py
│   │   ├── dictionary.py            # replacements, longest-first
│   │   ├── normalize.py             # numbers, dates, times, units
│   │   ├── context.py               # focused-window text extraction
│   │   └── casing.py
│   ├── inject/
│   │   ├── __init__.py
│   │   ├── clipboard.py             # per-platform backends
│   │   ├── paste.py                 # paste simulation + Wayland native
│   │   ├── undo.py                  # revert last injection
│   │   └── focus.py                 # foreground app detection
│   ├── history/
│   │   ├── __init__.py
│   │   ├── store.py                 # SQLite
│   │   └── search.py
│   ├── plugins/
│   │   ├── __init__.py
│   │   └── loader.py                # entry-point discovery
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── theme.py
│   │   ├── hud/
│   │   │   ├── __init__.py
│   │   │   ├── geometry.py          # PURE shared math — single source
│   │   │   ├── model.py             # HudModel (state + values)
│   │   │   ├── renderer.py          # shared draw semantics
│   │   │   └── position.py          # screen placement
│   │   └── settings/
│   │       ├── __init__.py
│   │       ├── app.py
│   │       ├── state.py
│   │       └── tabs/
│   │           ├── general.py
│   │           ├── transcription.py
│   │           ├── cleanup.py
│   │           ├── commands.py
│   │           ├── dictionary.py
│   │           ├── snippets.py
│   │           ├── profiles.py
│   │           └── stats.py
│   ├── platform/
│   │   ├── __init__.py              # detect + facade
│   │   ├── base.py                  # protocols
│   │   ├── macos/
│   │   │   ├── __init__.py
│   │   │   ├── hotkey.py
│   │   │   ├── hud.py
│   │   │   ├── tray.py
│   │   │   ├── startup.py
│   │   │   └── permissions.py
│   │   ├── windows/
│   │   │   ├── __init__.py
│   │   │   ├── hotkey.py
│   │   │   ├── hud.py
│   │   │   ├── tray.py
│   │   │   └── startup.py
│   │   └── linux/
│   │       ├── __init__.py
│   │       ├── hotkey.py            # x11 / wayland / evdev
│   │       ├── hud.py
│   │       ├── tray.py
│   │       └── startup.py
│   └── resources/
│       ├── icons/                   # real template PNGs, not emoji
│       └── prompts/
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_config.py
    │   ├── test_events.py
    │   ├── test_states.py
    │   ├── test_pipeline.py
    │   ├── test_dictionary.py
    │   ├── test_normalize.py
    │   ├── test_commands.py
    │   ├── test_rules.py
    │   ├── test_guard.py
    │   ├── test_hud_geometry.py
    │   └── test_ring.py
    ├── integration/
    │   ├── test_stt_faster_whisper.py
    │   ├── test_llm_groq.py         # VCR cassettes
    │   ├── test_clipboard.py
    │   └── test_history.py
    └── fixtures/
        ├── audio/                   # 16k mono wavs
        └── cassettes/               # recorded HTTP
```

## 3.4 Core data model

```python
# core/states.py
class State(str, Enum):
    IDLE = "idle"
    ARMED = "armed"  # stream open, waiting for hotkey
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    CLEANING = "cleaning"
    INJECTING = "injecting"
    ERROR = "error"
```

```python
# core/events.py
class Event(str, Enum):
    STATE_CHANGED = "state_changed"
    DEVICE_CHANGED = "device_changed"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    PARTIAL = "partial"  # live preview text
    TRANSCRIPT_READY = "transcript_ready"
    CLEANUP_DONE = "cleanup_done"
    COMMAND_MATCHED = "command_matched"
    INJECTED = "injected"
    INJECTION_FAILED = "injection_failed"
    CONFIG_CHANGED = "config_changed"
    PROVIDER_STATUS = "provider_status"
    ERROR = "error"
```

EventBus: plain `threading` based pub/sub. `subscribe(event, callback)` returns an unsubscribe token. Callbacks must never raise into the bus — exceptions get logged, not propagated.

```python
# core/session.py
@dataclass
class DictationSession:
    id: str
    started_at: float
    released_at: float | None = None
    audio: np.ndarray | None = None
    raw_text: str = ""
    cleaned_text: str = ""
    command_id: str | None = None
    stt_provider: str = ""
    stt_model: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    tier: str = ""
    app_bundle: str | None = None
    timings: dict[str, float] = field(default_factory=dict)
    injected: bool = False
```

```python
# core/errors.py
class FreewisperError(Exception): ...


class ConfigError(FreewisperError): ...


class AudioError(FreewisperError): ...


class DeviceError(AudioError): ...


class ProviderError(FreewisperError): ...


class ProviderUnavailable(ProviderError): ...


class ProviderTimeout(ProviderError): ...


class PermissionDenied(FreewisperError): ...


class InjectionError(FreewisperError): ...
```

## 3.5 Config schema (typed, versioned)

```json
{
  "schema_version": 2,
  "general": {
    "hotkey": { "mode": "push_to_talk", "modifiers": ["alt"], "key": "alt_r" },
    "secondary_hotkey": { "mode": "toggle", "modifiers": ["ctrl", "shift"], "key": "space" },
    "undo_hotkey": { "mode": "push_to_talk", "modifiers": ["ctrl", "alt"], "key": "z" },
    "pre_roll_ms": 500,
    "min_utterance_ms": 300,
    "overlay_enabled": true,
    "overlay_position": "bottom_center",
    "start_on_login": false,
    "language": "en"
  },
  "audio": {
    "device": null,
    "channels": "auto",
    "vad": { "enabled": true, "threshold_dbfs": -42.0, "hangover_ms": 600, "min_speech_ms": 200 }
  },
  "transcription": {
    "provider": "auto",
    "model": "base",
    "compute_type": "int8",
    "device": "auto",
    "beam_size": 1,
    "vad_filter": false,
    "hotwords_from_dictionary": true,
    "preview": { "enabled": true, "engine": "vosk", "model": "vosk-model-small-en-us-0.15" }
  },
  "cleanup": {
    "tier": "auto",
    "providers": [
      { "id": "groq", "type": "groq", "model": "openai/gpt-oss-20b", "enabled": true, "timeout_s": 6.0 },
      { "id": "ollama", "type": "ollama", "model": "llama3.2:3b", "enabled": true, "timeout_s": 15.0 },
      { "id": "rules", "type": "rules", "enabled": true }
    ],
    "system_prompt": null,
    "length_guard_ratio": 1.5,
    "dictionary": [["kubernetes", "K8s"], ["pie torch", "PyTorch"]],
    "snippets": { "adr": "Architecture Decision Record:\n\n## Context\n\n" }
  },
  "commands": [
    { "id": "summarize", "triggers": ["summarize", "summarise", "tl;dr"],
      "mode": "prefix", "prompt": "Summarize the following in at most 3 bullet points:\n\n{text}",
      "provider": "groq", "enabled": true }
  ],
  "profiles": {
    "default": { "cleanup_provider": null, "dictionary": null, "style": "general" },
    "com.microsoft.VSCode": { "style": "technical", "dictionary": "tech" }
  },
  "context": { "enabled": false, "max_chars": 500, "provider": null },
  "history": { "enabled": true, "max_rows": 5000, "retention_days": 30 },
  "privacy": { "cloud_cleanup": true, "redact_before_cloud": false }
}
```

`schema_version` drives migration. `store.py` must migrate old → new without data loss, and never crash on an unknown future version (warn + use defaults).

## 3.6 Provider registry (the plugin mechanism)

```python
# stt/base.py
class STTProvider(Protocol):
    name: str

    def available(self) -> bool: ...
    def list_models(self) -> list[str]: ...
    def transcribe(
        self, audio: np.ndarray, *, language: str | None = None, hotwords: list[str] | None = None
    ) -> STTResult: ...
    def transcribe_stream(
        self, audio: np.ndarray, *, language: str | None = None
    ) -> Iterator[str]: ...
```

```python
# llm/base.py
class LLMProvider(Protocol):
    name: str

    def available(self) -> bool: ...
    def list_models(self) -> list[str]: ...
    def complete(
        self, prompt: str, *, system: str | None = None, timeout_s: float | None = None
    ) -> LLMResult: ...
```

Registration via **entry points** so third parties can ship providers without touching Freewisper:

```toml
# pyproject.toml of a third-party plugin
[project.entry-points."freewisper.stt"]
my_asr = "my_plugin:MyASRProvider"
```

Loader: `plugins/loader.py` reads `importlib.metadata.entry_points(group="freewisper.stt")`, imports, validates against the protocol, registers. Built-in providers register the same way.

**`provider: "auto"`** resolution order must be explicit and logged: GPU → CUDA if available, else MLX on Apple Silicon, else whisper.cpp if installed, else faster-whisper CPU.

---

# 4. Build phases

Har phase: **goal → requirements → acceptance criteria → "must NOT" → tests.**

---

## PHASE 1 — Foundation (skeleton, config, logging, CLI)

**Goal.** Empty app jo chalti hai, typed config load/save karti hai, logs file me likhti hai, aur CLI sahi kaam karta hai.

**Requirements**
- `pyproject.toml` — `requires-python = ">=3.10"`, deps: `numpy`, `sounddevice`, `pynput`, `scipy`, `httpx`, `pydantic>=2`, `platformdirs`, `keyring`, `pystray`, `pillow`, `faster-whisper`, `python-dotenv`, `click` (ya stdlib argparse — tum choose karo, but stick to it).
- `pyproject.toml` me `[project.optional-dependencies]`: `wayland = ["evdev>=1.6.0"]`, `macos = ["pyobjc-framework-Cocoa", "pyobjc-framework-Quartz", "pyobjc-framework-ApplicationServices"]`, `windows = ["pywin32>=306"]`, `dev = ["pytest", "pytest-cov", "pytest-asyncio", "mypy", "ruff", "vcrpy"]`.
- `config/schema.py` — **pydantic v2** models for every section above. Unknown keys allowed (forward compat) but preserved.
- `config/store.py` — atomic write (`tmp` + `os.replace`), `schema_version` migration hook, never writes secrets. **Enforce:** strip `api_key` / `groq_api_key` from top level AND from every nested dict — same defense-in-depth as Likhari but generalized.
- `config/paths.py` — `platformdirs` based: config dir, cache dir, log dir, data dir. Cache: `~/.cache/freewisper/` (models). Logs: `~/.local/state/freewisper/freewisper.log`.
- Logging: **rotating file handler** (`RotatingFileHandler`, 5 MB × 3) + stderr handler. Level configurable. **Must redact** anything matching `gsk_[A-Za-z0-9]+` before it hits the log.
- `cli.py` — subcommands: `run`, `devices`, `settings`, `history`, `doctor`, `version`.
- `doctor` subcommand — checks: mic present, whisper model cached, keychain readable, hotkey backend importable, HUD backend importable, permissions (macOS Accessibility).
- `.gitignore` — `.env`, `*.json` under config dirs, `__pycache__/`, `.venv/`, `dist/`, `build/`, `*.egg-info/`, `.pytest_cache/`, `.mypy_cache/`, `*.wav`, `*.mp3`.

**Acceptance criteria**
- `freewisper run --dry-run` starts and exits cleanly, prints resolved config paths.
- `freewisper devices` lists input devices with index, name, default rate, max channels.
- `freewisper doctor` returns a table with green/red per check, exit code 0 if all pass, 1 otherwise.
- Killing the app mid-write never leaves a corrupt `config.json` (write a test that simulates a crash between tmp write and replace).
- A log file exists and rotates.
- `GROQ_API_KEY=gsk_secret` set in env → `grep -r "gsk_secret" ~/.local/state/freewisper/` returns nothing.

**Must NOT**
- Koi real audio/hotkey/HUD code is phase me nahi. Sirf skeleton.
- API key kabhi config.json me mat likho. Keychain use karo (Phase 5 me implement hoga, tab tak env fallback).
- `config.json` me `api_key` field kahin bhi as a supported key mat rakhna.

**Tests**
`test_config.py` — defaults, round-trip, migration from v1, atomic-write crash simulation, secret stripping (top-level + nested), unknown-key preservation.

---

## PHASE 2 — Core: events, state machine, task runner

**Goal.** Pure-logic core jo kisi OS ya network ko nahi jaanta, aur poore app ka nervous system ban jaata hai.

**Requirements**
- `core/events.py` — `Event` enum + `EventBus`. `subscribe(event, cb) -> unsubscribe_token`, `unsubscribe(token)`, `publish(event, **payload)`. **Thread-safe** (lock). **Callback exceptions logged, never propagated.** Subscriber ordering deterministic (FIFO by subscription).
- `core/states.py` — `State` enum + `StateMachine`. Legal transitions hardcoded:
  ```
  IDLE ↔ ARMED → RECORDING → TRANSCRIBING → CLEANING → INJECTING → IDLE
  any → ERROR → IDLE
  RECORDING → IDLE        (cancelled / too short)
  ```
  Illegal transition → raise `InvalidTransition` **and** publish `ERROR`. `on_transition(from, to)` hook.
- `core/tasks.py` — cancellable task runner. `submit(fn, *, name, cancel_token)`. A new task with the same "exclusive group" (e.g. `"transcribe"`) **cancels** the in-flight one. Cancellation must be **cooperative** — the worker checks the token at stage boundaries. Return a `TaskHandle` with `.cancel()`, `.done()`, `.result(timeout)`.
- `core/pipeline.py` — the 5-stage orchestrator, written against **protocols only** so it takes injected fake providers in tests:
  ```python
  class Pipeline:
      def __init__(self, bus, recorder, stt, cleanup, injector, context): ...
      def on_hotkey_down(self) -> None: ...
      def on_hotkey_up(self) -> None: ...
  ```
  It publishes events at every stage boundary. It **never** imports `tkinter`, `sounddevice`, or `httpx`.
- `core/session.py` — the `DictationSession` dataclass above.

**Acceptance criteria**
- `tests/unit/test_states.py`: every legal transition passes; every illegal one raises.
- `tests/unit/test_pipeline.py`: with **fake** providers (in-memory), a full run produces `INJECTED` event and the exact injected string, with **zero** network/IO.
- Cancelling mid-pipeline → `CANCELLED` event, and **no** `INJECTED` event fires afterwards.
- EventBus: a subscriber that raises does not prevent other subscribers from receiving the event.
- `grep -r "^import\|^from" core/` shows **only** stdlib + numpy + pydantic. No `sounddevice`, no `tkinter`, no `httpx`, no `os`/`sys` platform calls.

**Must NOT**
- `core/` me koi `print()` nahi — logger use karo.
- `core/` me koi sleep nahi (except a cancellable `task.sleep`).
- Global mutable state nahi. Sab instance-level.

**Tests**
`test_events.py`, `test_states.py`, `test_pipeline.py`, `test_tasks.py`.

---

## PHASE 3 — Audio: always-on recorder, ring buffer pre-roll, VAD

**Goal.** Pre-roll implement karna (Likhari ka sabse bada missing piece) + proper silence/speech detection.

**Requirements**
- `audio/ring.py` — `RingAudioBuffer(sample_rate, seconds=1.5)`. Bounded memory (use `np.ndarray` ring, not a growing list). `push(chunk)`, `snapshot(seconds) -> np.ndarray`, `clear()`. **Memory must be bounded** — no unbounded growth.
- `audio/recorder.py` — **always-on** stream:
  - Stream opens at app start (state `ARMED`), stays open for the session.
  - `_callback` pushes into the ring buffer continuously, always (even when not recording) — **but discards, never writes to disk** (spec compliance).
  - `start_recording()` → snapshots the last `pre_roll_ms` from the ring, then captures live.
  - `stop_recording()` → returns `pre_roll + captured` as one concatenated array.
  - **Device switch must restart the always-on stream**, not just re-lock.
  - If pre-roll is 0, behaviour must be byte-identical to the old press-to-open flow (so it can be disabled).
- `audio/devices.py` — enumerate, select by index or name-substring, hot-plug detection (poll every 2 s; if the active device disappears → auto-switch to fallback, publish `DEVICE_CHANGED`).
- `audio/vad.py` — energy VAD with **hangover**:
  - `threshold_dbfs` (default -42), `hangover_ms` (default 600), `min_speech_ms` (default 200).
  - Returns speech intervals. Used for (a) dropping silent recordings, (b) trimming leading/trailing silence before STT.
  - **Must be a pure function over an array** so it is trivially testable.
- `audio/levels.py` — RMS meter, ring of last N samples, thread-safe (used by HUD).
- `audio/resample.py` — mono downmix + `resample_poly` to 16 kHz, GCD-reduced.

**Acceptance criteria**
- `tests/unit/test_ring.py`: pushing 10× the buffer size keeps memory bounded; `snapshot(0.5)` returns exactly 0.5 s of the most recent audio.
- **Pre-roll correctness test (the important one):** feed a 3 s signal, sleep, then `start_recording()` → the returned audio **contains the 500 ms before the press**. Assert sample-level equality on a known tone.
- `test_vad.py`: a synthetic array of speech (loud) + silence (quiet) yields the expected speech intervals. Edge cases: all-silence, all-loud, 10 ms blip (should be rejected by `min_speech_ms`).
- Recording shorter than `min_utterance_ms` (300 ms) is **discarded** — no STT call, no injection, publish `RECORDING_STOPPED` with `dropped=True`.
- Device removal mid-recording → app does not crash; publishes `DEVICE_CHANGED`.
- Microphone is **never** written to disk.

**Must NOT**
- PortAudio open/close per hotkey press — is phase ka poora point hi ye hai ki stream hamesha open rahe.
- Ring buffer me unbounded list nahi.
- VAD me hardcoded magic numbers nahi — sab config se.

**Tests**
`test_ring.py`, `test_vad.py`, `test_resample.py`, `test_recorder.py` (fake sounddevice).

---

## PHASE 4 — STT providers

**Goal.** Pluggable speech-to-text with real device acceleration.

**Requirements**
- `stt/base.py` — protocol + `STTResult` dataclass (`text`, `language`, `language_probability`, `segments`, `duration_ms`).
- `stt/faster_whisper.py`:
  - `device` auto-detect: **CUDA if available, else CPU**. `compute_type`: `float16` on CUDA, `int8` on CPU.
  - `beam_size` configurable (default 1).
  - `vad_filter` configurable, default **False** (Silero drops quiet mic signals — this was a real bug in Likhari) — **but** when our own `audio/vad.py` trims the array first, `vad_filter=True` becomes safe. Implement both paths; document the interaction.
  - **`initial_prompt` / `hotwords` from the dictionary** — biases the model toward your terms. This is a big accuracy win.
  - `transcribe_stream()` yielding segments incrementally (for streaming injection in Phase 9).
- `stt/mlx_whisper.py` — Apple Silicon / Metal. Optional import; `available()` returns False if `mlx_whisper` isn't installed. **This is the big macOS speedup** (faster-whisper has no Metal path).
- `stt/whisper_cpp.py` — optional; talks to a local `whisper-server` over HTTP.
- `stt/openai_api.py` — optional cloud STT; **disabled by default**, must be clearly marked as sending audio off-device.
- `stt/vosk_stream.py` — live preview only. Bounded queue (8 frames), **drop-oldest** when full, rate-limit emissions to 15 Hz, never injects.
- Model download: **visible progress** for every engine (Whisper included — Likhari only had this for Vosk). Show in Settings: cached / needs-download / downloading with a progress bar.
- Model cache under `~/.cache/freewisper/models/`.

**Acceptance criteria**
- `provider="auto"` resolution is **logged** with the chosen backend + reason.
- Switching provider/model does **not** require an app restart — the next dictation uses the new one.
- `initial_prompt` actually reaches Whisper: assert via a mocked `model.transcribe` call that `initial_prompt` contains a dictionary term.
- On a machine with no CUDA, `device` resolves to `cpu` and `compute_type` to `int8`; on CUDA, `float16`. Logged.
- Vosk unavailable → preview silently disables, Whisper keeps working, HUD falls back to the collapsed pill. **No crash.**
- Preview text is **never** injected (test: run a full session with a fake Vosk that returns "WRONG", assert injected text comes from Whisper only).

**Must NOT**
- Vosk output kabhi inject mat karo.
- Audio cloud STT pe default me mat bhejo.
- Model download background me silently fail hone mat do — user ko dikhna chahiye.

**Tests**
`test_stt_faster_whisper.py` (mocked), `test_stt_registry.py`, `test_vosk_stream.py` (queue overflow → oldest dropped).

---

## PHASE 5 — Cleanup chain, guards, prompts

**Goal.** Likhari ki 3-tier cleanup, lekin production-grade: proper guardrails, configurable prompt, correct model defaults.

**Requirements**
- `cleanup/chain.py` — ordered provider list from config (`cleanup.providers`). Each entry has its own model + timeout. Failover is **ordered, not hardcoded**.
- **Provider defaults — IMPORTANT:**
  - Groq default model → **`openai/gpt-oss-20b`** (Production tier, 1000 tok/s, $0.075/$0.30).
    - `qwen/qwen3.8-27b` is **Preview tier** ("may be discontinued at short notice"), 450 tok/s, $0.80/$4.00, and has a thinking mode that wrecks a <200 ms cleanup target. Keep it only as an *optional* user choice.
  - `reasoning_effort="low"` must be sent to **any** reasoning model (gpt-oss **and** qwen) — Likhari only did it for gpt-oss.
  - `GROQ_TIMEOUT_S` default → **6.0** (3 s trips constantly on large models; a 404/timeout silently downgrades users).
  - Ollama timeout → **15.0** (a CPU-local model regularly needs >2 s).
  - **Model name ek hi jagah se aaye** — `cleanup/prompts.py` ya `config/defaults.py` me constant, teen jagah hardcoded nahi.
- `cleanup/guard.py`:
  - **Length guard** — output words ≤ `max(in + 3, ratio × in)`; else the tier is rejected and the chain continues.
  - **Injection guard** — detect refusal/answer patterns ("Sure, here's", "I'm sorry, I can't", "As an AI"). Reject + fall back. (Likhari only had the length guard.)
  - **Repetition guard** — detect degenerate output (same token repeated).
  - Each rejection **publishes a log warning with the actual tier error** — never fail silently.
- `cleanup/rules.py` — Tier 3, deterministic, offline. Improved over Likhari's:
  - filler removal (including single-word `um/uh/er/ah` with repeats)
  - spoken punctuation → symbols (`new paragraph`, `comma`, `period`, `question mark`, `open/close quote`, `dash`, `ellipsis`)
  - **false-start / self-correction removal** — "no wait", "scratch that", "I mean" → keep only the final version. (Likhari's rule tier did NOT do this — only the LLM tier did.)
  - repeated-word collapse
  - sentence capitalisation, terminal punctuation
  - **smart-quote toggle** — off in terminals/profiles where it matters
- `cleanup/prompts.py` — the default system prompt as an **editable library**, with the anti-hallucination rules + few-shot examples. Also a **per-profile variant** (general / technical / formal / casual).
- `text/dictionary.py` — replacements applied **longest-first** (sort by `len(find)` descending). Case-insensitive match, word boundaries, replacement verbatim. **Log every replacement that fires** (so users can see which entries work).
- `text/normalize.py` — number/date/time/unit normalization:
  - "fifteen" → "15", "twenty five" → "25"
  - "five pm" → "5:00 PM", "half past three" → "3:30"
  - "ten percent" → "10%", "twenty dollars" → "$20", "five kilos" → "5 kg"
  - Language-aware, and **toggleable per profile** (a coding profile must NOT rewrite "int" or "float" — this is a real hazard).
- **Dictionary runs BEFORE and AFTER cleanup?** — No. Apply **after** the LLM tier (the LLM may reformat and break an earlier substitution). But feed dictionary terms as **hotwords to STT** (Phase 4) and as context to the LLM.

**Acceptance criteria**
- `test_guard.py`: length guard rejects a 2× output; injection guard rejects "Sure, here's an email: ..."; repetition guard rejects "the the the the".
- A tier that throws → next tier runs, and the **actual error text is in the log**.
- `test_dictionary.py`: with entries `("js","JS")` and `("next js","Next.js")`, input `"next js"` → `"Next.js"` (longest wins), **regardless of entry order**.
- `test_rules.py`: `"um so I was thinking we should maybe uh try the new approach"` → no fillers. `"meet at 3 Friday oh no meet at 5 Wednesday"` → `"Meet at 5 Wednesday."`
- `test_normalize.py`: "fifteen" → "15"; "ten percent" → "10%"; but in the "technical" profile, `"int"` and `"float"` are untouched.
- The configured Groq model is `openai/gpt-oss-20b` by default; `reasoning_effort` is present in the payload for both gpt-oss and qwen.
- Every dictionary replacement logs `"dictionary: replaced 'X' → 'Y'"`.

**Must NOT**
- Tier failure silently fall back mat karo — log the real error.
- Hardcoded model name ek se zyada jagah nahi.
- Normalizer technical identifiers ko mat chhedhe (`int`, `float`, `str`, `id`, `self`).
- Smart quotes har profile me mat lagao.

**Tests**
`test_guard.py`, `test_rules.py`, `test_dictionary.py`, `test_normalize.py`, `test_chain.py` (fake providers, ordered failover).

---

## PHASE 6 — Injection, clipboard, undo, focus detection

**Goal.** Paste reliable ho, undo ho, aur app ka pata ho ki kaunsa app focused hai.

**Requirements**
- `inject/clipboard.py` — backends: `pbcopy/pbpaste` (macOS), `win32clipboard` (Windows), `wl-copy/wl-paste` → `xclip` → `xsel` (Linux). **Write must be verified** before paste is attempted, with **one retry** (Likhari checked but never retried — a failed write pastes the *previous* clipboard contents, which is data corruption from the user's point of view).
- `inject/paste.py` — `Cmd+V` on macOS, `Ctrl+V` elsewhere. On Wayland try **`wtype`** then **`ydotool`** (native Wayland) before falling back to pynput (XWayland only). Wait **≥350 ms** before restoring the clipboard — Electron apps (Slack, VS Code, Discord) need more; 80 ms is not enough.
- `inject/undo.py` — **revert the last injection**. Store the text that was injected + the cursor position (as far as the platform allows) so a hotkey can undo it. Minimum viable: select the injected text and replace it with the previous clipboard content, or send backspaces. This is a headline feature — "dictate wrong → one hotkey to revert".
- `inject/focus.py` — detect the foreground app:
  - macOS: `NSWorkspace.frontmostApplication()` → bundle identifier.
  - Windows: `GetForegroundWindow()` → `GetWindowThreadProcessId` → process name.
  - Linux: `_NET_ACTIVE_WINDOW` via X11, or `xdg-activation-token` on Wayland (best-effort).
  - Used for per-app profiles and for `context.py`.
- `inject/` must handle the **no-permission** case gracefully: stage the text on the clipboard and tell the user to paste manually, instead of failing silently.

**Acceptance criteria**
- `test_clipboard.py`: write→read round-trip preserves unicode + newlines; write failure → `False`, no paste attempted.
- `test_undo.py`: inject "hello", undo → clipboard and inserted text revert to the original.
- Focus detection returns a non-empty app id on the current platform (or `None` gracefully, never raises).
- On Wayland without `wtype`/`ydotool`, the app warns clearly that pynput only reaches XWayland apps — **does not silently fail**.
- Clipboard is restored to its original content after injection (verified by test).

**Must NOT**
- Clipboard restore nahi kiya jaayega bina paste complete hone ke.
- Fail hua clipboard write ke baad paste mat bhejo.
- Undo implementation me destructive keyboard simulation mat karo (Ctrl+Z style hacks) — prefer explicit text replacement.

**Tests**
`test_clipboard.py`, `test_undo.py`, `test_focus.py` (mocked per-platform).

---

## PHASE 7 — Hotkey: combos, toggle mode, per-platform backends

**Goal.** Single-key push-to-talk se aage — key **combos** aur **toggle mode**.

**Requirements**
- `core/hotkey_spec.py` — `HotkeySpec(modifiers: frozenset[str], key: str)`:
  - Parses `"ctrl+shift+space"`, `"alt_r"`, `"cmd+shift+d"`.
  - Normalises `cmd` ↔ `super` ↔ `meta`; `alt_r` ↔ `alt_gr` matching.
  - `to_pynput()` → a `pynput` chord.
- **Modes:**
  - `push_to_talk` — hold to record, release to finalize (current behaviour).
  - `toggle` — press once to start, press again to stop. **Essential for long dictation** — you can't hold a key for 30 seconds and think.
  - `double_tap` — optional: double-tap the hotkey to enter toggle mode.
- Three hotkeys configurable: **primary**, **secondary**, **undo**.
- Platform backends under `platform/{macos,windows,linux}/hotkey.py`:
  - macOS: `pynput` (needs Accessibility + Input Monitoring).
  - Windows: `pynput`; note that elevated apps need admin.
  - Linux X11: `pynput`.
  - Linux Wayland: `evdev` (reads `/dev/input/event*` directly — Wayland doesn't let apps see global keys). Requires the `input` group. **Auto-fallback to pynput with a clear warning** if unavailable.
- **Key must not be swallowed** — other apps must still receive it.
- Layout tolerance: Right Alt reported as AltGr (German/French/Nordic) must be treated as the same physical key on **both** press and release.

**Acceptance criteria**
- `test_hotkey_spec.py`: `"ctrl+shift+space"` parses to the right modifiers; `"alt_r"` ≡ `"alt_gr"`; invalid specs raise a clear error.
- `test_hotkey.py`: a synthetic press/release sequence produces exactly one `on_press` + one `on_release` (no double-fire on auto-repeat); a press without a release does **not** leave the state machine stuck in RECORDING (watchdog timeout).
- AltGr ↔ alt_r matching works for press **and** release.
- Toggle mode: two presses start and stop; the session finalizes exactly once.
- Evdev backend: a missing `/dev/input` permission produces an **actionable** error message ("add yourself to the `input` group: `sudo usermod -aG input $USER`"), not a stack trace.

**Must NOT**
- Hotkey key event ko swallow mat karo.
- Toggle mode me double-finalize mat karo.
- Wayland pe pynput ko silently fail hone mat do.

**Tests**
`test_hotkey_spec.py`, `test_hotkey.py`, `test_evdev_backend.py` (mocked).

---

## PHASE 8 — HUD: shared geometry + per-platform renderers

**Goal.** Likhari ka **duplicated wave math** fix karna, aur HUD ko configurable banana.

**Requirements**
- `ui/hud/geometry.py` — **PURE** functions, no Tk, no AppKit, no platform imports. This is the single source of truth:
  ```python
  def wave_points(
      rms: list[float], pulse_t: float, width: float, height: float, num_pts: int = 16
  ) -> list[tuple[float, float]]: ...
  def fit_text(text: str, measure: Callable[[str], float], max_w: float) -> str: ...
  def bar_geometry(levels: list[float], width: float, height: float) -> list[tuple]: ...
  def breathing_dots(pulse_t: float, width: float, height: float) -> list[tuple]: ...
  def layout_rect(state: HudState, width: float, height: float) -> HudLayout: ...
  ```
  `fit_text` takes a `measure` **callable** so NSString vs Tk font measurement stays platform-specific while the *algorithm* is shared.
- `ui/hud/model.py` — `HudModel`: state, RMS levels, preview text, status text, tier indicator, position. Pure data + `update()`.
- `ui/hud/renderer.py` — shared **semantics** (what to draw when), each platform draws it its own way.
- `ui/hud/position.py` — placement: `bottom_center`, `bottom_left`, `bottom_right`, `top_center`, `follow_cursor`, plus a custom offset. Screen selection: the screen with the foreground window, then the mouse, then the main screen.
- **The HUD must NEVER take keyboard focus.** Per platform:
  - macOS: `canBecomeKeyWindow`/`canBecomeMainWindow`/`acceptFirstResponder` → `False`; `NSStatusWindowLevel`; `setIgnoresMouseEvents_(True)`; `CanJoinAllSpaces | Transient | Stationary`.
  - Windows: `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW` via ctypes.
  - Linux/X11: `overrideredirect(True)`.
- Two layouts: **collapsed** (140×44, bars only) and **expanded** (420×96, waveform + live text).
- **Configurable** size, opacity, position, and a "show tier indicator" toggle.
- Tier indicator: show `●` local / `☁` cloud when the text went to a cloud LLM. **Users must be able to see when their audio-derived text left the machine.**
- **Linux note:** without a compositing manager X11 ignores `-alpha`, so an alpha-0 window stays painted — withdraw the window when fully faded on Linux.
- Windows high-DPI: scale geometry by the display scale factor.

**Acceptance criteria**
- `test_hud_geometry.py` — pure-function tests, no GUI. `wave_points` returns exactly `num_pts + 1` points; `fit_text` truncates at a **word boundary** and always keeps the newest words visible; identical results for the same inputs regardless of platform.
- `grep -r "math.sin" src/freewisper/ui/hud/` returns matches in **exactly one** file (`geometry.py`). **This is the acceptance test for the duplication fix.**
- `grep -rn "import tkinter\|import AppKit\|import objc" src/freewisper/ui/hud/geometry.py` returns **nothing**.
- The HUD never steals focus — on macOS assert `canBecomeKeyWindow()` is False.
- On Wayland/X11 without compositor, the window is fully unmapped (not painted) when idle.
- The tier indicator reflects whether a cloud provider was used.

**Must NOT**
- `geometry.py` me koi platform import nahi.
- Wave math do jagah nahi.
- HUD kabhi focus mat lo — ye app ka core promise hai, warna text cursor blink karega hi nahi aur paste chupke se fail hoga.

**Tests**
`test_hud_geometry.py` (pure), plus per-platform smoke scripts run manually.

---

## PHASE 9 — Command macros + context-aware cleanup + profiles

**Goal.** Likhari se genuinely aage — dictation ko assistant banao.

**Requirements**

**A. Command system**
- `commands/registry.py` — commands loaded from config + `commands/builtin.py`.
- Command definition:
  ```json
  { "id": "summarize", "triggers": ["summarize", "summarise", "tl;dr"],
    "mode": "prefix", "prompt": "...{text}", "provider": "groq",
    "model": null, "enabled": true, "cooldown_ms": 0 }
  ```
- `mode`: `prefix` (trigger at the start) or `contains` (anywhere — riskier).
- Built-in commands: `summarize`, `translate` (target language), `bullets`, `rewrite` (formal/casual/concise), `expand` (abbreviations → full form), `sql` (format as SQL), `email` (draft-ready tone), `shout`/`whisper` (case style), `code` (code-aware formatting).
- **Critical safety:** a command must **never** leak into normal dictation. Matching is exact-phrase + word-boundary. The command phrase is **stripped** before the text is passed to the command's prompt.
- A command's output must still pass the **guard** (length + injection) — a command is allowed to be longer than 1.5× only if the user explicitly opted in (`"allow_expansion": true`).

**B. Context-aware cleanup**
- `text/context.py` — extract the **focused window's surrounding text** so the LLM can match style.
  - macOS: `AXUIElement` value of the focused text field (Accessibility permission).
  - Windows: `GetGUIThreadInfo` → `hwndFocus` → `SendMessage(WM_GETTEXT)`; UI Automation as a fallback.
  - Linux: best-effort via X11/AT-SPI; often unavailable → **degrade gracefully**.
- Config: `context.enabled` (default **false**), `max_chars` (default 500), `provider` (null = same as cleanup).
- **Privacy:** context may contain sensitive text. Default OFF, and the HUD must show `☁ ctx` when context is attached.

**C. Per-app profiles**
- `profiles` map keyed by app bundle id / process name.
- Each profile can override: cleanup provider+model, style prompt variant, dictionary, snippets, normalization on/off, smart quotes on/off, context on/off.
- Example:
  ```json
  "com.microsoft.VSCode": { "style": "technical", "smart_quotes": false, "normalize": false },
  "com.apple.Terminal":   { "smart_quotes": false, "normalize": false }
  ```
- Profile resolution happens at record time (capture the focused app **when the hotkey is pressed** — not when released).

**D. Snippets (text expansion)**
- `cleanup.snippets` — map of trigger → expansion. `"adr"` → a full ADR template.
- Expansion happens **before** cleanup (so the LLM sees real text) and **before** normalization.
- Word-boundary + case-insensitive trigger; the expansion is inserted verbatim.

**Acceptance criteria**
- `test_commands.py`: "summarize this in three points we built a thing" → command `summarize` matched, prompt contains the text **without** the trigger phrase; normal dictation "I summarize my todos daily" → **no** command matched.
- A command whose output is 5× the input is rejected by the guard unless `allow_expansion` is set.
- `test_context.py`: context extraction returns `None` gracefully when unsupported — **never raises**.
- Profiles: the profile is resolved from the app focused **at hotkey-press time**, and switching to a different app mid-dictation does not change the resolved profile.
- Snippets: `"adr"` expands; `"adrenal"` does **not** (word boundary).

**Must NOT**
- Command trigger ko output me mat chhodo.
- Context default ON mat karo — privacy.
- Normalizer aur snippets ko LLM se pehle **aur** baad dono mat chalao — exactly ek baar, defined order me.

**Tests**
`test_commands.py`, `test_context.py`, `test_profiles.py`, `test_snippets.py`.

---

## PHASE 10 — History, stats, re-inject

**Goal.** Dictation history searchable ho, aur stats actually useful ho.

**Requirements**
- `history/store.py` — **SQLite** at `~/.local/state/freewisper/history.db`. WAL mode. Schema:
  ```sql
  CREATE TABLE dictations (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    raw TEXT NOT NULL,
    cleaned TEXT NOT NULL,
    command_id TEXT,
    stt_provider TEXT, stt_model TEXT,
    llm_provider TEXT, llm_model TEXT, tier TEXT,
    app_bundle TEXT,
    duration_ms REAL, stt_ms REAL, cleanup_ms REAL, total_ms REAL,
    injected INTEGER DEFAULT 0
  );
  ```
  Plus FTS5 virtual table over `cleaned` for fast search.
- `history/search.py` — search by text, filter by date/app/provider/tier.
- **Re-inject**: any history row can be re-inserted at the cursor (via the Settings History tab, and via a CLI `freewisper history --reinject <id>`).
- **Stats must be persisted and useful** (Likhari computes latency then throws it away):
  - Totals: dictations, words, characters, active time.
  - **Per-tier usage split** — how often Groq vs Ollama vs rules actually won. This is the honest measure of whether the cleanup chain is healthy.
  - **Latency distribution** — p50/p95 for STT, cleanup, total. A simple sparkline.
  - Words per minute.
- `freewisper history` CLI — list/search/export (JSON, Markdown, plain text).
- **Retention**: `history.retention_days` (default 30) + `max_rows` (default 5000). Auto-prune.
- Stats go to the **History DB**, not `config.json` — config stays small and human-editable.

**Acceptance criteria**
- `test_history.py`: insert 100 rows → search finds the right ones; FTS works on a partial word; prune respects both limits.
- Re-inject puts the exact historical text at the cursor.
- The stats panel shows a **non-zero tier split** after a run — i.e. the tier that actually ran is recorded, not the tier that was configured.
- Latency values in history match the values logged during the run (same session id).

**Must NOT**
- Raw audio history me mat rakhho (disk + privacy). Sirf text.
- Config.json ko database mat banao.

**Tests**
`test_history.py`, `test_search.py`, `test_stats.py`.

---

## PHASE 11 — Tray, Settings UI, first-run wizard

**Goal.** App "product" feel kare — proper tray, complete settings, guided setup.

**Requirements**
- **Tray** (`platform/*/tray.py`):
  - Real icon assets (`resources/icons/`) — **not emoji**. macOS template PNGs (light/dark), Windows `.ico`, Linux PNG.
  - Icon reflects state: idle / recording / processing / muted / error.
  - Menu: status, start/stop, mute toggle, command palette quick-actions, open Settings, History, Quit.
  - macOS: manual `NSStatusItem` (pystray's darwin backend races with the HUD's `NSApp` pump on Apple Silicon — this is a known Likhari finding, keep it).
  - Fallback to a **null tray** if no system tray exists (GNOME without AppIndicator, headless) — the app must still work.
- **Settings UI** (`ui/settings/`) — 8 tabs:
  1. **General** — hotkeys (primary/secondary/undo), pre-roll slider, min utterance, overlay toggle + position, start on login, language.
  2. **Transcription** — provider, model, device (auto/CPU/CUDA/MLX), beam size, preview toggle, model download with progress, hotwords from dictionary toggle.
  3. **Cleanup** — provider chain (ordered list, add/remove/reorder), per-provider model + timeout, **editable system prompt** with "reset to default", style variant, length-guard ratio, normalization toggles.
  4. **Commands** — table of commands: trigger, prompt, provider, enable/disable, add/edit/delete, test-run.
  5. **Dictionary** — table, longest-first preview, per-replacement hit counter.
  6. **Snippets** — table.
  7. **Profiles** — per-app profile editor with app-picker.
  8. **Stats** — totals, tier split, latency sparkline, WPM, history browser with re-inject.
- **Dirty tracking:** Save/Cancel enabled **only** when something changed; reverting a change re-disables them (compare snapshots, not a dirty flag).
- **Close guard:** X / Escape with unsaved changes → Save / Discard / Cancel modal.
- **Keyboard:** `Cmd+S`/`Ctrl+S` → Save. `Escape` → close guard.
- **Settings runs as a separate process** on macOS (Tk must own the main thread; the main thread is busy with the HUD). The running app live-reloads config on change via an **mtime watcher** (1 s poll) or a **file-watcher** (watchdog) — pick one, document it.
- **First-run wizard** — the #1 failure mode is permissions. On first launch:
  - Detect OS, explain exactly which permissions are needed and **where** to grant them, with deep links where possible.
  - Mic test: record 3 s, play back the level meter, confirm signal.
  - API key setup with a **Test Connection** button.
  - Optional sample dictation.
- `ui/settings` **must not** import from `core/`'s internals in a way that breaks the layering rule.

**Acceptance criteria**
- `test_settings_state.py`: dirty tracking — change → dirty; revert → clean; Save/Cancel button states match.
- Save writes config + keychain, and the **running app picks it up within ~1.5 s** without a restart (test: run the app, change the model in Settings, confirm the next dictation uses the new model).
- Tray icon visibly changes between idle and recording.
- No-tray environment → app runs fine, warning logged once.
- First-run wizard completes on a fresh profile and creates a working config.
- Settings window opens on macOS without the app hanging (the Likhari bug class).

**Must NOT**
- Settings me business logic mat likho — sirf UI + call core APIs.
- Settings process me `core/` ko import karne se pehle confirm karo ki core me koi Tk import nahi hai.

**Tests**
`test_settings_state.py` (pure logic), plus a manual UI checklist.

---

## PHASE 12 — Plugins, packaging, CI, release

**Goal.** Baar baar rebuild karne ka pain khatam + doosre logon ko contribute karne ka raasta.

**Requirements**
- **Plugin loading** — `plugins/loader.py` discovers `freewisper.stt`, `freewisper.llm`, `freewisper.cleanup` entry points. Third-party providers plug in with zero core changes. Document the contract in `docs/PROVIDERS.md`.
- **Packaging**
  - `pyproject.toml` with `[project.scripts] freewisper = "freewisper.cli:main"`.
  - **macOS**: `PyInstaller` spec → `.app` bundle; **codesign + notarize**. Also `py2app` as an alternative.
  - **Windows**: PyInstaller → `.exe` + Inno Setup installer.
  - **Linux**: PyInstaller onefile, or a `.deb`/`.rpm` + AppImage.
  - The macOS bundle needs `Info.plist` entries: `NSMicrophoneUsageDescription`, `NSAppleEventsUsageDescription`, and `LSUIElement` (no Dock icon).
- **CI** (`.github/workflows/ci.yml`):
  - Matrix: macOS (arm64 + x86_64), Windows, Linux (X11).
  - `uv sync --frozen --all-extras` + `ruff check` + `mypy` + `pytest --cov`.
  - Coverage gate: **≥ 75%** on `core/`, `text/`, `cleanup/`, `commands/`, `history/`.
  - A `pip install -e .` smoke test.
- **Release** (`.github/workflows/release.yml`): tag-triggered, builds artifacts for 3 OSes, attaches to a GitHub Release, updates `CHANGELOG.md`.
- **Docs**: `README.md` (per-OS setup, permissions, troubleshooting for the 3 most likely failures), `docs/ARCHITECTURE.md`, `docs/PRIVACY.md` (exactly what data leaves the machine, per provider), `docs/COMMANDS.md`.
- **Type checking**: `mypy --strict` on `core/`, `text/`, `cleanup/`, `commands/`.

**Acceptance criteria**
- `pip install -e . && freewisper --version` works on a clean venv.
- The macOS `.app` bundle launches **without** a terminal, has no Dock icon, and passes `codesign --verify`.
- CI is green on all 3 OSes.
- A third-party dummy plugin implementing the STT protocol registers via entry points and appears in the provider list — **proved by a test with a local package fixture**.
- `docs/PRIVACY.md` explicitly lists: which providers send audio, which send text, which send context, and the defaults for each.

**Must NOT**
- CI me secrets hardcode mat karo.
- macOS bundle me `NSMicrophoneUsageDescription` na ho to mic crash hoga — ye zaroor add karo.
- `core/` aur `platform/` ka coverage gate kam mat rakho — wahi parts regression-prone hain.

**Tests**
`test_plugin_loader.py` (fixture plugin), packaging smoke tests in CI.

---

# 5. Cross-cutting requirements (har phase me lazmi)

| Requirement | Detail |
|---|---|
| **Typing** | `mypy --strict` on `core/`, `text/`, `cleanup/`, `commands/`, `history/`. `pyproject.toml` me `[tool.mypy] strict = true`. |
| **Linting** | `ruff` with a sensible rule set (E, F, I, B, UP, SIM). No `print()` outside CLI. |
| **No secrets in logs** | A logging filter that redacts `gsk_*`, `sk-*`, and `Bearer <token>`. |
| **No secrets in config** | `config/store.py` strips key-ish fields from every nested dict on write. |
| **Thread-safety** | Every shared mutable structure has a documented lock. `core/events.py`, `core/tasks.py`, `audio/levels.py`, `audio/ring.py` explicitly. |
| **Cancellation** | Every long operation is cancellable at stage boundaries. No orphaned threads. |
| **Timeouts** | **Every** network call has a timeout. No bare `httpx.post`. |
| **Error taxonomy** | Use `core/errors.py` classes. Never swallow an exception silently — log with the actual error text. |
| **Privacy** | Cloud STT default OFF. Context default OFF. The HUD shows when anything left the machine. |
| **Accessibility** | Every setting reachable by keyboard. Focus order sane. |
| **i18n** | All user-facing strings via a translation table, not hardcoded English in logic. |

---

# 6. Testing strategy

| Layer | What | Target |
|---|---|---|
| **Unit** | `core/`, `text/`, `cleanup/`, `commands/`, `history/`, `audio/ring.py`, `ui/hud/geometry.py` — **pure, no mocks needed** | ≥ 90% coverage |
| **Integration** | Real providers behind recorded cassettes (VCR) or fake servers | ≥ 70% |
| **Platform** | macOS/Windows/Linux specific — hotkey, HUD focus, clipboard, startup | Manual checklist + CI smoke |
| **End-to-end** | A scripted session: fake audio in → assert injected text out | 1 golden test |

**Golden test idea** — one canonical WAV in `tests/fixtures/audio/`, one expected cleaned output. Any change to the cleanup chain must update this deliberately, not silently.

**CI must run on:** macOS arm64, macOS x86_64, Windows, Ubuntu (X11). Wayland is covered by a separate job with `weston` headless if feasible, else manual.

---

# 7. Non-goals (ye scope me nahi — pehle se decide kar lo)

Explicitly **out of scope for v1**:

- Any cloud account system, sync, or telemetry.
- Mobile apps.
- Meeting-mode continuous listening (needs a VAD state machine that survives long silences — v2).
- Speaker diarization.
- On-device LLM training or fine-tuning.
- A full text editor inside Freewisper.
- OS-level automation beyond paste + undo (no clicking, no window management).

**Ye list build ko focused rakhti hai.** Agent ko in par kaam karne se rokta hai.

---

# 8. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| macOS Tk main-thread rule | Settings open karte hi app hang | Settings = separate process (Phase 11). Test on every macOS CI run. |
| Wayland global hotkeys | Hotkey silently dead on GNOME/Wayland | `evdev` backend + explicit "add yourself to the `input` group" error. Never silent. |
| Always-on mic | Battery drain, privacy concern, device conflicts | Only when `pre_roll_ms > 0`; document it; allow disabling. Ring buffer bounded to 1.5 s. |
| Bluetooth profile switch | First word clipped | Pre-roll (Phase 3) + VAD trimming. |
| Provider model retirement | Cleanup silently degrades | Live `/v1/models` probe at startup + `doctor` + clear warnings. Likhari hit exactly this. |
| LLM hallucination / prompt injection | Garbage text injected at cursor | Length + injection + repetition guards; command matching is exact-phrase; context off by default. |
| Clipboard race | Pastes wrong content, loses user data | Verify write + one retry; restore only after paste completes; ≥350 ms wait. |
| CPU-only transcription | Multi-second latency on long dictation | Provider auto-detect (CUDA/MLX/whisper.cpp) + small model default + optional streaming injection. |
| Cross-platform UI drift | macOS fix breaks Linux | Pure `geometry.py` shared by both renderers; CI matrix. |
| Scope creep | Never finishes | The non-goals list above. Review before adding. |

---

# 9. Suggested build order & effort

| Phase | Effort | Depends on | Ships a working… |
|---|---|---|---|
| 1 Foundation | 2–3 h | — | CLI + config + logging |
| 2 Core | 4–5 h | 1 | Testable pipeline skeleton |
| 3 Audio | 5–6 h | 2 | Real capture **with pre-roll** |
| 4 STT | 4–5 h | 3 | Working transcription |
| 5 Cleanup | 5–6 h | 2 | Clean text |
| 6 Injection | 3–4 h | 2 | Text at cursor + undo |
| 7 Hotkey | 3–4 h | 2 | Trigger |
| 8 HUD | 6–8 h | 2 | Visible feedback |
| 9 Commands/context/profiles | 8–10 h | 5, 6 | **The product moment** |
| 10 History/stats | 4–5 h | 5 | Searchable history |
| 11 Tray/Settings/wizard | 8–10 h | all above | Shippable app |
| 12 Plugins/CI/release | 6–8 h | 11 | Distributable |

**Total ≈ 60–74 h.** Phases 1–8 = a strictly-better Likhari. Phase 9 = a different product. Phase 12 = something you can hand to other people.

**Milestone:** after **Phase 6** you have a working dictation app with pre-roll and undo. After **Phase 9** you have something Likhari isn't.

---

# 10. Definition of Done (per phase)

Every phase is done only when **all** of these are true:

- [ ] Acceptance criteria from the phase pass, **verified locally by you**.
- [ ] Tests written and green; coverage gate met for touched modules.
- [ ] `ruff check` and `mypy --strict` clean.
- [ ] No secrets in logs or config (grep-verified).
- [ ] Every new error path is **logged with its actual error text** — no silent failures.
- [ ] Public functions have docstrings explaining *why*, not just *what*.
- [ ] No new dependency added without it being justified in the PR description.
- [ ] `CHANGELOG.md` updated.
- [ ] The layering rule still holds: `core/` imports nothing platform-specific.

---

# 11. Build notes — kaise kaam karna hai

**Phase-by-phase loop:**
1. Agent ko sirf **ek** phase do. Poora spec ek saath dene se agent context lose karta hai.
2. Agent ka output compile ho, tests chale, tum manually run karke dekho.
3. **Verification script** har phase ke saath do — ek chhota script jo tum locally chalate ho aur pass/fail batata hai.
4. Agar kuch brike to **symptom** report karo.

**Testing locally:**
```bash
uv sync --all-extras
uv run pytest -q
uv run mypy src/freewisper/core src/freewisper/text
uv run ruff check .
uv run freewisper doctor
uv run freewisper run --dry-run
```

**Common breakages aur unke symptoms (pehle se jaan lo):**

| Symptom | Likely cause |
|---|---|
| Settings open karte hi app hang | Tk off the main thread (macOS). → separate process. |
| Paste kuch nahi karta | No Accessibility permission (macOS), or Wayland + no `wtype`/`ydotool`. |
| Cleanup chupke se degrade | Tier failed and fell back silently → check the `cleanup` tier in logs. |
| Pehla word kat gaya | Pre-roll = 0, or Bluetooth profile switch longer than the pre-roll. |
| HUD focus le raha hai | Missing `canBecomeKeyWindow` override / `WS_EX_NOACTIVATE`. |
| Dictation bahut slow | CPU-only Whisper → check `provider` resolution in the log. |
| Model 404 | Provider retired the model → run `freewisper doctor`. |

---

# 12. Comparison — Likhari vs Freewisper

| Area | Likhari | Freewisper |
|---|---|---|
| Architecture | Flat package, 15 modules | 4 layers, `core/` pure |
| Platform code | `if sys.platform` inside one file | Separate `platform/{macos,windows,linux}/` |
| Wave math | Duplicated in 2 places | One pure `geometry.py` |
| Pre-roll | Config + slider exist, **not implemented** | Ring buffer, always-on stream |
| STT backends | faster-whisper only (CPU hardcoded) | Pluggable: faster-whisper / MLX / whisper.cpp / cloud |
| Device accel | None (CPU only) | CUDA auto-detect + Metal via MLX |
| LLM backends | Groq + Ollama | Any OpenAI-compatible + Anthropic + llama.cpp |
| Model default | `qwen/qwen3.8-27b` (Preview, costly) | `openai/gpt-oss-20b` (Production, cheap, fast) |
| Hallucination guard | Length only | Length + injection + repetition |
| Hotwords | Not used | Dictionary terms → Whisper `initial_prompt` |
| Commands | None | Macro system + snippets |
| Context | None | Focused-window aware (opt-in) |
| Profiles | None | Per-app |
| Undo | None | Revert last injection |
| History | 2 in-memory counters, lost on restart | SQLite + FTS search + re-inject + latency stats |
| Config | Plain dict | Typed pydantic + versioned migration |
| Tests | 4 files, smoke-test style | pytest + coverage gates + CI matrix |
| Logging | stderr only | Rotating file + redaction |
| Packaging | `uv sync` from source | `.app` bundle, installer, auto-update |
| CI | None | 3-OS matrix |

---

*Spec v1.0. Bas ek phase se shuru karo — **Phase 1**. Phir har phase ke baad isi doc me "what I learned" section update karte jao, bilkul Likhari ke appendix ki tarah.*
