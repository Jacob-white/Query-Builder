"""
PrestoDB Distributed SQL Query Engine Connector.
================================================
Provides PrestoDB connectivity, dual sync and async execution protocols,
statement timeout isolation, and schema introspection.
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
from query_builder.connectors.introspection import introspect_information_schema
from query_builder.connectors.registry import register_connector


@register_connector("prestodb", aliases=["presto"])
class PrestoDBConnector(BaseConnector):
    """Connector for PrestoDB distributed SQL query engine."""

    dialect_name = "presto"

    def __init__(
        self,
        catalog: str = "memory",
        schema_name: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.catalog = catalog
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("prestodb.dbapi", "prestodb", "trino.dbapi", "trino"):
            try:
                driver = __import__(mod_name, fromlist=["dbapi"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'prestodb' (or 'trino') is not installed. "
                "Install with: pip install 'query-builder-engine[prestodb]'"
            )

        try:
            self._connection = driver.connect(
                catalog=self.catalog, schema=self.schema_name, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to PrestoDB: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute("SELECT version();")
            row = cur.fetchone()
            if row:
                info["engine_version"] = row[0]
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_information_schema(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect PrestoDB schema '{self.schema_name}': {exc}"
                ) from exc


PrestoConnector = PrestoDBConnector


@register_connector("async_prestodb", aliases=["async_presto"])
class AsyncPrestoDBConnector(AsyncBaseConnector):
    """Asynchronous connector for PrestoDB query engine."""

    dialect_name = "presto"

    def __init__(
        self,
        catalog: str = "memory",
        schema_name: str = "default",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.catalog = catalog
        self.schema_name = schema_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection
        driver = None
        for mod_name in ("prestodb.dbapi", "prestodb", "trino.dbapi", "trino"):
            try:
                driver = __import__(mod_name, fromlist=["dbapi"])
                break
            except ImportError:
                continue
        if driver is None:
            raise DriverNotInstalledError(
                "'prestodb' (or 'trino') is not installed. "
                "Install with: pip install 'query-builder-engine[prestodb]'"
            )
        try:
            self._connection = driver.connect(
                catalog=self.catalog, schema=self.schema_name, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to PrestoDB: {exc}"
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
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            cur.close()


AsyncPrestoConnector = AsyncPrestoDBConnector
