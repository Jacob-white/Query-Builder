"""
Apache Drill Distributed Schema-Free SQL Engine Connector.
==========================================================
Provides Apache Drill connectivity via pydrill / REST / DB-API, dual sync
and async execution protocols, cursor adapters, and catalog schema introspection.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
    QueryExecutionError,
)
from query_builder.connectors.introspection import introspect_drill
from query_builder.connectors.registry import register_connector


def _has_attr(target: Any, attr: str) -> bool:
    if hasattr(target, "_mock_children"):
        if getattr(target, "_mock_methods", None) is not None:
            return hasattr(target, attr)
        return attr in target._mock_children
    return hasattr(target, attr)


def _drill_literal(value: Any) -> str:
    """Render one bound value as a Drill SQL literal (Drill's REST API has no binding)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("non-finite float cannot be bound to Apache Drill")
        return repr(value)
    text = value if isinstance(value, str) else str(value)
    if "\x00" in text:
        raise ValueError("NUL character cannot be bound to Apache Drill")
    # Drill (Calcite) string literals escape a quote by doubling it; backslash is literal.
    return "'" + text.replace("'", "''") + "'"


def inline_params(sql: str, params: list[Any] | tuple[Any, ...] | None) -> str:
    """Substitute ``%s`` placeholders (outside quoted text) with escaped literals.

    The Drill REST endpoint (and so pydrill) accepts only a complete SQL string, so bound
    values are escaped client-side. Placeholders inside string literals or quoted identifiers
    are left alone and the placeholder count must match the parameter count.
    """
    if not params:
        return sql
    values = list(params)
    out: list[str] = []
    i, used, n = 0, 0, len(sql)
    quote = ""
    while i < n:
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:
                    out.append(sql[i + 1])
                    i += 1
                else:
                    quote = ""
        elif ch in ("'", '"', "`"):
            quote = ch
            out.append(ch)
        elif ch == "%" and sql.startswith("%s", i):
            if used >= len(values):
                raise ValueError("more placeholders than bound parameters")
            out.append(_drill_literal(values[used]))
            used += 1
            i += 1
        else:
            out.append(ch)
        i += 1
    if used != len(values):
        raise ValueError(f"{len(values)} parameters supplied for {used} placeholders")
    return "".join(out)


class _DrillCursorAdapter:
    """Adapts a PyDrill client or DB-API connection into a standardized cursor interface."""

    def __init__(
        self,
        client_or_cursor: Any,
        default_schema: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.target = client_or_cursor
        self.default_schema = default_schema
        self.timeout_s = timeout_s
        self.description: list[tuple[Any, ...]] | None = None
        self._rows: list[list[Any]] = []
        self._types: list[str] = []

    # -- pydrill REST -------------------------------------------------------
    def _rest(self, method: str, url: str, **kw: Any) -> Any:
        _response, data, _duration = self.target.perform_request(method, url, **kw)
        return data

    def _rest_query(self, sql: str) -> tuple[list[str], list[Any]]:
        """POST /query.json. Drill answers HTTP 200 + ``queryState: FAILED`` (with no message)
        when a query fails, which pydrill's ``query()`` turns into an empty result: raise."""
        body: dict[str, Any] = {"queryType": "SQL", "query": sql}
        if self.default_schema:
            body["defaultSchema"] = self.default_schema
        try:
            data = self._rest(
                "POST",
                "/query.json",
                params={"request_timeout": self.timeout_s or 300},
                body=body,
            )
        except Exception as exc:
            if "imeout" in type(exc).__name__ or "imed out" in str(exc):
                self._cancel_running(sql)
            raise
        data = data if isinstance(data, dict) else {}
        state = data.get("queryState")
        if state not in (None, "COMPLETED"):
            raise QueryExecutionError(self._failure_message(data, state))
        self._types = [str(t) for t in data.get("metadata", [])]
        return [str(c) for c in data.get("columns", [])], list(data.get("rows", []))

    def _failure_message(self, data: dict[str, Any], state: Any) -> str:
        detail = str(data.get("errorMessage") or "")
        query_id = data.get("queryId")
        for _ in range(6):  # the error lands in the query profile a moment after the reply
            if detail or not query_id:
                break
            with contextlib.suppress(Exception):
                profile = self._rest("GET", f"/profiles/{query_id}.json")
                detail = str(profile.get("error") or "").strip()
            if not detail:
                time.sleep(0.4)
        return f"Apache Drill query {state}: {detail or 'no error detail reported'}"

    def _cancel_running(self, sql: str) -> None:
        """Best effort: cancel the still-running server-side query after a client timeout."""
        wanted = " ".join(sql.split())
        with contextlib.suppress(Exception):
            for q in self._rest("GET", "/profiles.json").get("runningQueries", []):
                if " ".join(str(q.get("query", "")).split()) == wanted:
                    self._rest("GET", f"/profiles/cancel/{q.get('queryId')}")

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if (
            not hasattr(self.target, "_mock_children")
            and not hasattr(self.target, "execute")
            and hasattr(self.target, "perform_request")
        ):
            columns, raw_rows = self._rest_query(inline_params(clean_sql, params))
            types = self._types
            self.description = [
                (c, types[i] if i < len(types) else None) for i, c in enumerate(columns)
            ]
            self._rows = [
                [row.get(c) if isinstance(row, dict) else row for c in columns]
                for row in raw_rows
            ]
            return
        if _has_attr(self.target, "cursor") and not _has_attr(self.target, "fetchall"):
            cur = self.target.cursor()
            try:
                if params:
                    cur.execute(clean_sql, params)
                else:
                    cur.execute(clean_sql)
                self.description = getattr(cur, "description", None)
                self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
            finally:
                with contextlib.suppress(Exception):
                    cur.close()
        elif _has_attr(self.target, "query"):
            # a stand-in client exposing only query() (pydrill without perform_request)
            res = self.target.query(inline_params(clean_sql, params))
            columns = getattr(res, "columns", [])
            self.description = [(str(col),) for col in columns]
            raw_rows = getattr(res, "rows", [])
            self._rows = [
                [
                    row.get(col)
                    if isinstance(row, dict)
                    else (
                        row[i]
                        if isinstance(row, (list, tuple)) and i < len(row)
                        else row
                    )
                    for i, col in enumerate(columns)
                ]
                for row in raw_rows
            ]
        elif _has_attr(self.target, "execute") or _has_attr(self.target, "fetchall"):
            if params:
                self.target.execute(clean_sql, params)
            else:
                self.target.execute(clean_sql)
            self.description = getattr(self.target, "description", None)
            self._rows = (
                list(self.target.fetchall()) if hasattr(self.target, "fetchall") else []
            )
        else:
            self.description = None
            self._rows = []

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


@register_connector("drill", aliases=["apache_drill", "pydrill"])
class DrillConnector(BaseConnector):
    """Connector for Apache Drill distributed schema-free SQL engine."""

    dialect_name = "drill"

    def __init__(
        self,
        schema_name: str = "dfs.default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pydrill.client", "pydrill"):
            try:
                driver = __import__(mod_name, fromlist=["Drill", "PyDrill"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pydrill' is not installed. "
                "Install with: pip install 'query-builder-engine[drill]'"
            )

        try:
            drill_cls = getattr(driver, "PyDrill", getattr(driver, "Drill", None))
            if drill_cls is not None:
                self._connection = drill_cls(**self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Apache Drill: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield _DrillCursorAdapter(self._cursor, self.schema_name)
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield _DrillCursorAdapter(cur, self.schema_name)
            finally:
                if hasattr(cur, "close"):
                    with contextlib.suppress(Exception):
                        cur.close()
        else:
            yield _DrillCursorAdapter(conn, self.schema_name)

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        # Drill's REST API is stateless (no ALTER SESSION): enforce the timeout on the HTTP
        # request and cancel the running query on the server when it fires.
        if isinstance(cursor, _DrillCursorAdapter):
            cursor.timeout_s = max(1.0, timeout_ms / 1000.0)

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur, contextlib.suppress(Exception):
            cur.execute("SELECT version FROM sys.version;")
            rows = cur.fetchall() if hasattr(cur, "fetchall") else []
            if rows and len(rows) > 0:
                ver = (
                    rows[0][0]
                    if isinstance(rows[0], (tuple, list))
                    else (
                        rows[0].get("version", "")
                        if isinstance(rows[0], dict)
                        else str(rows[0])
                    )
                )
                if ver:
                    info["engine_version"] = f"Apache Drill {ver}".strip()
        info["schema_name"] = self.schema_name
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_drill(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Apache Drill schema '{self.schema_name}': {exc}"
                ) from exc


ApacheDrillConnector = DrillConnector


@register_connector("async_drill", aliases=["async_apache_drill"])
class AsyncDrillConnector(AsyncBaseConnector):
    """Asynchronous connector for Apache Drill distributed SQL engine."""

    dialect_name = "drill"

    def __init__(
        self,
        schema_name: str = "dfs.default",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.schema_name = schema_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pydrill.client", "pydrill"):
            try:
                driver = __import__(mod_name, fromlist=["Drill", "PyDrill"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pydrill' is not installed. "
                "Install with: pip install 'query-builder-engine[drill]'"
            )

        try:
            drill_cls = getattr(driver, "Drill", getattr(driver, "PyDrill", None))
            if drill_cls is not None:
                self._connection = drill_cls(**self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Apache Drill: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _DrillCursorAdapter(conn, self.schema_name)
        try:
            # pydrill is a blocking HTTP client: keep it off the event loop
            await asyncio.to_thread(adapter.execute, sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            adapter.close()

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        adapter = _DrillCursorAdapter(conn, self.schema_name)
        try:
            return await asyncio.to_thread(
                introspect_drill,
                adapter,
                schema_name=self.schema_name,
                filter_sensitive=filter_sensitive,
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Apache Drill schema '{self.schema_name}': {exc}"
            ) from exc


AsyncApacheDrillConnector = AsyncDrillConnector
