"""
Real asyncio execution for async connectors that sit on DB-API style drivers.

``psycopg`` (3.x, ``AsyncConnection``) and ``aiomysql``/``asyncmy`` are genuinely
asynchronous: their cursor calls are awaited.  Blocking drivers (``psycopg2``,
``pymysql``, the ``crate`` HTTP client, ...) are run on a worker thread so that an async
connector never blocks the event loop and never leaves a coroutine un-awaited.

A connection object is classified by its class, not by duck typing, so a ``Mock`` handed to
a connector is always treated as a blocking connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from collections.abc import Callable
from typing import Any


def is_native_async(conn: Any) -> bool:
    """True for a real ``psycopg.AsyncConnection`` or an aiomysql/asyncmy connection."""
    cls = type(conn)
    root = cls.__module__.split(".")[0]
    if root == "psycopg":
        return cls.__name__ == "AsyncConnection"
    return root in ("aiomysql", "asyncmy")


async def open_psycopg_async(driver: Any, config: dict[str, Any]) -> Any | None:
    """Open a ``psycopg.AsyncConnection`` (autocommit) when ``driver`` is real psycopg 3.

    Returns ``None`` for anything else (psycopg2, a Mock, ...) so the caller can fall back
    to :func:`open_blocking`.
    """
    cls = getattr(driver, "AsyncConnection", None)
    connect = getattr(cls, "connect", None)
    if inspect.iscoroutinefunction(connect):
        return await connect(autocommit=True, **config)
    return None


async def open_aiomysql(driver: Any, config: dict[str, Any]) -> Any | None:
    """Open an aiomysql/asyncmy connection (autocommit); ``None`` for other drivers."""
    connect = getattr(driver, "connect", None)
    if getattr(driver, "__name__", "") in ("aiomysql", "asyncmy") and callable(connect):
        return await connect(autocommit=True, **config)
    return None


async def open_blocking(connect: Callable[..., Any], **config: Any) -> Any:
    """Run a blocking driver's ``connect`` on a worker thread; sessions autocommit."""
    conn = await asyncio.to_thread(connect, **config)
    with contextlib.suppress(Exception):
        conn.autocommit = True
    return conn


def _blocking_query(
    conn: Any, sql: str, params: list[Any] | None
) -> tuple[list[str], list[Any]]:
    cur = conn.cursor()
    try:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        names = [c[0] for c in (cur.description or [])]
        rows = cur.fetchall() or []
        return names, list(rows)
    except Exception:
        rollback = getattr(conn, "rollback", None)
        if callable(rollback):
            with contextlib.suppress(Exception):
                rollback()
        raise
    finally:
        with contextlib.suppress(Exception):
            cur.close()


async def run_query(
    conn: Any, sql: str, params: list[Any] | None = None
) -> tuple[list[str], list[dict[str, Any]], float]:
    """Execute one statement; returns ``(columns, dict rows, latency_ms)``."""
    start = time.perf_counter()
    if is_native_async(conn):
        async with conn.cursor() as cur:
            if params:
                await cur.execute(sql, params)
            else:
                await cur.execute(sql)
            names = [c[0] for c in (cur.description or [])]
            rows = list(await cur.fetchall()) if cur.description else []
    else:
        names, rows = await asyncio.to_thread(_blocking_query, conn, sql, params)
    dict_rows = [dict(zip(names, r, strict=False)) for r in rows]
    return names, dict_rows, (time.perf_counter() - start) * 1000.0


class _LoopCursor:
    """Synchronous cursor facade over an async connection, for worker-thread callers.

    The existing introspection helpers are written against a blocking DB-API cursor.  They
    run on a worker thread; every ``execute`` is scheduled on the event loop that owns the
    async connection and waited for, so the loop itself is never blocked.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, conn: Any) -> None:
        self._loop = loop
        self._conn = conn
        self._rows: list[Any] = []
        self.description: Any = None

    async def _run(self, sql: str, params: Any) -> None:
        async with self._conn.cursor() as cur:
            if params:
                await cur.execute(sql, params)
            else:
                await cur.execute(sql)
            self.description = cur.description
            self._rows = list(await cur.fetchall()) if cur.description else []

    def execute(self, sql: str, params: Any = None) -> None:
        asyncio.run_coroutine_threadsafe(self._run(sql, params), self._loop).result()

    def fetchall(self) -> list[Any]:
        rows, self._rows = self._rows, []
        return rows

    def fetchone(self) -> Any:
        return self._rows.pop(0) if self._rows else None

    def close(self) -> None:
        self._rows = []


async def introspect_with(conn: Any, introspect: Callable[[Any], Any]) -> Any:
    """Run a blocking ``introspect(cursor)`` helper against ``conn`` without blocking."""
    if is_native_async(conn):
        cursor: Any = _LoopCursor(asyncio.get_running_loop(), conn)
        return await asyncio.to_thread(introspect, cursor)

    def work() -> Any:
        cur = conn.cursor() if hasattr(conn, "cursor") else conn
        try:
            return introspect(cur)
        except Exception:
            rollback = getattr(conn, "rollback", None)
            if callable(rollback):
                with contextlib.suppress(Exception):
                    rollback()
            raise
        finally:
            if cur is not conn:
                with contextlib.suppress(Exception):
                    cur.close()

    return await asyncio.to_thread(work)
