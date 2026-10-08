"""
Pluggable Query Caching Engine.
===============================
Provides high-performance in-memory LRU caching with TTL, thread safety,
hit/miss telemetry, deterministic canonical hashing, and optional Redis backend.
Zero required external dependencies.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import asdict
from typing import Any

from query_builder.models import QuerySpec


def compute_cache_key(
    spec: dict[str, Any] | QuerySpec,
    dialect: str = "postgres",
    tenant_id: Any = None,
) -> str:
    """Computes a deterministic SHA256 cache key from a QuerySpec or dict."""
    if isinstance(spec, QuerySpec) or hasattr(spec, "__dataclass_fields__"):
        spec_dict: dict[str, Any] = asdict(spec)  # type: ignore
    elif isinstance(spec, dict):
        spec_dict = dict(spec)
    else:
        spec_dict = {"raw": str(spec)}

    normalized_payload = {
        "spec": spec_dict,
        "dialect": dialect.lower().strip(),
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
    }

    canonical_json = json.dumps(
        normalized_payload,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class BaseQueryCache(ABC):
    """Abstract base class for query result cache implementations."""

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Retrieves a cached item by key or returns None if missing/expired."""

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Stores an item in the cache with an optional TTL in seconds."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Deletes an item from the cache. Returns True if existed."""

    @abstractmethod
    def clear(self) -> None:
        """Clears all entries from the cache."""

    @abstractmethod
    def stats(self) -> dict[str, Any]:
        """Returns cache telemetry statistics (hits, misses, size)."""


class InMemoryLRUCache(BaseQueryCache):
    """Thread-safe in-memory LRU cache with TTL support and eviction telemetry."""

    def __init__(
        self,
        max_entries: int = 1000,
        default_ttl: int | None = 300,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, tuple[Any, float | None]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            value, expire_at = self._cache[key]
            if expire_at is not None and time.time() > expire_at:
                del self._cache[key]
                self._misses += 1
                self._expirations += 1
                return None

            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        effective_ttl = ttl if ttl is not None else self.default_ttl
        expire_at = (
            (time.time() + effective_ttl)
            if effective_ttl and effective_ttl > 0
            else None
        )

        with self._lock:
            if key in self._cache:
                self._cache[key] = (value, expire_at)
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self.max_entries:
                    self._cache.popitem(last=False)
                    self._evictions += 1
                self._cache[key] = (value, expire_at)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._expirations = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_requests = self._hits + self._misses
            hit_ratio = (
                round(self._hits / total_requests, 4) if total_requests > 0 else 0.0
            )
            return {
                "type": "in_memory_lru",
                "size": len(self._cache),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "expirations": self._expirations,
                "hit_ratio": hit_ratio,
            }


# Names of redis-py exceptions that mean "the server is unreachable / unhealthy right now".
_OUTAGE_ERROR_NAMES = frozenset(
    {
        "ConnectionError",
        "TimeoutError",
        "BusyLoadingError",
        "AuthenticationError",
        "MaxConnectionsError",
    }
)

# Redis glob metacharacters that must be escaped when a literal prefix is used in SCAN MATCH.
_GLOB_META = re.compile(r"([\\*?\[\]])")


def _escape_glob(text: str) -> str:
    return _GLOB_META.sub(lambda m: "\\" + m.group(1), text)


# Keys deleted per round trip by ``RedisQueryCache.clear``.
_CLEAR_BATCH_SIZE = 500


def _is_outage_error(exc: BaseException) -> bool:
    """True for failures that indicate Redis is down/unreachable (not payload bugs)."""
    if isinstance(exc, (OSError, TimeoutError)):
        return True
    try:
        from redis import exceptions as redis_exceptions
    except ImportError:
        pass
    else:
        for name in _OUTAGE_ERROR_NAMES:
            cls = getattr(redis_exceptions, name, None)
            if isinstance(cls, type) and isinstance(exc, cls):
                return True
    # Duck-typed fallback for clients/stubs that raise look-alike classes (or subclasses of them).
    return any(cls.__name__ in _OUTAGE_ERROR_NAMES for cls in type(exc).__mro__)


class RedisQueryCache(BaseQueryCache):
    """Redis-backed query cache adapter with TTL support.

    Requires optional 'redis' dependency.
    """

    def __init__(
        self,
        client: Any | None = None,
        redis_client: Any | None = None,
        redis_url: str = "redis://localhost:6379/0",
        prefix: str = "qb:cache:",
        default_ttl: int | None = 300,
        connect_timeout: float = 2.0,
        command_timeout: float | None = 30.0,
    ) -> None:
        self.prefix = prefix
        self.default_ttl = default_ttl
        self._hits = 0
        self._misses = 0
        self._down_until = 0.0
        self._health: tuple[float, bool] | None = None  # (checked_at, reachable)
        if client is not None or redis_client is not None:
            self.client = client if client is not None else redis_client
        else:
            try:
                import redis

                # A short *connect* timeout makes an unreachable server degrade quickly; commands
                # get a larger budget so slow-but-healthy ones are not mistaken for an outage.
                self.client = redis.from_url(
                    redis_url,
                    socket_connect_timeout=connect_timeout,
                    socket_timeout=command_timeout,
                )
            except ImportError:
                self.client = None

    def _format_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    # After a connection failure, skip Redis for this long instead of stalling every call.
    _RETRY_AFTER_SECONDS = 30.0
    # How long a `stats()` connectivity probe result is reused.
    _HEALTH_TTL_SECONDS = 5.0

    def _usable(self) -> bool:
        return self.client is not None and time.monotonic() >= self._down_until

    def _note_failure(self, exc: Exception) -> None:
        if _is_outage_error(exc):
            self._down_until = time.monotonic() + self._RETRY_AFTER_SECONDS

    def get(self, key: str) -> Any | None:
        if not self._usable():
            self._misses += 1
            return None
        try:
            val = self.client.get(self._format_key(key))
            if val is not None:
                self._hits += 1
                return json.loads(
                    val.decode("utf-8") if isinstance(val, bytes) else str(val)
                )
        except Exception as exc:  # noqa: BLE001
            self._note_failure(exc)
        self._misses += 1
        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if not self._usable():
            return
        effective_ttl = ttl if ttl is not None else self.default_ttl
        try:
            encoded = json.dumps(value, default=str)
            r_key = self._format_key(key)
            if effective_ttl and effective_ttl > 0:
                self.client.set(r_key, encoded, ex=int(effective_ttl))
            else:
                self.client.set(r_key, encoded)
        except Exception as exc:  # noqa: BLE001
            self._note_failure(exc)

    # delete()/clear() are invalidations: they are ALWAYS attempted, even during the read
    # back-off, because dropping one would let stale entries be served once Redis recovers.
    # A failure still extends the back-off for reads; a success proves Redis is reachable.

    def delete(self, key: str) -> bool:
        if self.client is None:
            return False
        try:
            removed = bool(self.client.delete(self._format_key(key)))
        except Exception as exc:  # noqa: BLE001
            self._note_failure(exc)
            return False
        self._down_until = 0.0
        return removed

    def _delete_batch(self, keys: list[Any]) -> None:
        # UNLINK frees memory asynchronously, keeping each call O(batch) for the server.
        remover = getattr(self.client, "unlink", None) or self.client.delete
        remover(*keys)

    def clear(self) -> None:
        if self.client is None:
            return
        pattern = f"{_escape_glob(self.prefix)}*"
        try:
            # SCAN iterates incrementally (KEYS would block a large keyspace) and keys are
            # removed in bounded batches, never one giant DEL.
            scan = getattr(self.client, "scan_iter", None)
            if scan:
                key_iter: Any = scan(match=pattern, count=_CLEAR_BATCH_SIZE)
            else:
                key_iter = self.client.keys(pattern)
            batch: list[Any] = []
            for key in key_iter:
                batch.append(key)
                if len(batch) >= _CLEAR_BATCH_SIZE:
                    self._delete_batch(batch)
                    batch = []
            if batch:
                self._delete_batch(batch)
        except Exception as exc:  # noqa: BLE001
            # Keep counters: the cache was not (fully) cleared.
            self._note_failure(exc)
            return
        self._down_until = 0.0
        self._hits = 0
        self._misses = 0

    def _is_connected(self) -> bool:
        """True only if a client exists and the server answers a PING."""
        # Read-only health probe: never starts the back-off itself, and clients without
        # `ping` (duck-typed/minimal clients) are assumed reachable.
        if not self._usable():
            return False
        ping = getattr(self.client, "ping", None)
        if ping is None:
            return True
        # Cache the result briefly so a polled health endpoint never pays a network round
        # trip (or a full socket timeout while Redis is down) on every call.
        now = time.monotonic()
        if (
            self._health is not None
            and now - self._health[0] < self._HEALTH_TTL_SECONDS
        ):
            return self._health[1]
        try:
            reachable = bool(ping())
        except Exception:  # noqa: BLE001
            reachable = False
        self._health = (time.monotonic(), reachable)
        return reachable

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        hit_ratio = round(self._hits / total, 4) if total > 0 else 0.0
        return {
            "type": "redis",
            "connected": self._is_connected(),
            "hits": self._hits,
            "misses": self._misses,
            "hit_ratio": hit_ratio,
        }


_global_cache_instance: BaseQueryCache | None = None
_global_cache_lock = threading.RLock()


def get_global_cache() -> BaseQueryCache:
    """Returns the global singleton query cache instance (defaults to InMemoryLRUCache)."""
    global _global_cache_instance
    with _global_cache_lock:
        if _global_cache_instance is None:
            _global_cache_instance = InMemoryLRUCache()
        return _global_cache_instance


def set_global_cache(cache: BaseQueryCache) -> None:
    """Sets a custom query cache implementation globally."""
    global _global_cache_instance
    with _global_cache_lock:
        _global_cache_instance = cache


def reset_global_cache() -> None:
    """Resets the global query cache instance to a fresh InMemoryLRUCache."""
    global _global_cache_instance
    with _global_cache_lock:
        _global_cache_instance = InMemoryLRUCache()
