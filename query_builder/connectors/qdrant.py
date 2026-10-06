"""
Qdrant Vector Database & Search Engine Connector.
=================================================
Provides Qdrant vector search engine connectivity via qdrant-client,
dual sync and async execution protocols, and payload schema introspection.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_qdrant
from query_builder.connectors.registry import register_connector


class _QdrantCursorAdapter:
    """Adapts a QdrantClient into a standard DB-API cursor interface."""

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
        elif clean_sql.startswith("GET /collections") and hasattr(
            self.conn, "get_collections"
        ):
            res = self.conn.get_collections()
            colls = (
                getattr(res, "collections", res) if hasattr(res, "collections") else res
            )
            self.description = [("collection_name",)]
            self._rows = [[getattr(c, "name", str(c))] for c in colls]
        elif hasattr(self.conn, "search") and (
            params is not None
            and len(params) > 0
            and ("distance" in clean_sql.lower() or "vector" in clean_sql.lower() or "search" in clean_sql.lower())
        ):
            coll = "default"
            import re

            m = re.search(r"\bFROM\s+([`\"]?)([\w_]+)\1", clean_sql, re.IGNORECASE)
            if m:
                coll = m.group(2)
            vector = [0.0] * 8
            if params and isinstance(params[0], (list, tuple)):
                vector = list(params[0])
            elif params and isinstance(params[0], str):
                with contextlib.suppress(Exception):
                    parsed = json.loads(params[0])
                    if isinstance(parsed, list):
                        vector = parsed
            limit_val = 10
            lm = re.search(r"\bLIMIT\s+(\d+)", clean_sql, re.IGNORECASE)
            if lm:
                limit_val = int(lm.group(1))
            res = self.conn.search(
                collection_name=coll, query_vector=vector, limit=limit_val
            )
            self.description = [("id",), ("score",), ("payload",)]
            self._rows = [
                [
                    getattr(p, "id", p.get("id") if isinstance(p, dict) else None),
                    getattr(p, "score", p.get("score") if isinstance(p, dict) else 0.0),
                    getattr(p, "payload", p.get("payload") if isinstance(p, dict) else {}),
                ]
                for p in res
            ]
        elif hasattr(self.conn, "scroll"):
            coll = "default"
            import re

            m = re.search(r"\bFROM\s+([`\"]?)([\w_]+)\1", clean_sql, re.IGNORECASE)
            if m:
                coll = m.group(2)
            scroll_res = self.conn.scroll(collection_name=coll, limit=10)
            points = (
                scroll_res[0]
                if isinstance(scroll_res, (tuple, list))
                and len(scroll_res) == 2
                and isinstance(scroll_res[0], list)
                else (
                    scroll_res
                    if isinstance(scroll_res, list)
                    else getattr(scroll_res, "points", [])
                )
            )
            self.description = [("id",), ("payload",)]
            self._rows = [
                [getattr(p, "id", None), getattr(p, "payload", {})] for p in points
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


@register_connector("qdrant", aliases=["qdrant_db"])
class QdrantConnector(BaseConnector):
    """Connector for Qdrant vector search database."""

    dialect_name = "qdrant"

    def __init__(
        self,
        url: str | None = None,
        host: str = "localhost",
        port: int = 6333,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.url = url
        self.host = host
        self.port = port

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import qdrant_client
        except ImportError as err:
            raise DriverNotInstalledError(
                "'qdrant-client' is not installed. "
                "Install with: pip install 'query-builder-engine[qdrant]'"
            ) from err

        try:
            if self.url:
                self._connection = qdrant_client.QdrantClient(
                    url=self.url, **self.config
                )
            else:
                self._connection = qdrant_client.QdrantClient(
                    host=self.host, port=self.port, **self.config
                )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to Qdrant: {exc}") from exc

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
            adapter = _QdrantCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "get_collections"):
            conn.get_collections()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Qdrant",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_qdrant(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Qdrant schema: {exc}"
                ) from exc


@register_connector("async_qdrant", aliases=["async_qdrant_db"])
class AsyncQdrantConnector(AsyncBaseConnector):
    """Asynchronous connector for Qdrant vector search database."""

    dialect_name = "qdrant"

    def __init__(
        self,
        url: str | None = None,
        host: str = "localhost",
        port: int = 6333,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.url = url
        self.host = host
        self.port = port

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import qdrant_client
        except ImportError as err:
            raise DriverNotInstalledError(
                "'qdrant-client' is not installed. "
                "Install with: pip install 'query-builder-engine[qdrant]'"
            ) from err

        try:
            client_cls = getattr(
                qdrant_client, "AsyncQdrantClient", qdrant_client.QdrantClient
            )
            if self.url:
                self._connection = client_cls(url=self.url, **self.config)
            else:
                self._connection = client_cls(
                    host=self.host, port=self.port, **self.config
                )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Qdrant: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _QdrantCursorAdapter(conn)

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
        if hasattr(conn, "get_collections"):
            res = conn.get_collections()
            if hasattr(res, "__await__"):
                await res
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Qdrant",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = conn.cursor() if hasattr(conn, "cursor") else _QdrantCursorAdapter(conn)
        try:
            return introspect_qdrant(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Qdrant schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
