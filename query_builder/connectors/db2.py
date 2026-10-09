"""
IBM DB2 Enterprise Relational Database Connector.
=================================================
Provides IBM DB2 connectivity via ibm_db_dbi / ibm_db, dual sync and async
execution protocols, query statement isolation, and SYSCAT schema introspection.

``ibm_db`` is a blocking C driver: the async connector runs every driver call in a worker
thread so the event loop (and ``asyncio.wait_for`` timeouts) stay responsive.
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
from query_builder.connectors.introspection import introspect_db2
from query_builder.connectors.registry import register_connector

_VERSION_SQL = "SELECT SERVICE_LEVEL FROM SYSIBMADM.ENV_INST_INFO"
_SCHEMA_SQL = "VALUES CURRENT SCHEMA"


def _load_driver() -> Any:
    for mod_name in ("ibm_db_dbi", "ibm_db"):
        try:
            return __import__(mod_name)
        except ImportError:
            continue
    raise DriverNotInstalledError(
        "'ibm_db' or 'ibm_db_dbi' is not installed. "
        "Install with: pip install 'query-builder-engine[db2]'"
    )


def _connect(driver: Any, config: dict[str, Any]) -> Any:
    conn = driver.connect(**config)
    # reads only: never leave a transaction (and its locks) open on a long-lived connection
    with contextlib.suppress(Exception):
        conn.set_autocommit(True)
    return conn


def _scalar(cur: Any, sql: str) -> Any:
    with contextlib.suppress(Exception):
        cur.execute(sql)
        row = cur.fetchone()
        if row and row[0] is not None:
            return row[0]
    return None


def _engine_version(cur: Any) -> str:
    level = _scalar(cur, _VERSION_SQL)
    return str(level) if isinstance(level, str) and level else "IBM DB2"


@register_connector("db2", aliases=["ibm_db2"])
class DB2Connector(BaseConnector):
    """Connector for IBM DB2 enterprise relational database."""

    dialect_name = "db2"

    def __init__(
        self,
        schema_name: str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        #: schema to introspect; ``None`` = the session's CURRENT SCHEMA (the old default,
        #: SYSCAT, only ever listed Db2's own catalog)
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = _load_driver()
        try:
            self._connection = _connect(driver, self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to IBM DB2: {exc}") from exc

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        with self.get_cursor() as cur:
            cur.execute("SELECT 1 FROM SYSIBM.SYSDUMMY1")
            cur.fetchone()
            version = _engine_version(cur)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": version,
            "schema_name": self.schema_name,
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            schema = self.schema_name or _scalar(cur, _SCHEMA_SQL) or "SYSCAT"
            try:
                return introspect_db2(
                    cur,
                    schema_name=str(schema),
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect IBM DB2 schema '{schema}': {exc}"
                ) from exc


IBMDB2Connector = DB2Connector


@register_connector("async_db2", aliases=["async_ibm_db2"])
class AsyncDB2Connector(AsyncBaseConnector):
    """Asynchronous connector for IBM DB2 enterprise database."""

    dialect_name = "db2"

    def __init__(
        self,
        schema_name: str | None = None,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.schema_name = schema_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = _load_driver()
        try:
            self._connection = await asyncio.to_thread(_connect, driver, self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to IBM DB2: {exc}"
            ) from exc

    def _run_sync(
        self, sql: str, params: list[Any] | None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        start = time.perf_counter()
        cur = self._connection.cursor()
        try:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            desc = cur.description or []
            col_names = [col[0] for col in desc]
            rows = cur.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            return col_names, dict_rows, (time.perf_counter() - start) * 1000.0
        finally:
            cur.close()

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        await self.connect()
        return await asyncio.to_thread(self._run_sync, sql, params)

    async def test_connection(self) -> dict[str, Any]:
        # Db2 has no FROM-less SELECT, so the base class's "SELECT 1" cannot work here
        start = time.perf_counter()
        await self.execute_raw("SELECT 1 FROM SYSIBM.SYSDUMMY1")

        def version() -> str:
            cur = self._connection.cursor()
            try:
                return _engine_version(cur)
            finally:
                cur.close()

        engine_version = await asyncio.to_thread(version)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": engine_version,
            "schema_name": self.schema_name,
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        await self.connect()

        def run() -> dict[str, Any]:
            cur = self._connection.cursor()
            try:
                schema = self.schema_name or _scalar(cur, _SCHEMA_SQL) or "SYSCAT"
                return introspect_db2(
                    cur, schema_name=str(schema), filter_sensitive=filter_sensitive
                )
            finally:
                cur.close()

        try:
            return await asyncio.to_thread(run)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect IBM DB2 schema '{self.schema_name}': {exc}"
            ) from exc


AsyncIBMDB2Connector = AsyncDB2Connector
