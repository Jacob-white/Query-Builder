"""
Memgraph In-Memory Graph Database Connector.
============================================
Provides Memgraph connectivity via neo4j / mgclient Bolt driver,
dual sync and async execution protocols, and OpenCypher schema introspection.
"""

from __future__ import annotations

import contextlib
import inspect
import time
from typing import Any

from query_builder.connectors._native_readonly import assert_read_only
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import (
    introspect_memgraph,
    memgraph_schema_steps,
)
from query_builder.connectors.registry import register_connector


class _MemgraphCursorAdapter:
    """Adapts a Memgraph Driver / Session into a DB-API cursor interface."""

    def __init__(self, connection: Any, read_only: bool = True) -> None:
        self.conn = connection
        self.read_only = read_only
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if clean_sql.upper() in ("SELECT 1", "SELECT 1;"):
            clean_sql = "RETURN 1 AS val"
        if self.read_only:
            # Memgraph ignores Bolt access modes, and SET / MERGE / REMOVE are not in the
            # SQL-shaped generic mutation check: refuse them here, below every code path.
            assert_read_only(clean_sql, "cypher", "Memgraph")
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
        elif hasattr(self.conn, "execute_query"):
            res = self.conn.execute_query(clean_sql, parameters=params or {})
            records = getattr(res, "records", res)
            keys = getattr(res, "keys", [])
            self.description = [(k,) for k in keys] if keys else None
            self._rows = [
                list(r.values()) if hasattr(r, "values") else list(r) for r in records
            ]
        elif hasattr(self.conn, "run"):
            res = self.conn.run(clean_sql, params or {})
            keys = getattr(res, "keys", list)()
            self.description = [(k,) for k in keys] if keys else None
            records = res.values() if hasattr(res, "values") else list(res)
            self._rows = [list(r) for r in records]
        elif hasattr(self.conn, "session"):
            session = self.conn.session()
            try:
                adapter = _MemgraphCursorAdapter(session, read_only=False)
                adapter.execute(clean_sql, params)
                self.description = adapter.description
                self._rows = adapter._rows
            finally:
                if hasattr(session, "close"):
                    session.close()
        elif hasattr(self.conn, "execute"):
            res = (
                self.conn.execute(clean_sql, params)
                if params
                else self.conn.execute(clean_sql)
            )
            self.description = getattr(res, "description", None)
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


@register_connector("memgraph", aliases=["memgraph_db"])
class MemgraphConnector(BaseConnector):
    """Connector for Memgraph in-memory graph database."""

    dialect_name = "memgraph"

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        auth: tuple[str, str] | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.uri = uri
        self.auth = auth

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("neo4j", "mgclient"):
            try:
                driver = __import__(mod_name, fromlist=["GraphDatabase", "connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'neo4j' or 'mgclient' is not installed. "
                "Install with: pip install 'query-builder-engine[memgraph]'"
            )

        try:
            if hasattr(driver, "GraphDatabase"):
                self._connection = driver.GraphDatabase.driver(
                    self.uri, auth=self.auth, **self.config
                )
            else:
                self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Memgraph: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield self._cursor
            return

        conn = self.connect()
        if hasattr(conn, "session"):
            session = conn.session()
            adapter = _MemgraphCursorAdapter(session, read_only=self._read_only())
            try:
                yield adapter
            finally:
                adapter.close()
                if hasattr(session, "close"):
                    session.close()
        elif hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield cur
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        else:
            adapter = _MemgraphCursorAdapter(conn, read_only=self._read_only())
            try:
                yield adapter
            finally:
                adapter.close()

    def _read_only(self) -> bool:
        sec = getattr(self, "security", None)
        return sec is None or sec.execution.enforce_read_only_session

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        version = "Memgraph"
        with self.get_cursor() as cur:
            cur.execute("RETURN 1 AS val;")
            cur.fetchone()
            with contextlib.suppress(Exception):
                cur.execute("SHOW VERSION;")
                row = cur.fetchone()
                if row and row[0]:
                    version = f"Memgraph {row[0]}"
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
                return introspect_memgraph(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Memgraph schema: {exc}"
                ) from exc


@register_connector("async_memgraph", aliases=["async_memgraph_db"])
class AsyncMemgraphConnector(AsyncBaseConnector):
    """Asynchronous connector for Memgraph in-memory graph database."""

    dialect_name = "memgraph"

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        auth: tuple[str, str] | None = None,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.uri = uri
        self.auth = auth

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("neo4j", "mgclient"):
            try:
                driver = __import__(
                    mod_name, fromlist=["AsyncGraphDatabase", "GraphDatabase"]
                )
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'neo4j' or 'mgclient' is not installed. "
                "Install with: pip install 'query-builder-engine[memgraph]'"
            )

        try:
            if hasattr(driver, "AsyncGraphDatabase"):
                self._connection = driver.AsyncGraphDatabase.driver(
                    self.uri, auth=self.auth, **self.config
                )
            elif hasattr(driver, "GraphDatabase"):
                self._connection = driver.GraphDatabase.driver(
                    self.uri, auth=self.auth, **self.config
                )
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Memgraph: {exc}"
            ) from exc

    def _read_only(self) -> bool:
        sec = getattr(self, "security", None)
        return sec is None or sec.execution.enforce_read_only_session

    async def _fetch(
        self, conn: Any, cypher: str, params: Any = None
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """One query on a real ``neo4j.AsyncDriver`` (Memgraph speaks Bolt)."""
        clean = cypher.strip().rstrip(";").strip()
        if self._read_only():
            assert_read_only(clean, "cypher", "Memgraph")
        parameters = params if isinstance(params, dict) else {}
        async with conn.session() as session:
            result = await session.run(clean, parameters)
            records = [record async for record in result]
            keys = list(result.keys())
        return keys, [dict(zip(keys, rec.values(), strict=False)) for rec in records]

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if _is_async_driver(conn):
            if sql.strip().rstrip(";").strip().upper() == "SELECT 1":
                sql = "RETURN 1 AS val"
            keys, dict_rows = await self._fetch(conn, sql, params)
            return keys, dict_rows, (time.perf_counter() - start) * 1000.0
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _MemgraphCursorAdapter(conn, read_only=self._read_only())

        try:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            desc = cur.description or []
            col_names = [col[0] for col in desc]
            rows = cur.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            if hasattr(cur, "close"):
                cur.close()

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        await self.execute_raw("RETURN 1 AS val;")
        version = "Memgraph"
        conn = self._connection
        if conn is not None and _is_async_driver(conn):
            with contextlib.suppress(Exception):
                _, rows = await self._fetch(conn, "SHOW VERSION")
                if rows:
                    version = f"Memgraph {next(iter(rows[0].values()))}"
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": version,
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        if _is_async_driver(conn):
            try:
                steps = memgraph_schema_steps(filter_sensitive)
                statement = next(steps)
                while True:
                    try:
                        _, rows = await self._fetch(conn, statement)
                    except Exception as exc:  # noqa: BLE001 - handed to the generator
                        statement = steps.throw(exc)
                        continue
                    statement = steps.send(rows)
            except StopIteration as done:
                return done.value  # type: ignore[no-any-return]
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Memgraph schema: {exc}"
                ) from exc
        cur = (
            conn.cursor()
            if hasattr(conn, "cursor")
            else _MemgraphCursorAdapter(conn, read_only=self._read_only())
        )
        try:
            return introspect_memgraph(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Memgraph schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()


def _is_async_driver(conn: Any) -> bool:
    """A real ``neo4j.AsyncDriver`` (its methods are coroutines; Mocks' are not)."""
    return inspect.iscoroutinefunction(getattr(conn, "verify_connectivity", None))
