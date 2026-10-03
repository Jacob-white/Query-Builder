"""
Exasol High-Performance In-Memory Analytics Database Connector.
===============================================================
Provides Exasol MP-relational connectivity via pyexasol/turbodbc, dual sync and async
execution protocols, query statement execution, and EXA catalog introspection.
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
from query_builder.connectors.introspection import introspect_exasol
from query_builder.connectors.registry import register_connector


class _ExasolCursorAdapter:
    """Adapts a pyexasol ExaConnection or ExaStatement into a DB-API cursor interface."""

    def __init__(self, connection: Any) -> None:
        self.conn = connection
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if hasattr(self.conn, "execute"):
            stmt = (
                self.conn.execute(clean_sql, query_params=params)
                if params
                else self.conn.execute(clean_sql)
            )
            if hasattr(stmt, "columns"):
                cols_obj = stmt.columns() if callable(stmt.columns) else stmt.columns
                cols = (
                    list(cols_obj.keys())
                    if isinstance(cols_obj, dict)
                    else list(cols_obj)
                )
                self.description = [(col,) for col in cols]
            elif hasattr(stmt, "description"):
                self.description = stmt.description
            else:
                self.description = None

            if hasattr(stmt, "fetchall"):
                self._rows = list(stmt.fetchall())
            elif hasattr(stmt, "fetchall_dict"):
                dicts = stmt.fetchall_dict()
                if dicts:
                    cols = list(dicts[0].keys())
                    self.description = [(c,) for c in cols]
                    self._rows = [[d.get(c) for c in cols] for d in dicts]
                else:
                    self._rows = []
            elif isinstance(stmt, (list, tuple)):
                self._rows = list(stmt)
            else:
                self._rows = []
        elif hasattr(self.conn, "cursor"):
            cur = self.conn.cursor()
            if params:
                cur.execute(clean_sql, params)
            else:
                cur.execute(clean_sql)
            self.description = getattr(cur, "description", None)
            self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
        else:
            self.description = None
            self._rows = []

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


@register_connector("exasol")
class ExasolConnector(BaseConnector):
    """Connector for Exasol high-performance in-memory MP-relational database."""

    dialect_name = "exasol"

    def __init__(
        self,
        schema_name: str = "PUBLIC",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pyexasol", "turbodbc"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pyexasol' (or 'turbodbc') is not installed. "
                "Install with: pip install 'query-builder-engine[exasol]'"
            )

        try:
            self._connection = driver.connect(schema=self.schema_name, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Exasol database: {exc}"
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
            adapter = _ExasolCursorAdapter(conn)
            yield adapter

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Exasol"
        info["schema_name"] = self.schema_name
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_exasol(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Exasol schema '{self.schema_name}': {exc}"
                ) from exc


@register_connector("async_exasol")
class AsyncExasolConnector(AsyncBaseConnector):
    """Asynchronous connector for Exasol analytics database."""

    dialect_name = "exasol"

    def __init__(
        self,
        schema_name: str = "PUBLIC",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.schema_name = schema_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pyexasol", "turbodbc"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pyexasol' (or 'turbodbc') is not installed. "
                "Install with: pip install 'query-builder-engine[exasol]'"
            )

        try:
            self._connection = driver.connect(schema=self.schema_name, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Exasol: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _ExasolCursorAdapter(conn)
        adapter.execute(sql, params)
        desc = adapter.description or []
        col_names = [col[0] for col in desc]
        rows = adapter.fetchall() or []
        dict_rows = [dict(zip(col_names, r)) for r in rows]
        latency_ms = (time.perf_counter() - start) * 1000.0
        return col_names, dict_rows, latency_ms
