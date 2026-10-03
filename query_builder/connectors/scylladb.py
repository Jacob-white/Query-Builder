"""
ScyllaDB and Apache Cassandra Distributed NoSQL / CQL Database Connector.
========================================================================
Provides ScyllaDB and Cassandra CQL cluster session connectivity,
DB-API cursor adaptation, and system_schema keyspace introspection.
"""

from __future__ import annotations

import contextlib
from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_scylladb
from query_builder.connectors.registry import register_connector


class _ScyllaCursorAdapter:
    """Adapts a Cassandra / ScyllaDB Session into a DB-API compliant cursor interface."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        # Strip trailing semicolon and surrounding whitespace for CQL driver
        clean_sql = sql.strip().rstrip(";").strip()
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

            # Format rows as list of values safely handling dicts, tuples, and scalar items
            self._rows = [
                list(r.values())
                if hasattr(r, "values")
                else (list(r) if isinstance(r, (list, tuple)) else [r])
                for r in rows
            ]

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


@register_connector("scylladb", aliases=["scylla", "cassandra", "cql"])
class ScyllaDBConnector(BaseConnector):
    """Connector for ScyllaDB and Apache Cassandra distributed CQL clusters."""

    dialect_name = "scylladb"

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
                driver = __import__(mod_name, fromlist=["cluster"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'cassandra-driver' or 'scylla-driver' is not installed. "
                "Install with: pip install 'query-builder-engine[scylladb]'"
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
                f"Failed to connect to ScyllaDB cluster at {self.contact_points}: {exc}"
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
            adapter = _ScyllaCursorAdapter(conn)
            yield adapter

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "ScyllaDB / Apache Cassandra"
        info["keyspace"] = self.keyspace
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_scylladb(
                    cur,
                    keyspace=self.keyspace,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect ScyllaDB keyspace '{self.keyspace}': {exc}"
                ) from exc


CassandraConnector = ScyllaDBConnector
