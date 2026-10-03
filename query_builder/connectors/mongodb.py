"""
MongoDB Atlas SQL Interface / DB-API Connector.
===============================================
Provides SQL query execution and schema introspection for MongoDB Atlas collections.
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


class MongoDBAtlasSQLConnector(BaseConnector):
    """Connector for MongoDB Atlas SQL interface / DB-API."""

    dialect_name = "mongodb"

    def __init__(
        self,
        database: str = "sample_mflix",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.database = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import pymongosql
        except ImportError as err:
            raise DriverNotInstalledError(
                "pymongosql is not installed. "
                "Install with: pip install 'query-builder-engine[mongodb]'"
            ) from err

        try:
            self._connection = pymongosql.connect(database=self.database, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to MongoDB Atlas SQL database '{self.database}': {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "MongoDB Atlas SQL"
        info["database"] = self.database
        return info

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
                    f"Failed to introspect MongoDB Atlas SQL schema '{self.database}': {exc}"
                ) from exc


MongoDBConnector = MongoDBAtlasSQLConnector
