"""Real-time level metering for the HUD.

The audio callback writes levels from the PortAudio thread; the HUD reads
them from the Tk thread. The meter is therefore bounded and thread-safe.
"""

from __future__ import annotations

import threading
from collections import deque


class LevelMeter:
    """A bounded, thread-safe history of RMS levels (oldest first)."""

    def __init__(self, size: int = 5) -> None:
        if size <= 0:
            raise ValueError(f"size must be positive, got {size}")
        self._size = int(size)
        self._levels: deque[float] = deque(maxlen=self._size)
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        """Maximum number of levels retained."""
        return self._size

    def push(self, level: float) -> None:
        """Record a new level, dropping the oldest once the history is full."""
        with self._lock:
            self._levels.append(float(level))

    def levels(self) -> list[float]:
        """The retained levels, oldest first."""
        with self._lock:
            return list(self._levels)

    def peak(self) -> float:
        """The loudest retained level, or 0.0 when nothing was recorded."""
        with self._lock:
            return max(self._levels) if self._levels else 0.0

    def latest(self) -> float:
        """The most recent level, or 0.0 when nothing was recorded."""
        with self._lock:
            return self._levels[-1] if self._levels else 0.0

    def clear(self) -> None:
        """Drop the recorded history."""
        with self._lock:
            self._levels.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._levels)
