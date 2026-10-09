"""
SurrealDB Multi-Model Document/Graph Database Connector.
========================================================
Provides SurrealDB connectivity via surrealdb SDK, dual sync and async execution protocols,
SurrealQL query execution, cursor adaptation, and schema introspection.
"""

from __future__ import annotations

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
from query_builder.connectors.introspection import (
    introspect_surrealdb,
    surreal_schema_steps,
)
from query_builder.connectors.registry import register_connector


def _plain(value: Any) -> Any:
    """SDK value types (RecordID, Datetime, Duration, UUID, ...) as JSON-friendly values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return str(value)


def _statement_records(res: Any) -> list[Any]:
    """Records of the first statement, for both SDK result shapes.

    SDK >= 1.0 returns the first statement's result directly (a list of records, or a scalar
    for ``RETURN 1``); older SDKs return ``[{"result": ..., "status": "OK"}, ...]``.
    """
    if isinstance(res, list) and res:
        first = res[0]
        if (
            isinstance(first, dict)
            and "result" in first
            and set(first) <= {"result", "status", "time"}
        ):
            items = first["result"]
            return (
                items if isinstance(items, list) else ([] if items is None else [items])
            )
        return res
    if isinstance(res, list) or res is None:
        return []
    return [res]


def _server_url(url: str) -> str:
    """The SDK appends ``/rpc`` itself; a configured ``.../rpc`` would be doubled."""
    return url[: -len("/rpc")] if url.rstrip("/").endswith("/rpc") else url


class _SurrealCursorAdapter:
    """Adapts a SurrealDB client instance into a DB-API cursor interface."""

    def __init__(self, client: Any, read_only: bool = True) -> None:
        self.client = client
        self.read_only = read_only
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def prepare(self, sql: str, params: Any = None) -> tuple[str, dict[str, Any]]:
        clean_sql = sql.strip().rstrip(";").strip()
        if clean_sql.upper() in ("SELECT 1", "SELECT 1;"):
            clean_sql = "RETURN 1"
        if self.read_only:
            assert_read_only(clean_sql, "surrealql", "SurrealDB")
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
                        rebuilt.append(f"$p{i}")
                    rebuilt.append(parts[-1])
                    clean_sql = "".join(rebuilt)
                bind_vars = {f"p{i}": p for i, p in enumerate(params)}
        return clean_sql, bind_vars

    def load(self, res: Any) -> None:
        """Turn one SDK query result into ``description`` + rows."""
        items = [_plain(i) for i in _statement_records(res)]
        if items and isinstance(items[0], dict):
            col_names = list(
                dict.fromkeys(k for i in items if isinstance(i, dict) for k in i)
            )
            self.description = [(col,) for col in col_names]
            self._rows = [[i.get(c) for c in col_names] for i in items]
        elif items:
            self.description = [("value",)]
            self._rows = [[item] for item in items]
        else:
            self.description = []
            self._rows = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql, bind_vars = self.prepare(sql, params)
        if hasattr(self.client, "query"):
            self.load(self.client.query(clean_sql, bind_vars or None))
        elif hasattr(self.client, "execute"):
            if params:
                self.client.execute(clean_sql, params)
            else:
                self.client.execute(clean_sql)
            self.description = getattr(self.client, "description", None)
            self._rows = (
                list(self.client.fetchall()) if hasattr(self.client, "fetchall") else []
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


def _import_driver() -> Any:
    for mod_name in ("surrealdb", "surrealdb.ws"):
        try:
            return __import__(mod_name, fromlist=["Surreal", "connect"])
        except ImportError:
            continue
    raise DriverNotInstalledError(
        "'surrealdb' is not installed. "
        "Install with: pip install 'query-builder-engine[surrealdb]'"
    )


def _credentials(username: str | None, password: str | None) -> dict[str, str] | None:
    return {"username": username, "password": password or ""} if username else None


@register_connector("surrealdb", aliases=["surreal"])
class SurrealDBConnector(BaseConnector):
    """Connector for SurrealDB multi-model database engine."""

    dialect_name = "surrealdb"

    def __init__(
        self,
        url: str = "ws://localhost:8000/rpc",
        database: str = "test",
        namespace: str = "test",
        connection: Any = None,
        cursor: Any = None,
        username: str | None = None,
        password: str | None = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.url = url
        self.database = database
        self.namespace = namespace
        self.username = username
        self.password = password
        self.schema_name = database
        self.config.setdefault("url", url)
        self.config.setdefault("database", database)
        self.config.setdefault("namespace", namespace)
        if password is not None:
            self.config.setdefault("password", password)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = _import_driver()

        try:
            surreal_cls = getattr(driver, "Surreal", None)
            url = _server_url(self.url)
            client = surreal_cls(url) if surreal_cls else driver.connect(url)
            creds = _credentials(self.username, self.password)
            try:
                if creds and hasattr(client, "signin"):
                    client.signin(creds)
                if hasattr(client, "use"):
                    client.use(self.namespace, self.database)
            except Exception:
                with contextlib.suppress(Exception):
                    client.close()
                raise
            self._connection = client
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to SurrealDB at '{self.url}': {exc}"
            ) from exc

    def _read_only(self) -> bool:
        sec = getattr(self, "security", None)
        return sec is None or sec.execution.enforce_read_only_session

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
            adapter = _SurrealCursorAdapter(conn, read_only=self._read_only())
            yield adapter

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "SurrealDB"
        conn = self._connection
        if conn is not None and hasattr(conn, "version"):
            with contextlib.suppress(Exception):
                info["engine_version"] = str(conn.version())
        info["database"] = self.database
        info["namespace"] = self.namespace
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_surrealdb(
                    cur,
                    database=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect SurrealDB database '{self.database}': {exc}"
                ) from exc


@register_connector("async_surrealdb", aliases=["async_surreal"])
class AsyncSurrealDBConnector(AsyncBaseConnector):
    """Asynchronous connector for SurrealDB multi-model database."""

    dialect_name = "surrealdb"

    def __init__(
        self,
        url: str = "ws://localhost:8000/rpc",
        database: str = "test",
        namespace: str = "test",
        connection: Any = None,
        username: str | None = None,
        password: str | None = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.url = url
        self.database = database
        self.namespace = namespace
        self.username = username
        self.password = password
        self.schema_name = database
        self.config.setdefault("url", url)
        self.config.setdefault("database", database)
        self.config.setdefault("namespace", namespace)
        if password is not None:
            self.config.setdefault("password", password)

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = _import_driver()

        try:
            url = _server_url(self.url)
            # the async SDK entry point is AsyncSurreal; Surreal is its blocking twin
            surreal_cls = getattr(driver, "AsyncSurreal", None) or getattr(
                driver, "Surreal", None
            )
            client = surreal_cls(url) if surreal_cls else driver.connect(url)
            try:
                if hasattr(client, "connect"):
                    await _maybe_await(client.connect())
                creds = _credentials(self.username, self.password)
                if creds and hasattr(client, "signin"):
                    await _maybe_await(client.signin(creds))
                if hasattr(client, "use"):
                    await _maybe_await(client.use(self.namespace, self.database))
            except Exception:
                with contextlib.suppress(Exception):
                    await _maybe_await(client.close())
                raise
            self._connection = client
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to SurrealDB: {exc}"
            ) from exc

    def _read_only(self) -> bool:
        sec = getattr(self, "security", None)
        return sec is None or sec.execution.enforce_read_only_session

    async def _run(self, sql: str, params: Any = None) -> _SurrealCursorAdapter:
        conn = await self.connect()
        adapter = _SurrealCursorAdapter(conn, read_only=self._read_only())
        clean_sql, bind_vars = adapter.prepare(sql, params)
        adapter.load(await _maybe_await(conn.query(clean_sql, bind_vars or None)))
        return adapter

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        start = time.perf_counter()
        adapter = await self._run(sql, params)
        col_names = [col[0] for col in adapter.description or []]
        rows = adapter.fetchall() or []
        dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
        return col_names, dict_rows, (time.perf_counter() - start) * 1000.0

    async def test_connection(self) -> dict[str, Any]:
        info = await super().test_connection()
        info["engine_version"] = "SurrealDB"
        conn = self._connection
        if conn is not None and hasattr(conn, "version"):
            with contextlib.suppress(Exception):
                info["engine_version"] = str(await _maybe_await(conn.version()))
        info["database"] = self.database
        info["namespace"] = self.namespace
        return info

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        try:
            steps = surreal_schema_steps(filter_sensitive)
            statement = next(steps)
            while True:
                adapter = await self._run(statement)
                names = [c[0] for c in adapter.description or []]
                records = [
                    dict(zip(names, row, strict=False))
                    for row in adapter.fetchall() or []
                ]
                statement = steps.send(records)
        except StopIteration as done:
            return done.value  # type: ignore[no-any-return]
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect SurrealDB database '{self.database}': {exc}"
            ) from exc


async def _maybe_await(value: Any) -> Any:
    """Await ``value`` when it is awaitable (async SDK) and pass it through otherwise."""
    if hasattr(value, "__await__"):
        return await value
    return value
