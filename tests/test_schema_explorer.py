"""
Unit and integration tests for Schema Explorer helpers and CLI command.
"""

from __future__ import annotations

import json

import pytest

from query_builder import explore_schema, format_schema_tree
from query_builder.cli import main


@pytest.fixture
def sample_schema_dict() -> dict:
    return {
        "tables": {
            "users": {
                "name": "users",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "is_primary": True,
                    },
                    {
                        "name": "email",
                        "data_type": "text",
                        "is_nullable": False,
                        "is_primary": False,
                    },
                ],
                "has_user_id": False,
                "comment": "User accounts table",
            },
            "orders": {
                "name": "orders",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "is_primary": True,
                    },
                    {
                        "name": "user_id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "is_primary": False,
                    },
                    {
                        "name": "total",
                        "data_type": "numeric",
                        "is_nullable": True,
                        "is_primary": False,
                    },
                ],
                "has_user_id": True,
                "comment": "Orders placed by users",
            },
            "order_items": {
                "name": "order_items",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "is_primary": True,
                    },
                    {
                        "name": "order_id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "is_primary": False,
                    },
                    {
                        "name": "product_name",
                        "data_type": "text",
                        "is_nullable": False,
                        "is_primary": False,
                    },
                ],
                "has_user_id": False,
            },
            "settings": {
                "name": "settings",
                "columns": [
                    {
                        "name": "key",
                        "data_type": "text",
                        "is_nullable": False,
                        "is_primary": True,
                    },
                    {
                        "name": "val",
                        "data_type": "json",
                        "is_nullable": True,
                        "is_primary": False,
                    },
                ],
                "has_user_id": False,
            },
            "pg_tables": {
                "name": "pg_tables",
                "columns": [{"name": "tablename", "data_type": "text"}],
            },
        },
        "foreign_keys": [
            {
                "table": "orders",
                "column": "user_id",
                "foreign_table": "users",
                "foreign_column": "id",
            },
            {
                "table": "order_items",
                "column": "order_id",
                "foreign_table": "orders",
                "foreign_column": "id",
            },
        ],
        "relationships": [
            {
                "source_table": "orders",
                "source_column": "user_id",
                "target_table": "users",
                "target_column": "id",
            },
            {
                "source_table": "order_items",
                "source_column": "order_id",
                "target_table": "orders",
                "target_column": "id",
            },
        ],
        "categories": {
            "Commerce": ["orders", "order_items"],
            "Identity": ["users"],
        },
    }


def test_explore_schema_metrics(sample_schema_dict):
    result = explore_schema(sample_schema_dict, filter_sensitive=True)

    # pg_tables should be filtered out
    assert "pg_tables" not in result["tables"]
    assert result["table_count"] == 4
    assert result["column_count"] == 10  # 2 + 3 + 3 + 2
    assert result["primary_key_count"] == 4
    assert result["foreign_key_count"] == 2
    assert result["user_isolated_count"] == 1  # orders
    assert "settings" in result["isolated_tables"]
    assert "users" in result["tables"]
    assert "orders" in result["tables"]

    # Check incoming & outgoing FK tracking
    orders_info = result["tables"]["orders"]
    assert len(orders_info["outgoing_fks"]) == 1
    assert orders_info["outgoing_fks"][0]["foreign_table"] == "users"
    assert len(orders_info["incoming_fks"]) == 1
    assert orders_info["incoming_fks"][0]["table"] == "order_items"

    # Data types distribution
    assert result["data_types"]["integer"] >= 4
    assert result["data_types"]["text"] >= 2
    assert result["data_types"]["json"] == 1


def test_explore_schema_without_filtering_sensitive(sample_schema_dict):
    result = explore_schema(sample_schema_dict, filter_sensitive=False)
    assert "pg_tables" in result["tables"]
    assert result["table_count"] == 5


def test_format_schema_tree_rendering(sample_schema_dict):
    tree_text = format_schema_tree(
        sample_schema_dict, filter_sensitive=True, max_columns=2
    )

    assert "Database Schema (4 tables, 10 columns, 2 FKs):" in tree_text
    assert "├── orders (3 cols) [user-isolated]" in tree_text
    assert "FK: user_id -> users.id" in tree_text
    assert "... (1 more columns)" in tree_text
    assert "users" in tree_text
    assert "settings" in tree_text
    assert "pg_tables" not in tree_text


def test_cli_schema_overview(sample_schema_dict, capsys):
    json_schema = json.dumps(sample_schema_dict)
    code = main(["schema", "--schema", json_schema])
    assert code == 0
    captured = capsys.readouterr()
    assert "Schema Overview: 4 tables, 10 columns, 2 foreign keys" in captured.out
    assert "User-Isolated Tables: 1" in captured.out
    assert "Tables: order_items, orders, settings, users" in captured.out


def test_cli_schema_tree(sample_schema_dict, capsys):
    json_schema = json.dumps(sample_schema_dict)
    code = main(["schema", "--schema", json_schema, "--tree"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Database Schema (4 tables, 10 columns, 2 FKs):" in captured.out
    assert "FK: user_id -> users.id" in captured.out


def test_cli_schema_json(sample_schema_dict, capsys):
    json_schema = json.dumps(sample_schema_dict)
    code = main(["schema", "--schema", json_schema, "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["table_count"] == 4
    assert "users" in data["tables"]


def test_cli_schema_table_detail(sample_schema_dict, capsys):
    json_schema = json.dumps(sample_schema_dict)
    code = main(["schema", "--schema", json_schema, "--table", "orders"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Table: orders [user-isolated]" in captured.out
    assert "Columns (3):" in captured.out
    assert "• id (integer, NOT NULL) [PK]" in captured.out
    assert "Outgoing Foreign Keys:" in captured.out
    assert "➔ user_id -> users.id" in captured.out
    assert "Incoming References:" in captured.out
    assert "⬅ order_items.order_id -> id" in captured.out


def test_cli_schema_table_detail_json(sample_schema_dict, capsys):
    json_schema = json.dumps(sample_schema_dict)
    code = main(["schema", "--schema", json_schema, "--table", "orders", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["name"] == "orders"
    assert data["column_count"] == 3


def test_cli_schema_table_not_found(sample_schema_dict, capsys):
    json_schema = json.dumps(sample_schema_dict)
    code = main(["schema", "--schema", json_schema, "--table", "nonexistent"])
    assert code == 1
    captured = capsys.readouterr()
    assert (
        "Table 'nonexistent' not found in schema snapshot." in captured.err
        or "Table 'nonexistent' not found" in captured.out
    )


def test_cli_schema_file_reading(sample_schema_dict, tmp_path, capsys):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(sample_schema_dict), encoding="utf-8")

    code = main(["schema", "--schema", str(schema_file)])
    assert code == 0
    captured = capsys.readouterr()
    assert "Schema Overview: 4 tables" in captured.out
