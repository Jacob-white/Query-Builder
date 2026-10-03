"""
Milestone 1 DX Challenger 2 Adversarial Stress & Empirical Verification Suite.
==============================================================================
Empirically tests deep boundary conditions and hostile edge cases for Milestone 1:
1. Complex Interceptor Chains:
   - Deep multi-stage context mutations across pre_compile, post_compile, pre_execute, post_execute, and on_error.
   - Multiple short-circuiting interceptors (first short-circuit wins; subsequent pre_execute skipped; post_execute chain preserves/modifies result).
   - Nested and cascading exception handlers (exceptions in pre_compile, post_compile, pre_execute, post_execute, on_error; error deduplication; context persistence).
   - Pipeline normalization edge cases (nested lists, invalid types, None).
2. Dynamic Dialect Registration & Custom Syntax Transformations:
   - Dynamic dialect registration with aliases and custom transformations (custom quoting, placeholders, custom pagination, custom ilike).
   - Case insensitivity and whitespace trimming for dialect names and aliases.
   - Unregistering and overriding dialects.
   - Dialect validation bounds (invalid types, empty strings, control characters, identifier boundaries).
3. Custom Connector Edge Cases (<50 lines) with Broken/Missing Schemas:
   - Minimal connectors (<50 lines) connecting to dynamic SQLite instances.
   - Missing tables, missing columns, and corrupted schema catalog introspection.
   - Default introspection fallback returning normalized empty schema snapshot.
   - Executing against schemas with non-existent tables and ensuring AST validation / error handling.
   - Connector registration error paths (non-BaseConnector, empty names, invalid dialect types).
4. Native Async Execution under Concurrent Cancellation Conditions:
   - High concurrency (30+ tasks) where a subset are cancelled via task.cancel() while others complete.
   - Verification that cancelled tasks trigger on_error with CancelledError and clean up properly.
   - Simultaneous timeouts (asyncio.wait_for) and external task cancellations.
   - Threadpool cancellation behavior for synchronous connectors.
   - Rapid-fire start-and-cancel loops verifying no leaked coroutines or corrupted state.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any

import pytest

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
    DIALECTS,
    BaseDialect,
    DialectError,
    get_dialect,
    list_dialects,
    register_dialect,
    unregister_dialect,
)
from query_builder.executor import async_execute
from query_builder.middleware import (
    LifecycleInterceptor,
    MiddlewarePipeline,
    QueryCancelledError,
)


@pytest.fixture(autouse=True)
def clean_registry_and_dialects():
    """Ensure custom connectors and dialects are cleaned up after each test."""
    initial_dialects = set(DIALECTS.keys())
    initial_connectors = set(ConnectorRegistry.list_available())
    yield
    # Cleanup any new dialects
    current_dialects = set(DIALECTS.keys())
    for d in current_dialects - initial_dialects:
        unregister_dialect(d)
    # Cleanup any new connectors
    current_connectors = set(ConnectorRegistry.list_available())
    for c in current_connectors - initial_connectors:
        ConnectorRegistry.unregister(c)


# ==============================================================================
# SECTION 1: Complex Interceptor Chains, Context Mutations, & Exception Handling
# ==============================================================================


class ContextMutatingInterceptor(LifecycleInterceptor):
    def __init__(self, tag: str, mutate_value: int) -> None:
        self.tag = tag
        self.mutate_value = mutate_value

    def on_pre_compile(
        self, spec: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        context.setdefault("mutations", []).append(
            f"{self.tag}:pre_compile:{self.mutate_value}"
        )
        context[f"{self.tag}_pre_compile"] = self.mutate_value
        return spec

    def on_post_compile(
        self, compilation: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        context.setdefault("mutations", []).append(
            f"{self.tag}:post_compile:{self.mutate_value}"
        )
        context[f"{self.tag}_post_compile"] = self.mutate_value
        return compilation

    def on_pre_execute(
        self, execution_plan: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        context.setdefault("mutations", []).append(
            f"{self.tag}:pre_execute:{self.mutate_value}"
        )
        context[f"{self.tag}_pre_execute"] = self.mutate_value
        return None

    def on_post_execute(
        self, result: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        context.setdefault("mutations", []).append(
            f"{self.tag}:post_execute:{self.mutate_value}"
        )
        context[f"{self.tag}_post_execute"] = self.mutate_value
        # Also mutate result payload by appending tag
        result.setdefault("tags", []).append(self.tag)
        return result

    def on_error(self, error: Exception, context: dict[str, Any]) -> None:
        context.setdefault("mutations", []).append(
            f"{self.tag}:on_error:{type(error).__name__}"
        )


@register_connector("sqlite_inmemory_m1_test", dialect="sqlite")
class InMemorySQLiteConnector(BaseConnector):
    dialect_name = "sqlite"

    def connect(self) -> Any:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE test_data (id INT PRIMARY KEY, name TEXT, score INT);"
        )
        conn.execute(
            "INSERT INTO test_data VALUES (1, 'Alice', 95), (2, 'Bob', 80), (3, 'Charlie', 70);"
        )
        conn.commit()
        return conn


def test_complex_interceptor_chain_context_mutations():
    """Verify context flows across a 4-interceptor chain through all lifecycle stages."""
    i1 = ContextMutatingInterceptor("A", 10)
    i2 = ContextMutatingInterceptor("B", 20)
    i3 = ContextMutatingInterceptor("C", 30)
    i4 = ContextMutatingInterceptor("D", 40)

    pipeline = MiddlewarePipeline([i1, i2, i3, i4])
    conn = get_connector("sqlite_inmemory_m1_test", middleware=pipeline)

    ctx: dict[str, Any] = {"session_id": "sess-999"}
    res = conn.execute({"table": "test_data"}, context=ctx)

    assert res["count"] == 3
    assert res["tags"] == ["A", "B", "C", "D"]
    assert ctx["session_id"] == "sess-999"
    assert ctx["A_pre_compile"] == 10
    assert ctx["B_post_compile"] == 20
    assert ctx["C_pre_execute"] == 30
    assert ctx["D_post_execute"] == 40

    # Ensure sequential mutation order is preserved
    expected_order = [
        "A:pre_compile:10",
        "B:pre_compile:20",
        "C:pre_compile:30",
        "D:pre_compile:40",
        "A:post_compile:10",
        "B:post_compile:20",
        "C:post_compile:30",
        "D:post_compile:40",
        "A:pre_execute:10",
        "B:pre_execute:20",
        "C:pre_execute:30",
        "D:pre_execute:40",
        "A:post_execute:10",
        "B:post_execute:20",
        "C:post_execute:30",
        "D:post_execute:40",
    ]
    assert ctx["mutations"] == expected_order


def test_multiple_short_circuit_interceptors_first_wins_and_post_execute_runs():
    """
    When multiple interceptors attempt to short-circuit in on_pre_execute:
    1. The first interceptor to return a non-None dict wins.
    2. Subsequent interceptors are NOT called in on_pre_execute.
    3. All interceptors STILL run their on_post_execute hooks on the short-circuited result.
    4. Database execution is completely bypassed.
    """
    called_pre_execute: list[str] = []
    called_post_execute: list[str] = []

    class FirstShortCircuit(LifecycleInterceptor):
        def on_pre_execute(
            self, plan: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            called_pre_execute.append("First")
            return {
                "sql": "-- FROM FIRST SHORT CIRCUIT",
                "params": [],
                "columns": ["cached_col"],
                "rows": [{"cached_col": "WINNER_1"}],
                "count": 1,
                "limit": 50,
                "offset": 0,
                "page": 1,
                "latency_ms": 0.1,
                "dialect": "sqlite",
            }

        def on_post_execute(
            self, result: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            called_post_execute.append("First")
            result["post_first"] = True
            return result

    class SecondShortCircuit(LifecycleInterceptor):
        def on_pre_execute(
            self, plan: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            called_pre_execute.append("Second")
            return {"rows": [{"cached_col": "SHOULD_NOT_WIN"}]}

        def on_post_execute(
            self, result: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            called_post_execute.append("Second")
            result["post_second"] = True
            return result

    pipeline = MiddlewarePipeline([FirstShortCircuit(), SecondShortCircuit()])

    # Use a dummy connector that would throw an exception if connect() were called
    class DummyExplodingConnector(BaseConnector):
        dialect_name = "sqlite"

        def connect(self) -> Any:
            raise AssertionError(
                "Database connect() must NOT be called when short-circuited!"
            )

    conn = DummyExplodingConnector(middleware=pipeline)
    ctx: dict[str, Any] = {}
    result = conn.execute({"table": "test_data"}, context=ctx)

    assert called_pre_execute == ["First"]  # Second is skipped in pre_execute!
    assert called_post_execute == ["First", "Second"]  # Both run in post_execute
    assert result["rows"] == [{"cached_col": "WINNER_1"}]
    assert result["post_first"] is True
    assert result["post_second"] is True
    assert ctx["short_circuited"] is True


def test_nested_exceptions_in_lifecycle_hooks():
    """Verify exceptions in any lifecycle stage trigger on_error and pipeline.run_error cleanly."""

    class StageExploder(LifecycleInterceptor):
        def __init__(self, explode_stage: str) -> None:
            self.explode_stage = explode_stage

        def on_pre_compile(
            self, spec: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            if self.explode_stage == "pre_compile":
                raise ValueError("Explosion in on_pre_compile")
            return spec

        def on_post_compile(
            self, compilation: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            if self.explode_stage == "post_compile":
                raise KeyError("Explosion in on_post_compile")
            return compilation

        def on_pre_execute(
            self, plan: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            if self.explode_stage == "pre_execute":
                raise RuntimeError("Explosion in on_pre_execute")
            return None

        def on_post_execute(
            self, result: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            if self.explode_stage == "post_execute":
                raise IndexError("Explosion in on_post_execute")
            return result

    class ErrorCatcher(LifecycleInterceptor):
        def __init__(self) -> None:
            self.caught_errors: list[Exception] = []

        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            self.caught_errors.append(error)
            context["last_error_type"] = type(error).__name__

    stages_and_errors = [
        ("pre_compile", ValueError, "Explosion in on_pre_compile"),
        ("post_compile", KeyError, "Explosion in on_post_compile"),
        ("pre_execute", RuntimeError, "Explosion in on_pre_execute"),
        ("post_execute", IndexError, "Explosion in on_post_execute"),
    ]

    for stage, err_cls, err_msg in stages_and_errors:
        catcher = ErrorCatcher()
        exploder = StageExploder(stage)
        pipeline = MiddlewarePipeline([exploder, catcher])
        conn = InMemorySQLiteConnector(middleware=pipeline)
        ctx: dict[str, Any] = {}

        with pytest.raises(err_cls):
            conn.execute({"table": "test_data"}, context=ctx)

        assert len(catcher.caught_errors) == 1
        assert isinstance(catcher.caught_errors[0], err_cls)
        assert ctx["last_error_type"] == err_cls.__name__


def test_error_handler_nesting_and_exception_in_on_error():
    """Verify that if one interceptor throws an error in on_error, subsequent interceptors still execute."""
    order: list[str] = []

    class ExplodingErrorHandler(LifecycleInterceptor):
        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            order.append("ExplodingErrorHandler")
            raise ArithmeticError("Secondary crash inside on_error")

    class HealthyErrorHandler(LifecycleInterceptor):
        def on_error(self, error: Exception, context: dict[str, Any]) -> None:
            order.append("HealthyErrorHandler")
            context["healthy_caught"] = str(error)

    pipeline = MiddlewarePipeline([ExplodingErrorHandler(), HealthyErrorHandler()])
    ctx: dict[str, Any] = {}
    original_err = ValueError("Primary database failure")

    # Directly execute run_error
    pipeline.run_error(original_err, ctx)

    assert order == ["ExplodingErrorHandler", "HealthyErrorHandler"]
    assert ctx["healthy_caught"] == "Primary database failure"


def test_interceptor_query_cancellation_with_payload():
    """Verify QueryCancelledError carries structured context through pipeline error hooks."""

    class GuardInterceptor(LifecycleInterceptor):
        def on_pre_compile(
            self, spec: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            raise QueryCancelledError(
                "Rate limit exceeded for client", context={"retry_after": 30}
            )

    conn = InMemorySQLiteConnector(middleware=[GuardInterceptor()])
    ctx: dict[str, Any] = {}
    with pytest.raises(QueryCancelledError) as exc_info:
        conn.execute({"table": "test_data"}, context=ctx)

    assert exc_info.value.message == "Rate limit exceeded for client"
    assert exc_info.value.context == {"retry_after": 30}


def test_pipeline_ensure_normalization_and_validation():
    """Test MiddlewarePipeline.ensure with valid and invalid inputs."""
    assert isinstance(MiddlewarePipeline.ensure(None), MiddlewarePipeline)

    interceptor = LifecycleInterceptor()
    p1 = MiddlewarePipeline.ensure(interceptor)
    assert len(p1.interceptors) == 1
    assert p1.interceptors[0] is interceptor

    p2 = MiddlewarePipeline.ensure(p1)
    assert p2 is p1

    p3 = MiddlewarePipeline.ensure([interceptor, interceptor])
    assert len(p3.interceptors) == 2

    p4 = MiddlewarePipeline.ensure((interceptor,))
    assert len(p4.interceptors) == 1

    with pytest.raises(TypeError, match="Cannot convert int to MiddlewarePipeline"):
        MiddlewarePipeline.ensure(42)

    p_empty = MiddlewarePipeline()
    with pytest.raises(TypeError, match="Expected LifecycleInterceptor"):
        p_empty.add("not_an_interceptor")  # type: ignore


# ==============================================================================
# SECTION 2: Dynamic Dialect Registration & Custom Syntax Transformations
# ==============================================================================


class CustomSyntaxDialect(BaseDialect):
    """Custom dialect with custom identifier quoting, placeholders, and pagination."""

    name: str = "custom_syntax_dx"
    placeholder: str = ":param"

    def quote_identifier(self, ident: str) -> str:
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

    def format_ilike(self, col_ref: str) -> str:
        return f"REGEXP_LIKE({col_ref}, {self.placeholder}, 'i')"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"TAKE {self.placeholder} SKIP {self.placeholder}", [limit, offset]


def test_dynamic_dialect_functional_registration_with_aliases_and_syntax():
    """Verify register_dialect functionally with aliases and custom transformations."""
    dialect_instance = CustomSyntaxDialect()
    registered = register_dialect(
        "custom_syntax_dx", dialect_instance, aliases=["cs_alias_1", "cs_alias_2"]
    )

    assert registered is dialect_instance
    assert "custom_syntax_dx" in list_dialects()
    assert "cs_alias_1" in list_dialects()
    assert "cs_alias_2" in list_dialects()

    # Retrieve by primary name and aliases (case insensitive, whitespace trimmed)
    d_primary = get_dialect("custom_syntax_dx")
    d_alias1 = get_dialect("  CS_ALIAS_1  ")
    d_alias2 = get_dialect("cs_alias_2")

    assert d_primary is dialect_instance
    assert d_alias1 is dialect_instance
    assert d_alias2 is dialect_instance

    # Test custom transformations
    assert d_primary.quote_identifier("my_table.col1") == "`my_table`.`col1`"
    assert d_primary.quote_alias("my_alias") == "`my_alias`"
    assert d_primary.format_ilike("`name`") == "REGEXP_LIKE(`name`, :param, 'i')"
    clause, params = d_primary.format_limit_offset(10, 20)
    assert clause == "TAKE :param SKIP :param"
    assert params == [10, 20]


def test_dynamic_dialect_decorator_forms():
    """Verify register_dialect as both bare decorator and decorator with name/aliases."""

    @register_dialect
    class BareDecoratedDialect(BaseDialect):
        name = "bare_decorated_dx"

    assert "bare_decorated_dx" in list_dialects()
    assert isinstance(get_dialect("bare_decorated_dx"), BareDecoratedDialect)

    @register_dialect("named_decorated_dx", aliases=["nd_alias"])
    class NamedDecoratedDialect(BaseDialect):
        name = "ignored_default"

    assert "named_decorated_dx" in list_dialects()
    assert "nd_alias" in list_dialects()
    assert isinstance(get_dialect("nd_alias"), NamedDecoratedDialect)


def test_dynamic_dialect_registration_errors_and_boundaries():
    """Verify validation boundaries on register_dialect."""
    with pytest.raises(
        TypeError, match="Dialect name must be a string or dialect class"
    ):
        register_dialect(123)  # type: ignore

    with pytest.raises(ValueError, match="Dialect name cannot be empty"):
        register_dialect("   ")

    with pytest.raises(
        TypeError, match="Dialect must be an instance or subclass of BaseDialect"
    ):
        register_dialect("bad_cls", object)  # type: ignore

    with pytest.raises(
        TypeError, match="Dialect must be an instance or subclass of BaseDialect"
    ):
        register_dialect("bad_obj", 999)  # type: ignore

    # Decorator with invalid class
    dec = register_dialect("bad_dec")
    with pytest.raises(
        TypeError, match="Dialect must be an instance or subclass of BaseDialect"
    ):
        dec(dict)  # type: ignore


def test_dialect_identifier_and_alias_boundaries():
    """Test boundary checks on identifier and alias lengths and control characters."""
    d = BaseDialect()

    # Valid identifier boundaries
    assert d.quote_identifier("a" * 128) == f'"{"a" * 128}"'
    with pytest.raises(DialectError, match="exceeds maximum allowed length"):
        d.quote_identifier("a" * 129)

    # Multi-part identifier
    with pytest.raises(DialectError, match="exceeds maximum allowed length"):
        d.quote_identifier(f"schema.{'b' * 129}.col")

    # Alias boundaries
    assert d.quote_alias("x" * 256) == f'"{"x" * 256}"'
    with pytest.raises(DialectError, match="exceeds maximum limit"):
        d.quote_alias("x" * 257)

    # Control characters in alias
    with pytest.raises(DialectError, match="forbidden control characters"):
        d.quote_alias("bad\x01alias")

    with pytest.raises(DialectError, match="forbidden control characters"):
        d.quote_alias("bad\x00alias")


# ==============================================================================
# SECTION 3: Custom Connector Edge Cases (<50 Lines) & Missing/Broken Schemas
# ==============================================================================


@register_connector("minimal_sqlite_connector", dialect="sqlite")
class MinimalSQLiteConnector(BaseConnector):
    """Minimal SQLite connector written in 8 lines of code (<50 lines)."""

    dialect_name = "sqlite"

    def connect(self) -> Any:
        return sqlite3.connect(":memory:")


def test_minimal_connector_with_missing_and_empty_tables():
    """Verify minimal connector behavior when querying missing tables or tables with broken schemas."""
    conn = get_connector("minimal_sqlite_connector")

    # Introspecting an empty database returns empty table map without error
    schema = conn.introspect_schema()
    assert schema["tables"] == {}
    assert schema["foreign_keys"] == []
    assert schema["relationships"] == []

    # Executing against non-existent table fails at DB execution level cleanly
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        conn.execute({"table": "non_existent_table"})

    # Attempting to retrieve an unknown connector raises ConnectorError
    with pytest.raises(
        ConnectorError, match="No connector registered for 'non_existent_sdk_connector'"
    ):
        get_connector("non_existent_sdk_connector")


def test_connector_introspection_corrupted_catalog_fallback():
    """
    Verify introspect_schema falls back to normalized empty snapshot
    when the database catalog is corrupted or throws an unhandled exception.
    """

    class CorruptedCatalogConnector(BaseConnector):
        dialect_name = "sqlite"

        def connect(self) -> Any:
            # Create a mock cursor that explodes during execute
            class CorruptedCursor:
                def execute(self, *args, **kwargs):
                    raise sqlite3.DatabaseError("database disk image is malformed")

                def close(self):
                    pass

            class BrokenConnection:
                backup = True  # trick dialect check

                def cursor(self):
                    return CorruptedCursor()

                def close(self):
                    pass

            return BrokenConnection()

    corrupted = CorruptedCatalogConnector()
    snapshot = corrupted.introspect_schema()

    # Must NOT raise exception; returns normalized fallback snapshot
    assert snapshot["tables"] == {}
    assert snapshot["foreign_keys"] == []
    assert snapshot["relationships"] == []


def test_connector_registration_bare_decorator_and_retrieval():
    """Verify bare decorator registration inferring connector name."""

    @register_connector
    class BareWidgetConnector(BaseConnector):
        dialect_name = "sqlite"

        def connect(self) -> Any:
            return sqlite3.connect(":memory:")

    assert "barewidget" in list_connectors()
    inst = get_connector("barewidget")
    assert isinstance(inst, BareWidgetConnector)
    assert inst.dialect_name == "sqlite"


def test_connector_execute_with_dataclass_or_invalid_spec():
    """Verify BaseConnector.execute spec parameter validations."""
    conn = get_connector("minimal_sqlite_connector")

    with pytest.raises(
        CompilationError,
        match="Specification must be a dictionary or dataclass instance",
    ):
        conn.execute(12345)  # type: ignore

    with pytest.raises(ValueError, match="statement_timeout_ms must be positive"):
        conn.execute({"table": "foo"}, statement_timeout_ms=-10)

    with pytest.raises(ValueError, match="statement_timeout_ms must be positive"):
        conn.execute({"table": "foo"}, statement_timeout_ms=0)


# ==============================================================================
# SECTION 4: Native Async Execution Under Concurrent Cancellation Conditions
# ==============================================================================


class HeavyAsyncConnector(AsyncBaseConnector):
    dialect_name = "sqlite"

    def __init__(self, delay_per_query: float = 0.05, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.delay_per_query = delay_per_query
        self.active_queries: int = 0
        self.completed_queries: int = 0
        self.cancelled_queries: int = 0

    async def connect(self) -> Any:
        return "async_session_mock"

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        self.active_queries += 1
        try:
            if self.delay_per_query > 0:
                await asyncio.sleep(self.delay_per_query)
            self.completed_queries += 1
            if "COUNT" in sql.upper():
                return ["count"], [{"count": 100}], 1.0
            return ["id", "val"], [{"id": 1, "val": "data"}], 2.0
        except asyncio.CancelledError:
            self.cancelled_queries += 1
            raise
        finally:
            self.active_queries -= 1


def test_concurrent_async_tasks_with_targeted_cancellations():
    """
    Stress-test high concurrency (40 tasks) where half the tasks are cancelled mid-flight,
    while the other half run to completion.
    Verify:
    1. Cancelled tasks raise CancelledError cleanly.
    2. Non-cancelled tasks complete with valid results.
    3. Middleware on_error captures CancelledError for each cancelled task.
    4. Active query count returns to 0 (no resource leak).
    """

    async def _test():
        cancelled_errors_captured: list[Exception] = []

        class CancellationTracker(LifecycleInterceptor):
            def on_error(self, error: Exception, context: dict[str, Any]) -> None:
                if isinstance(error, asyncio.CancelledError):
                    cancelled_errors_captured.append(error)

        conn = HeavyAsyncConnector(
            delay_per_query=0.08, middleware=[CancellationTracker()]
        )

        num_tasks = 40
        tasks: list[asyncio.Task] = []

        for i in range(num_tasks):
            spec = {"table": "test_data", "offset": i, "limit": 1}
            t = asyncio.create_task(async_execute(conn, spec))
            tasks.append(t)

        # Allow tasks to begin execution
        await asyncio.sleep(0.02)

        # Cancel even-indexed tasks (20 tasks cancelled)
        cancelled_indices = set()
        for idx in range(0, num_tasks, 2):
            tasks[idx].cancel()
            cancelled_indices.add(idx)

        # Gather with return_exceptions=True
        results = await asyncio.gather(*tasks, return_exceptions=True)

        completed_count = 0
        cancelled_count = 0

        for idx, res in enumerate(results):
            if idx in cancelled_indices:
                assert isinstance(res, asyncio.CancelledError)
                cancelled_count += 1
            else:
                assert isinstance(res, dict)
                assert res["count"] == 100
                completed_count += 1

        assert cancelled_count == 20
        assert completed_count == 20
        assert len(cancelled_errors_captured) == 20
        assert conn.active_queries == 0
        assert conn.completed_queries >= 20

    asyncio.run(_test())


def test_simultaneous_timeout_and_explicit_cancellation():
    """
    Verify races between timeout_ms (asyncio.wait_for) and explicit task cancellation.
    Tasks timing out should raise TimeoutError, while externally cancelled tasks raise CancelledError.
    """

    async def _test():
        conn = HeavyAsyncConnector(delay_per_query=0.2)

        # Task 1: Has 50ms timeout (will time out on its own)
        t_timeout = asyncio.create_task(
            async_execute(conn, {"table": "test_data"}, timeout_ms=50)
        )

        # Task 2: Has 500ms timeout, but will be cancelled after 30ms
        t_cancelled = asyncio.create_task(
            async_execute(conn, {"table": "test_data"}, timeout_ms=500)
        )

        # Task 3: Normal query with 500ms timeout that finishes after 200ms
        t_normal = asyncio.create_task(
            async_execute(conn, {"table": "test_data"}, timeout_ms=500)
        )

        await asyncio.sleep(0.03)
        t_cancelled.cancel()

        results = await asyncio.gather(
            t_timeout, t_cancelled, t_normal, return_exceptions=True
        )

        assert isinstance(results[0], TimeoutError)
        assert isinstance(results[1], asyncio.CancelledError)
        assert isinstance(results[2], dict)
        assert results[2]["count"] == 100

    asyncio.run(_test())


def test_rapid_fire_start_and_cancel_loop():
    """
    Stress-test rapid firing and immediate cancellation of 60 async queries
    to verify no event loop corruption or unhandled task exceptions.
    """

    async def _test():
        conn = HeavyAsyncConnector(delay_per_query=0.1)

        for i in range(60):
            task = asyncio.create_task(
                async_execute(conn, {"table": "test_data", "offset": i})
            )
            # Cancel immediately or with micro-delay
            if i % 2 == 0:
                task.cancel()
            else:
                await asyncio.sleep(0.001)
                task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

        assert conn.active_queries == 0

    asyncio.run(_test())


def test_async_execute_synchronous_connector_threadpool_cancellation():
    """
    Verify that cancelling an async_execute on a synchronous BaseConnector
    propagates CancelledError cleanly and triggers middleware on_error.
    """

    async def _test():
        class SlowSyncConnector(BaseConnector):
            dialect_name = "sqlite"

            def connect(self) -> Any:
                return sqlite3.connect(":memory:")

            def execute(self, *args, **kwargs) -> Any:
                time.sleep(0.2)  # Simulate slow DB call in worker thread
                return {"count": 1, "rows": []}

        logged_errors: list[Exception] = []

        class ErrorWatcher(LifecycleInterceptor):
            def on_error(self, error: Exception, context: dict[str, Any]) -> None:
                logged_errors.append(error)

        conn = SlowSyncConnector(middleware=[ErrorWatcher()])

        task = asyncio.create_task(async_execute(conn, {"table": "items"}))
        await asyncio.sleep(0.02)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert len(logged_errors) == 1
        assert isinstance(logged_errors[0], asyncio.CancelledError)

    asyncio.run(_test())
