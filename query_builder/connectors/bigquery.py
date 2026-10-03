"""
Google BigQuery Cloud Data Warehouse Connector.
===============================================
Provides standard SQL compilation, dataset qualification, and column introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class BigQueryConnector(BaseConnector):
    """Connector for Google BigQuery."""

    dialect_name = "bigquery"

    def __init__(
        self,
        dataset: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.dataset = dataset

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            from google.cloud import bigquery  # noqa: F401
            from google.cloud.bigquery import dbapi
        except ImportError as err:
            raise DriverNotInstalledError(
                "google-cloud-bigquery is not installed. "
                "Install with: pip install 'query-builder-engine[bigquery]'"
            ) from err

        try:
            self._connection = dbapi.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Google BigQuery: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "BigQuery Standard SQL"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_information_schema(
                cur, schema_name=self.dataset, filter_sensitive=filter_sensitive
            )
