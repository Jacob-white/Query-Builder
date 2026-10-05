"""
Pinecone Serverless Vector Database Connector.
==============================================
Provides Pinecone vector search connectivity via official pinecone client,
dual sync and async execution protocols, and index schema introspection.
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
from query_builder.connectors.introspection import introspect_pinecone
from query_builder.connectors.registry import register_connector


class _PineconeCursorAdapter:
    """Adapts a Pinecone Index / Client connection into a DB-API cursor interface."""

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
        elif clean_sql.startswith("list_indexes") and hasattr(
            self.conn, "list_indexes"
        ):
            indexes = self.conn.list_indexes()
            idx_list = (
                getattr(indexes, "names", lambda: indexes)()
                if callable(getattr(indexes, "names", None))
                else getattr(indexes, "names", indexes)
            )
            if isinstance(idx_list, list):
                names = [getattr(i, "name", str(i)) for i in idx_list]
            elif isinstance(indexes, list):
                names = [getattr(i, "name", str(i)) for i in indexes]
            else:
                names = [str(indexes)]
            self.description = [("index_name",)]
            self._rows = [[str(name)] for name in names]
        elif hasattr(self.conn, "query"):
            res = self.conn.query(
                vector=params or [0.0] * 8, top_k=10, include_metadata=True
            )
            matches = (
                res.get("matches", [])
                if isinstance(res, dict)
                else getattr(res, "matches", [])
            )
            self.description = [("id",), ("score",), ("metadata",)]
            self._rows = [
                [
                    getattr(m, "id", m.get("id") if isinstance(m, dict) else str(m)),
                    getattr(m, "score", m.get("score") if isinstance(m, dict) else 0.0),
                    getattr(
                        m,
                        "metadata",
                        m.get("metadata") if isinstance(m, dict) else {},
                    ),
                ]
                for m in matches
            ]
        elif hasattr(self.conn, "describe_index_stats"):
            stats = self.conn.describe_index_stats()
            self.description = [("dimension",), ("total_vector_count",)]
            self._rows = [
                [stats.get("dimension", 0), stats.get("total_vector_count", 0)]
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


@register_connector("pinecone", aliases=["pinecone_db"])
class PineconeConnector(BaseConnector):
    """Connector for Pinecone managed vector database."""

    dialect_name = "pinecone"

    def __init__(
        self,
        api_key: str | None = None,
        index_name: str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.api_key = api_key
        self.index_name = index_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pinecone", "pinecone_client"):
            try:
                driver = __import__(mod_name, fromlist=["Pinecone", "init"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pinecone' is not installed. "
                "Install with: pip install 'query-builder-engine[pinecone]'"
            )

        try:
            if hasattr(driver, "Pinecone"):
                pc = driver.Pinecone(api_key=self.api_key, **self.config)
                if self.index_name and hasattr(pc, "Index"):
                    self._connection = pc.Index(self.index_name)
                else:
                    self._connection = pc
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Pinecone: {exc}"
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
            adapter = _PineconeCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "list_indexes"):
            conn.list_indexes()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Pinecone",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_pinecone(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Pinecone schema: {exc}"
                ) from exc


@register_connector("async_pinecone", aliases=["async_pinecone_db"])
class AsyncPineconeConnector(AsyncBaseConnector):
    """Asynchronous connector for Pinecone vector database."""

    dialect_name = "pinecone"

    def __init__(
        self,
        api_key: str | None = None,
        index_name: str | None = None,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.api_key = api_key
        self.index_name = index_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pinecone", "pinecone_client"):
            try:
                driver = __import__(mod_name, fromlist=["Pinecone", "init"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pinecone' is not installed. "
                "Install with: pip install 'query-builder-engine[pinecone]'"
            )

        try:
            if hasattr(driver, "Pinecone"):
                pc = driver.Pinecone(api_key=self.api_key, **self.config)
                if self.index_name and hasattr(pc, "Index"):
                    self._connection = pc.Index(self.index_name)
                else:
                    self._connection = pc
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Pinecone: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _PineconeCursorAdapter(conn)

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
        if hasattr(conn, "list_indexes"):
            conn.list_indexes()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Pinecone",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = conn.cursor() if hasattr(conn, "cursor") else _PineconeCursorAdapter(conn)
        try:
            return introspect_pinecone(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Pinecone schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
