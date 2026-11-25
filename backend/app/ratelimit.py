"""A small in-memory sliding-window rate limiter, so one client can't burn through the AI quota."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_calls: int, window_seconds: float = 60.0, clock=time.monotonic):
        self.max_calls = max_calls
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_calls > 0

    def check(self, key: str) -> float:
        """Record a call. Returns 0 if allowed, otherwise the seconds to wait before trying again."""
        if not self.enabled:
            return 0.0
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.max_calls:
                return max(self.window - (now - hits[0]), 0.1)
            hits.append(now)
            if len(self._hits) > 1000:  # forget clients that have gone quiet
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
                    self._hits.pop(k, None)
            return 0.0
