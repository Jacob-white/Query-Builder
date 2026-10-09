"""
Google Cloud Firestore Document Database Connector.
===================================================
Provides Google Cloud Firestore connectivity via google-cloud-firestore,
dual sync and async execution protocols, and collection schema introspection.

Firestore has no SQL.  The connector runs a documented SQL SUBSET (see
:mod:`query_builder.connectors._sql_subset`) by translating it to Firestore structured
queries: one collection, a projection, AND-ed simple predicates, ``ORDER BY``,
``LIMIT``/``OFFSET`` and ``COUNT(*)``.  A statement outside the subset raises
``UnsupportedQuery``; it is never approximated.  The document id is exposed as column
``id`` unless the documents carry an ``id`` field of their own.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from query_builder.connectors._sql_subset import (
    SubsetPlan,
    UnsupportedQuery,
    parse_select_subset,
)
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import (
    firestore_schema_steps,
    introspect_firestore,
)
from query_builder.connectors.registry import register_connector

_OPS = {"=": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


def _plain(value: Any) -> Any:
    """Firestore value as a plain value (references and geo points become strings)."""
    if value is None or isinstance(value, (str, int, float, bool, bytes)):
        return value
    if hasattr(value, "isoformat"):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    path = getattr(value, "path", None)  # DocumentReference
    return str(path) if path else str(value)


def build_query(client: Any, plan: SubsetPlan) -> Any:
    """Firestore ``Query`` for ``plan`` (works for the sync and the async client)."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    query = client.collection(plan.table)
    for pred in plan.predicates:
        col, op, val = pred.column, pred.op, pred.value
        if op in _OPS:
            filters = [(_OPS[op], val)]
        elif op in ("in", "not-in"):
            filters = [(op, list(val))]
        elif op == "is-null":
            filters = [("==", None)]
        elif op == "is-not-null":
            filters = [("!=", None)]
        elif op == "prefix":
            filters = [(">=", val), ("<=", val + "")]
        else:  # pragma: no cover - parse_select_subset only yields the ops above
            raise UnsupportedQuery(f"unsupported operator {op}")
        for fop, fval in filters:
            query = query.where(filter=FieldFilter(col, fop, fval))
    for col, desc in plan.order_by:
        query = query.order_by(col, direction="DESCENDING" if desc else "ASCENDING")
    if plan.offset:
        query = query.offset(plan.offset)
    if plan.limit is not None:
        query = query.limit(plan.limit)
    return query


def shape_documents(
    plan: SubsetPlan, docs: list[Any]
) -> tuple[list[tuple[str]], list[list[Any]]]:
    """Documents -> (description, rows) following the projection of ``plan``."""
    records: list[dict[str, Any]] = []
    for doc in docs:
        data = {k: _plain(v) for k, v in (doc.to_dict() or {}).items()}
        records.append({"id": doc.id, **data})
    if plan.columns is None:
        names = list(dict.fromkeys(k for r in records for k in r))
        out_names = names
    else:
        names, out_names = plan.columns, plan.out_names
    return (
        [(n,) for n in out_names],
        [[r.get(n) for n in names] for r in records],
    )


def _count_result(res: Any) -> int:
    """First value of a Firestore aggregation result (``[[AggregationResult]]``)."""
    first = res[0][0] if res and isinstance(res[0], (list, tuple)) else res[0]
    return int(first.value)


class _FirestoreCursorAdapter:
    """Adapts a Firestore Client into a standard DB-API cursor interface."""

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
        elif clean_sql.upper() == "SELECT 1":
            self.description, self._rows = [("val",)], [[1]]
        elif (
            clean_sql == "collections" or clean_sql.upper().startswith("SHOW")
        ) and hasattr(self.conn, "collections"):
            colls = self.conn.collections()
            self.description = [("collection_name",)]
            self._rows = [[getattr(c, "id", str(c))] for c in colls]
        elif hasattr(self.conn, "collection"):
            plan = parse_select_subset(clean_sql, params)
            query = build_query(self.conn, plan)
            if plan.count_star:
                value = _count_result(query.count().get())
                self.description, self._rows = [(plan.count_alias,)], [[value]]
            else:
                self.description, self._rows = shape_documents(
                    plan, list(query.stream())
                )
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


@register_connector("firestore", aliases=["google_firestore", "gcp_firestore"])
class FirestoreConnector(BaseConnector):
    """Connector for Google Cloud Firestore document database."""

    dialect_name = "firestore"

    def __init__(
        self,
        project: str | None = None,
        database: str = "(default)",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.project = project
        self.database = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("google.cloud.firestore", "google.cloud.firestore_v1"):
            try:
                driver = __import__(mod_name, fromlist=["Client"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'google-cloud-firestore' is not installed. "
                "Install with: pip install 'query-builder-engine[firestore]'"
            )

        try:
            client_cls = getattr(driver, "Client", driver)
            self._connection = client_cls(
                project=self.project, database=self.database, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Google Cloud Firestore: {exc}"
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
            adapter = _FirestoreCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "collections"):
            list(conn.collections())
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Google Cloud Firestore",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_firestore(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Firestore schema: {exc}"
                ) from exc


@register_connector(
    "async_firestore", aliases=["async_google_firestore", "async_gcp_firestore"]
)
class AsyncFirestoreConnector(AsyncBaseConnector):
    """Asynchronous connector for Google Cloud Firestore."""

    dialect_name = "firestore"

    def __init__(
        self,
        project: str | None = None,
        database: str = "(default)",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.project = project
        self.database = database

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("google.cloud.firestore", "google.cloud.firestore_v1"):
            try:
                driver = __import__(mod_name, fromlist=["AsyncClient", "Client"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'google-cloud-firestore' is not installed. "
                "Install with: pip install 'query-builder-engine[firestore]'"
            )

        try:
            client_cls = getattr(
                driver, "AsyncClient", getattr(driver, "Client", driver)
            )
            self._connection = client_cls(
                project=self.project, database=self.database, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Google Cloud Firestore: {exc}"
            ) from exc

    async def _run(
        self, conn: Any, sql: str, params: list[Any] | None
    ) -> tuple[list[tuple[str, ...]], list[list[Any]]]:
        """One statement on the ASYNC client (awaiting its coroutines and async streams)."""
        clean_sql = sql.strip().rstrip(";").strip()
        if clean_sql.upper() == "SELECT 1":
            return [("val",)], [[1]]
        if clean_sql == "collections":
            return [("collection_name",)], [[c.id] async for c in conn.collections()]
        plan = parse_select_subset(clean_sql, params)
        query = build_query(conn, plan)
        if plan.count_star:
            return [(plan.count_alias,)], [[_count_result(await query.count().get())]]
        docs = [d async for d in query.stream()]
        return shape_documents(plan, docs)

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                if params:
                    cur.execute(sql, params)
                else:
                    cur.execute(sql)
                desc = cur.description or []
                rows = cur.fetchall() or []
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        elif hasattr(conn, "collection") and hasattr(conn, "collections"):
            desc, rows = await self._run(conn, sql, params)
        else:
            adapter = _FirestoreCursorAdapter(conn)
            try:
                adapter.execute(sql, params)
                desc = adapter.description or []
                rows = adapter.fetchall() or []
            finally:
                adapter.close()
        col_names = [col[0] for col in desc]
        dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
        return col_names, dict_rows, (time.perf_counter() - start) * 1000.0

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        if hasattr(conn, "collections"):
            res = conn.collections()
            if hasattr(res, "__aiter__"):
                _ = [c async for c in res]
            elif hasattr(res, "__await__"):
                await res
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Google Cloud Firestore",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        try:
            if hasattr(conn, "collection") and hasattr(conn, "collections"):
                steps = firestore_schema_steps(filter_sensitive)
                statement = next(steps)
                while True:
                    try:
                        desc, rows = await self._run(conn, statement, None)
                    except Exception as exc:  # noqa: BLE001 - handed to the generator
                        statement = steps.throw(exc)
                        continue
                    names = [d[0] for d in desc]
                    statement = steps.send(
                        [dict(zip(names, r, strict=False)) for r in rows]
                    )
            cur = (
                conn.cursor()
                if hasattr(conn, "cursor")
                else _FirestoreCursorAdapter(conn)
            )
            try:
                return introspect_firestore(cur, filter_sensitive=filter_sensitive)
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        except StopIteration as done:
            return done.value  # type: ignore[no-any-return]
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Firestore schema: {exc}"
            ) from exc

