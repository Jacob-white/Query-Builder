"""
Comprehensive Unit Tests for Schema Exporters (Prisma, Drizzle, SQLAlchemy).
=============================================================================
Verifies code generation accuracy, constraint synthesis, type mapping,
nullability handling, foreign key relationships, dialect variations,
and syntax execution safety.
"""

from __future__ import annotations

import pytest

from query_builder.models import ColumnMeta, ForeignKeyMeta, SchemaSnapshot, TableMeta
from query_builder.schema_converters import (
    _extract_snapshot,
    _to_camel_case,
    _to_pascal_case,
    _to_snake_case,
    to_drizzle_schema,
    to_prisma_schema,
    to_sqlalchemy_models,
)

# ============================================================================
# 1. Identifier Utilities Tests
# ============================================================================


def test_identifier_utilities():
    # PascalCase
    assert _to_pascal_case("users") == "Users"
    assert _to_pascal_case("user_accounts") == "UserAccounts"
    assert _to_pascal_case("firm-master-v2") == "FirmMasterV2"
    assert _to_pascal_case("123_reports") == "Model123Reports"
    assert _to_pascal_case("") == "Model"
    assert _to_pascal_case("   ") == "Model"

    # CamelCase
    assert _to_camel_case("id") == "id"
    assert _to_camel_case("user_id") == "userId"
    assert _to_camel_case("first_name_field") == "firstNameField"
    assert _to_camel_case("123_val") == "col123Val"
    assert _to_camel_case("") == "field"
    assert _to_camel_case("   ") == "field"

    # SnakeCase
    assert _to_snake_case("UserID") == "user_id"
    assert _to_snake_case("UserAccounts") == "user_accounts"
    assert _to_snake_case("firm_master") == "firm_master"
    assert _to_snake_case("123_val") == "col_123_val"
    assert _to_snake_case("") == "col"
    assert _to_snake_case("   ") == "col"


def test_extract_snapshot_type_error():
    with pytest.raises(TypeError, match="Expected SchemaSnapshot or dict"):
        _extract_snapshot("invalid_snapshot")  # type: ignore[arg-type]


def test_extract_snapshot_edge_cases():
    # Table with non-dict/non-TableMeta value, columns as strings, malformed foreign keys
    raw = {
        "tables": {
            "t1": "invalid_table_format",
            "t2": {
                "name": "t2",
                "columns": ["id", "title", 123],
                "comment": "Sample table",
            },
        },
        "foreign_keys": [
            "invalid_fk_entry",
            {"table": "", "column": "a", "foreign_table": "b", "foreign_column": "c"},
        ],
        "relationships": [
            "invalid_rel_entry",
            {
                "source_table": "t2",
                "source_column": "id",
                "target_table": "t1",
                "target_column": "id",
            },
            # Relationship with empty field to hit false branch
            {
                "source_table": "",
                "source_column": "id",
                "target_table": "t1",
                "target_column": "id",
            },
        ],
    }
    tables, fks = _extract_snapshot(raw)
    assert "t1" in tables
    assert len(tables["t1"]["columns"]) == 0
    assert "t2" in tables
    assert len(tables["t2"]["columns"]) == 2
    assert tables["t2"]["columns"][0]["is_primary"] is True
    assert tables["t2"]["columns"][1]["is_primary"] is False
    assert len(fks) == 1
    assert fks[0]["table"] == "t2"

    # raw_tables is not a dict, fks is None, rels is None
    tables_none, fks_none = _extract_snapshot(
        {"tables": None, "foreign_keys": None, "relationships": None}
    )
    assert len(tables_none) == 0
    assert len(fks_none) == 0


def test_prisma_fk_column_not_ending_in_id():
    schema = {
        "tables": {
            "users": {
                "columns": [{"name": "id", "data_type": "int", "is_primary": True}]
            },
            "tasks": {
                "columns": [
                    {"name": "id", "data_type": "int", "is_primary": True},
                    {"name": "assignee", "data_type": "int"},
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "tasks",
                "column": "assignee",
                "foreign_table": "users",
                "foreign_column": "id",
            }
        ],
    }
    out = to_prisma_schema(schema)
    assert "users Users? @relation(fields: [assignee], references: [id])" in out


# ============================================================================
# 2. Prisma Schema Tests
# ============================================================================


def test_prisma_basic_postgres():
    schema = {
        "tables": {
            "users": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "email", "data_type": "text", "is_nullable": False},
                    {"name": "age", "data_type": "integer", "is_nullable": True},
                ]
            }
        }
    }
    out = to_prisma_schema(schema, provider="postgresql")
    assert 'provider = "postgresql"' in out
    assert 'url      = env("DATABASE_URL")' in out
    assert "generator client {" in out
    assert "model Users {" in out
    assert "id Int @id @default(autoincrement())" in out
    assert "email String" in out
    assert "age Int?" in out
    assert '@@map("users")' in out


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("postgresql", "postgresql"),
        ("postgres", "postgresql"),
        ("mysql", "mysql"),
        ("sqlite", "sqlite"),
        ("sqlserver", "sqlserver"),
        ("mssql", "sqlserver"),
        ("cockroachdb", "cockroachdb"),
        ("mongodb", "mongodb"),
    ],
)
def test_prisma_all_providers(provider, expected):
    out = to_prisma_schema({}, provider=provider)
    assert f'provider = "{expected}"' in out


def test_prisma_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported Prisma provider 'oracle_db'"):
        to_prisma_schema({}, provider="oracle_db")


def test_prisma_data_types():
    schema = {
        "tables": {
            "all_types": {
                "columns": [
                    {"name": "c_bigint", "data_type": "bigint"},
                    {"name": "c_bool", "data_type": "boolean"},
                    {"name": "c_float", "data_type": "float"},
                    {"name": "c_decimal", "data_type": "numeric"},
                    {"name": "c_date", "data_type": "timestamptz"},
                    {"name": "c_json", "data_type": "jsonb"},
                    {"name": "c_bytes", "data_type": "bytea"},
                    {"name": "c_unknown", "data_type": "custom_domain"},
                ]
            }
        }
    }
    out = to_prisma_schema(schema)
    assert 'cBigint BigInt? @map("c_bigint")' in out
    assert 'cBool Boolean? @map("c_bool")' in out
    assert 'cFloat Float? @map("c_float")' in out
    assert 'cDecimal Decimal? @map("c_decimal")' in out
    assert 'cDate DateTime? @map("c_date")' in out
    assert 'cJson Json? @map("c_json")' in out
    assert 'cBytes Bytes? @map("c_bytes")' in out
    assert 'cUnknown String? @map("c_unknown")' in out


def test_prisma_foreign_key_relations_single_and_multi():
    schema = {
        "tables": {
            "users": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "name", "data_type": "text"},
                ]
            },
            "posts": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "author_id",
                        "data_type": "int",
                        "is_nullable": True,
                    },
                    {
                        "name": "editor_id",
                        "data_type": "int",
                        "is_nullable": False,
                    },
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "posts",
                "column": "author_id",
                "foreign_table": "users",
                "foreign_column": "id",
            },
            {
                "table": "posts",
                "column": "editor_id",
                "foreign_table": "users",
                "foreign_column": "id",
            },
        ],
    }
    out = to_prisma_schema(schema)
    # Check multi-relation names on posts model
    assert (
        'author Users? @relation("Users_authorId", fields: [authorId], references: [id])'
        in out
    )
    assert (
        'editor Users @relation("Users_editorId", fields: [editorId], references: [id])'
        in out
    )
    # Check back-relations on users model
    assert 'postsByAuthorId Posts[] @relation("Users_authorId")' in out
    assert 'postsByEditorId Posts[] @relation("Users_editorId")' in out


def test_prisma_single_relation_naming_and_collision():
    schema = {
        "tables": {
            "company": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    }
                ]
            },
            "employee": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    # column has name 'company', which would collide with base_rel 'company'
                    {"name": "company", "data_type": "text"},
                    {"name": "company_id", "data_type": "int"},
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "employee",
                "column": "company_id",
                "foreign_table": "company",
                "foreign_column": "id",
            }
        ],
    }
    out = to_prisma_schema(schema)
    assert "companyRel Company? @relation(fields: [companyId], references: [id])" in out
    assert "employees Employee[]" in out


def test_prisma_dataclass_input():
    snapshot = SchemaSnapshot(
        tables={
            "logs": TableMeta(
                name="logs",
                columns=[
                    ColumnMeta(
                        name="id",
                        data_type="serial",
                        is_primary=True,
                        is_nullable=False,
                    ),
                    ColumnMeta(name="msg", data_type="text"),
                ],
            )
        },
        foreign_keys=[],
    )
    out = to_prisma_schema(snapshot)
    assert "model Logs {" in out
    assert "id Int @id @default(autoincrement())" in out
    assert "msg String?" in out


def test_prisma_empty_table_without_columns():
    schema = {"tables": {"empty_table": {"columns": []}}}
    out = to_prisma_schema(schema)
    assert 'model EmptyTable {\n  @@map("empty_table")\n}' in out


# ============================================================================
# 3. Drizzle Schema Tests
# ============================================================================


def test_drizzle_postgres_dialect():
    schema = {
        "tables": {
            "users": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "uuid_str", "data_type": "uuid", "is_primary": True},
                    {"name": "big_num", "data_type": "bigint"},
                    {"name": "counter", "data_type": "int", "is_nullable": False},
                    {"name": "active", "data_type": "boolean"},
                    {"name": "ratio", "data_type": "real"},
                    {"name": "price", "data_type": "numeric"},
                    {"name": "created_at", "data_type": "timestamp"},
                    {"name": "metadata", "data_type": "jsonb"},
                    {"name": "code", "data_type": "varchar(50)"},
                    {"name": "raw_text", "data_type": "text"},
                ]
            }
        }
    }
    out = to_drizzle_schema(schema, dialect="postgres")
    assert 'from "drizzle-orm/pg-core";' in out
    assert 'export const users = pgTable("users", {' in out
    assert 'id: serial("id").primaryKey(),' in out
    assert 'uuidStr: text("uuid_str").primaryKey(),' in out
    assert 'bigNum: bigint("big_num", { mode: "number" }),' in out
    assert 'counter: integer("counter").notNull(),' in out
    assert 'active: boolean("active"),' in out
    assert 'ratio: doublePrecision("ratio"),' in out
    assert 'price: numeric("price"),' in out
    assert 'createdAt: timestamp("created_at"),' in out
    assert 'metadata: jsonb("metadata"),' in out
    assert 'code: varchar("code", { length: 255 }),' in out
    assert 'rawText: text("raw_text"),' in out


def test_drizzle_mysql_dialect():
    schema = {
        "tables": {
            "accounts": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "uuid_key", "data_type": "varchar", "is_primary": True},
                    {"name": "balance", "data_type": "decimal"},
                    {"name": "factor", "data_type": "double"},
                    {"name": "props", "data_type": "json"},
                    {"name": "count", "data_type": "bigint"},
                    {"name": "updated_at", "data_type": "datetime"},
                ]
            }
        }
    }
    out = to_drizzle_schema(schema, dialect="mysql")
    assert 'from "drizzle-orm/mysql-core";' in out
    assert 'export const accounts = mysqlTable("accounts", {' in out
    assert 'id: serial("id").primaryKey(),' in out
    assert 'uuidKey: varchar("uuid_key", { length: 255 }).primaryKey(),' in out
    assert 'balance: decimal("balance", { precision: 10, scale: 2 }),' in out
    assert 'factor: double("factor"),' in out
    assert 'props: json("props"),' in out
    assert 'count: bigint("count", { mode: "number" }),' in out
    assert 'updatedAt: timestamp("updated_at"),' in out


def test_drizzle_sqlite_dialect():
    schema = {
        "tables": {
            "items": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "uid", "data_type": "text", "is_primary": True},
                    {"name": "score", "data_type": "float"},
                    {"name": "is_done", "data_type": "bool"},
                    {"name": "avatar", "data_type": "blob"},
                    {"name": "data", "data_type": "json"},
                ]
            }
        }
    }
    out = to_drizzle_schema(schema, dialect="sqlite")
    assert 'from "drizzle-orm/sqlite-core";' in out
    assert 'export const items = sqliteTable("items", {' in out
    assert 'id: integer("id").primaryKey({ autoIncrement: true }),' in out
    assert 'uid: text("uid").primaryKey(),' in out
    assert 'score: real("score"),' in out
    assert 'isDone: integer("is_done", { mode: "boolean" }),' in out
    assert 'avatar: blob("avatar"),' in out
    assert 'data: text("data"),' in out


def test_drizzle_foreign_keys_and_not_null():
    schema = {
        "tables": {
            "users": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    }
                ]
            },
            "orders": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "user_id",
                        "data_type": "int",
                        "is_nullable": False,
                    },
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "orders",
                "column": "user_id",
                "foreign_table": "users",
                "foreign_column": "id",
            }
        ],
    }
    out = to_drizzle_schema(schema, dialect="postgres")
    assert 'userId: integer("user_id").references(() => users.id).notNull(),' in out


def test_drizzle_empty_table_and_empty_schema():
    out_empty = to_drizzle_schema({})
    assert 'from "drizzle-orm/pg-core";' in out_empty

    schema = {"tables": {"empty": {"columns": []}}}
    out_tbl = to_drizzle_schema(schema, dialect="sqlite")
    assert 'export const empty = sqliteTable("empty", {});' in out_tbl


def test_drizzle_unsupported_dialect():
    with pytest.raises(ValueError, match="Unsupported Drizzle dialect 'oracle'"):
        to_drizzle_schema({}, dialect="oracle")


def test_drizzle_alias_postgresql():
    out = to_drizzle_schema({}, dialect="postgresql")
    assert 'from "drizzle-orm/pg-core";' in out


# ============================================================================
# 4. SQLAlchemy Models Tests
# ============================================================================


def test_sqlalchemy_models_declarative_base_and_compilation():
    schema = {
        "tables": {
            "users": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "username", "data_type": "varchar", "is_nullable": False},
                    {"name": "is_active", "data_type": "boolean", "is_nullable": True},
                    {"name": "score", "data_type": "float"},
                    {"name": "balance", "data_type": "numeric"},
                    {"name": "created_at", "data_type": "timestamp"},
                    {"name": "bio", "data_type": "text"},
                ],
                "comment": "System registered users.",
            },
            "orders": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "user_id", "data_type": "integer", "is_nullable": False},
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "orders",
                "column": "user_id",
                "foreign_table": "users",
                "foreign_column": "id",
            }
        ],
    }

    code = to_sqlalchemy_models(schema)
    assert "Base = declarative_base()" in code
    assert "class Users(Base):" in code
    assert '"""System registered users."""' in code
    assert '__tablename__ = "users"' in code
    assert "id = Column(Integer, primary_key=True, nullable=False)" in code
    assert "username = Column(String, primary_key=False, nullable=False)" in code
    assert "isActive = Column(Boolean, primary_key=False, nullable=True)" not in code
    assert "is_active = Column(Boolean, primary_key=False, nullable=True)" in code
    assert "score = Column(Float, primary_key=False, nullable=True)" in code
    assert "balance = Column(Numeric, primary_key=False, nullable=True)" in code
    assert "created_at = Column(DateTime, primary_key=False, nullable=True)" in code
    assert "bio = Column(Text, primary_key=False, nullable=True)" in code

    assert "class Orders(Base):" in code
    assert (
        'user_id = Column(Integer, ForeignKey("users.id"), primary_key=False, nullable=False)'
        in code
    )
    assert 'user = relationship("Users", foreign_keys=[user_id])' in code

    # Execute Python compile and exec to ensure 100% syntactically valid code
    compiled = compile(code, "<test_sqlalchemy_models>", "exec")
    local_scope: dict = {}
    exec(compiled, local_scope)  # noqa: S102
    assert "Base" in local_scope
    assert "Users" in local_scope
    assert "Orders" in local_scope


def test_sqlalchemy_models_relationship_naming_variations():
    schema = {
        "tables": {
            "parent": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    }
                ]
            },
            "child": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    # column 'parent' collides with rel name 'parent'
                    {"name": "parent", "data_type": "text"},
                    {"name": "parent_ref_id", "data_type": "int"},
                    {"name": "custom_fk", "data_type": "int"},
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "child",
                "column": "parent_ref_id",
                "foreign_table": "parent",
                "foreign_column": "id",
            },
            {
                "table": "child",
                "column": "custom_fk",
                "foreign_table": "parent",
                "foreign_column": "id",
            },
        ],
    }

    code = to_sqlalchemy_models(schema)
    assert 'parent_ref = relationship("Parent", foreign_keys=[parent_ref_id])' in code
    assert 'parent_rel = relationship("Parent", foreign_keys=[custom_fk])' in code

    compiled = compile(code, "<test_naming>", "exec")
    exec(compiled, {})  # noqa: S102


def test_sqlalchemy_models_empty_tables_and_dataclass_input():
    # Empty schema
    empty_code = to_sqlalchemy_models({})
    assert "Base = declarative_base()" in empty_code

    # Table with no columns
    schema_empty_table = {"tables": {"empty_tbl": {"columns": []}}}
    code_empty_tbl = to_sqlalchemy_models(schema_empty_table)
    assert "class EmptyTbl(Base):" in code_empty_tbl
    assert "    pass" in code_empty_tbl
    compile(code_empty_tbl, "<empty_tbl>", "exec")

    # SchemaSnapshot dataclass
    snapshot = SchemaSnapshot(
        tables={
            "logs": TableMeta(
                name="logs",
                columns=[
                    ColumnMeta(
                        name="id",
                        data_type="bigserial",
                        is_primary=True,
                        is_nullable=False,
                    ),
                    ColumnMeta(name="payload", data_type="json"),
                ],
            )
        },
        foreign_keys=[
            ForeignKeyMeta(
                table="logs",
                column="id",
                foreign_table="logs",
                foreign_column="id",
            )
        ],
    )
    code_ds = to_sqlalchemy_models(snapshot)
    assert "class Logs(Base):" in code_ds
    assert (
        'id = Column(Integer, ForeignKey("logs.id"), primary_key=True, nullable=False)'
        in code_ds
    )
    assert "payload = Column(Text, primary_key=False, nullable=True)" in code_ds
    exec(compile(code_ds, "<snapshot>", "exec"), {})  # noqa: S102


def test_schema_converters_branch_coverage_exhaustion():
    # 1. Prisma: table name matching model name with 0 columns -> model User {}
    schema_empty_named = {"tables": {"User": {"columns": []}}}
    prisma_out = to_prisma_schema(schema_empty_named)
    assert "model User {\n}" in prisma_out

    # 2. Prisma: fk with userId (ends with id without underscore), and fk with owner (no id)
    # Also test back-relation collision: target model already has field named "authors"
    schema_fks = {
        "tables": {
            "User": {
                "columns": [
                    {"name": "id", "data_type": "text", "is_primary": True},
                    {"name": "authors", "data_type": "text"},
                ]
            },
            "author": {
                "columns": [
                    {"name": "id", "data_type": "int", "is_primary": True},
                    {"name": "user", "data_type": "text"},
                    {"name": "userId", "data_type": "text"},
                    {"name": "owner", "data_type": "text"},
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "author",
                "column": "userId",
                "foreign_table": "User",
                "foreign_column": "id",
            },
            # FK pointing to external table not in snapshot
            {
                "table": "author",
                "column": "external_id",
                "foreign_table": "external_tbl",
                "foreign_column": "id",
            },
        ],
    }
    prisma_fks = to_prisma_schema(schema_fks)
    assert "userRel User? @relation(" in prisma_fks
    # Check back-relation collision with scalar field "authors"
    assert "authorsRel Author[]" in prisma_fks

    # 3. Drizzle: MySQL with int, boolean, datetime, json, fallback; SQLite with fallback text
    schema_drizzle_types = {
        "tables": {
            "t_mysql": {
                "columns": [
                    {"name": "id", "data_type": "int", "is_primary": True},
                    {"name": "c_int", "data_type": "integer"},
                    {"name": "c_bool", "data_type": "boolean"},
                    {"name": "c_time", "data_type": "datetime"},
                    {"name": "c_json", "data_type": "json"},
                    {"name": "c_custom", "data_type": "geometry"},
                ]
            },
            "t_sqlite": {
                "columns": [
                    {"name": "id", "data_type": "int", "is_primary": True},
                    {"name": "c_custom", "data_type": "unknown_type"},
                ]
            },
        }
    }
    drizzle_mysql = to_drizzle_schema(schema_drizzle_types, dialect="mysql")
    assert 'cInt: int("c_int")' in drizzle_mysql
    assert 'cBool: boolean("c_bool")' in drizzle_mysql
    assert 'cTime: timestamp("c_time")' in drizzle_mysql
    assert 'cJson: json("c_json")' in drizzle_mysql
    assert 'cCustom: varchar("c_custom", { length: 255 })' in drizzle_mysql

    drizzle_sqlite = to_drizzle_schema(schema_drizzle_types, dialect="sqlite")
    assert 'cCustom: text("c_custom")' in drizzle_sqlite

    # 4. SQLAlchemy: FK columns ending in "id" without underscore and not ending in "id"
    # Also foreign key where table is not in snapshot
    schema_sa_fks = {
        "tables": {
            "users": {
                "columns": [{"name": "id", "data_type": "int", "is_primary": True}]
            },
            "items": {
                "columns": [
                    {"name": "id", "data_type": "int", "is_primary": True},
                    {"name": "userid", "data_type": "int"},
                    {"name": "supervisor", "data_type": "int"},
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "items",
                "column": "userid",
                "foreign_table": "users",
                "foreign_column": "id",
            },
            {
                "table": "items",
                "column": "supervisor",
                "foreign_table": "users",
                "foreign_column": "id",
            },
            {
                "table": "ghost_table",
                "column": "ghost_col",
                "foreign_table": "users",
                "foreign_column": "id",
            },
        ],
    }
    sa_code = to_sqlalchemy_models(schema_sa_fks)
    assert 'user = relationship("Users", foreign_keys=[userid])' in sa_code
    assert 'users = relationship("Users", foreign_keys=[supervisor])' in sa_code
    exec(compile(sa_code, "<sa_code>", "exec"), {})  # noqa: S102
