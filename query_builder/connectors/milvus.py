"""
Milvus Distributed Cloud-Native Vector Database Connector.
==========================================================
Provides Milvus connectivity via pymilvus (MilvusClient / connections),
dual sync and async execution protocols, and collection schema introspection.
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
from query_builder.connectors.introspection import introspect_milvus
from query_builder.connectors.registry import register_connector


class _MilvusCursorAdapter:
    """Adapts a MilvusClient into a standard DB-API cursor interface."""

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
            self._rows = [[str(c)] for c in cols]
        elif hasattr(self.conn, "search") and (
            params is not None
            and len(params) > 0
            and (
                "distance" in clean_sql.lower()
                or "vector" in clean_sql.lower()
                or "search" in clean_sql.lower()
                or "score" in clean_sql.lower()
            )
        ):
            coll = "default"
            import re

            m = re.search(r"\bFROM\s+([`\"]?)([\w_]+)\1", clean_sql, re.IGNORECASE)
            if m:
                coll = m.group(2)
            vector = [[0.0] * 8]
            if params and isinstance(params[0], (list, tuple)):
                vector = [list(params[0])]
            elif params and isinstance(params[0], str):
                with contextlib.suppress(Exception):
                    parsed = json.loads(params[0])
                    if isinstance(parsed, list):
                        vector = [parsed]
            limit_val = 10
            lm = re.search(r"\bLIMIT\s+(\d+)", clean_sql, re.IGNORECASE)
            if lm:
                limit_val = int(lm.group(1))
            res = self.conn.search(collection_name=coll, data=vector, limit=limit_val)
            self.description = [("id",), ("distance",), ("entity",)]
            self._rows = [
                [
                    getattr(r, "id", r.get("id") if isinstance(r, dict) else None),
                    getattr(
                        r, "distance", r.get("distance") if isinstance(r, dict) else 0.0
                    ),
                    getattr(
                        r, "entity", r.get("entity") if isinstance(r, dict) else {}
                    ),
                ]
                for hits in (res if isinstance(res, list) else [res])
                for r in (hits if isinstance(hits, list) else [hits])
            ]
        elif hasattr(self.conn, "query"):
            coll = "default"
            import re

            m = re.search(r"\bFROM\s+([`\"]?)([\w_]+)\1", clean_sql, re.IGNORECASE)
            if m:
                coll = m.group(2)
            res = self.conn.query(collection_name=coll, filter=clean_sql or "")
            if res and isinstance(res[0], dict):
                keys = list(res[0].keys())
                self.description = [(k,) for k in keys]
                self._rows = [[r.get(k) for k in keys] for r in res]
            else:
                self.description = [("res",)]
                self._rows = [[r] for r in res] if res else []
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


@register_connector("milvus", aliases=["pymilvus", "zilliz"])
class MilvusConnector(BaseConnector):
    """Connector for Milvus distributed cloud-native vector database."""

    dialect_name = "milvus"

    def __init__(
        self,
        uri: str = "http://localhost:19530",
        token: str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.uri = uri
        self.token = token

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pymilvus", "pymilvus.milvus_client"):
            try:
                driver = __import__(mod_name, fromlist=["MilvusClient", "connections"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pymilvus' is not installed. "
                "Install with: pip install 'query-builder-engine[milvus]'"
            )

        try:
            if hasattr(driver, "MilvusClient"):
                self._connection = driver.MilvusClient(
                    uri=self.uri, token=self.token, **self.config
                )
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to Milvus: {exc}") from exc

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
            adapter = _MilvusCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "list_collections"):
            conn.list_collections()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Milvus",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_milvus(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Milvus schema: {exc}"
                ) from exc


@register_connector("async_milvus", aliases=["async_pymilvus", "async_zilliz"])
class AsyncMilvusConnector(AsyncBaseConnector):
    """Asynchronous connector for Milvus vector database."""

    dialect_name = "milvus"

    def __init__(
        self,
        uri: str = "http://localhost:19530",
        token: str | None = None,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.uri = uri
        self.token = token

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pymilvus", "pymilvus.milvus_client"):
            try:
                driver = __import__(mod_name, fromlist=["MilvusClient", "connections"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pymilvus' is not installed. "
                "Install with: pip install 'query-builder-engine[milvus]'"
            )

        try:
            if hasattr(driver, "MilvusClient"):
                self._connection = driver.MilvusClient(
                    uri=self.uri, token=self.token, **self.config
                )
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Milvus: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _MilvusCursorAdapter(conn)

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
        if hasattr(conn, "list_collections"):
            conn.list_collections()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Milvus",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = conn.cursor() if hasattr(conn, "cursor") else _MilvusCursorAdapter(conn)
        try:
            return introspect_milvus(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Milvus schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()


ZillizConnector = MilvusConnector
AsyncZillizConnector = AsyncMilvusConnector
