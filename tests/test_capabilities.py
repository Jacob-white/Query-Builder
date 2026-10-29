"""
Tests for EngineCapabilities, FeatureTier, DisabledFeatureError, and compiler integration.
"""

import pytest

from query_builder import (
    DisabledFeatureError,
    EngineCapabilities,
    FeatureTier,
    QueryCompiler,
)
from query_builder.capabilities import disabled_feature_message


def test_require_feature():
    caps = EngineCapabilities.default()
    # Should not raise for standard/advanced features
    caps.require_feature("projections")
    caps.require_feature("ctes")

    caps_disabled = EngineCapabilities(ctes=FeatureTier.DISABLED)
    with pytest.raises(DisabledFeatureError) as exc_info:
        caps_disabled.require_feature("ctes")

    assert exc_info.value.feature_name == "ctes"


def test_capabilities_custom_overrides():
    caps = EngineCapabilities(
        custom_overrides={"my_feature": FeatureTier.ADVANCED, "other": "standard"}
    )

    assert caps.get_tier("my_feature") == FeatureTier.ADVANCED
    assert caps.get_tier("other") == "standard"
    assert caps.get_tier("ctes") == FeatureTier.ADVANCED

    d = caps.to_dict()
    assert d["my_feature"] == "advanced"
    assert d["other"] == "standard"

    d2 = {"projections": "standard", "custom1": "disabled"}
    caps2 = EngineCapabilities.from_dict(d2)
    assert caps2.custom_overrides["custom1"] == FeatureTier.DISABLED


def test_capabilities_from_dict_parsing():
    d = {
        "ctes": FeatureTier.STANDARD,
        "window_functions": True,
        "analytical_grouping": False,
        "raw_sql": "std",
        "query_plan": "adv",
        "calculated_fields": "off",
        "custom_expressions": "none",
        "schema_tools": "unknown_string",
    }
    caps = EngineCapabilities.from_dict(d)

    assert caps.ctes == FeatureTier.STANDARD
    assert caps.window_functions == FeatureTier.STANDARD
    assert caps.analytical_grouping == FeatureTier.DISABLED
    assert caps.raw_sql == FeatureTier.STANDARD
    assert caps.query_plan == FeatureTier.ADVANCED
    assert caps.calculated_fields == FeatureTier.DISABLED
    assert caps.custom_expressions == FeatureTier.DISABLED
    assert caps.schema_tools == FeatureTier.STANDARD


def test_capabilities_presets():
    pu = EngineCapabilities.power_user()
    assert pu.ctes == FeatureTier.ADVANCED
    assert pu.projections == FeatureTier.STANDARD

    full = EngineCapabilities.full()
    assert full.ctes == FeatureTier.STANDARD
    assert full.vector_search == FeatureTier.STANDARD
    assert full.analytical_grouping == FeatureTier.STANDARD


def test_disabled_feature_message():
    exc = DisabledFeatureError("ctes")
    msg = disabled_feature_message(exc, None)
    assert "Feature 'ctes' is disabled" in msg

    exc2 = DisabledFeatureError("my_custom")
    caps = EngineCapabilities(custom_overrides={"my_custom": FeatureTier.DISABLED})
    msg2 = disabled_feature_message(exc2, caps)
    assert "Feature 'my_custom' is disabled" in msg2

    exc3 = DisabledFeatureError("unknown_evil_feature")
    msg3 = disabled_feature_message(exc3, None)
    assert (
        msg3
        == "A feature used by this query is disabled in the active engine capabilities."
    )


def test_capabilities_default_and_serialization():
    caps = EngineCapabilities.default()
    assert caps.projections == FeatureTier.STANDARD
    assert caps.filters == FeatureTier.STANDARD
    assert caps.joins == FeatureTier.STANDARD
    assert caps.ctes == FeatureTier.ADVANCED
    assert caps.window_functions == FeatureTier.ADVANCED
    assert caps.is_enabled("ctes")
    assert caps.is_advanced("ctes")

    d = caps.to_dict()
    assert d["projections"] == "standard"
    assert d["ctes"] == "advanced"
    assert d["window_functions"] == "advanced"

    restored = EngineCapabilities.from_dict(d)
    assert restored.ctes == FeatureTier.ADVANCED
    assert restored.projections == FeatureTier.STANDARD


def test_capabilities_simple_only_preset():
    simple = EngineCapabilities.simple_only()
    assert not simple.is_enabled("ctes")
    assert not simple.is_enabled("window_functions")
    assert not simple.is_enabled("analytical_grouping")
    assert not simple.is_enabled("vector_search")
    assert simple.is_enabled("projections")
    assert simple.is_enabled("filters")


def test_compiler_allows_standard_query_on_simple_capabilities():
    simple = EngineCapabilities.simple_only()
    spec = {
        "table": "users",
        "columns": ["id", "name"],
        "filters": [{"column": "age", "op": "gt", "value": 21}],
        "order_by": [{"column": "name", "direction": "asc"}],
        "limit": 10,
    }
    compiler = QueryCompiler(spec, capabilities=simple)
    sql, params, _, _ = compiler.compile()
    assert "users" in sql
    assert "WHERE" in sql
    assert "ORDER BY" in sql


def test_compiler_blocks_ctes_when_disabled():
    caps = EngineCapabilities(ctes=FeatureTier.DISABLED)
    spec = {
        "table": "users",
        "columns": ["id"],
        "ctes": [
            {"name": "active_users", "query": {"table": "users", "columns": ["id"]}}
        ],
    }
    with pytest.raises(DisabledFeatureError) as exc_info:
        QueryCompiler(spec, capabilities=caps)
    assert "Feature 'ctes' is disabled" in str(exc_info.value)


def test_compiler_blocks_window_functions_when_disabled():
    caps = EngineCapabilities(window_functions=FeatureTier.DISABLED)
    spec = {
        "table": "orders",
        "columns": ["id", "amount"],
        "window_functions": [
            {
                "function": "sum",
                "column": "amount",
                "partition_by": ["user_id"],
                "order_by": ["id"],
                "alias": "running_total",
            }
        ],
    }
    with pytest.raises(DisabledFeatureError) as exc_info:
        QueryCompiler(spec, capabilities=caps)
    assert "Feature 'window_functions' is disabled" in str(exc_info.value)


def test_compiler_blocks_analytical_grouping_when_disabled():
    caps = EngineCapabilities(analytical_grouping=FeatureTier.DISABLED)
    spec = {
        "table": "sales",
        "columns": ["region", "year"],
        "rollup": {"columns": ["region", "year"]},
    }
    with pytest.raises(DisabledFeatureError) as exc_info:
        QueryCompiler(spec, capabilities=caps)
    assert "Feature 'analytical_grouping' is disabled" in str(exc_info.value)


def test_compiler_blocks_vector_search_when_disabled():
    caps = EngineCapabilities(vector_search=FeatureTier.DISABLED)
    spec = {
        "table": "documents",
        "columns": ["id", "content"],
        "vector_search": {
            "column": "embedding",
            "vector": [0.1, 0.2, 0.3],
            "metric": "cosine",
            "top_k": 5,
        },
    }
    with pytest.raises(DisabledFeatureError) as exc_info:
        QueryCompiler(spec, capabilities=caps)
    assert "Feature 'vector_search' is disabled" in str(exc_info.value)


def test_compiler_blocks_calculated_fields_when_disabled():
    caps = EngineCapabilities(calculated_fields=FeatureTier.DISABLED)
    spec = {
        "table": "orders",
        "columns": [
            "id",
            {"alias": "total_with_tax", "expression": "amount * 1.1"},
        ],
    }
    with pytest.raises(DisabledFeatureError) as exc_info:
        QueryCompiler(spec, capabilities=caps)
    assert "Feature 'calculated_fields' is disabled" in str(exc_info.value)


def test_fastapi_capabilities_integration():
    try:
        import sqlite3

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from query_builder.connectors.sqlite import SQLiteConnector
        from query_builder.integrations.fastapi import create_query_builder_router
    except ImportError:
        pytest.skip("FastAPI not installed")

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'Alice')")
    conn.commit()
    connector = SQLiteConnector(connection=conn)

    simple_caps = EngineCapabilities.simple_only()
    router = create_query_builder_router(
        connector=connector,
        capabilities=simple_caps,
        prefix="/qb",
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. GET /qb/capabilities
    cap_res = client.get("/qb/capabilities")
    assert cap_res.status_code == 200
    caps_data = cap_res.json()["capabilities"]
    assert caps_data["ctes"] == "disabled"
    assert caps_data["projections"] == "standard"

    # 2. GET /qb/schema contains capabilities
    schema_res = client.get("/qb/schema")
    assert schema_res.status_code == 200
    assert "capabilities" in schema_res.json()
    assert schema_res.json()["capabilities"]["raw_sql"] == "disabled"

    # 3. POST /qb/compile simple succeeds
    compile_ok = client.post(
        "/qb/compile",
        json={"spec": {"table": "users", "columns": ["id", "name"]}},
    )
    assert compile_ok.status_code == 200

    # 4. POST /qb/compile with disabled CTE returns 403
    compile_cte = client.post(
        "/qb/compile",
        json={
            "spec": {
                "table": "users",
                "columns": ["id"],
                "ctes": [{"name": "u", "query": {"table": "users", "columns": ["id"]}}],
            }
        },
    )
    assert compile_cte.status_code == 403
    assert "disabled" in compile_cte.json()["detail"].lower()

    # 5. POST /qb/execute with raw SQL when raw_sql is disabled returns 403
    exec_raw = client.post(
        "/qb/execute",
        json={"sql": "SELECT 1"},
    )
    assert exec_raw.status_code == 403
    assert "raw_sql" in exec_raw.json()["detail"].lower()
