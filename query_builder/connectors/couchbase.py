"""
Couchbase SQL++ / N1QL Query Connector.
========================================
Translates declarative query specifications to Couchbase SQL++ (N1QL) execution
across buckets, scopes, and collections with schema inference.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.schema import normalize_schema_snapshot


class _CouchbaseCursor:
    """Minimal DB-API cursor interface wrapping Couchbase Cluster query execution."""

    def __init__(self, cluster: Any) -> None:
        self.cluster = cluster
        self._rows: list[list[Any]] = []
        self.description: list[tuple[str, ...]] | None = None

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        if hasattr(self.cluster, "query"):
            result = self.cluster.query(sql)
            raw_items = list(result)
            if not raw_items:
                self.description = None
                self._rows = []
                return

            first = raw_items[0]
            if isinstance(first, dict):
                keys = list(first.keys())
                self.description = [(k,) for k in keys]
                self._rows = [[item.get(k) for k in keys] for item in raw_items]
            elif isinstance(first, (list, tuple)):
                self.description = [(f"col_{i}",) for i in range(len(first))]
                self._rows = [list(item) for item in raw_items]
            else:
                self.description = [("val",)]
                self._rows = [[item] for item in raw_items]
            return

        if hasattr(self.cluster, "execute"):
            self.cluster.execute(sql, params)
            self.description = getattr(self.cluster, "description", None)
            self._rows = getattr(self.cluster, "fetchall", list)()

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


class _CouchbaseClient:
    """Connection abstraction providing cursor creation for Couchbase Cluster."""

    def __init__(self, cluster: Any) -> None:
        self.cluster = cluster

    def cursor(self) -> _CouchbaseCursor:
        return _CouchbaseCursor(self.cluster)

    def close(self) -> None:
        if hasattr(self.cluster, "close"):
            self.cluster.close()


class CouchbaseConnector(BaseConnector):
    """Connector for Couchbase SQL++ / N1QL query interface."""

    dialect_name = "couchbase"

    def __init__(
        self,
        connstr: str = "couchbase://localhost",
        username: str = "Administrator",
        password: str = "password",
        bucket_name: str = "default",
        scope_name: str = "_default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.connstr = connstr
        self.username = username
        self.password = password
        self.bucket_name = bucket_name
        self.scope_name = scope_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            from couchbase.auth import PasswordAuthenticator
            from couchbase.cluster import Cluster
            from couchbase.options import ClusterOptions
        except ImportError as err:
            raise DriverNotInstalledError(
                "couchbase is not installed. "
                "Install with: pip install 'query-builder-engine[couchbase]'"
            ) from err

        try:
            auth = PasswordAuthenticator(self.username, self.password)
            opts = ClusterOptions(auth)
            cluster = Cluster(self.connstr, opts)
            self._connection = _CouchbaseClient(cluster)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Couchbase cluster '{self.connstr}': {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Iterator[Any]:
        if self._cursor is not None:
            yield self._cursor
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield cur
            finally:
                with contextlib.suppress(Exception):
                    cur.close()
        else:
            cur = _CouchbaseCursor(conn)
            try:
                yield cur
            finally:
                with contextlib.suppress(Exception):
                    cur.close()

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Couchbase SQL++"
        info["bucket"] = self.bucket_name
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                cur.execute("SELECT name FROM system:keyspaces ORDER BY name;")
                rows = cur.fetchall()
                table_names = [str(r[0]) for r in rows if r and r[0]]
                tables: dict[str, dict[str, Any]] = {}
                for tbl in table_names:
                    cur.execute(f"INFER `{tbl}`")
                    inf_rows = cur.fetchall()
                    cols: list[dict[str, Any]] = []
                    has_user = False
                    if inf_rows and len(inf_rows) > 0:
                        first_inf = inf_rows[0]
                        if isinstance(first_inf, (list, tuple)) and len(first_inf) > 0:
                            sample = (
                                first_inf[0] if isinstance(first_inf[0], dict) else {}
                            )
                        elif isinstance(first_inf, dict):
                            sample = first_inf
                        else:
                            sample = {}

                        properties = sample.get("properties", {})
                        for p_name, p_val in properties.items():
                            if p_name == "user_id":
                                has_user = True
                            data_type = (
                                p_val.get("type", "string")
                                if isinstance(p_val, dict)
                                else (str(p_val) if p_val else "string")
                            )
                            cols.append(
                                {
                                    "name": p_name,
                                    "data_type": data_type,
                                    "is_nullable": True,
                                    "is_primary": p_name == "id",
                                    "comment": None,
                                }
                            )
                    tables[tbl] = {
                        "name": tbl,
                        "columns": cols,
                        "has_user_id": has_user,
                        "user_col": "user_id",
                        "comment": None,
                    }
                return normalize_schema_snapshot(
                    {"tables": tables, "foreign_keys": [], "relationships": []},
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Couchbase schema: {exc}"
                ) from exc


N1QLConnector = CouchbaseConnector
