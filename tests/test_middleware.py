"""
Unit tests for execution lifecycle middleware and interceptor pipeline.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

import pytest

from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.connectors.base import BaseConnector, QueryExecutionError
from query_builder.middleware import (
    LifecycleInterceptor,
    MiddlewarePipeline,
    QueryCancelledError,
)


class InMemorySQLiteConnector(BaseConnector):
    dialect_name = "sqlite"

    def connect(self) -> Any:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);"
        )
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@test.com');")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'bob@test.com');")
        return conn


def test_lifecycle_interceptor_default_hooks():
    interceptor = LifecycleInterceptor()
    ctx: dict[str, Any] = {}
    assert interceptor.on_pre_compile({"table": "users"}, ctx) is None
    assert (
        interceptor.on_post_compile(
            {
                "main_sql": "SELECT 1",
                "main_params": [],
                "count_sql": "SELECT 1",
                "count_params": [],
            },
            ctx,
        )
        is None
    )
    assert interceptor.on_pre_execute({"main_sql": "SELECT 1"}, ctx) is None
    assert interceptor.on_post_execute({"rows": []}, ctx) is None
    assert interceptor.on_error(RuntimeError("test"), ctx) is None


def test_middleware_pipeline_ensure_and_add():
    p1 = MiddlewarePipeline.ensure(None)
    assert isinstance(p1, MiddlewarePipeline)
    assert len(p1.interceptors) == 0

    p2 = MiddlewarePipeline.ensure(p1)
    assert p2 is p1

    interceptor = LifecycleInterceptor()
    p3 = MiddlewarePipeline.ensure(interceptor)
    assert len(p3.interceptors) == 1

    p4 = MiddlewarePipeline.ensure([interceptor])
    assert len(p4.interceptors) == 1

    p5 = MiddlewarePipeline.ensure((interceptor,))
    assert len(p5.interceptors) == 1

    with pytest.raises(TypeError, match="Cannot convert str to MiddlewarePipeline"):
        MiddlewarePipeline.ensure("invalid")

    with pytest.raises(TypeError, match="Expected LifecycleInterceptor, got str"):
        p1.add("invalid")  # type: ignore

    res = p1.add(interceptor)
    assert res is p1
    assert len(p1.interceptors) == 1


def test_pre_compile_spec_rewriting():
    class TableRewriter(LifecycleInterceptor):
        def on_pre_compile(
            self, spec: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            new_spec = dict(spec)
            new_spec["table"] = "users"
            return new_spec

    conn = InMemorySQLiteConnector(middleware=[TableRewriter()])
    res = conn.execute({"table": "dummy"})
    assert res["count"] == 2
    assert len(res["rows"]) == 2


def test_pre_compile_invalid_return_type():
    class BadInterceptor(LifecycleInterceptor):
        def on_pre_compile(
            self, spec: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            return "not a dict"  # type: ignore

    conn = InMemorySQLiteConnector(middleware=[BadInterceptor()])
    with pytest.raises(TypeError, match="on_pre_compile must return dict or None"):
        conn.execute({"table": "users"})


def test_post_compile_sql_rewriting():
    class CommentAppender(LifecycleInterceptor):
        def on_post_compile(
            self, compilation: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            compilation["main_sql"] += "\n-- audit: req_123"
            return compilation

    conn = InMemorySQLiteConnector(middleware=[CommentAppender()])
    res = conn.execute({"table": "users"})
    assert "-- audit: req_123" in res["sql"]


def test_post_compile_invalid_return_type():
    class BadPostCompile(LifecycleInterceptor):
        def on_post_compile(
            self, compilation: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            return 12345  # type: ignore

    conn = InMemorySQLiteConnector(middleware=[BadPostCompile()])
    with pytest.raises(TypeError, match="on_post_compile must return dict or None"):
        conn.execute({"table": "users"})


def test_pre_execute_short_circuit_cache_hit():
    cached_payload = {
        "sql": "CACHED",
        "params": [],
        "columns": ["id", "val"],
        "rows": [{"id": 99, "val": "cached_val"}],
        "count": 1,
        "limit": 50,
        "offset": 0,
        "page": 1,
        "latency_ms": 0.5,
        "dialect": "sqlite",
    }

    class CacheInterceptor(LifecycleInterceptor):
        def on_pre_execute(
            self, execution_plan: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            context["cache_hit"] = True
            return cached_payload

    class BrokenDBConnector(BaseConnector):
        dialect_name = "sqlite"

        def connect(self) -> Any:
            raise RuntimeError("Database connection broken!")

    conn = BrokenDBConnector(middleware=[CacheInterceptor()])
    ctx: dict[str, Any] = {}
    res = conn.execute({"table": "users"}, context=ctx)
    assert res == cached_payload
    assert ctx.get("short_circuited") is True
    assert ctx.get("cache_hit") is True


def test_post_execute_data_masking():
    class EmailMasker(LifecycleInterceptor):
        def on_post_execute(
            self, result: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            for row in result.get("rows", []):
                if row.get("email"):
                    user_part = row["email"].split("@")[0]
                    row["email"] = f"{user_part[:2]}***@test.com"
            return result

    conn = InMemorySQLiteConnector(middleware=[EmailMasker()])
    res = conn.execute({"table": "users"})
    emails = [r["email"] for r in res["rows"]]
    assert "al***@test.com" in emails
    assert "bo***@test.com" in emails


def test_post_execute_invalid_return_type():
    class BadPostExecute(LifecycleInterceptor):
        def on_post_execute(
            self, result: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            return "invalid string"  # type: ignore

    conn = InMemorySQLiteConnector(middleware=[BadPostExecute()])
    with pytest.raises(TypeError, match="on_post_execute must return dict or None"):
        conn.execute({"table": "users"})


def test_on_error_hook_called_on_compilation_error():
    error_log: list[Exception] = []

    class ErrorLogger(LifecycleInterceptor):
        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            error_log.append(error)

    conn = InMemorySQLiteConnector(middleware=[ErrorLogger()])
    with pytest.raises(CompilationError):
        conn.execute({"columns": ["name"]})  # missing table

    assert len(error_log) == 1
    assert isinstance(error_log[0], CompilationError)


def test_on_error_hook_called_on_execution_error():
    error_log: list[Exception] = []

    class ErrorLogger(LifecycleInterceptor):
        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            error_log.append(error)

    conn = InMemorySQLiteConnector(middleware=[ErrorLogger()])
    with pytest.raises(QueryExecutionError):
        conn.execute({"table": "nonexistent_table"})

    assert len(error_log) == 1


def test_on_error_hook_does_not_suppress_exception():
    class CrashingInterceptor(LifecycleInterceptor):
        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            raise RuntimeError("Interceptor crashed!")

    conn = InMemorySQLiteConnector(middleware=[CrashingInterceptor()])
    # Original CompilationError must be raised, not RuntimeError
    with pytest.raises(CompilationError):
        conn.execute({"columns": ["name"]})


def test_query_cancelled_error_propagation():
    error_log: list[Exception] = []

    class CancellationInterceptor(LifecycleInterceptor):
        def on_pre_compile(
            self, spec: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            raise QueryCancelledError("Quota exceeded", context={"user_id": 99})

        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            error_log.append(error)

    conn = InMemorySQLiteConnector(middleware=[CancellationInterceptor()])
    with pytest.raises(QueryCancelledError) as exc_info:
        conn.execute({"table": "users"})

    assert exc_info.value.message == "Quota exceeded"
    assert exc_info.value.context == {"user_id": 99}
    assert len(error_log) == 1
    assert isinstance(error_log[0], QueryCancelledError)


def test_full_interceptor_lifecycle_chain_order():
    events: list[str] = []

    class InterceptorA(LifecycleInterceptor):
        def on_pre_compile(
            self, spec: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            events.append("A_pre_compile")
            return None

        def on_post_compile(
            self, compilation: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            events.append("A_post_compile")
            return None

        def on_pre_execute(
            self, execution_plan: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            events.append("A_pre_execute")
            return None

        def on_post_execute(
            self, result: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            events.append("A_post_execute")
            return None

    class InterceptorB(LifecycleInterceptor):
        def on_pre_compile(
            self, spec: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            events.append("B_pre_compile")
            return None

        def on_post_compile(
            self, compilation: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            events.append("B_post_compile")
            return None

        def on_pre_execute(
            self, execution_plan: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            events.append("B_pre_execute")
            return None

        def on_post_execute(
            self, result: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            events.append("B_post_execute")
            return None

    conn = InMemorySQLiteConnector(middleware=[InterceptorA(), InterceptorB()])
    res = conn.execute({"table": "users"})
    assert res["count"] == 2
    assert events == [
        "A_pre_compile",
        "B_pre_compile",
        "A_post_compile",
        "B_post_compile",
        "A_pre_execute",
        "B_pre_execute",
        "A_post_execute",
        "B_post_execute",
    ]


def test_compiler_direct_middleware_integration():
    events: list[str] = []

    class CompilerInterceptor(LifecycleInterceptor):
        def on_pre_compile(
            self, spec: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            events.append("compiler_pre")
            mod_spec = dict(spec)
            mod_spec["table"] = "users"
            return mod_spec

        def on_post_compile(
            self, compilation: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            events.append("compiler_post")
            compilation["main_sql"] += " -- compiler_hook"
            return compilation

    compiler = QueryCompiler(
        spec={"table": "old_users"},
        middleware=[CompilerInterceptor()],
    )
    main_sql, _, _, _ = compiler.compile()
    assert events == ["compiler_pre", "compiler_post"]
    assert "-- compiler_hook" in main_sql
    assert '"users"' in main_sql


def test_middleware_run_error_deduplication():
    calls: list[Exception] = []

    class SimpleInterceptor(LifecycleInterceptor):
        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            calls.append(error)

    pipeline = MiddlewarePipeline([SimpleInterceptor()])
    ctx: dict[str, Any] = {}
    err = ValueError("Test error")

    pipeline.run_error(err, ctx)
    assert len(calls) == 1

    # Second call with the same error object and context should be ignored
    pipeline.run_error(err, ctx)
    assert len(calls) == 1


def test_base_connector_execute_with_dataclass():
    @dataclass
    class SpecDC:
        table: str
        limit: int = 10

    conn = InMemorySQLiteConnector()
    res = conn.execute(SpecDC(table="users"))  # type: ignore
    assert res["count"] == 2
    assert len(res["rows"]) == 2
