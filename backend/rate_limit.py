"""In-memory sliding-window rate limiter, keyed per session.

Applied as a guard on expensive endpoints (chat = LLM tokens, rag indexing =
embedding tokens). Production path: swap the bucket store for Redis and key
on user identity rather than session — abstraction here stays the same.

Today's limits are single-tier. If user tiers existed (free vs enterprise),
this would become a lookup against a tier map; the limiter object is reusable.
"""
import time
from collections import deque
from threading import Lock
from typing import Dict, Tuple

from fastapi import HTTPException


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: Dict[str, deque] = {}
        self._lock = Lock()

    def check(self, key: str) -> Tuple[bool, int]:
        """Record one call against the key. Returns (allowed, retry_after_seconds).

        Not allowed = caller has exceeded the window's request budget.
        retry_after is seconds until the oldest in-window call expires.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                retry_after = max(1, int(bucket[0] + self.window_seconds - now) + 1)
                return False, retry_after
            bucket.append(now)
            return True, 0

    def reset(self, key: str = None) -> None:
        """Clear state for a key, or all keys. Used by tests."""
        with self._lock:
            if key is None:
                self._buckets.clear()
            elif key in self._buckets:
                del self._buckets[key]


# Module-level limiters used by the app.
# Limits chosen for single-user demo: a real human won't trip them, but a
# runaway client or accidental loop will. Tune up in config for prod.
chat_limiter = SlidingWindowLimiter(max_requests=30, window_seconds=60)
rag_limiter = SlidingWindowLimiter(max_requests=10, window_seconds=60)


def enforce(limiter: SlidingWindowLimiter, key: str, scope: str) -> None:
    """Raise 429 if the key has exceeded the limiter's budget.

    `scope` appears in the error detail to disambiguate which endpoint
    bucket the caller hit ("chat", "rag", etc.).
    """
    allowed, retry_after = limiter.check(key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {scope}. Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )
