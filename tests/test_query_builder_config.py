"""
Unit and integration tests for QueryBuilderConfig, configuration ergonomics,
custom connector registration, and custom filter operator extensions.
=============================================================================
"""

from __future__ import annotations

import concurrent.futures
from typing import Any

import pytest

from query_builder import (
    QueryBuilderConfig,
    QueryCompiler,
    configure_query_builder,
    get_connector,
    get_query_builder_config,
    list_connectors,
    list_filter_operators,
    register_connector,
    register_filter_operator,
    reset_query_builder_config,
    unregister_connector,
    unregister_filter_operator,
)
from query_builder.config import SecurityConfig, SecurityProfile
from query_builder.connectors.base import BaseConnector, ConnectorError
from query_builder.dialects import (
    BaseDialect,
    get_dialect,
    unregister_dialect,
)
from query_builder.exceptions import CompilationError, ValidationError


@pytest.fixture(autouse=True)
def clean_config_state():
    """Reset configuration and registries before and after each test."""
    reset_query_builder_config()
    yield
    reset_query_builder_config()
    # Clean up custom dialects/connectors/operators if left behind
    for d in ["custom_test_dialect", "custom_cfg_dialect", "another_dialect"]:
        unregister_dialect(d)
    for c in ["mock_test_connector", "custom_cfg_connector"]:
        unregister_connector(c)
    for op in ["regex_match", "geo_within", "custom_unary", "invalid_ret_op"]:
        unregister_filter_operator(op)


# ---------------------------------------------------------------------------
# 1. QueryBuilderConfig Dataclass Tests
# ---------------------------------------------------------------------------


def test_query_builder_config_defaults():
    cfg = QueryBuilderConfig()
    assert cfg.default_dialect == "postgres"
    assert isinstance(cfg.security, SecurityConfig)
    assert cfg.dialects == {}
    assert cfg.connectors == {}
    assert cfg.custom_operators == {}
    assert cfg.default_limit == 100


def test_query_builder_config_copy():
    cfg = QueryBuilderConfig(
        default_dialect="mysql",
        dialects={"my_dialect": "mock"},
        connectors={"my_conn": "mock_conn"},
        custom_operators={"op": "handler"},
        default_limit=50,
    )
    copied = cfg.copy()
    assert copied.default_dialect == "mysql"
    assert copied.default_limit == 50
    assert copied.dialects == {"my_dialect": "mock"}
    assert copied.connectors == {"my_conn": "mock_conn"}
    assert copied.custom_operators == {"op": "handler"}
    assert copied is not cfg
    assert copied.security is not cfg.security


def test_query_builder_config_to_dict():
    cfg = QueryBuilderConfig(default_dialect="sqlite", default_limit=25)
    d = cfg.to_dict()
    assert d["default_dialect"] == "sqlite"
    assert d["default_limit"] == 25
    assert "security" in d
    assert isinstance(d["security"], dict)


# ---------------------------------------------------------------------------
# 2. configure_query_builder & get_query_builder_config
# ---------------------------------------------------------------------------


def test_get_query_builder_config_lazy_init():
    cfg = get_query_builder_config()
    assert isinstance(cfg, QueryBuilderConfig)
    assert cfg.default_dialect == "postgres"


def test_configure_query_builder_default_dialect():
    cfg = configure_query_builder(default_dialect="mysql")
    assert cfg.default_dialect == "mysql"
    assert get_query_builder_config().default_dialect == "mysql"

    # Verify get_dialect() resolves MySQL default
    resolved = get_dialect()
    assert resolved.placeholder == "%s"


def test_configure_query_builder_profile():
    cfg = configure_query_builder(profile="development")
    assert cfg.security.network.allow_private_networks is True
    assert cfg.security.execution.enforce_read_only_session is False

    cfg_strict = configure_query_builder(profile="strict")
    assert cfg_strict.security.network.allow_private_networks is False
    assert cfg_strict.security.execution.enforce_read_only_session is True

    with pytest.raises(ValueError, match="profile override must be a string"):
        configure_query_builder(profile=123)  # type: ignore


def test_configure_query_builder_security_and_kwargs():
    custom_sec = SecurityProfile.production()
    custom_sec.execution.max_rows_limit = 42

    cfg = configure_query_builder(security=custom_sec)
    assert cfg.security.execution.max_rows_limit == 42

    # Override via kwargs
    cfg2 = configure_query_builder(max_rows_limit=99, allow_private_networks=True)
    assert cfg2.security.execution.max_rows_limit == 99
    assert cfg2.security.network.allow_private_networks is True


def test_configure_query_builder_default_limit_validation():
    cfg = configure_query_builder(default_limit=200)
    assert cfg.default_limit == 200

    with pytest.raises(ValueError, match="default_limit must be positive"):
        configure_query_builder(default_limit=0)

    with pytest.raises(ValueError, match="default_limit must be positive"):
        configure_query_builder(default_limit=-5)


def test_configure_query_builder_reset():
    configure_query_builder(default_dialect="snowflake")
    assert get_query_builder_config().default_dialect == "snowflake"

    reset_query_builder_config()
    # Next get_query_builder_config creates fresh defaults
    fresh = get_query_builder_config()
    assert fresh.default_dialect == "postgres"


# ---------------------------------------------------------------------------
# 3. Custom Dialect Registration via Configuration
# ---------------------------------------------------------------------------


class CustomTestDialect(BaseDialect):
    name = "custom_cfg_dialect"
    placeholder = "?"

    def quote_identifier(self, ident: str) -> str:
        return f"`{ident}`"


def test_configure_query_builder_registers_dialect():
    custom_dialect = CustomTestDialect()
    configure_query_builder(dialects={"custom_cfg_dialect": custom_dialect})

    resolved = get_dialect("custom_cfg_dialect")
    assert resolved.quote_identifier("my_col") == "`my_col`"
    assert resolved.placeholder == "?"

    # Test compilation using the registered dialect
    compiler = QueryCompiler(
        spec={"table": "users", "columns": ["id", "name"]},
        dialect="custom_cfg_dialect",
    )
    sql, _params, _, _ = compiler.compile()
    assert "FROM `users`" in sql


# ---------------------------------------------------------------------------
# 4. Custom Connector Registration & Unregistration
# ---------------------------------------------------------------------------


class MockCustomConnector(BaseConnector):
    dialect_name = "sqlite"

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        return [{"mock_id": 1, "mock_val": "ok"}]


def test_connector_registration_and_unregistration():
    # Module-level register
    register_connector("mock_test_connector", MockCustomConnector)
    assert "mock_test_connector" in list_connectors()

    instance = get_connector("mock_test_connector")
    assert isinstance(instance, MockCustomConnector)

    # Module-level unregister
    unregister_connector("mock_test_connector")
    assert "mock_test_connector" not in list_connectors()

    with pytest.raises(
        ConnectorError, match="No connector registered for 'mock_test_connector'"
    ):
        get_connector("mock_test_connector")


def test_configure_query_builder_registers_connectors():
    configure_query_builder(connectors={"custom_cfg_connector": MockCustomConnector})
    assert "custom_cfg_connector" in list_connectors()

    inst = get_connector("custom_cfg_connector")
    assert isinstance(inst, MockCustomConnector)

    unregister_connector("custom_cfg_connector")
    assert "custom_cfg_connector" not in list_connectors()


# ---------------------------------------------------------------------------
# 5. Custom Filter Operators Registration & Compilation
# ---------------------------------------------------------------------------


def test_custom_filter_operator_lifecycle():
    def regex_handler(
        quoted_col: str, val: Any, dialect: BaseDialect
    ) -> tuple[str, list[Any]]:
        return f"{quoted_col} ~ {dialect.placeholder}", [str(val)]

    register_filter_operator("regex_match", regex_handler)
    assert "regex_match" in list_filter_operators()

    # Compile query with custom operator returning tuple
    compiler = QueryCompiler(
        spec={
            "table": "users",
            "columns": ["id", "email"],
            "filters": [
                {"column": "email", "op": "regex_match", "value": "^admin.*"},
            ],
        },
        dialect="postgres",
    )
    sql, params, _, _ = compiler.compile()
    assert '"email" ~ %s' in sql
    assert params[0] == "^admin.*"

    # Unregister operator
    unregister_filter_operator("regex_match")
    assert "regex_match" not in list_filter_operators()

    # Trying to compile with unregistered operator raises ValidationError
    with pytest.raises(ValidationError, match="Unsupported filter operator"):
        QueryCompiler(
            spec={
                "table": "users",
                "columns": ["id"],
                "filters": [{"column": "email", "op": "regex_match", "value": "test"}],
            }
        )


def test_custom_filter_operator_plain_string_and_params():
    # Test operator returning a string clause without new params
    def unary_handler(quoted_col: str, val: Any, dialect: BaseDialect) -> str:
        return f"LENGTH({quoted_col}) = 0"

    register_filter_operator("custom_unary", unary_handler)

    compiler = QueryCompiler(
        spec={
            "table": "docs",
            "columns": ["id"],
            "filters": [{"column": "body", "op": "custom_unary", "value": None}],
        },
        dialect="postgres",
    )
    sql, params, _, _ = compiler.compile()
    assert 'LENGTH("t1"."body") = 0' in sql
    assert params[0] == 50  # default limit

    unregister_filter_operator("custom_unary")


def test_custom_filter_operator_geospatial_multi_param():
    def dwithin_handler(
        quoted_col: str, val: Any, dialect: BaseDialect
    ) -> tuple[str, list[Any]]:
        # val is tuple of (lon, lat, distance)
        lon, lat, dist = val
        clause = f"ST_DWithin({quoted_col}, ST_MakePoint({dialect.placeholder}, {dialect.placeholder}), {dialect.placeholder})"
        return clause, [lon, lat, dist]

    register_filter_operator("geo_within", dwithin_handler)

    compiler = QueryCompiler(
        spec={
            "table": "places",
            "columns": ["id", "name"],
            "filters": [
                {"column": "geom", "op": "geo_within", "value": [-122.4, 37.7, 5000]}
            ],
        },
        dialect="postgres",
    )
    sql, params, _, _ = compiler.compile()
    assert 'ST_DWithin("t1"."geom", ST_MakePoint(%s, %s), %s)' in sql
    assert params[:3] == [-122.4, 37.7, 5000]

    unregister_filter_operator("geo_within")


def test_custom_filter_operator_invalid_return_type():
    def bad_handler(quoted_col: str, val: Any, dialect: BaseDialect) -> Any:
        return 12345  # Not a str or tuple

    register_filter_operator("invalid_ret_op", bad_handler)

    compiler = QueryCompiler(
        spec={
            "table": "items",
            "columns": ["id"],
            "filters": [{"column": "id", "op": "invalid_ret_op", "value": 1}],
        },
        dialect="postgres",
    )
    with pytest.raises(CompilationError, match="returned invalid result: int"):
        compiler.compile()

    unregister_filter_operator("invalid_ret_op")


def test_builtin_filter_operators_protected():
    # Attempting to unregister a builtin operator should not remove it from ALLOWED_FILTER_OPS
    unregister_filter_operator("eq")
    assert "eq" in list_filter_operators()

    compiler = QueryCompiler(
        spec={
            "table": "users",
            "columns": ["id"],
            "filters": [{"column": "id", "op": "eq", "value": 10}],
        }
    )
    sql, _params, _, _ = compiler.compile()
    assert '"id" = %s' in sql


# ---------------------------------------------------------------------------
# 6. Thread Safety & Concurrency
# ---------------------------------------------------------------------------


def test_concurrent_configuration_access():
    def worker(idx: int):
        configure_query_builder(default_limit=100 + idx)
        cfg = get_query_builder_config()
        return cfg.default_limit

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker, range(20)))

    assert len(results) == 20
    assert all(100 <= r < 120 for r in results)
