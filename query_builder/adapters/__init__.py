"""
Query Builder Schema Interoperability & ORM Adapters.
=====================================================
Declarative adapters converting schemas from Prisma, Drizzle ORM,
SQLAlchemy, and JSON Schema / OpenAPI into Query-Builder TableSchema models.
"""

from __future__ import annotations

from query_builder.adapters.drizzle import from_drizzle
from query_builder.adapters.json_schema import from_json_schema
from query_builder.adapters.prisma import from_prisma
from query_builder.adapters.sqlalchemy import from_sqlalchemy
from query_builder.adapters.utils import to_schema_snapshot
from query_builder.models import (
    ColumnSchema,
    ForeignKey,
    SchemaDict,
    TableSchema,
)

__all__ = [
    "ColumnSchema",
    "ForeignKey",
    "SchemaDict",
    "TableSchema",
    "from_drizzle",
    "from_json_schema",
    "from_prisma",
    "from_sqlalchemy",
    "to_schema_snapshot",
]
