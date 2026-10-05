"""
Unit tests for AsyncBaseConnector and async_execute harness.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from typing import Any

import pytest

from query_builder.compiler import CompilationError
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import BaseConnector
from query_builder.dialects import BaseDialect
from query_builder.exceptions import SecurityError
from query_builder.executor import async_execute
from query_builder.middleware import LifecycleInterceptor, MiddlewarePipeline


class MockAsyncConn:
    def __init__(self, async_close: bool = True) -> None:
        self.closed = False
        self.async_close = async_close

    async def close(self) -> None:
        self.closed = True


class MockSyncCloseConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ConcreteAsyncConnector(AsyncBaseConnector):
    dialect_name = "postgres"

    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        count: int = 1,
        delay_sec: float = 0.0,
        async_close: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.dummy_rows = rows if rows is not None else [{"id": 1, "name": "Test"}]
        self.dummy_count = count
        self.delay_sec = delay_sec
        self.raw_queries: list[tuple[str, list[Any] | None]] = []
        self._mock_conn = MockAsyncConn(async_close=async_close)

    async def connect(self) -> Any:
        self._connection = self._mock_conn
        return self._connection

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        self.raw_queries.append((sql, params))
        if self.delay_sec > 0:
            await asyncio.sleep(self.delay_sec)
        if "COUNT" in sql.upper():
            return ["count"], [{"count": self.dummy_count}], 1.0
        cols = list(self.dummy_rows[0].keys()) if self.dummy_rows else []
        return cols, self.dummy_rows, 1.5


class SyncSQLiteConnector(BaseConnector):
    dialect_name = "sqlite"

    def connect(self) -> Any:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT);")
        conn.execute("INSERT INTO items VALUES (10, 'Widget');")
        return conn


def test_async_base_connector_lifecycle():
    async def _test():
        conn = ConcreteAsyncConnector()
        assert conn._connection is None

        # test connect
        c = await conn.connect()
        assert c is conn._connection
        assert conn._connection.closed is False

        # test close with async close
        await conn.close()
        assert conn._connection is None

        # test close when already closed
        await conn.close()
        assert conn._connection is None

        # test close with sync close
        sync_conn = ConcreteAsyncConnector()
        sync_conn._connection = MockSyncCloseConn()
        await sync_conn.close()
        assert sync_conn._connection is None

        # test close when connection has no close method
        no_close_conn = ConcreteAsyncConnector()
        no_close_conn._connection = 12345
        await no_close_conn.close()
        assert no_close_conn._connection is None

        # test context manager
        async with ConcreteAsyncConnector() as managed:
            assert managed._connection is not None
            assert managed._connection.closed is False
        assert managed._connection is None

        # test execute with validate_ast=False
        res_no_ast = await conn.execute({"table": "users"}, validate_ast=False)
        assert res_no_ast["count"] == 1

    asyncio.run(_test())


def test_async_base_connector_init_dialects():
    class CustomDialect(BaseDialect):
        name = "custom_pg"

    conn1 = ConcreteAsyncConnector(dialect="sqlite")
    assert conn1.dialect_name == "sqlite"

    conn2 = ConcreteAsyncConnector(dialect=CustomDialect())
    assert conn2.dialect_name == "custom_pg"

    conn3 = ConcreteAsyncConnector(dialect=None)
    assert conn3.dialect_name == "postgres"


def test_async_base_connector_health_check():
    async def _test():
        conn = ConcreteAsyncConnector()
        health = await conn.test_connection()
        assert health["status"] == "healthy"
        assert health["dialect"] == "postgres"
        assert health["latency_ms"] >= 0

    asyncio.run(_test())


def test_async_base_connector_fallback_introspection():
    async def _test():
        conn = ConcreteAsyncConnector()
        snapshot = await conn.introspect_schema()
        assert snapshot["tables"] == {}
        assert snapshot["foreign_keys"] == []
        assert snapshot["relationships"] == []

    asyncio.run(_test())


def test_async_base_connector_execute_success():
    async def _test():
        conn = ConcreteAsyncConnector(
            rows=[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}], count=2
        )
        res = await conn.execute({"table": "users", "limit": 10, "offset": 0})
        assert res["count"] == 2
        assert len(res["rows"]) == 2
        assert res["columns"] == ["id", "name"]
        assert res["limit"] == 10
        assert res["offset"] == 0
        assert res["page"] == 1
        assert res["dialect"] == "postgres"

    asyncio.run(_test())


def test_async_base_connector_execute_timeout_validation():
    async def _test():
        conn = ConcreteAsyncConnector()
        with pytest.raises(ValueError, match="statement_timeout_ms must be positive."):
            await conn.execute({"table": "users"}, statement_timeout_ms=-5)

    asyncio.run(_test())


def test_async_base_connector_execute_invalid_spec():
    async def _test():
        conn = ConcreteAsyncConnector()
        with pytest.raises(
            CompilationError,
            match="Specification must be a dictionary or dataclass instance.",
        ):
            await conn.execute(12345)  # type: ignore

    asyncio.run(_test())


def test_async_base_connector_ast_validation_failure():
    async def _test():
        conn = ConcreteAsyncConnector()

        class MainAstCorruptor(LifecycleInterceptor):
            def on_post_compile(
                self, compilation: dict[str, Any], context: dict[str, Any]
            ) -> dict[str, Any] | None:
                compilation["main_sql"] = "DROP TABLE users;"
                return compilation

        with pytest.raises(
            SecurityError, match="Generated query failed AST safety validation"
        ):
            await conn.execute({"table": "users"}, middleware=[MainAstCorruptor()])

        class CountAstCorruptor(LifecycleInterceptor):
            def on_post_compile(
                self, compilation: dict[str, Any], context: dict[str, Any]
            ) -> dict[str, Any] | None:
                compilation["count_sql"] = "DROP TABLE users;"
                return compilation

        with pytest.raises(
            SecurityError,
            match="Generated count query failed AST safety validation",
        ):
            await conn.execute({"table": "users"}, middleware=[CountAstCorruptor()])

    asyncio.run(_test())


def test_async_base_connector_middleware_short_circuit():
    async def _test():
        cached_payload = {
            "sql": "CACHED",
            "params": [],
            "columns": ["id"],
            "rows": [{"id": 42}],
            "count": 1,
            "limit": 50,
            "offset": 0,
            "page": 1,
            "latency_ms": 0.1,
            "dialect": "postgres",
        }

        class CacheHitInterceptor(LifecycleInterceptor):
            def on_pre_execute(
                self, execution_plan: dict[str, Any], context: dict[str, Any]
            ) -> dict[str, Any] | None:
                return cached_payload

        conn = ConcreteAsyncConnector()
        ctx: dict[str, Any] = {}
        res = await conn.execute(
            {"table": "users"}, middleware=[CacheHitInterceptor()], context=ctx
        )
        assert res == cached_payload
        assert ctx.get("short_circuited") is True
        assert len(conn.raw_queries) == 0  # Database execution bypassed!

    asyncio.run(_test())


def test_async_base_connector_middleware_error_hook():
    async def _test():
        errors: list[Exception] = []

        class ErrorInterceptor(LifecycleInterceptor):
            def on_error(self, error: Exception, context: dict[str, Any]) -> None:
                errors.append(error)

        class FailingAsyncConnector(ConcreteAsyncConnector):
            async def execute_raw(
                self, sql: str, params: list[Any] | None = None
            ) -> tuple[list[str], list[dict[str, Any]], float]:
                raise RuntimeError("Database execution error")

        conn = FailingAsyncConnector(middleware=[ErrorInterceptor()])
        with pytest.raises(RuntimeError, match="Database execution error"):
            await conn.execute({"table": "users"})

        assert len(errors) == 1

    asyncio.run(_test())


def test_async_base_connector_count_formats():
    async def _test():
        # Test count returning tuple/list rows instead of dict
        class TupleCountConnector(ConcreteAsyncConnector):
            async def execute_raw(
                self, sql: str, params: list[Any] | None = None
            ) -> tuple[list[str], list[Any], float]:
                if "COUNT" in sql.upper():
                    return ["count"], [(42,)], 1.0
                return ["id"], [{"id": 1}], 1.0

        conn = TupleCountConnector()
        res = await conn.execute({"table": "users"})
        assert res["count"] == 42

        # Test count returning empty tuple row
        class EmptyTupleConnector(ConcreteAsyncConnector):
            async def execute_raw(
                self, sql: str, params: list[Any] | None = None
            ) -> tuple[list[str], list[Any], float]:
                if "COUNT" in sql.upper():
                    return ["count"], [()], 1.0
                return ["id"], [{"id": 1}], 1.0

        conn_tuple = EmptyTupleConnector()
        res_tuple = await conn_tuple.execute({"table": "users"})
        assert res_tuple["count"] == 0

        # Test count returning empty dict row
        class EmptyDictConnector(ConcreteAsyncConnector):
            async def execute_raw(
                self, sql: str, params: list[Any] | None = None
            ) -> tuple[list[str], list[Any], float]:
                if "COUNT" in sql.upper():
                    return ["count"], [{}], 1.0
                return ["id"], [{"id": 1}], 1.0

        conn_dict = EmptyDictConnector()
        res_dict = await conn_dict.execute({"table": "users"})
        assert res_dict["count"] == 0

        # Test count returning empty rows
        class EmptyCountConnector(ConcreteAsyncConnector):
            async def execute_raw(
                self, sql: str, params: list[Any] | None = None
            ) -> tuple[list[str], list[Any], float]:
                if "COUNT" in sql.upper():
                    return ["count"], [], 1.0
                return ["id"], [{"id": 1}], 1.0

        conn_empty = EmptyCountConnector()
        res_empty = await conn_empty.execute({"table": "users"})
        assert res_empty["count"] == 0

    asyncio.run(_test())


def test_async_base_connector_default_execute_raw_raises():
    async def _test():
        class RawNotImplemented(AsyncBaseConnector):
            async def connect(self) -> Any:
                return None

        conn = RawNotImplemented()
        with pytest.raises(
            NotImplementedError, match="Subclasses must implement execute_raw"
        ):
            await conn.execute_raw("SELECT 1")

    asyncio.run(_test())


def test_async_execute_with_async_connector():
    async def _test():
        conn = ConcreteAsyncConnector(rows=[{"id": 1, "name": "Item 1"}], count=1)
        res = await async_execute(conn, {"table": "items"})
        assert res["count"] == 1
        assert res["rows"] == [{"id": 1, "name": "Item 1"}]

    asyncio.run(_test())


def test_async_execute_with_sync_connector():
    async def _test():
        conn = SyncSQLiteConnector()
        res = await async_execute(conn, {"table": "items"})
        assert res["count"] == 1
        assert res["rows"] == [{"id": 10, "title": "Widget"}]

    asyncio.run(_test())


def test_async_execute_timeout_cancellation():
    async def _test():
        errors: list[Exception] = []

        class ErrorLogger(LifecycleInterceptor):
            def on_error(self, error: Exception, context: dict[str, Any]) -> None:
                errors.append(error)

        # Delay of 0.2s with timeout of 50ms (0.05s)
        conn = ConcreteAsyncConnector(delay_sec=0.2)
        pipeline = MiddlewarePipeline([ErrorLogger()])

        with pytest.raises(TimeoutError, match="Query execution timed out after 50ms"):
            await async_execute(
                conn, {"table": "users"}, timeout_ms=50, middleware=pipeline
            )

        assert len(errors) == 1

    asyncio.run(_test())


def test_async_execute_task_cancellation():
    async def _test():
        errors: list[Exception] = []

        class ErrorLogger(LifecycleInterceptor):
            def on_error(self, error: Exception, context: dict[str, Any]) -> None:
                errors.append(error)

        conn = ConcreteAsyncConnector(delay_sec=1.0)
        pipeline = MiddlewarePipeline([ErrorLogger()])

        task = asyncio.create_task(
            async_execute(conn, {"table": "users"}, middleware=pipeline)
        )
        await asyncio.sleep(0.02)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert len(errors) == 1

    asyncio.run(_test())


def test_async_execute_invalid_args():
    async def _test():
        with pytest.raises(ValueError, match="Connector cannot be None."):
            await async_execute(None, {"table": "users"})  # type: ignore

        conn = ConcreteAsyncConnector()
        with pytest.raises(
            CompilationError,
            match="Specification must be a dictionary or dataclass instance.",
        ):
            await async_execute(conn, 12345)  # type: ignore

        with pytest.raises(ValueError, match="timeout_ms must be positive."):
            await async_execute(conn, {"table": "users"}, timeout_ms=-10)

        with pytest.raises(ValueError, match="timeout_ms must be positive."):
            await async_execute(conn, {"table": "users"}, timeout_ms=0)

        with pytest.raises(ValueError, match="timeout_ms must be positive."):
            await async_execute(conn, {"table": "users"}, timeout_ms="invalid")  # type: ignore

    asyncio.run(_test())


def test_async_execute_with_middleware_chain():
    async def _test():
        events: list[str] = []

        class TrackingInterceptor(LifecycleInterceptor):
            def on_pre_compile(
                self, spec: dict[str, Any], context: dict[str, Any]
            ) -> dict[str, Any] | None:
                events.append("pre_compile")
                return None

            def on_post_execute(
                self, result: dict[str, Any], context: dict[str, Any]
            ) -> dict[str, Any] | None:
                events.append("post_execute")
                return None

        conn = ConcreteAsyncConnector()
        res = await async_execute(
            conn, {"table": "users"}, middleware=[TrackingInterceptor()]
        )
        assert res["count"] == 1
        assert events == ["pre_compile", "post_execute"]

    asyncio.run(_test())


def test_async_execute_general_exception():
    async def _test():
        errors: list[Exception] = []

        class ErrorInterceptor(LifecycleInterceptor):
            def on_error(self, error: Exception, context: dict[str, Any]) -> None:
                errors.append(error)

        class FailingConnector:
            middleware = MiddlewarePipeline([ErrorInterceptor()])

            def execute(self, **kwargs: Any) -> Any:
                raise RuntimeError("Sync execute failure")

        conn = FailingConnector()
        with pytest.raises(RuntimeError, match="Sync execute failure"):
            await async_execute(conn, {"table": "users"})

        assert len(errors) == 1

    asyncio.run(_test())


def test_async_execute_with_dataclass():
    async def _test():
        @dataclass
        class QueryDC:
            table: str
            limit: int = 5

        conn = ConcreteAsyncConnector()
        res = await async_execute(conn, QueryDC(table="users"))  # type: ignore
        assert res["count"] == 1

    asyncio.run(_test())
