"""
Dremio SQL Lakehouse Platform Connector.
=========================================
Provides Arrow Flight SQL and DB-API connectivity, session execution,
and schema introspection for Dremio lakehouse datasets.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_information_schema


class _DremioFlightCursor:
    """DB-API cursor interface wrapping Dremio Arrow Flight client."""

    def __init__(self, flight_client: Any) -> None:
        self.flight_client = flight_client
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        if hasattr(self.flight_client, "get_flight_info"):
            from pyarrow import flight

            descriptor = flight.FlightDescriptor.for_command(
                sql.encode("utf-8") if isinstance(sql, str) else sql
            )
            flight_info = self.flight_client.get_flight_info(descriptor)
            endpoints = flight_info.endpoints
            if not endpoints:
                self.description = None
                self._rows = []
                return

            reader = self.flight_client.do_get(endpoints[0].ticket)
            table = reader.read_all()
            names = list(table.column_names)
            self.description = [(name,) for name in names]
            pylist = table.to_pylist()
            self._rows = [[row.get(n) for n in names] for row in pylist]
            return

        if hasattr(self.flight_client, "execute"):
            self.flight_client.execute(sql, params)
            self.description = getattr(self.flight_client, "description", None)
            self._rows = getattr(self.flight_client, "fetchall", list)()

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


class _DremioFlightClient:
    """Connection abstraction providing cursor creation for Dremio Arrow Flight."""

    def __init__(self, flight_client: Any) -> None:
        self.flight_client = flight_client

    def cursor(self) -> _DremioFlightCursor:
        return _DremioFlightCursor(self.flight_client)

    def close(self) -> None:
        if hasattr(self.flight_client, "close"):
            self.flight_client.close()


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
            self._connection = _DremioFlightClient(client)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Dremio at {self.host}:{self.port}: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Iterator[Any]:
        if self._cursor is not None:
            yield self._cursor
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield cur
            finally:
                with contextlib.suppress(Exception):
                    cur.close()
        else:
            cur = _DremioFlightCursor(conn)
            try:
                yield cur
            finally:
                with contextlib.suppress(Exception):
                    cur.close()

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
