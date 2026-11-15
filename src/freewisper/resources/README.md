# Resources

Static assets shipped inside the package.

| Path | Purpose | Status |
|---|---|---|
| `icons/` | Tray and HUD icons | Phase 11 — the tray currently falls back to a generated icon |
| `prompts/` | Overridable prompt templates | Phase 5 — the default prompt lives in `freewisper/cleanup/prompts.py` for now |

Icons must be shipped as real template assets rather than emoji: the macOS
menu bar expects a template image that follows the light/dark theme, and
emoji render inconsistently across platforms.

Recommended sizes:

- `icons/tray.png` — 22×22 @1x, 44×44 @2x (macOS template)
- `icons/tray-muted.png` — the same, in the muted state
- `icons/tray.ico` — 16, 32, 48, 256 px (Windows)
