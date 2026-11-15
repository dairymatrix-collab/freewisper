"""Loading, migrating, and atomically saving the configuration.

Three properties this module guarantees:

1. **Atomic writes.** The document is written to a sibling ``.tmp`` file and
   then moved into place with :func:`os.replace`. A crash mid-write can never
   leave a truncated ``config.json``.
2. **Versioned.** ``schema_version`` selects a migration. Unknown future
   versions degrade to defaults rather than crashing.
3. **Secret-free.** Anything that looks like an API key is stripped on the
   way in *and* on the way out, so a key can never reach disk even if a
   caller injects one.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .defaults import default_config
from .paths import config_path
from .schema import SCHEMA_VERSION, FreewisperConfig, default_cleanup_providers

log = logging.getLogger("freewisper.config")

#: Field names that must never be written to disk. Matched case-insensitively
#: against **exact** keys (not substrings), so ``hotkey`` is unaffected.
SECRET_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "groq_api_key",
        "openai_api_key",
        "anthropic_api_key",
        "api_token",
        "access_token",
        "refresh_token",
        "bearer_token",
        "secret",
        "client_secret",
        "password",
        "passphrase",
    }
)


class ConfigError(Exception):
    """Raised when the configuration cannot be loaded or written."""


def strip_secrets(obj: Any) -> Any:
    """Recursively remove secret-looking keys from a JSON-like structure.

    Mutates ``obj`` in place and returns it, so it can be used both on a
    freshly-parsed document and on a ``model_dump()`` payload.
    """
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            if isinstance(key, str) and key.lower() in SECRET_KEYS:
                obj.pop(key, None)
                continue
            strip_secrets(obj[key])
    elif isinstance(obj, list):
        for item in obj:
            strip_secrets(item)
    return obj


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


def _hotkey_from_legacy(spec: str) -> dict[str, Any]:
    """Convert a legacy hotkey string (``"Key.alt_r"``) to the v2 shape."""
    raw = str(spec).strip()
    if raw.startswith("Key."):
        raw = raw[4:]

    parts = [p.strip().lower() for p in raw.split("+") if p.strip()]
    if not parts:
        parts = ["alt_r"]

    key = parts[-1]
    modifiers = parts[:-1]
    key = {"alt_l": "alt", "ctrl_l": "ctrl", "cmd_l": "cmd", "shift_l": "shift"}.get(key, key)
    return {"mode": "push_to_talk", "modifiers": modifiers, "key": key}


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate the flat v1 document to the nested v2 document.

    v1 kept everything at the top level (``hotkey`` as a string, ``format``
    instead of ``cleanup``); v2 nests per concern and represents a hotkey as
    a structured object.
    """
    out = dict(data)

    general: dict[str, Any] = dict(out.pop("general", {}) or {})

    hotkey = out.pop("hotkey", None)
    if hotkey is not None and "hotkey" not in general:
        general["hotkey"] = hotkey if isinstance(hotkey, dict) else _hotkey_from_legacy(str(hotkey))

    for legacy_key, target in (
        ("pre_roll_ms", "pre_roll_ms"),
        ("min_utterance_ms", "min_utterance_ms"),
        ("overlay_enabled", "overlay_enabled"),
        ("overlay_position", "overlay_position"),
        ("start_on_login", "start_on_login"),
        ("language", "language"),
    ):
        if legacy_key in out and target not in general:
            general[target] = out.pop(legacy_key)

    if general:
        out["general"] = general

    audio: dict[str, Any] = dict(out.pop("audio", {}) or {})
    if "input_device" in out and "device" not in audio:
        audio["device"] = out.pop("input_device")
    if audio:
        out["audio"] = audio

    transcription: dict[str, Any] = dict(out.pop("transcription", {}) or {})
    if "preview_enabled" in transcription:
        preview = dict(transcription.get("preview") or {})
        preview.setdefault("enabled", transcription.pop("preview_enabled"))
        transcription["preview"] = preview
    if transcription:
        out["transcription"] = transcription

    legacy_format = out.pop("format", None)
    cleanup: dict[str, Any] = dict(out.pop("cleanup", {}) or {})
    if legacy_format:
        cleanup = {**legacy_format, **cleanup}
        # The v1 document named the models as flat fields. v2 keeps them on
        # the individual provider entries, so carry them across rather than
        # dropping the user's choice on the floor.
        groq_model = cleanup.pop("groq_model", None)
        ollama_model = cleanup.pop("ollama_model", None)
        cleanup.pop("api_key", None)
        cleanup.pop("groq_api_key", None)

        providers = [p for p in (cleanup.get("providers") or []) if isinstance(p, dict)]
        if not providers and (groq_model or ollama_model):
            providers = [p.model_dump(mode="json") for p in default_cleanup_providers()]
        for provider in providers:
            if provider.get("id") == "groq" and groq_model:
                provider.setdefault("model", groq_model)
            if provider.get("id") == "ollama" and ollama_model:
                provider.setdefault("model", ollama_model)
        if providers:
            cleanup["providers"] = providers

    if "dictionary" in out and "dictionary" not in cleanup:
        cleanup["dictionary"] = out.pop("dictionary")
    if "snippets" in out and "snippets" not in cleanup:
        cleanup["snippets"] = out.pop("snippets")

    if cleanup:
        out["cleanup"] = cleanup

    out["schema_version"] = 2
    return out


#: ``{from_version: migration}`` — each returns the document at version+1.
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _migrate_v1_to_v2,
}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Run every migration needed to bring ``data`` to :data:`SCHEMA_VERSION`."""
    try:
        version = int(data.get("schema_version", 1))
    except (TypeError, ValueError):
        version = 1

    guard = 0
    while version < SCHEMA_VERSION:
        guard += 1
        if guard > 50:  # pragma: no cover - defensive, migrations are finite
            log.warning("Migration loop exceeded 50 iterations; using defaults.")
            break
        migrator = _MIGRATIONS.get(version)
        if migrator is None:
            log.warning(
                "No migration available from schema version %s; unknown fields kept as-is.",
                version,
            )
            break
        data = migrator(data)
        version = int(data.get("schema_version", version + 1))

    data["schema_version"] = SCHEMA_VERSION
    return data


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def load_config(path: Path | None = None) -> FreewisperConfig:
    """Load the configuration, falling back to defaults on any problem.

    A document that fails validation is preserved next to the original as
    ``<name>.invalid`` so nothing the user wrote is ever lost.
    """
    target = Path(path) if path is not None else config_path()

    if not target.exists():
        log.debug("No config at %s; using defaults.", target)
        return default_config()

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Config at %s unreadable (%s); using defaults.", target, exc)
        return default_config()

    if not isinstance(raw, dict):
        log.warning("Config at %s is not a JSON object; using defaults.", target)
        return default_config()

    strip_secrets(raw)
    migrated = migrate(raw)

    try:
        return FreewisperConfig.model_validate(migrated)
    except ValidationError as exc:
        log.warning("Config at %s failed validation (%s); using defaults.", target, exc)
        _quarantine(target)
        return default_config()


def _quarantine(target: Path) -> Path | None:
    """Move an invalid config aside so the user can inspect and fix it."""
    backup = target.with_name(target.name + ".invalid")
    try:
        os.replace(target, backup)
        log.warning("Invalid config moved to %s", backup)
    except OSError as exc:  # pragma: no cover - filesystem dependent
        log.warning("Could not quarantine invalid config: %s", exc)
        return None
    return backup


def save_config(cfg: FreewisperConfig, path: Path | None = None) -> Path:
    """Write the configuration atomically, without secrets.

    Returns the path that was written.
    """
    target = Path(path) if path is not None else config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = cfg.model_dump(mode="json")
    strip_secrets(payload)

    tmp = target.with_name(target.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise

    return target
