import React, { useState, useEffect, useMemo } from "react";
import {
  QueryBuilderProvider,
  VisualQueryBuilder,
  useQueryBuilder,
  useQueryExecution,
  fromPrisma,
  fromDrizzle,
  fromSqlAlchemy,
  toSchemaSnapshot,
  type SchemaSnapshot,
  type QueryResultData,
  type QuerySpec,
  type CustomFilterOperator,
} from "@jacob-white/query-builder-react";

// Fallback initial schema generated via fromPrisma in case backend is offline
const FALLBACK_PRISMA = `
datasource db {
  provider = "sqlite"
  url = "file:./starter.db"
}

model Category {
  id          Int       @id @default(autoincrement())
  name        String
  slug        String    @unique
  description String?
  isActive    Int       @default(1) @map("is_active")
  products    Product[]
  @@map("categories")
}

model Product {
  id            Int        @id @default(autoincrement())
  categoryId    Int        @map("category_id")
  name          String
  price         Float
  stockQuantity Int        @default(0) @map("stock_quantity")
  status        String
  description   String?
  category      Category   @relation(fields: [categoryId], references: [id])
  orderItems    OrderItem[]
  @@map("products")
}

model User {
  id        Int      @id @default(autoincrement())
  email     String   @unique
  fullName  String   @map("full_name")
  role      String
  createdAt String   @map("created_at")
  lastLogin String?  @map("last_login")
  orders    Order[]
  @@map("users")
}

model Order {
  id              Int         @id @default(autoincrement())
  userId          Int         @map("user_id")
  status          String
  totalAmount     Float       @map("total_amount")
  shippingAddress String?     @map("shipping_address")
  createdAt       String      @map("created_at")
  user            User        @relation(fields: [userId], references: [id])
  orderItems      OrderItem[]
  @@map("orders")
}

model OrderItem {
  id        Int     @id @default(autoincrement())
  orderId   Int     @map("order_id")
  productId Int     @map("product_id")
  quantity  Int     @default(1)
  unitPrice Float   @map("unit_price")
  discount  Float?  @default(0.0)
  order     Order   @relation(fields: [orderId], references: [id])
  product   Product @relation(fields: [productId], references: [id])
  @@map("order_items")
}
`;

const FALLBACK_SCHEMA: SchemaSnapshot = toSchemaSnapshot(fromPrisma(FALLBACK_PRISMA));

// 1. Custom filter operator
const customOperators: Record<string, CustomFilterOperator> = {
  TAX_EXEMPT: {
    label: "Tax Exempt Item",
    value: "TAX_EXEMPT",
    hasValue: false,
    formatSql: (colRef: string) => `${colRef} IS NOT NULL AND ${colRef} = 0`,
  },
};

// 2. Custom price cell renderer
const cellRenderers = {
  price: (val: any) => (
    <span style={{ color: "#10b981", fontWeight: "bold", fontFamily: "monospace" }}>
      ${Number(val || 0).toFixed(2)}
    </span>
  ),
  total_amount: (val: any) => (
    <span style={{ color: "#38bdf8", fontWeight: "bold", fontFamily: "monospace" }}>
      ${Number(val || 0).toFixed(2)}
    </span>
  ),
};

// Sample ORM Schemas for Demo Tab
const SAMPLE_PRISMA = `datasource db {
  provider = "sqlite"
  url      = "file:./starter.db"
}

model Customer {
  id        Int      @id @default(autoincrement())
  email     String   @unique
  fullName  String   @map("full_name")
  role      Role     @default(CUSTOMER)
  orders    PurchaseOrder[]
}

enum Role {
  ADMIN
  CUSTOMER
  GUEST
}

model PurchaseOrder {
  id         Int      @id @default(autoincrement())
  customerId Int      @map("customer_id")
  amount     Float
  customer   Customer @relation(fields: [customerId], references: [id])
}`;

const SAMPLE_DRIZZLE = `import { sqliteTable, integer, text, real } from 'drizzle-orm/sqlite-core';

export const authors = sqliteTable('authors', {
  id: integer('id').primaryKey(),
  name: text('name').notNull(),
});

export const articles = sqliteTable('articles', {
  id: integer('id').primaryKey(),
  authorId: integer('author_id').references(() => authors.id),
  title: text('title').notNull(),
  views: integer('views').default(0),
});`;

const SAMPLE_SQLALCHEMY = `class Inventory(Base):
    __tablename__ = 'warehouse_inventory'
    sku = Column(String(50), primary_key=True)
    quantity = Column(Integer, nullable=False, default=0)
    reorder_point = Column(Integer, nullable=False)
`;

export function App() {
  const [activeTab, setActiveTab] = useState<"visual" | "headless" | "adapters">("visual");
  const [schema, setSchema] = useState<SchemaSnapshot>(FALLBACK_SCHEMA);
  const [serverStatus, setServerStatus] = useState<string>("checking...");

  // Load live schema from FastAPI backend
  useEffect(() => {
    async function loadBackendData() {
      try {
        const healthRes = await fetch("/health");
        if (healthRes.ok) {
          const healthData = await healthRes.json();
          setServerStatus(`Connected (${healthData.service})`);
        } else {
          setServerStatus("Backend Offline (using mock schema)");
        }
      } catch {
        setServerStatus("Backend Offline (using mock schema)");
      }

      try {
        const schemaRes = await fetch("/api/schema");
        if (schemaRes.ok) {
          const schemaData = await schemaRes.json();
          setSchema(schemaData);
        }
      } catch {
        // Fallback remains active
      }
    }
    loadBackendData();
  }, []);

  // Execution handler talking to backend /api/execute
  const handleExecuteQuery = async (
    sql: string,
    spec?: QuerySpec | null,
  ): Promise<QueryResultData> => {
    const res = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec: spec ?? undefined, sql }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Execution failed");
    }
    return await res.json();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", backgroundColor: "#0f172a" }}>
      {/* Header bar */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 24px",
          borderBottom: "1px solid #1e293b",
          backgroundColor: "#1e293b",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <h1 style={{ margin: 0, fontSize: "1.25rem", color: "#f8fafc" }}>
            ⚡ Query-Builder Starter
          </h1>
          <span
            style={{
              fontSize: "0.75rem",
              padding: "2px 8px",
              borderRadius: "9999px",
              backgroundColor: serverStatus.includes("Connected") ? "#065f46" : "#7c2d12",
              color: serverStatus.includes("Connected") ? "#6ee7b7" : "#fdba74",
            }}
          >
            {serverStatus}
          </span>
        </div>

        {/* Tab switcher */}
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            onClick={() => setActiveTab("visual")}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              fontWeight: 500,
              backgroundColor: activeTab === "visual" ? "#3b82f6" : "#334155",
              color: "#fff",
            }}
          >
            🎨 Visual Studio
          </button>
          <button
            onClick={() => setActiveTab("headless")}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              fontWeight: 500,
              backgroundColor: activeTab === "headless" ? "#3b82f6" : "#334155",
              color: "#fff",
            }}
          >
            🧩 Headless Mode
          </button>
          <button
            onClick={() => setActiveTab("adapters")}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              fontWeight: 500,
              backgroundColor: activeTab === "adapters" ? "#3b82f6" : "#334155",
              color: "#fff",
            }}
          >
            🔄 ORM Adapters
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main style={{ flex: 1, overflow: "hidden" }}>
        {activeTab === "visual" && (
          <QueryBuilderProvider
            mode="styled"
            themeMode="dark"
            customOperators={customOperators}
            cellRenderers={cellRenderers}
          >
            <VisualQueryBuilder
              schema={schema}
              initialTable="products"
              dialect="sqlite"
              onExecuteQuery={handleExecuteQuery}
            />
          </QueryBuilderProvider>
        )}

        {activeTab === "headless" && (
          <HeadlessDemo schema={schema} onExecuteQuery={handleExecuteQuery} />
        )}

        {activeTab === "adapters" && <OrmAdaptersDemo />}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Headless Unstyled Component Demonstration
// ---------------------------------------------------------------------------
function HeadlessDemo({
  schema,
  onExecuteQuery,
}: {
  schema: SchemaSnapshot;
  onExecuteQuery: (sql: string, spec?: QuerySpec | null) => Promise<QueryResultData>;
}) {
  const tableNames = useMemo(() => Object.keys(schema.tables || {}), [schema]);
  const defaultTable = tableNames.length > 0 ? tableNames[0] : "products";

  const { state, compiled, actions, safety } = useQueryBuilder({
    schema,
    initialTable: defaultTable,
    dialect: "sqlite",
  });

  const { results, isLoading, error, executeQuery } = useQueryExecution({
    onExecuteQuery,
  });

  const activeColumns = schema.tables[state.primaryTable]?.columns || [];

  return (
    <div style={{ padding: "24px", maxWidth: "1200px", margin: "0 auto", overflowY: "auto", height: "100%" }}>
      <h2 style={{ color: "#38bdf8", marginTop: 0 }}>🧩 Unstyled Headless Query Builder</h2>
      <p style={{ color: "#94a3b8" }}>
        Demonstrating <code>useQueryBuilder</code> and <code>useQueryExecution</code> hooks with custom HTML elements and zero opinionated styles.
      </p>

      {/* Table Selector */}
      <div style={{ display: "flex", gap: "16px", alignItems: "center", marginBottom: "16px" }}>
        <label style={{ fontWeight: 600 }}>Select Table:</label>
        <select
          value={state.primaryTable}
          onChange={(e) => actions.setPrimaryTable(e.target.value)}
          style={{ padding: "8px 12px", borderRadius: "6px", backgroundColor: "#1e293b", color: "#fff", border: "1px solid #334155" }}
        >
          {tableNames.map((tbl) => (
            <option key={tbl} value={tbl}>{tbl}</option>
          ))}
        </select>

        <span style={{ fontSize: "0.85rem", color: safety.valid ? "#10b981" : "#ef4444" }}>
          AST Safety: {safety.valid ? "✓ Read-Only Safe" : `✗ ${safety.violations.join(", ") || safety.message}`}
        </span>
      </div>

      {/* Column Selectors */}
      <div style={{ marginBottom: "16px" }}>
        <div style={{ fontWeight: 600, marginBottom: "8px" }}>Select Columns to Project:</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
          {activeColumns.map((col) => {
            const isSelected = Boolean(state.selectedColumns[`${state.primaryTable}.${col.name}`]);
            return (
              <button
                key={col.name}
                onClick={() => actions.toggleColumn(state.primaryTable, col.name)}
                style={{
                  padding: "6px 12px",
                  borderRadius: "6px",
                  border: "1px solid #334155",
                  backgroundColor: isSelected ? "#2563eb" : "#1e293b",
                  color: "#fff",
                  cursor: "pointer",
                }}
              >
                {col.name} ({col.data_type})
              </button>
            );
          })}
        </div>
      </div>

      {/* Compiled SQL Output */}
      <div style={{ marginBottom: "16px" }}>
        <div style={{ fontWeight: 600, marginBottom: "8px" }}>Compiled SQL:</div>
        <pre
          style={{
            backgroundColor: "#020617",
            padding: "16px",
            borderRadius: "8px",
            color: "#38bdf8",
            overflowX: "auto",
            margin: 0,
            border: "1px solid #1e293b",
          }}
        >
          {compiled.sql || "SELECT * FROM ..."}
        </pre>
      </div>

      {/* Action Buttons */}
      <div style={{ marginBottom: "24px" }}>
        <button
          onClick={() => executeQuery(compiled.sql, compiled.spec)}
          disabled={isLoading || !safety.valid}
          style={{
            padding: "10px 24px",
            borderRadius: "6px",
            border: "none",
            backgroundColor: "#10b981",
            color: "#fff",
            fontWeight: "bold",
            cursor: "pointer",
            opacity: isLoading ? 0.7 : 1,
          }}
        >
          {isLoading ? "Executing Query..." : "▶ Run Query"}
        </button>
      </div>

      {error && (
        <div style={{ padding: "12px", backgroundColor: "#7f1d1d", color: "#fca5a5", borderRadius: "6px", marginBottom: "16px" }}>
          {error}
        </div>
      )}

      {/* Results View */}
      {results && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
            <h3 style={{ margin: 0 }}>Results ({results.count} rows)</h3>
            <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>
              Latency: {results.latency_ms} ms
            </span>
          </div>

          <div style={{ overflowX: "auto", border: "1px solid #334155", borderRadius: "8px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.9rem" }}>
              <thead style={{ backgroundColor: "#1e293b" }}>
                <tr>
                  {results.columns.map((col) => (
                    <th key={col} style={{ padding: "10px 14px", borderBottom: "1px solid #334155", color: "#e2e8f0" }}>
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.rows.map((row, idx) => (
                  <tr key={idx} style={{ backgroundColor: idx % 2 === 0 ? "#0f172a" : "#1e293b" }}>
                    {results.columns.map((col) => (
                      <td key={col} style={{ padding: "10px 14px", borderBottom: "1px solid #334155" }}>
                        {String(row[col] ?? "NULL")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ORM Adapters Live Demonstration Tab
// ---------------------------------------------------------------------------
function OrmAdaptersDemo() {
  const [selectedOrm, setSelectedOrm] = useState<"prisma" | "drizzle" | "sqlalchemy">("prisma");

  const { title, source, convertedTables } = useMemo(() => {
    if (selectedOrm === "prisma") {
      const tables = fromPrisma(SAMPLE_PRISMA);
      return { title: "Prisma Schema Adapter (fromPrisma)", source: SAMPLE_PRISMA, convertedTables: tables };
    }
    if (selectedOrm === "drizzle") {
      const tables = fromDrizzle(SAMPLE_DRIZZLE);
      return { title: "Drizzle ORM Adapter (fromDrizzle)", source: SAMPLE_DRIZZLE, convertedTables: tables };
    }
    const tables = fromSqlAlchemy(SAMPLE_SQLALCHEMY);
    return { title: "SQLAlchemy Adapter (fromSqlAlchemy)", source: SAMPLE_SQLALCHEMY, convertedTables: tables };
  }, [selectedOrm]);

  const snapshot = useMemo(() => toSchemaSnapshot(convertedTables), [convertedTables]);

  return (
    <div style={{ padding: "24px", maxWidth: "1200px", margin: "0 auto", overflowY: "auto", height: "100%" }}>
      <h2 style={{ color: "#38bdf8", marginTop: 0 }}>🔄 Client-Side ORM Adapters</h2>
      <p style={{ color: "#94a3b8" }}>
        Parse schemas from Prisma, Drizzle, and SQLAlchemy directly in the browser with 1 line of TypeScript.
      </p>

      {/* Sub tabs */}
      <div style={{ display: "flex", gap: "8px", marginBottom: "16px" }}>
        {(["prisma", "drizzle", "sqlalchemy"] as const).map((orm) => (
          <button
            key={orm}
            onClick={() => setSelectedOrm(orm)}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: "1px solid #334155",
              backgroundColor: selectedOrm === orm ? "#3b82f6" : "#1e293b",
              color: "#fff",
              cursor: "pointer",
              textTransform: "capitalize",
            }}
          >
            {orm}
          </button>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: "8px", color: "#f8fafc" }}>Source Definition ({title})</div>
          <pre
            style={{
              backgroundColor: "#020617",
              padding: "16px",
              borderRadius: "8px",
              color: "#f1f5f9",
              fontSize: "0.85rem",
              border: "1px solid #1e293b",
              height: "400px",
              overflowY: "auto",
            }}
          >
            {source}
          </pre>
        </div>

        <div>
          <div style={{ fontWeight: 600, marginBottom: "8px", color: "#10b981" }}>
            Query-Builder Schema Snapshot (Tables: {convertedTables.length})
          </div>
          <pre
            style={{
              backgroundColor: "#020617",
              padding: "16px",
              borderRadius: "8px",
              color: "#10b981",
              fontSize: "0.85rem",
              border: "1px solid #1e293b",
              height: "400px",
              overflowY: "auto",
            }}
          >
            {JSON.stringify(snapshot, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}
