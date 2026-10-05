"""
E-Commerce Relational Database Schema & Seeder for Fullstack Starter.
=====================================================================
Provides multi-table SQLite schema (categories, products, users, orders, order_items),
sample data seeding, connection helpers, and schema snapshot generation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from query_builder.adapters import to_schema_snapshot
from query_builder.models import (
    ColumnSchema,
    ForeignKey,
    SchemaSnapshot,
    TableSchema,
)

DEFAULT_DB_PATH = Path(__file__).parent / "starter.db"

SCHEMA_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    stock_quantity INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('IN_STOCK', 'LOW_STOCK', 'OUT_OF_STOCK')),
    description TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('ADMIN', 'CUSTOMER', 'GUEST')),
    created_at TEXT NOT NULL,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'COMPLETED', 'CANCELLED')),
    total_amount REAL NOT NULL,
    shipping_address TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL,
    discount REAL DEFAULT 0.0
);
"""

SEED_DATA_SQL = """
-- Categories
INSERT OR IGNORE INTO categories (id, name, slug, description, is_active) VALUES
(1, 'Electronics', 'electronics', 'Gadgets, devices, and computing accessories', 1),
(2, 'Apparel', 'apparel', 'Quality clothing, footwear, and accessories', 1),
(3, 'Home & Kitchen', 'home-kitchen', 'Cookware, appliances, and home decor', 1),
(4, 'Books & Media', 'books-media', 'Fiction, non-fiction, and digital media', 1);

-- Products
INSERT OR IGNORE INTO products (id, category_id, name, price, stock_quantity, status, description) VALUES
(1, 1, 'ProBook 16 Laptop', 1299.99, 25, 'IN_STOCK', 'High performance laptop with 32GB RAM'),
(2, 1, 'Noise-Cancelling Headphones', 249.50, 8, 'LOW_STOCK', 'Wireless over-ear headphones with ANC'),
(3, 1, 'Ergonomic Mechanical Keyboard', 129.00, 42, 'IN_STOCK', 'RGB mechanical keyboard with brown switches'),
(4, 2, 'Merino Wool Hoodie', 89.95, 30, 'IN_STOCK', 'Ultra-soft breathable merino wool pullover'),
(5, 2, 'Waterproof Trail Running Shoes', 145.00, 4, 'LOW_STOCK', 'All-weather trail shoes with vibram soles'),
(6, 3, 'Cast Iron Dutch Oven 6-Qt', 79.99, 0, 'OUT_OF_STOCK', 'Enameled heavy duty Dutch oven'),
(7, 3, 'Smart Temperature Mug', 119.50, 15, 'IN_STOCK', 'App-controlled heated coffee mug'),
(8, 4, 'Designing Data-Intensive Applications', 45.00, 50, 'IN_STOCK', 'The definitive guide to distributed data systems');

-- Users
INSERT OR IGNORE INTO users (id, email, full_name, role, created_at, last_login) VALUES
(1, 'alice.admin@example.com', 'Alice Admin', 'ADMIN', '2026-01-10 09:00:00', '2026-10-04 18:30:00'),
(2, 'bob.builder@example.com', 'Bob Builder', 'CUSTOMER', '2026-02-15 11:20:00', '2026-10-05 10:15:00'),
(3, 'charlie.chen@example.com', 'Charlie Chen', 'CUSTOMER', '2026-03-22 14:45:00', '2026-10-03 12:00:00'),
(4, 'diana.prince@example.com', 'Diana Prince', 'CUSTOMER', '2026-04-05 16:10:00', '2026-09-28 08:45:00'),
(5, 'guest.shopper@example.com', 'Guest Shopper', 'GUEST', '2026-05-01 20:00:00', NULL);

-- Orders
INSERT OR IGNORE INTO orders (id, user_id, status, total_amount, shipping_address, created_at) VALUES
(1, 2, 'COMPLETED', 1428.99, '742 Evergreen Terrace, Springfield, OR', '2026-09-15 14:22:00'),
(2, 2, 'COMPLETED', 119.50, '742 Evergreen Terrace, Springfield, OR', '2026-09-29 16:40:00'),
(3, 3, 'PENDING', 234.95, '221B Baker Street, London, UK', '2026-10-04 11:05:00'),
(4, 4, 'COMPLETED', 1344.99, '350 Fifth Ave, New York, NY', '2026-10-01 09:12:00'),
(5, 4, 'CANCELLED', 79.99, '350 Fifth Ave, New York, NY', '2026-10-02 15:30:00');

-- Order Items
INSERT OR IGNORE INTO order_items (id, order_id, product_id, quantity, unit_price, discount) VALUES
(1, 1, 1, 1, 1299.99, 0.0),
(2, 1, 3, 1, 129.00, 0.0),
(3, 2, 7, 1, 119.50, 0.0),
(4, 3, 4, 1, 89.95, 0.0),
(5, 3, 5, 1, 145.00, 0.0),
(6, 4, 1, 1, 1299.99, 0.0),
(7, 4, 8, 1, 45.00, 0.0),
(8, 5, 6, 1, 79.99, 0.0);
"""


def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Returns an active SQLite connection with foreign keys enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_database(
    db_path: str | Path = DEFAULT_DB_PATH, force_recreate: bool = False
) -> sqlite3.Connection:
    """
    Initializes the SQLite schema and seeds realistic demo data.
    If force_recreate is True, removes existing file first.
    """
    path_obj = Path(db_path)
    if force_recreate and path_obj.exists() and str(db_path) != ":memory:":
        path_obj.unlink()

    conn = get_connection(db_path)
    with conn:
        conn.executescript(SCHEMA_DDL)
        conn.executescript(SEED_DATA_SQL)
    return conn


def get_starter_tables() -> dict[str, TableSchema]:
    """Returns structured TableSchema objects for all starter tables."""
    return {
        "categories": TableSchema(
            name="categories",
            columns=[
                ColumnSchema("id", "integer", is_nullable=False, is_primary=True),
                ColumnSchema("name", "text", is_nullable=False),
                ColumnSchema("slug", "text", is_nullable=False),
                ColumnSchema("description", "text", is_nullable=True),
                ColumnSchema("is_active", "integer", is_nullable=False),
            ],
            primary_keys=["id"],
            comment="Product classification categories",
        ),
        "products": TableSchema(
            name="products",
            columns=[
                ColumnSchema("id", "integer", is_nullable=False, is_primary=True),
                ColumnSchema(
                    "category_id",
                    "integer",
                    is_nullable=False,
                    foreign_key=ForeignKey(
                        "products", "category_id", "categories", "id"
                    ),
                ),
                ColumnSchema("name", "text", is_nullable=False),
                ColumnSchema("price", "decimal", is_nullable=False),
                ColumnSchema("stock_quantity", "integer", is_nullable=False),
                ColumnSchema(
                    "status",
                    "text",
                    is_nullable=False,
                    enums=["IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"],
                ),
                ColumnSchema("description", "text", is_nullable=True),
            ],
            primary_keys=["id"],
            foreign_keys=[ForeignKey("products", "category_id", "categories", "id")],
            enums={"status": ["IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"]},
            comment="Inventory products catalogue",
        ),
        "users": TableSchema(
            name="users",
            columns=[
                ColumnSchema("id", "integer", is_nullable=False, is_primary=True),
                ColumnSchema("email", "text", is_nullable=False),
                ColumnSchema("full_name", "text", is_nullable=False),
                ColumnSchema(
                    "role",
                    "text",
                    is_nullable=False,
                    enums=["ADMIN", "CUSTOMER", "GUEST"],
                ),
                ColumnSchema("created_at", "timestamp", is_nullable=False),
                ColumnSchema("last_login", "timestamp", is_nullable=True),
            ],
            primary_keys=["id"],
            enums={"role": ["ADMIN", "CUSTOMER", "GUEST"]},
            comment="System user accounts",
        ),
        "orders": TableSchema(
            name="orders",
            columns=[
                ColumnSchema("id", "integer", is_nullable=False, is_primary=True),
                ColumnSchema(
                    "user_id",
                    "integer",
                    is_nullable=False,
                    foreign_key=ForeignKey("orders", "user_id", "users", "id"),
                ),
                ColumnSchema(
                    "status",
                    "text",
                    is_nullable=False,
                    enums=["PENDING", "COMPLETED", "CANCELLED"],
                ),
                ColumnSchema("total_amount", "decimal", is_nullable=False),
                ColumnSchema("shipping_address", "text", is_nullable=True),
                ColumnSchema("created_at", "timestamp", is_nullable=False),
            ],
            primary_keys=["id"],
            foreign_keys=[ForeignKey("orders", "user_id", "users", "id")],
            enums={"status": ["PENDING", "COMPLETED", "CANCELLED"]},
            comment="Customer purchase orders",
        ),
        "order_items": TableSchema(
            name="order_items",
            columns=[
                ColumnSchema("id", "integer", is_nullable=False, is_primary=True),
                ColumnSchema(
                    "order_id",
                    "integer",
                    is_nullable=False,
                    foreign_key=ForeignKey("order_items", "order_id", "orders", "id"),
                ),
                ColumnSchema(
                    "product_id",
                    "integer",
                    is_nullable=False,
                    foreign_key=ForeignKey(
                        "order_items", "product_id", "products", "id"
                    ),
                ),
                ColumnSchema("quantity", "integer", is_nullable=False),
                ColumnSchema("unit_price", "decimal", is_nullable=False),
                ColumnSchema("discount", "decimal", is_nullable=True),
            ],
            primary_keys=["id"],
            foreign_keys=[
                ForeignKey("order_items", "order_id", "orders", "id"),
                ForeignKey("order_items", "product_id", "products", "id"),
            ],
            comment="Individual line items per order",
        ),
    }


def get_starter_schema_snapshot() -> SchemaSnapshot:
    """Returns a full SchemaSnapshot containing tables, foreign keys, and relationships."""
    tables = get_starter_tables()
    return to_schema_snapshot(tables)


def snapshot_to_dict(snapshot: SchemaSnapshot) -> dict[str, Any]:
    """Converts a SchemaSnapshot into a JSON-serializable dictionary."""
    return {
        "tables": snapshot.tables,
        "foreign_keys": snapshot.foreign_keys,
        "relationships": snapshot.relationships,
        "categories": snapshot.categories,
    }
