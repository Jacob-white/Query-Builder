"""
Azure Data Explorer / Kusto Database Connector.
===============================================
Provides Azure Data Explorer (ADX/KQL) connectivity via azure-kusto-data,
dual sync and async execution protocols, and Kusto schema introspection.
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
from query_builder.connectors.introspection import introspect_kusto
from query_builder.connectors.registry import register_connector


class _KustoCursorAdapter:
    """Adapts a KustoClient connection into a standard DB-API cursor interface."""

    def __init__(self, connection: Any, database: str = "default") -> None:
        self.conn = connection
        self.database = database
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
        elif hasattr(self.conn, "execute_query") or hasattr(self.conn, "execute"):
            exec_fn = getattr(
                self.conn, "execute_query", getattr(self.conn, "execute", None)
            )
            try:
                res = exec_fn(self.database, clean_sql)
            except (TypeError, Exception):  # noqa: BLE001
                res = exec_fn(clean_sql, params) if params else exec_fn(clean_sql)

            if hasattr(res, "description"):
                self.description = res.description
            elif hasattr(res, "primary_results") and res.primary_results:
                tbl = res.primary_results[0]
                if hasattr(tbl, "columns") and tbl.columns is not None:
                    self.description = [
                        (getattr(col, "column_name", str(col)),) for col in tbl.columns
                    ]
                elif tbl and hasattr(tbl[0], "as_dict"):
                    self.description = [(k,) for k in tbl[0].as_dict()]
                elif tbl and hasattr(tbl[0], "keys"):
                    self.description = [(k,) for k in tbl[0]]
                else:
                    self.description = None
            else:
                self.description = None

            if hasattr(res, "fetchall"):
                self._rows = list(res.fetchall())
            elif hasattr(res, "primary_results") and res.primary_results:
                tbl = res.primary_results[0]
                rows: list[list[Any]] = []
                for r in tbl:
                    if hasattr(r, "as_dict"):
                        rows.append(list(r.as_dict().values()))
                    elif hasattr(r, "values"):
                        rows.append(list(r.values()))
                    elif isinstance(r, (list, tuple)):
                        rows.append(list(r))
                    else:
                        rows.append([r])
                self._rows = rows
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


@register_connector("kusto", aliases=["adx", "azure_data_explorer", "kql"])
class KustoConnector(BaseConnector):
    """Connector for Azure Data Explorer (Kusto/KQL)."""

    dialect_name = "kusto"

    def __init__(
        self,
        database: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.database = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("azure.kusto.data", "azure.kusto.data.client"):
            try:
                driver = __import__(mod_name, fromlist=["KustoClient"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'azure-kusto-data' is not installed. "
                "Install with: pip install 'query-builder-engine[kusto]'"
            )

        try:
            client_cls = getattr(driver, "KustoClient", driver)
            self._connection = client_cls(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Azure Data Explorer: {exc}"
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
            adapter = _KustoCursorAdapter(conn, database=self.database)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        with self.get_cursor() as cur:
            cur.execute(".show tables")
            cur.fetchone()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Azure Data Explorer (Kusto)",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_kusto(
                    cur, database=self.database, filter_sensitive=filter_sensitive
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Kusto schema: {exc}"
                ) from exc


@register_connector(
    "async_kusto", aliases=["async_adx", "async_azure_data_explorer", "async_kql"]
)
class AsyncKustoConnector(AsyncBaseConnector):
    """Asynchronous connector for Azure Data Explorer (Kusto/KQL)."""

    dialect_name = "kusto"

    def __init__(
        self,
        database: str = "default",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.database = database

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("azure.kusto.data", "azure.kusto.data.client"):
            try:
                driver = __import__(mod_name, fromlist=["KustoClient"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'azure-kusto-data' is not installed. "
                "Install with: pip install 'query-builder-engine[kusto]'"
            )

        try:
            client_cls = getattr(driver, "KustoClient", driver)
            self._connection = client_cls(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Azure Data Explorer: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _KustoCursorAdapter(conn, database=self.database)

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
        await self.execute_raw(".show tables")
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Azure Data Explorer (Kusto)",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = conn.cursor() if hasattr(conn, "cursor") else _KustoCursorAdapter(conn)
        try:
            return introspect_kusto(
                cur, database=self.database, filter_sensitive=filter_sensitive
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Kusto schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()


ADXConnector = KustoConnector
AsyncADXConnector = AsyncKustoConnector
