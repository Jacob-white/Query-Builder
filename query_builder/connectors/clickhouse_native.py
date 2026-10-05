"""
ClickHouse Native High-Throughput Binary TCP Protocol Adapter Connector.
========================================================================
Provides ClickHouse connectivity via native binary TCP driver (clickhouse-driver / asynch),
dual sync and async execution protocols, statement timeouts, and system catalog introspection.
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
from query_builder.connectors.introspection import introspect_clickhouse_native
from query_builder.connectors.registry import register_connector


def _has_attr(target: Any, attr: str) -> bool:
    if hasattr(target, "_mock_children"):
        if getattr(target, "_mock_methods", None) is not None:
            return hasattr(target, attr)
        return attr in target._mock_children
    return hasattr(target, attr)


class _ClickHouseNativeCursorAdapter:
    """Adapts a clickhouse_driver Client or cursor into a DB-API cursor interface."""

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
        elif _has_attr(self.target, "execute"):
            if _has_attr(self.target, "fetchall"):
                if params:
                    self.target.execute(clean_sql, params)
                else:
                    self.target.execute(clean_sql)
                self.description = getattr(self.target, "description", None)
                self._rows = list(self.target.fetchall())
            else:
                try:
                    out = self.target.execute(
                        clean_sql, params or [], with_column_types=True
                    )
                    if (
                        isinstance(out, tuple)
                        and len(out) == 2
                        and isinstance(out[1], (list, tuple))
                    ):
                        res, col_types = out
                        self.description = [(col[0],) for col in col_types]
                        self._rows = [list(r) for r in res]
                    else:
                        self.description = [("val",)]
                        self._rows = [
                            list(r) if isinstance(r, (list, tuple)) else [r]
                            for r in (out or [])
                        ]
                except TypeError:
                    res = self.target.execute(clean_sql, params or [])
                    self.description = [("val",)]
                    self._rows = [
                        list(r) if isinstance(r, (list, tuple)) else [r] for r in res
                    ]
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


@register_connector("clickhouse_native", aliases=["ch_native", "clickhouse_tcp"])
class ClickHouseNativeConnector(BaseConnector):
    """Connector for ClickHouse high-throughput native binary TCP protocol."""

    dialect_name = "clickhouse_native"

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
        for mod_name in ("clickhouse_driver.Client", "clickhouse_driver"):
            try:
                driver = __import__(mod_name, fromlist=["Client"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'clickhouse-driver' is not installed. "
                "Install with: pip install 'query-builder-engine[clickhouse-native]'"
            )

        try:
            client_cls = getattr(driver, "Client", None)
            if client_cls is not None:
                self._connection = client_cls(database=self.database, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to ClickHouse Native: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield _ClickHouseNativeCursorAdapter(self._cursor)
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield _ClickHouseNativeCursorAdapter(cur)
            finally:
                if hasattr(cur, "close"):
                    with contextlib.suppress(Exception):
                        cur.close()
        else:
            yield _ClickHouseNativeCursorAdapter(conn)

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        seconds = max(1, timeout_ms // 1000)
        cursor.execute(f"SET max_execution_time = {seconds};")

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur, contextlib.suppress(Exception):
            cur.execute("SELECT version();")
            rows = cur.fetchall() if hasattr(cur, "fetchall") else []
            if rows and len(rows) > 0 and len(rows[0]) > 0 and rows[0][0]:
                info["engine_version"] = f"ClickHouse Native {rows[0][0]}".strip()
        info["database"] = self.database
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_clickhouse_native(
                    cur,
                    database=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect ClickHouse Native database '{self.database}': {exc}"
                ) from exc


@register_connector("async_clickhouse_native", aliases=["async_ch_native"])
class AsyncClickHouseNativeConnector(AsyncBaseConnector):
    """Asynchronous connector for ClickHouse native binary TCP protocol."""

    dialect_name = "clickhouse_native"

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
        for mod_name in ("asynch", "clickhouse_driver.Client", "clickhouse_driver"):
            try:
                driver = __import__(mod_name, fromlist=["connect", "Client"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'asynch' or 'clickhouse-driver' is not installed. "
                "Install with: pip install 'query-builder-engine[clickhouse-native]'"
            )

        try:
            if hasattr(driver, "connect"):
                res = driver.connect(database=self.database, **self.config)
                self._connection = await res if hasattr(res, "__await__") else res
            elif hasattr(driver, "Client"):
                self._connection = driver.Client(database=self.database, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to ClickHouse Native: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _ClickHouseNativeCursorAdapter(conn)
        try:
            adapter.execute(sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            dict_rows = [dict(zip(col_names, r)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            adapter.close()

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        adapter = _ClickHouseNativeCursorAdapter(conn)
        try:
            return introspect_clickhouse_native(
                adapter, database=self.database, filter_sensitive=filter_sensitive
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect ClickHouse Native database '{self.database}': {exc}"
            ) from exc
