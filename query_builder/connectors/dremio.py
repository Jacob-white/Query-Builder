"""
Dremio SQL Lakehouse Platform Connector.
=========================================
Provides Arrow Flight SQL and DB-API connectivity, session execution,
and schema introspection for Dremio lakehouse datasets.
"""

from __future__ import annotations

import contextlib
import copy
import os
from collections.abc import Iterator
from typing import Any

from query_builder.config import SecurityConfig, get_security_config
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_information_schema
from query_builder.security import validate_network_target


class _DremioFlightCursor:
    """DB-API cursor interface wrapping Dremio Arrow Flight client."""

    def __init__(self, flight_client: Any) -> None:
        self.flight_client = flight_client
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        if hasattr(self.flight_client, "get_flight_info"):
            try:
                from pyarrow import flight
            except ImportError as err:
                raise DriverNotInstalledError(
                    "pyarrow is not installed. Install with: pip install 'query-builder-engine[dremio]'"
                ) from err

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
        self.config.setdefault("username", username)
        self.config.setdefault("password", password)
        self.config.setdefault("schema_name", schema_name)
        if flight_endpoint is not None:
            self.config.setdefault("flight_endpoint", flight_endpoint)
            self.config.setdefault("endpoint", flight_endpoint)
            if host != "localhost":
                self.config.setdefault("host", host)
            if port != 32010:
                self.config.setdefault("port", port)
        else:
            self.config.setdefault("host", host)
            self.config.setdefault("port", port)

    def _validate_network_target(
        self, security_config: SecurityConfig | None = None
    ) -> None:
        sec = (
            security_config or getattr(self, "security", None) or get_security_config()
        )
        if not sec or not sec.network:
            return

        net_cfg = sec.network
        if not self._explicit_security:
            net_cfg = copy.copy(net_cfg)
            if "QB_ALLOW_PRIVATE_NETWORKS" in os.environ:
                from query_builder.config import _parse_bool

                net_cfg.allow_private_networks = _parse_bool(
                    os.environ["QB_ALLOW_PRIVATE_NETWORKS"],
                    "QB_ALLOW_PRIVATE_NETWORKS",
                )
            elif "QB_SECURITY_PROFILE" not in os.environ:
                net_cfg.allow_private_networks = True
            if "QB_ENFORCE_TLS" in os.environ:
                from query_builder.config import _parse_bool

                net_cfg.enforce_tls = _parse_bool(
                    os.environ["QB_ENFORCE_TLS"],
                    "QB_ENFORCE_TLS",
                )
            elif "QB_SECURITY_PROFILE" not in os.environ:
                net_cfg.enforce_tls = False

        if self.flight_endpoint:
            validate_network_target(
                url=self.flight_endpoint,
                network_config=net_cfg,
                config=dict(self.config),
            )

        if not self.flight_endpoint or self.host != "localhost":
            validate_network_target(
                host=self.host,
                port=self.port,
                network_config=net_cfg,
                config=dict(self.config),
            )

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
            flight_kwargs = {
                k: v
                for k, v in self.config.items()
                if k
                not in (
                    "host",
                    "port",
                    "username",
                    "password",
                    "schema_name",
                    "flight_endpoint",
                    "endpoint",
                )
            }
            client = flight.FlightClient(location, **flight_kwargs)
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
