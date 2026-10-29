"""Bounded, process-local request windows for the development API."""

from collections import deque
from math import ceil
from threading import Lock
from time import monotonic
from typing import Hashable

from fastapi import HTTPException


class WindowLimiter:
    def __init__(self, limit: int, seconds: int, *, max_keys: int = 10_000):
        self.limit = limit
        self.seconds = seconds
        self.max_keys = max_keys
        self._entries: dict[Hashable, deque[float]] = {}
        self._lock = Lock()
        self.clock = monotonic

    def hit(self, key: Hashable) -> int | None:
        """Return seconds until retry, or None when the request is admitted."""
        now = self.clock()
        with self._lock:
            # Remove inactive keys before admitting new identities; never grow
            # unbounded state from attacker-controlled login names or IPs.
            if len(self._entries) >= self.max_keys and key not in self._entries:
                self._prune(now)
                if len(self._entries) >= self.max_keys:
                    return self.seconds
            visits = self._entries.setdefault(key, deque())
            while visits and now - visits[0] >= self.seconds:
                visits.popleft()
            if len(visits) >= self.limit:
                return max(1, ceil(self.seconds - (now - visits[0])))
            visits.append(now)
            return None

    def _prune(self, now: float) -> None:
        for key, visits in list(self._entries.items()):
            while visits and now - visits[0] >= self.seconds:
                visits.popleft()
            if not visits:
                del self._entries[key]

    def forget(self, key: Hashable) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


QUESTION_LIMITER = WindowLimiter(20, 60)
TOOL_LIMITER = WindowLimiter(60, 60)
HISTORY_LIMITER = WindowLimiter(60, 60)
SITEMAP_LIMITER = WindowLimiter(3, 60)
LOGIN_IP_LIMITER = WindowLimiter(60, 60)
LOGIN_ACCOUNT_LIMITER = WindowLimiter(6, 60)


def enforce_limit(limiter: WindowLimiter, key: Hashable) -> None:
    retry_after = limiter.hit(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=429, detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )
