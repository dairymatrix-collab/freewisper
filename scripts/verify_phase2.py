#!/usr/bin/env python3
"""Verify every Phase-2 acceptance criterion empirically.

Each criterion is checked by actually exercising the behaviour.

    python scripts/verify_phase2.py
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
# The venv's executable directory — "bin" on POSIX, "Scripts" on Windows.
VENV_BIN = Path(sys.executable).parent
CORE_DIR = SRC / "freewisper" / "core"

sys.path.insert(0, str(SRC))

# The checks deliberately trigger error paths; keep the output readable.
logging.getLogger("freewisper").setLevel(logging.CRITICAL)

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


def main() -> int:
    """Run every criterion check."""
    print("PHASE 2 ACCEPTANCE CRITERIA — empirical verification")
    print("=" * 78)

    # ------------------------------------------------------------------
    # AC1 — every legal transition works, every illegal one raises.
    # ------------------------------------------------------------------
    from freewisper.core.errors import InvalidTransition
    from freewisper.core.events import Event, EventBus
    from freewisper.core.states import LEGAL_TRANSITIONS, State, StateMachine

    paths: dict[State, list[State]] = {
        State.IDLE: [],
        State.ARMED: [State.ARMED],
        State.RECORDING: [State.ARMED, State.RECORDING],
        State.TRANSCRIBING: [State.ARMED, State.RECORDING, State.TRANSCRIBING],
        State.CLEANING: [State.ARMED, State.RECORDING, State.TRANSCRIBING, State.CLEANING],
        State.INJECTING: [
            State.ARMED,
            State.RECORDING,
            State.TRANSCRIBING,
            State.CLEANING,
            State.INJECTING,
        ],
        State.ERROR: [State.ERROR],
    }

    legal_ok = 0
    illegal_ok = 0
    unexpected = 0
    total_legal = sum(len(targets) for targets in LEGAL_TRANSITIONS.values())
    total_pairs = len(State) * len(State)
    for source, targets in LEGAL_TRANSITIONS.items():
        for target in State:
            machine = StateMachine(EventBus())
            for step in paths[source]:
                machine.transition(step)
            try:
                machine.transition(target)
            except InvalidTransition:
                illegal_ok += 1
            else:
                if target in targets:
                    legal_ok += 1
                else:
                    unexpected += 1
    check(
        "AC1  every legal transition works, every illegal one raises",
        legal_ok == total_legal and illegal_ok == total_pairs - total_legal and unexpected == 0,
        f"{legal_ok}/{total_legal} legal accepted, "
        f"{illegal_ok}/{total_pairs - total_legal} illegal rejected",
    )

    # ------------------------------------------------------------------
    # AC2 — a full run with fakes produces INJECTED and the exact string.
    # ------------------------------------------------------------------
    from freewisper.core.pipeline import Pipeline
    from freewisper.core.session import RecordingResult
    from freewisper.core.tasks import TaskRunner

    class Recorder:
        def start_recording(self) -> None:
            self.started = True

        def stop_recording(self) -> RecordingResult:
            return RecordingResult(audio=b"fake", duration_s=2.0)

    class Transcriber:
        def transcribe(self, audio: object) -> str:
            return "hello world"

    class Cleaner:
        def clean(self, text: str) -> str:
            return text.upper()

    class Injector:
        def __init__(self) -> None:
            self.injected: list[str] = []

        def inject(self, text: str) -> bool:
            self.injected.append(text)
            return True

    bus = EventBus()
    machine = StateMachine(bus)
    injector = Injector()
    seen: list[tuple[Event, dict]] = []

    def record(event: Event, payload: dict) -> None:
        seen.append((event, dict(payload)))

    for event in Event:
        bus.subscribe(event, record)

    pipeline = Pipeline(
        bus,
        machine,
        Recorder(),
        Transcriber(),
        Cleaner(),
        injector,
        tasks=TaskRunner(),
        min_utterance_ms=300,
    )
    pipeline.on_hotkey_down()
    pipeline.on_hotkey_up()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not any(e is Event.INJECTED for e, _ in seen):
        time.sleep(0.01)

    injected = [p for e, p in seen if e is Event.INJECTED]
    check(
        "AC2  a full run injects the exact cleaned string",
        bool(injected) and injected[0]["text"] == "HELLO WORLD",
        f"injected={injector.injected}",
    )

    # ------------------------------------------------------------------
    # AC3 — the run performed no network I/O at all.
    # ------------------------------------------------------------------
    probe = f"""
import socket, sys, time
sys.path.insert(0, {str(SRC)!r})

def forbidden(*args, **kwargs):
    raise AssertionError("the core pipeline opened a socket")

socket.socket = forbidden
socket.create_connection = forbidden

from freewisper.core.events import Event, EventBus
from freewisper.core.pipeline import Pipeline
from freewisper.core.session import RecordingResult
from freewisper.core.states import StateMachine
from freewisper.core.tasks import TaskRunner

class R:
    def start_recording(self): pass
    def stop_recording(self): return RecordingResult(audio=b"x", duration_s=2.0)
class T:
    def transcribe(self, a): return "raw"
class C:
    def clean(self, t): return t.upper()
class I:
    def inject(self, t): return True

bus = EventBus()
done = []
bus.subscribe(Event.INJECTED, lambda ev, p: done.append(p))
p = Pipeline(bus, StateMachine(bus), R(), T(), C(), I(), tasks=TaskRunner())
p.on_hotkey_down()
p.on_hotkey_up()
for _ in range(500):
    if done:
        break
    time.sleep(0.01)
print("OK" if done else "TIMEOUT")
"""
    r = subprocess.run([tool("python"), "-c", probe], capture_output=True, text=True, timeout=30)
    check(
        "AC3  the pipeline opens no socket (zero network I/O)",
        r.stdout.strip().endswith("OK"),
        (r.stdout.strip() or r.stderr.strip())[-120:],
    )

    # ------------------------------------------------------------------
    # AC4 — the core package imports nothing platform-specific.
    # ------------------------------------------------------------------
    forbidden_roots = {
        "tkinter",
        "AppKit",
        "objc",
        "Quartz",
        "pynput",
        "pystray",
        "PIL",
        "sounddevice",
        "scipy",
        "vosk",
        "faster_whisper",
        "httpx",
        "requests",
        "urllib",
        "socket",
        "aiohttp",
        "os",
        "sys",
        "platform",
        "subprocess",
        "shutil",
        "pathlib",
        "tempfile",
        "glob",
        "freewisper.config",
        "freewisper.ui",
        "freewisper.platform",
    }
    offenders: list[str] = []
    modules = sorted(CORE_DIR.rglob("*.py"))
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root in forbidden_roots:
                    offenders.append(f"{path.name}:{root}")
    check(
        "AC4  core imports nothing platform-specific",
        not offenders,
        f"{len(modules)} modules audited, offenders={offenders}",
    )

    # ------------------------------------------------------------------
    # AC5 — a raising subscriber does not stop the others.
    # ------------------------------------------------------------------
    bus2 = EventBus()
    delivered: list[str] = []

    def boom(_ev: Event, _payload: dict) -> None:
        raise RuntimeError("subscriber exploded")

    bus2.subscribe(Event.INJECTED, boom)
    bus2.subscribe(Event.INJECTED, lambda ev, _p: delivered.append("second"))
    count = bus2.publish(Event.INJECTED)
    check(
        "AC5  a raising subscriber does not block the others",
        count == 1 and delivered == ["second"],
        f"delivered={delivered}, count={count}",
    )

    # ------------------------------------------------------------------
    # AC6 — cancelling publishes CANCELLED and never INJECTED.
    # ------------------------------------------------------------------
    cancel_probe = f"""
import sys, threading, time
sys.path.insert(0, {str(SRC)!r})
from freewisper.core.events import Event, EventBus
from freewisper.core.pipeline import Pipeline
from freewisper.core.session import RecordingResult
from freewisper.core.states import StateMachine
from freewisper.core.tasks import TaskRunner

release = threading.Event()

class R:
    def start_recording(self): pass
    def stop_recording(self): return RecordingResult(audio=b"x", duration_s=2.0)
class T:
    def transcribe(self, a):
        release.wait(10.0)
        return "raw"
class C:
    def clean(self, t): return t
class I:
    def __init__(self): self.injected = []
    def inject(self, t):
        self.injected.append(t)
        return True

bus = EventBus()
events = []
for e in Event:
    bus.subscribe(e, lambda ev, p: events.append(ev))
inj = I()
p = Pipeline(bus, StateMachine(bus), R(), T(), C(), inj, tasks=TaskRunner())
p.on_hotkey_down()
p.on_hotkey_up()
time.sleep(0.1)
p.cancel()
time.sleep(0.2)
release.set()
time.sleep(0.4)
print("CANCELLED" if Event.CANCELLED in events else "NO_CANCELLED",
      "INJECTED" if Event.INJECTED in events else "NO_INJECTED",
      len(inj.injected))
"""
    r6 = subprocess.run(
        [tool("python"), "-c", cancel_probe], capture_output=True, text=True, timeout=30
    )
    out6 = r6.stdout.strip().splitlines()[-1] if r6.stdout.strip() else ""
    check(
        "AC6  cancelling publishes CANCELLED and never INJECTED",
        out6.startswith("CANCELLED") and "NO_INJECTED" in out6 and out6.endswith("0"),
        out6 or r6.stderr.strip()[-120:],
    )

    # ------------------------------------------------------------------
    # AC7 — the quality gates.
    # ------------------------------------------------------------------
    r7 = subprocess.run(
        [tool("python"), "-m", "pytest", "-q"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    r8 = subprocess.run(
        [tool("mypy")], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300
    )
    r9 = subprocess.run(
        [tool("ruff"), "check", "."],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    check(
        "AC7  pytest green",
        r7.returncode == 0,
        r7.stdout.strip().splitlines()[-1] if r7.stdout.strip() else "no output",
    )
    check(
        "AC8  mypy --strict clean",
        r8.returncode == 0,
        r8.stdout.strip().splitlines()[-1] if r8.stdout.strip() else "no output",
    )
    check(
        "AC9  ruff clean",
        r9.returncode == 0,
        r9.stdout.strip().splitlines()[-1] if r9.stdout.strip() else "no output",
    )

    print("=" * 78)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"RESULT: {passed}/{len(RESULTS)} acceptance criteria verified")
    print(json.dumps({"passed": passed, "total": len(RESULTS)}))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
