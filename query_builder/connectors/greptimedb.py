"""
GreptimeDB Cloud-Native Distributed Time-Series Database Connector.
===================================================================
Provides GreptimeDB time-series query execution, MySQL/PostgreSQL wire protocol
compatibility, dual sync and async execution protocols, and schema introspection.
"""

from __future__ import annotations

import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_greptimedb
from query_builder.connectors.registry import register_connector


@register_connector("greptimedb", aliases=["greptime"])
class GreptimeDBConnector(BaseConnector):
    """Connector for GreptimeDB distributed time-series database."""

    dialect_name = "greptimedb"

    def __init__(
        self,
        schema_name: str = "public",
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
        for mod_name in ("greptimedb", "psycopg2", "psycopg", "pymysql"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'greptimedb' (or 'psycopg2' / 'pymysql') is not installed. "
                "Install with: pip install 'query-builder-engine[greptimedb]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to GreptimeDB: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "GreptimeDB"
        info["schema_name"] = self.schema_name
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_greptimedb(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect GreptimeDB schema '{self.schema_name}': {exc}"
                ) from exc


@register_connector("async_greptimedb", aliases=["async_greptime"])
class AsyncGreptimeDBConnector(AsyncBaseConnector):
    """Asynchronous connector for GreptimeDB time-series database."""

    dialect_name = "greptimedb"

    def __init__(
        self,
        schema_name: str = "public",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.schema_name = schema_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("greptimedb", "psycopg", "asyncpg", "pymysql"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'greptimedb' (or 'psycopg' / 'pymysql') is not installed. "
                "Install with: pip install 'query-builder-engine[greptimedb]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to GreptimeDB: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        cur = conn.cursor()
        try:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            desc = cur.description or []
            col_names = [col[0] for col in desc]
            rows = cur.fetchall() or []
            dict_rows = [dict(zip(col_names, r)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            cur.close()
