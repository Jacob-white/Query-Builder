"""
OceanBase Enterprise Distributed Relational Database Connector.
==============================================================
Provides OceanBase multi-tenant connectivity via pyoceanbase / pymysql,
session timeout isolation, and schema introspection.
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


@register_connector("oceanbase")
class OceanBaseConnector(BaseConnector):
    """Connector for OceanBase enterprise distributed database."""

    dialect_name = "oceanbase"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 2881,
        database: str = "test",
        tenant: str = "sys",
        user: str = "root",
        password: str = "",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host = host
        self.port = port
        self.database = database
        self.schema_name = database
        self.tenant = tenant
        self.user = user
        self.password = password
        self.config.setdefault("host", host)
        self.config.setdefault("port", port)
        self.config.setdefault("database", database)
        self.config.setdefault("tenant", tenant)
        self.config.setdefault("user", user)
        self.config.setdefault("password", password)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pyoceanbase", "pymysql", "MySQLdb"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'pyoceanbase' nor 'pymysql' is installed. "
                "Install with: pip install 'query-builder-engine[oceanbase]'"
            )

        try:
            full_user = (
                f"{self.user}@{self.tenant}"
                if self.tenant and "@" not in self.user
                else self.user
            )
            connect_kwargs = {
                "host": self.host,
                "port": self.port,
                "user": full_user,
                "password": self.password,
            }
            if "pymysql" in getattr(driver, "__name__", "") or "pyoceanbase" in getattr(
                driver, "__name__", ""
            ):
                connect_kwargs["database"] = self.database
            cfg = {
                k: v
                for k, v in self.config.items()
                if k
                not in (
                    "host",
                    "port",
                    "user",
                    "password",
                    "database",
                    "db",
                    "tenant",
                )
            }
            connect_kwargs.update(cfg)
            self._connection = driver.connect(**connect_kwargs)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to OceanBase at {self.host}:{self.port}: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "OceanBase Enterprise Distributed Database"
        info["tenant"] = self.tenant
        return info

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        timeout_us = int(timeout_ms * 1000)
        cursor.execute(f"SET ob_query_timeout = {timeout_us};")

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_information_schema(
                    cur,
                    schema_name=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect OceanBase schema '{self.database}': {exc}"
                ) from exc
