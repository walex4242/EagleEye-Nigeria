"""
cache.py
─────────
In-memory cache with TTL + request deduplication for FIRMS data.
"""

from __future__ import annotations

import time
import threading
from typing import Any


class TTLCache:
    """Thread-safe in-memory cache with TTL and in-flight deduplication."""

    def __init__(self, default_ttl: int = 300):
        self._store: dict[str, dict[str, Any]] = {}
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        self._in_flight: dict[str, threading.Event] = {}

    def get(self, key: str) -> Any | None:
        """Get a cached value. Returns None if expired or missing."""
        with self._lock:
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
        with self._lock:
            self._store[key] = {
                "value": value,
                "expires_at": time.time() + ttl,
                "created_at": time.time(),
            }
            # Signal any threads waiting for this key
            event = self._in_flight.pop(key, None)
            if event:
                event.set()

    def wait_or_claim(self, key: str, timeout: float = 60.0) -> str:
        """
        Race-condition prevention for concurrent identical requests.
        
        Returns:
            "claimed"  — you should fetch the data and call .set()
            "waited"   — another thread fetched it; call .get() now
            "timeout"  — timed out waiting; fetch it yourself
        """
        with self._lock:
            # Already cached?
            entry = self._store.get(key)
            if entry and time.time() <= entry["expires_at"]:
                return "waited"

            # Another thread already fetching?
            if key in self._in_flight:
                event = self._in_flight[key]
            else:
                # We claim it
                self._in_flight[key] = threading.Event()
                return "claimed"

        # Wait for the other thread to finish
        completed = event.wait(timeout=timeout)
        return "waited" if completed else "timeout"

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._in_flight.clear()

    def stats(self) -> dict:
        now = time.time()
        with self._lock:
            active = {
                k: v for k, v in self._store.items()
                if now <= v["expires_at"]
            }
            expired = {
                k: v for k, v in self._store.items()
                if now > v["expires_at"]
            }
            return {
                "active_entries": len(active),
                "expired_entries": len(expired),
                "in_flight": len(self._in_flight),
                "keys": list(active.keys()),
            }


# ── Global singleton ──
firms_cache = TTLCache(default_ttl=300)