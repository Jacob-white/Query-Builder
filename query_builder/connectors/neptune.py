"""
Amazon Neptune Graph Database Connector.
========================================
Provides Amazon Neptune connectivity via openCypher Bolt/HTTPS endpoint,
dual sync and async execution protocols, and graph schema introspection.
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
from query_builder.connectors.introspection import introspect_neptune
from query_builder.connectors.registry import register_connector


class _NeptuneCursorAdapter:
    """Adapts an Amazon Neptune openCypher client or session into a DB-API cursor interface."""

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
        elif hasattr(self.conn, "execute_open_cypher_query"):
            res = self.conn.execute_open_cypher_query(openCypherQuery=clean_sql)
            results = res.get("results", [])
            if results and isinstance(results[0], dict):
                keys = list(results[0].keys())
                self.description = [(k,) for k in keys]
                self._rows = [[r.get(k) for k in keys] for r in results]
            else:
                self.description = [("val",)]
                self._rows = [[r] for r in results]
        elif hasattr(self.conn, "run"):
            res = self.conn.run(clean_sql, params or {})
            keys = getattr(res, "keys", list)()
            self.description = [(k,) for k in keys] if keys else None
            records = res.values() if hasattr(res, "values") else list(res)
            self._rows = [list(r) for r in records]
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


@register_connector("neptune", aliases=["amazon_neptune", "aws_neptune"])
class NeptuneConnector(BaseConnector):
    """Connector for Amazon Neptune managed graph database service."""

    dialect_name = "neptune"

    def __init__(
        self,
        endpoint: str = "localhost",
        port: int = 8182,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.endpoint = endpoint
        self.port = port

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("boto3", "neo4j"):
            try:
                driver = __import__(mod_name, fromlist=["client", "GraphDatabase"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'neo4j' or 'boto3' is not installed. "
                "Install with: pip install 'query-builder-engine[neptune]'"
            )

        try:
            if hasattr(driver, "client"):
                self._connection = driver.client(
                    "neptunedata",
                    endpoint_url=f"https://{self.endpoint}:{self.port}",
                    **self.config,
                )
            elif hasattr(driver, "GraphDatabase"):
                uri = f"bolt://{self.endpoint}:{self.port}"
                self._connection = driver.GraphDatabase.driver(uri, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Amazon Neptune: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield self._cursor
            return

        conn = self.connect()
        if hasattr(conn, "session"):
            session = conn.session()
            adapter = _NeptuneCursorAdapter(session)
            try:
                yield adapter
            finally:
                adapter.close()
                if hasattr(session, "close"):
                    session.close()
        elif hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield cur
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        else:
            adapter = _NeptuneCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        with self.get_cursor() as cur:
            cur.execute("RETURN 1 AS val;")
            cur.fetchone()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Amazon Neptune",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_neptune(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Neptune schema: {exc}"
                ) from exc


@register_connector(
    "async_neptune", aliases=["async_amazon_neptune", "async_aws_neptune"]
)
class AsyncNeptuneConnector(AsyncBaseConnector):
    """Asynchronous connector for Amazon Neptune graph database."""

    dialect_name = "neptune"

    def __init__(
        self,
        endpoint: str = "localhost",
        port: int = 8182,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.endpoint = endpoint
        self.port = port

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("neo4j", "boto3"):
            try:
                driver = __import__(
                    mod_name, fromlist=["AsyncGraphDatabase", "GraphDatabase", "client"]
                )
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'neo4j' or 'boto3' is not installed. "
                "Install with: pip install 'query-builder-engine[neptune]'"
            )

        try:
            if hasattr(driver, "AsyncGraphDatabase"):
                uri = f"bolt://{self.endpoint}:{self.port}"
                self._connection = driver.AsyncGraphDatabase.driver(uri, **self.config)
            elif hasattr(driver, "GraphDatabase"):
                uri = f"bolt://{self.endpoint}:{self.port}"
                self._connection = driver.GraphDatabase.driver(uri, **self.config)
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Amazon Neptune: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _NeptuneCursorAdapter(conn)

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
        await self.execute_raw("RETURN 1 AS val;")
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Amazon Neptune",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = conn.cursor() if hasattr(conn, "cursor") else _NeptuneCursorAdapter(conn)
        try:
            return introspect_neptune(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Neptune schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
