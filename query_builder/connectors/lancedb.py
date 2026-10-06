"""
LanceDB Serverless Columnar Vector Database Connector.
======================================================
Provides LanceDB Apache Arrow-backed connectivity via lancedb client,
dual sync and async execution protocols, and Arrow table schema introspection.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_lancedb
from query_builder.connectors.registry import register_connector

DEFAULT_LANCEDB_URI = os.path.join(tempfile.gettempdir(), "lancedb")


class _LanceDBCursorAdapter:
    """Adapts a LanceDB connection into a standard DB-API cursor interface."""

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
        elif (
            clean_sql == "table_names" or clean_sql.upper().startswith("SHOW TABLES")
        ) and hasattr(self.conn, "table_names"):
            tbls = self.conn.table_names()
            self.description = [("table_name",)]
            self._rows = [[t] for t in tbls]
        elif hasattr(self.conn, "open_table"):
            import re

            m = re.search(
                r"\b(?:FROM|INTO|UPDATE|TABLE)\s+[`\"\[]?([a-zA-Z0-9_.-]+)[`\"\]]?",
                clean_sql,
                re.IGNORECASE,
            )
            tbl_name = m.group(1) if m else "items"
            try:
                tbl = self.conn.open_table(tbl_name)
                if hasattr(tbl, "search"):
                    vector = None
                    if params and len(params) > 0:
                        if isinstance(params[0], (list, tuple)):
                            vector = list(params[0])
                        elif isinstance(params[0], str):
                            with contextlib.suppress(Exception):
                                parsed = json.loads(params[0])
                                if isinstance(parsed, list):
                                    vector = parsed
                    limit_val = 10
                    lm = re.search(r"\bLIMIT\s+(\d+)", clean_sql, re.IGNORECASE)
                    if lm:
                        limit_val = int(lm.group(1))
                    search_builder = tbl.search(vector) if vector is not None else tbl.search()
                    arrow_tbl = search_builder.limit(limit_val).to_arrow()
                    self.description = [(f.name,) for f in arrow_tbl.schema]
                    pylist = arrow_tbl.to_pylist()
                    self._rows = [
                        [r.get(f.name) for f in arrow_tbl.schema] for r in pylist
                    ]
                elif hasattr(tbl, "to_pandas"):
                    df = tbl.to_pandas()
                    self.description = [(c,) for c in df.columns]
                    self._rows = [list(r) for r in df.values]
                else:
                    self.description = [("status",)]
                    self._rows = [["ok"]]
            except Exception:  # noqa: BLE001
                self.description = [("status",)]
                self._rows = [["ok"]]
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


@register_connector("lancedb", aliases=["lance"])
class LanceDBConnector(BaseConnector):
    """Connector for LanceDB Arrow-backed vector database."""

    dialect_name = "lancedb"

    def __init__(
        self,
        uri: str = DEFAULT_LANCEDB_URI,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.uri = uri or DEFAULT_LANCEDB_URI

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("lancedb",):
            try:
                driver = __import__(mod_name, fromlist=["connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'lancedb' is not installed. "
                "Install with: pip install 'query-builder-engine[lancedb]'"
            )

        try:
            self._connection = driver.connect(self.uri, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to LanceDB: {exc}") from exc

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
            adapter = _LanceDBCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "table_names"):
            conn.table_names()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "LanceDB",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_lancedb(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect LanceDB schema: {exc}"
                ) from exc


@register_connector("async_lancedb", aliases=["async_lance"])
class AsyncLanceDBConnector(AsyncBaseConnector):
    """Asynchronous connector for LanceDB vector database."""

    dialect_name = "lancedb"

    def __init__(
        self,
        uri: str = DEFAULT_LANCEDB_URI,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.uri = uri or DEFAULT_LANCEDB_URI

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("lancedb",):
            try:
                driver = __import__(mod_name, fromlist=["connect_async", "connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'lancedb' is not installed. "
                "Install with: pip install 'query-builder-engine[lancedb]'"
            )

        try:
            if hasattr(driver, "connect_async"):
                res = driver.connect_async(self.uri, **self.config)
                if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                    self._connection = await res
                else:
                    self._connection = res
            else:
                self._connection = driver.connect(self.uri, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to LanceDB: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _LanceDBCursorAdapter(conn)

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
        if hasattr(conn, "table_names"):
            res = conn.table_names()
            if hasattr(res, "__await__"):
                await res
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "LanceDB",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = conn.cursor() if hasattr(conn, "cursor") else _LanceDBCursorAdapter(conn)
        try:
            return introspect_lancedb(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect LanceDB schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
