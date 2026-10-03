"""
Generic DB-API 2.0 Database Connector.
======================================
Universal connector accepting any active DB-API 2.0 connection or cursor
and configurable with any registered SQL dialect.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import BaseConnector, ConnectionFailedError
from query_builder.connectors.introspection import (
    introspect_information_schema,
    introspect_via_sqlalchemy,
)
from query_builder.dialects import BaseDialect


class GenericDBAPIConnector(BaseConnector):
    """Universal connector for any DB-API 2.0 cursor or connection."""

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        dialect: str | BaseDialect = "postgres",
        engine: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(
            connection=connection, cursor=cursor, dialect=dialect, **config
        )
        self.engine = engine

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection
        if self._cursor is not None:
            return self._cursor
        if self.engine is not None:
            try:
                self._connection = self.engine.raw_connection()
                return self._connection
            except Exception as exc:
                raise ConnectionFailedError(
                    f"Failed to obtain raw connection from engine: {exc}"
                ) from exc

        raise ConnectionFailedError(
            "GenericDBAPIConnector requires an explicit connection, cursor, or engine."
        )

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        if self.engine is not None:
            return introspect_via_sqlalchemy(
                self.engine, filter_sensitive=filter_sensitive
            )

        with self.get_cursor() as cur:
            return introspect_information_schema(cur, filter_sensitive=filter_sensitive)
