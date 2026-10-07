"""
Tests for NLQ models, schema serialization, and prompt construction.
"""

from __future__ import annotations

from query_builder.models import QuerySpec
from query_builder.nlq.models import (
    NlqError,
    NlqExplainResult,
    NlqProviderError,
    NlqResult,
    NlqTranslateRequest,
    NlqValidationError,
)
from query_builder.nlq.prompt import (
    build_explain_prompt,
    build_system_prompt,
    build_user_prompt,
    get_few_shot_exemplars,
    serialize_schema_for_prompt,
)


def test_nlq_error_hierarchy() -> None:
    base = NlqError("base error")
    assert isinstance(base, Exception)

    val_err = NlqValidationError("validation error")
    assert isinstance(val_err, NlqError)

    prov_err = NlqProviderError("provider error")
    assert isinstance(prov_err, NlqError)


def test_nlq_result_and_explain_result_to_dict() -> None:
    qs = QuerySpec(table="users", columns=["id", "name"])
    res = NlqResult(
        spec={"table": "users", "columns": ["id", "name"]},
        query_spec=qs,
        confidence=0.95,
        explanation="Selects id and name from users.",
        provider="mock",
        model="mock-v1",
        tokens_used=120,
        warnings=["table schema was inferred"],
    )
    d = res.to_dict()
    assert d["spec"]["table"] == "users"
    assert d["confidence"] == 0.95
    assert d["provider"] == "mock"
    assert d["tokens_used"] == 120
    assert d["warnings"] == ["table schema was inferred"]

    explain_res = NlqExplainResult(
        summary="User query",
        explanation="Detailed description",
        steps=["Step 1", "Step 2"],
        provider="mock",
    )
    ed = explain_res.to_dict()
    assert ed["summary"] == "User query"
    assert ed["steps"] == ["Step 1", "Step 2"]
    assert ed["provider"] == "mock"


def test_nlq_translate_request_defaults() -> None:
    req = NlqTranslateRequest(prompt="Show all users")
    assert req.prompt == "Show all users"
    assert req.provider == "mock"
    assert req.dialect == "postgres"
    assert req.schema is None
    assert req.temperature == 0.0
    assert req.max_tokens == 1024


def test_serialize_schema_for_prompt() -> None:
    # 1. None schema
    assert "No explicit schema provided" in serialize_schema_for_prompt(None)

    # 2. Empty schema
    assert "No explicit schema provided" in serialize_schema_for_prompt({})

    # 3. Rich schema with dict columns, list columns, and foreign keys
    schema = {
        "tables": {
            "users": {
                "columns": {
                    "id": {"data_type": "INTEGER", "primary_key": True},
                    "email": {"data_type": "VARCHAR"},
                    "score": "FLOAT",
                },
                "foreign_keys": [],
            },
            "orders": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "primary_key": True},
                    {"name": "user_id", "type": "INTEGER"},
                    "created_at",
                ],
                "foreign_keys": [
                    {
                        "column": "user_id",
                        "target_table": "users",
                        "target_column": "id",
                    }
                ],
            },
            "invalid_table": "not_a_dict",
        }
    }
    serialized = serialize_schema_for_prompt(schema)
    assert "Table `users`:" in serialized
    assert "id: INTEGER (PK)" in serialized
    assert "score: FLOAT" in serialized
    assert "Table `orders`:" in serialized
    assert "user_id -> users.id" in serialized
    assert "created_at" in serialized

    # 4. Edge cases: non-dict tables, non-dict/list columns, non-dict fks, empty cols
    edge_schema = {
        "tables": {
            "empty_tbl": {
                "columns": {},
                "foreign_keys": ["not_a_dict", {"column": ""}],
            },
            "bad_col_types": {
                "columns": [123],
                "foreign_keys": "not_a_list",
            },
            "string_cols": {
                "columns": "invalid_columns",
            },
        }
    }
    edge_serialized = serialize_schema_for_prompt(edge_schema)
    assert "no columns listed" in edge_serialized
    assert "Table `bad_col_types`:" in edge_serialized

    # 5. tables as string
    assert "Database Schema:" in serialize_schema_for_prompt({"tables": "not_a_dict"})


def test_prompt_builders_and_exemplars() -> None:
    exemplars = get_few_shot_exemplars()
    assert len(exemplars) >= 3
    for ex in exemplars:
        assert "prompt" in ex
        assert "spec" in ex

    sys_p = build_system_prompt("Schema text", dialect="duckdb")
    assert "Target SQL Dialect: duckdb" in sys_p
    assert "Schema text" in sys_p
    assert "FEW-SHOT EXAMPLES" in sys_p

    user_p = build_user_prompt("Find all active products")
    assert (
        'Translate this request into QuerySpec JSON:\n"Find all active products"'
        == user_p
    )

    explain_p = build_explain_prompt({"table": "orders", "limit": 10}, dialect="sqlite")
    assert "Target Dialect: sqlite" in explain_p
    assert '"table": "orders"' in explain_p
