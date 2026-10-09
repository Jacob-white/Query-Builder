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


class UnsupportedLanceQuery(ValueError):
    """The statement is outside what LanceDB's native API can run."""


def _inline_params(sql: str, params: list[Any] | None) -> str:
    """Substitute positional ``?`` / ``%s`` markers (outside string literals) with literals."""
    if not params:
        return sql
    out: list[str] = []
    idx = 0
    in_quote = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            in_quote = not in_quote
            out.append(ch)
        elif (
            not in_quote
            and idx < len(params)
            and (ch == "?" or sql.startswith("%s", i))
        ):
            val = params[idx]
            idx += 1
            if ch == "%":
                i += 1
            if val is None:
                out.append("NULL")
            elif isinstance(val, bool):
                out.append("TRUE" if val else "FALSE")
            elif isinstance(val, (int, float)):
                out.append(str(val))
            else:
                out.append("'" + str(val).replace("'", "''") + "'")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _lancedb_version() -> str:
    try:
        import lancedb

        return f"LanceDB {getattr(lancedb, '__version__', '')}".strip()
    except ImportError:  # pragma: no cover - only reached without the driver
        return "LanceDB"


def _run_sync(
    conn: Any, sql: str, params: list[Any] | None
) -> tuple[list[str], list[dict[str, Any]], float]:
    start = time.perf_counter()
    cur = conn.cursor() if hasattr(conn, "cursor") else _LanceDBCursorAdapter(conn)
    try:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        col_names = [col[0] for col in (cur.description or [])]
        rows = cur.fetchall() or []
        dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
        return col_names, dict_rows, (time.perf_counter() - start) * 1000.0
    finally:
        if hasattr(cur, "close"):
            cur.close()


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
            self._execute_native(clean_sql, params)
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

    def _execute_native(self, clean_sql: str, params: list[Any] | None) -> None:
        """Run ``SELECT <cols> FROM <table> [WHERE ..] [ORDER BY ..] [LIMIT n [OFFSET m]]``
        (or a vector search when a vector parameter is given) with LanceDB's own API.

        LanceDB has no SQL engine of its own, so anything this subset cannot express raises
        ``UnsupportedLanceQuery`` instead of silently returning unfiltered rows.
        """
        if params and (
            "distance" in clean_sql.lower() or "vector" in clean_sql.lower()
        ):
            self._vector_search(clean_sql, params)
            return
        import sqlglot
        from sqlglot import exp

        parsed = sqlglot.parse_one(_inline_params(clean_sql, params), read="postgres")
        unsupported = ("joins", "group", "having", "distinct", "with", "with_", "laterals")
        if not isinstance(parsed, exp.Select) or any(
            parsed.args.get(k) for k in unsupported
        ):
            raise UnsupportedLanceQuery(
                "LanceDB supports only single-table SELECT ... [WHERE] [ORDER BY] [LIMIT] "
                f"(got: {clean_sql[:80]!r})"
            )
        from_ = parsed.args.get("from_") or parsed.args.get("from")
        table_expr = from_.this if from_ is not None else None
        if not isinstance(table_expr, exp.Table):
            raise UnsupportedLanceQuery("LanceDB SELECT needs a plain FROM <table>.")
        tbl = self.conn.open_table(table_expr.name)
        where = parsed.args.get("where")
        builder = tbl.search()
        if where is not None:
            builder = builder.where(where.this.sql(dialect="postgres"), prefilter=True)
        order = parsed.args.get("order")
        limit_node = parsed.args.get("limit")
        offset_node = parsed.args.get("offset")
        limit = int(limit_node.expression.name) if limit_node is not None else None
        offset = int(offset_node.expression.name) if offset_node is not None else 0
        if order is None and limit is not None:
            builder = builder.limit(limit + offset)
        else:
            builder = builder.limit(None)
        table = builder.to_arrow()
        if order is not None:
            keys = []
            for o in order.expressions:
                if not isinstance(o.this, exp.Column):
                    raise UnsupportedLanceQuery("ORDER BY supports plain columns only.")
                keys.append(
                    (o.this.name, "descending" if o.args.get("desc") else "ascending")
                )
            table = table.sort_by(keys)
        if offset or (order is not None and limit is not None):
            table = table.slice(offset, limit)
        elif offset:
            table = table.slice(offset)
        names: list[str] = []
        arrays: list[Any] = []
        for item in parsed.expressions:
            if isinstance(item, exp.Star):
                for f in table.schema.names:
                    names.append(f)
                    arrays.append(table.column(f))
                continue
            col = item.this if isinstance(item, exp.Alias) else item
            if not isinstance(col, exp.Column):
                raise UnsupportedLanceQuery(
                    "LanceDB projections support plain columns and * only."
                )
            names.append(item.alias_or_name)
            arrays.append(table.column(col.name))
        self.description = [(n,) for n in names]
        columns = [a.to_pylist() for a in arrays]
        self._rows = [list(r) for r in zip(*columns, strict=True)] if columns else []

    def _vector_search(self, clean_sql: str, params: list[Any]) -> None:
        import re

        tbl_name = re.search(
            r"FROM\s+[`\"\[]?([a-zA-Z0-9_.-]+)[`\"\]]?", clean_sql, re.IGNORECASE
        )
        tbl = self.conn.open_table(tbl_name.group(1) if tbl_name else "items")
        vector = None
        if isinstance(params[0], (list, tuple)):
            vector = list(params[0])
        elif isinstance(params[0], str):
            with contextlib.suppress(Exception):
                parsed_vec = json.loads(params[0])
                if isinstance(parsed_vec, list):
                    vector = parsed_vec
        if vector is None:
            raise UnsupportedLanceQuery(
                "vector search needs a vector as first parameter"
            )
        lm = re.search(r"LIMIT\s+(\d+)", clean_sql, re.IGNORECASE)
        arrow_tbl = tbl.search(vector).limit(int(lm.group(1)) if lm else 10).to_arrow()
        self.description = [(f.name,) for f in arrow_tbl.schema]
        names = [f.name for f in arrow_tbl.schema]
        self._rows = [[r.get(n) for n in names] for r in arrow_tbl.to_pylist()]

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
            "engine_version": _lancedb_version(),
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

        # The AsyncConnection of lancedb returns coroutines from every method, which the
        # shared cursor adapter cannot await: use the synchronous client and run it in a
        # worker thread so the event loop is never blocked.
        try:
            self._connection = await asyncio.to_thread(
                driver.connect, self.uri, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to LanceDB: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        return await asyncio.to_thread(_run_sync, conn, sql, params)

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        if hasattr(conn, "table_names"):
            await asyncio.to_thread(conn.table_names)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": _lancedb_version(),
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()

        def _introspect() -> dict[str, Any]:
            cur = (
                conn.cursor()
                if hasattr(conn, "cursor")
                else _LanceDBCursorAdapter(conn)
            )
            try:
                return introspect_lancedb(cur, filter_sensitive=filter_sensitive)
            finally:
                if hasattr(cur, "close"):
                    cur.close()

        try:
            return await asyncio.to_thread(_introspect)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect LanceDB schema: {exc}"
            ) from exc
