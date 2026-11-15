# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

Freewisper is pre-alpha. Only the latest release receives security fixes.

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Use GitHub's private reporting: *Security → Report a vulnerability* on the
repository page. Include:

- What an attacker can do, and what they need in order to do it
- Steps to reproduce
- The affected version and platform
- Any log output that helps (with secrets removed)

You will get an acknowledgement within 72 hours and an assessment within
7 days.

## Threat model

Freewisper is a **local** application. By default:

- **Audio never leaves the machine.** Transcription runs locally
  (faster-whisper or MLX).
- **The transcript may leave the machine** if the cloud cleanup tier is
  enabled — that is the Groq tier, which is on by default. The Settings
  dashboard shows a cloud indicator when this happens.
- **Focused-window context is off by default.** When enabled, surrounding
  text from the focused app is sent to the cleanup provider.
- **API keys live in the OS keychain** (macOS Keychain, Windows Credential
  Manager, Linux Secret Service) and are never written to `config.json`.

If you dictate something sensitive, either switch the cleanup tier to
`ollama` or `rules`, or turn off cloud cleanup in Privacy settings.

## What we do to keep secrets out

- The config writer strips key-shaped fields (`api_key`, `groq_api_key`,
  `access_token`, `password`, …) recursively, on both read and write.
- The logger redacts provider keys (`gsk_…`), bearer tokens and
  `api_key=` values — including inside exception tracebacks.
- Test fixtures assemble credential-shaped strings at runtime so no literal
  secret pattern is ever committed.

## What we cannot promise

Freewisper injects text at your cursor by simulating a paste. That means a
malicious process running as your user could, in principle, read your
clipboard. Freewisper does not defend against a compromised desktop
environment — it restores the clipboard after injection, but it cannot
prevent another process from watching it.

Keep the OS keychain locked, and be careful about which cleanup tier you
trust with your words.
