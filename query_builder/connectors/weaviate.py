"""
Weaviate Modular Vector Database & Knowledge Graph Connector.
=============================================================
Provides Weaviate connectivity via official weaviate-client v4+,
dual sync and async execution protocols, and collection schema introspection.
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
from query_builder.connectors.introspection import introspect_weaviate
from query_builder.connectors.registry import register_connector


class _WeaviateCursorAdapter:
    """Adapts a WeaviateClient into a DB-API cursor interface."""

    def __init__(self, connection: Any) -> None:
        self.conn = connection
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if hasattr(self.conn, "cursor"):
            cur = self.conn.cursor()
            try:
                if params:
                    cur.execute(clean_sql, params)
                else:
                    cur.execute(clean_sql)
                self.description = getattr(cur, "description", None)
                self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        elif clean_sql.startswith("collections.list_all") and hasattr(
            self.conn, "collections"
        ):
            classes = self.conn.collections.list_all()
            names = (
                list(classes.keys())
                if isinstance(classes, dict)
                else [str(c) for c in classes]
            )
            self.description = [("class_name",)]
            self._rows = [[str(name)] for name in names]
        elif hasattr(self.conn, "graphql") and hasattr(self.conn.graphql, "raw_query"):
            res = self.conn.graphql.raw_query(clean_sql)
            data = getattr(res, "get", lambda _: {})("data", {})
            self.description = [("data",)]
            self._rows = [[str(data)]]
        elif hasattr(self.conn, "execute"):
            res = (
                self.conn.execute(clean_sql, params)
                if params
                else self.conn.execute(clean_sql)
            )
            self.description = getattr(res, "description", None)
            if hasattr(res, "fetchall"):
                self._rows = list(res.fetchall())
            elif isinstance(res, (list, tuple)):
                self._rows = list(res)
            else:
                self._rows = []
        else:
            self.description = None
            self._rows = []

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def fetchmany(self, size: int = 1) -> list[list[Any]]:
        if not self._rows:
            return []
        res = self._rows[:size]
        self._rows = self._rows[size:]
        return res

    def close(self) -> None:
        self._rows = []


@register_connector("weaviate", aliases=["weaviate_db", "weaviate_vector"])
class WeaviateConnector(BaseConnector):
    """Connector for Weaviate modular vector database and knowledge graph."""

    dialect_name = "weaviate"

    def __init__(
        self,
        url: str = "http://localhost:8080",
        api_key: str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.url = url
        self.api_key = api_key

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("weaviate", "weaviate.client"):
            try:
                driver = __import__(
                    mod_name,
                    fromlist=["connect_to_local", "connect_to_custom", "Client"],
                )
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'weaviate-client' is not installed. "
                "Install with: pip install 'query-builder-engine[weaviate]'"
            )

        try:
            if hasattr(driver, "connect_to_custom"):
                self._connection = driver.connect_to_custom(
                    http_host=self.url, **self.config
                )
            elif hasattr(driver, "Client"):
                self._connection = driver.Client(url=self.url, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Weaviate: {exc}"
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
            adapter = _WeaviateCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "is_ready"):
            conn.is_ready()
        elif hasattr(conn, "collections"):
            conn.collections.list_all()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Weaviate",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_weaviate(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Weaviate schema: {exc}"
                ) from exc


@register_connector(
    "async_weaviate", aliases=["async_weaviate_db", "async_weaviate_vector"]
)
class AsyncWeaviateConnector(AsyncBaseConnector):
    """Asynchronous connector for Weaviate vector database."""

    dialect_name = "weaviate"

    def __init__(
        self,
        url: str = "http://localhost:8080",
        api_key: str | None = None,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.url = url
        self.api_key = api_key

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("weaviate", "weaviate.client"):
            try:
                driver = __import__(
                    mod_name, fromlist=["use_async", "connect_to_custom", "Client"]
                )
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'weaviate-client' is not installed. "
                "Install with: pip install 'query-builder-engine[weaviate]'"
            )

        try:
            if hasattr(driver, "connect_to_custom"):
                self._connection = driver.connect_to_custom(
                    http_host=self.url, **self.config
                )
            elif hasattr(driver, "Client"):
                self._connection = driver.Client(url=self.url, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Weaviate: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _WeaviateCursorAdapter(conn)

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
            if hasattr(cur, "close"):
                cur.close()

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        if hasattr(conn, "is_ready"):
            res = conn.is_ready()
            if hasattr(res, "__await__"):
                await res
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Weaviate",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = conn.cursor() if hasattr(conn, "cursor") else _WeaviateCursorAdapter(conn)
        try:
            return introspect_weaviate(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Weaviate schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
