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


def bind_escaped_quote_literals(sql: str, params: Any) -> tuple[str, Any]:
    """Turn string literals that use the SQL ``''`` quote escape into bound ``?`` parameters.

    pymongosql does not understand the doubled-quote escape: ``WHERE name = 'O''Brien'``
    matches nothing and silently returns no rows. Binding the value through the driver's
    own ``?`` placeholder is understood correctly, so every single-quoted literal containing
    ``''`` is replaced by ``?`` and its unescaped value is inserted into the positional
    parameter list at the matching position. Literals without ``''``, double-quoted or
    backtick-quoted identifiers, SQL that is not a positional-parameter list (dict params)
    and unterminated literals are left exactly as written.
    """
    if "''" not in sql or not (params is None or isinstance(params, (list, tuple))):
        return sql, params
    out: list[str] = []
    new_params = list(params or [])
    placeholders = 0  # `?` seen so far outside literals (index into the parameter list)
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in '"`':  # quoted identifier: copy verbatim
            end = sql.find(ch, i + 1)
            if end == -1:
                return sql, params
            out.append(sql[i : end + 1])
            i = end + 1
        elif ch == "'":
            j, value = i + 1, []
            while True:
                end = sql.find("'", j)
                if end == -1:
                    return sql, params  # unterminated: let the driver report it
                value.append(sql[j:end])
                if sql[end + 1 : end + 2] == "'":
                    value.append("'")
                    j = end + 2
                    continue
                break
            if len(value) > 1:  # contained at least one doubled quote
                new_params.insert(placeholders, "".join(value))
                placeholders += 1
                out.append("?")
            else:
                out.append(sql[i : end + 1])
            i = end + 1
        else:
            if ch == "?":
                placeholders += 1
            out.append(ch)
            i += 1
    return "".join(out), new_params


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

    def prepare_raw_sql(self, sql: str, params: list[Any]) -> tuple[str, list[Any]]:
        new_sql, new_params = bind_escaped_quote_literals(sql, params)
        return new_sql, new_params

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
