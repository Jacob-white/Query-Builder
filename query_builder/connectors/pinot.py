"""
Apache Pinot Distributed OLAP Datastore Connector.
==================================================
Provides Pinot SQL connectivity via pinotdb, broker session dispatch,
and schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.registry import register_connector
from query_builder.schema import normalize_schema_snapshot


@register_connector("pinot", aliases=["apache_pinot"])
class PinotConnector(BaseConnector):
    """Connector for Apache Pinot distributed real-time OLAP datastore."""

    dialect_name = "pinot"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8099,
        path: str = "/query/sql",
        scheme: str = "http",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host = host
        self.port = port
        self.path = path
        self.scheme = scheme
        self.config.setdefault("host", host)
        self.config.setdefault("port", port)
        self.config.setdefault("path", path)
        self.config.setdefault("scheme", scheme)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import pinotdb
        except ImportError as err:
            raise DriverNotInstalledError(
                "'pinotdb' is not installed. "
                "Install with: pip install 'query-builder-engine[pinot]'"
            ) from err

        try:
            cfg = {
                k: v
                for k, v in self.config.items()
                if k not in ("host", "port", "path", "scheme")
            }
            self._connection = pinotdb.connect(
                host=self.host,
                port=self.port,
                path=self.path,
                scheme=self.scheme,
                **cfg,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Apache Pinot broker at {self.host}:{self.port}: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Apache Pinot OLAP"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables ORDER BY table_name;"
                )
                table_rows = cur.fetchall()
                table_names = [r[0] for r in table_rows if r and r[0]]

                cur.execute(
                    "SELECT table_name, column_name, data_type FROM information_schema.columns ORDER BY table_name;"
                )
                col_rows = cur.fetchall()

                table_cols_map: dict[str, list[dict[str, Any]]] = {}
                for r in col_rows:
                    t_name, c_name, d_type = str(r[0]), str(r[1]), str(r[2])
                    table_cols_map.setdefault(t_name, []).append(
                        {
                            "name": c_name,
                            "data_type": d_type,
                            "is_nullable": True,
                            "is_primary": c_name == "id",
                            "comment": None,
                        }
                    )

                tables: dict[str, dict[str, Any]] = {}
                for tbl in table_names:
                    cols = table_cols_map.get(tbl, [])
                    has_user = any(c["name"] == "user_id" for c in cols)
                    tables[tbl] = {
                        "name": tbl,
                        "columns": cols,
                        "has_user_id": has_user,
                        "user_col": "user_id",
                        "comment": None,
                    }

                raw_snapshot = {
                    "tables": tables,
                    "foreign_keys": [],
                    "relationships": [],
                }
                return normalize_schema_snapshot(
                    raw_snapshot, filter_sensitive=filter_sensitive
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Apache Pinot schema: {exc}"
                ) from exc
