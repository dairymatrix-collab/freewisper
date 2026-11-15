## What this changes

<!-- One or two sentences. -->

## Why

<!-- The problem this solves. Not the implementation. -->

## How it was verified

<!-- Paste the command output, not a description of it. -->

- [ ] `uv run ruff format --check .` passes
- [ ] `uv run ruff check .` passes
- [ ] `uv run mypy` passes
- [ ] `uv run pytest` passes
- [ ] `uv run python scripts/verify_phase1.py` passes
- [ ] `uv run python scripts/verify_phase2.py` passes

## Checklist

- [ ] `freewisper.core` still imports nothing platform-specific (no `tkinter`, `sounddevice`, `httpx`, `os`, `sys`), calls no `print()` and no `open()`
- [ ] No API key, token or password is written to disk
- [ ] Every new error path logs the actual error text — nothing fails silently
- [ ] New public functions have docstrings that explain *why*, not just *what*
- [ ] `CHANGELOG.md` updated
- [ ] No new dependency without justification in this description

## Screenshots

<!-- If this touches the HUD, the tray, or the settings window. -->
