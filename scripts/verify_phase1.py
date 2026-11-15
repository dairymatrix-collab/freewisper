#!/usr/bin/env python3
"""Verify every Phase-1 acceptance criterion empirically.

Each criterion is checked by actually exercising the behaviour, not by
reading the source. Exits 0 only when every criterion passes.

    python scripts/verify_phase1.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
# The venv's executable directory — "bin" on POSIX, "Scripts" on Windows.
VENV_BIN = Path(sys.executable).parent
RUN_DIR = Path(os.environ.get("FREEWISPER_VERIFY_DIR", "/tmp/freewisper-verify"))

sys.path.insert(0, str(SRC))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, evidence: str = "") -> None:
    """Record and print one criterion result."""
    RESULTS.append((name, ok, evidence))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if evidence:
        print(f"         {evidence}")


def tool(name: str) -> str:
    """Path to a tool in the project venv, falling back to PATH."""
    candidate = VENV_BIN / name
    return str(candidate) if candidate.exists() else name


def env_for_run() -> dict[str, str]:
    """A fully isolated environment for every subprocess."""
    for sub in ("config", "logs", "cache", "data"):
        (RUN_DIR / sub).mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "FREEWISPER_CONFIG_DIR": str(RUN_DIR / "config"),
        "FREEWISPER_LOG_DIR": str(RUN_DIR / "logs"),
        "FREEWISPER_CACHE_DIR": str(RUN_DIR / "cache"),
        "FREEWISPER_DATA_DIR": str(RUN_DIR / "data"),
        "GROQ_API_KEY": "gsk_" + "supersecret1234567890",
    }


def main() -> int:
    """Run every criterion check."""
    env = env_for_run()
    print("PHASE 1 ACCEPTANCE CRITERIA — empirical verification")
    print("=" * 78)

    # AC1 — run --dry-run exits 0 and prints the resolved paths.
    r1 = subprocess.run(
        [tool("freewisper"), "run", "--dry-run"], env=env, capture_output=True, text=True
    )
    check(
        "AC1  run --dry-run exits 0 and prints resolved config paths",
        r1.returncode == 0 and "Resolved paths" in r1.stdout and "config file" in r1.stdout,
        f"exit={r1.returncode}",
    )

    # AC2 — devices lists inputs, or explains cleanly why it cannot.
    r2 = subprocess.run([tool("freewisper"), "devices"], env=env, capture_output=True, text=True)
    ok2 = (r2.returncode == 0 and "Input devices" in r2.stdout) or (
        r2.returncode == 2 and "sounddevice" in r2.stderr
    )
    check("AC2  devices lists inputs, or explains cleanly", ok2, f"exit={r2.returncode}")

    # AC3 — doctor: table, consistent exit code, machine-readable JSON.
    r3 = subprocess.run([tool("freewisper"), "doctor"], env=env, capture_output=True, text=True)
    r3s = subprocess.run(
        [tool("freewisper"), "doctor", "--strict"], env=env, capture_output=True, text=True
    )
    r3j = subprocess.run(
        [tool("freewisper"), "doctor", "--json"], env=env, capture_output=True, text=True
    )
    payload = json.loads(r3j.stdout)
    ok3 = (
        "[PASS]" in r3.stdout
        and (r3.returncode == 1) == ("[FAIL]" in r3.stdout)
        and (r3s.returncode == 1) == ("[WARN]" in r3s.stdout or "[FAIL]" in r3s.stdout)
        and isinstance(payload, list)
        and bool(payload)
        and payload[0]["status"] in {"PASS", "WARN", "FAIL"}
    )
    check(
        "AC3  doctor table + exit code + machine-readable JSON",
        ok3,
        f"exit={r3.returncode} strict={r3s.returncode} json_rows={len(payload)}",
    )

    # AC4 — a crash mid-write leaves the config intact and no .tmp behind.
    cfg = RUN_DIR / "config" / "config.json"
    script = f"""
import json, os, sys
sys.path.insert(0, {str(SRC)!r})
from freewisper.config.store import save_config
from freewisper.config.defaults import default_config
save_config(default_config(), {str(cfg)!r})
before = open({str(cfg)!r}).read()
import freewisper.config.store as store
original = store.os.replace
def boom(a, b):
    raise OSError("simulated crash")
store.os.replace = boom
try:
    save_config(default_config(), {str(cfg)!r})
except OSError:
    pass
store.os.replace = original
after = open({str(cfg)!r}).read()
print(json.dumps({{"intact": before == after, "tmp_left": os.path.exists({str(cfg)!r} + ".tmp")}}))
"""
    r4 = subprocess.run([tool("python"), "-c", script], env=env, capture_output=True, text=True)
    try:
        data = json.loads(r4.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        data = {"intact": False, "tmp_left": True}
    check(
        "AC4  crash mid-write leaves config intact, no .tmp left",
        bool(data.get("intact")) and not data.get("tmp_left"),
        json.dumps(data),
    )

    # AC5 — the log file exists and is not an empty stub.
    logf = RUN_DIR / "logs" / "freewisper.log"
    size = logf.stat().st_size if logf.is_file() else 0
    check("AC5  log file exists and has content", size > 0, f"{logf} ({size} bytes)")

    # AC6 — the API key never reaches the log directory or the config.
    for label, directory in (
        ("log directory", RUN_DIR / "logs"),
        ("config directory", RUN_DIR / "config"),
    ):
        hits = subprocess.run(
            ["grep", "-r", "-l", "gsk_" + "supersecret1234567890", str(directory)],
            capture_output=True,
            text=True,
        )
        found = [line for line in hits.stdout.splitlines() if line.strip()]
        check(
            f"AC6  GROQ_API_KEY never appears in the {label}",
            not found,
            f"grep found {len(found)} file(s)",
        )

    # AC7 — the log file rotates.
    rotate_script = f"""
import glob, logging, pathlib, sys
sys.path.insert(0, {str(SRC)!r})
from freewisper.logging_setup import setup_logging
path = pathlib.Path({str(RUN_DIR / "logs" / "rotate.log")!r})
setup_logging(log_file=path, console=False, max_bytes=1024, backup_count=3)
log = logging.getLogger("rotate")
for i in range(300):
    log.info("padding %d %s", i, "x" * 60)
for handler in logging.getLogger().handlers:
    handler.flush()
print(len(glob.glob(str(path) + ".*")))
"""
    r7 = subprocess.run(
        [tool("python"), "-c", rotate_script], env=env, capture_output=True, text=True
    )
    try:
        count = int(r7.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        count = 0
    check("AC7  log file rotates", count >= 1, f"{count} rotated file(s)")

    # AC8/9/10 — the quality gates.
    r8 = subprocess.run(
        [tool("python"), "-m", "pytest", "-q"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    r9 = subprocess.run([tool("mypy")], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
    r10 = subprocess.run(
        [tool("ruff"), "check", "."], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True
    )
    check(
        "AC8  pytest green",
        r8.returncode == 0,
        r8.stdout.strip().splitlines()[-1] if r8.stdout.strip() else "no output",
    )
    check(
        "AC9  mypy --strict clean",
        r9.returncode == 0,
        r9.stdout.strip().splitlines()[-1] if r9.stdout.strip() else "no output",
    )
    check(
        "AC10 ruff clean",
        r10.returncode == 0,
        r10.stdout.strip().splitlines()[-1] if r10.stdout.strip() else "no output",
    )

    print("=" * 78)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"RESULT: {passed}/{len(RESULTS)} acceptance criteria verified")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
