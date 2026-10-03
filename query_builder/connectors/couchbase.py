"""
Couchbase SQL++ / N1QL Query Connector.
========================================
Translates declarative query specifications to Couchbase SQL++ (N1QL) execution
across buckets, scopes, and collections with schema inference.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.schema import normalize_schema_snapshot


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
            self._connection = Cluster(self.connstr, opts)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Couchbase cluster '{self.connstr}': {exc}"
            ) from exc

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
                    if (
                        inf_rows
                        and len(inf_rows) > 0
                        and isinstance(inf_rows[0], (list, tuple))
                    ):
                        sample = (
                            inf_rows[0][0] if isinstance(inf_rows[0][0], dict) else {}
                        )
                        properties = sample.get("properties", {})
                        for p_name, p_val in properties.items():
                            if p_name == "user_id":
                                has_user = True
                            cols.append(
                                {
                                    "name": p_name,
                                    "data_type": (
                                        p_val.get("type", "string")
                                        if isinstance(p_val, dict)
                                        else "string"
                                    ),
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
