"""
VictoriaMetrics Time-Series & Observability Connector.
======================================================
Provides VictoriaMetrics connectivity via HTTP REST (requests/httpx),
dual sync and async execution protocols, and MetricsQL schema introspection.
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
from query_builder.connectors.introspection import introspect_victoriametrics
from query_builder.connectors.registry import register_connector


class _VictoriaMetricsCursorAdapter:
    """Adapts an HTTP client connection to VictoriaMetrics into a DB-API cursor interface."""

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
        elif hasattr(self.conn, "get") or hasattr(self.conn, "post"):
            endpoint = (
                clean_sql if clean_sql.startswith("/api/v1/") else "/api/v1/query"
            )
            req_params = (
                {} if clean_sql.startswith("/api/v1/") else {"query": clean_sql}
            )
            res = (
                self.conn.get(endpoint, params=req_params)
                if hasattr(self.conn, "get")
                else self.conn.post(endpoint, data=req_params)
            )
            if hasattr(res, "__await__"):
                import asyncio

                try:
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None

                    if loop is not None and loop.is_running():
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            res = pool.submit(asyncio.run, res).result()
                    else:
                        res = asyncio.run(res)
                except Exception:  # noqa: BLE001, S110
                    pass

            data = res.json() if hasattr(res, "json") else {}
            if isinstance(data, dict) and "data" in data:
                payload = data.get("data", {})
                if isinstance(payload, list):
                    self.description = [("metric_name",)]
                    self._rows = [[str(m)] for m in payload]
                elif isinstance(payload, dict):
                    results = payload.get("result", [])
                    self.description = [("timestamp",), ("value",), ("metric",)]
                    rows = []
                    for item in results:
                        val = item.get("value", [None, None])
                        rows.append([val[0], val[1], str(item.get("metric", {}))])
                    self._rows = rows
                else:
                    self.description = [("result",)]
                    self._rows = [[str(payload)]]
            elif isinstance(data, list):
                self.description = [("result",)]
                self._rows = [[str(d)] for d in data]
            else:
                self.description = [("status",)]
                self._rows = [["ok"]]
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


@register_connector("victoriametrics", aliases=["vm", "metricsql"])
class VictoriaMetricsConnector(BaseConnector):
    """Connector for VictoriaMetrics scalable time-series database."""

    dialect_name = "victoriametrics"

    def __init__(
        self,
        url: str = "http://localhost:8428",
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
        for mod_name in ("httpx", "requests"):
            try:
                driver = __import__(mod_name, fromlist=["get", "Client"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'requests' or 'httpx' is not installed. "
                "Install with: pip install 'query-builder-engine[victoriametrics]'"
            )

        try:
            if hasattr(driver, "Client"):
                self._connection = driver.Client(base_url=self.url, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to VictoriaMetrics: {exc}"
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
            adapter = _VictoriaMetricsCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        with self.get_cursor() as cur:
            cur.execute("/api/v1/label/__name__/values")
            cur.fetchone()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "VictoriaMetrics",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_victoriametrics(
                    cur, filter_sensitive=filter_sensitive
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect VictoriaMetrics schema: {exc}"
                ) from exc


@register_connector("async_victoriametrics", aliases=["async_vm", "async_metricsql"])
class AsyncVictoriaMetricsConnector(AsyncBaseConnector):
    """Asynchronous connector for VictoriaMetrics time-series database."""

    dialect_name = "victoriametrics"

    def __init__(
        self,
        url: str = "http://localhost:8428",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.url = url

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("httpx", "requests"):
            try:
                driver = __import__(mod_name, fromlist=["AsyncClient", "get"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'requests' or 'httpx' is not installed. "
                "Install with: pip install 'query-builder-engine[victoriametrics]'"
            )

        try:
            if hasattr(driver, "AsyncClient"):
                self._connection = driver.AsyncClient(base_url=self.url, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to VictoriaMetrics: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _VictoriaMetricsCursorAdapter(conn)

        try:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            desc = cur.description or []
            col_names = [col[0] for col in desc]
            rows = cur.fetchall() or []
            dict_rows = [dict(zip(col_names, r)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            if hasattr(cur, "close"):
                cur.close()

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        await self.execute_raw("/api/v1/label/__name__/values")
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "VictoriaMetrics",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = (
            conn.cursor()
            if hasattr(conn, "cursor")
            else _VictoriaMetricsCursorAdapter(conn)
        )
        try:
            return introspect_victoriametrics(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect VictoriaMetrics schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
