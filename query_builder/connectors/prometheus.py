"""
Prometheus Metrics Time-Series Connector.
=========================================
Provides Prometheus monitoring system connectivity via prometheus-api-client or requests,
dual sync and async execution protocols, and PromQL metric introspection.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from query_builder.connectors._promql import (
    PromAsync,
    PromSync,
    RequestsBase,
    is_http_client,
    promql_introspect_plan,
    version_plan,
    version_text,
)
from query_builder.connectors._vector_sql import drive_async, drive_sync
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import (
    introspect_prometheus,
    normalize_schema_snapshot,
)
from query_builder.connectors.registry import register_connector


class _PrometheusCursorAdapter:
    """Adapts a Prometheus API client or HTTP connection into a DB-API cursor interface."""

    def __init__(self, connection: Any) -> None:
        self.conn = connection
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if is_http_client(self.conn):
            self.description, self._rows = PromSync(self.conn).request(clean_sql)
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
        elif clean_sql == "/api/v1/label/__name__/values" and hasattr(
            self.conn, "all_metrics"
        ):
            metrics = self.conn.all_metrics()
            self.description = [("metric_name",)]
            self._rows = [[m] for m in metrics]
        elif hasattr(self.conn, "custom_query"):
            res = self.conn.custom_query(query=clean_sql)
            self.description = [("timestamp",), ("value",), ("metric",)]
            self._rows = (
                [
                    [
                        item.get("value", [None, None])[0],
                        item.get("value", [None, None])[1],
                        str(item.get("metric", {})),
                    ]
                    for item in res
                ]
                if isinstance(res, list)
                else []
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


@register_connector("prometheus", aliases=["prom", "promql"])
class PrometheusConnector(BaseConnector):
    """Connector for Prometheus time-series monitoring system."""

    dialect_name = "prometheus"

    def __init__(
        self,
        url: str = "http://localhost:9090",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.url = url

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("httpx", "requests", "prometheus_api_client"):
            try:
                driver = __import__(mod_name, fromlist=["PrometheusConnect", "get"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'prometheus-api-client' or 'requests' is not installed. "
                "Install with: pip install 'query-builder-engine[prometheus]'"
            )

        try:
            if mod_name == "httpx":
                self._connection = driver.Client(base_url=self.url, **self.config)
            elif mod_name == "requests":
                self._connection = RequestsBase(self.url, **self.config)
            elif hasattr(driver, "PrometheusConnect"):
                self._connection = driver.PrometheusConnect(url=self.url, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Prometheus: {exc}"
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
            adapter = _PrometheusCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        version = "Prometheus"
        conn = self.connect()
        if is_http_client(conn):
            PromSync(conn).request("/-/ready")  # raises on a non-2xx answer
            with contextlib.suppress(Exception):
                version = version_text(
                    "Prometheus", drive_sync(version_plan(), PromSync(conn))
                )
        else:
            with self.get_cursor() as cur:
                cur.execute("/api/v1/label/__name__/values")
                cur.fetchone()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": version,
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = self.connect()
        if is_http_client(conn):
            try:
                raw = drive_sync(promql_introspect_plan(), PromSync(conn))
                return normalize_schema_snapshot(raw, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Prometheus schema: {exc}"
                ) from exc
        with self.get_cursor() as cur:
            try:
                return introspect_prometheus(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Prometheus schema: {exc}"
                ) from exc


@register_connector("async_prometheus", aliases=["async_prom", "async_promql"])
class AsyncPrometheusConnector(AsyncBaseConnector):
    """Asynchronous connector for Prometheus monitoring system."""

    dialect_name = "prometheus"

    def __init__(
        self,
        url: str = "http://localhost:9090",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.url = url

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("httpx", "prometheus_api_client", "requests"):
            try:
                driver = __import__(mod_name, fromlist=["PrometheusConnect", "get"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'prometheus-api-client' or 'requests' is not installed. "
                "Install with: pip install 'query-builder-engine[prometheus]'"
            )

        try:
            if mod_name == "httpx":
                self._connection = driver.AsyncClient(base_url=self.url, **self.config)
            elif hasattr(driver, "PrometheusConnect"):
                self._connection = driver.PrometheusConnect(url=self.url, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Prometheus: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if is_http_client(conn) and hasattr(conn, "aclose"):
            desc, rows = await PromAsync(conn).request(sql)
            names = [d[0] for d in desc]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return names, [dict(zip(names, r, strict=False)) for r in rows], latency_ms
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _PrometheusCursorAdapter(conn)

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
        version = "Prometheus"
        conn = await self.connect()
        if is_http_client(conn) and hasattr(conn, "aclose"):
            await PromAsync(conn).request("/-/ready")
            with contextlib.suppress(Exception):
                version = version_text(
                    "Prometheus", await drive_async(version_plan(), PromAsync(conn))
                )
        else:
            await self.execute_raw("/api/v1/label/__name__/values")
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": version,
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        if is_http_client(conn) and hasattr(conn, "aclose"):
            try:
                raw = await drive_async(promql_introspect_plan(), PromAsync(conn))
                return normalize_schema_snapshot(raw, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Prometheus schema: {exc}"
                ) from exc
        cur = (
            conn.cursor() if hasattr(conn, "cursor") else _PrometheusCursorAdapter(conn)
        )
        try:
            return introspect_prometheus(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Prometheus schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
