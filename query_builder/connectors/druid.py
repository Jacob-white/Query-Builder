"""
Apache Druid Real-Time Analytical Database Connector.
=====================================================
Provides Druid SQL connectivity via pydruid, metadata introspection,
and ANSI SQL query execution.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_druid
from query_builder.connectors.registry import register_connector


@register_connector("druid", aliases=["apache_druid"])
class DruidConnector(BaseConnector):
    """Connector for Apache Druid real-time analytical database."""

    dialect_name = "druid"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8888,
        path: str = "/druid/v2/sql",
        schema_name: str = "druid",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host = host
        self.port = port
        self.path = path
        self.schema_name = schema_name
        self.config.setdefault("host", host)
        self.config.setdefault("port", port)
        self.config.setdefault("path", path)
        self.config.setdefault("schema_name", schema_name)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pydruid.db", "pydruid"):
            try:
                driver = __import__(mod_name, fromlist=["db"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pydruid' is not installed. "
                "Install with: pip install 'query-builder-engine[druid]'"
            )

        try:
            connect_fn = getattr(driver, "connect", None) or getattr(
                getattr(driver, "db", None), "connect", None
            )
            scheme = self.config.get("scheme", "http")
            cfg = {
                k: v
                for k, v in self.config.items()
                if k not in ("scheme", "host", "port", "path", "schema_name")
            }
            self._connection = connect_fn(
                host=self.host,
                port=self.port,
                path=self.path,
                scheme=scheme,
                **cfg,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Apache Druid at {self.host}:{self.port}: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Apache Druid"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_druid(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Apache Druid schema '{self.schema_name}': {exc}"
                ) from exc
