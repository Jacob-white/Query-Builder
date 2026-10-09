"""
Amazon Redshift Cloud Data Warehouse Connector.
===============================================
Provides statement timeout management and schema introspection for AWS Redshift clusters.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class RedshiftConnector(BaseConnector):
    """Connector for Amazon Redshift."""

    dialect_name = "redshift"
    read_only_support = "best_effort"

    def apply_read_only(self, connection: Any) -> None:
        """Best effort: Redshift accepts the PostgreSQL syntax but enforcement varies by
        driver/version; use a read-only database user for a real guarantee."""
        from query_builder.connectors.postgres import _pg_read_only

        _pg_read_only(connection)

    def __init__(
        self,
        schema_name: str = "public",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("redshift_connector", "psycopg2", "psycopg"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'redshift_connector' nor 'psycopg2' is installed. "
                "Install with: pip install 'query-builder-engine[redshift]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Amazon Redshift: {exc}"
            ) from exc

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET statement_timeout = {int(timeout_ms)};")

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
