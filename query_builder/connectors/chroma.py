"""
ChromaDB In-Process & Server AI Vector Database Connector.
==========================================================
Provides ChromaDB connectivity via chromadb client,
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
from query_builder.connectors.introspection import introspect_chroma
from query_builder.connectors.registry import register_connector


class _ChromaCursorAdapter:
    """Adapts a ChromaDB client or collection into a standard DB-API cursor interface."""

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
        elif clean_sql.startswith("list_collections") and hasattr(
            self.conn, "list_collections"
        ):
            cols = self.conn.list_collections()
            self.description = [("collection_name",)]
            self._rows = [[getattr(c, "name", str(c))] for c in cols]
        elif hasattr(self.conn, "get"):
            res = self.conn.get(limit=10)
            ids = res.get("ids", [])
            docs = res.get("documents", [])
            metas = res.get("metadatas", [])
            self.description = [("id",), ("document",), ("metadata",)]
            self._rows = [
                [
                    ids[i] if i < len(ids) else None,
                    docs[i] if i < len(docs) else None,
                    metas[i] if i < len(metas) else None,
                ]
                for i in range(max(len(ids), len(docs), len(metas)))
            ]
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


@register_connector("chroma", aliases=["chromadb"])
class ChromaConnector(BaseConnector):
    """Connector for ChromaDB embedding database."""

    dialect_name = "chroma"

    def __init__(
        self,
        path: str | None = None,
        host: str | None = None,
        port: int = 8000,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.path = path
        self.host = host
        self.port = port

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import chromadb
        except ImportError as err:
            raise DriverNotInstalledError(
                "'chromadb' is not installed. "
                "Install with: pip install 'query-builder-engine[chroma]'"
            ) from err

        try:
            if self.host:
                self._connection = chromadb.HttpClient(
                    host=self.host, port=self.port, **self.config
                )
            elif self.path:
                self._connection = chromadb.PersistentClient(
                    path=self.path, **self.config
                )
            else:
                self._connection = chromadb.Client(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to ChromaDB: {exc}"
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
            adapter = _ChromaCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "heartbeat"):
            conn.heartbeat()
        elif hasattr(conn, "list_collections"):
            conn.list_collections()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "ChromaDB",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_chroma(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Chroma schema: {exc}"
                ) from exc


@register_connector("async_chroma", aliases=["async_chromadb"])
class AsyncChromaConnector(AsyncBaseConnector):
    """Asynchronous connector for ChromaDB embedding database."""

    dialect_name = "chroma"

    def __init__(
        self,
        path: str | None = None,
        host: str | None = None,
        port: int = 8000,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.path = path
        self.host = host
        self.port = port

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import chromadb
        except ImportError as err:
            raise DriverNotInstalledError(
                "'chromadb' is not installed. "
                "Install with: pip install 'query-builder-engine[chroma]'"
            ) from err

        try:
            if hasattr(chromadb, "AsyncHttpClient") and self.host:
                self._connection = await chromadb.AsyncHttpClient(
                    host=self.host, port=self.port, **self.config
                )
            elif self.host:
                self._connection = chromadb.HttpClient(
                    host=self.host, port=self.port, **self.config
                )
            elif self.path:
                self._connection = chromadb.PersistentClient(
                    path=self.path, **self.config
                )
            else:
                self._connection = chromadb.Client(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to ChromaDB: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _ChromaCursorAdapter(conn)

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
        if hasattr(conn, "heartbeat"):
            conn.heartbeat()
        elif hasattr(conn, "list_collections"):
            conn.list_collections()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "ChromaDB",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = conn.cursor() if hasattr(conn, "cursor") else _ChromaCursorAdapter(conn)
        try:
            return introspect_chroma(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Chroma schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()


ChromaDBConnector = ChromaConnector
AsyncChromaDBConnector = AsyncChromaConnector
