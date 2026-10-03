"""
Oracle Database Connector.
==========================
Provides ANSI quoting, OFFSET-FETCH pagination, and user/all_tables schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_oracle


class OracleConnector(BaseConnector):
    """Connector for Oracle Database."""

    dialect_name = "oracle"

    def __init__(
        self,
        owner: str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.owner = owner

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("oracledb", "cx_Oracle"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'oracledb' nor 'cx_Oracle' is installed. "
                "Install with: pip install 'query-builder-engine[oracle]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to Oracle: {exc}") from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute("SELECT 1 FROM DUAL")
            cur.fetchone()
        info["engine_version"] = "Oracle Database"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_oracle(
                cur, owner=self.owner, filter_sensitive=filter_sensitive
            )
