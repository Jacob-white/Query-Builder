"""
Google Cloud Spanner Horizontally Scalable SQL Connector.
========================================================
Provides GoogleSQL compilation and cloud database execution.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class SpannerConnector(BaseConnector):
    """Connector for Google Cloud Spanner."""

    dialect_name = "spanner"
    read_only_support = "enforced"

    def __init__(
        self,
        instance_id: str | None = None,
        database_id: str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.instance_id = instance_id
        self.database_id = database_id

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            from google.cloud.spanner_dbapi import connect
        except ImportError as err:
            raise DriverNotInstalledError(
                "google-cloud-spanner is not installed. "
                "Install with: pip install 'query-builder-engine[spanner]'"
            ) from err

        try:
            # spanner_dbapi.connect(instance_id, database_id, project=..., credentials=...)
            self._connection = connect(
                self.instance_id,
                self.database_id,
                **self.config,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Google Cloud Spanner: {exc}"
            ) from exc

    def apply_read_only(self, connection: Any) -> None:
        """Spanner DB-API read-only connections use read-only snapshot transactions."""
        connection.read_only = True

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Google Cloud Spanner GoogleSQL"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            snapshot = introspect_information_schema(
                cur, schema_name="", filter_sensitive=filter_sensitive
            )
            # Spanner has no table_constraints rows for primary keys (the generic query then
            # GUESSES "id"); its real primary key is the PRIMARY_KEY index.
            try:
                cur.execute(
                    "SELECT table_name, column_name FROM information_schema.index_columns "
                    "WHERE index_name = 'PRIMARY_KEY' AND table_schema = ''"
                )
                keys = {(str(r[0]), str(r[1])) for r in cur.fetchall()}
            except Exception:  # noqa: BLE001 - keep the generic answer
                return snapshot
            for table in snapshot.get("tables", {}).values():
                for col in table["columns"]:
                    col["is_primary"] = (table["name"], col["name"]) in keys
            return snapshot
