# Query Builder ⚡

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![React 18+](https://img.shields.io/badge/React-18+-61dafb.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178c6.svg)](https://www.typescriptlang.org/)

A turnkey, developer-first **declarative SQL compiler, AST safety validator, enterprise security governor, bidirectional ORM schema converter, Model Context Protocol (MCP) server, and embeddable React visual studio**. Designed for applications requiring safe, tenant-isolated, multi-dialect SQL generation and interactive visual query exploration without exposing database internals or opening SQL injection vulnerabilities.

---

## 📚 Documentation & Quickstarts

- **[5-Minute Quickstart Guide](docs/quickstart.md)** — Step-by-step onboarding for Python backend, FastAPI/Django integrations, and React frontend studio.
- **[React Studio Package README](packages/react/README.md)** — Exhaustive guide for `@jacob-white/query-builder-react` (subpaths, client, compound components, controlled mode, and OLAP).
- **[Complete API Reference](docs/api_reference.md)** — Exhaustive reference for all Python and TypeScript public APIs.
- **[Full-Stack Starter Template](examples/fullstack_starter/README.md)** — Standalone runnable project (FastAPI + React 18 + Vite + SQLite).
- **[Security Policy & Sandboxing Guide](SECURITY.md)** — Vulnerability reporting, zero-trust query isolation, AST validation, and defense-in-depth architecture.
- **[Documentation Index & Specifications](docs/README.md)** — Master index for all guides, API specs, connector roadmaps, and testing invariants.

---

## 🌟 Key Capabilities

### 1. 🐍 Python Core Engine & Ecosystem (`query_builder`)
- **Declarative Multi-Dialect Query Compiler**: Compiles JSON query specs into safe, parameterized SQL with bind parameter isolation across **71+ SQL dialects** (PostgreSQL, Snowflake, MySQL, SQLite, DuckDB, ClickHouse, Microsoft SQL Server, BigQuery, Oracle, Trino, Redshift, etc.).
- **Analytical SQL Expressiveness**: First-class support for `CASE WHEN` conditional expressions (`CaseWhenSpec`), set operations (`SetOperationSpec`: `UNION`, `UNION ALL`, `INTERSECT`, `EXCEPT`), OLAP grouping sets (`grouping_type`: `"rollup"`, `"cube"`, `"grouping_sets"`), and window functions (`WindowFunctionSpec` / `WindowSpec`, `WindowFrameSpec` with `PARTITION BY`, `ORDER BY`, and `ROWS`/`RANGE`/`GROUPS` frames).
- **AST Safety & Mutation Blocking**: Deep AST parsing (`validate_sql_ast`) blocking mutation keywords (`RESTRICTED_MUTATION_KEYWORDS`), multi-statement semicolons, and sensitive schema tables (`RESTRICTED_SECURITY_TABLES`).
- **Enterprise Security Governor**: Multi-tenant fail-closed isolation (`SecurityPolicy` / `SecurityGovernor`, `TenantContext`), Role-Based Column-Level Access Control (CLAC via `ColumnPolicy`), dynamic attribute ABAC filters (`RowPolicy`), table allow/denylists (`TablePolicy`), and pre-execution AST complexity quota enforcement.
- **Async Connection Pooling & Streaming**: High-concurrency non-blocking connection pool (`AsyncConnectionPool` / `AsyncQueryPool`, `AsyncConnectionPoolManager`) with cooperative query cancellation (`AsyncCancellationToken`), statement timeouts, and streaming chunk exports (`AsyncStreamingExecutor`, `stream_export_dataset`).
- **Turnkey Framework Integrations**: 1-line router factories for **FastAPI** (`create_query_builder_router`), **Django** (`create_django_urls`), **Django REST Framework** (`create_drf_views`), and **Django Ninja** (`create_ninja_router`) with built-in schema, compile, validate, execute, and export endpoints.
- **Bidirectional Schema Converters**: Instant import from Prisma, Drizzle, SQLAlchemy, JSON Schema, and export back to production-ready definitions (`to_prisma_schema`, `to_drizzle_schema`, `to_sqlalchemy_models`).
- **Model Context Protocol (MCP) Server & CLI**: Built-in JSON-RPC 2.0 stdio server (`query-builder mcp`) exposing query compilation, AST validation, execution, and join path tools to AI assistants (Claude Desktop, Cursor, Windsurf), plus terminal utilities (`query-builder init`, `doctor`, `serve`, `schema`).

### 2. ⚛️ React Visual Query Studio & Headless SDK (`@jacob-white/query-builder-react`)
- **Multi-Entry Subpath Architecture**: Modern exports for `@jacob-white/query-builder-react`, `@jacob-white/query-builder-react/client`, `@jacob-white/query-builder-react/adapters`, `@jacob-white/query-builder-react/hooks`, and `@jacob-white/query-builder-react/olap`.
- **First-Class Typed API Client**: Zero-dependency typed client (`createQueryBuilderClient`, `createQuery`, `FluentQuery`) with dynamic authorization headers, per-request timeouts, and `AbortSignal` cancellation.
- **Controlled & Uncontrolled Studio**: `<VisualQueryBuilder>` with `value`, `onChange` (canonical AST diffing), `client` auto-wiring, 50-step undo/redo history, imperative ref handle (`VisualQueryBuilderRef`), and schema diagnostics (`validateSchema`).
- **Composable Compound Components**: Atomic studio primitives (`QueryBuilderRoot`, `QueryBuilderCanvas`, `QueryBuilderColumns`, `QueryBuilderFilters`, `QueryBuilderJoins`, `QueryBuilderSorts`, `QueryBuilderSqlEditor`, `QueryBuilderResults`) with slotted Tailwind CSS styling (`classNames`).
- **In-Memory Client OLAP Engine**: In-browser columnar execution (`InMemoryOlapEngine`, `getClientOlapEngine`) and local file ingestion (`ingestLocalFile`) for CSV, TSV, Parquet, and JSON with zero server latency.
- **TypeScript Schema Adapters**: Browser/Node runtime schema converters (`fromPrisma`, `toPrismaSchema`, `fromDrizzle`, `toDrizzleSchema`, `fromSqlAlchemy`, `toSqlAlchemyModels`, `fromJsonSchema`, `createSemanticModel`).
- **Headless Hooks & Container Theming**: Unstyled hooks (`useQueryBuilder`, `useQueryExecution`, `useSchemaIntrospection`) and container-scoped CSS custom properties (`--qb-*`).

---

## 📦 Project Layout

```text
Query-Builder/
├── query_builder/               # Standalone Python Query Engine
│   ├── adapters/                # 1-line ORM adapters (Prisma, Drizzle, SQLAlchemy, JSON Schema)
│   ├── compiler.py              # Declarative JSON spec -> parameterized SQL compiler
│   ├── ast_validator.py         # AST parser & SQL injection safety validator
│   ├── policy.py                # SecurityPolicy, SecurityGovernor, TenantContext, CLAC
│   ├── async_pool.py            # AsyncConnectionPool, AsyncQueryPool, AsyncCancellationToken
│   ├── executor.py              # async_execute, execute_cursor_query, execute_compiled_spec
│   ├── export.py                # stream_export_dataset, export_dataset (CSV, Parquet, Excel)
│   ├── integrations/            # FastAPI, Django, DRF, and Django Ninja router factories
│   ├── schema_converters.py     # to_prisma_schema, to_drizzle_schema, to_sqlalchemy_models
│   ├── mcp_server.py            # Model Context Protocol (MCP) JSON-RPC 2.0 stdio server
│   ├── config.py                # SecurityConfig, SecurityProfile, configure_query_builder
│   ├── dialects/                # 71+ dialect definitions (Postgres, Snowflake, SQLite, etc.)
│   ├── connectors/              # BaseConnector, AsyncBaseConnector, SQLiteConnector, etc.
│   ├── join_solver.py           # BFS graph join path and condition solver
│   ├── models.py                # Dataclasses (TableSchema, QuerySpec, WindowFunctionSpec, etc.)
│   └── cli.py                   # Terminal CLI tool (query-builder)
├── docs/                        # Comprehensive Documentation
│   ├── quickstart.md            # 5-minute setup guide
│   └── api_reference.md         # Exhaustive public API reference
├── examples/                    # Runnable Starter Examples
│   └── fullstack_starter/       # FastAPI + React 18 + Vite + SQLite turnkey template
├── packages/
│   └── react/                   # React Visual Studio Library (@jacob-white/query-builder-react)
│       ├── src/
│       │   ├── client/          # createQueryBuilderClient, FluentQuery, createQuery
│       │   ├── adapters/        # TypeScript ORM schema adapters & exporters
│       │   ├── components/      # VisualQueryBuilder, QueryCanvas, compound components
│       │   ├── drivers/         # InMemoryOlapEngine & DuckDB driver
│       │   ├── hooks/           # useQueryBuilder, useQueryExecution, useSchemaIntrospection
│       │   ├── olap/            # Client OLAP and local file ingest entry point
│       │   ├── theme/           # QueryBuilderProvider, ThemeProvider, design tokens
│       │   └── index.ts         # Public React exports
│       ├── README.md            # Dedicated React Studio documentation
│       └── package.json         # Package configuration & subpaths
├── tests/                       # Complete backend test suite
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

# Connector families: sql, cloud-warehouses, nosql, vector, streaming
pip install "query-builder-engine[sql]"

# FastAPI / Django integrations and the MCP server entry point (`query-builder-mcp`)
pip install "query-builder-engine[server]"
pip install "query-builder-engine[django]"

# Every driver that installs from wheels on Linux, macOS and Windows
pip install "query-builder-engine[all]"

# Also the drivers that need a C toolchain / vendor client library / JVM
# (mysqlclient, pymssql, pyodbc, ibm-db, ...). May fail on some platforms.
pip install "query-builder-engine[all-native]"
```

Each connector also has its own extra (`[snowflake]`, `[bigquery]`, `[mysql]`, ...); see
`[project.optional-dependencies]` in `pyproject.toml`. The wheel ships type information (`py.typed`).

---

### 1. Declarative Query Compilation with Analytical Expressiveness

```python
from query_builder import QueryCompiler, WindowFunctionSpec, WindowFrameSpec

spec = {
    "table": "orders",
    "columns": [
        "orders.id",
        "orders.customer_id",
        {"column": "orders.amount", "agg": "sum", "alias": "total_spend"},
        {
            "case_when": {
                "branches": [
                    {
                        "condition": {
                            "column": "orders.amount",
                            "op": "gte",
                            "value": 1000,
                        },
                        "then_value": "VIP",
                    },
                    {
                        "condition": {
                            "column": "orders.amount",
                            "op": "gte",
                            "value": 200,
                        },
                        "then_value": "Regular",
                    },
                ],
                "else_value": "Standard",
            },
            "alias": "customer_tier",
        },
    ],
    "joins": [
        {
            "table": "users",
            "type": "LEFT JOIN",
            "on": [{"left": "orders.customer_id", "right": "users.id"}],
        }
    ],
    "window_functions": [
        WindowFunctionSpec(
            function="RANK",
            order_by=[{"column": "orders.amount", "direction": "DESC"}],
            alias="spending_rank",
        )
    ],
    "grouping_type": "rollup",
    "limit": 25,
}

compiler = QueryCompiler(spec, dialect="postgres")
main_sql, params, count_sql, count_params = compiler.compile()

print(main_sql)
```

---

### 2. Multi-Tenant Enterprise Security Governor & CLAC

Enforce fail-closed row-level tenant filtering, Role-Based Column-Level Access Control (CLAC), and AST complexity quotas:

```python
from query_builder import (
    SecurityPolicy,
    TenantContext,
    apply_security_policy,
)

# Define governance policy
policy = SecurityPolicy(
    enforce_tenant_isolation=True,
    tenant_column="tenant_id",
    max_complexity_score=50,
    column_permissions={
        "employees": {
            "allowed_roles": ["finance", "hr_admin"],
            "restricted_columns": ["salary", "ssn"],
        }
    },
)

# User authentication context
context = TenantContext(
    tenant_id="tenant-alpha",
    user_id="usr_42",
    roles=["engineer"],
)

spec = {
    "table": "employees",
    "columns": ["id", "name", "salary"],
}

# Automatically fails closed or strips unauthorized columns
try:
    secure_spec = apply_security_policy(spec, context=context, policy=policy)
except Exception as err:
    print(f"Rejected: {err}")
    # Access to restricted column 'salary' on table 'employees' requires roles: ['finance', 'hr_admin']
```

---

### 3. Turnkey Web Framework Routers

#### FastAPI Integration:
```python
from fastapi import FastAPI, Request
from query_builder import SQLiteConnector, create_query_builder_router, TenantContext

app = FastAPI()
connector = SQLiteConnector("app.db")


async def get_tenant(request: Request) -> TenantContext:
    tenant_id = request.headers.get("X-Tenant-ID", "default")
    return TenantContext(tenant_id=tenant_id)


router = create_query_builder_router(
    connector=connector,
    tenant_resolver=get_tenant,
    prefix="/api/qb",
)
app.include_router(router)
# Exposes: GET /api/qb/schema, POST /api/qb/compile, POST /api/qb/execute, POST /api/qb/export
```

#### Django Ninja Integration:
```python
from ninja import NinjaAPI
from query_builder import SQLiteConnector, create_ninja_router

api = NinjaAPI()
connector = SQLiteConnector("app.db")
router = create_ninja_router(connector=connector)
api.add_router("/qb", router)
```

---

### 4. Async Connection Pooling & Cancellation

```python
import asyncio
from query_builder import AsyncConnectionPool, AsyncCancellationToken


async def run_queries():
    # Initialize connection pool with driver or connector name
    pool = AsyncConnectionPool(
        connector_name="sqlite",
        database=":memory:",
        min_size=2,
        max_size=10,
    )
    await pool.initialize()

    # Cooperative cancellation token
    token = AsyncCancellationToken()

    # Acquire and release safely via async context manager
    async with pool.connection(token=token) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        print(cursor.fetchall())

    # Or acquire manually: conn = await pool.acquire(); await pool.release(conn)

    await pool.close()


asyncio.run(run_queries())
```

---

### 5. Bidirectional Schema Converters

```python
from query_builder.adapters import from_prisma
from query_builder.schema_converters import to_drizzle_schema, to_sqlalchemy_models

# 1. Ingest Prisma Schema
tables = from_prisma("""
  model User {
    id    Int    @id @default(autoincrement())
    email String @unique
  }
""")

# 2. Export to Drizzle ORM TypeScript
drizzle_code = to_drizzle_schema(tables, dialect="postgres")

# 3. Export to SQLAlchemy Models Python
sqlalchemy_code = to_sqlalchemy_models(tables)
```

---

### 6. Terminal CLI & Model Context Protocol (MCP) Server

```bash
# Start MCP Server for AI assistants (Cursor, Claude Desktop, Windsurf)
query-builder mcp

# Scaffold turnkey starter project
query-builder init my-analytics-app --template fullstack

# Check environment health and optional driver dependencies
query-builder doctor

# Start built-in REST microservice with interactive Swagger UI
query-builder serve --host 127.0.0.1 --port 8000
```

---

## 🎨 React Visual Studio Quickstart

Install the React component library:

```bash
pnpm add @jacob-white/query-builder-react
```

### 1. Typed API Client & Visual Studio Mode

```tsx
import React, { useState } from "react";
import {
  QueryBuilderProvider,
  VisualQueryBuilder,
  fromPrisma,
  toSchemaSnapshot,
} from "@jacob-white/query-builder-react";
import { createQueryBuilderClient } from "@jacob-white/query-builder-react/client";

// Initialize typed API client
const qbClient = createQueryBuilderClient({
  baseUrl: "/api/qb",
  timeoutMs: 30000,
});

const schema = toSchemaSnapshot(fromPrisma(`
  model Product {
    id       Int     @id @default(autoincrement())
    name     String
    price    Float
    category String
  }
`));

export function App() {
  return (
    <QueryBuilderProvider mode="styled" themeMode="dark">
      <div style={{ height: "100vh" }}>
        <VisualQueryBuilder
          schema={schema}
          client={qbClient}
          initialTable="Product"
          dialect="postgres"
        />
      </div>
    </QueryBuilderProvider>
  );
}
```

---

### 2. Composable Compound Components

```tsx
import {
  QueryBuilderRoot,
  QueryBuilderCanvas,
  QueryBuilderColumns,
  QueryBuilderFilters,
  QueryBuilderResults,
} from "@jacob-white/query-builder-react";

export function CustomStudio({ schema }: { schema: any }) {
  return (
    <QueryBuilderRoot schema={schema} initialTable="Product">
      <div className="flex gap-4">
        <div className="flex-1 space-y-4">
          <QueryBuilderCanvas className="h-96 border rounded-lg" />
          <QueryBuilderResults className="border rounded-lg" />
        </div>
        <div className="w-80 space-y-4">
          <QueryBuilderColumns />
          <QueryBuilderFilters />
        </div>
      </div>
    </QueryBuilderRoot>
  );
}
```

---

### 3. In-Memory OLAP Engine & Local File Ingest

Execute queries in-browser over local files with zero server roundtrips:

```tsx
import {
  getClientOlapEngine,
  ingestLocalFile,
} from "@jacob-white/query-builder-react/olap";

const olap = getClientOlapEngine();

// Ingest local CSV/Parquet file
await ingestLocalFile(olap, file, { tableName: "metrics" });

// Run fast analytical SQL locally
const results = await olap.query("SELECT category, AVG(val) FROM metrics GROUP BY category");
console.log(results.rows);
```

---

## 🧪 Testing & Verification

Query-Builder adheres to resource-throttled, sequential testing standards:

```bash
# 1. Run Python test suite
.venv/bin/pytest tests/ -q

# 2. Run React test suite (Vitest workers capped at 2)
cd packages/react
pnpm typecheck
pnpm build
VITEST_MAX_WORKERS=2 pnpm test
```

---

## 📄 License

MIT License © 2026 HobbyHabbit LLC. See [LICENSE](LICENSE) for full details.
