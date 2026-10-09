"""
Google Cloud Bigtable Wide-Column NoSQL Database Connector.
===========================================================
Provides Google Cloud Bigtable connectivity via google-cloud-bigtable,
dual sync and async execution protocols, and table/column-family introspection.

Bigtable's data API has no query language, so the connector runs a documented SQL SUBSET
(:mod:`query_builder.connectors._sql_subset`) over ``read_rows``:

* the table is the ``FROM`` name; the columns are ``row_key`` and one column per
  ``"family.qualifier"`` (quote it as a single identifier), valued with the LATEST cell
  decoded as UTF-8 text (non-text bytes come back as ``0x...`` hex);
* ``row_key`` predicates (``=``, ranges, ``LIKE 'prefix%'``) are pushed down to the server as a
  key range; every predicate (including those on cells) is then re-applied client side, and
  ``ORDER BY``/``OFFSET`` are applied client side, so results are exact but a predicate on a
  cell column scans the key range;
* anything else raises ``UnsupportedQuery`` instead of being approximated.

The async class runs the same synchronous client in a worker thread (the Bigtable admin
API used for table listing exists only in the synchronous client).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from typing import Any

from query_builder.connectors._sql_subset import (
    Predicate,
    SubsetPlan,
    parse_select_subset,
)
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_bigtable
from query_builder.connectors.registry import register_connector

ROW_KEY = "row_key"


def cell_text(value: Any) -> Any:
    """Cell bytes as text; bytes that are not UTF-8 are returned as ``0x...`` hex."""
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + bytes(value).hex()
    return value


def _row_record(row: Any) -> dict[str, Any]:
    key = row.row_key
    record: dict[str, Any] = {ROW_KEY: cell_text(key)}
    for family, qualifiers in (getattr(row, "cells", None) or {}).items():
        for qualifier, cells in qualifiers.items():
            if cells:
                name = f"{family}.{cell_text(qualifier)}"
                record[name] = cell_text(cells[0].value)  # latest version first
    return record


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _compare(left: Any, op: str, right: Any) -> bool:
    ln, rn = _number(left), _number(right)
    a, b = (ln, rn) if ln is not None and rn is not None else (str(left), str(right))
    return {
        "=": a == b,
        "!=": a != b,
        "<": a < b,  # type: ignore[operator]
        "<=": a <= b,  # type: ignore[operator]
        ">": a > b,  # type: ignore[operator]
        ">=": a >= b,  # type: ignore[operator]
    }[op]


def _matches(record: dict[str, Any], pred: Predicate) -> bool:
    value = record.get(pred.column)
    if pred.op == "is-null":
        return value is None
    if pred.op == "is-not-null":
        return value is not None
    if value is None:
        return False
    if pred.op == "prefix":
        return str(value).startswith(str(pred.value))
    if pred.op == "in":
        return any(_compare(value, "=", v) for v in pred.value)
    if pred.op == "not-in":
        return not any(_compare(value, "=", v) for v in pred.value)
    return _compare(value, pred.op, pred.value)


def _sort_key(value: Any) -> tuple[int, Any]:
    if value is None:
        return (2, 0)
    number = _number(value)
    return (0, number) if number is not None else (1, str(value))


def _key_range(plan: SubsetPlan) -> dict[str, Any]:
    """Server-side ``read_rows`` key range from the ``row_key`` predicates."""
    kwargs: dict[str, Any] = {}
    for pred in plan.predicates:
        if pred.column != ROW_KEY or pred.op in ("in", "not-in", "is-null", "!="):
            continue
        val = str(pred.value).encode()
        if pred.op == "=":
            kwargs.update(start_key=val, end_key=val, end_inclusive=True)
        elif pred.op == ">=" and "start_key" not in kwargs:
            kwargs["start_key"] = val
        elif pred.op == ">" and "start_key" not in kwargs:
            kwargs["start_key"] = val + b"\x00"
        elif pred.op == "<" and "end_key" not in kwargs:
            kwargs.update(end_key=val, end_inclusive=False)
        elif pred.op == "<=" and "end_key" not in kwargs:
            kwargs.update(end_key=val, end_inclusive=True)
        elif pred.op == "prefix" and "start_key" not in kwargs:
            kwargs["start_key"] = val
            if val:
                kwargs.update(
                    end_key=val[:-1] + bytes([val[-1] + 1]) if val[-1] < 255 else None,
                    end_inclusive=False,
                )
    return kwargs


def read_records(instance: Any, plan: SubsetPlan) -> list[dict[str, Any]]:
    """Rows of ``plan`` as ``{column: value}`` records (exact, see module docstring)."""
    kwargs = _key_range(plan)
    pushdown_limit = (
        plan.limit + plan.offset
        if plan.limit is not None and not plan.order_by and len(plan.predicates) == 0
        else None
    )
    if pushdown_limit is not None:
        kwargs["limit"] = pushdown_limit
    table = instance.table(plan.table)
    with contextlib.suppress(ImportError):  # latest cell version only
        from google.cloud.bigtable import row_filters

        kwargs["filter_"] = row_filters.CellsColumnLimitFilter(1)
    rows = table.read_rows(**kwargs)
    records = [_row_record(r) for r in rows]
    records = [r for r in records if all(_matches(r, p) for p in plan.predicates)]
    for col, desc in reversed(plan.order_by):
        records.sort(key=lambda r, c=col: _sort_key(r.get(c)), reverse=desc)
    end = None if plan.limit is None else plan.offset + plan.limit
    return records[plan.offset : end]


def shape_records(
    plan: SubsetPlan, records: list[dict[str, Any]]
) -> tuple[list[tuple[str]], list[list[Any]]]:
    if plan.count_star:
        return [(plan.count_alias,)], [[len(records)]]
    if plan.columns is None:
        names = list(dict.fromkeys(k for r in records for k in r)) or [ROW_KEY]
        out_names = names
    else:
        names, out_names = plan.columns, plan.out_names
    return [(n,) for n in out_names], [[r.get(n) for n in names] for r in records]


class _BigtableCursorAdapter:
    """Adapts a Bigtable Client or Instance into a standard DB-API cursor interface."""

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
        elif clean_sql == "list_tables" and hasattr(self.conn, "list_tables"):
            tbls = self.conn.list_tables()
            self.description = [("table_id",)]
            self._rows = [[getattr(t, "table_id", str(t))] for t in tbls]
        elif hasattr(self.conn, "table"):
            if clean_sql.upper() == "SELECT 1":
                self.description, self._rows = [("val",)], [[1]]
                return
            plan = parse_select_subset(clean_sql, params)
            self.description, self._rows = shape_records(
                plan, read_records(self.conn, plan)
            )
        elif hasattr(self.conn, "execute_query"):
            res = (
                self.conn.execute_query(clean_sql, params)
                if params
                else self.conn.execute_query(clean_sql)
            )
            self.description = getattr(res, "description", None)
            if hasattr(res, "fetchall"):
                self._rows = list(res.fetchall())
            elif isinstance(res, (list, tuple)):
                self._rows = list(res)
            else:
                self._rows = []
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


def _import_driver() -> Any:
    for mod_name in ("google.cloud.bigtable", "google.cloud.bigtable_v2"):
        try:
            return __import__(mod_name, fromlist=["Client"])
        except ImportError:
            continue
    raise DriverNotInstalledError(
        "'google-cloud-bigtable' is not installed. "
        "Install with: pip install 'query-builder-engine[bigtable]'"
    )


def _open(
    driver: Any,
    project_id: str | None,
    instance_id: str | None,
    app_profile_id: str | None,
    admin: bool,
    config: dict[str, Any],
) -> Any:
    client_cls = getattr(driver, "Client", driver)
    client = client_cls(project=project_id, admin=admin, **config)
    if instance_id and hasattr(client, "instance"):
        return client.instance(instance_id, app_profile_id=app_profile_id)
    return client


@register_connector("bigtable", aliases=["google_bigtable", "gcp_bigtable"])
class BigtableConnector(BaseConnector):
    """Connector for Google Cloud Bigtable wide-column database."""

    dialect_name = "bigtable"

    def __init__(
        self,
        project_id: str | None = None,
        instance_id: str | None = None,
        app_profile_id: str | None = None,
        admin: bool = False,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.project_id = project_id
        self.instance_id = instance_id
        self.app_profile_id = app_profile_id
        self.admin = admin

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = _import_driver()
        try:
            self._connection = _open(
                driver,
                self.project_id,
                self.instance_id,
                self.app_profile_id,
                self.admin,
                self.config,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Google Cloud Bigtable: {exc}"
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
            adapter = _BigtableCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "list_tables"):
            list(conn.list_tables())
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Google Cloud Bigtable",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_bigtable(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Bigtable schema: {exc}"
                ) from exc


@register_connector(
    "async_bigtable", aliases=["async_google_bigtable", "async_gcp_bigtable"]
)
class AsyncBigtableConnector(AsyncBaseConnector):
    """Asynchronous connector for Google Cloud Bigtable (sync client in a worker thread)."""

    dialect_name = "bigtable"

    def __init__(
        self,
        project_id: str | None = None,
        instance_id: str | None = None,
        app_profile_id: str | None = None,
        admin: bool = False,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.project_id = project_id
        self.instance_id = instance_id
        self.app_profile_id = app_profile_id
        self.admin = admin

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = _import_driver()
        try:
            self._connection = await asyncio.to_thread(
                _open,
                driver,
                self.project_id,
                self.instance_id,
                self.app_profile_id,
                self.admin,
                self.config,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Google Cloud Bigtable: {exc}"
            ) from exc

    @staticmethod
    def _run_blocking(
        conn: Any, sql: str, params: list[Any] | None
    ) -> tuple[list[tuple[str, ...]], list[list[Any]]]:
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                if params:
                    cur.execute(sql, params)
                else:
                    cur.execute(sql)
                return list(cur.description or []), list(cur.fetchall() or [])
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        adapter = _BigtableCursorAdapter(conn)
        try:
            adapter.execute(sql, params)
            return list(adapter.description or []), adapter.fetchall() or []
        finally:
            adapter.close()

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        desc, rows = await asyncio.to_thread(self._run_blocking, conn, sql, params)
        col_names = [col[0] for col in desc]
        dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
        return col_names, dict_rows, (time.perf_counter() - start) * 1000.0

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        if hasattr(conn, "list_tables"):
            res = await asyncio.to_thread(conn.list_tables)
            if inspect.isawaitable(res):  # an async admin client
                await res
            else:
                list(res)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Google Cloud Bigtable",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()

        def _blocking() -> dict[str, Any]:
            cur = (
                conn.cursor()
                if hasattr(conn, "cursor")
                else _BigtableCursorAdapter(conn)
            )
            try:
                return introspect_bigtable(cur, filter_sensitive=filter_sensitive)
            finally:
                if hasattr(cur, "close"):
                    cur.close()

        try:
            return await asyncio.to_thread(_blocking)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Bigtable schema: {exc}"
            ) from exc
