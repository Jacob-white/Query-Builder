"""
Redis / RediSearch Secondary Index Connector.
=============================================
Provides Redis / RediSearch connectivity via redis-py (FT.SEARCH / FT.INFO),
dual sync and async execution protocols, and index schema introspection.
"""

from __future__ import annotations

import contextlib
import inspect
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import (
    introspect_redis_search,
    parse_ft_info,
)
from query_builder.connectors.registry import register_connector
from query_builder.security import SecurityError

#: Commands the raw-command path may send. Anything else (FLUSHALL, SET, DEL,
#: FT.CREATE, FT.DROPINDEX, EVAL, CONFIG SET, ...) is refused client-side.
READ_ONLY_COMMANDS: frozenset[str] = frozenset(
    {
        "PING", "INFO", "DBSIZE", "TIME", "ECHO", "EXISTS", "TYPE", "TTL", "PTTL",
        "GET", "MGET", "STRLEN", "HGET", "HMGET", "HGETALL", "HLEN", "HEXISTS",
        "HKEYS", "HVALS", "LRANGE", "LLEN", "LINDEX", "SMEMBERS", "SCARD",
        "SISMEMBER", "ZRANGE", "ZCARD", "ZSCORE", "ZRANK", "SCAN", "HSCAN",
        "SSCAN", "ZSCAN", "KEYS", "JSON.GET", "JSON.MGET",
        "FT.SEARCH", "FT.AGGREGATE", "FT.INFO", "FT._LIST", "FT.EXPLAIN",
        "FT.EXPLAINCLI", "FT.PROFILE", "FT.TAGVALS", "FT.SYNDUMP", "FT.SPELLCHECK",
        "FT.DICTDUMP",
    }
)  # fmt: skip


class _RedisSearchCursorAdapter:
    """Adapts a Redis client into a DB-API cursor interface for RediSearch."""

    def __init__(self, connection: Any) -> None:
        self.conn = connection
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if hasattr(self.conn, "cursor"):
            cur = self.conn.cursor()
            try:
                if params:
                    cur.execute(clean_sql, params)
                else:
                    cur.execute(clean_sql)
                self.description = getattr(cur, "description", None)
                self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        elif hasattr(self.conn, "execute_command"):
            parts = clean_sql.split()
            cmd = parts[0] if parts else "PING"
            args = parts[1:] if len(parts) > 1 else []
            if cmd.upper() not in READ_ONLY_COMMANDS:
                # Redis has no read-only session: only known read commands pass.
                raise SecurityError(
                    f"Read-only session violation: Redis command '{cmd}' is not a "
                    "permitted read command."
                )
            res = self.conn.execute_command(cmd, *args)
            if hasattr(res, "__await__"):
                import asyncio

                try:
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None

                    if loop is not None and loop.is_running():
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            res = pool.submit(asyncio.run, res).result()
                    else:
                        res = asyncio.run(res)
                except Exception:  # noqa: BLE001, S110
                    pass
            self.description = [("result",)]
            if isinstance(res, list):
                self._rows = [
                    [r.decode() if isinstance(r, bytes) else str(r)] for r in res
                ]
            else:
                val = res.decode() if isinstance(res, bytes) else str(res)
                self._rows = [[val]]
        elif hasattr(self.conn, "execute"):
            res = (
                self.conn.execute(clean_sql, params)
                if params
                else self.conn.execute(clean_sql)
            )
            self.description = getattr(res, "description", None)
            if hasattr(res, "fetchall"):
                self._rows = list(res.fetchall())
            elif isinstance(res, (list, tuple)):
                self._rows = list(res)
            else:
                self._rows = []
        else:
            self.description = None
            self._rows = []

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def fetchmany(self, size: int = 1) -> list[list[Any]]:
        if not self._rows:
            return []
        res = self._rows[:size]
        self._rows = self._rows[size:]
        return res

    def close(self) -> None:
        self._rows = []


@register_connector("redis", aliases=["redisearch", "redis_search"])
class RedisSearchConnector(BaseConnector):
    """Connector for Redis and RediSearch secondary index engine."""

    dialect_name = "redis"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host = host
        self.port = port
        self.db = db
        self.password = password

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("redis", "redis.client"):
            try:
                driver = __import__(mod_name, fromlist=["Redis", "from_url"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'redis' is not installed. "
                "Install with: pip install 'query-builder-engine[redis]'"
            )

        try:
            self._connection = driver.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                **self.config,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to Redis: {exc}") from exc

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
            adapter = _RedisSearchCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "ping"):
            conn.ping()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Redis / RediSearch",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_redis_search(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect RediSearch schema: {exc}"
                ) from exc


@register_connector("async_redis", aliases=["async_redisearch", "async_redis_search"])
class AsyncRedisSearchConnector(AsyncBaseConnector):
    """Asynchronous connector for Redis and RediSearch."""

    dialect_name = "redis"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.host = host
        self.port = port
        self.db = db
        self.password = password

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("redis.asyncio", "redis"):
            try:
                driver = __import__(mod_name, fromlist=["Redis"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'redis' is not installed. "
                "Install with: pip install 'query-builder-engine[redis]'"
            )

        try:
            redis_cls = getattr(driver, "Redis", driver)
            self._connection = redis_cls(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                **self.config,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Redis: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "execute_command") and not hasattr(conn, "cursor"):
            parts = sql.strip().rstrip(";").strip().split()
            cmd = parts[0] if parts else "PING"
            args = parts[1:] if len(parts) > 1 else []
            if cmd.upper() not in READ_ONLY_COMMANDS:
                raise SecurityError(
                    f"Read-only session violation: Redis command '{cmd}' is not a "
                    "permitted read command."
                )
            res = conn.execute_command(cmd, *args)
            if hasattr(res, "__await__"):
                res = await res
            col_names = ["result"]
            if isinstance(res, list):
                dict_rows = [
                    {"result": r.decode() if isinstance(r, bytes) else str(r)}
                    for r in res
                ]
            else:
                val = res.decode() if isinstance(res, bytes) else str(res)
                dict_rows = [{"result": val}]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms

        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _RedisSearchCursorAdapter(conn)

        try:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            desc = cur.description or []
            col_names = [col[0] for col in desc]
            rows = cur.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            if hasattr(cur, "close"):
                cur.close()

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        if hasattr(conn, "ping"):
            res = conn.ping()
            if hasattr(res, "__await__"):
                await res
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Redis / RediSearch",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        if inspect.iscoroutinefunction(getattr(conn, "execute_command", None)):
            # real redis.asyncio client: every call must be awaited
            try:
                names = await conn.execute_command("FT._LIST")
                indexes: dict[str, list[dict[str, Any]]] = {}
                for raw in names or []:
                    name = raw.decode() if isinstance(raw, bytes) else str(raw)
                    try:
                        indexes[name] = parse_ft_info(
                            await conn.execute_command("FT.INFO", name)
                        )
                    except Exception:  # noqa: BLE001 - index dropped meanwhile
                        indexes[name] = []
                return introspect_redis_search(
                    conn, filter_sensitive=filter_sensitive, _indexes=indexes
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect RediSearch schema: {exc}"
                ) from exc
        cur = (
            conn.cursor()
            if hasattr(conn, "cursor")
            else _RedisSearchCursorAdapter(conn)
        )
        try:
            return introspect_redis_search(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect RediSearch schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
