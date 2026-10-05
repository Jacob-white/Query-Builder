"""
Unit tests for connector extensibility, pluggable dialect registry,
and BaseConnector fallback introspection.
"""

from __future__ import annotations

import importlib
import sqlite3
from typing import Any
from unittest.mock import MagicMock

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
    PostgresDialect,
    get_dialect,
    list_dialects,
    register_dialect,
    unregister_dialect,
)
from query_builder.exceptions import SecurityError


def teardown_function() -> None:
    """Ensure built-in connectors and dialects are restored after each test."""
    importlib.reload(query_builder.connectors)


class MinimalSQLiteConnector(BaseConnector):
    """Minimal custom connector implementing connect() only."""

    dialect_name = "sqlite"

    def connect(self) -> Any:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);"
        )
        return conn


def test_register_connector_class_decorator_with_args():
    @register_connector("custom_mem", aliases=["cmem", "  ", ""], dialect="sqlite")
    class CustomMemConnector(BaseConnector):
        def connect(self) -> Any:
            return sqlite3.connect(":memory:")

    assert "custom_mem" in list_connectors()
    assert "cmem" in list_connectors()
    assert CustomMemConnector.dialect_name == "sqlite"

    instance = get_connector("custom_mem")
    assert isinstance(instance, CustomMemConnector)
    instance_alias = get_connector("cmem")
    assert isinstance(instance_alias, CustomMemConnector)


def test_register_connector_bare_decorator():
    @register_connector
    class BareCustomConnector(BaseConnector):
        def connect(self) -> Any:
            return None

    assert "barecustom" in list_connectors()
    instance = get_connector("barecustom")
    assert isinstance(instance, BareCustomConnector)

    @register_connector
    class SimpleSource(BaseConnector):
        def connect(self) -> Any:
            return None

    assert "simplesource" in list_connectors()


def test_register_connector_function_call():
    class FuncConnector(BaseConnector):
        def connect(self) -> Any:
            return None

    res = register_connector(
        "func_conn", FuncConnector, aliases=["fc"], dialect="postgres"
    )
    assert res is FuncConnector
    assert "func_conn" in list_connectors()
    assert "fc" in list_connectors()
    assert FuncConnector.dialect_name == "postgres"


def test_register_connector_with_dialect_instance():
    class CustomTestDialect(BaseDialect):
        name = "custom_test_dl"

    dialect_inst = CustomTestDialect()

    @register_connector("custom_dl_conn", dialect=dialect_inst)
    class CustomDialectConn(BaseConnector):
        def connect(self) -> Any:
            return None

    assert "custom_dl_conn" in list_connectors()
    assert CustomDialectConn.dialect_name == "custom_test_dl"
    assert "custom_test_dl" in list_dialects()
    unregister_dialect("custom_test_dl")

    with pytest.raises(
        TypeError, match="Dialect must be a string or BaseDialect instance"
    ):
        register_connector("bad_dl", MinimalSQLiteConnector, dialect=123)  # type: ignore


def test_register_connector_async_connector():
    @register_connector("custom_async", dialect="postgres")
    class CustomAsyncConn(AsyncBaseConnector):
        async def connect(self) -> Any:
            return None

    assert "custom_async" in list_connectors()
    instance = get_connector("custom_async")
    assert isinstance(instance, CustomAsyncConn)


def test_register_connector_invalid_class_type():
    with pytest.raises(TypeError, match="must inherit from BaseConnector"):
        register_connector("invalid_cls", object)  # type: ignore

    with pytest.raises(TypeError, match="must inherit from BaseConnector"):
        register_connector("invalid_inst", 1234)  # type: ignore

    with pytest.raises(
        TypeError, match="Connector name must be a string or connector class"
    ):
        register_connector(12345)  # type: ignore


def test_register_connector_empty_name():
    class Dummy(BaseConnector):
        def connect(self) -> Any:
            return None

    with pytest.raises(ValueError, match="Connector name cannot be empty."):
        register_connector("", Dummy)

    with pytest.raises(ValueError, match="Connector name cannot be empty."):
        register_connector("   ", Dummy)

    with pytest.raises(TypeError, match="Connector name must be a string"):
        ConnectorRegistry.register(123, Dummy)  # type: ignore


def test_register_connector_aliases_normalization():
    class DummyAlias(BaseConnector):
        def connect(self) -> Any:
            return None

    register_connector("dummy_alias", DummyAlias, aliases=[" DUM_1 ", "dum_2"])
    assert "dum_1" in list_connectors()
    assert "dum_2" in list_connectors()


def test_connector_registry_unregister_and_clear():
    class DummyUnreg(BaseConnector):
        def connect(self) -> Any:
            return None

    register_connector("temp_conn", DummyUnreg)
    assert "temp_conn" in list_connectors()
    ConnectorRegistry.unregister("temp_conn")
    assert "temp_conn" not in list_connectors()

    ConnectorRegistry.clear()
    assert len(list_connectors()) == 0

    # Test missing connector
    with pytest.raises(ConnectorError, match="No connector registered for 'missing'"):
        get_connector("missing")


def test_register_dialect_instance_and_class():
    inst = PostgresDialect()
    res = register_dialect("my_pg_inst", inst, aliases=["mpi"])
    assert res is inst
    assert "my_pg_inst" in list_dialects()
    assert "mpi" in list_dialects()
    assert get_dialect("my_pg_inst").name == "postgres"
    assert get_dialect("mpi").name == "postgres"

    res_cls = register_dialect("my_pg_cls", PostgresDialect, aliases=["mpc"])
    assert isinstance(res_cls, PostgresDialect)
    assert "my_pg_cls" in list_dialects()
    assert "mpc" in list_dialects()

    unregister_dialect("my_pg_inst")
    unregister_dialect("mpi")
    unregister_dialect("my_pg_cls")
    unregister_dialect("mpc")


def test_register_dialect_decorator():
    @register_dialect("decorated_sql", aliases=["dsql"])
    class DecoratedDialect(BaseDialect):
        name = "decorated_sql"

    assert "decorated_sql" in list_dialects()
    assert "dsql" in list_dialects()
    assert get_dialect("decorated_sql").name == "decorated_sql"
    assert get_dialect("dsql").name == "decorated_sql"
    unregister_dialect("decorated_sql")
    unregister_dialect("dsql")

    @register_dialect("decorated_no_aliases")
    class DecoratedNoAliases(BaseDialect):
        name = "decorated_no_aliases"

    assert "decorated_no_aliases" in list_dialects()
    assert get_dialect("decorated_no_aliases").name == "decorated_no_aliases"
    unregister_dialect("decorated_no_aliases")


def test_register_dialect_bare_decorator():
    @register_dialect
    class BareCustomDialect(BaseDialect):
        name = "bare_custom"

    assert "bare_custom" in list_dialects()
    assert get_dialect("bare_custom").name == "bare_custom"
    unregister_dialect("bare_custom")

    @register_dialect
    class CustomNoNameDialect(BaseDialect):
        pass

    assert "customnonamedialect" in list_dialects()
    unregister_dialect("customnonamedialect")

    # Bare decorator with aliases
    class BareWithAliases(BaseDialect):
        name = "bare_with_aliases"

    register_dialect(BareWithAliases, aliases=["bwa", "  ", ""])
    assert "bare_with_aliases" in list_dialects()
    assert "bwa" in list_dialects()
    unregister_dialect("bare_with_aliases")
    unregister_dialect("bwa")

    # Factory with empty and whitespace aliases
    @register_dialect("fact_empty_al", aliases=["fea", "  ", ""])
    class FactEmptyAl(BaseDialect):
        pass

    assert "fact_empty_al" in list_dialects()
    assert "fea" in list_dialects()
    unregister_dialect("fact_empty_al")
    unregister_dialect("fea")

    # Functional with empty and whitespace aliases
    register_dialect("func_empty_al", PostgresDialect, aliases=["fea2", "  ", ""])
    assert "func_empty_al" in list_dialects()
    assert "fea2" in list_dialects()
    unregister_dialect("func_empty_al")
    unregister_dialect("fea2")


def test_register_dialect_invalid_args():
    with pytest.raises(
        TypeError, match="Dialect must be an instance or subclass of BaseDialect"
    ):
        register_dialect("invalid_dl", object)  # type: ignore

    with pytest.raises(
        TypeError, match="Dialect must be an instance or subclass of BaseDialect"
    ):
        register_dialect("invalid_dl", 123)  # type: ignore

    with pytest.raises(ValueError, match="Dialect name cannot be empty."):
        register_dialect("", PostgresDialect)

    with pytest.raises(ValueError, match="Dialect name cannot be empty."):
        register_dialect("   ")

    with pytest.raises(TypeError, match="Dialect name must be a string"):
        register_dialect(12345, PostgresDialect)  # type: ignore

    with pytest.raises(
        TypeError, match="Dialect name must be a string or dialect class"
    ):
        register_dialect(12345)  # type: ignore

    # Decorator factory with invalid class
    deco = register_dialect("bad_deco")
    with pytest.raises(
        TypeError, match="Dialect must be an instance or subclass of BaseDialect"
    ):
        deco(object)  # type: ignore


def test_base_connector_fallback_introspection_sqlite():
    conn = MinimalSQLiteConnector()
    snapshot = conn.introspect_schema(filter_sensitive=True)
    assert "tables" in snapshot
    assert "users" in snapshot["tables"]
    columns = snapshot["tables"]["users"]["columns"]
    col_names = [c["name"] for c in columns]
    assert "id" in col_names
    assert "name" in col_names
    assert "email" in col_names


def test_base_connector_fallback_introspection_info_schema():
    mock_cursor = MagicMock()
    # Mock information_schema tables query and columns query
    mock_cursor.fetchall.side_effect = [
        [("orders", "BASE TABLE")],
        [
            ("orders", "id", "integer", "NO", None, 1),
            ("orders", "amount", "numeric", "YES", None, 2),
        ],
        [],  # primary keys
        [],  # foreign keys
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    class InfoSchemaConnector(BaseConnector):
        dialect_name = "postgres"

        def connect(self) -> Any:
            return mock_conn

    conn = InfoSchemaConnector()
    snapshot = conn.introspect_schema()
    assert "tables" in snapshot
    assert "orders" in snapshot["tables"]
    columns = snapshot["tables"]["orders"]["columns"]
    assert len(columns) == 2


def test_base_connector_fallback_introspection_error_handling():
    class ErrorConnector(BaseConnector):
        dialect_name = "sqlite"

        def connect(self) -> Any:
            raise RuntimeError("Database unavailable")

    conn = ErrorConnector()
    snapshot = conn.introspect_schema()
    assert snapshot["tables"] == {}
    assert snapshot["foreign_keys"] == []
    assert snapshot["relationships"] == []


def test_base_connector_execute_validation():
    conn = MinimalSQLiteConnector()

    with pytest.raises(
        CompilationError,
        match="Specification must be a dictionary or dataclass instance.",
    ):
        conn.execute("invalid_spec")  # type: ignore

    with pytest.raises(ValueError, match="statement_timeout_ms must be positive."):
        conn.execute({"table": "users"}, statement_timeout_ms=-1)

    # Valid execution
    res = conn.execute({"table": "users"})
    assert res["count"] == 0
    assert res["columns"] == ["id", "name", "email"]
    assert res["rows"] == []

    # AST validation failure on main query via interceptor
    from query_builder.middleware import LifecycleInterceptor

    class MainAstCorruptor(LifecycleInterceptor):
        def on_post_compile(
            self, compilation: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            compilation["main_sql"] = "DROP TABLE users;"
            return compilation

    with pytest.raises(
        SecurityError, match="Generated query failed AST safety validation"
    ):
        conn.execute({"table": "users"}, middleware=[MainAstCorruptor()])

    # AST validation failure on count query via interceptor
    class CountAstCorruptor(LifecycleInterceptor):
        def on_post_compile(
            self, compilation: dict[str, Any], context: dict[str, Any]
        ) -> dict[str, Any] | None:
            compilation["count_sql"] = "DROP TABLE users;"
            return compilation

    with pytest.raises(
        SecurityError, match="Generated count query failed AST safety validation"
    ):
        conn.execute({"table": "users"}, middleware=[CountAstCorruptor()])
