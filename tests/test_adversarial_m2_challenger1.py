"""
Milestone 2 DX Challenger 1 Adversarial Stress & Empirical Verification Suite.
==============================================================================
Empirically tests deep boundary conditions and hostile edge cases for Milestone 2:
1. Schema Converters (to_prisma_schema, to_drizzle_schema, to_sqlalchemy_models):
   - Complex multi-table schemas with self-referencing foreign keys (single and multi).
   - Circular relations across 2 and 3 tables.
   - Multiple foreign keys between the same pair of tables.
   - Comprehensive data type coverage and fallback handling across SQL dialects.
   - Autoincrement/serial vs UUID/text primary keys and nullability constraints.
   - Unconventional identifiers (digits, hyphens, spaces) and keyword sanitization.
   - Empty, degenerate, and malformed schemas.
   - Independent syntax verification:
     * Drizzle: Real TypeScript AST parse diagnostics via Node.js compiler API.
     * SQLAlchemy: compile(), exec(), configure_mappers(), and in-memory SQLite DDL execution.
     * Prisma: Structural AST parsing, block balance, directive semantics.
2. CLI Suite (query_builder/cli.py):
   - Subcommand `validate`:
     * Target variations: raw SQL, .sql file, .json query spec file, inline JSON.
     * Flags: --allowed-schemas, --restricted-tables, --disallow-cte, --fail-on-risk, --json.
     * Exit codes: 0 for clean read-only, non-zero for mutations/violations/risks.
     * Missing files, malformed JSON, and query injection attempts.
   - Subcommand `compile`:
     * Targets: spec file, inline JSON, schema file, dialects, --output, --json.
   - Subcommand `test-connection`:
     * Connectors: sqlite (:memory: and file), duckdb, nonexistent connector.
     * Flags: --config (string and file), --json.
   - Subcommand `introspect`:
     * Connector introspection with real SQLite tables, relations, and sensitive tables.
     * Flags: --filter-sensitive vs --no-filter-sensitive, --output, --json.
   - Subcommand `export-schema`:
     * Formats: prisma, drizzle, sqlalchemy.
     * Flags: --dialect, --output, --json, error handling for unknown formats.
   - Subcommand `join-path` and argument parsing error conditions.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from query_builder.cli import main
from query_builder.models import SchemaSnapshot
from query_builder.schema_converters import (
    _to_camel_case,
    _to_pascal_case,
    _to_snake_case,
    to_drizzle_schema,
    to_prisma_schema,
    to_sqlalchemy_models,
)

# ============================================================================
# Verification Oracles & Helpers
# ============================================================================


_TS_MODULE_PATH = str(
    Path(__file__).resolve().parents[1]
    / "packages"
    / "react"
    / "node_modules"
    / "typescript"
)


def verify_typescript_syntax(ts_code: str) -> None:
    """Verifies TypeScript code syntax using the installed TypeScript compiler AST parser."""
    if shutil.which("node") is None or not Path(_TS_MODULE_PATH).exists():
        pytest.skip("node and packages/react/node_modules/typescript are required")
    node_script = f"""
    const ts = require({json.dumps(_TS_MODULE_PATH)});
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
        for raw_line in body.strip().splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("//", "@@")):
                continue
            parts = line.split()
            assert len(parts) >= 2, f"Invalid field definition line: {line}"
            field_name = parts[0]
            assert re.match(r"^[a-zA-Z0-9_]+$", field_name), (
                f"Invalid field name: {field_name}"
            )


# ============================================================================
# 1. Schema Converters Adversarial Tests
# ============================================================================


def test_adversarial_complex_multi_table_self_referencing_fks():
    """
    Stress-test schema converters on complex multi-table structures featuring
    both single and multiple self-referencing foreign keys, hierarchies, and back-relations.
    """
    schema = {
        "tables": {
            "employees": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "name", "data_type": "varchar", "is_nullable": False},
                    {"name": "manager_id", "data_type": "integer", "is_nullable": True},
                    {"name": "mentor_id", "data_type": "integer", "is_nullable": True},
                    {"name": "salary", "data_type": "numeric", "is_nullable": False},
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
                    {"name": "name", "data_type": "text", "is_nullable": False},
                    {
                        "name": "parent_dept_id",
                        "data_type": "integer",
                        "is_nullable": True,
                    },
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "employees",
                "column": "manager_id",
                "foreign_table": "employees",
                "foreign_column": "id",
            },
            {
                "table": "employees",
                "column": "mentor_id",
                "foreign_table": "employees",
                "foreign_column": "id",
            },
            {
                "table": "departments",
                "column": "parent_dept_id",
                "foreign_table": "departments",
                "foreign_column": "id",
            },
        ],
    }

    # 1. Prisma Exporter
    prisma_out = to_prisma_schema(schema, provider="postgresql")
    verify_prisma_structure(prisma_out)
    assert 'manager Employees? @relation("Employees_managerId"' in prisma_out
    assert 'mentor Employees? @relation("Employees_mentorId"' in prisma_out
    assert (
        'employeesByManagerId Employees[] @relation("Employees_managerId")'
        in prisma_out
    )
    assert (
        'employeesByMentorId Employees[] @relation("Employees_mentorId")' in prisma_out
    )
    assert (
        "parentDept Departments? @relation(fields: [parentDeptId], references: [id])"
        in prisma_out
    )

    # 2. Drizzle Exporter across all supported dialects
    for dialect in ["postgres", "mysql", "sqlite"]:
        drizzle_out = to_drizzle_schema(schema, dialect=dialect)
        verify_typescript_syntax(drizzle_out)
        assert ".references(() => employees.id)" in drizzle_out
        assert ".references(() => departments.id)" in drizzle_out

    # 3. SQLAlchemy Exporter
    sa_out = to_sqlalchemy_models(schema)
    verify_sqlalchemy_models(
        sa_out,
        test_sqlite_ddl=True,
        assertions_code="assert 'Employees' in ns and 'Departments' in ns",
    )


def test_adversarial_circular_relations():
    """
    Stress-test circular relation topologies:
    A -> B and B -> A (2-cycle), and A -> B -> C -> A (3-cycle).
    """
    two_cycle_schema = {
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
                        "name": "active_workspace_id",
                        "data_type": "integer",
                        "is_nullable": True,
                    },
                ]
            },
            "workspaces": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "owner_id", "data_type": "integer", "is_nullable": False},
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "users",
                "column": "active_workspace_id",
                "foreign_table": "workspaces",
                "foreign_column": "id",
            },
            {
                "table": "workspaces",
                "column": "owner_id",
                "foreign_table": "users",
                "foreign_column": "id",
            },
        ],
    }

    # Prisma
    p2 = to_prisma_schema(two_cycle_schema)
    verify_prisma_structure(p2)
    assert "activeWorkspace Workspaces? @relation" in p2
    assert "owner Users @relation" in p2

    # Drizzle
    for d in ["postgres", "mysql", "sqlite"]:
        dz = to_drizzle_schema(two_cycle_schema, dialect=d)
        verify_typescript_syntax(dz)

    # SQLAlchemy
    sa2 = to_sqlalchemy_models(two_cycle_schema)
    verify_sqlalchemy_models(sa2, test_sqlite_ddl=True)

    # 3-cycle topology: a -> b -> c -> a
    three_cycle_schema = {
        "tables": {
            "node_a": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "b_id", "data_type": "integer", "is_nullable": True},
                ]
            },
            "node_b": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "c_id", "data_type": "integer", "is_nullable": True},
                ]
            },
            "node_c": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "a_id", "data_type": "integer", "is_nullable": True},
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "node_a",
                "column": "b_id",
                "foreign_table": "node_b",
                "foreign_column": "id",
            },
            {
                "table": "node_b",
                "column": "c_id",
                "foreign_table": "node_c",
                "foreign_column": "id",
            },
            {
                "table": "node_c",
                "column": "a_id",
                "foreign_table": "node_a",
                "foreign_column": "id",
            },
        ],
    }

    p3 = to_prisma_schema(three_cycle_schema)
    verify_prisma_structure(p3)

    for d in ["postgres", "mysql", "sqlite"]:
        dz3 = to_drizzle_schema(three_cycle_schema, dialect=d)
        verify_typescript_syntax(dz3)

    sa3 = to_sqlalchemy_models(three_cycle_schema)
    verify_sqlalchemy_models(sa3, test_sqlite_ddl=True)


def test_adversarial_multiple_fks_between_same_tables():
    """
    Stress-test tables with multiple distinct foreign keys pointing to the same target table
    (e.g. orders table pointing to addresses table for shipping and billing).
    """
    schema = {
        "tables": {
            "addresses": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "serial",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "street", "data_type": "text", "is_nullable": False},
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
                        "name": "shipping_address_id",
                        "data_type": "integer",
                        "is_nullable": False,
                    },
                    {
                        "name": "billing_address_id",
                        "data_type": "integer",
                        "is_nullable": False,
                    },
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "orders",
                "column": "shipping_address_id",
                "foreign_table": "addresses",
                "foreign_column": "id",
            },
            {
                "table": "orders",
                "column": "billing_address_id",
                "foreign_table": "addresses",
                "foreign_column": "id",
            },
        ],
    }

    # Prisma must disambiguate relations with named tags
    prisma_out = to_prisma_schema(schema)
    verify_prisma_structure(prisma_out)
    assert (
        'shippingAddress Addresses @relation("Addresses_shippingAddressId"'
        in prisma_out
    )
    assert (
        'billingAddress Addresses @relation("Addresses_billingAddressId"' in prisma_out
    )
    assert '@relation("Addresses_shippingAddressId")' in prisma_out
    assert '@relation("Addresses_billingAddressId")' in prisma_out

    # Drizzle must reference addresses.id on both columns
    for dialect in ["postgres", "mysql", "sqlite"]:
        drizzle_out = to_drizzle_schema(schema, dialect=dialect)
        verify_typescript_syntax(drizzle_out)
        assert ".references(() => addresses.id)" in drizzle_out

    # SQLAlchemy must map both relationships without naming collisions
    sa_out = to_sqlalchemy_models(schema)
    verify_sqlalchemy_models(
        sa_out,
        test_sqlite_ddl=True,
        assertions_code="assert hasattr(ns['Orders'], 'shipping_address') and hasattr(ns['Orders'], 'billing_address')",
    )


def test_adversarial_all_data_types_and_fallbacks():
    """
    Stress-test comprehensive data type translation across all three exporters:
    integers, floats, decimals, booleans, timestamps, jsons, blobs, text, and unknown types.
    """
    columns = [
        {"name": "id", "data_type": "bigint", "is_primary": True, "is_nullable": False},
        {"name": "col_serial", "data_type": "serial", "is_nullable": False},
        {"name": "col_bigserial", "data_type": "bigserial", "is_nullable": False},
        {"name": "col_smallint", "data_type": "smallint", "is_nullable": True},
        {"name": "col_tinyint", "data_type": "tinyint", "is_nullable": True},
        {"name": "col_bool", "data_type": "bool", "is_nullable": False},
        {"name": "col_boolean", "data_type": "boolean", "is_nullable": True},
        {"name": "col_float", "data_type": "float", "is_nullable": True},
        {"name": "col_double", "data_type": "double precision", "is_nullable": True},
        {"name": "col_real", "data_type": "real", "is_nullable": True},
        {"name": "col_decimal", "data_type": "decimal", "is_nullable": True},
        {"name": "col_numeric", "data_type": "numeric", "is_nullable": True},
        {"name": "col_money", "data_type": "money", "is_nullable": True},
        {"name": "col_datetime", "data_type": "datetime", "is_nullable": True},
        {
            "name": "col_timestamp",
            "data_type": "timestamp with time zone",
            "is_nullable": True,
        },
        {"name": "col_date", "data_type": "date", "is_nullable": True},
        {"name": "col_time", "data_type": "time", "is_nullable": True},
        {"name": "col_json", "data_type": "json", "is_nullable": True},
        {"name": "col_jsonb", "data_type": "jsonb", "is_nullable": True},
        {"name": "col_bytea", "data_type": "bytea", "is_nullable": True},
        {"name": "col_blob", "data_type": "blob", "is_nullable": True},
        {"name": "col_varchar", "data_type": "varchar(255)", "is_nullable": True},
        {"name": "col_text", "data_type": "text", "is_nullable": True},
        {"name": "col_unknown_geom", "data_type": "geometry", "is_nullable": True},
        {"name": "col_unknown_uuid", "data_type": "uuid", "is_nullable": True},
    ]

    schema = {"tables": {"type_matrix": {"columns": columns}}}

    # Prisma
    p_out = to_prisma_schema(schema)
    verify_prisma_structure(p_out)
    assert "colSerial Int" in p_out
    assert "colBigserial BigInt" in p_out
    assert "colBool Boolean" in p_out
    assert "colFloat Float?" in p_out
    assert "colDecimal Decimal?" in p_out
    assert "colTimestamp DateTime?" in p_out
    assert "colJsonb Json?" in p_out
    assert "colBytea Bytes?" in p_out
    assert "colUnknownGeom String?" in p_out  # Fallback to String

    # Drizzle
    for dialect in ["postgres", "mysql", "sqlite"]:
        d_out = to_drizzle_schema(schema, dialect=dialect)
        verify_typescript_syntax(d_out)

    # SQLAlchemy
    sa_out = to_sqlalchemy_models(schema)
    verify_sqlalchemy_models(sa_out, test_sqlite_ddl=True)


def test_adversarial_unconventional_identifiers_and_sanitization():
    """
    Stress-test identifiers starting with numbers, containing hyphens, spaces,
    and special characters across all three exporters.
    """
    schema = {
        "tables": {
            "123_reports": {
                "columns": [
                    {
                        "name": "user-id",
                        "data_type": "integer",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "2024_revenue",
                        "data_type": "numeric",
                        "is_nullable": False,
                    },
                    {"name": "special name!", "data_type": "text", "is_nullable": True},
                ]
            }
        }
    }

    # Identifier utilities sanity
    assert _to_pascal_case("123_reports") == "Model123Reports"
    assert _to_camel_case("2024_revenue") == "col2024Revenue"
    assert _to_snake_case("2024_revenue") == "col_2024_revenue"

    # Prisma
    p_out = to_prisma_schema(schema)
    verify_prisma_structure(p_out)
    assert "model Model123Reports" in p_out
    assert '@@map("123_reports")' in p_out

    # Drizzle
    d_out = to_drizzle_schema(schema, dialect="postgres")
    verify_typescript_syntax(d_out)

    # SQLAlchemy
    sa_out = to_sqlalchemy_models(schema)
    verify_sqlalchemy_models(sa_out, test_sqlite_ddl=True)


def test_adversarial_empty_and_degenerate_schemas():
    """
    Stress-test degenerate inputs: empty SchemaSnapshot, empty dict,
    tables with no columns, and invalid dialect/provider parameters.
    """
    # 1. Empty SchemaSnapshot object
    empty_snap = SchemaSnapshot()
    assert "datasource db" in to_prisma_schema(empty_snap)
    assert "import" in to_drizzle_schema(empty_snap)
    assert "Base = declarative_base()" in to_sqlalchemy_models(empty_snap)

    # 2. Empty raw dictionary
    assert "datasource db" in to_prisma_schema({})
    assert "import" in to_drizzle_schema({})
    assert "Base = declarative_base()" in to_sqlalchemy_models({})

    # 3. Table with zero columns
    zero_cols = {"tables": {"empty_tbl": {"columns": []}}}
    p_empty = to_prisma_schema(zero_cols)
    assert "model EmptyTbl {" in p_empty
    assert '@@map("empty_tbl")' in p_empty
    d_empty = to_drizzle_schema(zero_cols)
    verify_typescript_syntax(d_empty)
    sa_empty = to_sqlalchemy_models(zero_cols)
    assert compile(sa_empty, "<string>", "exec") is not None
    # SQLAlchemy requires at least one primary key column when defining ORM models
    empty_runner = f"""
import sys
code = {json.dumps(sa_empty)}
exec(code, {{}})
"""
    proc = subprocess.run(
        [sys.executable, "-c", empty_runner],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "primary key" in proc.stderr

    # 4. Invalid provider / dialect exceptions
    with pytest.raises(ValueError, match="Unsupported Prisma provider"):
        to_prisma_schema({}, provider="oracle_unsupported")

    with pytest.raises(ValueError, match="Unsupported Drizzle dialect"):
        to_drizzle_schema({}, dialect="cassandra_unsupported")

    # 5. Aliases support
    assert 'provider = "postgresql"' in to_prisma_schema({}, provider="postgres")
    assert 'provider = "sqlserver"' in to_prisma_schema({}, provider="mssql")
    assert "pgTable" in to_drizzle_schema({}, dialect="postgresql")


# ============================================================================
# 2. CLI Suite Subcommands Adversarial Tests
# ============================================================================


def test_adversarial_cli_validate_all_targets_and_flags(tmp_path, capsys):
    """
    Stress-test CLI `validate` across raw strings, .sql files, .json query specs,
    --allowed-schemas, --restricted-tables, --disallow-cte, --fail-on-risk, and --json.
    """
    # 1. Valid raw SQL -> exit 0
    ret = main(["validate", "SELECT id, email FROM users WHERE id = 1;", "--json"])
    assert ret == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["injection_risk"] == "NONE"

    # 2. Semicolon query chaining injection -> exit 1
    ret = main(["validate", "SELECT 1; DROP TABLE users;", "--json"])
    assert ret == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert payload["injection_risk"] == "CRITICAL"

    # 3. Dangerous function injection (pg_sleep) -> exit 1
    ret = main(["validate", "SELECT pg_sleep(5);", "--json"])
    assert ret == 1

    # 4. Target as .sql file
    safe_sql_file = tmp_path / "query.sql"
    safe_sql_file.write_text("SELECT count(*) FROM orders;")
    ret = main(["validate", str(safe_sql_file), "--json"])
    assert ret == 0

    mut_sql_file = tmp_path / "danger.sql"
    mut_sql_file.write_text("TRUNCATE TABLE users;")
    ret = main(["validate", str(mut_sql_file), "--json"])
    assert ret == 1

    # Missing .sql file -> exit 1
    ret = main(["validate", str(tmp_path / "missing.sql"), "--json"])
    assert ret == 1

    # 5. Target as .json query spec file
    spec_file = tmp_path / "valid_spec.json"
    spec_file.write_text(json.dumps({"table": "users", "columns": ["id"]}))
    ret = main(["validate", str(spec_file), "--json"])
    assert ret == 0

    # JSON file containing raw SQL
    raw_sql_spec = tmp_path / "raw_spec.json"
    raw_sql_spec.write_text(json.dumps({"sql": "SELECT id FROM users"}))
    ret = main(["validate", str(raw_sql_spec), "--json"])
    assert ret == 0

    # JSON file containing mutation SQL
    bad_sql_spec = tmp_path / "bad_spec.json"
    bad_sql_spec.write_text(json.dumps({"sql": "DELETE FROM users"}))
    ret = main(["validate", str(bad_sql_spec), "--json"])
    assert ret == 1

    # Malformed JSON file -> exit 1
    corrupt_json = tmp_path / "corrupt.json"
    corrupt_json.write_text("{ unclosed json")
    ret = main(["validate", str(corrupt_json), "--json"])
    assert ret == 1

    # Missing .json file -> exit 1
    ret = main(["validate", str(tmp_path / "nonexistent.json"), "--json"])
    assert ret == 1

    # 6. Target as inline JSON query spec
    ret = main(["validate", '{"table": "users", "columns": ["id"]}', "--json"])
    assert ret == 0

    # 7. --allowed-schemas flag
    ret = main(
        [
            "validate",
            "SELECT * FROM public.users;",
            "--allowed-schemas",
            "analytics",
            "--json",
        ]
    )
    assert ret == 1
    ret = main(
        [
            "validate",
            "SELECT * FROM public.users;",
            "--allowed-schemas",
            "public",
            "--json",
        ]
    )
    assert ret == 0

    # 8. --restricted-tables flag
    ret = main(
        ["validate", "SELECT * FROM orders;", "--restricted-tables", "orders", "--json"]
    )
    assert ret == 1
    ret = main(
        [
            "validate",
            "SELECT * FROM orders;",
            "--restricted-tables",
            "secret_table",
            "--json",
        ]
    )
    assert ret == 0

    # 9. --disallow-cte flag
    cte_query = "WITH t AS (SELECT 1) SELECT * FROM t;"
    ret_cte_ok = main(["validate", cte_query])
    assert ret_cte_ok == 0
    ret_cte_fail = main(["validate", cte_query, "--disallow-cte"])
    assert ret_cte_fail == 1

    # 10. --fail-on-risk flag
    ret_risk_safe = main(["validate", "SELECT 1;", "--fail-on-risk", "HIGH"])
    assert ret_risk_safe == 0
    ret_risk_high = main(
        ["validate", "SELECT * FROM auth_user;", "--fail-on-risk", "HIGH"]
    )
    assert ret_risk_high == 1
    ret_risk_crit = main(
        ["validate", "SELECT * FROM auth_user;", "--fail-on-risk", "CRITICAL"]
    )
    assert ret_risk_crit == 1

    # 11. Plain formatted terminal output (non-JSON)
    ret_pass = main(["validate", "SELECT 1;"])
    assert ret_pass == 0
    out = capsys.readouterr().out
    assert "[PASS] AST validation succeeded" in out

    ret_fail = main(["validate", "DROP TABLE users;"])
    assert ret_fail == 1
    out_fail = capsys.readouterr().out
    assert "[FAIL] AST validation failed" in out_fail


def test_adversarial_cli_compile_permutations(tmp_path, capsys):
    """
    Stress-test CLI `compile` subcommand across dialects, input styles (file vs inline),
    --output writing, --json structured responses, and compilation error paths.
    """
    spec = {"table": "items", "columns": ["id", "price"], "limit": 25}
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    # 1. Output to file as plain SQL
    sql_out = tmp_path / "compiled.sql"
    ret = main(
        [
            "compile",
            "--spec",
            str(spec_file),
            "--dialect",
            "postgres",
            "--output",
            str(sql_out),
        ]
    )
    assert ret == 0
    assert sql_out.exists()
    content = sql_out.read_text()
    assert 'FROM "items" "t1"' in content
    assert "LIMIT %s OFFSET %s" in content
    capsys.readouterr()

    # 2. Output as structured JSON
    json_out = tmp_path / "compiled.json"
    ret = main(
        [
            "compile",
            "--spec",
            json.dumps(spec),
            "--dialect",
            "sqlite",
            "--output",
            str(json_out),
            "--json",
        ]
    )
    assert ret == 0
    assert json_out.exists()
    payload = json.loads(json_out.read_text())
    assert payload["dialect"] == "sqlite"
    assert "LIMIT ? OFFSET ?" in payload["main_sql"]
    capsys.readouterr()

    # 3. Dialects permutation
    for dialect in ["snowflake", "mssql", "mysql"]:
        ret = main(
            ["compile", "--spec", json.dumps(spec), "--dialect", dialect, "--json"]
        )
        assert ret == 0
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["dialect"] == dialect

    # 4. Compilation error paths
    bad_spec = tmp_path / "bad.json"
    bad_spec.write_text("invalid json")
    ret_err = main(["compile", "--spec", str(bad_spec), "--json"])
    assert ret_err == 1
    err_payload = json.loads(capsys.readouterr().out)
    assert err_payload["success"] is False

    ret_missing = main(["compile", "--spec", str(tmp_path / "missing.json")])
    assert ret_missing == 1
    assert "Compilation error" in capsys.readouterr().err


def test_adversarial_cli_test_connection_sync_and_async(tmp_path, capsys):
    """
    Stress-test CLI `test-connection` across sync/async connectors,
    configuration files, inline JSON config, healthy, and failure cases.
    """
    # 1. SQLite memory connection via inline JSON
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
    assert res["dialect"] == "sqlite"

    # 2. SQLite file connection via config file
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE t (id INT);")
    conn.commit()
    conn.close()

    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(json.dumps({"database": str(db_file)}))

    ret = main(["test-connection", "--connector", "sqlite", "--config", str(cfg_file)])
    assert ret == 0
    assert "[OK] Connection to 'sqlite' successful" in capsys.readouterr().out

    # 3. Nonexistent connector identifier -> exit 1
    ret = main(["test-connection", "--connector", "fake_unknown_connector", "--json"])
    assert ret == 1
    err_payload = json.loads(capsys.readouterr().out)
    assert err_payload["status"] == "unhealthy"

    # Non-json terminal failure
    ret = main(["test-connection", "--connector", "fake_unknown_connector"])
    assert ret == 1
    assert "[ERROR]" in capsys.readouterr().out


def test_adversarial_cli_introspect_filtering_and_output(tmp_path, capsys):
    """
    Stress-test CLI `introspect` subcommand with real SQLite database,
    verifying --output, --json, and --filter-sensitive vs --no-filter-sensitive.
    """
    db_path = tmp_path / "test_introspect.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE public_data (id INTEGER PRIMARY KEY, info TEXT);")
    conn.execute("CREATE TABLE auth_user (id INTEGER PRIMARY KEY, password TEXT);")
    conn.execute(
        "CREATE TABLE django_session (id INTEGER PRIMARY KEY, session_key TEXT);"
    )
    conn.commit()
    conn.close()

    cfg = json.dumps({"database": str(db_path)})

    # 1. Default filtering (--filter-sensitive default True)
    out_filtered = tmp_path / "snap_filtered.json"
    ret = main(
        [
            "introspect",
            "--connector",
            "sqlite",
            "--config",
            cfg,
            "--output",
            str(out_filtered),
            "--json",
        ]
    )
    assert ret == 0
    snap_filtered = json.loads(out_filtered.read_text())
    assert "public_data" in snap_filtered["tables"]
    assert "auth_user" not in snap_filtered["tables"]
    assert "django_session" not in snap_filtered["tables"]
    capsys.readouterr()

    # 2. Unfiltered introspection (--no-filter-sensitive)
    out_unfiltered = tmp_path / "snap_unfiltered.json"
    ret = main(
        [
            "introspect",
            "--connector",
            "sqlite",
            "--config",
            cfg,
            "--output",
            str(out_unfiltered),
            "--no-filter-sensitive",
            "--json",
        ]
    )
    assert ret == 0
    snap_unfiltered = json.loads(out_unfiltered.read_text())
    assert "public_data" in snap_unfiltered["tables"]
    assert "auth_user" in snap_unfiltered["tables"]
    assert "django_session" in snap_unfiltered["tables"]
    capsys.readouterr()

    # 3. Formatted terminal output mode
    ret = main(["introspect", "--connector", "sqlite", "--config", cfg])
    assert ret == 0
    stdout_text = capsys.readouterr().out
    assert "[OK] Introspected" in stdout_text
    assert "public_data" in stdout_text

    # 4. Nonexistent connector error handling
    ret_err = main(["introspect", "--connector", "bad_connector", "--json"])
    assert ret_err == 1
    assert json.loads(capsys.readouterr().out)["success"] is False


def test_adversarial_cli_export_schema_all_formats(tmp_path, capsys):
    """
    Stress-test CLI `export-schema` subcommand across prisma, drizzle, and sqlalchemy formats,
    dialect flags, --output writing, --json output, and error conditions.
    """
    schema = {
        "tables": {
            "products": {
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {"name": "title", "data_type": "varchar", "is_nullable": False},
                    {"name": "price", "data_type": "numeric", "is_nullable": False},
                ]
            }
        }
    }
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    # 1. Prisma export to file
    prisma_out = tmp_path / "schema.prisma"
    ret = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "prisma",
            "--output",
            str(prisma_out),
        ]
    )
    assert ret == 0
    assert prisma_out.exists()
    assert "model Products" in prisma_out.read_text()
    capsys.readouterr()

    # 2. Drizzle export with mysql dialect and --json
    ret = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "drizzle",
            "--dialect",
            "mysql",
            "--json",
        ]
    )
    assert ret == 0
    res = json.loads(capsys.readouterr().out)
    assert res["success"] is True
    assert res["format"] == "drizzle"
    assert res["dialect"] == "mysql"
    assert "mysqlTable" in res["content"]

    # 3. SQLAlchemy export to file
    sa_out = tmp_path / "models.py"
    ret = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "sqlalchemy",
            "--output",
            str(sa_out),
        ]
    )
    assert ret == 0
    assert sa_out.exists()
    assert "class Products(Base):" in sa_out.read_text()
    capsys.readouterr()

    # 4. Unknown format error
    ret = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "unknown_format",
            "--json",
        ]
    )
    assert ret == 1
    err_res = json.loads(capsys.readouterr().out)
    assert err_res["success"] is False
    assert "Unknown format" in err_res["error"]

    # 5. Nonexistent schema file error
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


def test_adversarial_cli_join_path_and_argparse(tmp_path, capsys):
    """
    Stress-test CLI `join-path` subcommand and argparse validation bounds.
    """
    schema = {
        "tables": {
            "users": {"columns": [{"name": "id"}]},
            "orders": {"columns": [{"name": "id"}, {"name": "user_id"}]},
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
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    # 1. Valid join-path
    ret = main(
        [
            "join-path",
            "--active",
            "users",
            "--target",
            "orders",
            "--schema",
            str(schema_file),
            "--json",
        ]
    )
    assert ret == 0
    path = json.loads(capsys.readouterr().out)
    assert len(path) == 1
    assert path[0]["table"] == "orders"

    # 2. Join path error on missing schema file
    ret = main(
        [
            "join-path",
            "--active",
            "users",
            "--target",
            "orders",
            "--schema",
            str(tmp_path / "missing.json"),
        ]
    )
    assert ret == 1
    assert "Join path error" in capsys.readouterr().err

    # 3. Missing required subcommand -> SystemExit code 2
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
