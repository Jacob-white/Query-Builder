"""
Comprehensive Unit Tests for JSON Schema & OpenAPI Adapter.
============================================================
Tests parsing of OpenAPI 3.x specifications and JSON Schema (Draft 4/7/2020-12),
verifying property extraction, types, enums, required/nullable mapping,
$ref and x-foreign-key relationships, and composite primary keys.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from query_builder.adapters.json_schema import from_json_schema
from query_builder.models import SchemaDict, TableSchema

OPENAPI_ECOMMERCE_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "E-Commerce API", "version": "1.0.0"},
    "components": {
        "schemas": {
            "users": {
                "type": "object",
                "required": ["id", "email"],
                "properties": {
                    "id": {"type": "integer", "x-primary-key": True},
                    "email": {"type": "string", "format": "email"},
                    "name": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": ["admin", "customer", "guest"],
                        "default": "customer",
                    },
                    "created_at": {"type": "string", "format": "date-time"},
                },
            },
            "profiles": {
                "type": "object",
                "required": ["id", "user_id"],
                "properties": {
                    "id": {"type": "integer", "primaryKey": True},
                    "user_id": {
                        "type": "integer",
                        "x-foreign-key": "users.id",
                    },
                    "bio": {"type": "string"},
                },
            },
            "orders": {
                "type": "object",
                "required": ["id", "user_id", "total"],
                "properties": {
                    "id": {"type": "integer", "is_primary": True},
                    "user_id": {
                        "type": "integer",
                        "x-references": "users.id",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "paid", "shipped", "cancelled"],
                        "default": "pending",
                    },
                    "total": {"type": "number"},
                },
            },
            "products": {
                "type": "object",
                "required": ["id", "name", "price"],
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "price": {"type": "number"},
                },
            },
            "order_items": {
                "type": "object",
                "x-primary-keys": ["order_id", "product_id"],
                "required": ["order_id", "product_id"],
                "properties": {
                    "order_id": {
                        "type": "integer",
                        "x-foreign-key": "orders.id",
                    },
                    "product_id": {
                        "type": "integer",
                        "x-foreign-key": "products.id",
                    },
                    "quantity": {"type": "integer", "default": 1},
                },
            },
        }
    },
}


def test_from_json_schema_openapi_ecommerce():
    tables = from_json_schema(OPENAPI_ECOMMERCE_SPEC)
    assert isinstance(tables, SchemaDict)
    assert set(tables.keys()) == {
        "users",
        "profiles",
        "orders",
        "products",
        "order_items",
    }

    # 1. users
    users = tables["users"]
    assert isinstance(users, TableSchema)
    assert users.primary_keys == ["id"]
    id_col = next(c for c in users.columns if c.name == "id")
    assert id_col.is_primary is True
    assert id_col.is_nullable is False
    assert id_col.data_type == "integer"

    email_col = next(c for c in users.columns if c.name == "email")
    assert email_col.is_nullable is False

    name_col = next(c for c in users.columns if c.name == "name")
    assert name_col.is_nullable is True

    role_col = next(c for c in users.columns if c.name == "role")
    assert role_col.enums == ["admin", "customer", "guest"]

    created_at_col = next(c for c in users.columns if c.name == "created_at")
    assert created_at_col.data_type == "timestamp"

    # 2. profiles
    profiles = tables["profiles"]
    assert len(profiles.foreign_keys) == 1
    fk = profiles.foreign_keys[0]
    assert fk.column == "user_id"
    assert fk.foreign_table == "users"
    assert fk.foreign_column == "id"

    # 3. orders
    orders = tables["orders"]
    assert len(orders.foreign_keys) == 1
    assert orders.foreign_keys[0].foreign_table == "users"
    status_col = next(c for c in orders.columns if c.name == "status")
    assert status_col.enums == ["pending", "paid", "shipped", "cancelled"]

    # 4. order_items (composite primary keys)
    order_items = tables["order_items"]
    assert set(order_items.primary_keys) == {"order_id", "product_id"}
    assert len(order_items.foreign_keys) == 2


def test_from_json_schema_string_and_file():
    json_str = json.dumps(OPENAPI_ECOMMERCE_SPEC)
    tables = from_json_schema(json_str)
    assert "users" in tables

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(json_str)
        f_path = Path(f.name)

    try:
        tables_file = from_json_schema(f_path)
        assert "users" in tables_file
    finally:
        f_path.unlink()


def test_from_json_schema_draft_7_definitions_and_ref():
    draft7_spec = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "definitions": {
            "Department": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": ["id", "name"],
            },
            "Employee": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "department_id": {
                        "type": "integer",
                        "$ref": "#/definitions/Department",
                    },
                    "title": {"type": ["string", "null"]},
                },
                "required": ["id"],
            },
        },
    }

    tables = from_json_schema(draft7_spec)
    assert "Department" in tables
    assert "Employee" in tables
    emp = tables["Employee"]
    assert len(emp.foreign_keys) == 1
    assert emp.foreign_keys[0].foreign_table == "Department"
    title_col = next(c for c in emp.columns if c.name == "title")
    assert title_col.is_nullable is True


def test_from_json_schema_single_object():
    single = {
        "title": "audit_logs",
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "action": {"type": "string"},
        },
    }
    tables = from_json_schema(single)
    assert "audit_logs" in tables
    log_tbl = tables["audit_logs"]
    assert log_tbl.primary_keys == ["id"]
    id_col = log_tbl.columns[0]
    assert id_col.data_type == "uuid"
