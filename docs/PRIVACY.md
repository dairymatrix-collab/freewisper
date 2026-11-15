# Privacy

Freewisper is built to keep your words on your machine **by default** — but
"by default" is not "always", and this page is explicit about where the
exceptions are.

## What leaves your machine

| Thing | Leaves the machine? | Default | Where to change it |
|---|---|---|---|
| **Audio** | Only with a cloud STT provider | **No** — local only | `transcription.provider` |
| **Transcript** | Yes, with the Groq cleanup tier | **Yes** (Groq tier is on) | `cleanup.tier`, `privacy.cloud_cleanup` |
| **Focused-window context** | Yes, with the cleanup tier | **No** | `context.enabled` |
| **Personal dictionary** | Yes, as Whisper hotwords | **No** (local STT only) | `transcription.hotwords_from_dictionary` |
| **Clipboard contents** | No — read for backup, restored after | Local | — |
| **Usage statistics** | Nothing is collected | — | — |

## The audio path

Audio is captured by the local microphone and passed to the local
transcription engine (faster-whisper, MLX, or whisper.cpp). **It is never
written to disk.** The recorder holds a bounded in-memory ring buffer for
the pre-roll window and nothing else.

A cloud STT provider exists but is **off by default** and must be selected
explicitly.

## The transcript path

This is the one to think about.

By default the cleanup chain runs **Groq first**, so your transcript is sent
to Groq's API. That is the whole point of the Groq tier — it produces
markedly better punctuation, capitalisation and self-correction handling
than a local model.

If you would rather it did not:

| Goal | Setting |
|---|---|
| Use a local model instead | `cleanup.tier = "ollama"` |
| Use the deterministic, offline tier | `cleanup.tier = "rule"` |
| Remove cloud cleanup entirely | `privacy.cloud_cleanup = false` |
| Force a specific provider | Set `cleanup.tier` to the provider id |

Ollama runs at `http://localhost:11434` — entirely on your machine. The
rules tier is pure regex and never touches the network.

## The HUD tells you

When the cleanup tier was a cloud provider, the HUD shows a cloud
indicator. When context is attached, it shows a separate context indicator.
You should never have to read a log to know whether your words were sent.

## Secrets

Your Groq API key lives in the **OS keychain**:

| Platform | Store |
|---|---|
| macOS | Keychain |
| Windows | Credential Manager |
| Linux | Secret Service (GNOME Keyring, KWallet, …) |

It is **never** written to `config.json`. The config writer strips
key-shaped fields recursively, on both read and write, as defence in depth
— even if a caller accidentally puts one in.

The logger redacts provider keys (`gsk_…`), bearer tokens and
`api_key=` values, including inside exception tracebacks.

## The clipboard

The injection path reads the clipboard so it can restore it afterwards, puts
the transcript there, simulates a paste, waits, then puts your original
clipboard back. The contents are not sent anywhere — but they are briefly
in the system clipboard, where another process running as your user could
read them. That is a property of the operating system's clipboard, not
something Freewisper can fix.

## The always-on microphone

The pre-roll feature requires the input stream to stay open so the first
word is not lost. **An open microphone is a privacy consideration**, and it
also costs battery.

If you would rather not have it open:

- Set `general.pre_roll_ms = 0` — the stream then opens only while the
  hotkey is held, exactly like a conventional push-to-talk app.
- This is the default behaviour of any build without the pre-roll feature.

The audio is never written to disk in either mode.

## Logs

Logs are written to a rotating file in the platform log directory, and
secrets are redacted. The log records which providers ran, how long each
stage took, and what errors happened — but not the content of your
dictations.

| Platform | Log file |
|---|---|
| Linux | `~/.local/state/freewisper/freewisper.log` |
| macOS | `~/Library/Logs/freewisper/freewisper.log` |
| Windows | `%LOCALAPPDATA%\freewisper\Logs\freewisper.log` |

## History

From Phase 10, every dictation is stored in a local SQLite database so you
can search it and re-inject it. The history is **local only**, is pruned
automatically (`history.retention_days`, `history.max_rows`), and can be
disabled entirely with `history.enabled = false`.

Only the **text** is stored — never the audio.

## Telemetry

There is none. Freewisper does not phone home, does not collect analytics,
and has no crash-reporting service. The only network traffic is the cleanup
provider you configured.
