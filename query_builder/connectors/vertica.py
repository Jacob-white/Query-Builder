"""
Vertica Columnar Analytical Data Warehouse Connector.
=====================================================
Provides Vertica DB-API connectivity, session runtime cap isolation,
and catalog schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_information_schema
from query_builder.connectors.registry import register_connector


@register_connector("vertica")
class VerticaConnector(BaseConnector):
    """Connector for Vertica columnar analytical data warehouse."""

    dialect_name = "vertica"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5433,
        database: str = "VMart",
        user: str = "dbadmin",
        password: str = "",
        schema_name: str = "public",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import vertica_python
        except ImportError as err:
            raise DriverNotInstalledError(
                "'vertica-python' is not installed. "
                "Install with: pip install 'query-builder-engine[vertica]'"
            ) from err

        try:
            conn_info = {
                "host": self.host,
                "port": self.port,
                "user": self.user,
                "password": self.password,
                "database": self.database,
            }
            conn_info.update(self.config)
            self._connection = vertica_python.connect(**conn_info)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Vertica at {self.host}:{self.port}: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Vertica Columnar Analytical Database"
        return info

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        timeout_sec = max(int(timeout_ms // 1000), 1)
        cursor.execute(f"SET SESSION RUNTIMECAP = '{timeout_sec}s';")

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_information_schema(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Vertica schema '{self.schema_name}': {exc}"
                ) from exc
