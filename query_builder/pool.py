"""
Thread-Safe Database Connection Pool.
=====================================
Manages a pool of reusable DB-API connections with health checks (SELECT 1),
idle eviction, maximum capacity limits, and context manager support.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any


class PoolError(Exception):
    """Base exception for connection pool failures."""


class PoolTimeoutError(PoolError):
    """Raised when connection acquisition times out."""


class PoolClosedError(PoolError):
    """Raised when operation is attempted on closed pool."""


class ConnectionPool:
    """Thread-safe database connection pool."""

    def __init__(
        self,
        factory: Callable[[], Any],
        max_size: int = 10,
        timeout: float = 30.0,
        max_idle_seconds: float = 300.0,
        health_check_sql: str = "SELECT 1",
    ) -> None:
        self.factory = factory
        self.max_size = max(1, max_size)
        self.timeout = max(0.0, timeout)
        self.max_idle_seconds = max(0.0, max_idle_seconds)
        self.health_check_sql = health_check_sql

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._available: list[tuple[Any, float]] = []
        self._in_use: set[Any] = set()
        self._closed = False

    def acquire(self) -> Any:
        """Acquires a healthy connection from the pool or creates a new one."""
        with self._cond:
            if self._closed:
                raise PoolClosedError("Connection pool is closed.")

            start_time = time.time()

            while True:
                if self._closed:
                    raise PoolClosedError("Connection pool is closed.")

                # Option 1: Reuse existing available connection
                if self._available:
                    conn, last_time = self._available.pop()
                    is_idle = (time.time() - last_time) > self.max_idle_seconds
                    healthy = True

                    if not is_idle and self.health_check_sql:
                        try:
                            cursor = conn.cursor()
                            cursor.execute(self.health_check_sql)
                            cursor.close()
                        except Exception:  # noqa: BLE001
                            healthy = False

                    if is_idle or not healthy:
                        with contextlib.suppress(Exception):
                            conn.close()
                        conn = self.factory()

                    self._in_use.add(conn)
                    return conn

                # Option 2: Pool has capacity to create a new connection
                if len(self._in_use) < self.max_size:
                    conn = self.factory()
                    self._in_use.add(conn)
                    return conn

                # Option 3: Wait for a connection to be released
                remaining = self.timeout - (time.time() - start_time)
                if remaining <= 0:
                    raise PoolTimeoutError("Connection acquisition timed out.")

                self._cond.wait(timeout=remaining)

    def release(self, conn: Any) -> None:
        """Returns a connection back to the pool."""
        with self._cond:
            if conn in self._in_use:
                self._in_use.remove(conn)
                if self._closed:
                    with contextlib.suppress(Exception):
                        conn.close()
                else:
                    self._available.append((conn, time.time()))
                    self._cond.notify()

    @contextlib.contextmanager
    def connection(self) -> Iterator[Any]:
        """Context manager yielding an acquired connection and releasing upon exit."""
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    def close_all(self) -> None:
        """Closes all pooled and in-use connections and shuts down the pool."""
        with self._cond:
            self._closed = True
            for conn, _ in self._available:
                with contextlib.suppress(Exception):
                    conn.close()
            for conn in self._in_use:
                with contextlib.suppress(Exception):
                    conn.close()
            self._available.clear()
            self._in_use.clear()
            self._cond.notify_all()

    @property
    def size(self) -> int:
        """Total number of tracked connections (available + in use)."""
        with self._lock:
            return len(self._available) + len(self._in_use)

    @property
    def available_count(self) -> int:
        """Number of idle connections available in pool."""
        with self._lock:
            return len(self._available)

    @property
    def in_use_count(self) -> int:
        """Number of connections currently checked out."""
        with self._lock:
            return len(self._in_use)
