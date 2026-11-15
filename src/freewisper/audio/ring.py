"""Bounded ring buffer holding the always-on microphone pre-roll.

The whole point of the ring buffer is that memory usage is decided once, at
construction, and never grows. Pushing a thousand times more audio than the
buffer can hold overwrites the oldest samples instead of allocating more.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]


def as_mono(chunk: Any) -> FloatArray:
    """Coerce an audio chunk into a contiguous 1-D float32 mono array.

    Accepts what PortAudio actually hands us — ``(frames, channels)`` blocks —
    as well as flat arrays and Python sequences of numbers.

    The result is always a fresh array, never a view of ``chunk``. PortAudio
    reuses its buffer between callbacks, so a view would change underneath
    the caller.
    """
    arr = np.asarray(chunk, dtype=np.float32)
    if arr.ndim == 0:
        return np.zeros(0, dtype=np.float32)
    if arr.ndim == 1:
        return np.array(arr, dtype=np.float32, copy=True)
    # (frames, channels) -> average the channels
    arr = arr.mean(axis=1) if arr.ndim == 2 else arr.reshape(arr.shape[0], -1).mean(axis=1)
    return np.array(arr, dtype=np.float32, copy=True)


class RingAudioBuffer:
    """A fixed-capacity, thread-safe ring buffer of mono float32 samples.

    The buffer is filled by the always-on audio callback and read when the
    user presses the push-to-talk key, to recover the audio that was
    captured just *before* the press.
    """

    def __init__(self, sample_rate: int, seconds: float = 1.5) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")
        if seconds <= 0:
            raise ValueError(f"seconds must be positive, got {seconds}")
        self._sample_rate = int(sample_rate)
        self._capacity = max(1, round(sample_rate * seconds))
        self._buffer = np.zeros(self._capacity, dtype=np.float32)
        self._write = 0
        self._filled = 0
        self._lock = threading.Lock()

    @property
    def sample_rate(self) -> int:
        """Samples per second of the buffered audio."""
        return self._sample_rate

    @property
    def capacity(self) -> int:
        """Maximum number of samples the buffer can hold."""
        return self._capacity

    @property
    def seconds(self) -> float:
        """Duration of the audio the buffer can hold."""
        return self._capacity / self._sample_rate

    @property
    def filled(self) -> int:
        """How many samples are currently held (never more than capacity)."""
        with self._lock:
            return self._filled

    @property
    def nbytes(self) -> int:
        """Bytes of memory held by the sample buffer — constant for the lifetime."""
        return int(self._buffer.nbytes)

    def push(self, chunk: Any) -> None:
        """Append samples, overwriting the oldest ones when full."""
        data = as_mono(chunk)
        if data.size == 0:
            return
        with self._lock:
            n = data.size
            if n >= self._capacity:
                # The chunk alone is longer than the buffer: keep only its tail.
                self._buffer[:] = data[-self._capacity :]
                self._write = 0
                self._filled = self._capacity
                return

            end = self._write + n
            if end <= self._capacity:
                self._buffer[self._write : end] = data
            else:
                head = self._capacity - self._write
                self._buffer[self._write :] = data[:head]
                self._buffer[: n - head] = data[head:]
            self._write = end % self._capacity
            self._filled = min(self._filled + n, self._capacity)

    def snapshot(self, seconds: float) -> FloatArray:
        """Return the most recent ``seconds`` of audio, oldest sample first.

        Returns fewer samples than requested when the buffer does not hold
        enough history yet, and an empty array when it holds nothing.
        """
        if seconds <= 0:
            return np.zeros(0, dtype=np.float32)
        with self._lock:
            count = min(round(self._sample_rate * seconds), self._filled)
            if count <= 0:
                return np.zeros(0, dtype=np.float32)
            start = (self._write - count) % self._capacity
            out: FloatArray
            if start + count <= self._capacity:
                out = self._buffer[start : start + count].copy()
            else:
                head = self._capacity - start
                out = np.concatenate((self._buffer[start:], self._buffer[: count - head])).astype(
                    np.float32, copy=False
                )
        return out

    def clear(self) -> None:
        """Drop all buffered audio."""
        with self._lock:
            self._buffer[:] = 0.0
            self._write = 0
            self._filled = 0

    def __len__(self) -> int:
        return self.filled

    def __repr__(self) -> str:
        return (
            f"RingAudioBuffer(sample_rate={self._sample_rate}, "
            f"seconds={self.seconds:.2f}, filled={self.filled}/{self._capacity})"
        )
