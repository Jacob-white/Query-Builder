"""
Comprehensive Unit Tests for SQLAlchemy Adapter.
================================================
Tests dual-mode reflection:
1. Zero-dependency AST parsing of Python source code (SQLAlchemy 1.4 & 2.0).
2. Live reflection of MetaData / Table objects.
Verifies single/composite primary keys, foreign keys, enums, and nullability.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from query_builder.adapters.sqlalchemy import from_sqlalchemy
from query_builder.models import SchemaDict, TableSchema
from query_builder.schema_converters import to_sqlalchemy_models

SQLALCHEMY_ECOMMERCE_CODE = """
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Enum, PrimaryKeyConstraint
from sqlalchemy.orm import declarative_base, Mapped, mapped_column

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    name = Column(String(100), nullable=True)
    role = Column(Enum('admin', 'customer', 'guest', name='user_role'), default='customer')

class Profile(Base):
    __tablename__ = 'profiles'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    bio = Column(String, nullable=True)

class Order(Base):
    __tablename__ = 'orders'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(Enum('pending', 'paid', 'shipped', 'cancelled', name='order_status'), default='pending')
    total = Column(Float, nullable=False)

class Product(Base):
    __tablename__ = 'products'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)

class OrderItem(Base):
    __tablename__ = 'order_items'
    __table_args__ = (PrimaryKeyConstraint('order_id', 'product_id'),)

    order_id = Column(Integer, ForeignKey('orders.id'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), primary_key=True)
    quantity = Column(Integer, default=1)
"""

SQLALCHEMY_20_CODE = """
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import ForeignKey, String

class Base(DeclarativeBase):
    pass

class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(nullable=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
"""


def test_from_sqlalchemy_ast_ecommerce_schema():
    tables = from_sqlalchemy(SQLALCHEMY_ECOMMERCE_CODE)
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
    assert id_col.data_type == "integer"
    assert id_col.is_nullable is False

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
    status_col = next(c for c in orders.columns if c.name == "status")
    assert status_col.enums == ["pending", "paid", "shipped", "cancelled"]

    # 4. order_items (composite primary key & 2 foreign keys)
    order_items = tables["order_items"]
    assert set(order_items.primary_keys) == {"order_id", "product_id"}
    assert len(order_items.foreign_keys) == 2


def test_from_sqlalchemy_20_mapped_column_ast():
    tables = from_sqlalchemy(SQLALCHEMY_20_CODE)
    assert "posts" in tables
    post = tables["posts"]
    assert post.primary_keys == ["id"]
    id_col = next(c for c in post.columns if c.name == "id")
    assert id_col.is_primary is True
    assert id_col.data_type == "integer"

    title_col = next(c for c in post.columns if c.name == "title")
    assert title_col.is_nullable is False
    assert title_col.data_type == "text"

    content_col = next(c for c in post.columns if c.name == "content")
    assert content_col.is_nullable is True

    assert len(post.foreign_keys) == 1
    assert post.foreign_keys[0].foreign_table == "users"
    assert post.foreign_keys[0].foreign_column == "id"


def test_from_sqlalchemy_file_path():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(SQLALCHEMY_ECOMMERCE_CODE)
        f_path = Path(f.name)

    try:
        tables = from_sqlalchemy(f_path)
        assert "users" in tables
        assert "order_items" in tables
    finally:
        f_path.unlink()


def test_from_sqlalchemy_live_mock_objects():
    # Verify live reflection path using duck-typed Column & Table objects
    class MockColumn:
        def __init__(
            self, name, type_name, primary_key=False, nullable=True, foreign_keys=None
        ):
            self.name = name
            self.type = type(type_name, (), {})()
            self.primary_key = primary_key
            self.nullable = nullable
            self.default = None
            self.comment = None
            self.foreign_keys = foreign_keys or []

    class MockTable:
        def __init__(self, name, columns, schema="public"):
            self.name = name
            self.columns = columns
            self.schema = schema
            self.comment = None

    class MockMetaData:
        def __init__(self, tables):
            self.tables = {t.name: t for t in tables}

    t_users = MockTable(
        "users",
        [
            MockColumn("id", "Integer", primary_key=True, nullable=False),
            MockColumn("email", "String", nullable=False),
        ],
    )

    class MockForeignKey:
        def __init__(self, target_table_name, target_col_name):
            self.column = type(
                "Col",
                (),
                {
                    "name": target_col_name,
                    "table": type("Tbl", (), {"name": target_table_name})(),
                },
            )()

    t_orders = MockTable(
        "orders",
        [
            MockColumn("id", "Integer", primary_key=True, nullable=False),
            MockColumn(
                "user_id", "Integer", foreign_keys=[MockForeignKey("users", "id")]
            ),
        ],
    )

    meta = MockMetaData([t_users, t_orders])
    tables = from_sqlalchemy(meta)

    assert "users" in tables
    assert "orders" in tables
    orders = tables["orders"]
    assert len(orders.foreign_keys) == 1
    assert orders.foreign_keys[0].foreign_table == "users"


def test_sqlalchemy_table_schema_export_interop():
    tables = from_sqlalchemy(SQLALCHEMY_ECOMMERCE_CODE)
    snapshot = tables.to_snapshot()
    assert len(snapshot.tables) == 5

    exported_code = to_sqlalchemy_models(tables)
    assert "class User(" in exported_code or "class Users(" in exported_code
