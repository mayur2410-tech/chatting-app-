import math
import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """
    Sliding-window event counter per key (failed logins, sent messages), kept in process memory.

    This is sufficient for the single-process deployment this app targets. Running several
    workers would need a shared store (e.g. a Postgres table) instead.
    """

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, window: float, now: float) -> deque[float]:
        events = self._events[key]
        while events and events[0] <= now - window:
            events.popleft()
        if not events:
            self._events.pop(key, None)
        return events

    def retry_after(self, key: str, limit: int, window: float) -> int:
        """Seconds until another attempt is allowed, or 0 if the key is not blocked."""
        now = time.monotonic()
        with self._lock:
            events = self._prune(key, window, now)
            if len(events) < limit:
                return 0
            return max(1, math.ceil(events[0] + window - now))

    def record(self, key: str) -> None:
        with self._lock:
            self._events[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


login_limiter = SlidingWindowLimiter()
message_limiter = SlidingWindowLimiter()
