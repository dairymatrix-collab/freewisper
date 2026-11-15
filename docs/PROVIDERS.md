# Providers

Freewisper treats speech-to-text and text-cleanup as **pluggable backends**.
The core pipeline only knows the protocols; the concrete implementations
live in `freewisper/stt/` and `freewisper/llm/`.

> **Status:** the provider modules land in Phase 4 (STT) and Phase 5 (LLM).
> The plugin entry-point groups are deliberately **not** declared in
> `pyproject.toml` yet — registering an entry point whose module does not
> exist would raise `ModuleNotFoundError` on load, which is worse than
> having none. The loader lands in Phase 12.

## The protocols

```python
class STTProvider(Protocol):
    name: str

    def available(self) -> bool: ...
    def list_models(self) -> list[str]: ...
    def transcribe(
        self, audio: Any, *, language: str | None = None, hotwords: list[str] | None = None
    ) -> STTResult: ...
    def transcribe_stream(self, audio: Any, *, language: str | None = None) -> Iterator[str]: ...


class LLMProvider(Protocol):
    name: str

    def available(self) -> bool: ...
    def list_models(self) -> list[str]: ...
    def complete(
        self, prompt: str, *, system: str | None = None, timeout_s: float | None = None
    ) -> LLMResult: ...
```

Two methods matter more than the rest:

- **`available()`** — is this backend usable right now? A missing package,
  an unreachable server, or a missing API key all return `False` rather
  than raising. The provider chain skips anything unavailable.
- **`list_models()`** — providers retire models constantly. The Settings
  dashboard shows the live list, and `freewisper doctor` warns when the
  configured model is not in it.

## Speech-to-text

| Provider | Accelerator | Notes |
|---|---|---|
| `faster-whisper` | CPU (int8), CUDA (float16) | The default. CTranslate2; no Metal path. |
| `mlx-whisper` | Apple Silicon / Metal | Much faster on macOS, where most users are. |
| `whisper.cpp` | CPU, GGML | Fast on CPU; also a good live-preview engine. |
| `openai-api` | Cloud | **Off by default.** Sends audio off the machine. |
| `vosk` | CPU | Live preview only. Never injected. |

**Device resolution** (`provider: "auto"`):

1. CUDA, if an NVIDIA GPU is present.
2. MLX, on Apple Silicon.
3. `whisper.cpp`, if a local server is running.
4. `faster-whisper` on CPU with int8.

The resolution is **logged**, so a user on an NVIDIA machine can see why
transcription is slow.

**Hotwords.** The personal dictionary is passed to Whisper as an
`initial_prompt`, so "pie torch" is heard as "PyTorch" at the source rather
than being patched afterwards by a regex. This is the single biggest
accuracy win in the app.

## Text cleanup

| Provider | Type | Default model | Timeout |
|---|---|---|---|
| `groq` | Cloud | `openai/gpt-oss-20b` | 6 s |
| `ollama` | Local | `llama3.2:3b` | 15 s |
| `rules` | Deterministic | — | — |
| `openai-compat` | Any OpenAI-compatible endpoint | — | 15 s |
| `anthropic` | Cloud | — | 15 s |
| `llama-cpp-server` | Local | — | 15 s |

The chain is **data, not code** — the order, the models and the timeouts
live in `config.json`. When a provider retires a model, the fallback list
inside the provider moves on to the next candidate, and the chain moves on
to the next provider.

**Timeouts are not arbitrary.** A 3-second timeout on a large cloud model
trips constantly and silently downgrades the user to a worse tier. A local
CPU model regularly needs more than 2 seconds. Both numbers are deliberately
generous, and a `doctor` check reports which tier is reachable.

## Guards

Every LLM tier is wrapped in three guards before its output is accepted:

1. **Length guard** — output words must not exceed `max(in + 3, 1.5 × in)`.
   A model that answered the transcript instead of cleaning it fails here.
2. **Injection guard** — refusal and answer-shaped openings ("Sure, here's",
   "As an AI") are rejected.
3. **Repetition guard** — degenerate output (the same token repeated) is
   rejected.

A tier that fails any guard is discarded and the chain continues. The
actual error is logged — nothing fails silently.

## Writing your own provider

Implement the protocol, then register it. In-tree providers register
directly; third-party packages will register through entry points once
Phase 12 lands:

```toml
[project.entry-points."freewisper.stt"]
my_asr = "my_plugin:MyASRProvider"
```

A provider must:

- Return `False` from `available()` when it cannot run — never raise.
- Honour the timeout it is given.
- Never log or echo an API key.
- Raise a `ProviderError` subclass (`ProviderUnavailable`,
  `ProviderTimeout`) for genuine failures.
