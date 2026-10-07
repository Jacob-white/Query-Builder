import pytest
from unittest.mock import patch

from query_builder.models import (
    ColumnSchema,
    ForeignKey,
    HybridSearchSpec,
    QuerySpec,
    SchemaDict,
    TableSchema,
)
from query_builder.schema import explore_schema
from query_builder.schema_converters import _extract_snapshot
import query_builder.ast_validator as ast_validator
import query_builder.middleware as middleware
from query_builder.join_solver import find_best_join_condition, find_join_path
from query_builder.config import (
    ExecutionSecurityConfig,
    QueryBuilderConfig,
    configure_query_builder,
    load_security_config_from_env,
)


def test_models_foreign_keys_and_enums_mapping():
    col1 = ColumnSchema(name="user_id", data_type="integer", enums=["A", "B"])
    col2 = ColumnSchema(name="org_id", data_type="integer")
    fk = ForeignKey(
        table="orders",
        column="user_id",
        foreign_table="users",
        foreign_column="id",
    )
    tbl = TableSchema(
        name="orders",
        columns=[col1, col2],
        foreign_keys=[fk],
        enums={},
    )
    assert col1.foreign_key == fk
    assert tbl.enums["user_id"] == ["A", "B"]

    schema = SchemaDict({"orders": tbl})
    d = schema.to_dict()
    assert "orders" in d
    assert d["orders"]["name"] == "orders"


def test_models_hybrid_search_spec_type_errors():
    with pytest.raises(TypeError, match="query_text"):
        HybridSearchSpec(
            vector=[0.1, 0.2],
            vector_column="embed",
            query_text=123,  # type: ignore[arg-type]
            text_columns=["title"],
        )

    with pytest.raises(TypeError, match="text_columns"):
        HybridSearchSpec(
            vector=[0.1, 0.2],
            vector_column="embed",
            query_text="search",
            text_columns=None,  # type: ignore[arg-type]
        )


def test_models_query_spec_tenant_id_to_dict():
    qp = QuerySpec(
        table="users",
        columns=["id", "name"],
        tenant_id="tenant_abc",
    )
    d = qp.to_dict()
    assert d["tenant_id"] == "tenant_abc"


def test_schema_analyze_with_unmapped_foreign_keys():
    raw_data = {
        "tables": {
            "users": {"columns": [{"name": "id"}]},
        },
        "foreign_keys": [
            {
                "table": "orders",
                "foreign_table": "users",
                "column": "u_id",
                "foreign_column": "id",
            },
            {
                "table": "users",
                "foreign_table": "external_orgs",
                "column": "org_id",
                "foreign_column": "id",
            },
        ],
    }
    res = explore_schema(raw_data)
    assert isinstance(res, dict)
    assert res["table_count"] == 1


def test_schema_converters_from_table_schema_instance():
    tbl = TableSchema(
        name="products",
        columns=[ColumnSchema(name="sku", data_type="text")],
        foreign_keys=[
            ForeignKey(
                table="products",
                column="sku",
                foreign_table="warehouse",
                foreign_column="sku",
            )
        ],
    )
    raw_tables, raw_fks = _extract_snapshot(tbl)
    assert "products" in raw_tables
    assert len(raw_fks) == 1


def test_ast_validator_when_sqlparse_is_none():
    with patch.object(ast_validator, "sqlparse", None):
        res = ast_validator.validate_sql_ast("SELECT 1;")
        assert res["valid"] is False
        assert "sqlparse is not installed" in res["violations"][0]


def test_middleware_mutating_sql_when_sqlparse_is_none():
    with patch.object(middleware, "sqlparse", None):
        assert middleware._is_mutating_sql("DROP TABLE customers;") is True
        assert middleware._is_mutating_sql("SELECT * FROM customers;") is False


def test_join_solver_with_to_dict_and_object_foreign_keys():
    tbl_a = TableSchema(
        name="customers",
        columns=[ColumnSchema(name="id", data_type="int")],
    )
    tbl_b = TableSchema(
        name="invoices",
        columns=[ColumnSchema(name="customer_id", data_type="int")],
    )

    class ObjectFK:
        table = "invoices"
        foreign_table = "customers"
        column = "customer_id"
        foreign_column = "id"

    schema_data = {
        "tables": {
            "customers": tbl_a,
            "invoices": tbl_b,
            "invalid_meta": "not_a_dict_or_object",
        },
        "foreign_keys": [ObjectFK()],
    }

    cond = find_best_join_condition(
        "customers",
        "invoices",
        schema_data=schema_data,
    )
    assert cond is not None
    assert cond["left_col"] == "id"
    assert cond["right_col"] == "customer_id"

    # Inverted
    cond_inv = find_best_join_condition(
        "invoices",
        "customers",
        schema_data=schema_data,
    )
    assert cond_inv is not None

    # Graph join path with ObjectFK and TableSchema
    path = find_join_path(
        ["customers"],
        "invoices",
        schema_data=schema_data,
    )
    assert len(path) == 1
    assert path[0]["table"] == "invoices"


def test_config_cache_validation_and_env():
    with pytest.raises(ValueError, match="default_ttl_seconds"):
        ExecutionSecurityConfig(default_ttl_seconds=-1)

    with pytest.raises(ValueError, match="max_cache_entries"):
        ExecutionSecurityConfig(max_cache_entries=0)

    cfg = load_security_config_from_env(
        {
            "QB_ENABLE_CACHE": "true",
            "QB_DEFAULT_TTL_SECONDS": "300",
            "QB_MAX_CACHE_ENTRIES": "1000",
        }
    )
    assert cfg.execution.enable_cache is True
    assert cfg.execution.default_ttl_seconds == 300
    assert cfg.execution.max_cache_entries == 1000

    with pytest.raises(ValueError, match="QB_DEFAULT_TTL_SECONDS"):
        load_security_config_from_env({"QB_DEFAULT_TTL_SECONDS": "-1"})

    with pytest.raises(ValueError, match="QB_MAX_CACHE_ENTRIES"):
        load_security_config_from_env({"QB_MAX_CACHE_ENTRIES": "0"})

    custom_cfg = QueryBuilderConfig()
    configure_query_builder(config=custom_cfg)
