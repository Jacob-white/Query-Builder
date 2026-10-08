"""
Thread-Safe Database Connection Pool & Multi-Pool Manager.
==========================================================
Manages a pool of reusable DB-API connections with health checks (SELECT 1),
idle eviction, connection lifespan recycling, minimum/maximum capacity bounds,
cooperative query cancellation tokens, secret masking, and context manager support.
"""

from __future__ import annotations

import contextlib
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any


class PoolError(Exception):
    """Base exception for connection pool failures."""


class PoolTimeoutError(PoolError):
    """Raised when connection acquisition times out."""


class PoolClosedError(PoolError):
    """Raised when operation is attempted on closed pool."""


class QueryCancelledError(PoolError):
    """Raised when an in-flight query is cancelled via CancellationToken."""


_SECRET_KEY_PATTERNS = re.compile(
    r"(password|secret|token|api_key|credential|private_key|auth|access_key)",
    re.IGNORECASE,
)
_URI_PASSWORD_REGEX = re.compile(
    r"(://[^:]+:)([^@]+)(@)",
    re.IGNORECASE,
)


def mask_credentials(data: Any) -> Any:
    """
    Recursively masks passwords, tokens, API keys, and connection URI credentials.
    Ensures secrets are never exposed in logs, exceptions, or JSON serializations.
    """
    if isinstance(data, str):
        # A credential match always ends at an "@", so the text after the last "@" can
        # never be part of one.  Without this bound every "://" start scans to the end of
        # a string that has no "@" (quadratic).
        end = data.rfind("@") + 1
        if not end:
            return data
        return _URI_PASSWORD_REGEX.sub(r"\1***\3", data[:end]) + data[end:]
    if isinstance(data, dict):
        masked: dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(k, str) and _SECRET_KEY_PATTERNS.search(k):
                masked[k] = "***"
            else:
                masked[k] = mask_credentials(v)
        return masked
    if isinstance(data, list):
        return [mask_credentials(item) for item in data]
    if isinstance(data, tuple):
        return tuple(mask_credentials(item) for item in data)
    return data


class CancellationToken:
    """
    Cooperative cancellation token for in-flight database query execution.
    Allows registering callbacks to cancel database sockets or interrupt workers.
    """

    def __init__(self) -> None:
        self._is_cancelled: bool = False
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    @property
    def is_cancelled(self) -> bool:
        """Returns True if cancellation has been requested."""
        with self._lock:
            return self._is_cancelled

    def cancel(self) -> None:
        """Signals cancellation and invokes all registered callbacks."""
        callbacks_to_run: list[Callable[[], None]] = []
        with self._lock:
            if self._is_cancelled:
                return
            self._is_cancelled = True
            callbacks_to_run = list(self._callbacks)
            self._callbacks.clear()

        for cb in callbacks_to_run:
            try:
                cb()
            except Exception:  # noqa: BLE001, S110
                pass

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Registers a callback to be invoked upon cancellation."""
        should_run_now = False
        with self._lock:
            if self._is_cancelled:
                should_run_now = True
            else:
                self._callbacks.append(callback)

        if should_run_now:
            try:
                callback()
            except Exception:  # noqa: BLE001, S110
                pass

    def throw_if_cancelled(self) -> None:
        """Raises QueryCancelledError if cancellation has been requested."""
        if self.is_cancelled:
            raise QueryCancelledError("Query execution was cancelled.")


class ConnectionPool:
    """Thread-safe database connection pool with health checks and lifespan recycling."""

    def __init__(
        self,
        factory: Callable[[], Any],
        max_size: int = 10,
        min_size: int = 0,
        timeout: float = 30.0,
        max_idle_seconds: float = 300.0,
        max_lifespan_seconds: float = 3600.0,
        health_check_sql: str = "SELECT 1",
    ) -> None:
        self.factory = factory
        self.max_size = max(1, max_size)
        self.min_size = max(0, min(min_size, self.max_size))
        self.timeout = max(0.0, timeout)
        self.max_idle_seconds = max(0.0, max_idle_seconds)
        self.max_lifespan_seconds = max(0.0, max_lifespan_seconds)
        self.health_check_sql = health_check_sql

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        # Entry format: (connection, last_used_timestamp, created_at_timestamp)
        self._available: list[tuple[Any, float, float]] = []
        self._in_use: set[Any] = set()
        self._closed = False

        # Pre-populate minimum connections
        if self.min_size > 0:
            now = time.time()
            for _ in range(self.min_size):
                conn = self.factory()
                self._available.append((conn, now, now))

    def acquire(self) -> Any:
        """Acquires a healthy connection from the pool or creates a new one."""
        with self._cond:
            if self._closed:
                raise PoolClosedError("Connection pool is closed.")

            start_time = time.time()

            while True:
                if self._closed:
                    raise PoolClosedError("Connection pool is closed.")

                now = time.time()

                # Option 1: Reuse existing available connection
                if self._available:
                    conn, last_time, created_time = self._available.pop()
                    is_idle = (now - last_time) > self.max_idle_seconds
                    is_expired = (now - created_time) > self.max_lifespan_seconds
                    healthy = True

                    if not is_idle and not is_expired and self.health_check_sql:
                        try:
                            cursor = conn.cursor()
                            cursor.execute(self.health_check_sql)
                            cursor.close()
                        except Exception:  # noqa: BLE001
                            healthy = False

                    if is_idle or is_expired or not healthy:
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
                    now = time.time()
                    self._available.append((conn, now, now))
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
            for conn, _, _ in self._available:
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


class ConnectionPoolManager:
    """
    Registry and lifecycle manager for multiple connection pools and query executions.
    """

    def __init__(self) -> None:
        self._pools: dict[str, ConnectionPool] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._executions: dict[str, CancellationToken] = {}
        self._lock = threading.Lock()

    def register_pool(
        self,
        connection_id: str,
        pool: ConnectionPool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Registers a ConnectionPool instance under a given connection_id."""
        if not connection_id or not isinstance(connection_id, str):
            raise ValueError("connection_id must be a non-empty string.")
        if not isinstance(pool, ConnectionPool):
            raise TypeError("pool must be an instance of ConnectionPool.")
        with self._lock:
            if connection_id in self._pools and self._pools[connection_id] is not pool:
                self._pools[connection_id].close_all()
            self._pools[connection_id] = pool
            self._metadata[connection_id] = dict(metadata or {})

    def get_pool(self, connection_id: str) -> ConnectionPool:
        """Retrieves a registered ConnectionPool by connection_id."""
        with self._lock:
            pool = self._pools.get(connection_id)
            if pool is None:
                raise PoolError(f"Connection pool '{connection_id}' is not registered.")
            return pool

    def has_pool(self, connection_id: str) -> bool:
        """Checks if a pool is registered under connection_id."""
        with self._lock:
            return connection_id in self._pools

    def remove_pool(self, connection_id: str) -> None:
        """Closes and removes a registered connection pool."""
        with self._lock:
            pool = self._pools.pop(connection_id, None)
            self._metadata.pop(connection_id, None)
        if pool is not None:
            pool.close_all()

    def list_pools(self) -> list[dict[str, Any]]:
        """Returns status and masked metadata for all registered pools."""
        with self._lock:
            items = []
            for cid in sorted(self._pools.keys()):
                pool = self._pools[cid]
                meta = self._metadata.get(cid, {})
                items.append(
                    {
                        "connection_id": cid,
                        "size": pool.size,
                        "available": pool.available_count,
                        "in_use": pool.in_use_count,
                        "metadata": mask_credentials(meta),
                    }
                )
            return items

    @contextlib.contextmanager
    def connection(self, connection_id: str) -> Iterator[Any]:
        """Context manager checking out a connection from a named pool."""
        pool = self.get_pool(connection_id)
        with pool.connection() as conn:
            yield conn

    def close_all(self) -> None:
        """Closes all registered pools and clears registrations."""
        with self._lock:
            pools_to_close = list(self._pools.values())
            self._pools.clear()
            self._metadata.clear()
        for pool in pools_to_close:
            pool.close_all()

    # Query Execution & Cancellation Management
    def create_execution(
        self, execution_id: str | None = None
    ) -> tuple[str, CancellationToken]:
        """Creates and tracks a CancellationToken for a query execution."""
        eid = execution_id or str(uuid.uuid4())
        with self._lock:
            if eid in self._executions:
                return eid, self._executions[eid]
            token = CancellationToken()
            self._executions[eid] = token
            return eid, token

    def get_execution(self, execution_id: str) -> CancellationToken | None:
        """Retrieves an active CancellationToken by execution_id."""
        with self._lock:
            return self._executions.get(execution_id)

    def cancel_execution(self, execution_id: str) -> bool:
        """Cancels an active execution. Returns True if found, False otherwise."""
        with self._lock:
            token = self._executions.get(execution_id)
        if token is not None:
            token.cancel()
            return True
        return False

    def unregister_execution(self, execution_id: str) -> None:
        """Unregisters an execution token upon completion."""
        with self._lock:
            self._executions.pop(execution_id, None)

    # Health Check & Connectivity Test
    def test_connection(
        self,
        target: str | dict[str, Any] | ConnectionPool,
    ) -> dict[str, Any]:
        """
        Validates connectivity, runs a healthcheck ping ('SELECT 1'),
        and returns latency and dialect info.
        """
        start = time.perf_counter()
        dialect_name = "unknown"
        conn_id: str | None = None

        try:
            if isinstance(target, str):
                conn_id = target
                pool = self.get_pool(target)
                dialect_name = self._metadata.get(target, {}).get("dialect", "unknown")
                with pool.connection() as conn:
                    cur = conn.cursor()
                    cur.execute(pool.health_check_sql or "SELECT 1")
                    cur.close()
            elif isinstance(target, ConnectionPool):
                dialect_name = "custom"
                with target.connection() as conn:
                    cur = conn.cursor()
                    cur.execute(target.health_check_sql or "SELECT 1")
                    cur.close()
            elif isinstance(target, dict):
                from query_builder.connectors.registry import ConnectorRegistry

                dialect_name = target.get("dialect", target.get("connector", "sqlite"))
                clean_target = {
                    k: v for k, v in target.items() if k not in ("dialect", "connector")
                }
                conn = ConnectorRegistry.get(dialect_name, **clean_target)
                info = conn.test_connection()
                return {
                    "healthy": info.get("status") == "healthy",
                    "latency_ms": info.get("latency_ms", 0.0),
                    "dialect": dialect_name,
                    "connection_id": None,
                }
            else:
                raise TypeError(
                    f"Invalid target type for test_connection: {type(target).__name__}"
                )

            latency_ms = (time.perf_counter() - start) * 1000.0
            return {
                "healthy": True,
                "latency_ms": round(latency_ms, 2),
                "dialect": dialect_name,
                "connection_id": conn_id,
            }
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return {
                "healthy": False,
                "error": mask_credentials(str(exc)),
                "latency_ms": round(latency_ms, 2),
                "dialect": dialect_name,
                "connection_id": conn_id,
            }

    def execute_query(
        self,
        sql_or_spec: str | dict[str, Any],
        connection_id: str | None = None,
        config: dict[str, Any] | None = None,
        dialect: str | None = None,
        params: list[Any] | None = None,
        timeout_ms: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
        execution_id: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> dict[str, Any]:
        """
        Executes a SQL string or QuerySpec with cooperative cancellation and timeout.
        """
        eid, token = (
            (execution_id or str(uuid.uuid4()), cancellation_token)
            if cancellation_token is not None
            else self.create_execution(execution_id)
        )

        try:
            token.throw_if_cancelled()
            start_time = time.perf_counter()

            # Compile spec if input is QuerySpec dict
            effective_dialect = (
                dialect
                or (
                    self._metadata.get(connection_id, {}).get("dialect")
                    if connection_id
                    else None
                )
                or "sqlite"
            )

            if isinstance(sql_or_spec, dict):
                from query_builder.compiler import QueryCompiler

                compiler = QueryCompiler(spec=sql_or_spec, dialect=effective_dialect)
                sql, compiled_params, _, _ = compiler.compile()
                active_params = compiled_params
            else:
                sql = str(sql_or_spec)
                active_params = list(params or [])

            token.throw_if_cancelled()

            # Execution pathway 1: via named ConnectionPool
            if connection_id and self.has_pool(connection_id):
                with self.connection(connection_id) as conn:
                    # Register cancellation hooks
                    if hasattr(conn, "interrupt"):
                        token.register_callback(conn.interrupt)
                    elif hasattr(conn, "cancel"):
                        token.register_callback(conn.cancel)

                    token.throw_if_cancelled()
                    cur = conn.cursor()
                    try:
                        if active_params:
                            cur.execute(sql, active_params)
                        else:
                            cur.execute(sql)

                        col_names = (
                            [d[0] for d in cur.description] if cur.description else []
                        )
                        raw_rows = cur.fetchall()
                        token.throw_if_cancelled()
                    finally:
                        cur.close()

                    dict_rows = [
                        dict(zip(col_names, row, strict=False)) for row in raw_rows
                    ]
                    latency_ms = (time.perf_counter() - start_time) * 1000.0

                    return {
                        "execution_id": eid,
                        "sql": sql,
                        "params": active_params,
                        "columns": col_names,
                        "rows": dict_rows,
                        "count": len(dict_rows),
                        "limit": limit or len(dict_rows),
                        "offset": offset or 0,
                        "latency_ms": round(latency_ms, 2),
                        "dialect": effective_dialect,
                    }

            # Execution pathway 2: via ConnectorRegistry
            from query_builder.connectors.registry import ConnectorRegistry

            target_connector = effective_dialect
            connector_instance = ConnectorRegistry.get(
                target_connector, **(config or {})
            )

            token.throw_if_cancelled()
            if isinstance(sql_or_spec, dict):
                result = connector_instance.execute(
                    sql_or_spec, statement_timeout_ms=timeout_ms
                )
                token.throw_if_cancelled()
                result["execution_id"] = eid
                return result

            cols, rows, latency = connector_instance.execute_raw(sql, active_params)
            token.throw_if_cancelled()

            return {
                "execution_id": eid,
                "sql": sql,
                "params": active_params,
                "columns": cols,
                "rows": rows,
                "count": len(rows),
                "limit": limit or len(rows),
                "offset": offset or 0,
                "latency_ms": round(latency, 2),
                "dialect": effective_dialect,
            }
        finally:
            self.unregister_execution(eid)


_GLOBAL_POOL_MANAGER: ConnectionPoolManager | None = None
_GLOBAL_POOL_LOCK = threading.Lock()


def get_connection_pool_manager() -> ConnectionPoolManager:
    """Returns the process-wide global ConnectionPoolManager singleton."""
    global _GLOBAL_POOL_MANAGER
    if _GLOBAL_POOL_MANAGER is None:
        with _GLOBAL_POOL_LOCK:
            if _GLOBAL_POOL_MANAGER is None:
                _GLOBAL_POOL_MANAGER = ConnectionPoolManager()
    return _GLOBAL_POOL_MANAGER


def reset_connection_pool_manager() -> None:
    """Resets and cleans up the global ConnectionPoolManager."""
    global _GLOBAL_POOL_MANAGER
    with _GLOBAL_POOL_LOCK:
        if _GLOBAL_POOL_MANAGER is not None:
            _GLOBAL_POOL_MANAGER.close_all()
            _GLOBAL_POOL_MANAGER = None
