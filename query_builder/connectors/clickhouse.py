"""
ClickHouse Real-Time Analytical Database Connector.
===================================================
Provides fast analytical query execution, execution timeout limits, and system catalog introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_clickhouse


class ClickHouseConnector(BaseConnector):
    """Connector for ClickHouse columnar database."""

    dialect_name = "clickhouse"

    def __init__(
        self,
        database: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.database = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import clickhouse_connect
        except ImportError as err:
            raise DriverNotInstalledError(
                "clickhouse-connect is not installed. "
                "Install with: pip install 'query-builder-engine[clickhouse]'"
            ) from err

        try:
            client = clickhouse_connect.get_client(
                database=self.database, **self.config
            )
            self._connection = client
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to ClickHouse: {exc}"
            ) from exc

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        seconds = max(1, timeout_ms // 1000)
        cursor.execute(f"SET max_execution_time = {seconds};")

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
            return introspect_clickhouse(
                cur, database=self.database, filter_sensitive=filter_sensitive
            )
