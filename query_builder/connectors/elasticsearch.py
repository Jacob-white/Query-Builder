"""
Elasticsearch / OpenSearch SQL Search Connector.
================================================
Translates SQL query specifications to Elasticsearch /_sql REST API requests.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.schema import normalize_schema_snapshot


class ElasticsearchConnector(BaseConnector):
    """Connector for Elasticsearch and OpenSearch SQL endpoints."""

    dialect_name = "elasticsearch"

    def __init__(
        self,
        endpoint: str = "http://localhost:9200",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.endpoint = endpoint

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            from elasticsearch import Elasticsearch
        except ImportError as err:
            raise DriverNotInstalledError(
                "elasticsearch is not installed. Install with: pip install 'query-builder-engine[elasticsearch]'"
            ) from err

        try:
            self._connection = Elasticsearch(self.endpoint, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Elasticsearch at {self.endpoint}: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Elasticsearch SQL"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                cur.execute("SHOW TABLES")
                table_rows = cur.fetchall()
                tables_map: dict[str, dict[str, Any]] = {}

                for row in table_rows:
                    t_name = str(row[0])
                    cur.execute(f'DESCRIBE "{t_name}"')
                    col_rows = cur.fetchall()
                    cols = []
                    has_user = False
                    for c in col_rows:
                        col_name = str(c[0])
                        if col_name == "user_id":
                            has_user = True
                        cols.append(
                            {
                                "name": col_name,
                                "data_type": str(c[1]).lower(),
                                "is_nullable": True,
                                "is_primary": col_name == "id",
                                "comment": None,
                            }
                        )
                    tables_map[t_name] = {
                        "name": t_name,
                        "columns": cols,
                        "has_user_id": has_user,
                        "user_col": "user_id",
                        "comment": None,
                    }

                return normalize_schema_snapshot(
                    {"tables": tables_map, "foreign_keys": [], "relationships": []},
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Elasticsearch indices: {exc}"
                ) from exc
