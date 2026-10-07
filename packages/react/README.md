# @jacob-white/query-builder-react ⚛️

[![React 18+](https://img.shields.io/badge/React-18+-61dafb.svg)](https://react.dev/)
[![TypeScript 5.0+](https://img.shields.io/badge/TypeScript-5.0+-3178c6.svg)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Portable, embeddable, enterprise-grade **Visual SQL Query Builder & Schema Explorer React Component Library**.

Provides out-of-the-box support for:
- **Plug-and-Play Visual Studio** (`<VisualQueryBuilder>`): Drag-and-drop relational canvas, interactive filter builder, automatic graph joins, ERD modal, chart preview, and query execution.
- **Controlled & Uncontrolled State**: 50-step undo/redo history, canonical JSON AST serialization, and imperative ref handle (`VisualQueryBuilderRef`).
- **Composable Compound Components**: `<QueryBuilderRoot>`, `<QueryBuilderCanvas>`, `<QueryBuilderColumns>`, `<QueryBuilderFilters>`, `<QueryBuilderJoins>`, `<QueryBuilderSorts>`, `<QueryBuilderSqlEditor>`, and `<QueryBuilderResults>`.
- **First-Class Typed API Client**: `createQueryBuilderClient`, `createQuery`, and `FluentQuery` with automatic auth token injection, timeout handling, and `AbortSignal` cancellation.
- **Client-Side OLAP Engine & Ingest**: `InMemoryOlapEngine` and `getClientOlapEngine` for local in-memory SQL execution and instant CSV, TSV, Parquet, and JSON file ingestion.
- **Browser/Node Runtime Schema Adapters**: Bidirectional converters for Prisma (`fromPrisma`, `toPrismaSchema`), Drizzle ORM (`fromDrizzle`, `toDrizzleSchema`), SQLAlchemy (`fromSqlAlchemy`, `toSqlAlchemyModels`), and JSON Schema / OpenAPI (`fromJsonSchema`).
- **Headless Hooks**: `useQueryBuilder`, `useQueryExecution`, `useSchemaIntrospection`, `useStreamingQuery`, and `useLiveExecution` for building completely custom UIs with Tailwind CSS, shadcn/ui, or Radix UI.
- **Container-Scoped Theming**: Isolated CSS custom properties (`--qb-*`) via `QueryBuilderProvider` without stylesheet collisions.

---

## 📦 Installation

```bash
# pnpm
pnpm add @jacob-white/query-builder-react

# npm
npm install @jacob-white/query-builder-react

# yarn
yarn add @jacob-white/query-builder-react
```

### Peer Dependencies
`react >= 18.0.0` and `react-dom >= 18.0.0`.

---

## 🗂️ Multi-Entry Subpath Exports

Modern package exports allow fine-grained tree-shaking and runtime isolation:

| Subpath Entry Point | Contents & Use Case |
|:---|:---|
| `@jacob-white/query-builder-react` | Root export containing all Visual UI components, theming providers, hooks, and adapters. |
| `@jacob-white/query-builder-react/client` | First-class TypeScript HTTP API client (`createQueryBuilderClient`, `FluentQuery`, `createQuery`). |
| `@jacob-white/query-builder-react/adapters` | Bidirectional ORM schema converters (Prisma, Drizzle, SQLAlchemy, JSON Schema, Semantic Models). |
| `@jacob-white/query-builder-react/hooks` | Unstyled headless React hooks (`useQueryBuilder`, `useQueryExecution`, `useSchemaIntrospection`). |
| `@jacob-white/query-builder-react/olap` | In-memory client OLAP SQL engine and file ingestion utilities (`InMemoryOlapEngine`, `ingestLocalFile`). |

---

## 🚀 Quickstarts

### 1. Plug-and-Play Visual Query Builder

Mount the studio with dark or light container-scoped theming:

```tsx
import React, { useState } from "react";
import {
  QueryBuilderProvider,
  VisualQueryBuilder,
  fromPrisma,
  toSchemaSnapshot,
  type QueryResultData,
} from "@jacob-white/query-builder-react";

const PRISMA_SCHEMA = `
  model User {
    id        Int      @id @default(autoincrement())
    email     String   @unique
    name      String?
    orders    Order[]
  }

  model Order {
    id        Int      @id @default(autoincrement())
    userId    Int      @map("user_id")
    total     Float
    status    String
    user      User     @relation(fields: [userId], references: [id])
  }
`;

export function App() {
  const [schema] = useState(() => toSchemaSnapshot(fromPrisma(PRISMA_SCHEMA)));

  const handleExecute = async (sql: string, spec?: Record<string, unknown>): Promise<QueryResultData> => {
    const res = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql, spec }),
    });
    return await res.json();
  };

  return (
    <QueryBuilderProvider mode="styled" themeMode="dark">
      <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
        <VisualQueryBuilder
          schema={schema}
          initialTable="User"
          dialect="postgres"
          onExecuteQuery={handleExecute}
        />
      </div>
    </QueryBuilderProvider>
  );
}
```

---

### 2. First-Class Typed API Client (`/client`)

Connect your frontend directly to any Query-Builder backend router (FastAPI, Django, Express, or Native HTTP Server) with zero boilerplate:

```tsx
import {
  createQueryBuilderClient,
  createQuery,
  type QuerySpec,
} from "@jacob-white/query-builder-react/client";

// 1. Initialize client with auth token resolver and timeout
export const qbClient = createQueryBuilderClient({
  baseUrl: "/api/qb",
  token: async () => localStorage.getItem("auth_token"),
  timeoutMs: 15000,
});

// 2. Fetch schema snapshot
const schema = await qbClient.getSchema();

// 3. Programmatic fluent query building
const result = await createQuery("orders", qbClient)
  .select([
    "orders.id",
    { column: "orders.total", agg: "sum", alias: "revenue" },
  ])
  .join("users", "orders.user_id", "=", "users.id")
  .where("orders.status", "eq", "COMPLETED")
  .groupBy(["orders.id"])
  .orderBy("revenue", "DESC")
  .limit(20)
  .execute();

console.log("Columns:", result.columns);
console.log("Rows:", result.rows);

// 4. Direct spec compilation and execution
const compiled = await qbClient.compile({
  table: "users",
  columns: ["users.id", "users.email"],
  limit: 10,
}, "postgres");

console.log("Generated SQL:", compiled.sql);
```

#### Pass Client Directly to `<VisualQueryBuilder>`:

```tsx
import { VisualQueryBuilder } from "@jacob-white/query-builder-react";
import { qbClient } from "./client";

<VisualQueryBuilder
  schema={schema}
  client={qbClient}
  initialTable="orders"
  dialect="postgres"
/>
// onExecuteQuery is automatically wired to qbClient.execute!
```

---

### 3. Controlled State, Undo/Redo & Schema Diagnostics

`<VisualQueryBuilder>` supports controlled state via `value` and `onChange`, 50-step undo/redo history, and imperative control via `ref`:

```tsx
import React, { useState, useRef } from "react";
import {
  VisualQueryBuilder,
  validateSchema,
  type QuerySpec,
  type VisualQueryBuilderRef,
  type SchemaSnapshot,
} from "@jacob-white/query-builder-react";

export function ControlledEditor({ schema }: { schema: SchemaSnapshot }) {
  const ref = useRef<VisualQueryBuilderRef>(null);
  const [spec, setSpec] = useState<QuerySpec>({
    table: "orders",
    columns: ["orders.id", "orders.total"],
    limit: 50,
  });

  // Validate schema metadata for warnings/errors
  const diagnostics = validateSchema(schema);
  if (!diagnostics.valid) {
    console.warn("Schema issues detected:", diagnostics.errors);
  }

  return (
    <div className="space-y-4">
      {/* Toolbar utilizing imperative ref actions */}
      <div className="flex gap-2">
        <button
          onClick={() => ref.current?.undo()}
          disabled={!ref.current?.canUndo()}
          className="px-3 py-1 bg-gray-700 text-white rounded disabled:opacity-50"
        >
          Undo
        </button>
        <button
          onClick={() => ref.current?.redo()}
          disabled={!ref.current?.canRedo()}
          className="px-3 py-1 bg-gray-700 text-white rounded disabled:opacity-50"
        >
          Redo
        </button>
        <button
          onClick={() => ref.current?.reset()}
          className="px-3 py-1 bg-red-700 text-white rounded"
        >
          Reset
        </button>
        <button
          onClick={async () => {
            const results = await ref.current?.execute();
            console.log("Query Results:", results);
          }}
          className="px-3 py-1 bg-blue-600 text-white rounded"
        >
          Run Query
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

### 4. Composable Compound Components (`<QueryBuilderRoot>` or `<QueryBuilder.Root>`)

Build custom layouts by composing atomic studio primitives. Primitives can be imported individually or accessed via the `QueryBuilder.*` compound namespace, and styled with slotted Tailwind CSS classes:

```tsx
import React from "react";
import {
  QueryBuilder,
  QueryBuilderRoot,
  QueryBuilderCanvas,
  QueryBuilderColumns,
  QueryBuilderFilters,
  QueryBuilderJoins,
  QueryBuilderSorts,
  QueryBuilderSqlEditor,
  QueryBuilderResults,
  type SchemaSnapshot,
} from "@jacob-white/query-builder-react";

export function CustomStudio({ schema }: { schema: SchemaSnapshot }) {
  return (
    <QueryBuilderRoot
      schema={schema}
      initialTable="orders"
      dialect="postgres"
      classNames={{
        root: "bg-slate-950 text-slate-100 rounded-xl border border-slate-800 p-4",
      }}
    >
      <div className="grid grid-cols-12 gap-4">
        {/* Left Column: Interactive Visual Canvas */}
        <div className="col-span-8 space-y-4">
          <QueryBuilderCanvas className="h-[420px] rounded-lg border border-slate-800 bg-slate-900" />
          <QueryBuilderResults className="rounded-lg border border-slate-800" />
        </div>

        {/* Right Column: Tabular Control Panels */}
        <div className="col-span-4 space-y-4">
          <QueryBuilderColumns className="p-3 bg-slate-900 rounded-lg" />
          <QueryBuilderFilters className="p-3 bg-slate-900 rounded-lg" />
          <QueryBuilderJoins className="p-3 bg-slate-900 rounded-lg" />
          <QueryBuilderSorts className="p-3 bg-slate-900 rounded-lg" />
          <QueryBuilderSqlEditor className="p-3 bg-slate-900 rounded-lg" />
        </div>
      </div>
    </QueryBuilderRoot>
  );
}
```

---

### 5. In-Memory OLAP Engine & Local File Ingestion (`/olap`)

Run analytical queries entirely in the client browser with zero server roundtrips using the built-in columnar OLAP engine:

```tsx
import {
  getClientOlapEngine,
  ingestLocalFile,
  type SchemaSnapshot,
} from "@jacob-white/query-builder-react/olap";

// 1. Get client-side OLAP engine instance
const olapEngine = getClientOlapEngine();

// 2. Ingest local user file (CSV, TSV, Parquet, or JSON)
const fileInput = document.querySelector<HTMLInputElement>("#csv-input")!;
const file = fileInput.files![0];

const tableMeta = await ingestLocalFile(olapEngine, file, {
  tableName: "sales_data",
});

// 3. Extract automatically generated schema snapshot
const olapSchema: SchemaSnapshot = olapEngine.getSchemaSnapshot();

// 4. Execute analytical SQL directly in-browser
const result = await olapEngine.query(`
  SELECT category, SUM(amount) AS total_revenue
  FROM sales_data
  GROUP BY category
  ORDER BY total_revenue DESC
  LIMIT 10
`);

console.log("In-browser OLAP results:", result.rows);
```

---

### 6. Bidirectional TypeScript ORM Schema Adapters (`/adapters`)

Convert schemas directly in the browser or Node runtime:

```tsx
import {
  fromPrisma,
  toPrismaSchema,
  fromDrizzle,
  toDrizzleSchema,
  fromSqlAlchemy,
  toSqlAlchemyModels,
  fromJsonSchema,
  toSchemaSnapshot,
} from "@jacob-white/query-builder-react/adapters";

// --- Prisma ---
const prismaTables = fromPrisma(prismaSchemaString);
const snapshot = toSchemaSnapshot(prismaTables);
// Convert back to .prisma schema
const exportedPrisma = toPrismaSchema(snapshot, { provider: "postgresql" });

// --- Drizzle ORM ---
const drizzleTables = fromDrizzle(drizzleTypeScriptSource);
const exportedDrizzle = toDrizzleSchema(snapshot, { dialect: "postgres" });

// --- SQLAlchemy ---
const sqlalchemyTables = fromSqlAlchemy(pythonModelCode);
const exportedSqlAlchemy = toSqlAlchemyModels(snapshot);

// --- JSON Schema / OpenAPI 3.x ---
const jsonSchemaTables = fromJsonSchema(openApiSpecObject);
```

---

### 7. Headless Hooks (Zero CSS) (`/hooks`)

Build your own bespoke UI from scratch with unstyled state machines:

```tsx
import React from "react";
import {
  useQueryBuilder,
  useQueryExecution,
  type SchemaSnapshot,
} from "@jacob-white/query-builder-react/hooks";

export function HeadlessQueryStudio({ schema }: { schema: SchemaSnapshot }) {
  const { state, compiled, actions, safety } = useQueryBuilder({
    schema,
    initialTable: "users",
    dialect: "sqlite",
  });

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
        {Object.keys(schema.tables || {}).map((name) => (
          <option key={name} value={name}>{name}</option>
        ))}
      </select>

      <pre className="bg-black text-green-400 p-3 rounded font-mono text-sm">
        {compiled.sql}
      </pre>

      <button
        onClick={() => executeQuery(compiled.sql, compiled.spec)}
        disabled={isLoading || !safety.isValid}
        className="px-4 py-2 bg-blue-600 text-white rounded font-medium disabled:opacity-50"
      >
        {isLoading ? "Executing..." : "Execute Query"}
      </button>

      {results && (
        <div className="border rounded p-2">
          Found {results.count} rows in {results.latency_ms}ms
        </div>
      )}
    </div>
  );
}
```

---

## 🎨 Theming & CSS Custom Properties

Wrap your application in `QueryBuilderProvider` to configure styles:

```tsx
import { QueryBuilderProvider } from "@jacob-white/query-builder-react";

<QueryBuilderProvider
  mode="styled"
  themeMode="dark"
  customTokens={{
    colors: {
      primary: "#6366f1",
      background: "#090d16",
      surface: "#111827",
      border: "#1f2937",
    },
    radii: {
      md: "8px",
    },
  }}
>
  <VisualQueryBuilder schema={schema} />
</QueryBuilderProvider>
```

### Scoped CSS Variables (`--qb-*`):
- `--qb-color-primary`: Accent & primary action color.
- `--qb-color-background`: Canvas & modal background.
- `--qb-color-surface`: Card & table surface.
- `--qb-color-border`: Dividers and table borders.
- `--qb-color-text`: High-contrast body text.
- `--qb-color-text-muted`: Secondary labels and comments.
- `--qb-radius-md`: Button and input corner rounding.

---

## 🧪 Testing & Verification

Query-Builder React maintains 100% test coverage across unit, integration, and SSR scenarios:

```bash
# Typecheck
pnpm typecheck

# Production Bundle Build
pnpm build

# Run Vitest Suite (workers throttled to 2)
VITEST_MAX_WORKERS=2 pnpm test
```

---

## 📄 License

MIT License © 2026 HobbyHabbit LLC. See [LICENSE](../../LICENSE) for full details.
