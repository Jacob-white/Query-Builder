"""
Comprehensive Consumer Simulation Test Suite for Query-Builder.
================================================================
Simulates real-world third-party consumer workflows importing, adapting,
configuring, securing, and executing queries across the complete Python
engine public API surface.

Coverage:
1. Zero-dependency core import isolation (blocking optional database drivers)
2. Zero-dependency fresh subprocess execution
3. Multi-format schema adapter interoperability (Prisma, Drizzle, SQLAlchemy, JSON Schema)
4. Cross-table multi-dialect query compilation (PostgreSQL, SQLite, MySQL)
5. Custom SQL dialect registration and query compilation lifecycle
6. Custom filter operator registration, parameter binding, and config reset
7. Custom database connector lifecycle, secret scrubbing, and introspection
8. Real SQLite database end-to-end multi-table joins, aggregates, and queries
9. Production security governance, AST safety validation, and SSRF defense
10. Developer CLI workflow (validate, compile, export-schema)
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from query_builder import (
    QueryCompiler,
    configure_query_builder,
    configure_security,
    get_connector,
    get_security_config,
    list_connectors,
    list_dialects,
    list_filter_operators,
    register_connector,
    register_dialect,
    reset_query_builder_config,
    reset_security_config,
    unregister_connector,
    unregister_dialect,
    unregister_filter_operator,
    validate_network_target,
    validate_sql_ast,
)
from query_builder.adapters import (
    from_drizzle,
    from_json_schema,
    from_prisma,
    from_sqlalchemy,
    to_schema_snapshot,
)
from query_builder.cli import main as cli_main
from query_builder.config import SecurityProfile
from query_builder.connectors.base import BaseConnector
from query_builder.connectors.sqlite import SQLiteConnector
from query_builder.dialects import BaseDialect
from query_builder.exceptions import SecurityError, ValidationError

# ---------------------------------------------------------------------------
# Autouse Fixture for Zero State Contamination
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_consumer_state():
    """Ensure global configuration, security profile, and registries are reset before and after."""
    reset_query_builder_config()
    reset_security_config()
    yield
    reset_query_builder_config()
    reset_security_config()
    for d in ["consumer_custom", "ccd", "consumer_reporting"]:
        if d in list_dialects():
            unregister_dialect(d)
    for c in ["consumer_memory_db", "mock_consumer_db"]:
        if c in list_connectors():
            unregister_connector(c)
    for op in ["ci_eq", "regex_custom", "custom_unary"]:
        if op in list_filter_operators():
            unregister_filter_operator(op)


# ---------------------------------------------------------------------------
# 1. Zero-Dependency Core Import Isolation
# ---------------------------------------------------------------------------


def test_zero_dep_core_import_isolation():
    """
    Verifies that Query-Builder core compilation, adapters, and configuration
    can be imported and used in an environment where all optional database drivers
    are absent.
    """
    blocked_drivers = [
        "psycopg",
        "psycopg2",
        "duckdb",
        "sqlalchemy",
        "polars",
        "mysqlclient",
        "pymysql",
        "snowflake",
        "google",
        "boto3",
        "redis",
        "chromadb",
        "pinecone",
        "weaviate",
        "pymilvus",
        "neo4j",
        "taospy",
        "oracledb",
    ]
    saved_modules = {m: sys.modules.get(m) for m in blocked_drivers}

    try:
        for m in blocked_drivers:
            sys.modules[m] = None  # Forces ModuleNotFoundError on any import attempt

        # Core engine symbols
        from query_builder import (
            ColumnSchema,
            ForeignKey,
            QueryBuilderConfig,
            QueryCompiler,
            QuerySpec,
            TableSchema,
            validate_sql_ast,
        )
        from query_builder.adapters import from_json_schema, from_prisma

        # Test declarative query compilation
        spec = QuerySpec(
            table="customers",
            columns=["customers.id", "customers.name"],
            limit=10,
        )
        compiler = QueryCompiler(spec=spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()
        assert 'FROM "customers"' in sql
        assert params == [10, 0]

        # Test AST safety validation
        validation = validate_sql_ast(sql)
        assert validation["valid"] is True
        assert validation["is_read_only"] is True

        # Test JSON Schema adapter without external drivers
        raw_schema = {
            "title": "customers",
            "type": "object",
            "properties": {
                "id": {"type": "integer", "x-primary-key": True},
                "name": {"type": "string"},
            },
        }
        tables = from_json_schema(raw_schema)
        assert "customers" in tables
        assert isinstance(tables["customers"], TableSchema)
        assert "id" in tables["customers"].primary_keys

        # Test model instantiations in isolation
        col = ColumnSchema(name="id", data_type="integer", is_primary=True)
        fk = ForeignKey(
            table="orders",
            column="customer_id",
            foreign_table="customers",
            foreign_column="id",
        )
        qb_cfg = QueryBuilderConfig()
        assert col.is_primary is True
        assert fk.foreign_table == "customers"
        assert qb_cfg.default_dialect == "postgres"

        # Test Prisma parser without external drivers
        prisma_text = """
        model Customer {
          id   Int    @id
          name String
          @@map("customers")
        }
        """
        p_tables = from_prisma(prisma_text)
        assert "customers" in p_tables
        assert "id" in p_tables["customers"].primary_keys

    finally:
        for m, orig in saved_modules.items():
            if orig is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = orig


# ---------------------------------------------------------------------------
# 2. Zero-Dependency Subprocess Execution
# ---------------------------------------------------------------------------


def test_zero_dep_subprocess_execution():
    """
    Executes a pristine Python subprocess with all optional drivers blocked
    to ensure zero leakage from current interpreter runtime state.
    """
    code = """
import sys

blocked = [
    'psycopg', 'psycopg2', 'duckdb', 'sqlalchemy', 'polars',
    'mysqlclient', 'pymysql', 'snowflake', 'google', 'boto3',
    'redis', 'chromadb', 'pinecone', 'weaviate', 'pymilvus',
    'neo4j', 'taospy', 'oracledb'
]
for mod in blocked:
    sys.modules[mod] = None

import query_builder
from query_builder import QueryCompiler, QuerySpec, validate_sql_ast
from query_builder.adapters import from_prisma, from_json_schema

# 1. Compiler verification
compiler = QueryCompiler(
    spec={"table": "users", "columns": ["id", "email"], "limit": 5},
    dialect="postgres",
)
sql, params, _, _ = compiler.compile()
assert 'FROM "users"' in sql

# 2. AST validation verification
val = validate_sql_ast(sql)
assert val["valid"] is True

# 3. Adapter verification
prisma_raw = '''
model User {
  id    Int    @id
  email String
  @@map("users")
}
'''
tables = from_prisma(prisma_raw)
assert "users" in tables
assert "id" in tables["users"].primary_keys

print("SUBPROCESS_ISOLATION_VERIFIED")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Subprocess failed with stderr: {result.stderr}"
    assert "SUBPROCESS_ISOLATION_VERIFIED" in result.stdout


# ---------------------------------------------------------------------------
# 3. Schema Adapters Interoperability
# ---------------------------------------------------------------------------


def test_consumer_schema_adapters_interoperability():
    """
    Verifies that a consumer can adapt multi-table relational schemas from
    Prisma, Drizzle ORM, JSON Schema / OpenAPI, and SQLAlchemy into consistent
    Query-Builder TableSchema definitions with primary keys, foreign keys, and column types.
    """
    prisma_src = """
    enum Plan {
      FREE
      PRO
      ENTERPRISE
    }

    model Account {
      id        Int      @id @default(autoincrement())
      email     String   @unique
      plan      Plan     @default(FREE)
      createdAt DateTime @default(now())
      projects  Project[]
      @@map("accounts")
    }

    model Project {
      id        Int      @id @default(autoincrement())
      accountId Int
      account   Account  @relation(fields: [accountId], references: [id])
      name      String
      @@map("projects")
    }
    """

    drizzle_src = """
    import { pgTable, serial, integer, text, timestamp } from 'drizzle-orm/pg-core';

    export const accounts = pgTable('accounts', {
      id: serial('id').primaryKey(),
      email: text('email').notNull(),
      plan: text('plan').default('FREE'),
      createdAt: timestamp('created_at').defaultNow(),
    });

    export const projects = pgTable('projects', {
      id: serial('id').primaryKey(),
      accountId: integer('account_id').references(() => accounts.id).notNull(),
      name: text('name').notNull(),
    });
    """

    json_schema_src = {
        "components": {
            "schemas": {
                "accounts": {
                    "type": "object",
                    "required": ["id", "email"],
                    "properties": {
                        "id": {"type": "integer", "x-primary-key": True},
                        "email": {"type": "string"},
                        "plan": {"type": "string"},
                        "created_at": {"type": "string", "format": "date-time"},
                    },
                },
                "projects": {
                    "type": "object",
                    "required": ["id", "account_id", "name"],
                    "properties": {
                        "id": {"type": "integer", "x-primary-key": True},
                        "account_id": {
                            "type": "integer",
                            "x-foreign-key": "accounts.id",
                        },
                        "name": {"type": "string"},
                    },
                },
            }
        }
    }

    import textwrap

    sa_src = textwrap.dedent(
        """
        from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
        from sqlalchemy.orm import declarative_base

        Base = declarative_base()

        class Account(Base):
            __tablename__ = 'accounts'
            id = Column(Integer, primary_key=True)
            email = Column(String, nullable=False)
            plan = Column(String, default='FREE')
            created_at = Column(DateTime)

        class Project(Base):
            __tablename__ = 'projects'
            id = Column(Integer, primary_key=True)
            account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
            name = Column(String, nullable=False)
        """
    )

    p_tables = from_prisma(prisma_src)
    d_tables = from_drizzle(drizzle_src)
    j_tables = from_json_schema(json_schema_src)
    s_tables = from_sqlalchemy(sa_src)

    for adapter_name, tables in [
        ("prisma", p_tables),
        ("drizzle", d_tables),
        ("json_schema", j_tables),
        ("sqlalchemy", s_tables),
    ]:
        assert "accounts" in tables, f"{adapter_name} missing accounts table"
        assert "projects" in tables, f"{adapter_name} missing projects table"

        acc_table = tables["accounts"]
        proj_table = tables["projects"]

        # Primary key verification
        assert "id" in acc_table.primary_keys
        assert "id" in proj_table.primary_keys

        # Relationship / Foreign key verification
        assert any(fk.foreign_table == "accounts" for fk in proj_table.foreign_keys), (
            f"{adapter_name} missing foreign key from projects to accounts"
        )

        # Conversion to SchemaSnapshot interoperability
        snapshot = to_schema_snapshot(tables)
        assert "accounts" in snapshot.tables
        assert "projects" in snapshot.tables


# ---------------------------------------------------------------------------
# 4. Cross-Table Query Compilation across Dialects
# ---------------------------------------------------------------------------


def test_consumer_cross_table_query_compilation():
    """
    Verifies that a consumer can define complex multi-table queries with joins,
    aggregations, column aliases, filters, ordering, and pagination, and compile
    them cleanly across PostgreSQL, SQLite, and MySQL dialects.
    """
    spec = {
        "table": "orders",
        "columns": [
            "orders.id",
            {"column": "orders.total_amount", "alias": "order_total"},
            {"column": "customers.name", "alias": "customer_name"},
        ],
        "joins": [
            {
                "table": "customers",
                "type": "INNER JOIN",
                "on": [{"left": "orders.customer_id", "right": "customers.id"}],
            }
        ],
        "filters": [
            {"column": "orders.status", "op": "eq", "value": "COMPLETED"},
            {"column": "orders.total_amount", "op": "gt", "value": 99.50},
        ],
        "order_by": [{"column": "orders.total_amount", "direction": "DESC"}],
        "limit": 25,
        "offset": 0,
    }

    # 1. PostgreSQL dialect
    pg_compiler = QueryCompiler(spec=spec, dialect="postgres")
    pg_sql, pg_params, pg_count_sql, _ = pg_compiler.compile()
    assert 'FROM "orders"' in pg_sql
    assert 'INNER JOIN "customers"' in pg_sql
    assert 'AS "order_total"' in pg_sql
    assert 'AS "customer_name"' in pg_sql
    assert "%s" in pg_sql
    assert pg_params == ["COMPLETED", 99.50, 25, 0]
    assert "LIMIT %s" in pg_sql
    assert "COUNT(*)" in pg_count_sql

    # 2. SQLite dialect
    sqlite_compiler = QueryCompiler(spec=spec, dialect="sqlite")
    sqlite_sql, sqlite_params, _, _ = sqlite_compiler.compile()
    assert 'FROM "orders"' in sqlite_sql
    assert 'INNER JOIN "customers"' in sqlite_sql
    assert "?" in sqlite_sql
    assert sqlite_params == ["COMPLETED", 99.50, 25, 0]
    assert "LIMIT ?" in sqlite_sql

    # 3. MySQL dialect
    mysql_compiler = QueryCompiler(spec=spec, dialect="mysql")
    mysql_sql, mysql_params, _, _ = mysql_compiler.compile()
    assert "FROM `orders`" in mysql_sql
    assert "INNER JOIN `customers`" in mysql_sql
    assert "AS `order_total`" in mysql_sql
    assert "%s" in mysql_sql
    assert mysql_params == ["COMPLETED", 99.50, 25, 0]
    assert "LIMIT %s" in mysql_sql


# ---------------------------------------------------------------------------
# 5. Custom Dialect Registration
# ---------------------------------------------------------------------------


def test_consumer_custom_dialect_registration():
    """
    Verifies that a third-party developer can register a custom SQL dialect,
    compile queries against it with custom quoting and placeholders, and clean up.
    """

    class ConsumerReportingDialect(BaseDialect):
        name = "consumer_reporting"
        placeholder = "$PARAM"
        pagination_placement = "suffix"

        def quote_identifier(self, ident: str) -> str:
            parts = ident.split(".")
            return ".".join(f"[{p}]" for p in parts)

        def quote_alias(self, alias_name: str) -> str:
            return f"[{alias_name}]"

    # Register custom dialect with alias
    register_dialect("consumer_reporting", ConsumerReportingDialect, aliases=["crd"])
    assert "consumer_reporting" in list_dialects()
    assert "crd" in list_dialects()

    # Compile query using custom dialect
    spec = {
        "table": "metrics",
        "columns": ["id", {"column": "score", "alias": "metric_score"}],
        "filters": [{"column": "score", "op": "gt", "value": 85}],
        "limit": 10,
    }
    compiler = QueryCompiler(spec=spec, dialect="consumer_reporting")
    sql, params, _, _ = compiler.compile()

    assert "[metrics]" in sql
    assert "[metric_score]" in sql
    assert "$PARAM" in sql
    assert params == [85, 10, 0]

    # Also resolve through registered alias
    compiler_alias = QueryCompiler(spec=spec, dialect="crd")
    sql_alias, _, _, _ = compiler_alias.compile()
    assert "[metrics]" in sql_alias

    # Teardown
    unregister_dialect("consumer_reporting")
    unregister_dialect("crd")
    assert "consumer_reporting" not in list_dialects()


# ---------------------------------------------------------------------------
# 6. Custom Filter Operator Registration
# ---------------------------------------------------------------------------


def test_consumer_custom_filter_operator_registration():
    """
    Verifies that a consumer can register custom filter operators through
    configure_query_builder, format SQL and bind parameters, and reset cleanly.
    """

    def case_insensitive_eq_handler(
        quoted_col: str, val: Any, dialect: BaseDialect
    ) -> tuple[str, list[Any]]:
        return f"LOWER({quoted_col}) = LOWER({dialect.placeholder})", [str(val)]

    # Configure custom operator via unified configuration
    cfg = configure_query_builder(
        custom_operators={"ci_eq": case_insensitive_eq_handler}
    )
    assert "ci_eq" in cfg.custom_operators
    assert "ci_eq" in list_filter_operators()

    compiler = QueryCompiler(
        spec={
            "table": "users",
            "columns": ["id", "email"],
            "filters": [
                {
                    "column": "email",
                    "op": "ci_eq",
                    "value": "Customer@Example.com",
                }
            ],
        },
        dialect="postgres",
    )
    sql, params, _, _ = compiler.compile()

    assert (
        'LOWER("users"."email") = LOWER(%s)' in sql
        or 'LOWER("t1"."email") = LOWER(%s)' in sql
    )
    assert params[0] == "Customer@Example.com"

    # Reset configuration
    reset_query_builder_config()
    assert "ci_eq" not in list_filter_operators()

    # Attempting to compile with unregistered operator raises ValidationError
    with pytest.raises(ValidationError, match="Unsupported filter operator"):
        QueryCompiler(
            spec={
                "table": "users",
                "columns": ["id"],
                "filters": [
                    {
                        "column": "email",
                        "op": "ci_eq",
                        "value": "Customer@Example.com",
                    }
                ],
            },
            dialect="postgres",
        )


# ---------------------------------------------------------------------------
# 7. Custom Connector Lifecycle
# ---------------------------------------------------------------------------


def test_consumer_custom_connector_lifecycle():
    """
    Verifies that a consumer can subclass BaseConnector, decorate it with
    @register_connector, introspect schema, execute queries, verify secret
    scrubbing in representations, and unregister cleanly.
    """

    @register_connector("consumer_memory_db", dialect="sqlite")
    class ConsumerMemoryConnector(BaseConnector):
        dialect_name = "sqlite"

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            conn = sqlite3.connect(":memory:")
            conn.execute(
                "CREATE TABLE products (id INTEGER PRIMARY KEY, sku TEXT, price REAL);"
            )
            conn.execute(
                "INSERT INTO products (id, sku, price) VALUES (1, 'PROD-A', 49.99);"
            )
            conn.execute(
                "INSERT INTO products (id, sku, price) VALUES (2, 'PROD-B', 89.99);"
            )
            conn.commit()
            self._connection = conn

        def connect(self) -> Any:
            return self._connection

    try:
        assert "consumer_memory_db" in list_connectors()

        # Instantiate with sensitive credential
        connector = get_connector(
            "consumer_memory_db",
            api_key="SUPER_SECRET_TOKEN_999",
            password="my_db_password",
        )

        # 1. Health check
        health = connector.test_connection()
        assert health["status"] == "healthy"

        # 2. Schema introspection
        schema = connector.introspect_schema()
        assert "products" in schema["tables"]
        col_names = [c["name"] for c in schema["tables"]["products"]["columns"]]
        assert "sku" in col_names
        assert "price" in col_names

        # 3. Query execution
        result = connector.execute(
            spec={
                "table": "products",
                "columns": ["id", "sku", "price"],
                "filters": [{"column": "price", "op": "gt", "value": 50.0}],
            }
        )
        assert result["count"] == 1
        assert len(result["rows"]) == 1
        assert result["rows"][0]["sku"] == "PROD-B"
        assert result["dialect"] == "sqlite"

        # 4. Secret scrubbing in __repr__
        rep = repr(connector)
        assert "SUPER_SECRET_TOKEN_999" not in rep
        assert "my_db_password" not in rep
        assert "***" in rep

    finally:
        unregister_connector("consumer_memory_db")
        assert "consumer_memory_db" not in list_connectors()


# ---------------------------------------------------------------------------
# 8. Real SQLite Connector End-to-End Execution
# ---------------------------------------------------------------------------


def test_consumer_sqlite_connector_end_to_end(tmp_path: Path):
    """
    Creates a physical SQLite database with a multi-table relational schema
    (customers, orders, order_items), connects via SQLiteConnector, introspects
    schema, and executes queries with joins, filters, and aggregations.
    """
    db_file = tmp_path / "consumer_store.sqlite3"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            tier TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders (id)
        );
        """
    )

    # Seed data
    cur.execute("INSERT INTO customers VALUES (1, 'Alice Corp', 'ENTERPRISE');")
    cur.execute("INSERT INTO customers VALUES (2, 'Bob LLC', 'STARTER');")

    cur.execute("INSERT INTO orders VALUES (101, 1, 'FULFILLED');")
    cur.execute("INSERT INTO orders VALUES (102, 1, 'PENDING');")
    cur.execute("INSERT INTO orders VALUES (103, 2, 'FULFILLED');")

    cur.execute("INSERT INTO order_items VALUES (1, 101, 'Server Cluster', 2500.0, 1);")
    cur.execute("INSERT INTO order_items VALUES (2, 101, 'Support SLA', 500.0, 1);")
    cur.execute("INSERT INTO order_items VALUES (3, 102, 'Extra Node', 300.0, 1);")
    cur.execute("INSERT INTO order_items VALUES (4, 103, 'Starter Pack', 150.0, 1);")

    conn.commit()
    conn.close()

    # Use SQLiteConnector
    connector = SQLiteConnector(database=str(db_file))
    health = connector.test_connection()
    assert health["status"] == "healthy"

    # Schema Introspection
    schema = connector.introspect_schema()
    table_keys = set(schema["tables"].keys())
    assert {"customers", "orders", "order_items"}.issubset(table_keys)

    # Query: Enterprise customers and their fulfilled order items
    spec = {
        "table": "orders",
        "columns": [
            "orders.id",
            "customers.name",
            {"column": "order_items.price", "agg": "SUM", "alias": "total_cost"},
        ],
        "joins": [
            {
                "table": "customers",
                "type": "INNER JOIN",
                "on": [{"left": "orders.customer_id", "right": "customers.id"}],
            },
            {
                "table": "order_items",
                "type": "INNER JOIN",
                "on": [{"left": "orders.id", "right": "order_items.order_id"}],
            },
        ],
        "filters": [
            {"column": "customers.tier", "op": "eq", "value": "ENTERPRISE"},
            {"column": "orders.status", "op": "eq", "value": "FULFILLED"},
        ],
        "order_by": [{"column": "orders.id", "direction": "ASC"}],
    }

    result = connector.execute(spec=spec)
    assert result["count"] == 1
    assert len(result["rows"]) == 1

    row = result["rows"][0]
    # Sum of order 101 items (2500.0 + 500.0 = 3000.0)
    assert row["total_cost"] == 3000.0
    assert row["customers.name"] == "Alice Corp" or "Alice Corp" in row.values()
    assert result["dialect"] == "sqlite"
    assert result["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# 9. Security Governance, AST Safety & SSRF Defense
# ---------------------------------------------------------------------------


def test_consumer_security_governance_and_ast_safety():
    """
    Verifies that activating SecurityProfile.production() enforces read-only
    safety across AST validation, rejects mutation attacks and multi-statement
    injections, and blocks private/metadata network egress.
    """
    prod_profile = SecurityProfile.production()
    configure_security(prod_profile)
    active_sec = get_security_config()
    assert active_sec.execution.enforce_read_only_session is True
    assert active_sec.network.allow_private_networks is False

    # 1. Block destructive SQL mutations
    forbidden_queries = [
        "DROP TABLE customers;",
        "DELETE FROM orders WHERE id = 1;",
        "INSERT INTO customers (id, name) VALUES (99, 'Hacker');",
        "ALTER TABLE customers ADD COLUMN compromised TEXT;",
        "TRUNCATE TABLE order_items;",
        "SELECT id FROM customers; DROP TABLE orders;",
    ]
    for bad_sql in forbidden_queries:
        res = validate_sql_ast(bad_sql)
        assert res["valid"] is False, f"Expected validation failure for: {bad_sql}"
        assert res["is_read_only"] is False or res["injection_risk"] in (
            "HIGH",
            "CRITICAL",
        )

    # 2. Allow complex read-only analytical SQL
    safe_query = """
    WITH regional_summary AS (
        SELECT customer_id, SUM(amount) AS total_spent
        FROM orders
        WHERE status = 'PAID'
        GROUP BY customer_id
    )
    SELECT c.name, rs.total_spent
    FROM customers c
    JOIN regional_summary rs ON c.id = rs.customer_id
    ORDER BY rs.total_spent DESC
    LIMIT 20;
    """
    res_safe = validate_sql_ast(safe_query)
    assert res_safe["valid"] is True
    assert res_safe["is_read_only"] is True
    assert res_safe["injection_risk"] in ("NONE", "LOW")

    # 3. SSRF network egress defense
    with pytest.raises(SecurityError, match="(?i)(private|blocked|loopback)"):
        validate_network_target(host="127.0.0.1", config=active_sec)

    with pytest.raises(SecurityError, match="(?i)(private|blocked|loopback|metadata)"):
        validate_network_target(host="169.254.169.254", config=active_sec)


# ---------------------------------------------------------------------------
# 10. CLI Workflow (Validate, Compile, Export-Schema)
# ---------------------------------------------------------------------------


def test_consumer_cli_workflow(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    """
    Simulates a developer or CI/CD workflow executing CLI subcommands:
    - query-builder validate (valid query and blocked mutation)
    - query-builder compile (compiling JSON spec to SQL)
    - query-builder export-schema (converting schema snapshot to Prisma/Drizzle)
    """
    # 1. CLI Validate — Valid query
    ret_val = cli_main(
        ["validate", "--json", "SELECT id, name FROM customers LIMIT 10;"]
    )
    assert ret_val == 0
    cap_val = capsys.readouterr()
    res_val = json.loads(cap_val.out)
    assert res_val["valid"] is True
    assert res_val["statement_type"] == "SELECT"

    # CLI Validate — Blocked mutation
    ret_bad = cli_main(["validate", "--json", "DROP TABLE customers;"])
    assert ret_bad == 1
    cap_bad = capsys.readouterr()
    res_bad = json.loads(cap_bad.out)
    assert res_bad["valid"] is False
    assert res_bad["injection_risk"] == "CRITICAL"

    # 2. CLI Compile
    spec_data = {
        "table": "customers",
        "columns": ["customers.id", "customers.name"],
        "limit": 10,
    }
    schema_data = {
        "tables": {
            "customers": {
                "columns": [
                    {"name": "id", "data_type": "integer", "is_primary": True},
                    {"name": "name", "data_type": "text"},
                ]
            }
        }
    }
    spec_file = tmp_path / "cli_spec.json"
    schema_file = tmp_path / "cli_schema.json"
    spec_file.write_text(json.dumps(spec_data))
    schema_file.write_text(json.dumps(schema_data))

    ret_comp = cli_main(
        [
            "compile",
            "--spec",
            str(spec_file),
            "--schema",
            str(schema_file),
            "--dialect",
            "postgres",
            "--json",
        ]
    )
    assert ret_comp == 0
    cap_comp = capsys.readouterr()
    res_comp = json.loads(cap_comp.out)
    assert "main_sql" in res_comp
    assert 'FROM "customers"' in res_comp["main_sql"]

    # 3. CLI Export-Schema
    ret_exp = cli_main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "prisma",
            "--json",
        ]
    )
    assert ret_exp == 0
    cap_exp = capsys.readouterr()
    res_exp = json.loads(cap_exp.out)
    assert res_exp["success"] is True
    assert res_exp["format"] == "prisma"
    assert "model Customer" in res_exp["content"]
