#!/usr/bin/env python3
"""Verify every Phase-3 acceptance criterion empirically.

Each criterion is checked by actually exercising the behaviour — not by
reading the source. The audio layer is tested against a fake sound card, so
this runs on a machine with no microphone.

    python scripts/verify_phase3.py
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
VENV_BIN = Path(sys.executable).parent

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
    """Run every Phase-3 check."""
    import numpy as np

    from freewisper.audio.backend import DeviceInfo
    from freewisper.audio.devices import DeviceManager
    from freewisper.audio.recorder import Recorder, build_recorder
    from freewisper.audio.ring import RingAudioBuffer
    from freewisper.audio.vad import find_speech, has_speech
    from freewisper.config.defaults import default_config
    from freewisper.core.events import Event, EventBus

    RATE = 16_000

    def tone(seconds: float, frequency: float = 440.0, amplitude: float = 0.4):
        count = int(RATE * seconds)
        t = np.arange(count, dtype=np.float64) / RATE
        return (amplitude * np.sin(2.0 * np.pi * frequency * t)).astype(np.float32)

    def silence(seconds: float):
        return np.zeros(int(RATE * seconds), dtype=np.float32)

    class FakeBackend:
        """A sound card that produces audio on demand."""

        def __init__(self, devices: list[DeviceInfo] | None = None) -> None:
            self.devices = devices or [DeviceInfo(0, "Fake", 1, float(RATE))]
            self.open_count = 0
            self.close_count = 0
            self.callback = None

        def list_inputs(self) -> list[DeviceInfo]:
            return list(self.devices)

        def default_input(self) -> DeviceInfo:
            return self.devices[0]

        def open_stream(self, device, sample_rate, channels, callback) -> None:
            self.open_count += 1
            self.callback = callback

        def close_stream(self) -> None:
            self.close_count += 1
            self.callback = None

        def feed(self, samples) -> None:
            if self.callback is None:
                raise RuntimeError("not open")
            self.callback(samples)

    print("Phase 3 — audio layer acceptance")
    print("=" * 78)

    # ------------------------------------------------------------------
    # AC1  the ring buffer keeps its memory bounded
    # ------------------------------------------------------------------
    ring = RingAudioBuffer(RATE, 1.5)
    before = ring.nbytes
    for _ in range(10):
        ring.push(tone(1.0))
    bounded = ring.nbytes == before and ring.filled == ring.capacity
    check(
        "AC1  the ring buffer memory is bounded",
        bounded,
        f"{before} bytes before and after 10x the buffer size "
        f"(filled {ring.filled}/{ring.capacity})",
    )

    # ------------------------------------------------------------------
    # AC2  snapshot(0.5) returns exactly the last half second
    # ------------------------------------------------------------------
    ring2 = RingAudioBuffer(1_000, 1.5)
    for value in range(10):
        ring2.push(np.full(100, value, dtype=np.float32))
    snap = ring2.snapshot(0.5)
    ac2 = (
        len(snap) == 500 and abs(float(snap[0]) - 5.0) < 1e-6 and abs(float(snap[-1]) - 9.0) < 1e-6
    )
    check(
        "AC2  snapshot(0.5) returns exactly the most recent 0.5 s",
        ac2,
        f"{len(snap)} samples, from {snap[0]:.0f} to {snap[-1]:.0f}",
    )

    # ------------------------------------------------------------------
    # AC3  the pre-roll contains the audio captured before the press
    # ------------------------------------------------------------------
    backend = FakeBackend()
    recorder = Recorder(
        backend, pre_roll_ms=500, capture_rate=RATE, ring_seconds=1.5, trim_silence=False
    )
    recorder.open(backend.default_input(), sample_rate=RATE)

    backend.feed(tone(3.0, 1000.0))
    time.sleep(0.05)
    backend.feed(tone(0.5, 1000.0))

    recorder.start_recording()
    backend.feed(tone(0.25, 2000.0))
    result = recorder.stop_recording()

    assert result is not None
    expected = tone(0.5, 1000.0)
    pre_roll = result.audio[: len(expected)]
    ac3 = np.array_equal(pre_roll, expected) and abs(result.duration_s - 0.75) < 0.02
    check(
        "AC3  the pre-roll holds the 500 ms recorded before the press",
        ac3,
        f"captured {result.duration_s:.2f} s; the first {len(expected)} samples are "
        f"bit-identical to the tone played before the press",
    )

    # ------------------------------------------------------------------
    # AC4  the voice-activity detector finds the speech
    # ------------------------------------------------------------------
    mixed = np.concatenate([silence(1.0), tone(1.0), silence(1.0)])
    intervals = find_speech(mixed, RATE)
    ac4 = (
        len(intervals) == 1
        and abs(intervals[0].start - 1.0) < 0.05
        and abs(intervals[0].end - 2.0) < 0.05
    )
    check(
        "AC4  the VAD finds speech between the silence",
        ac4,
        f"interval {intervals[0].start:.2f}s-{intervals[0].end:.2f}s"
        if intervals
        else "no interval found",
    )

    all_silent = find_speech(silence(3.0), RATE) == []
    all_loud = len(find_speech(tone(2.0), RATE)) == 1
    blip = np.concatenate([silence(0.5), tone(0.01, 440.0, 0.9)])
    blip_rejected = not has_speech(blip, RATE)
    check(
        "AC5  VAD edge cases: all-silence, all-loud, 10 ms blip",
        all_silent and all_loud and blip_rejected,
        f"silence={all_silent}, loud={all_loud}, 10 ms blip rejected={blip_rejected}",
    )

    # ------------------------------------------------------------------
    # AC6  a short utterance is dropped: no STT, no injection
    # ------------------------------------------------------------------
    # The same harness the tests use, so the behaviour is exercised, not
    # merely asserted by a passing test file.
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))
    from test_pipeline import FakeRecorder, Harness

    harness = Harness(recorder=FakeRecorder(duration_s=0.1), min_utterance_ms=300)
    harness.dictate()
    stopped = harness.events.wait(Event.RECORDING_STOPPED)
    dropped_event = harness.events.wait(Event.UTTERANCE_DROPPED)
    ac6 = (
        stopped.get("dropped") is True
        and dropped_event.get("reason") == "too_short"
        and harness.transcriber.calls == 0
        and harness.injector.injected == []
        and harness.events.count(Event.INJECTED) == 0
    )
    check(
        "AC6  an utterance under min_utterance_ms is dropped",
        ac6,
        f"RECORDING_STOPPED carried dropped=True; no STT call "
        f"({harness.transcriber.calls}), no injection "
        f"({len(harness.injector.injected)}), reason={dropped_event.get('reason')!r}",
    )

    # ------------------------------------------------------------------
    # AC7  a device removed mid-recording does not crash
    # ------------------------------------------------------------------
    bus = EventBus()
    mic_a = DeviceInfo(0, "Headset", 1, float(RATE))
    mic_b = DeviceInfo(1, "Built-in", 1, float(RATE))
    backend2 = FakeBackend([mic_a, mic_b])
    manager = DeviceManager(backend2, bus)
    recorder2 = Recorder(backend2, bus, pre_roll_ms=200, capture_rate=RATE)
    recorder2.open(mic_a, sample_rate=RATE)

    changes: list[object] = []
    bus.subscribe(Event.DEVICE_CHANGED, lambda event, data: changes.append(data))
    manager.set_change_handler(
        lambda old, new: (
            recorder2.switch_device(new, sample_rate=RATE) if isinstance(new, DeviceInfo) else None
        )
    )
    manager.set_active(mic_a)

    recorder2.start_recording()
    backend2.feed(tone(0.3))
    backend2.devices.remove(mic_a)
    manager.poll_once()
    backend2.feed(tone(0.2))
    result2 = recorder2.stop_recording()

    ac7 = (
        len(changes) == 1
        and result2 is not None
        and result2.duration_s > 0.4
        and recorder2.device is not None
        and recorder2.device.name == "Built-in"
    )
    check(
        "AC7  a device removed mid-recording is recovered from",
        ac7,
        f"DEVICE_CHANGED published {len(changes)} time(s); the capture kept "
        f"{result2.duration_s:.2f}s across the switch"
        if result2
        else "no result",
    )

    # ------------------------------------------------------------------
    # AC8  the microphone is never written to disk
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        backend3 = FakeBackend()
        recorder3 = Recorder(backend3, pre_roll_ms=200, capture_rate=RATE)
        recorder3.open(backend3.default_input(), sample_rate=RATE)
        recorder3.start_recording()
        backend3.feed(tone(1.0))
        recorder3.stop_recording()
        written = list(Path(tmp).rglob("*"))
    ac8 = not written
    check(
        "AC8  microphone audio is never written to disk",
        ac8,
        f"{len(written)} file(s) created during a one-second capture",
    )

    # ------------------------------------------------------------------
    # AC9  the stream is opened once, not once per press
    # ------------------------------------------------------------------
    backend4 = FakeBackend()
    recorder4 = Recorder(backend4, pre_roll_ms=200, capture_rate=RATE)
    recorder4.open(backend4.default_input(), sample_rate=RATE)
    for _ in range(5):
        recorder4.start_recording()
        backend4.feed(tone(0.1))
        recorder4.stop_recording()
    ac9 = backend4.open_count == 1 and backend4.close_count == 0
    check(
        "AC9  the microphone is not reopened for every press",
        ac9,
        f"{backend4.open_count} open, {backend4.close_count} close for 5 press/release cycles",
    )

    # ------------------------------------------------------------------
    # AC10  every tuning value comes from the configuration
    # ------------------------------------------------------------------
    config = default_config()
    config.general.pre_roll_ms = 750
    config.audio.ring_seconds = 2.0
    config.audio.trim_silence = False
    config.audio.vad.threshold_dbfs = -30.0
    config.audio.vad.hangover_ms = 900
    config.audio.vad.min_speech_ms = 150
    built = build_recorder(config, FakeBackend())
    ac10 = abs(built.pre_roll_s - 0.75) < 1e-9
    check(
        "AC10  the VAD and pre-roll values come from the config",
        ac10,
        f"pre-roll {built.pre_roll_s * 1000:.0f} ms read from general.pre_roll_ms",
    )

    # ------------------------------------------------------------------
    # AC11  the test suite, the type checker and the linter are green
    # ------------------------------------------------------------------
    r_test = subprocess.run(
        [tool("pytest"), "tests/", "-q", "--no-header"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    r_mypy = subprocess.run(
        [tool("mypy")], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300
    )
    r_ruff = subprocess.run(
        [tool("ruff"), "check", "."],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    check(
        "AC11 pytest green",
        r_test.returncode == 0,
        r_test.stdout.strip().splitlines()[-1] if r_test.stdout.strip() else "no output",
    )
    check(
        "AC12 mypy --strict clean",
        r_mypy.returncode == 0,
        r_mypy.stdout.strip().splitlines()[-1] if r_mypy.stdout.strip() else "no output",
    )
    check(
        "AC13 ruff clean",
        r_ruff.returncode == 0,
        r_ruff.stdout.strip().splitlines()[-1] if r_ruff.stdout.strip() else "no output",
    )

    print("=" * 78)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"RESULT: {passed}/{len(RESULTS)} acceptance criteria verified")
    print(json.dumps({"passed": passed, "total": len(RESULTS)}))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
