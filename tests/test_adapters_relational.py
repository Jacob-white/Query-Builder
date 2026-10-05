"""
Comprehensive Multi-Table Relational Schema Integration Tests.
=============================================================
Verifies multi-table relational schema invariants across all 4 adapters:
Prisma, Drizzle, SQLAlchemy, and JSON Schema.
Ensures join discovery, compiler query execution, and schema snapshot
interoperability work seamlessly with adapted schemas.
"""

from __future__ import annotations

from query_builder.adapters import (
    from_drizzle,
    from_json_schema,
    from_prisma,
    from_sqlalchemy,
)
from query_builder.compiler import QueryCompiler
from query_builder.join_solver import find_best_join_condition, find_join_path
from query_builder.models import QuerySpec

PRISMA_ECOMMERCE = """
enum Role {
  admin
  customer
  guest
}

model User {
  id    Int    @id @default(autoincrement())
  email String
  role  Role   @default(customer)
  orders Order[]
  @@map("users")
}

model Order {
  id     Int         @id @default(autoincrement())
  userId Int
  user   User        @relation(fields: [userId], references: [id])
  items  OrderItem[]
  @@map("orders")
}

model Product {
  id    Int         @id @default(autoincrement())
  name  String
  items OrderItem[]
  @@map("products")
}

model OrderItem {
  orderId   Int
  productId Int
  order     Order   @relation(fields: [orderId], references: [id])
  product   Product @relation(fields: [productId], references: [id])
  @@id([orderId, productId])
  @@map("order_items")
}
"""

DRIZZLE_ECOMMERCE = """
import { pgTable, serial, integer, text, pgEnum, primaryKey } from 'drizzle-orm/pg-core';

export const roleEnum = pgEnum('role', ['admin', 'customer', 'guest']);

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  email: text('email').notNull(),
  role: roleEnum('role').default('customer'),
});

export const orders = pgTable('orders', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id).notNull(),
});

export const products = pgTable('products', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
});

export const orderItems = pgTable('order_items', {
  orderId: integer('order_id').references(() => orders.id).notNull(),
  productId: integer('product_id').references(() => products.id).notNull(),
}, (table) => ({
  pk: primaryKey({ columns: [table.orderId, table.productId] }),
}));
"""

SQLALCHEMY_ECOMMERCE = """
from sqlalchemy import Column, Integer, String, ForeignKey, Enum, PrimaryKeyConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    role = Column(Enum('admin', 'customer', 'guest', name='role'), default='customer')

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

class OrderItem(Base):
    __tablename__ = 'order_items'
    __table_args__ = (PrimaryKeyConstraint('order_id', 'product_id'),)
    order_id = Column(Integer, ForeignKey('orders.id'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), primary_key=True)
"""

JSON_SCHEMA_ECOMMERCE = {
    "components": {
        "schemas": {
            "users": {
                "type": "object",
                "required": ["id", "email"],
                "properties": {
                    "id": {"type": "integer", "x-primary-key": True},
                    "email": {"type": "string"},
                    "role": {"type": "string", "enum": ["admin", "customer", "guest"]},
                },
            },
            "orders": {
                "type": "object",
                "required": ["id", "user_id"],
                "properties": {
                    "id": {"type": "integer", "x-primary-key": True},
                    "user_id": {"type": "integer", "x-foreign-key": "users.id"},
                },
            },
            "products": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "integer", "x-primary-key": True},
                    "name": {"type": "string"},
                },
            },
            "order_items": {
                "type": "object",
                "x-primary-keys": ["order_id", "product_id"],
                "required": ["order_id", "product_id"],
                "properties": {
                    "order_id": {"type": "integer", "x-foreign-key": "orders.id"},
                    "product_id": {"type": "integer", "x-foreign-key": "products.id"},
                },
            },
        }
    }
}


def test_cross_adapter_schema_structural_conformance():
    """Verifies that all 4 adapters parse relational entities into consistent shapes."""
    prisma_tables = from_prisma(PRISMA_ECOMMERCE)
    drizzle_tables = from_drizzle(DRIZZLE_ECOMMERCE)
    sa_tables = from_sqlalchemy(SQLALCHEMY_ECOMMERCE)
    json_tables = from_json_schema(JSON_SCHEMA_ECOMMERCE)

    all_adapters = [prisma_tables, drizzle_tables, sa_tables, json_tables]

    for adapter_tables in all_adapters:
        # Table set
        assert set(adapter_tables.keys()) == {
            "users",
            "orders",
            "products",
            "order_items",
        }

        # users has 'id' PK
        assert "id" in adapter_tables["users"].primary_keys
        # order_items has composite PK
        assert len(adapter_tables["order_items"].primary_keys) == 2

        # orders references users
        assert any(
            fk.foreign_table == "users" for fk in adapter_tables["orders"].foreign_keys
        )

        # order_items references orders and products
        assert any(
            fk.foreign_table == "orders"
            for fk in adapter_tables["order_items"].foreign_keys
        )
        assert any(
            fk.foreign_table == "products"
            for fk in adapter_tables["order_items"].foreign_keys
        )


def test_join_solver_path_discovery_with_adapted_schemas():
    """Ensures join solver automatically discovers foreign key bridges from adapted snapshots."""
    drizzle_tables = from_drizzle(DRIZZLE_ECOMMERCE)
    snapshot = drizzle_tables.to_snapshot()

    # Find join condition between users and orders
    cond = find_best_join_condition("users", "orders", snapshot)
    assert cond is not None
    assert (
        cond["left_table"] == "users"
        and cond["left_col"] == "id"
        and cond["right_table"] == "orders"
        and cond["right_col"] == "user_id"
    ) or (
        cond["left_table"] == "orders"
        and cond["left_col"] == "user_id"
        and cond["right_table"] == "users"
        and cond["right_col"] == "id"
    )

    # Find multi-hop path: users -> orders -> order_items -> products
    path = find_join_path(["users"], "products", snapshot)
    assert path is not None
    assert len(path) == 3  # users -> orders -> order_items -> products


def test_query_compiler_with_adapted_schema_joins():
    """Verifies query compiler successfully compiles a query using adapted schema metadata."""
    sa_tables = from_sqlalchemy(SQLALCHEMY_ECOMMERCE)
    snapshot = sa_tables.to_snapshot()

    spec = QuerySpec(
        table="users",
        columns=["users.id", "users.email", "orders.id"],
        joins=[
            {
                "table": "orders",
                "type": "INNER",
                "on": [{"left": "users.id", "right": "orders.user_id"}],
            }
        ],
        filters=[{"column": "users.role", "op": "eq", "value": "customer"}],
    )
    compiler = QueryCompiler(spec, schema=snapshot, dialect="postgres")

    sql, _, _, _ = compiler.compile()
    assert "SELECT" in sql
    assert "users" in sql
    assert "orders" in sql
    assert "JOIN" in sql


def test_table_schema_get_column():
    """Verifies get_column case-insensitive lookup on TableSchema."""
    sa_tables = from_sqlalchemy(SQLALCHEMY_ECOMMERCE)
    users_table = sa_tables["users"]

    col = users_table.get_column("email")
    assert col is not None
    assert col.name == "email"

    # Case-insensitive
    col_upper = users_table.get_column("EMAIL")
    assert col_upper is not None
    assert col_upper.name == "email"

    # Non-existent
    assert users_table.get_column("nonexistent") is None


def test_foreign_key_constraint_name():
    """Verifies ForeignKey accepts optional constraint_name and serializes properly."""
    from query_builder.models import ForeignKey

    fk_without = ForeignKey("orders", "user_id", "users", "id")
    assert fk_without.constraint_name is None
    d_without = fk_without.to_dict()
    assert "constraint_name" not in d_without
    assert d_without["column"] == "user_id"

    fk_with = ForeignKey(
        "orders", "user_id", "users", "id", constraint_name="fk_orders_user_id"
    )
    assert fk_with.constraint_name == "fk_orders_user_id"
    d_with = fk_with.to_dict()
    assert d_with["constraint_name"] == "fk_orders_user_id"

    fk_meta = fk_with.to_foreign_key_meta()
    assert fk_meta.table == "orders"
    assert fk_meta.column == "user_id"
    assert fk_meta.foreign_table == "users"
    assert fk_meta.foreign_column == "id"
