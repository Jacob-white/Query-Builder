"""
OpenSearch Distributed Search & Analytics Engine SQL Plugin Connector.
======================================================================
Provides OpenSearch connectivity via opensearch-py / HTTP REST SQL plugin,
dual sync and async execution protocols, cursor adapters, and index mapping schema introspection.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_opensearch
from query_builder.connectors.registry import register_connector


def _has_attr(target: Any, attr: str) -> bool:
    if hasattr(target, "_mock_children"):
        if getattr(target, "_mock_methods", None) is not None:
            return hasattr(target, attr)
        return attr in target._mock_children
    return hasattr(target, attr)


class _OpenSearchCursorAdapter:
    """Adapts OpenSearch client or REST SQL responses into a DB-API cursor interface."""

    def __init__(self, client_or_cursor: Any) -> None:
        self.target = client_or_cursor
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
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
        elif _has_attr(self.target, "execute") or _has_attr(self.target, "fetchall"):
            if params:
                self.target.execute(clean_sql, params)
            else:
                self.target.execute(clean_sql)
            self.description = getattr(self.target, "description", None)
            self._rows = (
                list(self.target.fetchall()) if hasattr(self.target, "fetchall") else []
            )
        elif _has_attr(self.target, "transport") and hasattr(
            self.target.transport, "perform_request"
        ):
            # OpenSearch Python client
            body: dict[str, Any] = {"query": clean_sql}
            if params:
                body["parameters"] = params
            res = self.target.transport.perform_request(
                "POST", "/_plugins/_sql", body=body
            )
            schema = res.get("schema", []) if isinstance(res, dict) else []
            self.description = [
                (col.get("name", f"col_{i}"),) for i, col in enumerate(schema)
            ]
            self._rows = list(res.get("datarows", [])) if isinstance(res, dict) else []
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


@register_connector("opensearch", aliases=["opensearch_sql", "opensearch_connector"])
class OpenSearchConnector(BaseConnector):
    """Connector for OpenSearch distributed search & analytics engine via SQL plugin."""

    dialect_name = "opensearch"

    def __init__(
        self,
        index_pattern: str = "*",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.index_pattern = index_pattern

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("opensearchpy", "opensearch_py", "elasticsearch"):
            try:
                driver = __import__(mod_name, fromlist=["OpenSearch", "Elasticsearch"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'opensearch-py' is not installed. "
                "Install with: pip install 'query-builder-engine[opensearch]'"
            )

        try:
            client_cls = getattr(
                driver,
                "OpenSearch",
                getattr(driver, "Elasticsearch", None),
            )
            if client_cls is not None:
                self._connection = client_cls(**self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to OpenSearch: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield _OpenSearchCursorAdapter(self._cursor)
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield _OpenSearchCursorAdapter(cur)
            finally:
                if hasattr(cur, "close"):
                    with contextlib.suppress(Exception):
                        cur.close()
        else:
            yield _OpenSearchCursorAdapter(conn)

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        pass

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur, contextlib.suppress(Exception):
            cur.execute("SELECT version();")
            rows = cur.fetchall() if hasattr(cur, "fetchall") else []
            if rows and len(rows) > 0 and len(rows[0]) > 0 and rows[0][0]:
                info["engine_version"] = f"OpenSearch {rows[0][0]}".strip()
        info["index_pattern"] = self.index_pattern
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            conn = getattr(cur, "target", cur)
            try:
                return introspect_opensearch(
                    conn,
                    catalog=self.index_pattern,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect OpenSearch schema '{self.index_pattern}': {exc}"
                ) from exc


@register_connector("async_opensearch", aliases=["async_opensearch_sql"])
class AsyncOpenSearchConnector(AsyncBaseConnector):
    """Asynchronous connector for OpenSearch distributed search engine."""

    dialect_name = "opensearch"

    def __init__(
        self,
        index_pattern: str = "*",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.index_pattern = index_pattern

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("opensearchpy", "opensearch_py", "elasticsearch"):
            try:
                driver = __import__(
                    mod_name,
                    fromlist=[
                        "AsyncOpenSearch",
                        "OpenSearch",
                        "AsyncElasticsearch",
                    ],
                )
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'opensearch-py' is not installed. "
                "Install with: pip install 'query-builder-engine[opensearch]'"
            )

        try:
            client_cls = getattr(
                driver,
                "AsyncOpenSearch",
                getattr(
                    driver,
                    "OpenSearch",
                    getattr(driver, "AsyncElasticsearch", None),
                ),
            )
            if client_cls is not None:
                self._connection = client_cls(**self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to OpenSearch: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _OpenSearchCursorAdapter(conn)
        try:
            adapter.execute(sql, params)
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
        try:
            return introspect_opensearch(
                conn,
                catalog=self.index_pattern,
                filter_sensitive=filter_sensitive,
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect OpenSearch schema '{self.index_pattern}': {exc}"
            ) from exc
