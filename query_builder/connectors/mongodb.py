"""
MongoDB Atlas SQL Interface / DB-API Connector.
===============================================
Provides SQL query execution and schema introspection for MongoDB Atlas collections.
"""

from __future__ import annotations

import time
from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_information_schema
from query_builder.schema import normalize_schema_snapshot


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

    def _native_db(self) -> Any:
        """The underlying pymongo Database of a real pymongosql connection."""
        db = getattr(self._connection, "database", None)
        return db if hasattr(db, "list_collection_names") else None

    def test_connection(self) -> dict[str, Any]:
        db = self._native_db() if self._cursor is None and self.connect() else None
        if db is not None and isinstance(getattr(db, "name", None), str):
            # pymongosql's SQL grammar needs a FROM clause, so `SELECT 1` (the
            # generic probe) is a syntax error: ping the server instead.
            start = time.perf_counter()
            db.command("ping")
            info: dict[str, Any] = {
                "status": "healthy",
                "dialect": self.dialect_name,
                "latency_ms": round((time.perf_counter() - start) * 1000.0, 2),
            }
            try:
                info["engine_version"] = f"MongoDB {db.client.server_info()['version']}"
            except Exception:  # noqa: BLE001
                info["engine_version"] = "MongoDB"
        else:
            info = super().test_connection()
            info["engine_version"] = "MongoDB Atlas SQL"
        info["database"] = self.database
        return info

    def _introspect_native(
        self, db: Any, filter_sensitive: bool
    ) -> dict[str, Any] | None:
        """Collections and the union of fields in a sample of their documents."""
        names = db.list_collection_names()
        if not isinstance(names, list):
            return None
        tables: dict[str, dict[str, Any]] = {}
        for name in sorted(n for n in names if not n.startswith("system.")):
            fields: dict[str, str] = {"_id": "ObjectId"}
            for doc in db[name].find({}, limit=100):
                for key, value in doc.items():
                    fields.setdefault(key, type(value).__name__)
            cols = [
                {
                    "name": key,
                    "data_type": dtype,
                    "is_nullable": key != "_id",
                    "is_primary": key == "_id",
                    "comment": None,
                }
                for key, dtype in fields.items()
            ]
            tables[name] = {
                "name": name,
                "columns": cols,
                "has_user_id": "user_id" in fields,
                "user_col": "user_id",
                "comment": None,
            }
        return normalize_schema_snapshot(
            {"tables": tables, "foreign_keys": [], "relationships": []},
            filter_sensitive=filter_sensitive,
        )

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        if self._cursor is None:
            self.connect()
            db = self._native_db()
            if db is not None:
                try:
                    native = self._introspect_native(db, filter_sensitive)
                except Exception as exc:
                    raise IntrospectionError(
                        f"Failed to introspect MongoDB database '{self.database}': {exc}"
                    ) from exc
                if native is not None:
                    return native
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
