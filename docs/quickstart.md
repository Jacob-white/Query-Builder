# Query-Builder Quickstart Guide 🚀

Get up and running with Query-Builder in under 5 minutes. This guide covers both the **Python Core Engine** (compiler, ORM adapters, connectors, and microservice server) and the **React Visual Studio** (styled visual builder, container-scoped theming, and unstyled headless hooks).

---

## Part 1: Python Engine (5-Minute Quickstart)

### 1. Installation

Install Query-Builder core with your preferred database connector extra:

```bash
# SQLite (built-in driver, zero extra dependencies)
pip install "query-builder-engine[sqlite]"

# PostgreSQL
pip install "query-builder-engine[postgres]"

# Snowflake, MySQL, ClickHouse, DuckDB, or all connectors
pip install "query-builder-engine[all]"
```

For local repository development:
```bash
pip install -e .
```

---

### 2. 1-Line ORM Schema Adapters

Query-Builder includes declarative schema adapters for popular ORMs and schema formats. These convert external schemas into normalized `TableSchema` models and `SchemaSnapshot` structures for the query compiler and UI:

#### Prisma Schema (`from_prisma`)
```python
from query_builder.adapters import from_prisma, to_schema_snapshot

prisma_schema = """
datasource db {
  provider = "sqlite"
  url      = "file:./dev.db"
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
  user      User     @relation(fields: [userId], references: [id])
}
"""

# Accepts schema text or path to schema.prisma
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

# Mode A: Live SQLAlchemy MetaData or Declarative Models
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

# Mode B: Zero-dependency AST reflection from source string or .py file
py_code = """
class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    sku = Column(String(32), nullable=False)
"""
tables_ast = from_sqlalchemy(py_code)
```

#### JSON Schema & OpenAPI 3.x (`from_json_schema`)
```python
from query_builder.adapters import from_json_schema

json_schema = {
    "definitions": {
        "customers": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "company": {"type": "string"},
            },
            "required": ["id", "company"],
            "x-primary-keys": ["id"],
        }
    }
}

tables = from_json_schema(json_schema)
```

---

### 3. Global Engine Configuration

Configure dialects, security profiles, and custom extensions with a single function call:

```python
from query_builder import configure_query_builder, get_query_builder_config

# Choose between "development", "production", or "strict"
config = configure_query_builder(
    profile="development",
    default_dialect="sqlite",
    default_limit=50,
)

print(f"Default Dialect: {config.default_dialect}")
print(
    f"Read-only sessions enforced: {config.security.execution.enforce_read_only_session}"
)
```

---

### 4. Declarative Query Compilation

Compile declarative query specifications into safe, parameterized SQL with bind parameters:

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

print("Main SQL:", main_sql)
print("Parameters:", params)
print("Count SQL:", count_sql)
```

---

### 5. Executing Queries with Connectors

Query-Builder includes built-in connectors supporting both synchronous (`BaseConnector`) and asynchronous (`AsyncBaseConnector`) execution:

```python
import sqlite3
from query_builder import SQLiteConnector

# Initialize SQLite database
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
conn.execute("INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');")
conn.commit()

# Pass open connection or database path
connector = SQLiteConnector(connection=conn)

# Execute spec directly with automatic AST safety validation & row pagination
result = connector.execute(
    spec={"table": "users", "columns": ["users.id", "users.name"], "limit": 10}
)

print("Columns:", result["columns"])
print("Rows:", result["rows"])
print("Total Count:", result["count"])
print("Execution Latency:", result["latency_ms"], "ms")
```

---

### 6. Built-in REST & Swagger Microservice

Query-Builder includes a zero-dependency HTTP server with OpenAPI 3.1 documentation:

```bash
# Start microservice on port 8000
query-builder serve --host 127.0.0.1 --port 8000 --profile development
```

Visit `http://localhost:8000/docs` in your browser to interact with the Swagger UI documentation for schema introspection, compilation, and query execution endpoints.

---

## Part 2: React Visual Studio (5-Minute Quickstart)

### 1. Installation

Install `@jacob-white/query-builder-react` using your preferred package manager:

```bash
pnpm add @jacob-white/query-builder-react
# or
npm install @jacob-white/query-builder-react
# or
yarn add @jacob-white/query-builder-react
```

---

### 2. Plug-and-Play Styled Mode (`<VisualQueryBuilder>`)

Wrap your application in `QueryBuilderProvider` and mount `<VisualQueryBuilder>`:

```tsx
import React, { useState } from "react";
import {
  QueryBuilderProvider,
  VisualQueryBuilder,
  type SchemaSnapshot,
  type QueryResultData,
} from "@jacob-white/query-builder-react";

export function App() {
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
          { name: "total", data_type: "decimal", is_nullable: false, is_primary: false },
          { name: "status", data_type: "text", is_nullable: false, is_primary: false },
        ],
      },
    },
    foreign_keys: [
      {
        table: "orders",
        column: "user_id",
        foreign_table: "users",
        foreign_column: "id",
      },
    ],
  });

  const handleExecute = async (
    sql: string,
    spec?: Record<string, unknown>
  ): Promise<QueryResultData> => {
    const response = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec }),
    });
    return await response.json();
  };

  return (
    <QueryBuilderProvider mode="styled" themeMode="dark">
      <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
        <VisualQueryBuilder
          schema={schema}
          initialTable="users"
          dialect="sqlite"
          onExecuteQuery={handleExecute}
        />
      </div>
    </QueryBuilderProvider>
  );
}
```

---

### 3. Loading Schemas with TypeScript Adapters

Instead of manually constructing `SchemaSnapshot` objects, load them using TypeScript adapters:

```tsx
import {
  fromPrisma,
  fromDrizzle,
  fromSqlAlchemy,
  fromJsonSchema,
  toSchemaSnapshot,
} from "@jacob-white/query-builder-react";

// Load from Prisma schema string or DMMF
const prismaTables = fromPrisma(`
  model Product {
    id    Int    @id @default(autoincrement())
    name  String
    price Float
  }
`);

// Convert TableSchema[] to SchemaSnapshot
const schemaSnapshot = toSchemaSnapshot(prismaTables);
```

---

### 4. Customizing Theme with CSS Variables

All components use container-scoped CSS custom properties (`--qb-*`). Override tokens globally or per-container:

```tsx
import { QueryBuilderProvider } from "@jacob-white/query-builder-react";

<QueryBuilderProvider
  mode="styled"
  themeMode="dark"
  customTokens={{
    colors: {
      primary: "#6366f1",
      background: "#0f172a",
      surface: "#1e293b",
      border: "#334155",
      text: "#f8fafc",
      textMuted: "#94a3b8",
    },
    radii: {
      md: "8px",
      lg: "12px",
    },
  }}
>
  <VisualQueryBuilder schema={schema} />
</QueryBuilderProvider>
```

Or via standard CSS:
```css
.my-custom-container {
  --qb-color-primary: #3b82f6;
  --qb-color-background: #18181b;
  --qb-radius-md: 6px;
}
```

---

### 5. Headless Mode (Zero CSS, Unstyled Design Systems)

For custom design systems (Tailwind CSS, shadcn/ui), use unstyled headless hooks without loading default component styles:

```tsx
import React from "react";
import {
  useQueryBuilder,
  useQueryExecution,
  type SchemaSnapshot,
} from "@jacob-white/query-builder-react";

export function HeadlessQueryBuilder({ schema }: { schema: SchemaSnapshot }) {
  // 1. Headless query builder state
  const { state, compiled, actions, safety } = useQueryBuilder({
    schema,
    initialTable: "users",
    dialect: "sqlite",
  });

  // 2. Query execution controller with AbortController support
  const { results, isLoading, error, executeQuery } = useQueryExecution({
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
    <div className="p-6 space-y-4 font-sans text-gray-900 dark:text-gray-100">
      <div className="flex items-center gap-4">
        <label className="font-semibold text-sm">Primary Table:</label>
        <select
          value={state.primaryTable}
          onChange={(e) => actions.setPrimaryTable(e.target.value)}
          className="px-3 py-1.5 border rounded-md dark:bg-gray-800"
        >
          {Object.keys(schema.tables || {}).map((tableName) => (
            <option key={tableName} value={tableName}>
              {tableName}
            </option>
          ))}
        </select>
      </div>

      <div className="bg-gray-900 text-gray-100 p-4 rounded-md font-mono text-sm">
        <div className="text-xs text-gray-400 mb-1">Generated SQL:</div>
        <pre>{compiled.sql}</pre>
      </div>

      <button
        onClick={() => executeQuery(compiled.sql, compiled.spec)}
        disabled={isLoading || !safety.isValid}
        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-md disabled:opacity-50"
      >
        {isLoading ? "Running..." : "Run Query"}
      </button>

      {error && <div className="text-red-500 text-sm">Error: {error}</div>}

      {results && (
        <div className="overflow-x-auto border rounded-md">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                {results.columns.map((col) => (
                  <th key={col} className="px-3 py-2 text-left text-xs font-medium uppercase">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-800">
              {results.rows.map((row, idx) => (
                <tr key={idx}>
                  {results.columns.map((col) => (
                    <td key={col} className="px-3 py-2 text-sm">
                      {String(row[col] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

---

## Next Steps

- Check out the **[Full-Stack Starter Template](../examples/fullstack_starter/README.md)** featuring FastAPI + React 18 + SQLite.
- Explore the **[API Reference](api_reference.md)** for exhaustive details on every configuration option, hook, and adapter.
