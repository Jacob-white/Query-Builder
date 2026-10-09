# Query-Builder Quickstart Guide 🚀

Get up and running with Query-Builder in under 5 minutes. This guide covers both the **Python Core Engine** (multi-dialect compiler, analytical expressions, enterprise security governor, framework routers, and MCP server) and the **React Visual Studio** (typed API client, compound components, controlled undo/redo studio, and client-side OLAP).

---

## Part 1: Python Engine Quickstart

### 1. Installation

Install Query-Builder core with your preferred database connector extra:

```bash
# SQLite (built-in driver, zero extra dependencies)
pip install "query-builder-engine[sqlite]"

# PostgreSQL
pip install "query-builder-engine[postgres]"

# A connector family (sql, cloud-warehouses, nosql, vector, streaming) ...
pip install "query-builder-engine[sql]"

# ... every driver that installs from wheels on all platforms ...
pip install "query-builder-engine[all]"

# ... or additionally the native-build drivers (mysqlclient, pymssql, pyodbc, ibm-db, ...)
pip install "query-builder-engine[all-native]"

# FastAPI / Django integrations
pip install "query-builder-engine[server]"
pip install "query-builder-engine[django]"
```

For local repository development:
```bash
pip install -e .
```

---

### 2. 1-Line ORM Schema Adapters

Query-Builder includes declarative schema adapters that convert external schemas into normalized `TableSchema` models and `SchemaSnapshot` catalogs:

#### Prisma Schema (`from_prisma`)
```python
from query_builder.adapters import from_prisma, to_schema_snapshot

prisma_schema = """
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model User {
  id        Int      @id @default(autoincrement())
  email     String   @unique
  name      String?
  orders    Order[]
}

model Order {
  id        Int      @id @default(autoincrement())
  userId    Int      @map("user_id")
  amount    Float
  status    String
  user      User     @relation(fields: [userId], references: [id])
}
"""

tables = from_prisma(prisma_schema)
snapshot = to_schema_snapshot(tables)
print(f"Loaded tables: {list(tables.keys())}")
# Loaded tables: ['User', 'Order']
```

#### Drizzle ORM (`from_drizzle`)
```python
from query_builder.adapters import from_drizzle

drizzle_schema = """
import { sqliteTable, integer, text, real } from 'drizzle-orm/sqlite-core';

export const users = sqliteTable('users', {
  id: integer('id').primaryKey(),
  email: text('email').notNull(),
});

export const orders = sqliteTable('orders', {
  id: integer('id').primaryKey(),
  userId: integer('user_id').references(() => users.id),
  total: real('total').notNull(),
});
"""

tables = from_drizzle(drizzle_schema)
print(f"Loaded tables: {list(tables.keys())}")
# Loaded tables: ['users', 'orders']
```

#### SQLAlchemy (`from_sqlalchemy`)
```python
from query_builder.adapters import from_sqlalchemy
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table

metadata = MetaData()
users_table = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(50), nullable=False),
)
orders_table = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id")),
)

tables = from_sqlalchemy(metadata)
print(f"Loaded tables: {list(tables.keys())}")
# Loaded tables: ['users', 'orders']
```

---

### 3. Declarative Query Compilation with Analytical SQL

Compile structured queries with multi-dialect support (Postgres, Snowflake, MySQL, SQLite, DuckDB, ClickHouse, MSSQL, BigQuery, Oracle, Trino) and analytical expressions:

```python
from query_builder import QueryCompiler, WindowFunctionSpec

spec = {
    "table": "orders",
    "columns": [
        "orders.id",
        "orders.user_id",
        {"column": "orders.amount", "agg": "sum", "alias": "total_spent"},
        {
            "case_when": {
                "branches": [
                    {
                        "condition": {
                            "column": "orders.amount",
                            "op": "gte",
                            "value": 500,
                        },
                        "then_value": "Premium",
                    }
                ],
                "else_value": "Standard",
            },
            "alias": "spend_tier",
        },
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
    ],
    "window_functions": [
        WindowFunctionSpec(
            function="RANK",
            order_by=[{"column": "orders.amount", "direction": "DESC"}],
            alias="order_rank",
        )
    ],
    "grouping_type": "rollup",
    "limit": 25,
}

compiler = QueryCompiler(spec, dialect="postgres")
main_sql, params, count_sql, count_params = compiler.compile()

print("Main SQL:\n", main_sql)
print("Bind Parameters:", params)
```

---

### 4. Enterprise Security Governor & Column-Level Access Control (CLAC)

Enforce fail-closed row-level tenant filtering, role-based column access, and AST complexity quotas:

```python
from query_builder import (
    SecurityPolicy,
    TenantContext,
    apply_security_policy,
)

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
    tenant_id="tenant_01",
    user_id="usr_99",
    roles=["analyst"],  # Does not have 'finance' role
)

spec = {
    "table": "employees",
    "columns": ["id", "name", "salary"],
}

try:
    apply_security_policy(spec, context=context, policy=policy)
except Exception as exc:
    print(f"Access Denied: {exc}")
    # Access to restricted column 'salary' on table 'employees' requires roles: ['finance', 'hr_admin']
```

---

### 5. Turnkey Web Framework Routers

Mount complete Query-Builder REST endpoints in 1 line of code:

#### FastAPI Router:
```python
from fastapi import FastAPI, Request
from query_builder import SQLiteConnector, create_query_builder_router, TenantContext

app = FastAPI()
connector = SQLiteConnector("app.db")


async def resolve_tenant(request: Request) -> TenantContext:
    tenant_id = request.headers.get("X-Tenant-ID", "tenant-1")
    return TenantContext(tenant_id=tenant_id)


router = create_query_builder_router(
    connector=connector,
    tenant_resolver=resolve_tenant,
    prefix="/api/qb",
)
app.include_router(router)
# Endpoints registered:
# GET  /api/qb/schema
# POST /api/qb/compile
# POST /api/qb/validate
# POST /api/qb/execute
# POST /api/qb/export
```

#### Django Ninja Router:
```python
# Requires: pip install django django-ninja
from ninja import NinjaAPI
from query_builder import SQLiteConnector, create_ninja_router

api = NinjaAPI()
connector = SQLiteConnector("app.db")

router = create_ninja_router(connector=connector)
api.add_router("/qb", router)
```

---

### 6. Async Connection Pooling & Streaming

Manage high-concurrency database connection lifecycles and query streaming:

```python
import asyncio
from query_builder import (
    AsyncConnectionPool,
    AsyncCancellationToken,
    AsyncStreamingExecutor,
)


async def run_analytics():
    # 1. Initialize pooled connections (with SQLite, Postgres, Snowflake, etc.)
    pool = AsyncConnectionPool(
        connector_name="sqlite",
        database=":memory:",
        min_size=2,
        max_size=10,
    )
    await pool.initialize()

    token = AsyncCancellationToken()

    # 2. Acquire and release safely via async context manager
    async with pool.connection(token=token) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        print("Pooled result:", cursor.fetchall())

    # 3. Or acquire manually: conn = await pool.acquire(token=token); await pool.release(conn)

    await pool.close()


asyncio.run(run_analytics())
```

---

### 7. Bidirectional Schema Converters

Export schemas directly to Prisma, Drizzle, or SQLAlchemy definitions:

```python
from query_builder.adapters import from_json_schema
from query_builder.schema_converters import (
    to_prisma_schema,
    to_drizzle_schema,
    to_sqlalchemy_models,
)

# Ingest schema
tables = from_json_schema(
    {
        "definitions": {
            "users": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "email": {"type": "string"}},
                "x-primary-keys": ["id"],
            }
        }
    }
)

# Export to any ORM definition:
prisma_code = to_prisma_schema(tables, provider="postgresql")
drizzle_code = to_drizzle_schema(tables, dialect="postgres")
sqlalchemy_code = to_sqlalchemy_models(tables)
```

---

### 8. MCP Server & CLI Tools

```bash
# Start Model Context Protocol (MCP) server for Claude Desktop / Cursor
query-builder mcp

# Scaffold a new fullstack project
query-builder init my-app --template fullstack

# Check system health & optional driver packages
query-builder doctor

# Start native HTTP microservice server
query-builder serve --host 127.0.0.1 --port 8000
```

---

## Part 2: React Visual Studio Quickstart

### 1. Installation & Subpaths

Install `@jacob-white/query-builder-react`:

```bash
pnpm add @jacob-white/query-builder-react
# or
npm install @jacob-white/query-builder-react
```

Subpath entry points:
- `@jacob-white/query-builder-react`: Visual UI studio and root components.
- `@jacob-white/query-builder-react/client`: Typed HTTP client (`createQueryBuilderClient`, `FluentQuery`).
- `@jacob-white/query-builder-react/adapters`: TypeScript ORM schema adapters.
- `@jacob-white/query-builder-react/hooks`: Headless unstyled React hooks.
- `@jacob-white/query-builder-react/olap`: In-memory client OLAP SQL engine and file ingest.

---

### 2. Plug-and-Play Visual Query Builder (`<VisualQueryBuilder>`)

Wrap your application in `QueryBuilderProvider` and mount `<VisualQueryBuilder>`:

```tsx
import React, { useState } from "react";
import {
  QueryBuilderProvider,
  VisualQueryBuilder,
  fromPrisma,
  toSchemaSnapshot,
} from "@jacob-white/query-builder-react";
import { createQueryBuilderClient } from "@jacob-white/query-builder-react/client";

// Initialize typed client
const client = createQueryBuilderClient({
  baseUrl: "/api/qb",
});

const schema = toSchemaSnapshot(fromPrisma(`
  model Customer {
    id      Int    @id @default(autoincrement())
    company String
    tier    String
  }
`));

export function App() {
  return (
    <QueryBuilderProvider mode="styled" themeMode="dark">
      <div style={{ height: "100vh" }}>
        <VisualQueryBuilder
          schema={schema}
          client={client}
          initialTable="Customer"
          dialect="postgres"
        />
      </div>
    </QueryBuilderProvider>
  );
}
```

---

### 3. First-Class Typed API Client (`/client`)

Construct queries programmatically with full TypeScript typing:

```tsx
import {
  createQueryBuilderClient,
  createQuery,
} from "@jacob-white/query-builder-react/client";

const client = createQueryBuilderClient({
  baseUrl: "/api/qb",
  token: async () => localStorage.getItem("jwt_token"),
  timeoutMs: 20000,
});

// Fluent query builder
const results = await createQuery("orders", client)
  .select([
    "orders.id",
    { column: "orders.amount", agg: "sum", alias: "revenue" },
  ])
  .where("orders.status", "eq", "COMPLETED")
  .groupBy(["orders.id"])
  .orderBy("revenue", "DESC")
  .limit(10)
  .execute();

console.log("Rows:", results.rows);
```

---

### 4. Controlled State, Undo/Redo & Schema Diagnostics

Control the builder state, access 50-step undo/redo, and run diagnostic validation:

```tsx
import React, { useState, useRef } from "react";
import {
  VisualQueryBuilder,
  validateSchema,
  type VisualQueryBuilderRef,
  type QuerySpec,
  type SchemaSnapshot,
} from "@jacob-white/query-builder-react";

export function ControlledStudio({ schema }: { schema: SchemaSnapshot }) {
  const ref = useRef<VisualQueryBuilderRef>(null);
  const [spec, setSpec] = useState<QuerySpec>({
    table: "orders",
    columns: ["orders.id", "orders.total"],
    limit: 25,
  });

  // Verify schema integrity
  const diagnostics = validateSchema(schema);
  if (!diagnostics.valid) {
    console.error("Schema errors:", diagnostics.errors);
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <button onClick={() => ref.current?.undo()} disabled={!ref.current?.canUndo()}>
          Undo
        </button>
        <button onClick={() => ref.current?.redo()} disabled={!ref.current?.canRedo()}>
          Redo
        </button>
        <button onClick={() => ref.current?.reset()}>
          Reset
        </button>
        <button onClick={() => ref.current?.execute()}>
          Execute
        </button>
      </div>

      <VisualQueryBuilder
        ref={ref}
        schema={schema}
        value={spec}
        onChange={(newSpec) => setSpec(newSpec)}
        dialect="postgres"
      />
    </div>
  );
}
```

---

### 5. Composable Compound Components

Compose custom query layouts with slotted CSS styling:

```tsx
import React from "react";
import {
  QueryBuilderRoot,
  QueryBuilderCanvas,
  QueryBuilderColumns,
  QueryBuilderFilters,
  QueryBuilderResults,
  type SchemaSnapshot,
} from "@jacob-white/query-builder-react";

export function Studio({ schema }: { schema: SchemaSnapshot }) {
  return (
    <QueryBuilderRoot schema={schema} initialTable="orders">
      <div className="flex gap-4 p-4 bg-slate-950 text-white">
        <div className="flex-1 space-y-4">
          <QueryBuilderCanvas className="h-96 border border-slate-800 rounded-lg" />
          <QueryBuilderResults className="border border-slate-800 rounded-lg" />
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

### 6. Client-Side OLAP Engine & Local File Ingestion (`/olap`)

Run analytical queries in-browser over local CSV, TSV, Parquet, or JSON files:

```tsx
import {
  getClientOlapEngine,
  ingestLocalFile,
} from "@jacob-white/query-builder-react/olap";

const olap = getClientOlapEngine();

// Ingest local file uploaded by user
const fileInput = document.querySelector<HTMLInputElement>("#file-upload")!;
const file = fileInput.files![0];

await ingestLocalFile(olap, file, { tableName: "user_data" });

// Run local SQL execution with zero server latency
const queryResult = await olap.query("SELECT * FROM user_data LIMIT 10");
console.log("Local rows:", queryResult.rows);
```

---

### 7. Headless Mode (Zero CSS, Custom Design Systems)

Build completely custom interfaces with zero CSS opinions:

```tsx
import React from "react";
import { useQueryBuilder, useQueryExecution } from "@jacob-white/query-builder-react/hooks";
import type { SchemaSnapshot } from "@jacob-white/query-builder-react";

export function HeadlessEditor({ schema }: { schema: SchemaSnapshot }) {
  const { state, compiled, actions } = useQueryBuilder({ schema, initialTable: "users" });
  const { results, isLoading, executeQuery } = useQueryExecution({
    onExecuteQuery: async (sql, spec) => {
      const res = await fetch("/api/qb/execute", {
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
        {Object.keys(schema.tables || {}).map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>

      <pre className="bg-gray-900 text-white p-3 rounded font-mono">{compiled.sql}</pre>

      <button
        onClick={() => executeQuery(compiled.sql, compiled.spec)}
        disabled={isLoading}
        className="px-4 py-2 bg-blue-600 text-white rounded font-medium disabled:opacity-50"
      >
        {isLoading ? "Executing..." : "Run Query"}
      </button>

      {results && <div>Found {results.count} results in {results.latency_ms}ms</div>}
    </div>
  );
}
```

---

## Next Steps

- Explore the **[Full-Stack Starter Template](../examples/fullstack_starter/README.md)** for a complete FastAPI + React 18 + SQLite application.
- Review the **[Exhaustive API Reference](api_reference.md)** for detailed specifications of all data models, options, and methods.
- Read the **[Security Policy & Sandboxing Guide](../SECURITY.md)** for zero-trust query isolation and vulnerability disclosure procedures.

---

*Query-Builder is developed and maintained by **HobbyHabbit LLC** under the **MIT License**.*
