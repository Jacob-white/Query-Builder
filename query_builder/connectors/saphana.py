"""
SAP HANA In-Memory Relational Database Connector.
================================================
Provides SAP HANA DB-API connectivity via hdbcli, system catalog introspection,
and enterprise SQL compilation.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_saphana
from query_builder.connectors.registry import register_connector


@register_connector("saphana", aliases=["hana", "sap_hana"])
class SAPHANAConnector(BaseConnector):
    """Connector for SAP HANA in-memory database."""

    dialect_name = "saphana"

    def __init__(
        self,
        address: str = "localhost",
        port: int = 39015,
        user: str = "SYSTEM",
        password: str = "",
        schema_name: str = "SYSTEM",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.address = address
        self.port = port
        self.user = user
        self.password = password
        self.schema_name = schema_name
        self.config.setdefault("address", address)
        self.config.setdefault("host", address)
        self.config.setdefault("port", port)
        self.config.setdefault("user", user)
        self.config.setdefault("password", password)
        self.config.setdefault("schema_name", schema_name)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("hdbcli.dbapi", "hdbcli"):
            try:
                driver = __import__(mod_name, fromlist=["dbapi"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'hdbcli' is not installed. "
                "Install with: pip install 'query-builder-engine[saphana]'"
            )

        try:
            connect_fn = getattr(driver, "connect", None)
            cfg = {
                k: v
                for k, v in self.config.items()
                if k
                not in (
                    "address",
                    "host",
                    "port",
                    "user",
                    "password",
                    "schema_name",
                    "currentSchema",
                )
            }
            self._connection = connect_fn(
                address=self.address,
                port=self.port,
                user=self.user,
                password=self.password,
                currentSchema=self.schema_name,
                **cfg,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to SAP HANA at {self.address}:{self.port}: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "SAP HANA In-Memory Database"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_saphana(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect SAP HANA schema '{self.schema_name}': {exc}"
                ) from exc


HANAConnector = SAPHANAConnector
