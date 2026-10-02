# Query Builder ⚡

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![React 18+](https://img.shields.io/badge/React-18+-61dafb.svg)](https://react.dev/)

A modern, production-grade **declarative SQL compiler, AST safety validator, and embeddable React visual query studio**. Designed for applications requiring safe, tenant-isolated, multi-dialect SQL generation and interactive visual query exploration without exposing database internals or opening SQL injection vulnerabilities.

---

## 🌟 Key Capabilities

### 1. 🐍 Python Query Engine (`query_builder`)
- **Declarative Query Compilation:** Compiles structured JSON query specifications into safe, parameterized SQL with full bind parameter isolation.
- **Multi-Dialect Support:** Pluggable dialect layer with native quoting and syntax for **PostgreSQL**, **Snowflake**, **Microsoft SQL Server** (`OFFSET ... FETCH NEXT`), **SQLite**, and **MySQL**.
- **AST Safety Validation:** Powered by `sqlparse`, enforces strict read-only execution by blocking mutation keywords (`DELETE`, `DROP`, `UPDATE`, `INSERT`, `TRUNCATE`, `ALTER`, `GRANT`, `REVOKE`, `INTO`, `COPY`), blocking semicolon query-chaining, and restricting access to administrative/credential schemas and tables (`auth_user`, `django_session`, `pg_shadow`, etc.).
- **Automatic Graph Join Solver:** Uses Breadth-First Search (BFS) over schema foreign key constraints and canonical entity bridges to find the shortest multi-hop join path automatically.
- **Fail-Closed Tenant Isolation:** Automatically injects row-level ownership and multi-tenant isolation predicates walking foreign key chains. Refuses to query tables without verifiable ownership paths.
- **Derived Aggregations & Pagination:** Generates derived `GROUP BY` clauses, `HAVING` filters, bounded pagination, and matching `COUNT(*)` subqueries.
- **CLI Utility:** Includes `query-builder` CLI for compiling specs, validating SQL, and resolving join paths directly from the terminal.

### 2. ⚛️ React Visual Query Studio (`@jacob-white/query-builder-react`)
- **Visual Table Canvas:** Interactive cards for tables, showing primary key indicators, data types, and selectable projections.
- **Interactive Relational Joins:** Visual join builder supporting `LEFT JOIN`, `INNER JOIN`, and `RIGHT JOIN` with 1-click automatic join condition discovery.
- **Complex Filter Builder:** Dynamic filter conditions supporting `=`, `!=`, `>`, `<`, `>=`, `<=`, `STARTS WITH`, `ENDS WITH`, `CONTAINS`, `LIKE`, `ILIKE`, `IN`, `NOT IN`, `BETWEEN`, `IS NULL`, and `IS NOT NULL`.
- **Projection & Aggregation Configurator:** Column reordering with aggregate functions (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`) and custom aliases.
- **Schema ERD Inspector:** Modal dialog showing full Entity-Relationship Diagram of tables, columns, and foreign keys.
- **Data Results Workbench:** Live query runner with latency metrics, row search, and CSV export.
- **Synchronized Raw SQL Editor:** Real-time bidirectional synchronization between visual canvas and syntax-checked SQL.

---

## 📦 Project Layout

```text
Query-Builder/
├── query_builder/               # Standalone Python Query Engine
│   ├── compiler.py              # Declarative JSON spec -> parameterized SQL compiler
│   ├── ast_validator.py         # AST parser & SQL injection safety validator (sqlparse)
│   ├── dialects.py              # Multi-dialect abstraction (Postgres, Snowflake, MSSQL, SQLite, MySQL)
│   ├── join_solver.py           # BFS graph join path and condition solver
│   ├── security.py              # Multi-tenant and user ownership isolation
│   ├── schema.py                # Schema metadata normalization and filtering
│   ├── executor.py              # DB-API read-only execution harness with latency profiling
│   ├── models.py                # Dataclass models for specifications and schemas
│   └── cli.py                   # Terminal CLI tool (query-builder)
├── tests/                       # Complete pytest suite (100% passing)
├── packages/
│   └── react/                   # Standalone React UI Component Library
│       ├── src/
│       │   ├── components/      # VisualQueryBuilder, QueryCanvas, TableCard, SchemaErdModal, etc.
│       │   ├── utils/           # Client-side compiler, AST safety, and join solvers
│       │   └── index.ts         # Public React exports
│       ├── tests/               # Vitest suite for UI compilation and safety
│       └── package.json         # @jacob-white/query-builder-react
├── pyproject.toml               # Python package configuration
└── requirements.txt             # Python dependencies
```

---

## 🚀 Quickstart: Python Engine

### Installation

```bash
# Direct from GitHub
pip install "query-builder-engine @ git+https://github.com/Jacob-white/Query-Builder.git"

# Local editable install
pip install -e /home/jwhite/Query-Builder
```

### Declarative Query Compilation

```python
from query_builder import QueryCompiler

spec = {
    "table": "orders",
    "columns": [
        "orders.id",
        {"column": "orders.amount", "agg": "sum", "alias": "total_revenue"},
    ],
    "joins": [
        {
            "table": "users",
            "type": "LEFT JOIN",
            "on": [{"left": "orders.user_id", "right": "users.id"}],
        }
    ],
    "filters": [
        {"column": "orders.status", "op": "eq", "value": "COMPLETED"},
        {"column": "orders.amount", "op": "gt", "value": 100},
    ],
    "filter_join": "AND",
    "order_by": [
        {"column": "orders.id", "direction": "DESC"}
    ],
    "limit": 25,
    "offset": 0,
}

compiler = QueryCompiler(spec, dialect="postgres")
main_sql, params, count_sql, count_params = compiler.compile()

print(main_sql)
# SELECT "t1"."id" AS "orders.id", SUM("t1"."amount") AS "total_revenue"
# FROM "orders" "t1"
# LEFT JOIN "users" "t2" ON "t1"."user_id" = "t2"."id"
# WHERE ("t1"."status" = %s AND "t1"."amount" > %s)
# GROUP BY "t1"."id"
# ORDER BY "t1"."id" DESC
# LIMIT %s OFFSET %s

print(params)
# ['COMPLETED', 100, 25, 0]
```

### AST Safety Validation

```python
from query_builder import validate_sql_ast

# 1. Safe analytical query
result = validate_sql_ast("SELECT legal_name, total_aum FROM production.firm_master LIMIT 50;")
assert result["valid"] is True
assert result["is_read_only"] is True

# 2. Blocked mutation
blocked = validate_sql_ast("DELETE FROM production.firm_master WHERE id = 1;")
assert blocked["valid"] is False
assert blocked["injection_risk"] == "CRITICAL"

# 3. Blocked query chaining
chain = validate_sql_ast("SELECT 1; DROP TABLE users;")
assert chain["valid"] is False
assert chain["statement_type"] == "MULTI_STATEMENT"
```

### Graph Join Pathfinding

```python
from query_builder import find_join_path

schema = {
    "tables": {
        "firms": {"columns": [{"name": "id"}]},
        "branches": {"columns": [{"name": "id"}, {"name": "firm_id"}, {"name": "address_id"}]},
        "addresses": {"columns": [{"name": "id"}, {"name": "city"}]},
    },
    "foreign_keys": [
        {"table": "branches", "column": "firm_id", "foreign_table": "firms", "foreign_column": "id"},
        {"table": "branches", "column": "address_id", "foreign_table": "addresses", "foreign_column": "id"},
    ],
}

# Automatically discovers multi-hop join: firms -> branches -> addresses
path = find_join_path(active_tables=["firms"], target_table="addresses", schema_data=schema)
print(path)
# [
#   {'type': 'LEFT JOIN', 'left_table': 'firms', 'left_col': 'id', 'table': 'branches', 'right_col': 'firm_id'},
#   {'type': 'LEFT JOIN', 'left_table': 'branches', 'left_col': 'address_id', 'table': 'addresses', 'right_col': 'id'}
# ]
```

### CLI Commands

```bash
# Validate SQL
query-builder validate "SELECT id, name FROM users LIMIT 10;"

# Compile JSON specification
query-builder compile --spec query_spec.json --dialect snowflake

# Find relational join path
query-builder join-path --active firms --target addresses --schema schema.json
```

---

## 🎨 Quickstart: React Visual Studio

### Installation

```bash
pnpm add @jacob-white/query-builder-react
# or
npm install @jacob-white/query-builder-react
```

### Embed in Any React Application

```tsx
import React, { useState } from "react";
import { VisualQueryBuilder, type SchemaSnapshot, type QueryResultData } from "@jacob-white/query-builder-react";

export function SqlStudioPage() {
  const [schema] = useState<SchemaSnapshot>({
    tables: {
      users: {
        name: "users",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "email", data_type: "text", is_nullable: false, is_primary: false },
          { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
        ],
      },
      orders: {
        name: "orders",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
        ],
      },
    },
    foreign_keys: [
      { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
    ],
  });

  const handleExecute = async (sql: string, spec?: Record<string, unknown>): Promise<QueryResultData> => {
    const res = await fetch("/api/v1/sql-builder/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: sql, spec }),
    });
    return await res.json();
  };

  return (
    <div style={{ padding: "24px", maxWidth: "1400px", margin: "0 auto" }}>
      <h1>Interactive SQL Studio</h1>
      <VisualQueryBuilder
        schema={schema}
        initialTable="users"
        onExecuteQuery={handleExecute}
      />
    </div>
  );
}
```

---

## 🧪 Testing & Verification

### Running Python Tests
```bash
cd /home/jwhite/Query-Builder
.venv/bin/pytest -v --cov=query_builder
```

### Running React UI Tests
```bash
cd /home/jwhite/Query-Builder/packages/react
pnpm test
pnpm build
```

---

## 📄 License

MIT © 2026 Jacob White.
