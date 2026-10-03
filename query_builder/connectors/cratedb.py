"""
CrateDB Distributed SQL Database Connector.
===========================================
Provides CrateDB distributed query connectivity, timeout management,
dual sync and async execution protocols, and Lucene-backed schema introspection.
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
from query_builder.connectors.introspection import introspect_cratedb
from query_builder.connectors.registry import register_connector


@register_connector("cratedb", aliases=["crate"])
class CrateDBConnector(BaseConnector):
    """Connector for CrateDB distributed SQL database."""

    dialect_name = "cratedb"

    def __init__(
        self,
        schema_name: str = "doc",
        servers: list[str] | str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.schema_name = schema_name
        self.servers = servers

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("crate.client", "psycopg2", "psycopg"):
            try:
                driver = __import__(mod_name, fromlist=["client"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'crate' nor 'psycopg2' is installed. "
                "Install with: pip install 'query-builder-engine[cratedb]'"
            )

        try:
            connect_args = dict(self.config)
            if self.servers:
                connect_args["servers"] = self.servers
            if self.schema_name:
                connect_args["schema"] = self.schema_name
            self._connection = driver.connect(**connect_args)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to CrateDB: {exc}") from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "CrateDB Distributed Database"
        return info

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET statement_timeout = {int(timeout_ms)};")

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_cratedb(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect CrateDB schema '{self.schema_name}': {exc}"
                ) from exc


CrateConnector = CrateDBConnector


@register_connector("async_cratedb", aliases=["async_crate"])
class AsyncCrateDBConnector(AsyncBaseConnector):
    """Asynchronous connector for CrateDB distributed database."""

    dialect_name = "cratedb"

    def __init__(
        self,
        schema_name: str = "doc",
        servers: list[str] | str | None = None,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.schema_name = schema_name
        self.servers = servers

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("crate.client", "psycopg2", "psycopg"):
            try:
                driver = __import__(mod_name, fromlist=["client"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'crate' nor 'psycopg2' is installed. "
                "Install with: pip install 'query-builder-engine[cratedb]'"
            )

        try:
            connect_args = dict(self.config)
            if self.servers:
                connect_args["servers"] = self.servers
            if self.schema_name:
                connect_args["schema"] = self.schema_name
            self._connection = driver.connect(**connect_args)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to CrateDB: {exc}"
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


AsyncCrateConnector = AsyncCrateDBConnector
