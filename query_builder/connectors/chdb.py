"""
chDB In-Process ClickHouse OLAP SQL Engine Connector.
=====================================================
Provides embedded in-process ClickHouse SQL query execution via chDB,
dual sync and async execution protocols, and system catalog introspection.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_chdb
from query_builder.connectors.registry import register_connector


def _use_database(conn: Any, database: str) -> None:
    """Point the session at ``database`` (the ``database`` argument was stored but never used,
    so every unqualified table name resolved against ``default``)."""
    if not hasattr(conn, "cursor"):
        return
    if database and database != "default" and not database.replace("_", "").isalnum():
        raise ConnectionFailedError(f"Invalid chDB database name: {database!r}")
    cur = conn.cursor()
    try:
        # join_use_nulls: without it ClickHouse fills the unmatched side of an OUTER JOIN with
        # type defaults ('' / 0) instead of NULL, silently corrupting LEFT/RIGHT join results.
        cur.execute("SET join_use_nulls = 1")
        if database and database != "default":
            cur.execute(f"USE `{database}`")
    finally:
        if hasattr(cur, "close"):
            cur.close()


def _chdb_version() -> str:
    try:
        import chdb
    except ImportError:  # pragma: no cover - the connector needs the driver anyway
        return "chDB"
    ver = str(getattr(chdb, "__version__", "") or "")
    engine = getattr(chdb, "engine_version", None)
    return (
        f"chDB {ver} (ClickHouse {engine})"
        if isinstance(engine, str)
        else f"chDB {ver}".strip()
    )


class _ChDBCursorAdapter:
    """Adapts chDB module or in-process query function into a DB-API cursor interface."""

    def __init__(self, chdb_mod: Any, database: str = "default") -> None:
        self.chdb = chdb_mod
        self.database = database
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if params:
            # Inline parameter substitution for chDB if DBAPI isn't used
            for p in params:
                if p is None:
                    val = "NULL"
                elif isinstance(p, bool):
                    val = "1" if p else "0"
                elif isinstance(p, str):
                    val = "'" + p.replace("'", "\\'") + "'"
                else:
                    val = str(p)
                if "%s" in clean_sql:
                    clean_sql = clean_sql.replace("%s", val, 1)
                else:
                    clean_sql = clean_sql.replace("?", val, 1)

        try:
            if hasattr(self.chdb, "query"):
                res = self.chdb.query(clean_sql, "JSONEachRow")
                if hasattr(res, "bytes"):
                    bytes_or_str = res.bytes
                elif hasattr(res, "data"):
                    bytes_or_str = res.data
                else:
                    bytes_or_str = res

                if not bytes_or_str:
                    self.description = []
                    self._rows = []
                    return

                raw_text = (
                    bytes_or_str.decode("utf-8")
                    if isinstance(bytes_or_str, (bytes, bytearray))
                    else str(bytes_or_str)
                )
                lines = [
                    line.strip()
                    for line in raw_text.strip().split("\n")
                    if line.strip()
                ]
                parsed = [json.loads(line) for line in lines]
                if parsed:
                    col_names = list(parsed[0].keys())
                    self.description = [(col,) for col in col_names]
                    self._rows = [[row.get(c) for c in col_names] for row in parsed]
                else:
                    self.description = []
                    self._rows = []
            elif hasattr(self.chdb, "execute"):
                self.chdb.execute(clean_sql)
                self.description = getattr(self.chdb, "description", None)
                self._rows = (
                    list(self.chdb.fetchall()) if hasattr(self.chdb, "fetchall") else []
                )
            else:
                self.description = []
                self._rows = []
        except Exception as exc:
            raise RuntimeError(f"chDB query execution failed: {exc}") from exc

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


@register_connector("chdb")
class ChDBConnector(BaseConnector):
    """Connector for chDB in-process ClickHouse SQL query engine."""

    dialect_name = "chdb"

    def __init__(
        self,
        database: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.database = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("chdb.dbapi", "chdb"):
            try:
                driver = __import__(mod_name, fromlist=["connect", "query"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'chdb' is not installed. "
                "Install with: pip install 'query-builder-engine[chdb]'"
            )

        try:
            if hasattr(driver, "connect"):
                self._connection = driver.connect(**self.config)
            else:
                self._connection = driver
            _use_database(self._connection, self.database)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to initialize chDB in-process engine: {exc}"
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
        else:
            adapter = _ChDBCursorAdapter(conn, database=self.database)
            yield adapter

    read_only_support = "enforced"

    def apply_read_only(self, connection: Any) -> None:
        # readonly=2: no writes/DDL, but settings (max_execution_time) stay changeable
        cur = connection.cursor() if hasattr(connection, "cursor") else None
        if cur is not None and hasattr(cur, "execute"):
            try:
                cur.execute("SET readonly = 2")
            finally:
                if hasattr(cur, "close"):
                    cur.close()

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        if hasattr(cursor, "execute") and not isinstance(cursor, _ChDBCursorAdapter):
            cursor.execute(
                f"SET max_execution_time = {max(1, int(timeout_ms) // 1000)}"
            )

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = _chdb_version()
        info["database"] = self.database
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_chdb(
                    cur,
                    database=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect chDB database '{self.database}': {exc}"
                ) from exc


@register_connector("async_chdb")
class AsyncChDBConnector(AsyncBaseConnector):
    """Asynchronous connector for chDB in-process ClickHouse query engine."""

    dialect_name = "chdb"

    def __init__(
        self,
        database: str = "default",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.database = database

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("chdb.dbapi", "chdb"):
            try:
                driver = __import__(mod_name, fromlist=["connect", "query"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'chdb' is not installed. "
                "Install with: pip install 'query-builder-engine[chdb]'"
            )

        try:
            if hasattr(driver, "connect"):
                self._connection = driver.connect(**self.config)
            else:
                self._connection = driver
            _use_database(self._connection, self.database)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to initialize chDB in-process engine: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
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
        else:
            adapter = _ChDBCursorAdapter(conn, database=self.database)
            adapter.execute(sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = None
        try:
            cur = conn.cursor() if hasattr(conn, "cursor") else _ChDBCursorAdapter(conn)
            return introspect_chdb(
                cur, database=self.database, filter_sensitive=filter_sensitive
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect chDB database '{self.database}': {exc}"
            ) from exc
        finally:
            if cur is not None and hasattr(cur, "close"):
                cur.close()
