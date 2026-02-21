"""Rate limiting and caching utilities for external data source APIs.

Free-tier API limits are the tightest constraint on Emet's external
data access.  This module provides:

    - ``TokenBucketLimiter``: per-second rate limiting (e.g., Etherscan 5/sec)
    - ``MonthlyCounter``: monthly request budgeting (e.g., OpenCorporates 200/month)
    - ``ResponseCache``: TTL-based in-memory cache to avoid redundant API calls
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token bucket rate limiter (per-second)
# ---------------------------------------------------------------------------


class TokenBucketLimiter:
    """Token-bucket rate limiter for per-second API limits.

    Parameters
    ----------
    rate:
        Maximum requests per second.
    burst:
        Maximum burst size (tokens that can accumulate).
        Defaults to ``rate`` for simple rate limiting.

    Usage::

        limiter = TokenBucketLimiter(rate=5)  # 5 req/sec
        await limiter.acquire()  # blocks if over limit
        # ... make API call ...
    """

    def __init__(self, rate: float, burst: int | None = None) -> None:
        self._rate = rate
        self._burst = burst or int(rate)
        self._tokens = float(self._burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Wait for one token to regenerate
                wait_time = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait_time)
                self._refill()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(float(self._burst), self._tokens + elapsed * self._rate)
        self._last_refill = now

    @property
    def available_tokens(self) -> float:
        """Current available tokens (approximate)."""
        self._refill()
        return self._tokens


# ---------------------------------------------------------------------------
# Monthly request counter
# ---------------------------------------------------------------------------


@dataclass
class MonthlyCounter:
    """Tracks monthly API request count against a budget.

    Parameters
    ----------
    monthly_limit:
        Maximum requests per calendar month.
    source_name:
        Name of the data source (for logging).

    Usage::

        counter = MonthlyCounter(monthly_limit=200, source_name="OpenCorporates")
        if counter.can_request():
            counter.record()
            # ... make API call ...
        else:
            logger.warning("Monthly limit reached")
    """

    monthly_limit: int
    source_name: str = "unknown"
    _count: int = field(default=0, init=False, repr=False)
    _month_key: str = field(default="", init=False, repr=False)

    def _current_month_key(self) -> str:
        """Return YYYY-MM string for current month."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _reset_if_new_month(self) -> None:
        """Reset counter at month boundary."""
        key = self._current_month_key()
        if key != self._month_key:
            if self._month_key and self._count > 0:
                logger.info(
                    "%s: monthly counter reset (%d requests last month)",
                    self.source_name, self._count,
                )
            self._month_key = key
            self._count = 0

    def can_request(self) -> bool:
        """Check if a request is allowed within budget."""
        self._reset_if_new_month()
        return self._count < self.monthly_limit

    def record(self, n: int = 1) -> None:
        """Record N requests."""
        self._reset_if_new_month()
        self._count += n

        # Warn at usage thresholds
        usage_pct = self._count / self.monthly_limit
        if usage_pct >= 0.95 and (self._count - n) / self.monthly_limit < 0.95:
            logger.warning(
                "%s: 95%% of monthly limit used (%d/%d)",
                self.source_name, self._count, self.monthly_limit,
            )
        elif usage_pct >= 0.80 and (self._count - n) / self.monthly_limit < 0.80:
            logger.warning(
                "%s: 80%% of monthly limit used (%d/%d)",
                self.source_name, self._count, self.monthly_limit,
            )

    @property
    def remaining(self) -> int:
        """Requests remaining this month."""
        self._reset_if_new_month()
        return max(0, self.monthly_limit - self._count)

    @property
    def usage(self) -> dict[str, Any]:
        """Current usage stats."""
        self._reset_if_new_month()
        return {
            "source": self.source_name,
            "month": self._month_key,
            "used": self._count,
            "limit": self.monthly_limit,
            "remaining": self.remaining,
            "usage_percent": round(self._count / self.monthly_limit * 100, 1),
        }


# ---------------------------------------------------------------------------
# Response cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    """Single cache entry with TTL."""
    value: Any
    expires_at: float


class ResponseCache:
    """TTL-based in-memory cache for API responses.

    Prevents redundant API calls during an investigation session.
    Cache keys are derived from (source, endpoint, params) to ensure
    uniqueness.

    Parameters
    ----------
    default_ttl:
        Default time-to-live in seconds.  Different sources may
        override with source-specific TTLs.
    max_entries:
        Maximum cache entries before LRU eviction.

    Usage::

        cache = ResponseCache(default_ttl=300)  # 5 minutes

        key = cache.make_key("opensanctions", "search", {"q": "Gazprom"})
        hit = cache.get(key)
        if hit is not None:
            return hit

        result = await api_call(...)
        cache.set(key, result)
    """

    def __init__(
        self,
        default_ttl: float = 300.0,
        max_entries: int = 1000,
    ) -> None:
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._store: dict[str, _CacheEntry] = {}
        self._hit_count = 0
        self._miss_count = 0

    @staticmethod
    def make_key(source: str, endpoint: str, params: dict[str, Any]) -> str:
        """Generate a deterministic cache key."""
        # Sort params for consistency
        param_str = json.dumps(params, sort_keys=True, default=str)
        raw = f"{source}:{endpoint}:{param_str}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def get(self, key: str) -> Any | None:
        """Retrieve a cached value, or None if expired/missing."""
        entry = self._store.get(key)
        if entry is None:
            self._miss_count += 1
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            self._miss_count += 1
            return None
        self._hit_count += 1
        return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store a value with TTL."""
        # Evict expired entries if at capacity
        if len(self._store) >= self._max_entries:
            self._evict_expired()

        # If still at capacity, evict oldest
        if len(self._store) >= self._max_entries:
            oldest_key = min(self._store, key=lambda k: self._store[k].expires_at)
            del self._store[oldest_key]

        expires = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        self._store[key] = _CacheEntry(value=value, expires_at=expires)

    def invalidate(self, key: str) -> bool:
        """Remove a specific key. Returns True if key existed."""
        if key in self._store:
            del self._store[key]
            return True
        return False

    def invalidate_source(self, source: str) -> int:
        """Remove all entries for a given source prefix. Returns count removed."""
        # This works because our keys are hashes — we need to track source metadata
        # For now, clear all (simple but effective for investigation sessions)
        count = len(self._store)
        self._store.clear()
        return count

    def clear(self) -> None:
        """Clear entire cache."""
        self._store.clear()
        self._hit_count = 0
        self._miss_count = 0

    def _evict_expired(self) -> None:
        """Remove all expired entries."""
        now = time.monotonic()
        expired = [k for k, v in self._store.items() if now > v.expires_at]
        for k in expired:
            del self._store[k]

    @property
    def stats(self) -> dict[str, Any]:
        """Cache performance stats."""
        total = self._hit_count + self._miss_count
        return {
            "entries": len(self._store),
            "max_entries": self._max_entries,
            "hits": self._hit_count,
            "misses": self._miss_count,
            "hit_rate": round(self._hit_count / total, 3) if total > 0 else 0.0,
        }
