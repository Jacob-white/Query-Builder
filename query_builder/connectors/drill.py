"""
Apache Drill Distributed Schema-Free SQL Engine Connector.
==========================================================
Provides Apache Drill connectivity via pydrill / REST / DB-API, dual sync
and async execution protocols, cursor adapters, and catalog schema introspection.
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
from query_builder.connectors.introspection import introspect_drill
from query_builder.connectors.registry import register_connector


def _has_attr(target: Any, attr: str) -> bool:
    if hasattr(target, "_mock_children"):
        if getattr(target, "_mock_methods", None) is not None:
            return hasattr(target, attr)
        return attr in target._mock_children
    return hasattr(target, attr)


class _DrillCursorAdapter:
    """Adapts a PyDrill client or DB-API connection into a standardized cursor interface."""

    def __init__(self, client_or_cursor: Any) -> None:
        self.target = client_or_cursor
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if _has_attr(self.target, "cursor") and not _has_attr(self.target, "fetchall"):
            cur = self.target.cursor()
            try:
                if params:
                    cur.execute(clean_sql, params)
                else:
                    cur.execute(clean_sql)
                self.description = getattr(cur, "description", None)
                self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
            finally:
                with contextlib.suppress(Exception):
                    cur.close()
        elif _has_attr(self.target, "query"):
            # pydrill.client.PyDrill
            res = self.target.query(clean_sql)
            columns = getattr(res, "columns", [])
            self.description = [(str(col),) for col in columns]
            raw_rows = getattr(res, "rows", [])
            self._rows = [
                [
                    row.get(col)
                    if isinstance(row, dict)
                    else (
                        row[i]
                        if isinstance(row, (list, tuple)) and i < len(row)
                        else row
                    )
                    for i, col in enumerate(columns)
                ]
                for row in raw_rows
            ]
        elif _has_attr(self.target, "execute") or _has_attr(self.target, "fetchall"):
            if params:
                self.target.execute(clean_sql, params)
            else:
                self.target.execute(clean_sql)
            self.description = getattr(self.target, "description", None)
            self._rows = (
                list(self.target.fetchall()) if hasattr(self.target, "fetchall") else []
            )
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


@register_connector("drill", aliases=["apache_drill", "pydrill"])
class DrillConnector(BaseConnector):
    """Connector for Apache Drill distributed schema-free SQL engine."""

    dialect_name = "drill"

    def __init__(
        self,
        schema_name: str = "dfs.default",
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
        for mod_name in ("pydrill.client", "pydrill"):
            try:
                driver = __import__(mod_name, fromlist=["Drill", "PyDrill"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pydrill' is not installed. "
                "Install with: pip install 'query-builder-engine[drill]'"
            )

        try:
            drill_cls = getattr(driver, "PyDrill", getattr(driver, "Drill", None))
            if drill_cls is not None:
                self._connection = drill_cls(**self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Apache Drill: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield _DrillCursorAdapter(self._cursor)
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield _DrillCursorAdapter(cur)
            finally:
                if hasattr(cur, "close"):
                    with contextlib.suppress(Exception):
                        cur.close()
        else:
            yield _DrillCursorAdapter(conn)

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        seconds = max(1, timeout_ms // 1000)
        with contextlib.suppress(Exception):
            cursor.execute(
                f"ALTER SESSION SET `exec.query.max__idle__seconds` = {seconds};"
            )

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur, contextlib.suppress(Exception):
            cur.execute("SELECT version FROM sys.version;")
            rows = cur.fetchall() if hasattr(cur, "fetchall") else []
            if rows and len(rows) > 0:
                ver = (
                    rows[0][0]
                    if isinstance(rows[0], (tuple, list))
                    else (
                        rows[0].get("version", "")
                        if isinstance(rows[0], dict)
                        else str(rows[0])
                    )
                )
                if ver:
                    info["engine_version"] = f"Apache Drill {ver}".strip()
        info["schema_name"] = self.schema_name
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_drill(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Apache Drill schema '{self.schema_name}': {exc}"
                ) from exc


ApacheDrillConnector = DrillConnector


@register_connector("async_drill", aliases=["async_apache_drill"])
class AsyncDrillConnector(AsyncBaseConnector):
    """Asynchronous connector for Apache Drill distributed SQL engine."""

    dialect_name = "drill"

    def __init__(
        self,
        schema_name: str = "dfs.default",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.schema_name = schema_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pydrill.client", "pydrill"):
            try:
                driver = __import__(mod_name, fromlist=["Drill", "PyDrill"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pydrill' is not installed. "
                "Install with: pip install 'query-builder-engine[drill]'"
            )

        try:
            drill_cls = getattr(driver, "Drill", getattr(driver, "PyDrill", None))
            if drill_cls is not None:
                self._connection = drill_cls(**self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Apache Drill: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _DrillCursorAdapter(conn)
        adapter.execute(sql, params)
        desc = adapter.description or []
        col_names = [col[0] for col in desc]
        rows = adapter.fetchall() or []
        dict_rows = [dict(zip(col_names, r)) for r in rows]
        latency_ms = (time.perf_counter() - start) * 1000.0
        return col_names, dict_rows, latency_ms

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        adapter = _DrillCursorAdapter(conn)
        try:
            return introspect_drill(
                adapter,
                schema_name=self.schema_name,
                filter_sensitive=filter_sensitive,
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Apache Drill schema '{self.schema_name}': {exc}"
            ) from exc


AsyncApacheDrillConnector = AsyncDrillConnector
