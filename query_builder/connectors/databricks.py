"""
Databricks and Apache Spark SQL Connector.
==========================================
Provides Unity Catalog multi-tier namespace introspection and session execution timeout guards.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class DatabricksConnector(BaseConnector):
    """Connector for Databricks Lakehouse Platform."""

    dialect_name = "databricks"

    def __init__(
        self,
        catalog: str = "main",
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

        try:
            from databricks import sql
        except ImportError as err:
            raise DriverNotInstalledError(
                "databricks-sql-connector is not installed. "
                "Install with: pip install 'query-builder-engine[databricks]'"
            ) from err

        try:
            self._connection = sql.connect(
                catalog=self.catalog, schema=self.schema_name, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Databricks: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Databricks Spark SQL"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_information_schema(
                cur, schema_name=self.schema_name, filter_sensitive=filter_sensitive
            )
