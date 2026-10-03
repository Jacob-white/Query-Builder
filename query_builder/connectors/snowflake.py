"""
Snowflake Cloud Data Warehouse Connector.
=========================================
Provides session-level query timeouts and metadata introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class SnowflakeConnector(BaseConnector):
    """Connector for Snowflake Data Warehouse."""

    dialect_name = "snowflake"

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        schema_name: str = "PUBLIC",
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import snowflake.connector
        except ImportError as err:
            raise DriverNotInstalledError(
                "snowflake-connector-python is not installed. "
                "Install with: pip install 'query-builder-engine[snowflake]'"
            ) from err

        try:
            self._connection = snowflake.connector.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Snowflake: {exc}"
            ) from exc

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        seconds = max(1, timeout_ms // 1000)
        cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {seconds};")

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute("SELECT CURRENT_VERSION();")
            row = cur.fetchone()
            if row:
                info["engine_version"] = row[0]
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_information_schema(
                cur, schema_name=self.schema_name, filter_sensitive=filter_sensitive
            )
