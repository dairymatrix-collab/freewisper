"""Default configuration and the built-in command set.

Everything here is what a fresh install gets. The values were chosen against
the live provider landscape (Nov 2026):

* Groq defaults to ``openai/gpt-oss-20b`` — a **Production** model.
  ``qwen/qwen3.8-27b`` is a *Preview* model ("may be discontinued at short
  notice"), is ~2.2x slower, and costs ~13x more per output token. It stays
  available as an explicit user choice, but must not be the default.
* The Groq timeout is 6 s, not 3 s — a large model routinely needs longer,
  and a timeout silently downgrades the user to a worse tier.
* The Ollama timeout is 15 s — a local CPU model regularly needs >2 s.
"""

from __future__ import annotations

from .schema import (
    AudioConfig,
    CleanupConfig,
    CommandConfig,
    FreewisperConfig,
    GeneralConfig,
    HotkeySpec,
    TranscriptionConfig,
    default_cleanup_providers,
)

#: Default Groq model — Production tier, fast, cheap.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"

#: Default Ollama model — runs fully offline.
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"

#: Default cleanup provider chain, in failover order.
DEFAULT_CLEANUP_PROVIDERS = default_cleanup_providers()

#: Personal dictionary seed entries — they double as format documentation.
DEFAULT_DICTIONARY: list[list[str]] = [
    ["kubernetes", "K8s"],
    ["pie torch", "PyTorch"],
    ["next js", "Next.js"],
    ["grpc", "gRPC"],
]

#: Built-in macro commands. Users can edit, disable, or add their own.
DEFAULT_COMMANDS: list[CommandConfig] = [
    CommandConfig(
        id="summarize",
        triggers=["summarize", "summarise", "tl;dr"],
        prompt=(
            "Summarize the following dictation in at most three bullet points. "
            "Return only the bullets.\n\n{text}"
        ),
    ),
    CommandConfig(
        id="bullets",
        triggers=["bullet points", "as bullets"],
        prompt="Rewrite the following as a bulleted list. Return only the list.\n\n{text}",
    ),
    CommandConfig(
        id="rewrite",
        triggers=["rewrite formally", "rewrite casually", "rewrite concisely"],
        prompt=(
            "Rewrite the following text. Return only the rewritten text, with no "
            "preamble.\n\n{text}"
        ),
    ),
    CommandConfig(
        id="translate",
        triggers=["translate to"],
        prompt=(
            "Translate the following text into the language named after "
            "'translate to'. Return only the translation.\n\n{text}"
        ),
    ),
    CommandConfig(
        id="sql",
        triggers=["write sql", "sql query"],
        prompt=(
            "Convert the following description into a single SQL query. Return "
            "only the SQL, no explanation.\n\n{text}"
        ),
    ),
    CommandConfig(
        id="email",
        triggers=["draft email", "write an email"],
        prompt=(
            "Rewrite the following as a short, professional email. Return only "
            "the email body.\n\n{text}"
        ),
    ),
]


def default_config() -> FreewisperConfig:
    """Return a fresh default configuration.

    A new object is built on every call so callers can mutate the result
    without contaminating the template.
    """
    return FreewisperConfig(
        general=GeneralConfig(
            hotkey=HotkeySpec(key="alt_r"),
            pre_roll_ms=500,
            min_utterance_ms=300,
        ),
        audio=AudioConfig(),
        transcription=TranscriptionConfig(),
        cleanup=CleanupConfig(
            providers=[p.model_copy(deep=True) for p in DEFAULT_CLEANUP_PROVIDERS],
            dictionary=[list(pair) for pair in DEFAULT_DICTIONARY],
        ),
        commands=[c.model_copy(deep=True) for c in DEFAULT_COMMANDS],
        profiles={},
    )
