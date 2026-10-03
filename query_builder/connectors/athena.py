"""
AWS Athena and Glue Data Catalog Connector.
===========================================
Provides serverless SQL exploration against Amazon S3 data lakes and AWS Glue Catalogs.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class AthenaConnector(BaseConnector):
    """Connector for AWS Athena."""

    dialect_name = "athena"

    def __init__(
        self,
        schema_name: str = "default",
        s3_staging_dir: str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.schema_name = schema_name
        self.s3_staging_dir = s3_staging_dir

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            from pyathena import connect
        except ImportError as err:
            raise DriverNotInstalledError(
                "pyathena is not installed. "
                "Install with: pip install 'query-builder-engine[athena]'"
            ) from err

        try:
            self._connection = connect(
                s3_staging_dir=self.s3_staging_dir,
                schema_name=self.schema_name,
                **self.config,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to AWS Athena: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "AWS Athena Presto/Trino Engine"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_information_schema(
                cur, schema_name=self.schema_name, filter_sensitive=filter_sensitive
            )
