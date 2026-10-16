"""
Tests for Autonomous Self-Healing Query Engine (Milestone 2).
============================================================
"""

from __future__ import annotations

from query_builder.ai.self_healing import SelfHealingQueryEngine

SAMPLE_SCHEMA = {
    "tables": {
        "users": {
            "columns": [
                {"name": "id", "data_type": "INTEGER"},
                {"name": "name", "data_type": "TEXT"},
                {"name": "email", "data_type": "TEXT"},
            ],
            "foreign_keys": [],
        },
        "orders": {
            "columns": [
                {"name": "id", "data_type": "INTEGER"},
                {"name": "user_id", "data_type": "INTEGER"},
                {"name": "amount", "data_type": "NUMERIC"},
                {"name": "status", "data_type": "TEXT"},
            ],
            "foreign_keys": [
                {
                    "table": "orders",
                    "column": "user_id",
                    "foreign_table": "users",
                    "foreign_column": "id",
                }
            ],
        },
    }
}


def test_operator_synonyms_normalization():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    raw_spec = {
        "table": "users",
        "columns": ["id", "name"],
        "filters": [
            {"column": "name", "op": "==", "value": "Alice"},
            {"column": "id", "op": "!=", "value": 99},
            {"column": "email", "op": "like", "value": "%@test.com"},
            {"column": "status", "op": "not in", "value": ["banned"]},
        ],
        "having": [
            {"column": "id", "op": ">=", "value": 1, "agg": "COUNT"},
        ],
    }

    healed, notes = engine.auto_heal(raw_spec)
    assert healed["filters"][0]["op"] == "eq"
    assert healed["filters"][1]["op"] == "neq"
    assert healed["filters"][2]["op"] == "contains"
    assert healed["filters"][3]["op"] == "not_in"
    assert healed["having"][0]["op"] == "gte"
    assert len(notes) >= 5


def test_table_typo_correction():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    raw_spec = {
        "table": "userz",
        "columns": ["id", "name"],
    }
    healed, notes = engine.auto_heal(raw_spec)
    assert healed["table"] == "users"
    assert any("userz" in n for n in notes)


def test_column_typo_correction():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    raw_spec = {
        "table": "users",
        "columns": ["id", "namme"],
        "filters": [
            {"column": "emaiil", "op": "eq", "value": "test@example.com"},
        ],
    }
    healed, notes = engine.auto_heal(raw_spec)
    assert "name" in healed["columns"]
    assert healed["filters"][0]["column"] == "email"


def test_cross_table_column_and_join_injection():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    # User queries 'users', but includes 'amount' from 'orders'
    raw_spec = {
        "table": "users",
        "columns": ["id", "name", "amount"],
        "filters": [],
    }
    healed, notes = engine.auto_heal(raw_spec)
    # Check that join to orders was injected
    assert len(healed.get("joins", [])) == 1
    join = healed["joins"][0]
    assert join["table"] == "orders"
    assert any("orders" in n for n in notes)


def test_generate_repair_prompt():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    broken_spec = {"table": "nonexistent"}
    prompt = engine.generate_repair_prompt(
        broken_spec=broken_spec,
        errors=["Table 'nonexistent' does not exist in schema"],
        original_prompt="Show non-existent data",
    )
    assert 'Original Intent: "Show non-existent data"' in prompt
    assert "nonexistent" in prompt
    assert "JSON QuerySpec" in prompt


def test_extended_operator_synonyms():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    raw_spec = {
        "table": "users",
        "columns": ["id", "name"],
        "filters": [
            {"column": "name", "op": "starts with", "value": "A"},
            {"column": "email", "op": "endswith", "value": ".com"},
            {"column": "status", "op": "is not", "value": "active"},
            {"column": "deleted_at", "op": "isnull", "value": None},
        ],
    }
    healed, notes = engine.auto_heal(raw_spec)
    assert healed["filters"][0]["op"] == "starts_with"
    assert healed["filters"][1]["op"] == "ends_with"
    assert healed["filters"][2]["op"] == "neq"
    assert healed["filters"][3]["op"] == "is_null"


def test_join_table_typo_correction():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    raw_spec = {
        "table": "users",
        "columns": ["id"],
        "joins": [
            {
                "table": "orderz",
                "type": "LEFT JOIN",
                "left_col": "id",
                "right_col": "user_id",
            }
        ],
    }
    healed, notes = engine.auto_heal(raw_spec)
    assert healed["joins"][0]["table"] == "orders"
    assert any("Fuzzy join table healed" in n for n in notes)


def test_having_and_window_join_synthesis():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    # Users is primary, but having references orders.amount
    raw_spec = {
        "table": "users",
        "columns": ["id"],
        "having": [{"column": "orders.amount", "agg": "sum", "op": "gt", "value": 100}],
    }
    healed, notes = engine.auto_heal(raw_spec)
    assert len(healed.get("joins", [])) == 1
    assert healed["joins"][0]["table"] == "orders"


def test_table_prefix_typo_correction():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    raw_spec = {
        "table": "orders",
        "columns": ["id"],
        "filters": [
            {"column": "name", "tablePrefix": "userz", "op": "eq", "value": "Alice"}
        ],
    }
    healed, notes = engine.auto_heal(raw_spec)
    assert healed["filters"][0]["tablePrefix"] == "users"
    assert any("Fuzzy filter table prefix healed" in n for n in notes)


def test_having_and_orderby_typo_corrections():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    raw_spec = {
        "table": "users",
        "columns": ["id"],
        "having": [{"column": "namme", "op": "eq", "value": "Alice", "agg": "COUNT"}],
        "order_by": [
            {"column": "emaiil", "tablePrefix": "userz", "direction": "desc"},
            {"column": "users.namme", "direction": "asc"},
        ],
    }
    healed, notes = engine.auto_heal(raw_spec)
    assert healed["having"][0]["column"] == "name"
    assert healed["order_by"][0]["column"] == "email"
    assert healed["order_by"][0]["tablePrefix"] == "users"
    assert healed["order_by"][1]["column"] == "users.name"
    assert any("Fuzzy column healed in having" in n for n in notes)
    assert any("Fuzzy order_by table prefix healed" in n for n in notes)
    assert any("Fuzzy column healed in order_by" in n for n in notes)


def test_join_details_typo_corrections():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    raw_spec = {
        "table": "users",
        "columns": ["id"],
        "joins": [
            {
                "table": "orderz",
                "left_table": "userz",
                "left_col": "idd",
                "right_col": "user_idd",
            }
        ],
    }
    healed, notes = engine.auto_heal(raw_spec)
    j = healed["joins"][0]
    assert j["table"] == "orders"
    assert j["left_table"] == "users"
    assert j["left_col"] == "id"
    assert j["right_col"] == "user_id"
    assert any("Fuzzy join left table healed" in n for n in notes)
    assert any("Fuzzy join column healed" in n for n in notes)


def test_window_functions_typo_correction():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    raw_spec = {
        "table": "users",
        "columns": ["id"],
        "window_functions": [
            {
                "function": "ROW_NUMBER",
                "alias": "rn",
                "partition_by": ["namme", "users.emaiil"],
            }
        ],
    }
    healed, notes = engine.auto_heal(raw_spec)
    w = healed["window_functions"][0]
    assert w["partition_by"] == ["name", "users.email"]
    assert any("Fuzzy column healed in window partition" in n for n in notes)


def test_table_inference_and_schema_variants():
    engine = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    # 1. Infer from projection prefix
    s1, n1 = engine.auto_heal({"columns": ["orders.id"]})
    assert s1["table"] == "orders"
    assert any("Inferred primary table 'orders' from projection" in n for n in n1)

    # 2. Infer from filter prefix
    s2, n2 = engine.auto_heal(
        {"filters": [{"tablePrefix": "users", "column": "id", "op": "eq", "value": 1}]}
    )
    assert s2["table"] == "users"
    assert any("Inferred primary table 'users' from filter prefix" in n for n in n2)

    # 3. Infer from filter column prefix
    s3, n3 = engine.auto_heal(
        {"filters": [{"column": "orders.amount", "op": "gt", "value": 10}]}
    )
    assert s3["table"] == "orders"
    assert any("Inferred primary table 'orders' from filter column" in n for n in n3)

    # 4. Fallback when completely empty
    s4, n4 = engine.auto_heal({})
    assert s4["table"] == "users"
    assert any("Assigned default primary table" in n for n in n4)

    # 5. Dict columns with typos
    s5, n5 = engine.auto_heal({"table": "users", "columns": [{"column": "namme"}]})
    assert s5["columns"][0]["column"] == "name"
    assert any("Fuzzy column healed" in n for n in n5)

    # 6. Column metadata variants
    custom_schema = {
        "tables": {
            "t1": {"columns": {"col_a": "TEXT", "col_b": "INT"}},
            "t2": {"columns": ["c1", "c2"]},
            "t3": "not-a-dict",
        }
    }
    e_custom = SelfHealingQueryEngine(schema=custom_schema)
    assert e_custom._get_column_names(custom_schema["tables"]["t1"]) == [
        "col_a",
        "col_b",
    ]
    assert e_custom._get_column_names(custom_schema["tables"]["t2"]) == ["c1", "c2"]
    assert e_custom._get_column_names(custom_schema["tables"]["t3"]) == []
    assert e_custom._get_column_names("invalid") == []

    # 7. Security sanitizer alert notice
    bad_spec = {
        "table": "users",
        "columns": ["id"],
        "filters": [{"column": "id; DROP TABLE users; --", "op": "eq", "value": 1}],
    }
    _, n_bad = engine.auto_heal(bad_spec)
    assert any("sanitizer" in n.lower() or "compiler" in n.lower() for n in n_bad)


def test_direct_join_fallback_when_no_foreign_keys():
    from unittest.mock import patch

    schema = {
        "tables": {
            "users": {"columns": [{"name": "id"}], "foreign_keys": []},
            "profiles": {
                "columns": [{"name": "user_id"}, {"name": "bio"}],
                "foreign_keys": [],
            },
        }
    }
    engine = SelfHealingQueryEngine(schema=schema)
    spec = {"table": "users", "columns": ["id", "profiles.bio"]}
    with patch("query_builder.ai.self_healing.find_join_path", return_value=[]):
        healed, notes = engine.auto_heal(spec)
    assert len(healed["joins"]) == 1
    assert healed["joins"][0]["table"] == "profiles"
    assert any("Autonomous join synthesis" in n for n in notes)
