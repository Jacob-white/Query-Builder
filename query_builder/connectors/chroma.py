"""
ChromaDB In-Process & Server AI Vector Database Connector.
==========================================================
Provides ChromaDB connectivity via chromadb client,
dual sync and async execution protocols, and collection schema introspection.
"""

from __future__ import annotations

import asyncio
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
from query_builder.connectors.introspection import introspect_chroma
from query_builder.connectors.registry import register_connector


class UnsupportedChromaQuery(ValueError):
    """The statement is outside what ChromaDB's native API can run."""


_CMP = {
    "EQ": "$eq",
    "NEQ": "$ne",
    "GT": "$gt",
    "GTE": "$gte",
    "LT": "$lt",
    "LTE": "$lte",
}


def _chroma_literal(node: Any) -> Any:
    from sqlglot import exp

    if isinstance(node, exp.Neg):
        return -_chroma_literal(node.this)
    if isinstance(node, exp.Boolean):
        return bool(node.this)
    if isinstance(node, exp.Literal):
        if node.is_string:
            return node.this
        text = node.this
        return float(text) if any(c in text for c in ".eE") else int(text)
    raise UnsupportedChromaQuery(f"unsupported literal in WHERE: {node.sql()}")


def _chroma_where(node: Any) -> tuple[list[str] | None, dict[str, Any] | None]:
    """Translate a WHERE expression to (ids, ``where``); ``id`` may only be =/IN, top-level."""
    from sqlglot import exp

    def conv(n: Any) -> dict[str, Any]:
        if isinstance(n, exp.Paren):
            return conv(n.this)
        if isinstance(n, (exp.And, exp.Or)):
            op = "$and" if isinstance(n, exp.And) else "$or"
            return {op: [conv(n.this), conv(n.expression)]}
        name = type(n).__name__.upper()
        if name in _CMP and isinstance(n.this, exp.Column):
            return {n.this.name: {_CMP[name]: _chroma_literal(n.expression)}}
        if isinstance(n, exp.In) and isinstance(n.this, exp.Column):
            return {n.this.name: {"$in": [_chroma_literal(e) for e in n.expressions]}}
        raise UnsupportedChromaQuery(f"unsupported WHERE expression: {n.sql()}")

    if isinstance(node, (exp.EQ, exp.In)) and isinstance(node.this, exp.Column):
        if node.this.name == "id":
            vals = (
                [_chroma_literal(node.expression)]
                if isinstance(node, exp.EQ)
                else [_chroma_literal(e) for e in node.expressions]
            )
            return [str(v) for v in vals], None
    return None, conv(node)


def _chroma_records(res: Any) -> list[dict[str, Any]]:
    ids = res.get("ids") or []
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    out: list[dict[str, Any]] = []
    for i, id_ in enumerate(ids):
        rec: dict[str, Any] = {
            "id": id_,
            "document": docs[i] if i < len(docs) else None,
        }
        meta = metas[i] if i < len(metas) else None
        rec.update(meta or {})
        out.append(rec)
    return out


def _chroma_version() -> str:
    try:
        import chromadb

        return f"ChromaDB {getattr(chromadb, '__version__', '')}".strip()
    except ImportError:  # pragma: no cover
        return "ChromaDB"


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
        elif hasattr(self.conn, "get_collection") and not hasattr(self.conn, "query"):
            self._execute_on_client(clean_sql, params)
        elif hasattr(self.conn, "query") and (
            params is not None
            and len(params) > 0
            and (
                "distance" in clean_sql.lower()
                or "vector" in clean_sql.lower()
                or "search" in clean_sql.lower()
                or "score" in clean_sql.lower()
            )
        ):
            vector = [[0.0] * 8]
            if params and isinstance(params[0], (list, tuple)):
                vector = [list(params[0])]
            elif params and isinstance(params[0], str):
                with contextlib.suppress(Exception):
                    parsed = json.loads(params[0])
                    if isinstance(parsed, list):
                        vector = [parsed]
            limit_val = 10
            import re

            lm = re.search(r"\bLIMIT\s+(\d+)", clean_sql, re.IGNORECASE)
            if lm:
                limit_val = int(lm.group(1))
            res = self.conn.query(query_embeddings=vector, n_results=limit_val)
            ids = (
                res.get("ids", [[]])[0]
                if isinstance(res, dict) and res.get("ids")
                else []
            )
            docs = (
                res.get("documents", [[]])[0]
                if isinstance(res, dict) and res.get("documents")
                else []
            )
            dists = (
                res.get("distances", [[]])[0]
                if isinstance(res, dict) and res.get("distances")
                else []
            )
            metas = (
                res.get("metadatas", [[]])[0]
                if isinstance(res, dict) and res.get("metadatas")
                else []
            )
            self.description = [("id",), ("document",), ("distance",), ("metadata",)]
            n = max(len(ids), len(docs), len(dists), len(metas))
            self._rows = [
                [
                    ids[i] if i < len(ids) else None,
                    docs[i] if i < len(docs) else None,
                    dists[i] if i < len(dists) else 0.0,
                    metas[i] if i < len(metas) else {},
                ]
                for i in range(n)
            ]
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

    # ------------------------------------------------------------------ real client
    def _execute_on_client(self, clean_sql: str, params: list[Any] | None) -> None:
        """``SELECT <cols> FROM <collection> [WHERE ..] [ORDER BY ..] [LIMIT n [OFFSET m]]``
        mapped onto ``Collection.get`` (or ``Collection.query`` for a vector parameter).

        Rows have ``id``, ``document`` and one column per metadata key. Chroma has no SQL
        engine: whatever the subset cannot express raises ``UnsupportedChromaQuery`` rather
        than returning unfiltered rows.
        """
        import re

        from query_builder.connectors.lancedb import _inline_params

        if params and re.search(
            r"distance|vector|search|score", clean_sql, re.IGNORECASE
        ):
            self._vector_query(clean_sql, params)
            return
        import sqlglot
        from sqlglot import exp

        parsed = sqlglot.parse_one(_inline_params(clean_sql, params), read="postgres")
        bad = ("joins", "group", "having", "distinct", "with", "laterals")
        if not isinstance(parsed, exp.Select) or any(parsed.args.get(k) for k in bad):
            raise UnsupportedChromaQuery(
                "ChromaDB supports only single-collection SELECT ... [WHERE] [ORDER BY] "
                f"[LIMIT] (got: {clean_sql[:80]!r})"
            )
        from_ = parsed.args.get("from_") or parsed.args.get("from")
        table_expr = from_.this if from_ is not None else None
        if not isinstance(table_expr, exp.Table):
            raise UnsupportedChromaQuery(
                "ChromaDB SELECT needs a plain FROM <collection>."
            )
        collection = self.conn.get_collection(table_expr.name)
        where_node = parsed.args.get("where")
        ids, where = (
            _chroma_where(where_node.this) if where_node is not None else (None, None)
        )
        res = collection.get(ids=ids, where=where, include=["documents", "metadatas"])
        records = _chroma_records(res)
        order = parsed.args.get("order")
        if order is not None:
            for o in reversed(order.expressions):
                if not isinstance(o.this, exp.Column):
                    raise UnsupportedChromaQuery(
                        "ORDER BY supports plain columns only."
                    )
                key = o.this.name
                records.sort(
                    key=lambda r, k=key: (r.get(k) is None, r.get(k)),
                    reverse=bool(o.args.get("desc")),
                )
        limit_node = parsed.args.get("limit")
        offset_node = parsed.args.get("offset")
        offset = int(offset_node.expression.name) if offset_node is not None else 0
        end = (
            offset + int(limit_node.expression.name) if limit_node is not None else None
        )
        records = records[offset:end]
        names: list[str] = []
        picks: list[str] = []
        for item in parsed.expressions:
            if isinstance(item, exp.Star):
                seen: list[str] = []
                for r in records:
                    seen.extend(k for k in r if k not in seen)
                for k in seen or ["id", "document"]:
                    names.append(k)
                    picks.append(k)
                continue
            col = item.this if isinstance(item, exp.Alias) else item
            if not isinstance(col, exp.Column):
                raise UnsupportedChromaQuery(
                    "ChromaDB projections support plain columns and * only."
                )
            names.append(item.alias_or_name)
            picks.append(col.name)
        self.description = [(n,) for n in names]
        self._rows = [[r.get(k) for k in picks] for r in records]

    def _vector_query(self, clean_sql: str, params: list[Any]) -> None:
        import re

        m = re.search(r"\bFROM\s+[`\"\[]?([A-Za-z0-9_.-]+)", clean_sql, re.IGNORECASE)
        if m is None:
            raise UnsupportedChromaQuery("vector search needs FROM <collection>")
        vector: Any = params[0]
        if isinstance(vector, str):
            vector = json.loads(vector)
        if not isinstance(vector, (list, tuple)):
            raise UnsupportedChromaQuery(
                "vector search needs a vector as first parameter"
            )
        lm = re.search(r"\bLIMIT\s+(\d+)", clean_sql, re.IGNORECASE)
        res = self.conn.get_collection(m.group(1)).query(
            query_embeddings=[list(vector)],
            n_results=int(lm.group(1)) if lm else 10,
            include=["documents", "metadatas", "distances"],
        )
        records = _chroma_records(
            {k: (v[0] if v else []) for k, v in res.items() if isinstance(v, list)}
        )
        for rec, dist in zip(records, (res.get("distances") or [[]])[0], strict=False):
            rec["distance"] = dist
        keys: list[str] = []
        for r in records:
            keys.extend(k for k in r if k not in keys)
        self.description = [(k,) for k in keys or ["id", "document", "distance"]]
        self._rows = [[r.get(k) for k in keys] for r in records]

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
            "engine_version": _chroma_version(),
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

        # chromadb's AsyncHttpClient returns coroutines from every method, which the shared
        # cursor adapter cannot await. Use the synchronous clients in a worker thread.
        def _open() -> Any:
            if self.host:
                return chromadb.HttpClient(
                    host=self.host, port=self.port, **self.config
                )
            if self.path:
                return chromadb.PersistentClient(path=self.path, **self.config)
            return chromadb.Client(**self.config)

        try:
            self._connection = await asyncio.to_thread(_open)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to ChromaDB: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()

        def _run() -> tuple[list[str], list[dict[str, Any]], float]:
            start = time.perf_counter()
            cur = (
                conn.cursor() if hasattr(conn, "cursor") else _ChromaCursorAdapter(conn)
            )
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

        return await asyncio.to_thread(_run)

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        if hasattr(conn, "heartbeat"):
            await asyncio.to_thread(conn.heartbeat)
        elif hasattr(conn, "list_collections"):
            await asyncio.to_thread(conn.list_collections)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": _chroma_version(),
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()

        def _introspect() -> dict[str, Any]:
            cur = (
                conn.cursor() if hasattr(conn, "cursor") else _ChromaCursorAdapter(conn)
            )
            try:
                return introspect_chroma(cur, filter_sensitive=filter_sensitive)
            finally:
                if hasattr(cur, "close"):
                    cur.close()

        try:
            return await asyncio.to_thread(_introspect)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Chroma schema: {exc}"
            ) from exc


ChromaDBConnector = ChromaConnector
AsyncChromaDBConnector = AsyncChromaConnector
