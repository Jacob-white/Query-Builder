"""
Azure Cosmos DB SQL API Database Connector.
===========================================
Provides Azure Cosmos DB SQL API connectivity via azure-cosmos SDK,
dual sync and async execution protocols, cursor adaptation, and container introspection.

A Cosmos query always runs against ONE container.  The container is taken from the
statement's ``FROM <container> [alias]`` (Cosmos itself treats that name only as an alias
for the container root, so the statement is sent unchanged).  A client without a container
name in the statement cannot run a query and raises instead of returning "no rows".
"""

from __future__ import annotations

import contextlib
import re
import time
from typing import Any

from query_builder.connectors._native_readonly import assert_read_only
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
    QueryExecutionError,
)
from query_builder.connectors.introspection import (
    cosmos_snapshot,
    introspect_cosmosdb,
)
from query_builder.connectors.registry import register_connector

_FROM_CONTAINER = re.compile(
    r'\bFROM\s+(?:"([^"]+)"|`([^`]+)`|\[([^\]]+)\]|([A-Za-z_][\w.\-]*))',
    re.IGNORECASE,
)


def container_of(sql: str) -> str | None:
    """Container named by the first ``FROM`` of ``sql`` (None when there is none)."""
    m = _FROM_CONTAINER.search(sql)
    return next((g for g in m.groups() if g), None) if m else None


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return str(value)


class _CosmosDBCursorAdapter:
    """Adapts an Azure Cosmos DB client or container query execution into a DB-API cursor interface."""

    def __init__(
        self,
        client_or_container: Any,
        database: str = "default",
        read_only: bool = True,
    ) -> None:
        self.target = client_or_container
        self.database = database
        self.read_only = read_only
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def prepare(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[str, list[dict[str, Any]]]:
        """Clean statement and ``@p<i>`` parameters (the compiler's placeholder is ``@param``)."""
        clean_sql = sql.strip().rstrip(";").strip()
        if clean_sql.upper() in ("SELECT 1", "SELECT 1;"):
            clean_sql = "SELECT VALUE 1"
        if self.read_only:
            assert_read_only(clean_sql, "cosmos", "Cosmos DB")
        cosmos_params: list[dict[str, Any]] = []
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
        return clean_sql, cosmos_params

    def container(self, sql: str) -> Any:
        """The container proxy ``sql`` runs against."""
        if hasattr(self.target, "query_items"):  # already a container client
            return self.target
        name = container_of(sql)
        if name is None or not hasattr(self.target, "get_database_client"):
            raise QueryExecutionError(
                "A Cosmos DB query needs a container: write FROM <container> [alias]"
            )
        return self.target.get_database_client(self.database).get_container_client(name)

    def load(self, items: list[Any]) -> None:
        items = [_plain(i) for i in items]
        if items and isinstance(items[0], dict):
            col_names = list(
                dict.fromkeys(k for i in items if isinstance(i, dict) for k in i)
            )
            self.description = [(col,) for col in col_names]
            self._rows = [[item.get(c) for c in col_names] for item in items]
        else:
            self.description = [("value",)] if items else []
            self._rows = [[item] for item in items]

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql, cosmos_params = self.prepare(sql, params)
        if hasattr(self.target, "query_items") or hasattr(
            self.target, "get_database_client"
        ):
            container = self.container(clean_sql)
            self.load(
                list(
                    container.query_items(
                        query=clean_sql,
                        parameters=cosmos_params if cosmos_params else None,
                        enable_cross_partition_query=True,
                    )
                )
            )
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


def _import_driver() -> Any:
    for mod_name in ("azure.cosmos", "azure.cosmos.cosmos_client"):
        try:
            return __import__(mod_name, fromlist=["CosmosClient"])
        except ImportError:
            continue
    raise DriverNotInstalledError(
        "'azure-cosmos' is not installed. "
        "Install with: pip install 'query-builder-engine[cosmosdb]'"
    )


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

        driver = _import_driver()
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

    def _read_only(self) -> bool:
        sec = getattr(self, "security", None)
        return sec is None or sec.execution.enforce_read_only_session

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
            adapter = _CosmosDBCursorAdapter(
                conn, database=self.database, read_only=self._read_only()
            )
            yield adapter

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self._cursor if self._cursor is not None else self.connect()
        if hasattr(conn, "get_database_client"):
            # a Cosmos query needs a container, so health = the database can be read
            conn.get_database_client(self.database).read()
        elif self._cursor is not None or hasattr(conn, "cursor"):
            with self.get_cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        info = {
            "status": "healthy",
            "dialect": self.dialect_name,
            "latency_ms": round((time.perf_counter() - start) * 1000.0, 2),
        }
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
        # the awaitable client lives in azure.cosmos.aio; fall back to the blocking module
        for mod_name in ("azure.cosmos.aio", "azure.cosmos", "azure.cosmos.cosmos_client"):
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

    def _read_only(self) -> bool:
        sec = getattr(self, "security", None)
        return sec is None or sec.execution.enforce_read_only_session

    async def _query(
        self, adapter: _CosmosDBCursorAdapter, sql: str, params: list[Any] | None
    ) -> None:
        clean_sql, cosmos_params = adapter.prepare(sql, params)
        container = adapter.container(clean_sql)
        items = container.query_items(
            query=clean_sql, parameters=cosmos_params if cosmos_params else None
        )
        if hasattr(items, "__aiter__"):
            adapter.load([i async for i in items])
        else:  # the blocking SDK object: a plain iterator
            adapter.load(list(items))

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _CosmosDBCursorAdapter(
            conn, database=self.database, read_only=self._read_only()
        )
        try:
            if hasattr(conn, "query_items") or hasattr(conn, "get_database_client"):
                await self._query(adapter, sql, params)
            else:
                adapter.execute(sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            adapter.close()

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        if hasattr(conn, "get_database_client"):
            res = conn.get_database_client(self.database).read()
            if hasattr(res, "__await__"):
                await res
        else:
            await self.execute_raw("SELECT 1")
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Azure Cosmos DB",
            "database": self.database,
            "latency_ms": round((time.perf_counter() - start) * 1000.0, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        try:
            if not hasattr(conn, "get_database_client"):
                return introspect_cosmosdb(
                    conn, database=self.database, filter_sensitive=filter_sensitive
                )
            db = conn.get_database_client(self.database)
            samples: dict[str, list[dict[str, Any]]] = {}
            names = []
            listing = db.list_containers()
            if hasattr(listing, "__aiter__"):
                names = [c async for c in listing]
            else:
                names = list(listing)
            for item in names:
                c_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
                if not c_id:
                    continue
                query = db.get_container_client(c_id).query_items(
                    query="SELECT * FROM c OFFSET 0 LIMIT 100"
                )
                if hasattr(query, "__aiter__"):
                    samples[c_id] = [d async for d in query]
                else:
                    samples[c_id] = list(query)
            return cosmos_snapshot(samples, filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Azure Cosmos DB database '{self.database}': {exc}"
            ) from exc


AsyncAzureCosmosDBConnector = AsyncCosmosDBConnector
