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

from query_builder.connectors._vector_sql import (
    VectorQuery,
    VectorQueryError,
    distance_from_score,
    drive_async,
    drive_sync,
    matches,
    parse_vector_sql,
    payload_columns,
    shape_rows,
    sort_hits,
)
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import (
    introspect_pinecone,
    normalize_schema_snapshot,
)
from query_builder.connectors.registry import register_connector

#: a filter-only / ordered read has to list and fetch ids; stop at this many vectors
MAX_SCAN_VECTORS = 10_000
_METRICS = {"cosine": "cosine", "euclidean": "euclidean", "dotproduct": "dot"}
_OPS = {
    "=": "$eq",
    "!=": "$ne",
    ">": "$gt",
    ">=": "$gte",
    "<": "$lt",
    "<=": "$lte",
    "in": "$in",
    "not_in": "$nin",
}


def _is_real_client(conn: Any) -> bool:
    return type(conn).__module__.startswith("pinecone")


def _is_index(conn: Any) -> bool:
    """A data-plane index handle (as opposed to the control-plane ``Pinecone`` client)."""
    return _is_real_client(conn) and hasattr(conn, "query") and hasattr(conn, "fetch")


def _pinecone_filter(conds: list[Any]) -> dict[str, Any] | None:
    if not conds:
        return None
    out: dict[str, Any] = {}
    for c in conds:
        if c.op in ("is_null", "is_not_null"):
            out.setdefault(c.column, {})["$exists"] = c.op == "is_not_null"
            continue
        out.setdefault(c.column, {})[_OPS[c.op]] = c.value
    return out


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _index_plan(table: str, make_index: str) -> Any:
    """Yield the calls that produce (index handle, describe_index info) for ``table``."""
    info = yield ("describe_index", {"name": table})
    idx = yield (make_index, {"host": _get(info, "host")})
    return idx, info


def _resolve_table(names: list[str], wanted: str) -> str:
    # Pinecone index names cannot contain '_' (lowercase alphanumerics and '-'), while the
    # compiler only emits identifiers made of '_': treat them as the same name.
    norm = wanted.lower().replace("_", "-")
    for n in names:
        if n == wanted or n.lower().replace("_", "-") == norm:
            return n
    raise VectorQueryError(f"index {wanted!r} does not exist; have {sorted(names)}")


def _index_names(listing: Any) -> list[str]:
    items = listing.names() if callable(getattr(listing, "names", None)) else listing
    return [str(_get(i, "name", i)) for i in items]


def pinecone_plan(
    vq: VectorQuery, conn_is_index: bool, make_index: str, index_metric: str | None
) -> Any:
    """``index_metric`` is only needed when the connector holds a bare index handle."""
    table = vq.table
    info = None
    if conn_is_index:
        idx = None  # the connection itself is the index; calls below use ``target``
    else:
        listing = yield ("list_indexes", {})
        table = _resolve_table(_index_names(listing), vq.table)
        idx, info = yield from _index_plan(table, make_index)

    def call(method: str) -> Any:
        return method if idx is None else getattr(idx, method)

    metric_name = str(_get(info, "metric", index_metric) or "cosine")
    engine_metric = _METRICS.get(metric_name, metric_name)

    hits: list[dict[str, Any]] = []
    if vq.is_search:
        if any(n != "_distance" or d for n, d in vq.order_by):
            raise VectorQueryError(
                "a vector search can only be ordered by distance, ascending"
            )
        want = 10_000 if vq.count_only else (vq.limit or 10) + vq.offset
        res = yield (
            call("query"),
            {
                "vector": vq.vector,
                "top_k": min(want, 10_000),
                "filter": _pinecone_filter(vq.conds),
                "include_metadata": True,
            },
        )
        for m in _get(res, "matches", []):
            score = float(_get(m, "score", 0.0))
            if engine_metric == "euclidean":  # Pinecone scores euclidean as squared L2
                score = score**0.5
            d = distance_from_score(vq.metric or "cosine", score, engine_metric)
            if vq.max_distance is None or d <= vq.max_distance:
                hits.append(
                    {"id": _get(m, "id"), **(_get(m, "metadata") or {}), "_distance": d}
                )
        if vq.count_only:
            return [("count",)], [[len(hits)]]
        hits = hits[vq.offset :]
    else:
        ids: list[str] = []
        pages = yield (call("list"), {})
        for page in pages:
            ids.extend(str(_get(v, "id", v)) for v in _get(page, "vectors", []))
            if len(ids) > MAX_SCAN_VECTORS:
                raise VectorQueryError(
                    f"index scan exceeds {MAX_SCAN_VECTORS} vectors; use a vector search"
                )
        everything: list[dict[str, Any]] = []
        for start in range(0, len(ids), 100):
            fetched = yield (call("fetch"), {"ids": ids[start : start + 100]})
            for vid, vec in (_get(fetched, "vectors", {}) or {}).items():
                everything.append({"id": vid, **(_get(vec, "metadata") or {})})
        everything = [h for h in everything if matches(vq.conds, h)]
        if vq.count_only:
            return [("count",)], [[len(everything)]]
        if not vq.order_by:
            everything.sort(key=lambda h: str(h["id"]))
        hits = sort_hits(vq, everything)[vq.offset :]
    if vq.limit is not None:
        hits = hits[: vq.limit]
    return shape_rows(vq, hits)


def pinecone_introspect_plan(
    conn_is_index: bool, make_index: str, index_name: str | None
) -> Any:
    tables: dict[str, dict[str, Any]] = {}
    targets: list[tuple[str, Any, Any]] = []
    if conn_is_index:
        targets.append((index_name or "index", None, None))
    else:
        listing = yield ("list_indexes", {})
        for name in _index_names(listing):
            idx, info = yield from _index_plan(name, make_index)
            targets.append((name, idx, info))
    for name, idx, info in targets:
        sample: list[dict[str, Any]] = []
        pages = yield ((idx.list if idx is not None else "list"), {})
        ids: list[str] = []
        for page in pages:
            ids.extend(str(_get(v, "id", v)) for v in _get(page, "vectors", []))
            if len(ids) >= 20:
                break
        if ids:
            fetched = yield (
                (idx.fetch if idx is not None else "fetch"),
                {"ids": ids[:20]},
            )
            sample = [
                dict(_get(v, "metadata") or {})
                for v in (_get(fetched, "vectors", {}) or {}).values()
            ]
        dim = _get(info, "dimension")
        metric = _get(info, "metric")
        cols: list[dict[str, Any]] = [
            {
                "name": "id",
                "data_type": "string",
                "is_nullable": False,
                "is_primary": True,
                "comment": None,
            },
            {
                "name": "vector",
                "data_type": "vector",
                "is_nullable": False,
                "is_primary": False,
                "comment": f"dimension={dim}; metric={metric}" if dim else None,
            },
        ]
        meta = payload_columns(sample)
        cols.extend(
            {
                "name": k,
                "data_type": t,
                "is_nullable": True,
                "is_primary": False,
                "comment": "metadata",
            }
            for k, t in meta.items()
        )
        tables[name] = {
            "name": name,
            "columns": cols,
            "has_user_id": "user_id" in meta,
            "user_col": "user_id" if "user_id" in meta else None,
            "comment": None,
        }
    return {"tables": tables, "foreign_keys": [], "relationships": []}


class _PineconeCursorAdapter:
    """Adapts a Pinecone Index / Client connection into a DB-API cursor interface."""

    def __init__(self, connection: Any, metric: str | None = None) -> None:
        self.conn = connection
        self.metric = metric
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if _is_real_client(self.conn) and not clean_sql.startswith("list_indexes"):
            vq = parse_vector_sql(clean_sql, params)
            plan = pinecone_plan(vq, _is_index(self.conn), "Index", self.metric)
            self.description, self._rows = drive_sync(plan, self.conn)
        elif hasattr(self.conn, "cursor"):
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
            v = [0.0] * 8
            k = 10
            if params and len(params) > 0:
                if all(isinstance(x, (int, float)) for x in params):
                    v = params
                elif isinstance(params[0], (list, tuple)):
                    v = list(params[0])
                elif isinstance(params[0], str) and params[0].startswith("["):
                    import json

                    with contextlib.suppress(Exception):
                        parsed = json.loads(params[0])
                        if isinstance(parsed, list):
                            v = parsed
                if len(params) > 1 and isinstance(params[1], int):
                    k = params[1]
            import re

            lm = re.search(r"\bLIMIT\s+(\d+)", clean_sql, re.IGNORECASE)
            if lm:
                k = int(lm.group(1))
            res = self.conn.query(vector=v, top_k=k, include_metadata=True)
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
                pc_cfg = {k: v for k, v in self.config.items() if k != "metric"}
                pc = driver.Pinecone(api_key=self.api_key, **pc_cfg)
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
            adapter = _PineconeCursorAdapter(conn, self.config.get("metric"))
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "list_indexes"):
            conn.list_indexes()
        elif _is_index(conn):
            conn.describe_index_stats()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Pinecone",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = self.connect()
        if _is_real_client(conn):
            try:
                plan = pinecone_introspect_plan(
                    _is_index(conn), "Index", self.index_name
                )
                raw = drive_sync(plan, conn)
                return normalize_schema_snapshot(raw, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Pinecone schema: {exc}"
                ) from exc
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
            pc_cfg = {k: v for k, v in self.config.items() if k != "metric"}
            if hasattr(driver, "PineconeAsyncio"):
                pc = driver.PineconeAsyncio(api_key=self.api_key, **pc_cfg)
                if self.index_name:
                    info = await pc.describe_index(self.index_name)
                    self._index_owner = pc
                    self._connection = pc.IndexAsyncio(host=info.host)
                else:
                    self._connection = pc
            elif hasattr(driver, "Pinecone"):
                pc = driver.Pinecone(api_key=self.api_key, **pc_cfg)
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
        if _is_real_client(conn):
            vq = parse_vector_sql(sql, params)
            plan = pinecone_plan(
                vq, _is_index(conn), "IndexAsyncio", self.config.get("metric")
            )
            desc, rows = await drive_async(plan, conn)
            names = [d[0] for d in desc]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return names, [dict(zip(names, r, strict=False)) for r in rows], latency_ms
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
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            if hasattr(cur, "close"):
                cur.close()

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        if hasattr(conn, "list_indexes"):
            res = conn.list_indexes()
            if hasattr(res, "__await__"):
                await res
        elif _is_index(conn):
            res = conn.describe_index_stats()
            if hasattr(res, "__await__"):
                await res
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Pinecone",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        if _is_real_client(conn):
            try:
                plan = pinecone_introspect_plan(
                    _is_index(conn), "IndexAsyncio", self.index_name
                )
                raw = await drive_async(plan, conn)
                return normalize_schema_snapshot(raw, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Pinecone schema: {exc}"
                ) from exc
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
