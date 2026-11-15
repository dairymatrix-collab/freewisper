"""Freewisper command-line interface.

Subcommands:

    run       start the dictation app (Phase 2+); ``--dry-run`` validates the
              environment and prints resolved paths without starting anything
    devices   list audio input devices
    settings  open the settings dashboard (Phase 11)
    history   inspect the dictation history database (Phase 10)
    doctor    diagnose the installation; exit code 1 if something is broken
    version   print the version
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .config.paths import (
    cache_dir,
    config_dir,
    config_path,
    data_dir,
    history_db_path,
    log_dir,
    log_file,
    models_dir,
)
from .config.store import load_config
from .logging_setup import setup_logging

log = logging.getLogger("freewisper.cli")

_STATUS_PASS = "PASS"
_STATUS_WARN = "WARN"
_STATUS_FAIL = "FAIL"


@dataclass(frozen=True)
class Check:
    """One diagnostic result."""

    name: str
    status: str
    detail: str

    @property
    def failed(self) -> bool:
        return self.status == _STATUS_FAIL

    @property
    def degraded(self) -> bool:
        return self.status == _STATUS_WARN


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="freewisper",
        description="Freewisper — push-to-talk voice dictation.",
    )
    parser.add_argument("--version", action="version", version=f"freewisper {__version__}")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        metavar="PATH",
        help="Use a specific config.json instead of the default location.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Start the dictation app.")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the environment and print resolved paths, then exit.",
    )
    run_parser.set_defaults(func=cmd_run)

    devices_parser = sub.add_parser("devices", help="List audio input devices.")
    devices_parser.set_defaults(func=cmd_devices)

    settings_parser = sub.add_parser("settings", help="Open the settings dashboard.")
    settings_parser.set_defaults(func=cmd_settings)

    history_parser = sub.add_parser("history", help="Inspect the dictation history.")
    history_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="How many recent entries to show.",
    )
    history_parser.set_defaults(func=cmd_history)

    doctor_parser = sub.add_parser("doctor", help="Diagnose the installation.")
    doctor_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures when computing the exit code.",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON instead of a table.",
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    version_parser = sub.add_parser("version", help="Print the version.")
    version_parser.set_defaults(func=cmd_version)

    return parser


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    """Start the app, or validate the environment with ``--dry-run``."""
    cfg = load_config(Path(args.config) if args.config else None)

    if args.dry_run:
        log.info("dry run starting")
        print("Freewisper — dry run")
        print("=" * 60)
        print(f"  version            {__version__}")
        print(f"  python             {platform.python_version()} ({sys.executable})")
        print(f"  platform           {platform.system()} {platform.release()}")
        print()
        print("Resolved paths")
        print("-" * 60)
        for label, path in (
            ("config file", config_path()),
            ("config dir", config_dir()),
            ("cache dir", cache_dir()),
            ("models dir", models_dir()),
            ("log file", log_file()),
            ("log dir", log_dir()),
            ("data dir", data_dir()),
            ("history db", history_db_path()),
        ):
            print(f"  {label:<18} {path}")
        print()
        print("Effective configuration")
        print("-" * 60)
        for key, value in cfg.describe().items():
            print(f"  {key:<22} {value}")
        print()
        print("Dry run complete — nothing was started.")
        log.info(
            "dry run complete: config=%s log=%s",
            config_path(),
            log_file(),
        )
        return 0

    print(
        "The dictation engine is not wired up yet — that lands in Phase 2+.\n"
        "Use `freewisper run --dry-run` to inspect the environment, or `freewisper doctor`\n"
        "to check the installation.",
        file=sys.stderr,
    )
    return 3


def cmd_devices(args: argparse.Namespace) -> int:
    """List audio input devices."""
    try:
        import sounddevice as sd
    except Exception as exc:  # noqa: BLE001 - optional dependency
        print(
            "sounddevice is not available in this environment.\n"
            "Install the audio extra:  pip install 'freewisper[audio]'\n"
            f"({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return 2

    try:
        devices = sd.query_devices()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not query audio devices: {exc}", file=sys.stderr)
        return 1

    print("Input devices")
    print("-" * 72)
    found = 0
    for index, device in enumerate(devices):
        if device.get("max_input_channels", 0) <= 0:
            continue
        found += 1
        rate = int(device.get("default_samplerate", 0))
        channels = int(device.get("max_input_channels", 0))
        print(f"  #{index:<3} {device.get('name', '?'):<44} {rate:>6} Hz  {channels} ch")

    if found == 0:
        print("  (no input devices found)")
        print()
        return 1

    print()
    try:
        default = sd.query_devices(kind="input")
        print(f"Default input: #{default.get('index')} — {default.get('name')}")
    except Exception:  # noqa: BLE001 - informational only
        pass
    return 0


def cmd_settings(args: argparse.Namespace) -> int:
    """Open the settings dashboard (arrives in Phase 11)."""
    print("Settings dashboard is not implemented yet (Phase 11).")
    print(f"The configuration lives at: {config_path()}")
    return 3


def cmd_history(args: argparse.Namespace) -> int:
    """Inspect the dictation history (arrives in Phase 10)."""
    db = history_db_path()
    print(f"History database: {db}")
    if not db.exists():
        print("No history yet — the history engine lands in Phase 10.")
        return 0
    size = db.stat().st_size
    print(f"Database size: {size} bytes")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    """Print the version."""
    print(f"freewisper {__version__}")
    return 0


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _check_python() -> Check:
    version = platform.python_version()
    ok = sys.version_info >= (3, 10)
    return Check(
        "python",
        _STATUS_PASS if ok else _STATUS_FAIL,
        f"{version} ({sys.executable})",
    )


def _check_config() -> Check:
    path = config_path()
    if not path.exists():
        return Check("config", _STATUS_WARN, f"not created yet — {path}")
    try:
        cfg = load_config(path)
    except Exception as exc:  # noqa: BLE001
        return Check("config", _STATUS_FAIL, f"could not load {path}: {exc}")
    return Check("config", _STATUS_PASS, f"{path} (schema v{cfg.schema_version})")


def _check_writable(label: str, path: Path) -> Check:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".freewisper-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check(label, _STATUS_FAIL, f"{path} is not writable: {exc}")
    return Check(label, _STATUS_PASS, str(path))


def _check_api_key() -> Check:
    try:
        import keyring
    except Exception:  # noqa: BLE001
        env = os.environ.get("GROQ_API_KEY")
        if env:
            return Check("api key", _STATUS_PASS, "from $GROQ_API_KEY")
        return Check(
            "api key",
            _STATUS_WARN,
            "not set — install the 'secrets' extra or export GROQ_API_KEY",
        )

    try:
        key = keyring.get_password("Freewisper", "groq_api_key")
    except Exception as exc:  # noqa: BLE001
        return Check("api key", _STATUS_WARN, f"keyring unavailable: {exc}")

    if key:
        return Check("api key", _STATUS_PASS, "present in the OS keychain")
    if os.environ.get("GROQ_API_KEY"):
        return Check("api key", _STATUS_PASS, "from $GROQ_API_KEY")
    return Check("api key", _STATUS_WARN, "not set — the Groq tier will be skipped")


def _check_import(label: str, module: str, extra: str) -> Check:
    try:
        __import__(module)
    except Exception as exc:  # noqa: BLE001
        return Check(
            label,
            _STATUS_WARN,
            f"not available ({type(exc).__name__}) — install the '{extra}' extra",
        )
    return Check(label, _STATUS_PASS, f"{module} importable")


def _check_stt() -> Check:
    try:
        import faster_whisper  # type: ignore[import-not-found]  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return Check(
            "speech-to-text",
            _STATUS_WARN,
            f"faster-whisper not available ({type(exc).__name__}) — install the 'audio' extra",
        )

    cached = []
    if models_dir().exists():
        cached = [p for p in models_dir().iterdir() if p.is_dir()]
    if cached:
        return Check(
            "speech-to-text", _STATUS_PASS, f"faster-whisper, {len(cached)} model(s) cached"
        )
    return Check(
        "speech-to-text",
        _STATUS_WARN,
        "faster-whisper available, but no model is downloaded yet",
    )


def _check_hotkey() -> Check:
    try:
        import pynput.keyboard  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return Check(
            "hotkey",
            _STATUS_WARN,
            f"pynput not available ({type(exc).__name__}) — install the 'hotkey' extra",
        )

    if platform.system() == "Linux" and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        try:
            import evdev  # noqa: F401
        except Exception:  # noqa: BLE001
            return Check(
                "hotkey",
                _STATUS_WARN,
                "Wayland: pynput only reaches XWayland — install the 'wayland' extra "
                "and join the 'input' group for global hotkeys",
            )
    return Check("hotkey", _STATUS_PASS, "pynput importable")


def _check_hud() -> Check:
    if platform.system() == "Darwin":
        try:
            import AppKit  # type: ignore[import-not-found]  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            return Check(
                "hud",
                _STATUS_WARN,
                f"PyObjC not available ({type(exc).__name__}) — install the 'macos' extra",
            )
        return Check("hud", _STATUS_PASS, "PyObjC (native)")

    try:
        import tkinter  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return Check(
            "hud",
            _STATUS_WARN,
            f"tkinter not available ({type(exc).__name__})",
        )
    return Check("hud", _STATUS_PASS, "tkinter")


def _check_permissions() -> Check:
    if platform.system() != "Darwin":
        return Check("permissions", _STATUS_PASS, "not applicable on this platform")
    try:
        from ApplicationServices import AXIsProcessTrusted  # type: ignore[import-not-found]

        trusted = bool(AXIsProcessTrusted())
    except Exception:  # noqa: BLE001
        return Check("permissions", _STATUS_WARN, "could not query Accessibility trust")
    if trusted:
        return Check("permissions", _STATUS_PASS, "Accessibility granted")
    return Check(
        "permissions",
        _STATUS_WARN,
        "Accessibility not granted — the HUD and paste injection will not work",
    )


def collect_checks() -> list[Check]:
    """Run every diagnostic check."""
    return [
        _check_python(),
        _check_config(),
        _check_writable("config dir", config_dir()),
        _check_writable("cache dir", cache_dir()),
        _check_writable("log dir", log_dir()),
        _check_api_key(),
        _check_import("audio backend", "sounddevice", "audio"),
        _check_stt(),
        _check_hotkey(),
        _check_hud(),
        _check_import("tray", "pystray", "tray"),
        _check_permissions(),
    ]


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnose the installation."""
    checks = collect_checks()

    for check in checks:
        log.info("doctor: [%s] %s — %s", check.status, check.name, check.detail)

    if args.as_json:
        print(
            json.dumps(
                [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks],
                indent=2,
            )
        )
    else:
        width = max(len(c.name) for c in checks)
        print("Freewisper doctor")
        print("=" * 76)
        for check in checks:
            print(f"  [{check.status}] {check.name.ljust(width)}  {check.detail}")
        print("=" * 76)

    failures = [c for c in checks if c.failed]
    degraded = [c for c in checks if c.degraded]

    # With --json the summary must not pollute stdout, or the output is not
    # machine-readable.
    summary_stream = sys.stderr if getattr(args, "as_json", False) else sys.stdout

    if failures:
        print(
            f"{len(failures)} check(s) FAILED — the app cannot work as-is.",
            file=summary_stream,
        )
        return 1
    if degraded:
        print(
            f"0 failed, {len(degraded)} degraded. "
            "Some features need extra packages — see the details above.",
            file=summary_stream,
        )
        return 1 if getattr(args, "strict", False) else 0

    print("All checks passed.", file=summary_stream)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(
        log_file=log_file(),
        level=logging.DEBUG if args.verbose else logging.INFO,
    )
    log.info("freewisper %s — command: %s", __version__, args.command)

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        log.exception("Unhandled error in %s", args.command)
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
