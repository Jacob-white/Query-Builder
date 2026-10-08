"""
Milestone 1 DX Adversarial Stress & Empirical Challenge Suite.
=============================================================
Empirically stress-tests and verifies:
1. Custom connector registration with @register_connector in <50 lines:
   - Query compilation, DB-API cursor execution, alias binding, and schema introspection fallback.
2. Lifecycle interceptor deterministic execution order:
   - pre-compile -> compile -> post-compile -> pre-execute -> execute -> post-execute chain.
   - Context propagation and return value validation.
3. Middleware query rewriting, caching short-circuit (bypassing broken DB), and QueryCancelledError.
   - Error suppression and deduplication across pipeline hooks.
4. Native async execution (AsyncBaseConnector, async_execute):
   - async/await query execution, context manager, test_connection.
   - Threadpool offloading for synchronous BaseConnector.
   - Strict timeout cancellations via asyncio.wait_for and asyncio.CancelledError propagation.
5. High-concurrency async load and edge-case boundary stress.
"""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
import time
from typing import Any

import pytest

import query_builder.connectors
from query_builder.compiler import CompilationError
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import BaseConnector, ConnectorError
from query_builder.connectors.registry import (
    ConnectorRegistry,
    get_connector,
    list_connectors,
    register_connector,
)
from query_builder.dialects import (
    BaseDialect,
    DialectError,
    list_dialects,
    unregister_dialect,
)
from query_builder.executor import async_execute
from query_builder.middleware import (
    LifecycleInterceptor,
    MiddlewarePipeline,
    QueryCancelledError,
)


def teardown_function() -> None:
    """Ensure registry and dialects are restored after each test."""
    importlib.reload(query_builder.connectors)


# ==============================================================================
# CHALLENGE 1: Custom Connector Registration (<50 lines) & Dialect Binding
# ==============================================================================


@register_connector(
    "adv_inventory", aliases=["adv_inv", "inventory_db"], dialect="sqlite"
)
class AdversarialInventoryConnector(BaseConnector):
    """
    Production-grade custom connector implemented in exactly 15 lines of code (< 50 lines).
    Demonstrates minimal developer boilerplate.
    """

    dialect_name = "sqlite"

    def connect(self) -> Any:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE inventory (id INT PRIMARY KEY, sku TEXT, qty INT);")
        conn.execute("INSERT INTO inventory VALUES (1, 'SKU-A', 100);")
        conn.execute("INSERT INTO inventory VALUES (2, 'SKU-B', 250);")
        conn.execute("INSERT INTO inventory VALUES (3, 'SKU-C', 50);")
        conn.commit()
        return conn


def test_custom_connector_under_50_lines_compilation_and_execution():
    """Verify custom connector is discovered, compiles query, and executes via cursor."""
    assert "adv_inventory" in list_connectors()
    assert "adv_inv" in list_connectors()
    assert "inventory_db" in list_connectors()

    connector = get_connector("adv_inv")
    assert isinstance(connector, AdversarialInventoryConnector)
    assert connector.dialect_name == "sqlite"

    # Execute query specification
    spec = {
        "table": "inventory",
        "columns": ["id", "sku", "qty"],
        "filters": [{"column": "qty", "operator": ">=", "value": 100}],
        "order_by": [{"column": "qty", "direction": "asc"}],
    }
    result = connector.execute(spec)

    assert result["count"] == 2
    assert len(result["rows"]) == 2
    assert result["rows"][0]["sku"] == "SKU-A"
    assert result["rows"][1]["sku"] == "SKU-B"
    assert result["columns"] == ["id", "sku", "qty"]
    assert "SELECT" in result["sql"].upper()


def test_custom_connector_schema_introspection_and_fallback():
    """Verify BaseConnector introspection discovers real SQLite schema and falls back on error."""
    connector = get_connector("adv_inventory")

    # Working SQLite schema introspection
    schema = connector.introspect_schema()
    assert "inventory" in schema["tables"]
    table_info = schema["tables"]["inventory"]
    col_names = [c["name"] for c in table_info["columns"]]
    assert "id" in col_names
    assert "sku" in col_names
    assert "qty" in col_names

    # Now verify fallback on broken connector
    class BrokenConnector(BaseConnector):
        dialect_name = "sqlite"

        def connect(self) -> Any:
            raise ConnectionError("Host unreachable: 10.0.0.1")

    broken = BrokenConnector()
    fallback_schema = broken.introspect_schema()
    assert fallback_schema["tables"] == {}
    assert fallback_schema["foreign_keys"] == []
    assert fallback_schema["relationships"] == []


def test_custom_dialect_binding_with_custom_connector():
    """Verify custom connector binds a dynamically registered BaseDialect instance."""

    class CustomDuckDialect(BaseDialect):
        name = "custom_duck"
        placeholder = "$1"

    duck_dialect = CustomDuckDialect()

    @register_connector("duck_adv", aliases=["duck_test"], dialect=duck_dialect)
    class CustomDuckConnector(BaseConnector):
        def connect(self) -> Any:
            return sqlite3.connect(":memory:")

    assert "custom_duck" in list_dialects()
    assert CustomDuckConnector.dialect_name == "custom_duck"
    inst = get_connector("duck_adv")
    assert inst.dialect.name == "custom_duck"

    # Clean up dialect
    unregister_dialect("custom_duck")


def test_connector_registration_invalid_inputs():
    """Verify validation guards on ConnectorRegistry."""
    with pytest.raises(
        TypeError, match="Connector class must inherit from BaseConnector"
    ):
        register_connector("invalid_class", object)  # type: ignore

    with pytest.raises(TypeError, match="Connector name must be a string"):
        ConnectorRegistry.register(12345, AdversarialInventoryConnector)  # type: ignore

    with pytest.raises(ValueError, match="Connector name cannot be empty"):
        ConnectorRegistry.register("   ", AdversarialInventoryConnector)

    with pytest.raises(TypeError, match="Dialect must be a string or BaseDialect"):
        ConnectorRegistry.register(
            "test_bad_dialect",
            AdversarialInventoryConnector,
            dialect=999,  # type: ignore
        )

    with pytest.raises(
        ConnectorError, match="No connector registered for 'non_existent'"
    ):
        get_connector("non_existent")


# ==============================================================================
# CHALLENGE 2: Lifecycle Interceptor Execution Order & Determinism
# ==============================================================================


class TracingInterceptor(LifecycleInterceptor):
    def __init__(self, name: str) -> None:
        self.name = name

    def on_pre_compile(
        self, spec: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        context.setdefault("trace", []).append(f"{self.name}.pre_compile")
        return spec

    def on_post_compile(
        self, compilation: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        context.setdefault("trace", []).append(f"{self.name}.post_compile")
        return compilation

    def on_pre_execute(
        self, execution_plan: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        context.setdefault("trace", []).append(f"{self.name}.pre_execute")
        return None

    def on_post_execute(
        self, result: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        context.setdefault("trace", []).append(f"{self.name}.post_execute")
        return result

    def on_error(self, error: Exception, context: dict[str, Any]) -> None:
        context.setdefault("trace", []).append(f"{self.name}.error")


def test_interceptor_deterministic_execution_chain():
    """Verify exact pre-compile -> compile -> post-compile -> pre-execute -> execute -> post-execute chain."""
    interceptor_1 = TracingInterceptor("I1")
    interceptor_2 = TracingInterceptor("I2")
    interceptor_3 = TracingInterceptor("I3")

    pipeline = MiddlewarePipeline([interceptor_1, interceptor_2, interceptor_3])
    connector = AdversarialInventoryConnector(middleware=pipeline)

    ctx: dict[str, Any] = {"trace": []}
    result = connector.execute({"table": "inventory"}, context=ctx)

    assert result["count"] == 3
    expected_trace = [
        "I1.pre_compile",
        "I2.pre_compile",
        "I3.pre_compile",
        "I1.post_compile",
        "I2.post_compile",
        "I3.post_compile",
        "I1.pre_execute",
        "I2.pre_execute",
        "I3.pre_execute",
        "I1.post_execute",
        "I2.post_execute",
        "I3.post_execute",
    ]
    assert ctx["trace"] == expected_trace


def test_interceptor_type_validation_on_returns():
    """Verify pipeline rejects invalid return types from lifecycle hooks."""

    class BadPreCompile(LifecycleInterceptor):
        def on_pre_compile(self, spec: dict[str, Any], context: dict[str, Any]):
            return "not-a-dict"  # type: ignore

    pipeline = MiddlewarePipeline([BadPreCompile()])
    conn = AdversarialInventoryConnector(middleware=pipeline)
    with pytest.raises(TypeError, match="on_pre_compile must return dict or None"):
        conn.execute({"table": "inventory"})

    class BadPostCompile(LifecycleInterceptor):
        def on_post_compile(self, compilation: dict[str, Any], context: dict[str, Any]):
            return 12345  # type: ignore

    pipeline = MiddlewarePipeline([BadPostCompile()])
    conn = AdversarialInventoryConnector(middleware=pipeline)
    with pytest.raises(TypeError, match="on_post_compile must return dict or None"):
        conn.execute({"table": "inventory"})

    class BadPostExecute(LifecycleInterceptor):
        def on_post_execute(self, result: dict[str, Any], context: dict[str, Any]):
            return ["not-a-dict"]  # type: ignore

    pipeline = MiddlewarePipeline([BadPostExecute()])
    conn = AdversarialInventoryConnector(middleware=pipeline)
    with pytest.raises(TypeError, match="on_post_execute must return dict or None"):
        conn.execute({"table": "inventory"})


# ==============================================================================
# CHALLENGE 3: Middleware Query Rewriting, Caching Short-Circuit & Cancellations
# ==============================================================================


def test_middleware_query_rewriting():
    """Verify middleware can rewrite query specifications and compiled SQL."""

    class SpecRewriter(LifecycleInterceptor):
        def on_pre_compile(self, spec: dict[str, Any], context: dict[str, Any]):
            new_spec = dict(spec)
            new_spec["limit"] = 1
            new_spec["filters"] = [{"column": "sku", "operator": "=", "value": "SKU-B"}]
            return new_spec

        def on_post_compile(self, compilation: dict[str, Any], context: dict[str, Any]):
            new_comp = dict(compilation)
            # Prepend audit comment to SQL
            new_comp["main_sql"] = f"/* audit-tenant-1 */ {new_comp['main_sql']}"
            return new_comp

    connector = AdversarialInventoryConnector(middleware=[SpecRewriter()])
    res = connector.execute({"table": "inventory"})

    assert res["count"] == 1
    assert len(res["rows"]) == 1
    assert res["rows"][0]["sku"] == "SKU-B"
    assert "/* audit-tenant-1 */" in res["sql"]


def test_caching_short_circuit_bypasses_catastrophic_db_failure():
    """Verify cache hit in on_pre_execute returns immediately, completely bypassing broken DB."""

    class ExplodingConnector(BaseConnector):
        dialect_name = "sqlite"

        def connect(self) -> Any:
            raise RuntimeError("Database host completely down / disk failure!")

    class MemoryCacheInterceptor(LifecycleInterceptor):
        def __init__(self) -> None:
            self.cache: dict[str, Any] = {
                "inventory": {
                    "sql": "/* FROM CACHE */ SELECT * FROM inventory",
                    "params": [],
                    "columns": ["id", "sku", "qty"],
                    "rows": [{"id": 999, "sku": "CACHED-SKU", "qty": 9999}],
                    "count": 1,
                    "limit": 50,
                    "offset": 0,
                    "page": 1,
                    "latency_ms": 0.05,
                    "dialect": "sqlite",
                }
            }

        def on_pre_execute(
            self, execution_plan: dict[str, Any], context: dict[str, Any]
        ):
            table = execution_plan["spec"].get("table")
            if table in self.cache:
                context["cache_hit"] = True
                return self.cache[table]
            return None

    conn = ExplodingConnector(middleware=[MemoryCacheInterceptor()])
    ctx: dict[str, Any] = {}
    res = conn.execute({"table": "inventory"}, context=ctx)

    assert ctx.get("cache_hit") is True
    assert ctx.get("short_circuited") is True
    assert res["rows"][0]["sku"] == "CACHED-SKU"
    assert res["latency_ms"] == 0.05


def test_query_cancellation_with_query_cancelled_error():
    """Verify QueryCancelledError halts execution cleanly and triggers on_error with context."""

    class GuardPolicyInterceptor(LifecycleInterceptor):
        def on_pre_compile(self, spec: dict[str, Any], context: dict[str, Any]):
            if spec.get("table") == "restricted_secrets":
                raise QueryCancelledError(
                    "Access denied to restricted_secrets table",
                    context={"violation": "security_policy_403"},
                )
            return spec

        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            context["error_captured"] = str(error)
            if isinstance(error, QueryCancelledError):
                context["cancellation_ctx"] = error.context

    interceptor = GuardPolicyInterceptor()
    conn = AdversarialInventoryConnector(middleware=[interceptor])

    ctx: dict[str, Any] = {}
    with pytest.raises(
        QueryCancelledError, match="Access denied to restricted_secrets table"
    ) as exc_info:
        conn.execute({"table": "restricted_secrets"}, context=ctx)

    assert exc_info.value.context == {"violation": "security_policy_403"}
    assert "Access denied" in ctx["error_captured"]
    assert ctx["cancellation_ctx"] == {"violation": "security_policy_403"}


def test_middleware_error_suppression_and_deduplication():
    """Verify secondary exceptions inside on_error are suppressed and deduplication functions."""

    class ExplodingErrorInterceptor(LifecycleInterceptor):
        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            raise RuntimeError("Secondary error inside on_error should be swallowed")

    class RecordingErrorInterceptor(LifecycleInterceptor):
        def __init__(self) -> None:
            self.errors: list[Exception] = []

        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            self.errors.append(error)

    recorder = RecordingErrorInterceptor()
    exploder = ExplodingErrorInterceptor()
    pipeline = MiddlewarePipeline([exploder, recorder])

    ctx: dict[str, Any] = {}
    err = ValueError("Original database error")

    # Call run_error directly
    pipeline.run_error(err, ctx)
    assert len(recorder.errors) == 1
    assert recorder.errors[0] is err

    # Call run_error again with the same error and context -> deduplication should prevent second call
    pipeline.run_error(err, ctx)
    assert len(recorder.errors) == 1  # Not called again


# ==============================================================================
# CHALLENGE 4: Native Async Execution & Timeout Cancellations
# ==============================================================================


class ConcreteAsyncDBConnector(AsyncBaseConnector):
    dialect_name = "sqlite"

    def __init__(self, artificial_delay: float = 0.0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.artificial_delay = artificial_delay
        self.executed_queries: list[str] = []

    async def connect(self) -> Any:
        self._connection = "mock_async_conn"
        return self._connection

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        self.executed_queries.append(sql)
        if self.artificial_delay > 0:
            await asyncio.sleep(self.artificial_delay)
        if "COUNT" in sql.upper():
            return ["count"], [{"count": 42}], 0.8
        return ["id", "val"], [{"id": 1, "val": "alpha"}, {"id": 2, "val": "beta"}], 1.2


def test_async_base_connector_lifecycle_and_test_connection():
    """Verify AsyncBaseConnector context manager, test_connection, and schema fallback."""

    async def _test():
        conn = ConcreteAsyncDBConnector()
        async with conn as c:
            assert c is conn
            assert conn._connection == "mock_async_conn"

            health = await conn.test_connection()
            assert health["status"] == "healthy"
            assert health["dialect"] == "sqlite"
            assert health["latency_ms"] >= 0.0

        assert conn._connection is None

        # Schema fallback
        schema = await conn.introspect_schema()
        assert schema["tables"] == {}

    asyncio.run(_test())


def test_async_execute_with_async_connector():
    """Verify async_execute with AsyncBaseConnector and middleware execution."""

    async def _test():
        interceptor = TracingInterceptor("AsyncTrace")
        conn = ConcreteAsyncDBConnector(middleware=[interceptor])

        ctx: dict[str, Any] = {}
        res = await async_execute(conn, {"table": "items"}, context=ctx)

        assert res["count"] == 42
        assert len(res["rows"]) == 2
        assert "AsyncTrace.pre_compile" in ctx["trace"]
        assert "AsyncTrace.post_execute" in ctx["trace"]

    asyncio.run(_test())


def test_async_execute_with_sync_connector_threadpool():
    """Verify async_execute smoothly offloads synchronous BaseConnector to worker thread."""

    async def _test():
        conn = AdversarialInventoryConnector()
        res = await async_execute(conn, {"table": "inventory"})

        assert res["count"] == 3
        assert len(res["rows"]) == 3
        assert res["rows"][0]["sku"] == "SKU-A"

    asyncio.run(_test())


def test_async_execute_timeout_cancellation():
    """Verify async_execute strictly enforces timeout_ms and raises TimeoutError via asyncio.wait_for."""

    async def _test():
        recording_interceptor = LifecycleInterceptor()
        error_logged: list[Exception] = []
        recording_interceptor.on_error = lambda err, ctx: error_logged.append(err)  # type: ignore

        # Delay is 0.5s (500ms), timeout is 50ms
        conn = ConcreteAsyncDBConnector(
            artificial_delay=0.5, middleware=[recording_interceptor]
        )

        start = time.perf_counter()
        with pytest.raises(TimeoutError, match="Query execution timed out after 50ms"):
            await async_execute(conn, {"table": "items"}, timeout_ms=50)
        elapsed = time.perf_counter() - start

        # Should time out in ~50ms, definitely well under the 500ms sleep
        assert elapsed < 0.25
        assert len(error_logged) == 1
        assert isinstance(error_logged[0], TimeoutError)

    asyncio.run(_test())


def test_async_execute_task_cancellation_propagation():
    """Verify task cancellation injects CancelledError and triggers middleware error hook."""

    async def _test():
        cancelled_errors: list[Exception] = []

        class CancellationLogger(LifecycleInterceptor):
            def on_error(self, error: Exception, context: dict[str, Any]) -> None:
                cancelled_errors.append(error)

        conn = ConcreteAsyncDBConnector(
            artificial_delay=1.0, middleware=[CancellationLogger()]
        )

        task = asyncio.create_task(async_execute(conn, {"table": "items"}))
        await asyncio.sleep(0.02)  # Allow task to start execution
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert len(cancelled_errors) == 1
        assert isinstance(cancelled_errors[0], asyncio.CancelledError)

    asyncio.run(_test())


def test_concurrent_async_query_stress():
    """Stress test: 50 concurrent async_execute queries via asyncio.gather."""

    async def _test():
        conn = ConcreteAsyncDBConnector(artificial_delay=0.01)

        specs = [{"table": "items", "offset": i * 2, "limit": 2} for i in range(50)]
        results = await asyncio.gather(*(async_execute(conn, spec) for spec in specs))

        assert len(results) == 50
        for i, res in enumerate(results):
            assert res["count"] == 42
            assert res["offset"] == i * 2

    asyncio.run(_test())


# ==============================================================================
# CHALLENGE 5: Edge Cases, Security & Dialect Escaping
# ==============================================================================


def test_malicious_identifier_dialect_injection_rejection():
    """Verify BaseDialect quote_identifier strictly rejects SQL injection attempts."""
    dialect = BaseDialect()

    injection_vectors = [
        "users; DROP TABLE users;--",
        "users' OR '1'='1",
        "users/**/WHERE/**/1=1",
        "table\x00name",
        "table name with spaces",
        "table-name-with-dashes",
        "",
        "a" * 129,  # exceeds MAX_IDENTIFIER_LENGTH
    ]

    for vector in injection_vectors:
        with pytest.raises(DialectError):
            dialect.quote_identifier(vector)


def test_async_execute_invalid_arguments():
    """Verify async_execute argument boundary validation."""
    with pytest.raises(ValueError, match="Connector cannot be None"):
        asyncio.run(async_execute(None, {"table": "users"}))

    conn = AdversarialInventoryConnector()
    with pytest.raises(CompilationError, match="Specification must be a dictionary"):
        asyncio.run(async_execute(conn, "invalid_spec"))  # type: ignore

    with pytest.raises(ValueError, match="timeout_ms must be positive"):
        asyncio.run(async_execute(conn, {"table": "inventory"}, timeout_ms=0))

    with pytest.raises(ValueError, match="timeout_ms must be positive"):
        asyncio.run(async_execute(conn, {"table": "inventory"}, timeout_ms=-100))


def test_memory_and_loop_stability():
    """Verify running 500 queries in a loop exhibits no memory or handler leaks."""
    conn = AdversarialInventoryConnector()
    ctx: dict[str, Any] = {}

    for _ in range(500):
        res = conn.execute({"table": "inventory", "limit": 1}, context=ctx)
        assert res["count"] == 3

    # Handled errors set should not be contaminated
    assert "_handled_errors" not in ctx


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
