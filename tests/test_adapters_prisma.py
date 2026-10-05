"""
Comprehensive Unit Tests for Prisma Schema Adapter.
===================================================
Tests parsing of Prisma schema files, text strings, and DMMF structures,
verifying single/composite primary keys, foreign key relations, enums,
nullable fields, default values, and snapshot synthesis.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from query_builder.adapters.prisma import from_prisma
from query_builder.models import SchemaDict, TableSchema
from query_builder.schema_converters import to_prisma_schema

PRISMA_ECOMMERCE_SCHEMA = """
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

enum UserRole {
  ADMIN
  CUSTOMER
  GUEST
}

enum OrderStatus {
  PENDING
  PAID
  SHIPPED
  CANCELLED
}

model User {
  id        Int       @id @default(autoincrement())
  email     String    @unique
  name      String?
  role      UserRole  @default(CUSTOMER)
  createdAt DateTime  @default(now())
  profile   Profile?
  orders    Order[]

  @@map("users")
}

model Profile {
  id        Int     @id @default(autoincrement())
  userId    Int     @unique
  bio       String?
  user      User    @relation(fields: [userId], references: [id])

  @@map("profiles")
}

model Order {
  id        Int         @id @default(autoincrement())
  userId    Int
  status    OrderStatus @default(PENDING)
  total     Float
  user      User        @relation(fields: [userId], references: [id])
  items     OrderItem[]

  @@map("orders")
}

model Product {
  id        Int         @id @default(autoincrement())
  name      String
  price     Float
  items     OrderItem[]

  @@map("products")
}

model OrderItem {
  orderId   Int
  productId Int
  quantity  Int     @default(1)
  order     Order   @relation(fields: [orderId], references: [id])
  product   Product @relation(fields: [productId], references: [id])

  @@id([orderId, productId])
  @@map("order_items")
}
"""


def test_from_prisma_text_ecommerce_tables():
    tables = from_prisma(PRISMA_ECOMMERCE_SCHEMA)
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
    assert users.name == "users"
    assert users.primary_keys == ["id"]
    id_col = next(c for c in users.columns if c.name == "id")
    assert id_col.is_primary is True
    assert id_col.data_type == "integer"
    assert id_col.is_nullable is False
    assert id_col.default == "autoincrement()"

    email_col = next(c for c in users.columns if c.name == "email")
    assert email_col.is_nullable is False
    assert email_col.data_type == "text"

    name_col = next(c for c in users.columns if c.name == "name")
    assert name_col.is_nullable is True

    role_col = next(c for c in users.columns if c.name == "role")
    assert role_col.enums == ["ADMIN", "CUSTOMER", "GUEST"]
    assert role_col.default == "CUSTOMER"

    # 2. profiles (foreign key to users)
    profiles = tables["profiles"]
    assert profiles.primary_keys == ["id"]
    assert len(profiles.foreign_keys) == 1
    fk = profiles.foreign_keys[0]
    assert fk.table == "profiles"
    assert fk.column == "userId"
    assert fk.foreign_table == "users"
    assert fk.foreign_column == "id"

    # 3. orders
    orders = tables["orders"]
    assert orders.primary_keys == ["id"]
    status_col = next(c for c in orders.columns if c.name == "status")
    assert status_col.enums == ["PENDING", "PAID", "SHIPPED", "CANCELLED"]
    assert status_col.default == "PENDING"
    assert len(orders.foreign_keys) == 1
    assert orders.foreign_keys[0].foreign_table == "users"

    # 4. order_items (composite primary key)
    order_items = tables["order_items"]
    assert set(order_items.primary_keys) == {"orderId", "productId"}
    order_id_col = next(c for c in order_items.columns if c.name == "orderId")
    assert order_id_col.is_primary is True
    prod_id_col = next(c for c in order_items.columns if c.name == "productId")
    assert prod_id_col.is_primary is True
    assert len(order_items.foreign_keys) == 2


def test_from_prisma_file_path():
    with tempfile.NamedTemporaryFile("w", suffix=".prisma", delete=False) as f:
        f.write(PRISMA_ECOMMERCE_SCHEMA)
        f_path = Path(f.name)

    try:
        tables = from_prisma(f_path)
        assert "users" in tables
        assert "order_items" in tables
    finally:
        f_path.unlink()


def test_from_prisma_dmmf_dictionary():
    dmmf = {
        "datamodel": {
            "enums": [
                {
                    "name": "Status",
                    "values": [{"name": "ACTIVE"}, {"name": "INACTIVE"}],
                }
            ],
            "models": [
                {
                    "name": "Account",
                    "dbName": "accounts",
                    "primaryKey": None,
                    "fields": [
                        {
                            "name": "id",
                            "type": "Int",
                            "isId": True,
                            "isRequired": True,
                            "default": {"name": "autoincrement"},
                        },
                        {
                            "name": "status",
                            "type": "Status",
                            "kind": "enum",
                            "isRequired": True,
                        },
                        {
                            "name": "notes",
                            "type": "String",
                            "isRequired": False,
                        },
                    ],
                }
            ],
        }
    }
    tables = from_prisma(dmmf)
    assert "accounts" in tables
    acc = tables["accounts"]
    assert acc.primary_keys == ["id"]
    status_col = next(c for c in acc.columns if c.name == "status")
    assert status_col.enums == ["ACTIVE", "INACTIVE"]
    notes_col = next(c for c in acc.columns if c.name == "notes")
    assert notes_col.is_nullable is True


def test_prisma_table_schema_conversion_methods():
    tables = from_prisma(PRISMA_ECOMMERCE_SCHEMA)
    users = tables["users"]

    # to_table_meta
    meta = users.to_table_meta()
    assert meta.name == "users"
    assert len(meta.columns) == len(users.columns)

    # to_dict
    d = users.to_dict()
    assert d["name"] == "users"
    assert d["primary_keys"] == ["id"]
    assert "columns" in d

    # to_schema_snapshot
    snapshot = users.to_schema_snapshot()
    assert "users" in snapshot.tables

    # SchemaDict to_snapshot
    full_snapshot = tables.to_snapshot()
    assert set(full_snapshot.tables.keys()) == {
        "users",
        "profiles",
        "orders",
        "products",
        "order_items",
    }
    assert len(full_snapshot.foreign_keys) >= 3

    # Interoperability with to_prisma_schema exporter
    exported_text = to_prisma_schema(tables)
    assert "model Users" in exported_text or "model users" in exported_text
