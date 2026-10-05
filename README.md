# Query Builder ⚡

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![React 18+](https://img.shields.io/badge/React-18+-61dafb.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178c6.svg)](https://www.typescriptlang.org/)

A turnkey, developer-first **declarative SQL compiler, AST safety validator, ORM schema adapter suite, and embeddable React visual query studio**. Designed for applications requiring safe, tenant-isolated, multi-dialect SQL generation and interactive visual query exploration without exposing database internals or opening SQL injection vulnerabilities.

---

## 📚 Documentation & Quickstarts

- **[5-Minute Quickstart Guide](docs/quickstart.md)** — Step-by-step onboarding for Python backend and React frontend.
- **[Full-Stack Starter Template](examples/fullstack_starter/README.md)** — Standalone runnable project (FastAPI + React 18 + Vite + SQLite).
- **[Complete API Reference](docs/api_reference.md)** — Exhaustive reference for all Python and TypeScript public APIs.

---

## 🌟 Key Capabilities

### 1. 🐍 Python Core Engine & Ecosystem (`query_builder`)
- **Zero-Dependency Core & Modular Extras**: Lightweight core engine with optional connector driver extras (`[sqlite]`, `[postgres]`, `[snowflake]`, `[mysql]`, `[all]`).
- **1-Line Declarative ORM Adapters**: Instant introspection from **Prisma** (`from_prisma`), **Drizzle ORM** (`from_drizzle`), **SQLAlchemy** (`from_sqlalchemy`), and **JSON Schema / OpenAPI 3.x** (`from_json_schema`).
- **Declarative Query Compilation**: Compiles structured JSON query specifications into safe, parameterized SQL with full bind parameter isolation across 71+ dialects.
- **AST Safety & Policy Governance**: Enforces read-only execution by blocking mutation keywords (`DELETE`, `DROP`, `UPDATE`, `INSERT`, `TRUNCATE`), multi-statement semicolons, and sensitive schema access (`auth_user`, `pg_shadow`).
- **Security Profiles & Unified Config**: Out-of-the-box profiles (`development`, `production`, `strict`) governing timeouts, row ceilings, complexity scoring, and SSRF egress filtering.
- **Automatic Graph Join Solver**: Uses Breadth-First Search (BFS) over schema foreign keys to compute the shortest multi-hop join path automatically.
- **Connectors & Async Execution**: Synchronous (`BaseConnector`) and asynchronous (`AsyncBaseConnector`) execution across 198 registered connector aliases.
- **Microservice HTTP Server**: Built-in zero-dependency HTTP microservice (`query-builder serve`) with OpenAPI 3.1 and interactive Swagger UI documentation at `/docs`.

### 2. ⚛️ React Visual Query Studio & Headless SDK (`@jacob-white/query-builder-react`)
- **Visual Studio Mode**: Drag-and-drop table canvas (`QueryCanvas`), relational join builder, interactive filters, projection reordering, aggregations, and ERD modal.
- **Headless Unstyled Mode**: Zero-CSS headless hooks (`useQueryBuilder`, `useQueryExecution`, `useSchemaIntrospection`) for custom design systems (Tailwind CSS, shadcn/ui, Radix).
- **Container-Scoped Theming**: Isolated CSS variables (`--qb-*`) via `QueryBuilderProvider` without stylesheet collisions or layout breakage.
- **TypeScript ORM Adapters**: Browser/Node runtime schema adapters (`fromPrisma`, `fromDrizzle`, `fromSqlAlchemy`, `fromJsonSchema`, `toSchemaSnapshot`).
- **Extensible Hook Points**: Custom filter operators (`customOperators`), custom field renderers (`fieldRenderers`), and custom cell formatters (`cellRenderers`).
- **Bidirectional State Synchronization**: Instant synchronization between visual query canvas, query spec, and syntax-checked raw SQL.

---

## 📦 Project Layout

```text
Query-Builder/
├── query_builder/               # Standalone Python Query Engine
│   ├── adapters/                # 1-line ORM adapters (Prisma, Drizzle, SQLAlchemy, JSON Schema)
│   ├── compiler.py              # Declarative JSON spec -> parameterized SQL compiler
│   ├── ast_validator.py         # AST parser & SQL injection safety validator
│   ├── config.py                # SecurityConfig, SecurityProfile, configure_query_builder
│   ├── dialects/                # 71+ dialect definitions (Postgres, Snowflake, SQLite, etc.)
│   ├── connectors/              # BaseConnector, AsyncBaseConnector, SQLiteConnector, etc.
│   ├── join_solver.py           # BFS graph join path and condition solver
│   ├── server.py                # Zero-dependency HTTP microservice & Swagger UI
│   ├── models.py                # Dataclasses (TableSchema, QuerySpec, SchemaSnapshot)
│   └── cli.py                   # Terminal CLI tool (query-builder)
├── docs/                        # Comprehensive Documentation
│   ├── quickstart.md            # 5-minute setup guide
│   └── api_reference.md         # Exhaustive public API reference
├── examples/                    # Runnable Starter Examples
│   └── fullstack_starter/       # FastAPI + React 18 + Vite + SQLite turnkey template
├── packages/
│   └── react/                   # Standalone React Component & Headless SDK
│       ├── src/
│       │   ├── adapters/        # TypeScript ORM schema adapters
│       │   ├── components/      # VisualQueryBuilder, QueryCanvas, TableCard, etc.
│       │   ├── hooks/           # useQueryBuilder, useQueryExecution, useSqlCompiler
│       │   ├── theme/           # QueryBuilderProvider, ThemeProvider, design tokens
│       │   └── index.ts         # Public React exports
│       ├── dist/                # ESM, CJS, and TypeScript declaration bundles
│       └── package.json         # @jacob-white/query-builder-react
├── tests/                       # Complete pytest suite
└── pyproject.toml               # Python package configuration
```

---

## 🚀 Python Engine Quickstart

### Installation

```bash
# Core + SQLite (zero external dependencies)
pip install "query-builder-engine[sqlite]"

# Core + PostgreSQL
pip install "query-builder-engine[postgres]"

# All connectors
pip install "query-builder-engine[all]"
```

### 1-Line ORM Schema Adapters

```python
from query_builder.adapters import (
    from_prisma,
    from_drizzle,
    from_sqlalchemy,
    to_schema_snapshot,
)

# 1. Prisma
prisma_tables = from_prisma("""
  model User {
    id     Int     @id @default(autoincrement())
    email  String  @unique
    orders Order[]
  }
  model Order {
    id     Int   @id @default(autoincrement())
    userId Int   @map("user_id")
    user   User  @relation(fields: [userId], references: [id])
  }
""")

# 2. Drizzle ORM
drizzle_tables = from_drizzle(
    "export const users = sqliteTable('users', { id: integer('id').primaryKey() });"
)

# 3. SQLAlchemy
sqlalchemy_tables = from_sqlalchemy(metadata_or_model_code)

# Synthesize into unified SchemaSnapshot for UI or compiler
snapshot = to_schema_snapshot(prisma_tables)
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
    "order_by": [{"column": "orders.id", "direction": "DESC"}],
    "limit": 25,
    "offset": 0,
}

compiler = QueryCompiler(spec, dialect="sqlite")
main_sql, params, count_sql, count_params = compiler.compile()

print(main_sql)
# SELECT "t1"."id" AS "orders.id", SUM("t1"."amount") AS "total_revenue"
# FROM "orders" "t1"
# LEFT JOIN "users" "t2" ON "t1"."user_id" = "t2"."id"
# WHERE ("t1"."status" = ? AND "t1"."amount" > ?)
# GROUP BY "t1"."id"
# ORDER BY "t1"."id" DESC
# LIMIT ? OFFSET ?
```

### Connector Execution

```python
from query_builder import SQLiteConnector

connector = SQLiteConnector("app.db")
result = connector.execute(
    spec={"table": "orders", "columns": ["orders.id", "orders.total"]}
)
print("Result rows:", result["rows"])
print("Execution latency:", result["latency_ms"], "ms")
```

### HTTP Microservice & OpenAPI 3.1

```bash
query-builder serve --host 127.0.0.1 --port 8000 --profile development
# Browse Swagger UI docs at http://127.0.0.1:8000/docs
```

---

## 🎨 React Visual Studio & Headless SDK

### Installation

```bash
pnpm add @jacob-white/query-builder-react
# or
npm install @jacob-white/query-builder-react
```

### 1. Styled Visual Studio Mode

```tsx
import React, { useState } from "react";
import {
  QueryBuilderProvider,
  VisualQueryBuilder,
  fromPrisma,
  toSchemaSnapshot,
  type QueryResultData,
} from "@jacob-white/query-builder-react";

const prismaSchema = `
  model User {
    id    Int    @id @default(autoincrement())
    email String
    role  String
  }
`;

export function App() {
  const [schema] = useState(() => toSchemaSnapshot(fromPrisma(prismaSchema)));

  const handleExecute = async (sql: string, spec?: Record<string, unknown>): Promise<QueryResultData> => {
    const res = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec }),
    });
    return await res.json();
  };

  return (
    <QueryBuilderProvider mode="styled" themeMode="dark">
      <div style={{ height: "100vh" }}>
        <VisualQueryBuilder
          schema={schema}
          initialTable="User"
          dialect="sqlite"
          onExecuteQuery={handleExecute}
        />
      </div>
    </QueryBuilderProvider>
  );
}
```

### 2. Unstyled Headless Mode

Build completely custom interfaces with zero CSS opinions:

```tsx
import React from "react";
import { useQueryBuilder, useQueryExecution } from "@jacob-white/query-builder-react";

export function HeadlessEditor({ schema }: { schema: any }) {
  const { state, compiled, actions } = useQueryBuilder({ schema, initialTable: "users" });
  const { results, isLoading, executeQuery } = useQueryExecution({
    onExecuteQuery: async (sql, spec) => {
      const res = await fetch("/api/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec }),
      });
      return await res.json();
    },
  });

  return (
    <div className="p-4 space-y-4">
      <select
        value={state.primaryTable}
        onChange={(e) => actions.setPrimaryTable(e.target.value)}
        className="border p-2 rounded"
      >
        {Object.keys(schema.tables).map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>
      <pre className="bg-gray-900 text-white p-3 rounded">{compiled.sql}</pre>
      <button
        onClick={() => executeQuery(compiled.sql, compiled.spec)}
        disabled={isLoading}
        className="px-4 py-2 bg-blue-600 text-white rounded"
      >
        {isLoading ? "Executing..." : "Run Query"}
      </button>
    </div>
  );
}
```

---

## 🧪 Testing & Verification

Query-Builder adheres to strict resource-throttled, sequential testing:

```bash
# 1. Run Python test suite
.venv/bin/pytest tests/ -v

# 2. Run React test suite (Vitest workers capped at 2)
cd packages/react
pnpm typecheck
pnpm build
VITEST_MAX_WORKERS=2 pnpm test

# 3. Linter & formatting checks
.venv/bin/ruff check query_builder tests examples
.venv/bin/ruff format --check query_builder tests examples
```

---

## 📄 License

MIT © 2026 Jacob White.
