"""
Google Cloud AlloyDB for PostgreSQL Connector.
==============================================
Provides AlloyDB connectivity, columnar engine acceleration management,
cluster instance awareness, and schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.postgres import PostgresConnector
from query_builder.connectors.registry import register_connector


@register_connector("alloydb")
class AlloyDBConnector(PostgresConnector):
    """Connector for Google Cloud AlloyDB for PostgreSQL clusters."""

    dialect_name = "alloydb"

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        schema_name: str = "public",
        project_id: str | None = None,
        region: str | None = None,
        cluster_id: str | None = None,
        instance_id: str | None = None,
        enable_columnar_engine: bool = True,
        **config: Any,
    ) -> None:
        super().__init__(
            connection=connection,
            cursor=cursor,
            schema_name=schema_name,
            **config,
        )
        self.project_id = project_id
        self.region = region
        self.cluster_id = cluster_id
        self.instance_id = instance_id
        self.enable_columnar_engine = enable_columnar_engine

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("google.cloud.alloydb.connector", "psycopg", "psycopg2"):
            try:
                driver = __import__(mod_name, fromlist=["connector"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'google-cloud-alloydb-connector' nor 'psycopg' is installed. "
                "Install with: pip install 'query-builder-engine[alloydb]'"
            )

        try:
            if hasattr(driver, "connect"):
                self._connection = driver.connect(**self.config)
            elif hasattr(driver, "Connector"):
                connector_inst = driver.Connector()
                self._connection = connector_inst.connect(
                    f"projects/{self.project_id}/locations/{self.region}/clusters/{self.cluster_id}/instances/{self.instance_id}",
                    "psycopg",
                    **self.config,
                )
            else:
                raise ConnectionFailedError("Unrecognized AlloyDB driver interface.")
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Google Cloud AlloyDB: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Google Cloud AlloyDB for PostgreSQL"
        if self.cluster_id:
            info["alloydb_cluster"] = self.cluster_id
        if self.instance_id:
            info["alloydb_instance"] = self.instance_id
        info["columnar_engine"] = self.enable_columnar_engine
        return info

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)};")
