"""
ArangoDB Multi-Model Document and Graph Database Connector.
===========================================================
Provides ArangoDB connectivity via python-arango, dual sync and async execution protocols,
AQL and SQL query execution, cursor adaptation, and schema introspection.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from query_builder.connectors._native_readonly import assert_read_only
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

    def __init__(self, db: Any, read_only: bool = True) -> None:
        self.db = db
        self.read_only = read_only
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if clean_sql.upper() in ("SELECT 1", "SELECT 1;"):
            clean_sql = "RETURN 1"
        if self.read_only:
            # AQL has REMOVE / REPLACE / UPSERT, which the SQL-shaped generic check misses.
            assert_read_only(clean_sql, "aql", "ArangoDB")
        if hasattr(self.db, "aql") and hasattr(self.db.aql, "execute"):
            bind_vars: dict[str, Any] = {}
            if params:
                if isinstance(params, dict):
                    bind_vars = params
                else:
                    parts = clean_sql.split("?")
                    if len(parts) - 1 == len(params):
                        rebuilt = []
                        for i, part in enumerate(parts[:-1]):
                            rebuilt.append(part)
                            rebuilt.append(f"@p{i}")
                        rebuilt.append(parts[-1])
                        clean_sql = "".join(rebuilt)
                    bind_vars = {f"p{i}": p for i, p in enumerate(params)}
            cursor = self.db.aql.execute(clean_sql, bind_vars=bind_vars)
            docs = list(cursor)
            if docs:
                if isinstance(docs[0], dict):
                    # union of keys in first-seen order: documents are schemaless
                    col_names = list(
                        dict.fromkeys(k for d in docs if isinstance(d, dict) for k in d)
                    )
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


def _server_version(db: Any) -> str:
    """``ArangoDB <version>`` from the server (``/_api/version``); plain name if unavailable."""
    try:
        version = db.version()
    except Exception:  # noqa: BLE001 - the version string is informational only
        return "ArangoDB"
    return f"ArangoDB {version}" if isinstance(version, str) and version else "ArangoDB"


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
            adapter = _ArangoCursorAdapter(conn, read_only=self._read_only())
            yield adapter

    def _read_only(self) -> bool:
        sec = getattr(self, "security", None)
        return sec is None or sec.execution.enforce_read_only_session

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        if self._connection is None and self._cursor is not None:
            # preset cursor only: no driver/connection to ask for the server version
            info["engine_version"] = "ArangoDB"
        else:
            info["engine_version"] = _server_version(self.connect())
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

    def _read_only(self) -> bool:
        sec = getattr(self, "security", None)
        return sec is None or sec.execution.enforce_read_only_session

    def _execute_blocking(
        self, conn: Any, sql: str, params: list[Any] | None
    ) -> tuple[list[str], list[dict[str, Any]]]:
        adapter = _ArangoCursorAdapter(conn, read_only=self._read_only())
        try:
            adapter.execute(sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            return col_names, [dict(zip(col_names, r, strict=False)) for r in rows]
        finally:
            adapter.close()

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        # python-arango is a blocking HTTP client: keep it off the event loop.
        col_names, dict_rows = await asyncio.to_thread(
            self._execute_blocking, conn, sql, params
        )
        return col_names, dict_rows, (time.perf_counter() - start) * 1000.0

    async def test_connection(self) -> dict[str, Any]:
        info = await super().test_connection()
        conn = await self.connect()
        info["engine_version"] = await asyncio.to_thread(_server_version, conn)
        info["database"] = self.database
        return info

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()

        def _blocking() -> dict[str, Any]:
            adapter = _ArangoCursorAdapter(conn, read_only=self._read_only())
            try:
                return introspect_arangodb(
                    adapter, database=self.database, filter_sensitive=filter_sensitive
                )
            finally:
                adapter.close()

        try:
            return await asyncio.to_thread(_blocking)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect ArangoDB database '{self.database}': {exc}"
            ) from exc
