# Freewisper

[![CI](https://github.com/dairymatrix-collab/freewisper/actions/workflows/ci.yml/badge.svg)](https://github.com/dairymatrix-collab/freewisper/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code of Conduct](https://img.shields.io/badge/CoC-enforced-blue.svg)](CODE_OF_CONDUCT.md)

Cross-platform **push-to-talk voice dictation**. Hold a key, speak, release — cleaned text lands at your cursor.

Local speech-to-text with pluggable LLM cleanup, a floating HUD that never steals keyboard focus, and text inserted wherever your caret is.

> **Status: Phase 3 of 12 — the audio engine is done.**
> The configuration layer, logging, CLI and diagnostics are built and tested (Phase 1).
> The event bus, state machine, cancellable task runner and dictation pipeline are built
> and tested (Phase 2). The always-on recorder, the pre-roll ring buffer, the energy VAD
> and hot-plug device recovery are built and tested (Phase 3).
> See [`docs/BUILD-SPEC.md`](docs/BUILD-SPEC.md) for the full plan.

---

## What it will be

```
Hotkey press
   └─▶ Recorder (always-on stream + pre-roll ring buffer)
        └─▶ Vosk live preview  → HUD shows provisional text (never injected)
Hotkey release
   └─▶ faster-whisper / MLX → final transcript (source of truth)
        └─▶ Cleanup chain: Groq → Ollama → deterministic rules
             └─▶ Personal dictionary + number/date normalisation
                  └─▶ Clipboard backup → paste → restore
```

## Architecture

Four layers, one direction. `core/` never imports from the layers above it.

```
ui/          Settings dashboard, HUD renderer      ← presentation
platform/    macos/ windows/ linux/                ← OS integration
providers/   stt/ llm/ inject/                     ← swappable backends
core/        events, states, tasks, pipeline       ← pure logic, zero I/O
```

### The core layer (built, tested, shipping)

| Module | What it does |
|---|---|
| `core/events.py` | Thread-safe pub/sub. A subscriber that raises is logged and skipped — the rest still get the event. |
| `core/states.py` | `IDLE → ARMED → RECORDING → TRANSCRIBING → CLEANING → INJECTING → IDLE`. Illegal moves raise `InvalidTransition` **and** publish an error. |
| `core/tasks.py` | Cooperative cancellation. Exclusive groups: a new task cancels the in-flight one in the same group. |
| `core/pipeline.py` | The five stages, wired to the bus. Talks to four collaborators through **protocols only**. |
| `core/session.py` | One dictation's record: text, timings, providers, command, outcome. |
| `core/errors.py` | The exception taxonomy, so expected failures are distinguishable from bugs. |

Because the pipeline takes protocols, a full dictation runs in a test with **no audio device, no network, and no GUI** — the tests assert on the exact string that would have landed at the cursor.

The layering rule is **executable**, not a comment: `tests/test_layering.py` parses the `core` package and fails if it imports `tkinter`, `sounddevice`, `httpx`, `os`, `sys`, or anything platform-specific — or calls `print()` or `open()`.

## What works today

| Command | What it does |
|---|---|
| `freewisper run --dry-run` | Validate the environment, print every resolved path and the effective config |
| `freewisper devices` | List audio input devices |
| `freewisper doctor` | 12-point installation diagnostic (human table or `--json`) |
| `freewisper history` | Locate the dictation history database |
| `freewisper version` | Print the version |

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # base + dev tooling
pip install -e ".[audio,hotkey,tray,secrets]"   # full features
```

Optional extras are platform-aware:

| Extra | Provides | Needed on |
|---|---|---|
| `audio` | sounddevice, numpy, scipy | all platforms |
| `hotkey` | pynput | all platforms |
| `tray` | pystray, pillow | all platforms |
| `secrets` | keyring | all platforms |
| `macos` | pyobjc-framework-Cocoa / Quartz / ApplicationServices | macOS |
| `windows` | pywin32 | Windows |
| `wayland` | evdev | Linux/Wayland |

> **Linux note — the hotkey and wayland extras need a C compiler.**
> `pynput` depends on `evdev` on Linux, and `evdev` ships only sdists and
> always builds a C extension. Install the toolchain first:
>
> ```bash
> sudo apt install python3-dev build-essential   # Debian / Ubuntu
> ```
>
> Everything else installs from wheels, with no compiler. macOS and Windows
> never need one.

## Configuration

`~/.config/freewisper/config.json` — same path on every OS.

```json
{
  "schema_version": 2,
  "general": {
    "hotkey": { "mode": "push_to_talk", "modifiers": [], "key": "alt_r" },
    "pre_roll_ms": 500,
    "min_utterance_ms": 300
  },
  "cleanup": {
    "tier": "auto",
    "providers": [
      { "id": "groq", "type": "groq", "model": "openai/gpt-oss-20b", "timeout_s": 6.0 },
      { "id": "ollama", "type": "ollama", "model": "llama3.2:3b", "timeout_s": 15.0 },
      { "id": "rules", "type": "rules", "timeout_s": 1.0 }
    ],
    "dictionary": [["kubernetes", "K8s"], ["pie torch", "PyTorch"]]
  }
}
```

Every path is overridable by environment variable, which is what makes the test suite hermetic:

```
FREEWISPER_CONFIG_DIR   FREEWISPER_CONFIG_FILE
FREEWISPER_CACHE_DIR    FREEWISPER_LOG_DIR
FREEWISPER_LOG_FILE     FREEWISPER_DATA_DIR
FREEWISPER_HISTORY_DB
```

## Design rules

These are enforced, not aspirational:

1. **`core/` is pure.** No OS, network, or filesystem imports. That is what makes the orchestration logic testable without mocks.
2. **Secrets never touch disk.** API keys live in the OS keychain. The config writer strips key-shaped fields recursively, on both read and write.
3. **Writes are atomic.** `tmp` file + `os.replace`. A crash mid-write cannot corrupt the config.
4. **Logs are redacted.** Provider keys, bearer tokens, and `api_key=` values are scrubbed — including inside exception tracebacks.
5. **Nothing fails silently.** Every error path logs the *actual* error text.
6. **The HUD never takes focus.** Otherwise the caret stops blinking and the paste silently fails.

## Before you publish

Three things to change before the first push:

1. **Replace `dairymatrix-collab`** in `pyproject.toml` (`[project.urls]`) and in
   `CHANGELOG.md` with your GitHub handle.
2. **Set the copyright holder** in `LICENSE`.
3. **Check the repository name and description** on GitHub — the default
   description is written for the app, not the repo.

Then:

```bash
git add -A
git commit -m "feat: initial release — config, core, CLI"
git remote add origin https://github.com/dairymatrix-collab/freewisper.git
git push -u origin main
```

The CI workflow will run on all three platforms and check the same gates you
can run locally.

## Development

```bash
uv sync --all-extras
uv run pytest                       # 77 tests
uv run pytest --cov                 # coverage report
uv run mypy                         # strict
uv run ruff check .
uv run freewisper doctor            # diagnose your machine
```

### Quality gates

| Gate | Threshold |
|---|---|
| `pytest` | 168 passing, zero skipped |
| `mypy` | `--strict`, zero errors across 16 modules |
| `ruff` | zero findings |
| Phase 1 acceptance | 11/11 — `python scripts/verify_phase1.py` |
| Phase 2 acceptance | 9/9 — `python scripts/verify_phase2.py` |
| Phase 3 acceptance | 13/13 — `python scripts/verify_phase3.py` |

## Licence

MIT.
