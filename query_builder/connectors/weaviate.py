"""
Weaviate Modular Vector Database & Knowledge Graph Connector.
=============================================================
Provides Weaviate connectivity via official weaviate-client v4+,
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
    drive_async,
    drive_sync,
    parse_vector_sql,
    payload_columns,
    shape_rows,
)
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import (
    introspect_weaviate,
    normalize_schema_snapshot,
)
from query_builder.connectors.registry import register_connector

_WEAVIATE_TYPES = {
    "text": "string",
    "text[]": "array",
    "int": "integer",
    "int[]": "array",
    "number": "float",
    "number[]": "array",
    "boolean": "boolean",
    "boolean[]": "array",
    "date": "timestamp",
    "uuid": "uuid",
    "object": "json",
    "blob": "binary",
}


def _is_real_client(conn: Any) -> bool:
    return type(conn).__module__.startswith("weaviate")


def _endpoint(url: str) -> tuple[str, int, bool]:
    """``http://host:port`` -> (host, port, secure); a bare ``host[:port]`` is accepted too."""
    from urllib.parse import urlparse

    parsed = urlparse(url if "//" in url else f"//{url}")
    secure = parsed.scheme == "https"
    return (
        parsed.hostname or "localhost",
        parsed.port or (443 if secure else 8080),
        secure,
    )


def _connect_kwargs(
    url: str, config: dict[str, Any], api_key: str | None
) -> dict[str, Any]:
    """Keyword arguments for ``weaviate.connect_to_custom`` / ``use_async_with_custom``."""
    host, port, secure = _endpoint(url)
    cfg = dict(config)
    kwargs: dict[str, Any] = {
        "http_host": cfg.pop("http_host", host),
        "http_port": cfg.pop("http_port", port),
        "http_secure": cfg.pop("http_secure", secure),
        "grpc_host": cfg.pop("grpc_host", host),
        "grpc_port": cfg.pop("grpc_port", 50051),
        "grpc_secure": cfg.pop("grpc_secure", secure),
    }
    if api_key and "auth_credentials" not in cfg:
        from weaviate.classes.init import Auth

        kwargs["auth_credentials"] = Auth.api_key(api_key)
    kwargs.update(cfg)
    return kwargs


def _weaviate_filter(conds: list[Any]) -> Any:
    if not conds:
        return None
    from weaviate.classes.query import Filter

    parts: list[Any] = []
    for c in conds:
        prop = Filter.by_property(c.column)
        if c.op == "=":
            parts.append(prop.equal(c.value))
        elif c.op == "!=":
            parts.append(prop.not_equal(c.value))
        elif c.op == ">":
            parts.append(prop.greater_than(c.value))
        elif c.op == ">=":
            parts.append(prop.greater_or_equal(c.value))
        elif c.op == "<":
            parts.append(prop.less_than(c.value))
        elif c.op == "<=":
            parts.append(prop.less_or_equal(c.value))
        elif c.op == "in":
            parts.append(prop.contains_any(list(c.value)))
        elif c.op == "not_in":
            parts.extend(Filter.by_property(c.column).not_equal(v) for v in c.value)
        elif c.op == "is_null":
            parts.append(prop.is_none(True))
        else:  # is_not_null
            parts.append(prop.is_none(False))
    return parts[0] if len(parts) == 1 else Filter.all_of(parts)


def _vector_config(cfg: Any) -> Any:
    index = getattr(cfg, "vector_index_config", None)
    if index is None:
        named = getattr(cfg, "vector_config", None) or {}
        for entry in named.values():
            index = getattr(entry, "vector_index_config", None)
            break
    return index


def _metric_of(cfg: Any) -> str:
    dm = getattr(_vector_config(cfg), "distance_metric", None)
    return str(getattr(dm, "value", dm) or "cosine")


def _resolve_name(listing: Any, wanted: str) -> str:
    names = list(listing.keys()) if isinstance(listing, dict) else list(listing)
    for n in names:
        if n == wanted or n.lower() == wanted.lower():
            return n
    raise VectorQueryError(
        f"collection {wanted!r} does not exist; have {sorted(names)}"
    )


def weaviate_plan(vq: VectorQuery) -> Any:
    from weaviate.classes.query import MetadataQuery, Sort

    listing = yield ("collections.list_all", {})
    name = _resolve_name(listing, vq.table)
    coll = yield ("collections.get", {"name": name})
    flt = _weaviate_filter(vq.conds)
    wanted = vq.wanted_payload_fields()
    props = (
        None if wanted is None else [w for w in wanted if w not in ("id", "_distance")]
    )

    if vq.count_only and not vq.is_search:
        agg = yield (coll.aggregate.over_all, {"filters": flt, "total_count": True})
        return [("count",)], [[agg.total_count]]

    hits: list[dict[str, Any]] = []
    if vq.is_search:
        if any(n != "_distance" or desc for n, desc in vq.order_by):
            raise VectorQueryError(
                "a vector search can only be ordered by distance, ascending"
            )
        cfg = yield (coll.config.get, {})
        engine_metric = _metric_of(cfg)
        wmetric = {"cosine": "cosine", "dot": "dot", "l2-squared": "euclidean"}.get(
            engine_metric, engine_metric
        )
        if wmetric != vq.metric:
            raise VectorQueryError(
                f"query asks for {vq.metric} distance but the collection uses {engine_metric}"
            )
        want = 10_000 if vq.count_only else vq.limit or 10
        res = yield (
            coll.query.near_vector,
            {
                "near_vector": vq.vector,
                "limit": want,
                "offset": 0 if vq.count_only else vq.offset,
                "filters": flt,
                "return_metadata": MetadataQuery(distance=True),
                "return_properties": props,
            },
        )
        for obj in res.objects:
            d = obj.metadata.distance
            if engine_metric == "l2-squared":
                d = float(d) ** 0.5
            if vq.max_distance is None or d <= vq.max_distance:
                hits.append({"id": str(obj.uuid), **obj.properties, "_distance": d})
        if vq.count_only:
            return [("count",)], [[len(hits)]]
        return shape_rows(vq, hits)

    sort = None
    for col, desc in vq.order_by:
        sort = (
            Sort.by_property(col, ascending=not desc)
            if sort is None
            else sort.by_property(col, ascending=not desc)
        )
    res = yield (
        coll.query.fetch_objects,
        {
            "limit": vq.limit or 10_000,
            "offset": vq.offset,
            "filters": flt,
            "sort": sort,
            "return_properties": props,
        },
    )
    hits = [{"id": str(o.uuid), **o.properties} for o in res.objects]
    return shape_rows(vq, hits)


def weaviate_introspect_plan() -> Any:
    listing = yield ("collections.list_all", {})
    tables: dict[str, dict[str, Any]] = {}
    for name in listing:
        coll = yield ("collections.get", {"name": name})
        cfg = yield (coll.config.get, {})
        sample = yield (coll.query.fetch_objects, {"limit": 1, "include_vector": True})
        dim = None
        if sample.objects:
            vec = sample.objects[0].vector
            first = next(iter(vec.values()), None) if isinstance(vec, dict) else None
            dim = len(first) if first is not None else None
        cols: list[dict[str, Any]] = [
            {
                "name": "id",
                "data_type": "uuid",
                "is_nullable": False,
                "is_primary": True,
                "comment": None,
            },
            {
                "name": "vector",
                "data_type": "vector",
                "is_nullable": False,
                "is_primary": False,
                "comment": f"distance={_metric_of(cfg)}"
                + (f"; dimension={dim}" if dim else ""),
            },
        ]
        declared = {
            p.name: _WEAVIATE_TYPES.get(
                str(getattr(p.data_type, "value", p.data_type)), "unknown"
            )
            for p in cfg.properties
        }
        for key, typ in payload_columns([], declared).items():
            cols.append(
                {
                    "name": key,
                    "data_type": typ,
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                }
            )
        tables[name] = {
            "name": name,
            "columns": cols,
            "has_user_id": "user_id" in declared,
            "user_col": "user_id" if "user_id" in declared else None,
            "comment": None,
        }
    return {"tables": tables, "foreign_keys": [], "relationships": []}


def _version_plan() -> Any:
    meta = yield ("get_meta", {})
    return meta


def _server_version(meta: Any) -> str:
    version = meta.get("version") if isinstance(meta, dict) else None
    return f"Weaviate {version}" if version else "Weaviate"


class _WeaviateCursorAdapter:
    """Adapts a WeaviateClient into a DB-API cursor interface."""

    def __init__(self, connection: Any) -> None:
        self.conn = connection
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if _is_real_client(self.conn) and not clean_sql.startswith(
            "collections.list_all"
        ):
            vq = parse_vector_sql(clean_sql, params)
            self.description, self._rows = drive_sync(weaviate_plan(vq), self.conn)
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
        elif clean_sql.startswith("collections.list_all") and hasattr(
            self.conn, "collections"
        ):
            classes = self.conn.collections.list_all()
            names = (
                list(classes.keys())
                if isinstance(classes, dict)
                else [str(c) for c in classes]
            )
            self.description = [("class_name",)]
            self._rows = [[str(name)] for name in names]
        elif (
            hasattr(self.conn, "collections")
            and hasattr(self.conn.collections, "get")
            and (
                params is not None
                and len(params) > 0
                and (
                    "distance" in clean_sql.lower()
                    or "vector" in clean_sql.lower()
                    or "search" in clean_sql.lower()
                    or "score" in clean_sql.lower()
                )
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
            collection = self.conn.collections.get(coll)
            res = collection.query.near_vector(near_vector=vector, limit=10)
            objects = getattr(res, "objects", res) if hasattr(res, "objects") else res
            self.description = [("uuid",), ("properties",), ("metadata",)]
            self._rows = [
                [
                    str(getattr(obj, "uuid", "")),
                    getattr(obj, "properties", {}),
                    getattr(obj, "metadata", {}),
                ]
                for obj in (objects if isinstance(objects, list) else [])
            ]
        elif hasattr(self.conn, "graphql") and hasattr(self.conn.graphql, "raw_query"):
            res = self.conn.graphql.raw_query(clean_sql)
            data = getattr(res, "get", lambda _: {})("data", {})
            self.description = [("data",)]
            self._rows = [[str(data)]]
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


@register_connector("weaviate", aliases=["weaviate_db", "weaviate_vector"])
class WeaviateConnector(BaseConnector):
    """Connector for Weaviate modular vector database and knowledge graph."""

    dialect_name = "weaviate"

    def __init__(
        self,
        url: str = "http://localhost:8080",
        api_key: str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.url = url
        self.api_key = api_key

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("weaviate", "weaviate.client"):
            try:
                driver = __import__(
                    mod_name,
                    fromlist=["connect_to_local", "connect_to_custom", "Client"],
                )
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'weaviate-client' is not installed. "
                "Install with: pip install 'query-builder-engine[weaviate]'"
            )

        try:
            if hasattr(driver, "connect_to_custom"):
                self._connection = driver.connect_to_custom(
                    **_connect_kwargs(self.url, self.config, self.api_key)
                )
            elif hasattr(driver, "Client"):
                self._connection = driver.Client(url=self.url, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Weaviate: {exc}"
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
            adapter = _WeaviateCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        version = "Weaviate"
        if hasattr(conn, "is_ready"):
            if not conn.is_ready():
                raise ConnectionFailedError("Weaviate reports it is not ready")
        elif hasattr(conn, "collections"):
            conn.collections.list_all()
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
                raw = drive_sync(weaviate_introspect_plan(), conn)
                return normalize_schema_snapshot(raw, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Weaviate schema: {exc}"
                ) from exc
        with self.get_cursor() as cur:
            try:
                return introspect_weaviate(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Weaviate schema: {exc}"
                ) from exc


@register_connector(
    "async_weaviate", aliases=["async_weaviate_db", "async_weaviate_vector"]
)
class AsyncWeaviateConnector(AsyncBaseConnector):
    """Asynchronous connector for Weaviate vector database."""

    dialect_name = "weaviate"

    def __init__(
        self,
        url: str = "http://localhost:8080",
        api_key: str | None = None,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.url = url
        self.api_key = api_key

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("weaviate", "weaviate.client"):
            try:
                driver = __import__(
                    mod_name, fromlist=["use_async", "connect_to_custom", "Client"]
                )
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'weaviate-client' is not installed. "
                "Install with: pip install 'query-builder-engine[weaviate]'"
            )

        try:
            if hasattr(driver, "use_async_with_custom"):
                client = driver.use_async_with_custom(
                    **_connect_kwargs(self.url, self.config, self.api_key)
                )
                await client.connect()
                self._connection = client
            elif hasattr(driver, "connect_to_custom"):
                self._connection = driver.connect_to_custom(
                    **_connect_kwargs(self.url, self.config, self.api_key)
                )
            elif hasattr(driver, "Client"):
                self._connection = driver.Client(url=self.url, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Weaviate: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if _is_real_client(conn):
            vq = parse_vector_sql(sql, params)
            desc, rows = await drive_async(weaviate_plan(vq), conn)
            names = [d[0] for d in desc]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return names, [dict(zip(names, r, strict=False)) for r in rows], latency_ms
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _WeaviateCursorAdapter(conn)

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
        version = "Weaviate"
        if hasattr(conn, "is_ready"):
            res = conn.is_ready()
            if hasattr(res, "__await__"):
                res = await res
            if res is False:
                raise ConnectionFailedError("Weaviate reports it is not ready")
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
                raw = await drive_async(weaviate_introspect_plan(), conn)
                return normalize_schema_snapshot(raw, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Weaviate schema: {exc}"
                ) from exc
        cur = conn.cursor() if hasattr(conn, "cursor") else _WeaviateCursorAdapter(conn)
        try:
            return introspect_weaviate(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Weaviate schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
