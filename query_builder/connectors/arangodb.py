"""
ArangoDB Multi-Model Document and Graph Database Connector.
===========================================================
Provides ArangoDB connectivity via python-arango, dual sync and async execution protocols,
AQL and SQL query execution, cursor adaptation, and schema introspection.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_arangodb
from query_builder.connectors.registry import register_connector


class _ArangoCursorAdapter:
    """Adapts an ArangoDB database or cursor object into a DB-API cursor interface."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if hasattr(self.db, "aql") and hasattr(self.db.aql, "execute"):
            bind_vars = {f"p{i}": p for i, p in enumerate(params)} if params else {}
            cursor = self.db.aql.execute(clean_sql, bind_vars=bind_vars)
            docs = list(cursor)
            if docs:
                if isinstance(docs[0], dict):
                    col_names = list(docs[0].keys())
                    self.description = [(col,) for col in col_names]
                    self._rows = [[doc.get(c) for c in col_names] for doc in docs]
                else:
                    self.description = [("value",)]
                    self._rows = [[doc] for doc in docs]
            else:
                self.description = []
                self._rows = []
        elif hasattr(self.db, "execute"):
            if params:
                self.db.execute(clean_sql, params)
            else:
                self.db.execute(clean_sql)
            self.description = getattr(self.db, "description", None)
            self._rows = (
                list(self.db.fetchall()) if hasattr(self.db, "fetchall") else []
            )
        else:
            self.description = []
            self._rows = []

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


@register_connector("arangodb", aliases=["arango", "aql"])
class ArangoDBConnector(BaseConnector):
    """Connector for ArangoDB multi-model graph and document database."""

    dialect_name = "arangodb"

    def __init__(
        self,
        hosts: str | list[str] = "http://localhost:8529",
        database: str = "_system",
        username: str = "root",
        password: str = "",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.hosts = hosts
        self.database = database
        self.username = username
        self.password = password
        self.schema_name = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("arango", "arango.client"):
            try:
                driver = __import__(mod_name, fromlist=["ArangoClient"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'python-arango' is not installed. "
                "Install with: pip install 'query-builder-engine[arangodb]'"
            )

        try:
            client_cls = getattr(driver, "ArangoClient", None) or driver
            client = client_cls(hosts=self.hosts, **self.config)
            db = client.db(
                self.database, username=self.username, password=self.password
            )
            self._connection = db
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to ArangoDB database '{self.database}': {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield self._cursor
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield cur
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        else:
            adapter = _ArangoCursorAdapter(conn)
            yield adapter

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "ArangoDB"
        info["database"] = self.database
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_arangodb(
                    cur,
                    database=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect ArangoDB database '{self.database}': {exc}"
                ) from exc


@register_connector("async_arangodb", aliases=["async_arango", "async_aql"])
class AsyncArangoDBConnector(AsyncBaseConnector):
    """Asynchronous connector for ArangoDB multi-model database."""

    dialect_name = "arangodb"

    def __init__(
        self,
        hosts: str | list[str] = "http://localhost:8529",
        database: str = "_system",
        username: str = "root",
        password: str = "",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.hosts = hosts
        self.database = database
        self.username = username
        self.password = password
        self.schema_name = database

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("arango", "arango.client"):
            try:
                driver = __import__(mod_name, fromlist=["ArangoClient"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'python-arango' is not installed. "
                "Install with: pip install 'query-builder-engine[arangodb]'"
            )

        try:
            client_cls = getattr(driver, "ArangoClient", None) or driver
            client = client_cls(hosts=self.hosts, **self.config)
            db = client.db(
                self.database, username=self.username, password=self.password
            )
            self._connection = db
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to ArangoDB: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _ArangoCursorAdapter(conn)
        adapter.execute(sql, params)
        desc = adapter.description or []
        col_names = [col[0] for col in desc]
        rows = adapter.fetchall() or []
        dict_rows = [dict(zip(col_names, r)) for r in rows]
        latency_ms = (time.perf_counter() - start) * 1000.0
        return col_names, dict_rows, latency_ms
