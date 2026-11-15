# Contributing to Freewisper

Thanks for your interest. This is an early-stage project and the bar for a
merged change is deliberately high: **the build must stay green, and the
rules the project claims must stay true.**

## The rules that are not negotiable

1. **`freewisper.core` stays pure.** No `tkinter`, `sounddevice`, `httpx`,
   `os`, `sys` or platform imports; no `print()`; no `open()`. This is
   enforced by `tests/test_layering.py` — if your change breaks the rule, the
   test fails rather than you noticing later.
2. **Secrets never touch disk.** API keys live in the OS keychain. The config
   writer strips key-shaped fields recursively on both read and write.
3. **Writes are atomic.** Use the helper in `config/store.py`; never write
   the config file directly.
4. **Nothing fails silently.** Every error path must log the *actual* error
   text. A swallowed exception is a bug.
5. **The HUD never takes keyboard focus.** Otherwise the caret stops blinking
   and the paste fails with no visible error.

## Getting set up

```bash
git clone https://github.com/YOUR-USERNAME/freewisper.git
cd freewisper
uv sync --all-extras
uv run pytest
```

If `uv` is not installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`.

## Before you open a pull request

```bash
uv run ruff format .          # apply formatting
uv run ruff check .           # lint — must be clean
uv run mypy                   # strict type check — must be clean
uv run pytest                 # all tests must pass
uv run python scripts/verify_phase1.py   # acceptance criteria
uv run python scripts/verify_phase2.py
```

The acceptance scripts check the *behaviour* end to end, not the source. If
you change a rule, change the criterion too — and say why in the PR.

## Commit messages

Conventional Commits, because the changelog is generated from them:

```
feat(audio): add a pre-roll ring buffer
fix(inject): restore the clipboard after a failed paste
docs(readme): explain the Linux clipboard dependencies
```

## Reporting bugs

Use the bug-report template. The most useful thing you can include is the
**symptom**, not your theory about the cause — "the paste goes to the wrong
window" is far more actionable than "I think the clipboard race is wrong".

Include:

- The output of `freewisper doctor --json`
- The relevant part of the log file (`~/.local/state/freewisper/freewisper.log`
  on Linux, `%LOCALAPPDATA%\freewisper\Logs\freewisper.log` on Windows,
  `~/Library/Logs/freewisper/freewisper.log` on macOS)
- Your OS, Python version, and which phase the failure is in

## Adding a provider

The plugin API lands in Phase 12. Until then, providers live in-tree under
`freewisper/stt/` and `freewisper/llm/`. See `docs/PROVIDERS.md`.

## Code of conduct

By participating you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).
