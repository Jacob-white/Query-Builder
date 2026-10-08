"""
Asynchronous Database Connection Pool & Multi-Pool Manager.
===========================================================
Provides high-concurrency, non-blocking connection pooling for asyncio, FastAPI,
and async database drivers (asyncpg, aiomysql, aiosqlite, async_base).
Includes non-blocking health checks, idle connection eviction, max-lifespan recycling,
cooperative async query cancellation tokens, and async context managers.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from query_builder.pool import (
    PoolClosedError,
    PoolTimeoutError,
    QueryCancelledError,
)


class AsyncCancellationToken:
    """
    Cooperative asynchronous cancellation token for in-flight database query execution.
    Allows registering synchronous or asynchronous callbacks to cancel database sockets.
    """

    def __init__(self) -> None:
        self._is_cancelled: bool = False
        self._lock = asyncio.Lock()
        self._callbacks: list[Callable[[], Any]] = []

    @property
    def is_cancelled(self) -> bool:
        """Returns True if cancellation has been requested."""
        return self._is_cancelled

    async def cancel(self) -> None:
        """Signals cancellation and invokes all registered callbacks."""
        async with self._lock:
            if self._is_cancelled:
                return
            self._is_cancelled = True
            callbacks = list(self._callbacks)
            self._callbacks.clear()

        for cb in callbacks:
            try:
                res = cb()
                if inspect.isawaitable(res):
                    await res
            except Exception:  # noqa: BLE001, S110
                pass

    def register_callback(self, callback: Callable[[], Any]) -> None:
        """Registers a callback to be invoked upon cancellation."""
        if self._is_cancelled:
            try:
                res = callback()
                if inspect.isawaitable(res):
                    asyncio.create_task(res)
            except Exception:  # noqa: BLE001, S110
                pass
        else:
            self._callbacks.append(callback)

    def throw_if_cancelled(self) -> None:
        """Raises QueryCancelledError if cancellation has been requested."""
        if self.is_cancelled:
            raise QueryCancelledError("Query execution was cancelled.")


class AsyncConnectionPool:
    """
    Asynchronous connection pool with non-blocking acquisition, health check pings,
    and automatic lifecycle recycling.
    """

    def __init__(
        self,
        factory: Callable[[], Awaitable[Any] | Any] | None = None,
        max_size: int = 10,
        min_size: int = 0,
        timeout: float = 30.0,
        max_idle_seconds: float = 300.0,
        max_lifespan_seconds: float = 3600.0,
        health_check_sql: str = "SELECT 1",
        connector_name: str | None = None,
        connector: Any = None,
        **connection_kwargs: Any,
    ) -> None:
        if factory is not None:
            self.factory = factory
        elif connector is not None:
            self.factory = lambda: (
                connector.connect() if hasattr(connector, "connect") else connector
            )
        elif connector_name is not None:
            clean_name = connector_name.lower().strip()
            if clean_name == "sqlite":
                db_name = connection_kwargs.get("database", ":memory:")
                clean_kw = {
                    k: v for k, v in connection_kwargs.items() if k != "database"
                }
                import sqlite3

                self.factory = lambda: sqlite3.connect(db_name, **clean_kw)
            else:
                from query_builder.connectors.registry import ConnectorRegistry

                inst = ConnectorRegistry.get(clean_name, **connection_kwargs)
                self.factory = lambda: (
                    inst.connect() if hasattr(inst, "connect") else inst
                )
        else:
            raise ValueError(
                "AsyncConnectionPool requires a 'factory' callable, 'connector' instance, or 'connector_name' string."
            )

        self.max_size = max(1, max_size)
        self.min_size = max(0, min(min_size, self.max_size))
        self.timeout = max(0.0, timeout)
        self.max_idle_seconds = max(0.0, max_idle_seconds)
        self.max_lifespan_seconds = max(0.0, max_lifespan_seconds)
        self.health_check_sql = health_check_sql

        self._lock = asyncio.Lock()
        # Entry format: (connection, last_used_timestamp, created_at_timestamp)
        self._available: list[tuple[Any, float, float]] = []
        self._in_use: set[Any] = set()
        self._closed: bool = False
        self._initialized: bool = False

    async def _create_connection(self) -> Any:
        res = self.factory()
        if inspect.isawaitable(res):
            return await res
        return res

    async def _close_connection(self, conn: Any) -> None:
        try:
            if hasattr(conn, "close"):
                res = conn.close()
                if inspect.isawaitable(res):
                    await res
        except Exception:  # noqa: BLE001, S110
            pass

    async def _check_health(self, conn: Any) -> bool:
        if not self.health_check_sql:
            return True
        try:
            if hasattr(conn, "execute"):
                res = conn.execute(self.health_check_sql)
                if inspect.isawaitable(res):
                    await res
                return True
            if hasattr(conn, "cursor"):
                cur = conn.cursor()
                if inspect.isawaitable(cur):
                    cur = await cur
                res = cur.execute(self.health_check_sql)
                if inspect.isawaitable(res):
                    await res
                if hasattr(cur, "close"):
                    c_res = cur.close()
                    if inspect.isawaitable(c_res):
                        await c_res
                return True
            return True
        except Exception:  # noqa: BLE001
            return False

    async def initialize(self) -> None:
        """Pre-warms minimum required connections."""
        async with self._lock:
            if self._initialized or self._closed:
                return
            now = time.time()
            for _ in range(self.min_size):
                conn = await self._create_connection()
                self._available.append((conn, now, now))
            self._initialized = True

    async def acquire(self, token: AsyncCancellationToken | None = None) -> Any:
        """Acquires a healthy connection from the pool, or creates a new one."""
        if token:
            token.throw_if_cancelled()

        start_time = time.time()

        while True:
            if token:
                token.throw_if_cancelled()

            async with self._lock:
                if self._closed:
                    raise PoolClosedError("Async connection pool is closed.")

                now = time.time()

                # 1. Reuse existing connection if available
                while self._available:
                    conn, last_time, created_time = self._available.pop()
                    is_idle = (now - last_time) > self.max_idle_seconds
                    is_expired = (now - created_time) > self.max_lifespan_seconds

                    if not is_idle and not is_expired:
                        # Test health outside lock
                        healthy = await self._check_health(conn)
                        if healthy:
                            self._in_use.add(conn)
                            return conn

                    # Stale or unhealthy connection
                    await self._close_connection(conn)

                # 2. Pool capacity available to create new connection
                if len(self._in_use) < self.max_size:
                    conn = await self._create_connection()
                    self._in_use.add(conn)
                    return conn

            # 3. Wait for connection release
            elapsed = time.time() - start_time
            if elapsed >= self.timeout:
                raise PoolTimeoutError(
                    f"Timeout waiting for connection after {elapsed:.2f}s (max_size={self.max_size})."
                )

            await asyncio.sleep(0.01)

    async def release(self, conn: Any) -> None:
        """Returns a connection to the pool or closes it if pool is closed."""
        async with self._lock:
            if conn in self._in_use:
                self._in_use.remove(conn)

            if self._closed:
                await self._close_connection(conn)
                return

            now = time.time()
            self._available.append((conn, now, now))

    @contextlib.asynccontextmanager
    async def connection(
        self, token: AsyncCancellationToken | None = None
    ) -> AsyncIterator[Any]:
        """Async context manager for acquiring and safely releasing a connection."""
        conn = await self.acquire(token=token)
        try:
            yield conn
        finally:
            await self.release(conn)

    async def close(self) -> None:
        """Closes all idle and active connections in the pool."""
        async with self._lock:
            self._closed = True
            to_close = [c for c, _, _ in self._available]
            to_close.extend(list(self._in_use))
            self._available.clear()
            self._in_use.clear()

        for conn in to_close:
            await self._close_connection(conn)

    @property
    def size(self) -> int:
        """Total current connection count (in-use + available)."""
        return len(self._available) + len(self._in_use)

    @property
    def in_use_count(self) -> int:
        """Count of connections currently checked out."""
        return len(self._in_use)

    @property
    def available_count(self) -> int:
        """Count of idle connections available for checkout."""
        return len(self._available)


class AsyncConnectionPoolManager:
    """Manages multiple named AsyncConnectionPool instances."""

    def __init__(self) -> None:
        self._pools: dict[str, AsyncConnectionPool] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        factory: Callable[[], Awaitable[Any] | Any],
        **kwargs: Any,
    ) -> AsyncConnectionPool:
        """Retrieves an existing async pool or creates and registers a new one."""
        async with self._lock:
            if name not in self._pools:
                pool = AsyncConnectionPool(factory=factory, **kwargs)
                await pool.initialize()
                self._pools[name] = pool
            return self._pools[name]

    async def close_all(self) -> None:
        """Closes all registered pools."""
        async with self._lock:
            pools = list(self._pools.values())
            self._pools.clear()

        for p in pools:
            await p.close()

    def get_pool(self, name: str) -> AsyncConnectionPool | None:
        """Retrieves a pool by name if registered."""
        return self._pools.get(name)


_GLOBAL_ASYNC_POOL_MANAGER: AsyncConnectionPoolManager | None = None


def get_async_connection_pool_manager() -> AsyncConnectionPoolManager:
    """Returns the process-wide AsyncConnectionPoolManager instance."""
    global _GLOBAL_ASYNC_POOL_MANAGER
    if _GLOBAL_ASYNC_POOL_MANAGER is None:
        _GLOBAL_ASYNC_POOL_MANAGER = AsyncConnectionPoolManager()
    return _GLOBAL_ASYNC_POOL_MANAGER


async def reset_async_connection_pool_manager() -> None:
    """Closes all pools and resets the global async manager."""
    global _GLOBAL_ASYNC_POOL_MANAGER
    if _GLOBAL_ASYNC_POOL_MANAGER is not None:
        await _GLOBAL_ASYNC_POOL_MANAGER.close_all()
        _GLOBAL_ASYNC_POOL_MANAGER = None


AsyncQueryPool = AsyncConnectionPool


class AsyncStreamingExecutor:
    """High-concurrency async streaming query and export execution harness."""

    def __init__(self, pool: AsyncConnectionPool | None = None) -> None:
        self.pool = pool

    async def execute_stream(
        self,
        connector: Any,
        spec: dict[str, Any] | Any,
        batch_size: int = 1000,
        **kwargs: Any,
    ) -> Any:
        from query_builder.executor import async_execute

        spec_dict = spec.to_dict() if hasattr(spec, "to_dict") else spec
        return await async_execute(connector, spec=spec_dict, **kwargs)

    async def export_stream(
        self,
        connector: Any,
        spec: dict[str, Any] | Any,
        format: str = "csv",
        chunk_size: int = 1000,
        **kwargs: Any,
    ) -> Any:
        from query_builder.export import stream_export_dataset

        result = await self.execute_stream(connector, spec, **kwargs)
        return stream_export_dataset(result, format=format, chunk_size=chunk_size)
