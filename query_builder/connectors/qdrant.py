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

from query_builder.connectors._vector_sql import (
    VectorQuery,
    VectorQueryError,
    distance_from_score,
    drive_async,
    drive_sync,
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
    introspect_qdrant,
    normalize_schema_snapshot,
)
from query_builder.connectors.registry import register_connector

#: ORDER BY on a scan has to read the whole collection (Qdrant orders only by indexed fields)
MAX_SCAN_POINTS = 10_000
_METRICS = {"Cosine": "cosine", "Euclid": "euclidean", "Dot": "dot"}


def _is_real_client(conn: Any) -> bool:
    """True for a genuine qdrant-client object (not a DB-API style wrapper or a test double)."""
    return type(conn).__module__.startswith("qdrant_client")


def _qdrant_filter(conds: list[Any]) -> Any:
    """Translate AND-ed conditions into a ``qdrant_client.models.Filter`` (or None)."""
    if not conds:
        return None
    from qdrant_client import models as m

    must: list[Any] = []
    must_not: list[Any] = []
    for c in conds:
        if c.op == "=":
            must.append(
                m.FieldCondition(key=c.column, match=m.MatchValue(value=c.value))
            )
        elif c.op == "!=":
            must_not.append(
                m.FieldCondition(key=c.column, match=m.MatchValue(value=c.value))
            )
        elif c.op in (">", ">=", "<", "<="):
            rng = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}[c.op]
            must.append(m.FieldCondition(key=c.column, range=m.Range(**{rng: c.value})))
        elif c.op == "in":
            must.append(
                m.FieldCondition(key=c.column, match=m.MatchAny(any=list(c.value)))
            )
        elif c.op == "not_in":
            must_not.append(
                m.FieldCondition(key=c.column, match=m.MatchAny(any=list(c.value)))
            )
        elif c.op == "is_null":
            must.append(m.IsNullCondition(is_null=m.PayloadField(key=c.column)))
        else:  # is_not_null
            must_not.append(m.IsNullCondition(is_null=m.PayloadField(key=c.column)))
    return m.Filter(must=must or None, must_not=must_not or None)


def _hit(point: Any, distance: float | None = None) -> dict[str, Any]:
    hit: dict[str, Any] = {"id": point.id}
    hit.update(point.payload or {})
    if distance is not None:
        hit["_distance"] = distance
    return hit


def qdrant_plan(vq: VectorQuery) -> Any:
    """Run one parsed query as a generator of client calls (see ``drive_sync``)."""
    flt = _qdrant_filter(vq.conds)
    table = vq.table
    if vq.count_only and not vq.is_search:
        res = yield (
            "count",
            {"collection_name": table, "count_filter": flt, "exact": True},
        )
        return [("count",)], [[res.count]]

    hits: list[dict[str, Any]] = []
    if vq.is_search:
        if any(name != "_distance" or desc for name, desc in vq.order_by):
            raise VectorQueryError(
                "a vector search can only be ordered by distance, ascending"
            )
        info = yield ("get_collection", {"collection_name": table})
        vectors = info.config.params.vectors
        using = None
        if isinstance(vectors, dict):
            using = vq.vector_column
            if using not in vectors:
                raise VectorQueryError(
                    f"collection {table} has named vectors {sorted(vectors)}; "
                    f"{using!r} is not one of them"
                )
            params = vectors[using]
        else:
            params = vectors
        dist = getattr(params.distance, "value", params.distance)
        engine_metric = _METRICS.get(str(dist), str(dist).lower())
        want = 10_000 if vq.count_only else (vq.limit or 10) + vq.offset
        res = yield (
            "query_points",
            {
                "collection_name": table,
                "query": vq.vector,
                "using": using,
                "query_filter": flt,
                "limit": want,
                "with_payload": True,
                "with_vectors": False,
            },
        )
        for point in res.points:
            d = distance_from_score(vq.metric or "cosine", point.score, engine_metric)
            if vq.max_distance is None or d <= vq.max_distance:
                hits.append(_hit(point, d))
        if vq.count_only:
            return [("count",)], [[len(hits)]]
        hits = hits[vq.offset :]
    else:
        need = None if vq.order_by or vq.limit is None else vq.limit + vq.offset
        offset: Any = None
        while True:
            points, offset = yield (
                "scroll",
                {
                    "collection_name": table,
                    "scroll_filter": flt,
                    "limit": 256,
                    "offset": offset,
                    "with_payload": True,
                    "with_vectors": False,
                },
            )
            hits.extend(_hit(p) for p in points)
            if offset is None or (need is not None and len(hits) >= need):
                break
            if len(hits) > MAX_SCAN_POINTS:
                raise VectorQueryError(
                    f"collection scan exceeds {MAX_SCAN_POINTS} points; add a filter or LIMIT"
                )
        hits = sort_hits(vq, hits)[vq.offset :]
    if vq.limit is not None:
        hits = hits[: vq.limit]
    return shape_rows(vq, hits)


def _version_plan() -> Any:
    info = yield ("http.service_api.root", {})
    return info


def _server_version(info: Any) -> str:
    version = getattr(info, "version", None)
    return f"Qdrant {version}" if version else "Qdrant"


def qdrant_introspect_plan() -> Any:
    """Describe every collection from the server: vector config, payload fields, ids."""
    listing = yield ("get_collections", {})
    tables: dict[str, dict[str, Any]] = {}
    for coll in listing.collections:
        name = coll.name
        info = yield ("get_collection", {"collection_name": name})
        points, _ = yield (
            "scroll",
            {
                "collection_name": name,
                "limit": 50,
                "with_payload": True,
                "with_vectors": False,
            },
        )
        declared = {
            key: str(getattr(getattr(schema, "data_type", None), "value", "unknown"))
            for key, schema in (info.payload_schema or {}).items()
        }
        payload = payload_columns([p.payload or {} for p in points], declared)
        id_type = "integer" if points and isinstance(points[0].id, int) else "uuid"
        cols = [
            {
                "name": "id",
                "data_type": id_type,
                "is_nullable": False,
                "is_primary": True,
                "comment": None,
            }
        ]
        vectors = info.config.params.vectors
        named = vectors if isinstance(vectors, dict) else {"vector": vectors}
        for vname, vp in named.items():
            dist = getattr(vp.distance, "value", vp.distance)
            cols.append(
                {
                    "name": vname,
                    "data_type": "vector",
                    "is_nullable": False,
                    "is_primary": False,
                    "comment": f"dimension={vp.size}; distance={dist}",
                }
            )
        cols.extend(
            {
                "name": key,
                "data_type": typ,
                "is_nullable": True,
                "is_primary": False,
                "comment": None,
            }
            for key, typ in payload.items()
        )
        tables[name] = {
            "name": name,
            "columns": cols,
            "has_user_id": "user_id" in payload,
            "user_col": "user_id" if "user_id" in payload else None,
            "comment": None,
        }
    return {"tables": tables, "foreign_keys": [], "relationships": []}


class _QdrantCursorAdapter:
    """Adapts a QdrantClient into a standard DB-API cursor interface."""

    def __init__(self, connection: Any) -> None:
        self.conn = connection
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if _is_real_client(self.conn) and not clean_sql.startswith("GET /"):
            vq = parse_vector_sql(clean_sql, params)
            self.description, self._rows = drive_sync(qdrant_plan(vq), self.conn)
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
                    getattr(
                        p, "payload", p.get("payload") if isinstance(p, dict) else {}
                    ),
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
        version = "Qdrant"
        if hasattr(conn, "get_collections"):
            conn.get_collections()
        if _is_real_client(conn):
            with contextlib.suppress(Exception):
                version = _server_version(drive_sync(_version_plan(), conn))
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": version,
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = self.connect()
        if _is_real_client(conn):
            try:
                raw = drive_sync(qdrant_introspect_plan(), conn)
                return normalize_schema_snapshot(raw, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Qdrant schema: {exc}"
                ) from exc
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
        if _is_real_client(conn):
            vq = parse_vector_sql(sql, params)
            desc, rows = await drive_async(qdrant_plan(vq), conn)
            names = [d[0] for d in desc]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return names, [dict(zip(names, r, strict=False)) for r in rows], latency_ms
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
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            if hasattr(cur, "close"):
                cur.close()

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        version = "Qdrant"
        if hasattr(conn, "get_collections"):
            res = conn.get_collections()
            if hasattr(res, "__await__"):
                await res
        if _is_real_client(conn):
            with contextlib.suppress(Exception):
                version = _server_version(await drive_async(_version_plan(), conn))
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": version,
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        if _is_real_client(conn):
            try:
                raw = await drive_async(qdrant_introspect_plan(), conn)
                return normalize_schema_snapshot(raw, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Qdrant schema: {exc}"
                ) from exc
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
