"""
Tests for NLQ AST Schema Grounding and Safety Validator.
"""

from __future__ import annotations

import pytest

from query_builder.nlq.models import NlqValidationError
from query_builder.nlq.validator import NlqAstValidator


def test_validator_with_non_dict_ast() -> None:
    validator = NlqAstValidator()
    with pytest.raises(NlqValidationError, match="Expected dictionary AST"):
        validator.validate("not a dict")  # type: ignore[arg-type]


def test_validator_with_missing_or_empty_table() -> None:
    validator = NlqAstValidator()
    with pytest.raises(NlqValidationError, match="must specify a non-empty 'table'"):
        validator.validate({"table": ""})

    with pytest.raises(NlqValidationError, match="must specify a non-empty 'table'"):
        validator.validate({"table": None})  # type: ignore[dict-item]


def test_validator_normalizes_valid_ast() -> None:
    schema = {
        "tables": {
            "Users": {
                "columns": {
                    "Id": {"data_type": "INT"},
                    "Email": {"data_type": "TEXT"},
                    "Status": {"data_type": "TEXT"},
                }
            },
            "Orders": {
                "columns": [
                    {"name": "Id"},
                    {"name": "User_Id"},
                    "Total",
                ]
            },
        }
    }
    validator = NlqAstValidator(schema=schema)

    raw_ast = {
        "table": "users",  # Case insensitive match to "Users"
        "columns": [
            "id",
            {"column": "email", "alias": "user_email"},
            {"column": "id", "agg": "count", "alias": "cnt"},
            {"column": "invalid_agg", "agg": "INVALID_FUNC"},
            {"column": ""},  # empty column should be skipped
            123,  # non-string/dict should be skipped
        ],
        "joins": [
            {
                "table": "orders",
                "type": "left",
                "left_table": "users",
                "left_col": "id",
                "right_col": "user_id",
            },
            {
                "table": "unknown_table",
                "type": "UNKNOWN_TYPE",
                "left_table": "users",
                "left_col": "id",
                "right_col": "id",
            },
            "not_a_dict_join",
            {"table": ""},
        ],
        "filters": [
            {"column": "status", "op": "eq", "value": "active"},
            {"column": "score", "op": ">=", "value": 50},
            {"column": "id", "op": "INVALID_OP", "value": 10},
            {"column": "", "op": "="},
            "not_a_filter",
        ],
        "filter_join": "or",
        "having": [
            {"column": "cnt", "op": ">", "value": 5},
            "not_a_having",
            {"op": ">"},
        ],
        "order_by": [
            {"column": "id", "direction": "desc"},
            {"column": "email", "direction": "INVALID_DIR"},
            {"column": ""},
            "not_an_order_by",
        ],
        "limit": "25",
        "offset": "10",
        "distinct": True,
        "vector_search": {
            "column": "embedding",
            "query_vector": [0.1, 0.2],
            "top_k": 5,
            "metric": "cosine",
        },
        "hybrid_search": {
            "vector": [0.1, 0.2],
            "query_text": "sample text",
            "alpha": 0.7,
        },
    }

    validated, warnings = validator.validate(raw_ast)
    assert validated["table"] == "Users"
    assert len(validated["columns"]) == 4
    assert validated["columns"][0] == "id"
    assert validated["columns"][1] == {"column": "email", "alias": "user_email"}
    assert validated["columns"][2] == {"column": "id", "agg": "COUNT", "alias": "cnt"}
    assert validated["columns"][3] == {"column": "invalid_agg"}

    # Joins
    assert len(validated["joins"]) == 2
    assert validated["joins"][0]["table"] == "Orders"
    assert validated["joins"][0]["type"] == "LEFT"
    assert validated["joins"][1]["type"] == "INNER"  # Fallback from UNKNOWN_TYPE

    # Filters
    assert len(validated["filters"]) == 3
    assert validated["filters"][0]["column"] == "status"
    assert validated["filters"][2]["op"] == "="  # Fallback from INVALID_OP
    assert validated["filter_join"] == "OR"

    # Having & Order By
    assert len(validated["having"]) == 1
    assert len(validated["order_by"]) == 2
    assert validated["order_by"][0]["direction"] == "DESC"
    assert validated["order_by"][1]["direction"] == "ASC"

    # Pagination & Flags
    assert validated["limit"] == 25
    assert validated["offset"] == 10
    assert validated["distinct"] is True
    assert validated["vector_search"]["column"] == "embedding"
    assert validated["hybrid_search"]["alpha"] == 0.7
    assert validated["hybrid_search"]["vector"] == [0.1, 0.2]


def test_validator_with_missing_table_in_schema_and_malformed_fields() -> None:
    schema = {"tables": {"customers": {"columns": {"id": "int"}}}}
    validator = NlqAstValidator(schema=schema)

    raw_ast = {
        "table": "products",  # not in schema
        "columns": "not_a_list",  # non-list columns
        "joins": "not_a_list",
        "filters": "not_a_list",
        "filter_join": "INVALID_JOIN",
        "having": "not_a_list",
        "order_by": "not_a_list",
        "limit": "invalid_number",
        "offset": -5,
        "vector_search": {"column": ""},  # empty column -> None
        "hybrid_search": "not_a_dict",
    }
    validated, warnings = validator.validate(raw_ast)
    assert validated["table"] == "products"
    assert any("was not found in the supplied database schema" in w for w in warnings)
    assert any("'columns' field was not a list" in w for w in warnings)
    assert validated["columns"] == []
    assert validated["joins"] == []
    assert validated["filters"] == []
    assert validated["filter_join"] == "AND"
    assert validated["limit"] == 50
    assert validated["offset"] == 0
    assert validated["vector_search"] is None
    assert validated["hybrid_search"] is None


def test_validator_edge_branches() -> None:
    # 1. Non-dict schema tables and non-dict table entries
    bad_schema = {
        "tables": {
            "invalid_meta": "not_a_dict",
            "table_with_odd_cols": {
                "columns": [123, "valid_col"],
            },
            "table_with_other_cols": {
                "columns": "not_a_dict_or_list",
            },
        }
    }
    validator = NlqAstValidator(schema=bad_schema)
    assert "table_with_odd_cols" in validator.tables_meta

    # 2. Whitespace-only string column, bad limit/offset, bad vector metric, empty hybrid vector
    raw = {
        "table": "table_with_odd_cols",
        "columns": ["   ", "valid_col"],
        "limit": object(),  # triggers TypeError on int()
        "offset": object(),  # triggers TypeError on int()
        "vector_search": {
            "vector": [1.0, 2.0],
            "metric": "UNKNOWN_METRIC",
        },
        "hybrid_search": {
            "vector": [],  # empty vector -> should become None
        },
    }
    res, warnings = validator.validate(raw)
    assert res["columns"] == ["valid_col"]
    assert res["limit"] == 50
    assert res["offset"] == 0
    assert res["vector_search"]["metric"] == "cosine"
    assert res["hybrid_search"] is None


def test_validator_with_non_dict_tables_key() -> None:
    validator = NlqAstValidator(schema={"tables": "string_not_dict"})
    assert validator.tables_meta == {}
