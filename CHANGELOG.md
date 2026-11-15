# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.0] — 2026-11-15

First tagged build. **Pre-alpha**: the configuration and orchestration layers
are complete and tested; the audio engine and the dictation loop are not wired
up yet, so the app cannot yet dictate anything.

### Added

- **Typed configuration** (`freewisper.config`) — pydantic v2 models with a
  versioned schema (`schema_version = 2`) and forward-compatible unknown keys.
- **Atomic config writes** — `tmp` file + `os.replace`, so a crash mid-write
  can never truncate `config.json`.
- **Recursive secret stripping** — key-shaped fields are removed from every
  nested structure, on both read and write. API keys live in the OS keychain
  and never reach disk.
- **Schema migration** — a v1 document (flat `hotkey` / `format` layout) is
  migrated to v2, carrying provider models across rather than dropping them.
- **Config quarantine** — a document that fails validation is preserved as
  `config.json.invalid` rather than deleted.
- **Redacting logger** (`freewisper.logging_setup`) — rotating file handler
  (5 MB × 3) plus a formatter and filter that scrub provider keys, bearer
  tokens and `api_key=` values, including inside exception tracebacks.
- **Command-line interface** — `run`, `devices`, `settings`, `history`,
  `doctor` and `version`. `doctor` runs 12 diagnostics and exits non-zero when
  something is broken; `--json` emits machine-readable output.
- **Event bus** (`freewisper.core.events`) — thread-safe publish/subscribe.
  A subscriber that raises is logged and skipped; the others still receive the
  event.
- **State machine** (`freewisper.core.states`) — a fixed transition graph. An
  illegal transition raises `InvalidTransition` *and* publishes an error.
- **Cancellable tasks** (`freewisper.core.tasks`) — cooperative cancellation
  plus exclusive groups, so a new dictation cancels the in-flight one.
- **Dictation pipeline** (`freewisper.core.pipeline`) — the five stages
  (record → transcribe → clean → inject) wired to the bus, talking to four
  collaborators through protocols only.
- **Session record** (`freewisper.core.session`) — text, timings, providers
  and outcome for every dictation.
- **Exception taxonomy** (`freewisper.core.errors`) — expected failures are
  distinguishable from bugs.
- **Executable layering rule** — `tests/test_layering.py` fails the build if
  `freewisper.core` imports anything platform-specific, or calls `print()`
  or `open()`.

### Security

- Provider defaults avoid Preview-tier models: the Groq tier uses
  `openai/gpt-oss-20b` (Production, ~2.2× faster and ~13× cheaper per output
  token than `qwen/qwen3.8-27b`, which Groq may discontinue at short notice).
- Test fixtures assemble credential-shaped strings at runtime, so no literal
  secret pattern is committed.

[Unreleased]: https://github.com/YOUR-USERNAME/freewisper/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/YOUR-USERNAME/freewisper/releases/tag/v0.1.0
