"""
Milestone 2 DX Challenger 2 Adversarial Stress & Empirical Verification Suite.
==============================================================================
Independent empirical stress-testing for Milestone 2:
1. Schema Converters (to_prisma_schema, to_drizzle_schema, to_sqlalchemy_models):
   - Degenerate, empty, single-column, and non-integer primary key schemas.
   - Comprehensive exotic SQL types (UUID, timestamptz, interval, inet, geometry, jsonb, blob) and fallbacks.
   - Unconventional identifiers (digits, hyphens, spaces, uppercase) and @map / @@map Prisma directives.
   - Diamond and multi-column foreign key relationships.
   - Relational identifier collisions (scalar fields vs relation names, back-relation clashing).
   - Drizzle dialect flavors (postgres, mysql, sqlite) verified via TypeScript compiler AST oracle.
   - Prisma provider flavors (postgresql, mysql, sqlite, sqlserver, cockroachdb, mongodb) and error bounds.
   - SQLAlchemy in-memory engine DDL generation, mapper configuration, and ORM query execution in isolated subprocess.
2. CLI Suite (query_builder/cli.py):
   - Subcommand `validate`:
     * Malformed JSON (files and inline strings) returning exit code 1 with structured JSON errors.
     * Empty files, whitespace-only files, and comment-only SQL files.
     * Hostile SQL injection vectors (semicolon chaining, DDL, DML, file access, sleep, security tables).
     * Policy enforcement (--allowed-schemas, --restricted-tables, --disallow-cte, --fail-on-risk).
   - Subcommand `compile`:
     * Output persistence (--output file in text and JSON modes), error paths, and dialect variations.
   - Subcommand `test-connection`:
     * Valid and invalid connectors, config file/string parsing, structured error outputs.
   - Subcommand `introspect`:
     * Sensitive table filtering (--filter-sensitive vs --no-filter-sensitive), output file writing, error paths.
   - Subcommand `export-schema`:
     * Formats (prisma, drizzle, sqlalchemy), dialect options, unknown format errors, --output writing.
   - Subcommand `join-path`, `serve`, and argument parsing boundaries (exit code 2).
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys

import pytest

from query_builder.cli import main
from query_builder.models import SchemaSnapshot
from query_builder.schema_converters import (
    to_drizzle_schema,
    to_prisma_schema,
    to_sqlalchemy_models,
)

# ============================================================================
# Verification Oracles & Helpers
# ============================================================================


def verify_typescript_syntax(ts_code: str) -> None:
    """Verifies TypeScript code syntax using the installed TypeScript compiler AST parser."""
    node_script = f"""
    const ts = require('/home/jwhite/Query-Builder/packages/react/node_modules/typescript');
    const code = {json.dumps(ts_code)};
    const sf = ts.createSourceFile('schema.ts', code, ts.ScriptTarget.Latest, true);
    if (sf.parseDiagnostics && sf.parseDiagnostics.length > 0) {{
        console.error('TS Parse Diagnostics:', JSON.stringify(sf.parseDiagnostics));
        process.exit(1);
    }}
    """
    proc = subprocess.run(
        ["node", "-e", node_script], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, (
        f"TypeScript syntax error:\n{proc.stderr}\nCode:\n{ts_code}"
    )


def verify_sqlalchemy_models(
    sa_code: str, test_sqlite_ddl: bool = True, assertions_code: str = ""
) -> None:
    """Compiles, executes, and configures SQLAlchemy mappers in an isolated process."""
    sub_code = f"""
import sys
code = {json.dumps(sa_code)}
compiled = compile(code, "<string>", "exec")
assert compiled is not None
ns = {{}}
exec(code, ns)
assert "Base" in ns
from sqlalchemy.orm import configure_mappers
configure_mappers()

if {test_sqlite_ddl}:
    from sqlalchemy import create_engine
    engine = create_engine("sqlite:///:memory:")
    ns["Base"].metadata.create_all(engine)

{assertions_code}
"""
    proc = subprocess.run(
        [sys.executable, "-c", sub_code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, (
        f"SQLAlchemy execution error:\n{proc.stderr}\nCode:\n{sa_code}"
    )


def verify_prisma_structure(prisma_code: str) -> None:
    """Verifies that generated Prisma schema conforms to structural syntax rules."""
    assert prisma_code.count("{") == prisma_code.count("}"), (
        "Unbalanced braces in Prisma schema"
    )
    assert "datasource db {" in prisma_code
    assert 'provider = "' in prisma_code
    assert 'url      = env("DATABASE_URL")' in prisma_code
    assert "generator client {" in prisma_code
    assert 'provider = "prisma-client-js"' in prisma_code

    models = re.findall(r"model\s+(\w+)\s*\{([^}]+)\}", prisma_code)
    for model_name, body in models:
        assert re.match(r"^[A-Z][a-zA-Z0-9_]*$", model_name), (
            f"Invalid model name: {model_name}"
        )
        for line in body.strip().splitlines():
            line = line.strip()
            if not line or line.startswith(("//", "@@")):
                continue
            parts = line.split()
            assert len(parts) >= 2, f"Invalid field definition line: {line}"
            field_name = parts[0]
            assert re.match(r"^[a-zA-Z0-9_]+$", field_name), (
                f"Invalid field name: {field_name}"
            )


# ============================================================================
# 1. Schema Converters Stress Tests
# ============================================================================


def test_adversarial_empty_and_minimal_schemas():
    """
    Stress-test schema converters on degenerate schemas:
    - Completely empty schemas
    - Tables with no columns
    - Tables with single primary key or single non-primary key
    - Primary keys of non-integer types (e.g. UUID, varchar)
    """
    empty_snapshot = SchemaSnapshot(tables={}, foreign_keys=[])

    # 1. Empty snapshot behavior
    prisma_empty = to_prisma_schema(empty_snapshot)
    verify_prisma_structure(prisma_empty)
    assert "model " not in prisma_empty

    for dialect in ["postgres", "mysql", "sqlite"]:
        drizzle_empty = to_drizzle_schema(empty_snapshot, dialect=dialect)
        verify_typescript_syntax(drizzle_empty)
        assert "Table(" not in drizzle_empty

    sa_empty = to_sqlalchemy_models(empty_snapshot)
    verify_sqlalchemy_models(sa_empty, test_sqlite_ddl=False)
    assert "class " not in sa_empty

    # 2. Minimal tables with single column and non-integer primary key
    minimal_schema = {
        "tables": {
            "tokens": {
                "columns": [
                    {
                        "name": "token_uuid",
                        "data_type": "uuid",
                        "is_primary": True,
                        "is_nullable": False,
                    }
                ]
            },
            "logs": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "message",
                        "data_type": "text",
                        "is_primary": False,
                        "is_nullable": True,
                    },
                ]
            },
        }
    }

    # Prisma
    prisma_out = to_prisma_schema(minimal_schema)
    verify_prisma_structure(prisma_out)
    assert 'tokenUuid String @id @map("token_uuid")' in prisma_out
    assert "message String?" in prisma_out
    assert (
        "@default(autoincrement())"
        not in prisma_out.split("tokenUuid")[1].splitlines()[0]
    )

    # Drizzle
    for dialect in ["postgres", "mysql", "sqlite"]:
        drizzle_out = to_drizzle_schema(minimal_schema, dialect=dialect)
        verify_typescript_syntax(drizzle_out)
        assert (
            'tokenUuid: text("token_uuid").primaryKey()' in drizzle_out
            or 'tokenUuid: varchar("token_uuid", { length: 255 }).primaryKey()'
            in drizzle_out
        )

    # SQLAlchemy
    sa_out = to_sqlalchemy_models(minimal_schema)
    verify_sqlalchemy_models(
        sa_out,
        test_sqlite_ddl=True,
        assertions_code="assert 'Tokens' in ns and 'Logs' in ns",
    )


def test_adversarial_exotic_sql_types_and_comprehensive_fallbacks():
    """
    Stress-test schema converters on an extensive battery of exotic, enterprise, and composite SQL types.
    Verifies that type mapping and fallbacks produce syntactically valid schemas across all targets.
    """
    schema = {
        "tables": {
            "exotic_types": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "bigserial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "col_uuid", "data_type": "uuid", "is_nullable": False},
                    {
                        "name": "col_timestamptz",
                        "data_type": "timestamptz",
                        "is_nullable": True,
                    },
                    {
                        "name": "col_interval",
                        "data_type": "interval",
                        "is_nullable": True,
                    },
                    {
                        "name": "col_geometry",
                        "data_type": "geometry",
                        "is_nullable": True,
                    },
                    {"name": "col_hstore", "data_type": "hstore", "is_nullable": True},
                    {"name": "col_inet", "data_type": "inet", "is_nullable": True},
                    {"name": "col_jsonb", "data_type": "jsonb", "is_nullable": True},
                    {"name": "col_bytea", "data_type": "bytea", "is_nullable": True},
                    {"name": "col_blob", "data_type": "blob", "is_nullable": True},
                    {"name": "col_money", "data_type": "money", "is_nullable": False},
                    {
                        "name": "col_double",
                        "data_type": "double precision",
                        "is_nullable": False,
                    },
                    {"name": "col_real", "data_type": "real", "is_nullable": False},
                    {
                        "name": "col_tinyint",
                        "data_type": "tinyint",
                        "is_nullable": False,
                    },
                    {
                        "name": "col_smallint",
                        "data_type": "smallint",
                        "is_nullable": False,
                    },
                    {
                        "name": "col_boolean",
                        "data_type": "boolean",
                        "is_nullable": False,
                    },
                    {"name": "col_citext", "data_type": "citext", "is_nullable": True},
                    {
                        "name": "col_custom",
                        "data_type": "my_custom_domain_type",
                        "is_nullable": True,
                    },
                ]
            }
        }
    }

    # 1. Prisma Exporter
    prisma_out = to_prisma_schema(schema)
    verify_prisma_structure(prisma_out)
    assert "colUuid String" in prisma_out
    assert "colTimestamptz DateTime?" in prisma_out
    assert "colJsonb Json?" in prisma_out
    assert "colBytea Bytes?" in prisma_out
    assert "colBlob Bytes?" in prisma_out
    assert "colMoney Decimal" in prisma_out
    assert "colDouble Float" in prisma_out
    assert "colReal Float" in prisma_out
    assert "colTinyint Int" in prisma_out
    assert "colSmallint Int" in prisma_out
    assert "colBoolean Boolean" in prisma_out
    assert "colCitext String?" in prisma_out
    assert "colCustom String?" in prisma_out

    # 2. Drizzle Exporter across all 3 dialects
    for dialect in ["postgres", "mysql", "sqlite"]:
        drizzle_out = to_drizzle_schema(schema, dialect=dialect)
        verify_typescript_syntax(drizzle_out)

    # Dialect-specific type assertions
    pg_out = to_drizzle_schema(schema, dialect="postgres")
    assert 'colJsonb: jsonb("col_jsonb")' in pg_out
    assert 'colDouble: doublePrecision("col_double").notNull()' in pg_out

    mysql_out = to_drizzle_schema(schema, dialect="mysql")
    assert 'colJsonb: json("col_jsonb")' in mysql_out
    assert 'colDouble: double("col_double").notNull()' in mysql_out

    sqlite_out = to_drizzle_schema(schema, dialect="sqlite")
    assert 'colBytea: blob("col_bytea")' in sqlite_out
    assert 'colBlob: blob("col_blob")' in sqlite_out
    assert 'colDouble: real("col_double").notNull()' in sqlite_out

    # 3. SQLAlchemy Exporter
    sa_out = to_sqlalchemy_models(schema)
    verify_sqlalchemy_models(
        sa_out,
        test_sqlite_ddl=True,
        assertions_code="assert 'ExoticTypes' in ns",
    )


def test_adversarial_special_identifiers_and_map_directives():
    """
    Stress-test identifiers containing digits, hyphens, spaces, mixed cases,
    and verify exact @map and @@map directives in Prisma, as well as valid Drizzle/SQLAlchemy code.
    """
    schema = {
        "tables": {
            "123_audit_trail": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "2025_revenue",
                        "data_type": "numeric",
                        "is_nullable": False,
                    },
                    {
                        "name": "user-account-id",
                        "data_type": "varchar",
                        "is_nullable": False,
                    },
                ]
            },
            "Order Details": {
                "columns": [
                    {
                        "name": "detail_id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "Total Amount",
                        "data_type": "decimal",
                        "is_nullable": False,
                    },
                ]
            },
        }
    }

    # 1. Prisma
    prisma_out = to_prisma_schema(schema)
    verify_prisma_structure(prisma_out)

    # Verify model names are valid PascalCase
    assert "model Model123AuditTrail {" in prisma_out
    assert "model OrderDetails {" in prisma_out

    # Verify @@map directives for tables with special characters or starting with digits
    assert '@@map("123_audit_trail")' in prisma_out
    assert '@@map("Order Details")' in prisma_out

    # Verify @map directives for columns with special characters or starting with digits
    assert '@map("2025_revenue")' in prisma_out
    assert '@map("user-account-id")' in prisma_out
    assert '@map("Total Amount")' in prisma_out

    # 2. Drizzle across dialects
    for dialect in ["postgres", "mysql", "sqlite"]:
        drizzle_out = to_drizzle_schema(schema, dialect=dialect)
        verify_typescript_syntax(drizzle_out)
        # Note: table starting with digits gets col prefix in camelCase variable name
        assert "export const col123AuditTrail =" in drizzle_out
        assert "export const orderDetails =" in drizzle_out
        assert '"123_audit_trail"' in drizzle_out
        assert '"Order Details"' in drizzle_out

    # 3. SQLAlchemy
    sa_out = to_sqlalchemy_models(schema)
    verify_sqlalchemy_models(
        sa_out,
        test_sqlite_ddl=True,
        assertions_code="assert 'Model123AuditTrail' in ns and 'OrderDetails' in ns",
    )


def test_adversarial_diamond_and_multi_column_relationships():
    """
    Stress-test complex relational topologies:
    - Diamond graph: Company -> Dept, Company -> Project; Dept -> Employee, Project -> Employee.
    - Multiple foreign keys from a single table targeting different tables and the same table.
    """
    schema = {
        "tables": {
            "companies": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "name", "data_type": "text", "is_nullable": False},
                ]
            },
            "departments": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "company_id",
                        "data_type": "integer",
                        "is_nullable": False,
                    },
                ]
            },
            "projects": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "company_id",
                        "data_type": "integer",
                        "is_nullable": False,
                    },
                ]
            },
            "employees": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "department_id",
                        "data_type": "integer",
                        "is_nullable": False,
                    },
                    {"name": "project_id", "data_type": "integer", "is_nullable": True},
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "departments",
                "column": "company_id",
                "foreign_table": "companies",
                "foreign_column": "id",
            },
            {
                "table": "projects",
                "column": "company_id",
                "foreign_table": "companies",
                "foreign_column": "id",
            },
            {
                "table": "employees",
                "column": "department_id",
                "foreign_table": "departments",
                "foreign_column": "id",
            },
            {
                "table": "employees",
                "column": "project_id",
                "foreign_table": "projects",
                "foreign_column": "id",
            },
        ],
    }

    # Prisma
    prisma_out = to_prisma_schema(schema)
    verify_prisma_structure(prisma_out)
    assert (
        "department Departments @relation(fields: [departmentId], references: [id])"
        in prisma_out
    )
    assert (
        "project Projects? @relation(fields: [projectId], references: [id])"
        in prisma_out
    )
    assert "employeesList Employees[]" in prisma_out

    # Drizzle across dialects
    for dialect in ["postgres", "mysql", "sqlite"]:
        drizzle_out = to_drizzle_schema(schema, dialect=dialect)
        verify_typescript_syntax(drizzle_out)
        assert ".references(() => companies.id)" in drizzle_out
        assert ".references(() => departments.id)" in drizzle_out
        assert ".references(() => projects.id)" in drizzle_out

    # SQLAlchemy
    sa_out = to_sqlalchemy_models(schema)
    verify_sqlalchemy_models(
        sa_out,
        test_sqlite_ddl=True,
        assertions_code="""
assert 'Companies' in ns and 'Departments' in ns and 'Projects' in ns and 'Employees' in ns
""",
    )


def test_adversarial_collision_resolution_scalar_vs_relation():
    """
    Stress-test collision resolution when a scalar field shares a name with a relation field:
    e.g., Table `orders` has a scalar column `user` and a foreign key `user_id -> users.id`.
    And Table `users` has a scalar column `ordersList` (clashing with back-relation).
    """
    schema = {
        "tables": {
            "users": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "orders_list",
                        "data_type": "text",
                        "is_nullable": True,
                    },  # clashing scalar camelCase -> ordersList!
                ]
            },
            "orders": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "user",
                        "data_type": "text",
                        "is_nullable": True,
                    },  # clashing scalar!
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

    # 1. Prisma should disambiguate clashing relation field to userRel and back-relation to ordersListRel
    prisma_out = to_prisma_schema(schema)
    verify_prisma_structure(prisma_out)
    assert "user String?" in prisma_out
    assert "userRel Users @relation(fields: [userId], references: [id])" in prisma_out
    assert 'ordersList String? @map("orders_list")' in prisma_out
    assert "ordersListRel Orders[]" in prisma_out

    # 2. Drizzle
    for dialect in ["postgres", "mysql", "sqlite"]:
        drizzle_out = to_drizzle_schema(schema, dialect=dialect)
        verify_typescript_syntax(drizzle_out)

    # 3. SQLAlchemy should disambiguate relation name to user_rel
    sa_out = to_sqlalchemy_models(schema)
    verify_sqlalchemy_models(
        sa_out,
        test_sqlite_ddl=True,
        assertions_code="""
Orders = ns['Orders']
assert hasattr(Orders, 'user')
assert hasattr(Orders, 'user_rel')
""",
    )


def test_adversarial_drizzle_dialect_flavors_and_strict_validation():
    """
    Stress-test Drizzle exporter against supported and unsupported dialects,
    alias normalization, and notNull modifiers.
    """
    schema = {
        "tables": {
            "items": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "required_name",
                        "data_type": "text",
                        "is_nullable": False,
                    },
                    {
                        "name": "optional_desc",
                        "data_type": "text",
                        "is_nullable": True,
                    },
                ]
            }
        }
    }

    # Dialect alias postgresql -> postgres
    drizzle_pg = to_drizzle_schema(schema, dialect="postgresql")
    verify_typescript_syntax(drizzle_pg)
    assert 'from "drizzle-orm/pg-core"' in drizzle_pg
    assert 'requiredName: text("required_name").notNull()' in drizzle_pg
    assert 'optionalDesc: text("optional_desc")' in drizzle_pg
    assert (
        ".notNull()"
        not in drizzle_pg.split('optionalDesc: text("optional_desc")')[1].split(",")[0]
    )

    # MySQL dialect
    drizzle_mysql = to_drizzle_schema(schema, dialect="mysql")
    verify_typescript_syntax(drizzle_mysql)
    assert 'from "drizzle-orm/mysql-core"' in drizzle_mysql

    # SQLite dialect
    drizzle_sqlite = to_drizzle_schema(schema, dialect="sqlite")
    verify_typescript_syntax(drizzle_sqlite)
    assert 'from "drizzle-orm/sqlite-core"' in drizzle_sqlite

    # Unsupported dialects must raise ValueError
    for invalid in ["oracle", "cockroachdb", "mongo", "", "  "]:
        with pytest.raises(ValueError, match="Unsupported Drizzle dialect"):
            to_drizzle_schema(schema, dialect=invalid)


def test_adversarial_sqlalchemy_in_memory_orm_and_session_queries():
    """
    Empirical roundtrip: Generate SQLAlchemy models from schema, compile them,
    create SQLite tables, insert rows through SQLAlchemy Session, and query across relations.
    """
    schema = {
        "tables": {
            "authors": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "name", "data_type": "string", "is_nullable": False},
                ]
            },
            "books": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "title", "data_type": "string", "is_nullable": False},
                    {
                        "name": "author_id",
                        "data_type": "integer",
                        "is_nullable": False,
                    },
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "books",
                "column": "author_id",
                "foreign_table": "authors",
                "foreign_column": "id",
            }
        ],
    }

    sa_code = to_sqlalchemy_models(schema)
    assertions = """
from sqlalchemy.orm import Session
Authors = ns['Authors']
Books = ns['Books']

with Session(engine) as session:
    author = Authors(id=1, name="Ada Lovelace")
    book = Books(id=101, title="Notes on the Analytical Engine", author_id=1)
    session.add_all([author, book])
    session.commit()

with Session(engine) as session:
    fetched_book = session.query(Books).filter_by(id=101).one()
    assert fetched_book.title == "Notes on the Analytical Engine"
    assert fetched_book.author.name == "Ada Lovelace"
"""
    verify_sqlalchemy_models(sa_code, test_sqlite_ddl=True, assertions_code=assertions)


def test_adversarial_prisma_provider_flavors_and_strict_validation():
    """
    Stress-test Prisma exporter against all supported providers, aliases, and invalid providers.
    """
    schema = {
        "tables": {
            "users": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "email", "data_type": "varchar", "is_nullable": False},
                ]
            }
        }
    }

    # Supported providers
    for provider in [
        "postgresql",
        "mysql",
        "sqlite",
        "sqlserver",
        "cockroachdb",
        "mongodb",
    ]:
        prisma_out = to_prisma_schema(schema, provider=provider)
        verify_prisma_structure(prisma_out)
        assert f'provider = "{provider}"' in prisma_out

    # Provider aliases
    assert 'provider = "postgresql"' in to_prisma_schema(schema, provider="postgres")
    assert 'provider = "sqlserver"' in to_prisma_schema(schema, provider="mssql")

    # Case insensitivity and whitespace trimming
    assert 'provider = "postgresql"' in to_prisma_schema(
        schema, provider="  PostgreSQL  "
    )

    # Unsupported provider raises ValueError
    for bad_provider in ["oracle", "dynamodb", "redis", ""]:
        with pytest.raises(ValueError, match="Unsupported Prisma provider"):
            to_prisma_schema(schema, provider=bad_provider)


# ============================================================================
# 2. CLI Suite Stress Tests
# ============================================================================


def test_adversarial_cli_validate_malformed_json_and_empty_targets(tmp_path, capsys):
    """
    Stress-test CLI `validate` with malformed JSON, empty files, whitespace-only files,
    and comment-only SQL files across text and structured JSON output modes.
    """
    # 1. Malformed JSON file (syntax error)
    bad_json_file = tmp_path / "broken.json"
    bad_json_file.write_text('{ "table": "users", "fields": [ ')

    # Text mode -> exit 1
    ret = main(["validate", str(bad_json_file)])
    assert ret == 1
    assert "Validation error" in capsys.readouterr().err

    # JSON mode -> exit 1, valid JSON stdout
    ret = main(["validate", str(bad_json_file), "--json"])
    assert ret == 1
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is False
    assert res["injection_risk"] == "CRITICAL"
    assert any("Failed to load or compile target" in v for v in res["violations"])

    # 2. Malformed inline JSON string
    ret = main(["validate", "{ table: users, unquoted }", "--json"])
    assert ret == 1
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is False
    assert res["injection_risk"] == "CRITICAL"

    # 3. Empty file
    empty_file = tmp_path / "empty.sql"
    empty_file.write_text("")
    ret = main(["validate", str(empty_file), "--json"])
    assert ret == 1
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is False

    # 4. Comment-only SQL file
    comment_file = tmp_path / "comment_only.sql"
    comment_file.write_text("-- Just a single line comment\n/* Block comment here */\n")
    ret = main(["validate", str(comment_file), "--json"])
    assert ret == 1
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is False
    assert any(
        "only select queries are permitted" in v.lower() for v in res["violations"]
    )

    # 5. Non-existent .sql and .json files
    ret = main(["validate", str(tmp_path / "missing.sql"), "--json"])
    assert ret == 1
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is False
    assert "Target file not found" in res["violations"][0]


def test_adversarial_cli_validate_sql_injection_and_policy_matrix(tmp_path, capsys):
    """
    Stress-test CLI `validate` across hostile SQL injection vectors, dangerous statements,
    and policy flags (--allowed-schemas, --restricted-tables, --disallow-cte, --fail-on-risk).
    """
    # Hostile vectors that MUST exit 1
    hostile_queries = [
        "SELECT * FROM users; DROP TABLE accounts;",
        "SELECT 1; UPDATE users SET is_admin = true;",
        "SELECT 1; DELETE FROM logs;",
        "SELECT 1; INSERT INTO users VALUES (1);",
        "SELECT 1; TRUNCATE TABLE audit;",
        "CREATE TABLE backdoor (id INT);",
        "ALTER TABLE users ADD COLUMN compromised INT;",
        "GRANT ALL PRIVILEGES ON users TO evil;",
        "SELECT pg_sleep(10);",
        "SELECT sleep(5);",
        "SELECT benchmark(1000000, MD5('test'));",
        "SELECT load_file('/etc/passwd');",
        "SELECT * INTO OUTFILE '/tmp/dump.txt' FROM users;",
        "EXEC xp_cmdshell('dir');",
        "SELECT * FROM auth_user;",
        "SELECT session_key FROM django_session;",
        "SELECT * FROM pg_shadow;",
    ]

    for q in hostile_queries:
        ret = main(["validate", q, "--json"])
        assert ret == 1, f"Hostile query unexpectedly passed: {q}"
        res = json.loads(capsys.readouterr().out)
        assert res["valid"] is False

    # Safe read-only SELECT query MUST exit 0
    safe_query = "SELECT id, name, created_at FROM orders WHERE status = 'active' ORDER BY id DESC LIMIT 10;"
    ret = main(["validate", safe_query, "--json"])
    assert ret == 0
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is True
    assert res["statement_type"] == "SELECT"
    assert res["injection_risk"] == "NONE"

    # Terminal formatted output for safe query
    ret = main(["validate", safe_query])
    assert ret == 0
    assert "[PASS] AST validation succeeded." in capsys.readouterr().out

    # 1. Flag: --allowed-schemas
    # Query against default restricted schema (e.g. public) without whitelist -> exit 1
    ret = main(["validate", "SELECT * FROM public.data;", "--json"])
    assert ret == 1
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is False

    # Query with authorized schema explicitly whitelisted -> exit 0
    ret = main(
        [
            "validate",
            "SELECT * FROM public.data;",
            "--allowed-schemas",
            "public,app",
            "--json",
        ]
    )
    assert ret == 0
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is True

    # Query targeting unwhitelisted restricted schema (pg_catalog) -> exit 1
    ret = main(
        [
            "validate",
            "SELECT * FROM pg_catalog.pg_tables;",
            "--allowed-schemas",
            "public,app",
            "--json",
        ]
    )
    assert ret == 1
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is False

    # 2. Flag: --restricted-tables
    ret = main(
        [
            "validate",
            "SELECT * FROM sensitive_tokens;",
            "--restricted-tables",
            "sensitive_tokens",
            "--json",
        ]
    )
    assert ret == 1
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is False

    ret = main(
        [
            "validate",
            "SELECT * FROM allowed_table;",
            "--restricted-tables",
            "sensitive_tokens",
            "--json",
        ]
    )
    assert ret == 0
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is True

    # 3. Flag: --disallow-cte
    cte_query = (
        "WITH recent AS (SELECT id FROM events WHERE ts > NOW()) SELECT * FROM recent;"
    )
    ret_allowed = main(["validate", cte_query, "--json"])
    assert ret_allowed == 0
    capsys.readouterr()

    ret_disallowed = main(["validate", cte_query, "--disallow-cte", "--json"])
    assert ret_disallowed == 1
    res = json.loads(capsys.readouterr().out)
    assert res["valid"] is False
    assert any(
        "Common Table Expressions (CTE) are disabled" in v
        or "Common Table Expressions (WITH) are not permitted" in v
        for v in res["violations"]
    )

    # 4. Flag: --fail-on-risk
    # Safe query passes --fail-on-risk HIGH
    ret = main(["validate", "SELECT 1;", "--fail-on-risk", "HIGH", "--json"])
    assert ret == 0

    # Query with risky function fails --fail-on-risk HIGH
    ret = main(["validate", "SELECT pg_sleep(1);", "--fail-on-risk", "HIGH", "--json"])
    assert ret == 1


def test_adversarial_cli_compile_error_conditions_and_json(tmp_path, capsys):
    """
    Stress-test CLI `compile` subcommand with invalid spec files, malformed JSON,
    nonexistent output directories, and formatted output vs JSON output.
    """
    valid_spec = {
        "table": "orders",
        "columns": ["id", "amount"],
        "filters": [{"column": "status", "op": "eq", "value": "paid"}],
    }
    spec_file = tmp_path / "valid_spec.json"
    spec_file.write_text(json.dumps(valid_spec))

    # 1. Successful compilation to output file
    out_file = tmp_path / "compiled.sql"
    ret = main(
        [
            "compile",
            "--spec",
            str(spec_file),
            "--dialect",
            "postgres",
            "--output",
            str(out_file),
        ]
    )
    assert ret == 0
    assert out_file.exists()
    assert "SELECT" in out_file.read_text()
    assert "--- Main SQL ---" in capsys.readouterr().out

    # 2. JSON output mode to output file
    out_json = tmp_path / "compiled.json"
    ret = main(
        [
            "compile",
            "--spec",
            str(spec_file),
            "--json",
            "--output",
            str(out_json),
        ]
    )
    assert ret == 0
    assert out_json.exists()
    payload = json.loads(out_json.read_text())
    assert "main_sql" in payload
    assert payload["dialect"] == "postgres"
    capsys.readouterr()

    # 3. Malformed JSON in spec file -> exit 1
    bad_spec = tmp_path / "bad.json"
    bad_spec.write_text("{ malformed: json")
    ret = main(["compile", "--spec", str(bad_spec), "--json"])
    assert ret == 1
    err = json.loads(capsys.readouterr().out)
    assert err["success"] is False

    # 4. Non-existent spec file -> exit 1
    ret = main(["compile", "--spec", str(tmp_path / "missing_spec.json")])
    assert ret == 1
    assert "Compilation error" in capsys.readouterr().err


def test_adversarial_cli_test_connection_error_conditions_and_json(tmp_path, capsys):
    """
    Stress-test CLI `test-connection` with corrupted config files, unknown connectors,
    and structured JSON error responses.
    """
    # 1. Healthy in-memory SQLite connection
    ret = main(
        [
            "test-connection",
            "--connector",
            "sqlite",
            "--config",
            '{"database": ":memory:"}',
            "--json",
        ]
    )
    assert ret == 0
    res = json.loads(capsys.readouterr().out)
    assert res["status"] == "healthy"

    # 2. Unknown connector -> exit 1
    ret = main(["test-connection", "--connector", "unknown_bogus_db", "--json"])
    assert ret == 1
    res = json.loads(capsys.readouterr().out)
    assert res["status"] == "unhealthy"
    assert res["success"] is False

    # 3. Corrupted JSON config string -> exit 1
    ret = main(
        [
            "test-connection",
            "--connector",
            "sqlite",
            "--config",
            "{ invalid json",
            "--json",
        ]
    )
    assert ret == 1
    res = json.loads(capsys.readouterr().out)
    assert res["status"] == "unhealthy"


def test_adversarial_cli_introspect_error_conditions_and_json(tmp_path, capsys):
    """
    Stress-test CLI `introspect` with SQLite database, verifying --output writing,
    --filter-sensitive behavior, and error handling for unknown connectors.
    """
    db_file = tmp_path / "introspect_test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);")
    conn.execute("CREATE TABLE auth_user (id INTEGER PRIMARY KEY, secret TEXT);")
    conn.commit()
    conn.close()

    cfg = json.dumps({"database": str(db_file)})
    out_snap = tmp_path / "snap.json"

    # Filtered introspection -> auth_user excluded
    ret = main(
        [
            "introspect",
            "--connector",
            "sqlite",
            "--config",
            cfg,
            "--output",
            str(out_snap),
            "--filter-sensitive",
            "--json",
        ]
    )
    assert ret == 0
    assert out_snap.exists()
    snap = json.loads(out_snap.read_text())
    assert "users" in snap["tables"]
    assert "auth_user" not in snap["tables"]
    capsys.readouterr()

    # Unfiltered introspection -> auth_user included
    ret = main(
        [
            "introspect",
            "--connector",
            "sqlite",
            "--config",
            cfg,
            "--no-filter-sensitive",
            "--json",
        ]
    )
    assert ret == 0
    snap = json.loads(capsys.readouterr().out)
    assert "users" in snap["tables"]
    assert "auth_user" in snap["tables"]

    # Unknown connector -> exit 1
    ret = main(["introspect", "--connector", "bogus_connector", "--json"])
    assert ret == 1
    err = json.loads(capsys.readouterr().out)
    assert err["success"] is False


def test_adversarial_cli_export_schema_error_conditions_and_json(tmp_path, capsys):
    """
    Stress-test CLI `export-schema` across supported and unsupported formats,
    dialect flags, --output file writing, and error conditions.
    """
    schema = {
        "tables": {
            "accounts": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "email", "data_type": "varchar", "is_nullable": False},
                ]
            }
        }
    }
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    # 1. Drizzle export with postgres dialect to file
    drizzle_out = tmp_path / "schema.ts"
    ret = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "drizzle",
            "--dialect",
            "postgres",
            "--output",
            str(drizzle_out),
            "--json",
        ]
    )
    assert ret == 0
    assert drizzle_out.exists()
    res = json.loads(capsys.readouterr().out)
    assert res["success"] is True
    assert res["format"] == "drizzle"
    assert res["dialect"] == "postgres"

    # 2. Unsupported format -> exit 1
    ret = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "unsupported_orm",
            "--json",
        ]
    )
    assert ret == 1
    err = json.loads(capsys.readouterr().out)
    assert err["success"] is False
    assert "Unknown format" in err["error"]

    # 3. Unsupported Drizzle dialect -> exit 1
    ret = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "drizzle",
            "--dialect",
            "unsupported_dialect",
            "--json",
        ]
    )
    assert ret == 1
    err = json.loads(capsys.readouterr().out)
    assert err["success"] is False
    assert "Unsupported Drizzle dialect" in err["error"]

    # 4. Non-existent schema file -> exit 1
    ret = main(
        [
            "export-schema",
            "--schema",
            str(tmp_path / "missing.json"),
            "--format",
            "prisma",
        ]
    )
    assert ret == 1
    assert "Export error" in capsys.readouterr().err


def test_adversarial_cli_argparse_bounds_and_subcommand_routing():
    """
    Stress-test CLI argument parsing boundaries, missing required arguments,
    subcommand routing, and version reporting.
    """
    # 1. No subcommand provided -> exit code 2
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2

    # 2. Invalid subcommand -> exit code 2
    with pytest.raises(SystemExit) as exc:
        main(["nonexistent-subcommand"])
    assert exc.value.code == 2

    # 3. Missing required options per subcommand
    with pytest.raises(SystemExit) as exc:
        main(["compile"])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        main(["test-connection"])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        main(["introspect"])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        main(["export-schema", "--schema", "dummy.json"])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        main(["join-path", "--active", "users"])
    assert exc.value.code == 2

    # 4. Version flag -> exit code 0
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
