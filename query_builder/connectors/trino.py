"""
Trino / Presto Distributed SQL Query Engine Connector.
======================================================
Provides ANSI SQL compilation, offset/limit pagination, and schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class TrinoConnector(BaseConnector):
    """Connector for Trino and Presto distributed query engines."""

    dialect_name = "trino"

    def __init__(
        self,
        catalog: str = "memory",
        schema_name: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.catalog = catalog
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("trino.dbapi", "trino"):
            try:
                driver = __import__(mod_name, fromlist=["dbapi"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'trino' is not installed. "
                "Install with: pip install 'query-builder-engine[trino]'"
            )

        try:
            self._connection = driver.connect(
                catalog=self.catalog, schema=self.schema_name, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to Trino: {exc}") from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute("SELECT version();")
            row = cur.fetchone()
            if row:
                info["engine_version"] = row[0]
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_information_schema(
                cur, schema_name=self.schema_name, filter_sensitive=filter_sensitive
            )
