"""
SurrealDB Multi-Model Document/Graph Database Connector.
========================================================
Provides SurrealDB connectivity via surrealdb SDK, dual sync and async execution protocols,
SurrealQL query execution, cursor adaptation, and schema introspection.
"""

from __future__ import annotations

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
from query_builder.connectors.introspection import introspect_surrealdb
from query_builder.connectors.registry import register_connector


class _SurrealCursorAdapter:
    """Adapts a SurrealDB client instance into a DB-API cursor interface."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if hasattr(self.client, "query"):
            res = self.client.query(clean_sql, params or {})
            if isinstance(res, list) and res:
                # SurrealDB returns a list of result objects, e.g. [{"result": [...], "status": "OK"}]
                first = res[0]
                items = first.get("result") if isinstance(first, dict) else first
                if isinstance(items, list) and items:
                    if isinstance(items[0], dict):
                        col_names = list(items[0].keys())
                        self.description = [(col,) for col in col_names]
                        self._rows = [[row.get(c) for c in col_names] for row in items]
                    else:
                        self.description = [("value",)]
                        self._rows = [[item] for item in items]
                else:
                    self.description = []
                    self._rows = []
            elif isinstance(res, dict):
                col_names = list(res.keys())
                self.description = [(col,) for col in col_names]
                self._rows = [[res.get(c) for c in col_names]]
            else:
                self.description = []
                self._rows = []
        elif hasattr(self.client, "execute"):
            if params:
                self.client.execute(clean_sql, params)
            else:
                self.client.execute(clean_sql)
            self.description = getattr(self.client, "description", None)
            self._rows = (
                list(self.client.fetchall()) if hasattr(self.client, "fetchall") else []
            )
        else:
            self.description = []
            self._rows = []

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


@register_connector("surrealdb", aliases=["surreal"])
class SurrealDBConnector(BaseConnector):
    """Connector for SurrealDB multi-model database engine."""

    dialect_name = "surrealdb"

    def __init__(
        self,
        url: str = "ws://localhost:8000/rpc",
        database: str = "test",
        namespace: str = "test",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.url = url
        self.database = database
        self.namespace = namespace
        self.schema_name = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("surrealdb", "surrealdb.ws"):
            try:
                driver = __import__(mod_name, fromlist=["Surreal", "connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'surrealdb' is not installed. "
                "Install with: pip install 'query-builder-engine[surrealdb]'"
            )

        try:
            surreal_cls = getattr(driver, "Surreal", None)
            if surreal_cls:
                client = surreal_cls(self.url, **self.config)
            else:
                client = driver.connect(self.url, **self.config)
            self._connection = client
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to SurrealDB at '{self.url}': {exc}"
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
            adapter = _SurrealCursorAdapter(conn)
            yield adapter

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "SurrealDB"
        info["database"] = self.database
        info["namespace"] = self.namespace
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_surrealdb(
                    cur,
                    database=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect SurrealDB database '{self.database}': {exc}"
                ) from exc


@register_connector("async_surrealdb", aliases=["async_surreal"])
class AsyncSurrealDBConnector(AsyncBaseConnector):
    """Asynchronous connector for SurrealDB multi-model database."""

    dialect_name = "surrealdb"

    def __init__(
        self,
        url: str = "ws://localhost:8000/rpc",
        database: str = "test",
        namespace: str = "test",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.url = url
        self.database = database
        self.namespace = namespace
        self.schema_name = database

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("surrealdb", "surrealdb.ws"):
            try:
                driver = __import__(mod_name, fromlist=["Surreal", "connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'surrealdb' is not installed. "
                "Install with: pip install 'query-builder-engine[surrealdb]'"
            )

        try:
            surreal_cls = getattr(driver, "Surreal", None)
            if surreal_cls:
                client = surreal_cls(self.url, **self.config)
            else:
                client = driver.connect(self.url, **self.config)
            self._connection = client
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to SurrealDB: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _SurrealCursorAdapter(conn)
        adapter.execute(sql, params)
        desc = adapter.description or []
        col_names = [col[0] for col in desc]
        rows = adapter.fetchall() or []
        dict_rows = [dict(zip(col_names, r)) for r in rows]
        latency_ms = (time.perf_counter() - start) * 1000.0
        return col_names, dict_rows, latency_ms
