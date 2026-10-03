"""
Materialize Streaming SQL Database Connector.
=============================================
Provides Materialize streaming SQL connectivity, cluster activation,
dual sync and async execution protocols, and materialized view schema introspection.
"""

from __future__ import annotations

import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_information_schema
from query_builder.connectors.postgres import PostgresConnector
from query_builder.connectors.registry import register_connector


@register_connector("materialize", aliases=["mz"])
class MaterializeConnector(PostgresConnector):
    """Connector for Materialize streaming SQL engine."""

    dialect_name = "materialize"

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        schema_name: str = "public",
        cluster: str | None = None,
        **config: Any,
    ) -> None:
        super().__init__(
            connection=connection,
            cursor=cursor,
            schema_name=schema_name,
            **config,
        )
        self.cluster = cluster

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("psycopg", "psycopg2"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'psycopg' nor 'psycopg2' is installed. "
                "Install with: pip install 'query-builder-engine[materialize]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            if self.cluster:
                with self.get_cursor() as cur:
                    cur.execute(f"SET cluster = {self.cluster};")
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Materialize: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Materialize Streaming SQL"
        if self.cluster:
            info["mz_cluster"] = self.cluster
        return info

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET statement_timeout = '{int(timeout_ms)}ms';")

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
                    f"Failed to introspect Materialize schema '{self.schema_name}': {exc}"
                ) from exc


@register_connector("async_materialize", aliases=["async_mz"])
class AsyncMaterializeConnector(AsyncBaseConnector):
    """Asynchronous connector for Materialize streaming database."""

    dialect_name = "materialize"

    def __init__(
        self,
        connection: Any = None,
        schema_name: str = "public",
        cluster: str | None = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.schema_name = schema_name
        self.cluster = cluster

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("psycopg", "psycopg2"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'psycopg' nor 'psycopg2' is installed. "
                "Install with: pip install 'query-builder-engine[materialize]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Materialize: {exc}"
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
            col_names = [c[0] for c in desc]
            rows = cur.fetchall() or []
            dict_rows = [dict(zip(col_names, r)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            cur.close()
