"""Energy-based voice activity detection.

Every function here is a pure function over a numpy array: no hardware, no
I/O, no hidden state. The speech/silence decisions are therefore
reproducible and can be tested without a microphone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]

#: Analysis window for the energy detector. 10 ms is short enough to catch
#: plosives and long enough to keep the frame count manageable.
FRAME_MS = 10.0

#: Floor used for dBFS conversion so silence is finite rather than -inf.
MIN_DBFS = -120.0


@dataclass(frozen=True)
class SpeechInterval:
    """A half-open time range, in seconds, that contains speech."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        """Length of the interval in seconds."""
        return self.end - self.start

    def slice(self, audio: FloatArray, sample_rate: int) -> FloatArray:
        """Return the samples of ``audio`` that fall inside this interval."""
        start = max(0, int(self.start * sample_rate))
        end = min(len(audio), int(self.end * sample_rate))
        if end <= start:
            return np.zeros(0, dtype=np.float32)
        return audio[start:end]


def amplitude_to_dbfs(amplitude: float) -> float:
    """Convert a linear amplitude (0.0-1.0) to decibels full scale."""
    if amplitude <= 0.0:
        return MIN_DBFS
    return max(MIN_DBFS, 20.0 * math.log10(amplitude))


def frame_rms(audio: FloatArray, sample_rate: int, frame_ms: float = FRAME_MS) -> FloatArray:
    """RMS level of each analysis frame, one value per frame.

    A trailing partial frame is included so the very end of the recording is
    never silently dropped.
    """
    if len(audio) == 0:
        return np.zeros(0, dtype=np.float32)
    frame_len = max(1, round(sample_rate * frame_ms / 1000.0))
    usable = len(audio) - (len(audio) % frame_len)
    if usable == 0:
        # Shorter than a single frame: treat the whole thing as one frame.
        usable = len(audio)
        frame_len = len(audio)
    frames = audio[:usable].reshape(-1, frame_len)
    levels: FloatArray = np.sqrt(np.mean(np.square(frames), axis=1)).astype(np.float32)
    return levels


def find_speech(
    audio: FloatArray,
    sample_rate: int,
    *,
    threshold_dbfs: float = -42.0,
    hangover_ms: float = 600.0,
    min_speech_ms: float = 200.0,
    frame_ms: float = FRAME_MS,
) -> list[SpeechInterval]:
    """Locate the speech intervals inside ``audio``.

    ``threshold_dbfs``
        A frame counts as speech when its RMS is above this level.
    ``hangover_ms``
        A gap of silence shorter than this does not end a speech run — it is
        the pause between two words. The hangover bridges gaps; it never
        extends the outer edges of an interval.
    ``min_speech_ms``
        Runs shorter than this are discarded, which is what rejects key taps
        and other short non-speech sounds.

    Returns intervals sorted by start time.
    """
    if len(audio) == 0:
        return []

    rms = frame_rms(audio, sample_rate, frame_ms)
    if rms.size == 0:
        return []

    loud = np.flatnonzero(rms_dbfs(rms) > threshold_dbfs)
    if loud.size == 0:
        return []

    # Collect runs of consecutive loud frames.
    runs: list[tuple[int, int]] = []
    start = int(loud[0])
    prev = start
    for raw in loud[1:]:
        idx = int(raw)
        if idx - prev > 1:
            runs.append((start, prev))
            start = idx
        prev = idx
    runs.append((start, prev))

    # Bridge gaps that are shorter than the hangover.
    hangover_frames = max(0, round(hangover_ms / frame_ms))
    merged: list[tuple[int, int]] = [runs[0]]
    for run in runs[1:]:
        gap = run[0] - merged[-1][1] - 1
        if gap <= hangover_frames:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)

    frame_len = max(1, round(sample_rate * frame_ms / 1000.0))
    intervals: list[SpeechInterval] = []
    for first, last in merged:
        start_s = (first * frame_len) / sample_rate
        end_s = ((last + 1) * frame_len) / sample_rate
        if (end_s - start_s) * 1000.0 >= min_speech_ms:
            intervals.append(SpeechInterval(start=start_s, end=end_s))
    return intervals


def rms_dbfs(levels: FloatArray) -> FloatArray:
    """Vectorised :func:`amplitude_to_dbfs`."""
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(levels.astype(np.float64), 1e-12))
    return np.maximum(db, MIN_DBFS).astype(np.float32)


def has_speech(audio: FloatArray, sample_rate: int, **kwargs: float) -> bool:
    """True when the audio contains a speech run long enough to count."""
    return bool(find_speech(audio, sample_rate, **kwargs))


def speech_duration(audio: FloatArray, sample_rate: int, **kwargs: float) -> float:
    """Total duration of the speech intervals, in seconds."""
    return sum(interval.duration for interval in find_speech(audio, sample_rate, **kwargs))


def trim_silence(audio: FloatArray, sample_rate: int, **kwargs: float) -> FloatArray:
    """Strip leading and trailing silence, keeping everything in between.

    Returns an empty array when no speech was found, and the input unchanged
    when the speech already starts at the beginning.
    """
    intervals = find_speech(audio, sample_rate, **kwargs)
    if not intervals:
        return np.zeros(0, dtype=np.float32)
    start = max(0, int(intervals[0].start * sample_rate))
    end = min(len(audio), int(intervals[-1].end * sample_rate))
    if end <= start:
        return np.zeros(0, dtype=np.float32)
    return audio[start:end]
