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
    introspect_milvus,
    normalize_schema_snapshot,
)
from query_builder.connectors.registry import register_connector

#: Milvus caps ``offset + limit`` of a single query/search at 16384
MAX_WINDOW = 16_384
_MILVUS_TYPES = {
    "BOOL": "boolean",
    "INT8": "integer",
    "INT16": "integer",
    "INT32": "integer",
    "INT64": "integer",
    "FLOAT": "float",
    "DOUBLE": "float",
    "VARCHAR": "string",
    "STRING": "string",
    "JSON": "json",
    "ARRAY": "array",
    "FLOAT_VECTOR": "vector",
    "BINARY_VECTOR": "vector",
    "FLOAT16_VECTOR": "vector",
    "BFLOAT16_VECTOR": "vector",
    "SPARSE_FLOAT_VECTOR": "vector",
}
_METRICS = {"COSINE": "cosine", "L2": "euclidean", "IP": "dot"}


def _is_real_client(conn: Any) -> bool:
    return type(conn).__module__.startswith("pymilvus")


def _lit(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    raise VectorQueryError(f"unsupported filter value {value!r}")


def _milvus_expr(conds: list[Any]) -> str:
    parts: list[str] = []
    for c in conds:
        col = c.column
        if c.op == "=":
            parts.append(f"{col} == {_lit(c.value)}")
        elif c.op in ("!=", ">", ">=", "<", "<="):
            parts.append(f"{col} {c.op} {_lit(c.value)}")
        elif c.op == "in":
            parts.append(f"{col} in [{', '.join(_lit(v) for v in c.value)}]")
        elif c.op == "not_in":
            parts.append(f"{col} not in [{', '.join(_lit(v) for v in c.value)}]")
        elif c.op == "is_null":
            parts.append(f"{col} is null")
        else:  # is_not_null
            parts.append(f"{col} is not null")
    return " and ".join(parts)


def _field_type(field: dict[str, Any]) -> str:
    t = field.get("type")
    return str(getattr(t, "name", t))


def _resolve_name(names: list[str], wanted: str) -> str:
    for n in names:
        if n == wanted or n.lower() == wanted.lower():
            return n
    raise VectorQueryError(
        f"collection {wanted!r} does not exist; have {sorted(names)}"
    )


def _loaded(state: Any) -> bool:
    raw = state.get("state") if isinstance(state, dict) else state
    return "loaded" in str(getattr(raw, "name", raw)).lower()


def milvus_plan(vq: VectorQuery) -> Any:
    names = yield ("list_collections", {})
    name = _resolve_name(list(names), vq.table)
    desc = yield ("describe_collection", {"collection_name": name})
    fields = desc.get("fields", [])
    pk = next((f["name"] for f in fields if f.get("is_primary")), "id")
    vec_fields = [f["name"] for f in fields if _field_type(f).endswith("VECTOR")]
    state = yield ("get_load_state", {"collection_name": name})
    if not _loaded(state):  # searching needs the collection in memory
        yield ("load_collection", {"collection_name": name})
    expr = _milvus_expr(vq.conds)
    wanted = vq.wanted_payload_fields()
    out = ["*"] if wanted is None else [w for w in wanted if w != "_distance"]
    if pk not in out and "*" not in out:
        out.append(pk)

    if vq.count_only and not vq.is_search:
        res = yield (
            "query",
            {"collection_name": name, "filter": expr, "output_fields": ["count(*)"]},
        )
        return [("count",)], [[res[0]["count(*)"]]]

    hits: list[dict[str, Any]] = []
    if vq.is_search:
        if any(n != "_distance" or desc_ for n, desc_ in vq.order_by):
            raise VectorQueryError(
                "a vector search can only be ordered by distance, ascending"
            )
        anns = (
            vq.vector_column
            if vq.vector_column in vec_fields
            else (vec_fields or ["vector"])[0]
        )
        index_names = yield (
            "list_indexes",
            {"collection_name": name, "field_name": anns},
        )
        if not index_names:
            raise VectorQueryError(f"collection {name} has no index on {anns}")
        index = yield (
            "describe_index",
            {"collection_name": name, "index_name": index_names[0]},
        )
        engine_metric = str(index.get("metric_type", "COSINE")).upper()
        want = MAX_WINDOW if vq.count_only else (vq.limit or 10) + vq.offset
        res = yield (
            "search",
            {
                "collection_name": name,
                "data": [vq.vector],
                "anns_field": anns,
                "filter": expr,
                "limit": min(want, MAX_WINDOW),
                "output_fields": out,
            },
        )
        for hit in res[0]:
            raw = float(hit["distance"])
            if engine_metric == "L2":  # Milvus reports the squared distance
                raw = raw**0.5
            d = distance_from_score(
                vq.metric or "cosine", raw, _METRICS.get(engine_metric, engine_metric)
            )
            if vq.max_distance is None or d <= vq.max_distance:
                hits.append(
                    {
                        pk: hit.get("id"),
                        "id": hit.get("id"),
                        **hit.get("entity", {}),
                        "_distance": d,
                    }
                )
        if vq.count_only:
            return [("count",)], [[len(hits)]]
        hits = hits[vq.offset :]
    else:
        if vq.order_by:  # Milvus cannot order a query: read the window and sort here
            res = yield (
                "query",
                {
                    "collection_name": name,
                    "filter": expr,
                    "output_fields": out,
                    "limit": MAX_WINDOW,
                },
            )
            hits = sort_hits(vq, [{"id": r.get(pk), **r} for r in res])[vq.offset :]
        else:
            lim = min((vq.limit or MAX_WINDOW), MAX_WINDOW - vq.offset)
            res = yield (
                "query",
                {
                    "collection_name": name,
                    "filter": expr,
                    "output_fields": out,
                    "limit": lim,
                    "offset": vq.offset,
                },
            )
            hits = [{"id": r.get(pk), **r} for r in res]
    if vq.limit is not None:
        hits = hits[: vq.limit]
    return shape_rows(vq, hits)


def milvus_introspect_plan() -> Any:
    names = yield ("list_collections", {})
    tables: dict[str, dict[str, Any]] = {}
    for name in names:
        desc = yield ("describe_collection", {"collection_name": name})
        state = yield ("get_load_state", {"collection_name": name})
        sample: list[dict[str, Any]] = []
        if _loaded(state):  # never load a collection just to look at it
            sample = yield (
                "query",
                {
                    "collection_name": name,
                    "filter": "",
                    "output_fields": ["*"],
                    "limit": 20,
                },
            )
        declared: dict[str, str] = {}
        cols: list[dict[str, Any]] = []
        for f in desc.get("fields", []):
            typ = _MILVUS_TYPES.get(_field_type(f), _field_type(f).lower())
            comment = None
            dim = (f.get("params") or {}).get("dim")
            if dim:
                comment = f"dimension={dim}"
            declared[f["name"]] = typ
            cols.append(
                {
                    "name": f["name"],
                    "data_type": typ,
                    "is_nullable": bool(f.get("nullable", False))
                    and not f.get("is_primary"),
                    "is_primary": bool(f.get("is_primary")),
                    "comment": comment,
                }
            )
        for key, typ in payload_columns(sample, {}).items():  # dynamic fields
            if key not in declared:
                cols.append(
                    {
                        "name": key,
                        "data_type": typ,
                        "is_nullable": True,
                        "is_primary": False,
                        "comment": "dynamic field",
                    }
                )
        tables[name] = {
            "name": name,
            "columns": cols,
            "has_user_id": "user_id" in declared,
            "user_col": "user_id" if "user_id" in declared else None,
            "comment": desc.get("description") or None,
        }
    return {"tables": tables, "foreign_keys": [], "relationships": []}


def _version_plan() -> Any:
    version = yield ("get_server_version", {})
    return version


class _MilvusCursorAdapter:
    """Adapts a MilvusClient into a standard DB-API cursor interface."""

    def __init__(self, connection: Any) -> None:
        self.conn = connection
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if _is_real_client(self.conn) and not clean_sql.startswith("list_collections"):
            vq = parse_vector_sql(clean_sql, params)
            self.description, self._rows = drive_sync(milvus_plan(vq), self.conn)
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
        version = "Milvus"
        if hasattr(conn, "list_collections"):
            conn.list_collections()
        if _is_real_client(conn):
            with contextlib.suppress(Exception):
                version = f"Milvus {drive_sync(_version_plan(), conn)}"
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
                raw = drive_sync(milvus_introspect_plan(), conn)
                return normalize_schema_snapshot(raw, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Milvus schema: {exc}"
                ) from exc
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
            if hasattr(driver, "AsyncMilvusClient"):
                self._connection = driver.AsyncMilvusClient(
                    uri=self.uri, token=self.token, **self.config
                )
            elif hasattr(driver, "MilvusClient"):
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
        if _is_real_client(conn):
            vq = parse_vector_sql(sql, params)
            desc, rows = await drive_async(milvus_plan(vq), conn)
            names = [d[0] for d in desc]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return names, [dict(zip(names, r, strict=False)) for r in rows], latency_ms
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
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            if hasattr(cur, "close"):
                cur.close()

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        version = "Milvus"
        if hasattr(conn, "list_collections"):
            res = conn.list_collections()
            if hasattr(res, "__await__"):
                await res
        if _is_real_client(conn):
            with contextlib.suppress(Exception):
                version = f"Milvus {await drive_async(_version_plan(), conn)}"
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
                raw = await drive_async(milvus_introspect_plan(), conn)
                return normalize_schema_snapshot(raw, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Milvus schema: {exc}"
                ) from exc
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
