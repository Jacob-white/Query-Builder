"""
Azure Cosmos DB SQL API Database Connector.
===========================================
Provides Azure Cosmos DB SQL API connectivity via azure-cosmos SDK,
dual sync and async execution protocols, cursor adaptation, and container introspection.
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
from query_builder.connectors.introspection import introspect_cosmosdb
from query_builder.connectors.registry import register_connector


class _CosmosDBCursorAdapter:
    """Adapts an Azure Cosmos DB client or container query execution into a DB-API cursor interface."""

    def __init__(self, client_or_container: Any, database: str = "default") -> None:
        self.target = client_or_container
        self.database = database
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if clean_sql.upper() in ("SELECT 1", "SELECT 1;"):
            clean_sql = "SELECT VALUE 1"
        cosmos_params = []
        if params:
            parts = clean_sql.split("@param")
            if len(parts) - 1 == len(params):
                rebuilt = []
                for i, part in enumerate(parts[:-1]):
                    rebuilt.append(part)
                    rebuilt.append(f"@p{i}")
                rebuilt.append(parts[-1])
                clean_sql = "".join(rebuilt)
            cosmos_params = [
                {"name": f"@p{i}", "value": p} for i, p in enumerate(params)
            ]

        if hasattr(self.target, "query_items"):
            # Container client
            items = list(
                self.target.query_items(
                    query=clean_sql,
                    parameters=cosmos_params if cosmos_params else None,
                    enable_cross_partition_query=True,
                )
            )
            if items and isinstance(items[0], dict):
                col_names = list(items[0].keys())
                self.description = [(col,) for col in col_names]
                self._rows = [[item.get(c) for c in col_names] for item in items]
            else:
                self.description = [("value",)] if items else []
                self._rows = [[item] for item in items]
        elif hasattr(self.target, "execute"):
            if params:
                self.target.execute(clean_sql, params)
            else:
                self.target.execute(clean_sql)
            self.description = getattr(self.target, "description", None)
            self._rows = (
                list(self.target.fetchall()) if hasattr(self.target, "fetchall") else []
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


@register_connector("cosmosdb", aliases=["azure_cosmos"])
class CosmosDBConnector(BaseConnector):
    """Connector for Azure Cosmos DB SQL API database engine."""

    dialect_name = "cosmosdb"

    def __init__(
        self,
        endpoint: str = "https://localhost:8081",
        key: str = "",
        database: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.endpoint = endpoint
        self.key = key
        self.database = database
        self.schema_name = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("azure.cosmos", "azure.cosmos.cosmos_client"):
            try:
                driver = __import__(mod_name, fromlist=["CosmosClient"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'azure-cosmos' is not installed. "
                "Install with: pip install 'query-builder-engine[cosmosdb]'"
            )

        try:
            client_cls = getattr(driver, "CosmosClient", None) or driver
            self._connection = client_cls(
                self.endpoint, credential=self.key, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Azure Cosmos DB at '{self.endpoint}': {exc}"
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
            adapter = _CosmosDBCursorAdapter(conn, database=self.database)
            yield adapter

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Azure Cosmos DB"
        info["database"] = self.database
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_cosmosdb(
                    cur,
                    database=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Azure Cosmos DB database '{self.database}': {exc}"
                ) from exc


AzureCosmosDBConnector = CosmosDBConnector


@register_connector("async_cosmosdb", aliases=["async_azure_cosmos"])
class AsyncCosmosDBConnector(AsyncBaseConnector):
    """Asynchronous connector for Azure Cosmos DB SQL API database."""

    dialect_name = "cosmosdb"

    def __init__(
        self,
        endpoint: str = "https://localhost:8081",
        key: str = "",
        database: str = "default",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.endpoint = endpoint
        self.key = key
        self.database = database
        self.schema_name = database

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("azure.cosmos", "azure.cosmos.cosmos_client"):
            try:
                driver = __import__(mod_name, fromlist=["CosmosClient"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'azure-cosmos' is not installed. "
                "Install with: pip install 'query-builder-engine[cosmosdb]'"
            )

        try:
            client_cls = getattr(driver, "CosmosClient", None) or driver
            self._connection = client_cls(
                self.endpoint, credential=self.key, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Azure Cosmos DB: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _CosmosDBCursorAdapter(conn, database=self.database)
        try:
            adapter.execute(sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            adapter.close()


AsyncAzureCosmosDBConnector = AsyncCosmosDBConnector
