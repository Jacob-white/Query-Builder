"""
Apache Cassandra Distributed NoSQL / CQL Database Connector.
============================================================
Provides native Apache Cassandra cluster connectivity, session management,
DB-API cursor adaptation, statement timeouts, and system_schema introspection.
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
from query_builder.connectors.introspection import introspect_cassandra
from query_builder.connectors.registry import register_connector


class _CassandraCursorAdapter:
    """Adapts an Apache Cassandra Cluster Session into a DB-API cursor interface."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if clean_sql.upper() in ("SELECT 1", "SELECT 1;"):
            clean_sql = "SELECT release_version FROM system.local LIMIT 1"
        if hasattr(self.session, "execute"):
            if params:
                result_set = self.session.execute(clean_sql, params)
            else:
                result_set = self.session.execute(clean_sql)

            if hasattr(result_set, "column_names"):
                self.description = [(col,) for col in result_set.column_names]
            elif hasattr(result_set, "description"):
                self.description = result_set.description
            else:
                self.description = None

            if hasattr(result_set, "all"):
                rows = result_set.all()
            elif hasattr(result_set, "fetchall"):
                rows = result_set.fetchall()
            elif isinstance(result_set, (list, tuple)):
                rows = list(result_set)
            else:
                rows = list(result_set) if result_set is not None else []

            self._rows = [
                list(r.values())
                if hasattr(r, "values")
                else (
                    [getattr(r, f) for f in r._fields]
                    if hasattr(r, "_fields")
                    else (list(r) if isinstance(r, (list, tuple)) else [r])
                )
                for r in rows
            ]
        elif hasattr(self.session, "cursor"):
            cur = self.session.cursor()
            if params:
                cur.execute(clean_sql, params)
            else:
                cur.execute(clean_sql)
            self.description = getattr(cur, "description", None)
            self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
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


@register_connector("apache_cassandra", aliases=["apache-cassandra"])
class ApacheCassandraConnector(BaseConnector):
    """Connector for Apache Cassandra distributed CQL clusters."""

    dialect_name = "cassandra"

    def __init__(
        self,
        contact_points: list[str] | None = None,
        port: int = 9042,
        keyspace: str = "system",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.contact_points = contact_points or ["127.0.0.1"]
        self.port = port
        self.keyspace = keyspace
        self.schema_name = keyspace

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("cassandra.cluster", "cassandra"):
            try:
                driver = __import__(mod_name, fromlist=["Cluster"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'cassandra-driver' is not installed. "
                "Install with: pip install 'query-builder-engine[cassandra]'"
            )

        try:
            cluster_cls = getattr(driver, "Cluster", None) or getattr(
                getattr(driver, "cluster", None), "Cluster", None
            )
            cluster = cluster_cls(
                contact_points=self.contact_points, port=self.port, **self.config
            )
            session = cluster.connect(self.keyspace)
            self._connection = session
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Apache Cassandra cluster at {self.contact_points}: {exc}"
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
            adapter = _CassandraCursorAdapter(conn)
            yield adapter

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Apache Cassandra"
        info["keyspace"] = self.keyspace
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_cassandra(
                    cur,
                    keyspace=self.keyspace,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Apache Cassandra keyspace '{self.keyspace}': {exc}"
                ) from exc


CassandraConnector = ApacheCassandraConnector


@register_connector("async_apache_cassandra", aliases=["async_cassandra", "async_cql"])
class AsyncApacheCassandraConnector(AsyncBaseConnector):
    """Asynchronous connector for Apache Cassandra clusters."""

    dialect_name = "cassandra"

    def __init__(
        self,
        contact_points: list[str] | None = None,
        port: int = 9042,
        keyspace: str = "system",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.contact_points = contact_points or ["127.0.0.1"]
        self.port = port
        self.keyspace = keyspace
        self.schema_name = keyspace

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("cassandra.cluster", "cassandra"):
            try:
                driver = __import__(mod_name, fromlist=["Cluster"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'cassandra-driver' is not installed. "
                "Install with: pip install 'query-builder-engine[cassandra]'"
            )

        try:
            cluster_cls = getattr(driver, "Cluster", None) or getattr(
                getattr(driver, "cluster", None), "Cluster", None
            )
            cluster = cluster_cls(
                contact_points=self.contact_points, port=self.port, **self.config
            )
            session = cluster.connect(self.keyspace)
            self._connection = session
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Apache Cassandra: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _CassandraCursorAdapter(conn)
        adapter.execute(sql, params)
        desc = adapter.description or []
        col_names = [col[0] for col in desc]
        rows = adapter.fetchall() or []
        dict_rows = [dict(zip(col_names, r)) for r in rows]
        latency_ms = (time.perf_counter() - start) * 1000.0
        return col_names, dict_rows, latency_ms


AsyncCassandraConnector = AsyncApacheCassandraConnector
