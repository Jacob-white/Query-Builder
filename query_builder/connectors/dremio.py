"""
Dremio SQL Lakehouse Platform Connector.
=========================================
Provides Arrow Flight SQL and DB-API connectivity, session execution,
and schema introspection for Dremio lakehouse datasets.
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


class DremioConnector(BaseConnector):
    """Connector for Dremio SQL Lakehouse platform using Arrow Flight."""

    dialect_name = "dremio"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 32010,
        username: str = "",
        password: str = "",
        flight_endpoint: str | None = None,
        schema_name: str = "public",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.flight_endpoint = flight_endpoint
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            from pyarrow import flight
        except ImportError as err:
            raise DriverNotInstalledError(
                "pyarrow is not installed. "
                "Install with: pip install 'query-builder-engine[dremio]'"
            ) from err

        try:
            location = (
                self.flight_endpoint
                if self.flight_endpoint
                else f"grpc://{self.host}:{self.port}"
            )
            client = flight.FlightClient(location, **self.config)
            if self.username and self.password:
                client.authenticate_basic_token(self.username, self.password)
            self._connection = client
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Dremio at {self.host}:{self.port}: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Dremio Arrow Flight SQL"
        return info

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
                    f"Failed to introspect Dremio schema '{self.schema_name}': {exc}"
                ) from exc
