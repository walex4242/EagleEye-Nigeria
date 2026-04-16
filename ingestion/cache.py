"""
cache.py
─────────
Simple in-memory cache with TTL for FIRMS data.
Prevents duplicate API calls when multiple endpoints
are hit simultaneously (e.g., dashboard loads hotspots + summary).
"""

from __future__ import annotations
import time
from typing import Any


class TTLCache:
    """Thread-safe in-memory cache with time-to-live expiration."""

    def __init__(self, default_ttl: int = 300):
        """
        Args:
            default_ttl: Default time-to-live in seconds (default 5 minutes).
        """
        self._store: dict[str, dict[str, Any]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        """Get a cached value. Returns None if expired or missing."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            del self._store[key]
            return None
        return entry["value"]

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value with TTL."""
        ttl = ttl if ttl is not None else self._default_ttl
        self._store[key] = {
            "value": value,
            "expires_at": time.time() + ttl,
            "created_at": time.time(),
        }

    def invalidate(self, key: str) -> None:
        """Remove a specific key."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._store.clear()

    def stats(self) -> dict:
        """Return cache statistics."""
        now = time.time()
        active = {k: v for k, v in self._store.items() if now <= v["expires_at"]}
        expired = {k: v for k, v in self._store.items() if now > v["expires_at"]}
        return {
            "active_entries": len(active),
            "expired_entries": len(expired),
            "keys": list(active.keys()),
        }


# ── Global cache instance ──
# 5-minute TTL: FIRMS data doesn't change more often than this
firms_cache = TTLCache(default_ttl=300)