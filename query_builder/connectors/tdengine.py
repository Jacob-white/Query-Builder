"""
TDengine IoT Big Data and Time-Series Engine Connector.
=======================================================
Provides TDengine connectivity via taos/taosrest, dual sync and async execution protocols,
cursor adapters, and schema introspection.
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
)
from query_builder.connectors.introspection import introspect_tdengine
from query_builder.connectors.registry import register_connector


class _TDengineCursorAdapter:
    """Adapts a TDengine client or cursor into a DB-API compliant cursor interface."""

    def __init__(self, conn_or_cursor: Any) -> None:
        self.target = conn_or_cursor
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if clean_sql.upper() in ("SELECT 1", "SELECT 1;"):
            clean_sql = "SELECT SERVER_VERSION();"
        if hasattr(self.target, "cursor"):
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
                    getattr(cur, "close", lambda: None)()
        elif hasattr(self.target, "execute"):
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


def _load_driver() -> Any:
    """First importable TDengine driver.

    ``taos`` (native) imports fine as a package but raises ``InterfaceError`` -- not
    ``ImportError`` -- when the ``libtaos`` client library is missing (every pip-only install
    and every Windows host without the TDengine client), so every failure has to fall through
    to the REST driver ``taosrest`` instead of aborting.
    """
    failures: list[str] = []
    for mod_name in ("taos", "taosrest"):
        try:
            return __import__(mod_name, fromlist=["connect"])
        except ImportError:
            continue
        except Exception as exc:  # noqa: BLE001 - native client library missing
            failures.append(f"{mod_name}: {exc}")
    detail = f" ({'; '.join(failures)})" if failures else ""
    raise DriverNotInstalledError(
        "No usable TDengine driver: install 'taospy' with the TDengine client library "
        "(native 'taos') or use its REST driver ('taosrest', pass url=...). "
        f"Install with: pip install 'query-builder-engine[tdengine]'{detail}"
    )


@register_connector("tdengine", aliases=["taos"])
class TDengineConnector(BaseConnector):
    """Connector for TDengine IoT time-series database engine."""

    dialect_name = "tdengine"

    def __init__(
        self,
        database: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.database = database
        self.schema_name = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = _load_driver()

        try:
            self._connection = driver.connect(database=self.database, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to TDengine database '{self.database}': {exc}"
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
            adapter = _TDengineCursorAdapter(conn)
            yield adapter

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        with self.get_cursor() as cur:
            cur.execute("SELECT SERVER_VERSION()")
            row = cur.fetchone()
        latency_ms = (time.perf_counter() - start) * 1000.0
        version = row[0] if row else None
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": f"TDengine {version}" if version else "TDengine",
            "database": self.database,
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_tdengine(
                    cur,
                    database=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect TDengine database '{self.database}': {exc}"
                ) from exc


@register_connector("async_tdengine", aliases=["async_taos"])
class AsyncTDengineConnector(AsyncBaseConnector):
    """Asynchronous connector for TDengine time-series database."""

    dialect_name = "tdengine"

    def __init__(
        self,
        database: str = "default",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.database = database
        self.schema_name = database

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = _load_driver()

        try:
            self._connection = driver.connect(database=self.database, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to TDengine: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _TDengineCursorAdapter(conn)
        try:
            await asyncio.to_thread(adapter.execute, sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            adapter.close()

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        _, rows, _ = await self.execute_raw("SELECT SERVER_VERSION()")
        version = next(iter(rows[0].values()), None) if rows else None
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": f"TDengine {version}" if version else "TDengine",
            "database": self.database,
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        """Same catalogue as the sync class (it used to inherit an always-empty snapshot)."""
        conn = await self.connect()

        def _run() -> dict[str, Any]:
            adapter = _TDengineCursorAdapter(conn)
            try:
                return introspect_tdengine(
                    adapter, database=self.database, filter_sensitive=filter_sensitive
                )
            finally:
                adapter.close()

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect TDengine database '{self.database}': {exc}"
            ) from exc
