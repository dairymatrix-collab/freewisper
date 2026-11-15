# Commands

A **command** turns part of a dictation into a different kind of output.
"Summarize this in three bullets" should produce bullets, not the sentence
"Summarize this in three bullets".

> **Status:** the command system lands in Phase 9. This document describes
> the design that the build spec commits to, so the behaviour is fixed
> before the code exists.

## The shape

```json
{
  "id": "summarize",
  "triggers": ["summarize", "summarise", "tl;dr"],
  "mode": "prefix",
  "prompt": "Summarize the following dictation in at most three bullet points. Return only the bullets.\n\n{text}",
  "provider": "groq",
  "model": null,
  "enabled": true,
  "allow_expansion": false
}
```

| Field | Meaning |
|---|---|
| `id` | Stable identifier, recorded in the history database. |
| `triggers` | The phrases that activate the command. |
| `mode` | `prefix` — trigger must start the utterance. `contains` — anywhere. |
| `prompt` | The template. `{text}` is replaced with the dictation. |
| `provider` | Which cleanup backend to use. `null` means the normal chain. |
| `model` | Override the provider's model. `null` means the provider's default. |
| `enabled` | Whether the command is active. |
| `allow_expansion` | Permit output longer than the input. |

## Built-in commands

| Command | Triggers | Effect |
|---|---|---|
| `summarize` | summarize, summarise, tl;dr | At most three bullet points |
| `bullets` | bullet points, as bullets | Rewrites as a bulleted list |
| `rewrite` | rewrite formally / casually / concisely | Restyles the text |
| `translate` | translate to … | Translates into the named language |
| `sql` | write sql, sql query | Converts a description into one query |
| `email` | draft email, write an email | Rewrites as a short professional email |

Users can edit, disable, add and delete commands in the Settings dashboard.

## Safety rules

**A command must never leak into normal dictation.** Matching is exact
phrase plus word boundary. "I summarise my todos every morning" must not
trigger the `summarize` command — it is ordinary speech. Only a *prefix*
match (or an exact `contains` match the user opted into) activates a
command.

**The trigger phrase is stripped** before the text reaches the command's
prompt.

**A command's output still passes the guards.** The length, injection and
repetition guards apply. A command that legitimately produces more text than
it consumed — a summary is shorter, but "expand these abbreviations" is
longer — sets `allow_expansion: true` explicitly.

**A command cannot reach a different provider by accident.** If a command
names a provider that is unavailable, it falls back through the normal chain
rather than failing.

## Snippets

Snippets are the simplest form of expansion: a typed abbreviation becomes a
block of text.

```json
{
  "adr": "Architecture Decision Record:\n\n## Context\n\n## Decision\n\n## Consequences\n\n",
  "sig": "Best regards,\n{name}"
}
```

Snippets expand **before** cleanup, so the model sees real text rather than
an abbreviation. Matching is word-boundary and case-insensitive, so `adr`
expands but `adrenal` does not.

## Context-aware cleanup

With `context.enabled` turned on, the text surrounding the caret is
extracted from the focused application and given to the model, so it can:

- match the surrounding capitalisation style,
- continue an existing bullet list,
- resolve "the third one" against what is above.

This is **off by default** — the surrounding text can be sensitive, and it
would be sent to the cloud cleanup tier. When it is on, the HUD shows a
cloud indicator so you know it happened.

| Platform | How the context is read |
|---|---|
| macOS | `AXUIElement` value of the focused text field (Accessibility permission) |
| Windows | `GetGUIThreadInfo` → `WM_GETTEXT`, with UI Automation as a fallback |
| Linux | X11 / AT-SPI where available; often unavailable, and degrades gracefully |

## `freewisper devices`

Lists the microphones, the system default and the device the configuration
would actually use.

```
$ freewisper devices
Input devices
------------------------------------------------------------------------
  #0   Built-in Microphone                                44100 Hz  2 ch
  #3   USB Headset Mic                                    48000 Hz  1 ch

Default input: #0 — Built-in Microphone
Configured input: #3 — USB Headset Mic
```

Exit codes: `0` success, `1` no input devices found, `2` the audio backend
could not be loaded (install the `audio` extra).
