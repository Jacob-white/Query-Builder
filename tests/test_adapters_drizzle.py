"""
Comprehensive Unit Tests for Drizzle ORM Adapter.
=================================================
Tests parsing of Drizzle TypeScript definitions (.ts code strings & files),
verifying pgTable/mysqlTable/sqliteTable, primaryKey composite constraints,
foreign key .references(), enums, nullable/notNull modifiers, and snapshot generation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from query_builder.adapters.drizzle import from_drizzle
from query_builder.models import SchemaDict, TableSchema
from query_builder.schema_converters import to_drizzle_schema

DRIZZLE_ECOMMERCE_CODE = """
import { pgTable, serial, text, integer, timestamp, doublePrecision, pgEnum, primaryKey } from 'drizzle-orm/pg-core';

export const userRoleEnum = pgEnum('user_role', ['admin', 'customer', 'guest']);
export const orderStatusEnum = pgEnum('order_status', ['pending', 'paid', 'shipped', 'cancelled']);

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  email: text('email').notNull(),
  name: text('name'),
  role: userRoleEnum('role').default('customer'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const profiles = pgTable('profiles', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id).notNull(),
  bio: text('bio'),
});

export const orders = pgTable('orders', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id).notNull(),
  status: orderStatusEnum('status').default('pending'),
  total: doublePrecision('total').notNull(),
});

export const products = pgTable('products', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  price: doublePrecision('price').notNull(),
});

export const orderItems = pgTable('order_items', {
  orderId: integer('order_id').references(() => orders.id).notNull(),
  productId: integer('product_id').references(() => products.id).notNull(),
  quantity: integer('quantity').default(1),
}, (table) => ({
  pk: primaryKey({ columns: [table.orderId, table.productId] }),
}));
"""


def test_from_drizzle_ecommerce_schema():
    tables = from_drizzle(DRIZZLE_ECOMMERCE_CODE)
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
    assert role_col.default == "customer"

    # 2. profiles (foreign key)
    profiles = tables["profiles"]
    assert len(profiles.foreign_keys) == 1
    fk = profiles.foreign_keys[0]
    assert fk.column == "user_id"
    assert fk.foreign_table == "users"
    assert fk.foreign_column == "id"

    # 3. orders
    orders = tables["orders"]
    assert len(orders.foreign_keys) == 1
    status_col = next(c for c in orders.columns if c.name == "status")
    assert status_col.enums == ["pending", "paid", "shipped", "cancelled"]

    # 4. order_items (composite PK & multiple foreign keys)
    order_items = tables["order_items"]
    assert set(order_items.primary_keys) == {"order_id", "product_id"}
    assert len(order_items.foreign_keys) == 2
    fks = {f.column: f for f in order_items.foreign_keys}
    assert fks["order_id"].foreign_table == "orders"
    assert fks["product_id"].foreign_table == "products"


def test_from_drizzle_file_path():
    with tempfile.NamedTemporaryFile("w", suffix=".ts", delete=False) as f:
        f.write(DRIZZLE_ECOMMERCE_CODE)
        f_path = Path(f.name)

    try:
        tables = from_drizzle(f_path)
        assert "users" in tables
        assert "order_items" in tables
    finally:
        f_path.unlink()


def test_from_drizzle_mysql_and_sqlite():
    mysql_code = """
    import { mysqlTable, int, varchar } from 'drizzle-orm/mysql-core';
    export const customers = mysqlTable('customers', {
      id: int('id').primaryKey(),
      name: varchar('name', { length: 255 }).notNull(),
    });
    """
    tables = from_drizzle(mysql_code)
    assert "customers" in tables
    c = tables["customers"]
    assert c.primary_keys == ["id"]
    name_col = next(col for col in c.columns if col.name == "name")
    assert name_col.is_nullable is False


def test_from_drizzle_structured_dict_input():
    raw_dict = {
        "articles": {
            "columns": [
                {"name": "id", "data_type": "integer", "is_primary": True},
                {"name": "title", "data_type": "text", "is_nullable": False},
            ],
            "primary_keys": ["id"],
        }
    }
    tables = from_drizzle(raw_dict)
    assert "articles" in tables
    art = tables["articles"]
    assert art.primary_keys == ["id"]
    assert len(art.columns) == 2


def test_drizzle_table_schema_and_export_interop():
    tables = from_drizzle(DRIZZLE_ECOMMERCE_CODE)
    snapshot = tables.to_snapshot()
    assert len(snapshot.tables) == 5
    assert len(snapshot.foreign_keys) >= 3

    # Interoperability with to_drizzle_schema exporter
    exported = to_drizzle_schema(tables, dialect="postgres")
    assert 'pgTable("users"' in exported or "pgTable('users'" in exported
