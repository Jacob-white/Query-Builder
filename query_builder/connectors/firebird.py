"""
Firebird Relational Database Connector.
=======================================
Provides Firebird connectivity via firebird-driver / fdb, dual sync and async
execution protocols, query statement isolation, and RDB$ schema introspection.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_firebird
from query_builder.connectors.registry import register_connector


class _FirebirdCursorAdapter:
    """Adapts a Firebird connection into a standard DB-API cursor interface."""

    def __init__(self, connection: Any) -> None:
        self.conn = connection
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if hasattr(self.conn, "cursor"):
            cur = self.conn.cursor()
            try:
                if params:
                    cur.execute(clean_sql, params)
                else:
                    cur.execute(clean_sql)
                self.description = getattr(cur, "description", None)
                self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        elif hasattr(self.conn, "execute"):
            res = (
                self.conn.execute(clean_sql, params)
                if params
                else self.conn.execute(clean_sql)
            )
            if hasattr(res, "description"):
                self.description = res.description
            else:
                self.description = None
            if hasattr(res, "fetchall"):
                self._rows = list(res.fetchall())
            elif isinstance(res, (list, tuple)):
                self._rows = list(res)
            else:
                self._rows = []
        else:
            self.description = None
            self._rows = []

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def fetchmany(self, size: int = 1) -> list[list[Any]]:
        if not self._rows:
            return []
        res = self._rows[:size]
        self._rows = self._rows[size:]
        return res

    def close(self) -> None:
        self._rows = []


def _end_read_transaction(conn: Any) -> None:
    """Firebird drivers keep ONE transaction open per connection; with snapshot isolation a
    long-lived connector would never see rows committed by anyone else after its first read.
    The connector only reads, so ending the transaction after each use is always safe."""
    with contextlib.suppress(Exception):
        conn.rollback()


def _firebird_version(cur: Any) -> str:
    with contextlib.suppress(Exception):  # version is informational only
        cur.execute(
            "SELECT rdb$get_context('SYSTEM', 'ENGINE_VERSION') FROM rdb$database"
        )
        row = cur.fetchone()
        if row and isinstance(row[0], str) and row[0]:
            return f"Firebird {row[0]}"
    return "Firebird"


@register_connector("firebird", aliases=["firebirdsql"])
class FirebirdConnector(BaseConnector):
    """Connector for Firebird relational database management system."""

    dialect_name = "firebird"

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("firebird.driver", "firebird", "fdb"):
            try:
                driver = __import__(mod_name, fromlist=["connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'firebird-driver' or 'fdb' is not installed. "
                "Install with: pip install 'query-builder-engine[firebird]'"
            )

        try:
            connect_fn = getattr(driver, "connect", driver)
            self._connection = connect_fn(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Firebird database: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield self._cursor
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield cur
            finally:
                if hasattr(cur, "close"):
                    cur.close()
                _end_read_transaction(conn)
        else:
            adapter = _FirebirdCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        # Firebird 4.0+: SET STATEMENT TIMEOUT (older servers have no equivalent)
        with contextlib.suppress(Exception):
            cursor.execute(f"SET STATEMENT TIMEOUT {int(timeout_ms)} MILLISECOND")

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        with self.get_cursor() as cur:
            cur.execute("SELECT 1 FROM RDB$DATABASE;")
            cur.fetchone()
            version = _firebird_version(cur)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": version,
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_firebird(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Firebird schema: {exc}"
                ) from exc


@register_connector("async_firebird", aliases=["async_firebirdsql"])
class AsyncFirebirdConnector(AsyncBaseConnector):
    """Asynchronous connector for Firebird relational database."""

    dialect_name = "firebird"

    def __init__(
        self,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("firebird.driver", "firebird", "fdb"):
            try:
                driver = __import__(mod_name, fromlist=["connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'firebird-driver' or 'fdb' is not installed. "
                "Install with: pip install 'query-builder-engine[firebird]'"
            )

        try:
            connect_fn = getattr(driver, "connect", driver)
            # blocking driver: connect off the event loop
            self._connection = await asyncio.to_thread(connect_fn, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Firebird database: {exc}"
            ) from exc

    def _run_sync(
        self, sql: str, params: list[Any] | None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = self._connection
        start = time.perf_counter()
        cur = conn.cursor() if hasattr(conn, "cursor") else _FirebirdCursorAdapter(conn)
        try:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            desc = cur.description or []
            col_names = [col[0] for col in desc]
            rows = cur.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            return col_names, dict_rows, (time.perf_counter() - start) * 1000.0
        finally:
            if hasattr(cur, "close"):
                cur.close()
            _end_read_transaction(conn)

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        await self.connect()
        # the driver blocks: run it in a worker thread so the event loop (and
        # asyncio.wait_for timeouts) stay responsive
        return await asyncio.to_thread(self._run_sync, sql, params)

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        await self.execute_raw("SELECT 1 FROM RDB$DATABASE;")
        _, rows, _ = await self.execute_raw(
            "SELECT rdb$get_context('SYSTEM', 'ENGINE_VERSION') AS v FROM rdb$database"
        )
        value = next(iter(rows[0].values())) if rows else None
        version = (
            f"Firebird {value}" if isinstance(value, str) and value else "Firebird"
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": version,
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()

        def run() -> dict[str, Any]:
            cur = (
                conn.cursor()
                if hasattr(conn, "cursor")
                else _FirebirdCursorAdapter(conn)
            )
            try:
                return introspect_firebird(cur, filter_sensitive=filter_sensitive)
            finally:
                if hasattr(cur, "close"):
                    cur.close()
                _end_read_transaction(conn)

        try:
            return await asyncio.to_thread(run)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Firebird schema: {exc}"
            ) from exc
