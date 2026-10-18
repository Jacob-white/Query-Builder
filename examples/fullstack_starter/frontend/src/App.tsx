import React, { useState, useEffect, useMemo } from "react";
import {
  QueryBuilderProvider,
  VisualQueryBuilder,
  DashboardWorkbench,
  ExportWorkbench,
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
  type SqlPreset,
  type SemanticModel,
  type DashboardState,
  type ExportFormat,
} from "@jacob-white/query-builder-react";

// Fallback initial schema generated via fromPrisma in case backend is offline
const FALLBACK_PRISMA = `
datasource db {
  provider = "sqlite"
  url = "file:./starter.db"
}

enum ProductStatus {
  IN_STOCK
  LOW_STOCK
  OUT_OF_STOCK
}

enum UserRole {
  ADMIN
  CUSTOMER
  GUEST
}

enum OrderStatus {
  PENDING
  COMPLETED
  CANCELLED
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
  id            Int           @id @default(autoincrement())
  categoryId    Int           @map("category_id")
  name          String
  price         Float
  stockQuantity Int           @default(0) @map("stock_quantity")
  status        ProductStatus
  description   String?
  category      Category      @relation(fields: [categoryId], references: [id])
  orderItems    OrderItem[]
  @@map("products")
}

model User {
  id        Int      @id @default(autoincrement())
  email     String   @unique
  fullName  String   @map("full_name")
  role      UserRole
  createdAt String   @map("created_at")
  lastLogin String?  @map("last_login")
  orders    Order[]
  @@map("users")
}

model Order {
  id              Int         @id @default(autoincrement())
  userId          Int         @map("user_id")
  status          OrderStatus
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

// 1. Custom filter operator (also registered on the FastAPI backend via register_filter_operator)
const customOperators: Record<string, CustomFilterOperator> = {
  TAX_EXEMPT: {
    label: "Tax Exempt Item",
    value: "TAX_EXEMPT",
    hasValue: false,
    formatSql: (colRef: string) => `${colRef} IS NOT NULL AND ${colRef} = 0`,
  },
};

// 2. Custom cell renderers for currency and status/role badges
function renderStatusBadge(val: unknown) {
  const status = String(val ?? "");
  let bg = "rgba(148, 163, 184, 0.18)";
  let fg = "#cbd5e1";
  let border = "rgba(148, 163, 184, 0.35)";

  if (status === "IN_STOCK" || status === "COMPLETED") {
    bg = "rgba(16, 185, 129, 0.16)";
    fg = "#34d399";
    border = "rgba(16, 185, 129, 0.4)";
  } else if (status === "LOW_STOCK" || status === "PENDING") {
    bg = "rgba(245, 158, 11, 0.16)";
    fg = "#fbbf24";
    border = "rgba(245, 158, 11, 0.4)";
  } else if (status === "OUT_OF_STOCK" || status === "CANCELLED") {
    bg = "rgba(239, 68, 68, 0.16)";
    fg = "#f87171";
    border = "rgba(239, 68, 68, 0.4)";
  }

  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: "9999px",
        fontSize: "0.72rem",
        fontWeight: 700,
        letterSpacing: "0.02em",
        backgroundColor: bg,
        color: fg,
        border: `1px solid ${border}`,
      }}
    >
      {status}
    </span>
  );
}

function renderRoleBadge(val: unknown) {
  const role = String(val ?? "");
  const palette: Record<string, { bg: string; fg: string; border: string }> = {
    ADMIN: {
      bg: "rgba(139, 92, 246, 0.18)",
      fg: "#c4b5fd",
      border: "rgba(139, 92, 246, 0.45)",
    },
    CUSTOMER: {
      bg: "rgba(59, 130, 246, 0.16)",
      fg: "#93c5fd",
      border: "rgba(59, 130, 246, 0.4)",
    },
    GUEST: {
      bg: "rgba(148, 163, 184, 0.16)",
      fg: "#cbd5e1",
      border: "rgba(148, 163, 184, 0.35)",
    },
  };
  const colors = palette[role] || palette.GUEST;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: "6px",
        fontSize: "0.72rem",
        fontWeight: 700,
        backgroundColor: colors.bg,
        color: colors.fg,
        border: `1px solid ${colors.border}`,
      }}
    >
      {role}
    </span>
  );
}

const cellRenderers = {
  price: (val: unknown) => (
    <span style={{ color: "#10b981", fontWeight: "bold", fontFamily: "monospace" }}>
      ${Number(val || 0).toFixed(2)}
    </span>
  ),
  unit_price: (val: unknown) => (
    <span style={{ color: "#10b981", fontWeight: "bold", fontFamily: "monospace" }}>
      ${Number(val || 0).toFixed(2)}
    </span>
  ),
  total_amount: (val: unknown) => (
    <span style={{ color: "#38bdf8", fontWeight: "bold", fontFamily: "monospace" }}>
      ${Number(val || 0).toFixed(2)}
    </span>
  ),
  status: (val: unknown) => renderStatusBadge(val),
  role: (val: unknown) => renderRoleBadge(val),
};

// 3. Curated E-Commerce Query Presets
const STARTER_PRESETS: SqlPreset[] = [
  {
    id: "completed_customer_orders",
    title: "Completed Customer Orders",
    category: "Sales",
    description: "Completed purchase orders joined with customer profile details, sorted by total amount.",
    spec: {
      table: "orders",
      columns: [
        "orders.id",
        "users.full_name",
        "users.email",
        "orders.status",
        "orders.total_amount",
        "orders.created_at",
      ],
      joins: [
        {
          table: "users",
          type: "INNER JOIN",
          left_table: "orders",
          left_col: "user_id",
          right_col: "id",
        },
      ],
      filters: [
        {
          tablePrefix: "orders",
          column: "status",
          op: "=",
          value: "COMPLETED",
        },
      ],
      order_by: [
        {
          tablePrefix: "orders",
          column: "total_amount",
          direction: "DESC",
        },
      ],
      limit: 25,
    },
  },
  {
    id: "catalog_revenue_by_category",
    title: "Catalog Inventory by Category",
    category: "Inventory",
    description: "Aggregate product count and average price across product categories.",
    spec: {
      table: "products",
      columns: [
        "categories.name",
        { column: "products.id", agg: "COUNT", alias: "product_count" },
        { column: "products.price", agg: "AVG", alias: "avg_price" },
        { column: "products.stock_quantity", agg: "SUM", alias: "total_units" },
      ],
      joins: [
        {
          table: "categories",
          type: "INNER JOIN",
          left_table: "products",
          left_col: "category_id",
          right_col: "id",
        },
      ],
      order_by: [
        {
          tablePrefix: "categories",
          column: "name",
          direction: "ASC",
        },
      ],
      limit: 25,
    },
  },
  {
    id: "low_stock_alert",
    title: "Low & Out-of-Stock Alert",
    category: "Operations",
    description: "Products with stock quantity at or below 10 units requiring replenishment.",
    spec: {
      table: "products",
      columns: [
        "products.id",
        "products.name",
        "products.status",
        "products.stock_quantity",
        "products.price",
      ],
      filters: [
        {
          tablePrefix: "products",
          column: "stock_quantity",
          op: "<=",
          value: 10,
        },
      ],
      order_by: [
        {
          tablePrefix: "products",
          column: "stock_quantity",
          direction: "ASC",
        },
      ],
      limit: 25,
    },
  },
  {
    id: "order_line_items_detail",
    title: "Order Line Items Breakdown",
    category: "Analytics",
    description: "Multi-table join across order_items, products, and orders.",
    spec: {
      table: "order_items",
      columns: [
        "order_items.id",
        "products.name",
        "order_items.quantity",
        "order_items.unit_price",
        "orders.status",
      ],
      joins: [
        {
          table: "products",
          type: "INNER JOIN",
          left_table: "order_items",
          left_col: "product_id",
          right_col: "id",
        },
        {
          table: "orders",
          type: "INNER JOIN",
          left_table: "order_items",
          left_col: "order_id",
          right_col: "id",
        },
      ],
      order_by: [
        {
          tablePrefix: "order_items",
          column: "unit_price",
          direction: "DESC",
        },
      ],
      limit: 50,
    },
  },
];

// 4. Semantic Layer Models (Metrics & Dimensions)
const STARTER_SEMANTIC_MODELS: SemanticModel[] = [
  {
    name: "orders_metrics",
    tableName: "orders",
    description: "Governing semantic metrics for customer orders and revenue.",
    primaryKey: "id",
    defaultTimeDimension: "created_at",
    dimensions: [
      {
        name: "order_status",
        title: "Order Status",
        sqlExpression: "orders.status",
        dataType: "text",
        table: "orders",
      },
      {
        name: "order_date",
        title: "Order Created Date",
        sqlExpression: "orders.created_at",
        dataType: "timestamp",
        timeGrains: ["day", "week", "month", "quarter", "year"],
        table: "orders",
      },
    ],
    metrics: [
      {
        name: "total_revenue",
        title: "Total Revenue",
        description: "Sum of order total_amount across selected orders.",
        sqlExpression: "orders.total_amount",
        aggregation: "sum",
        format: "currency",
        table: "orders",
      },
      {
        name: "completed_revenue",
        title: "Completed Revenue",
        description: "Revenue from orders with COMPLETED status.",
        sqlExpression: "orders.total_amount",
        aggregation: "sum",
        format: "currency",
        table: "orders",
        filters: [{ field: "orders.status", operator: "=", value: "COMPLETED" }],
      },
      {
        name: "order_count",
        title: "Order Count",
        description: "Total count of orders.",
        sqlExpression: "orders.id",
        aggregation: "count",
        format: "integer",
        table: "orders",
      },
      {
        name: "avg_order_value",
        title: "Average Order Value (AOV)",
        description: "Mean order value.",
        sqlExpression: "orders.total_amount",
        aggregation: "avg",
        format: "currency",
        table: "orders",
      },
    ],
  },
  {
    name: "products_metrics",
    tableName: "products",
    description: "Catalog inventory and pricing metrics.",
    primaryKey: "id",
    dimensions: [
      {
        name: "stock_status",
        title: "Inventory Status",
        sqlExpression: "products.status",
        dataType: "text",
        table: "products",
      },
    ],
    metrics: [
      {
        name: "in_stock_count",
        title: "In-Stock SKU Count",
        description: "Number of products currently marked IN_STOCK.",
        sqlExpression: "products.id",
        aggregation: "count",
        format: "integer",
        table: "products",
        filters: [{ field: "products.status", operator: "=", value: "IN_STOCK" }],
      },
      {
        name: "total_stock_units",
        title: "Total Inventory Units",
        description: "Sum of stock_quantity across catalog products.",
        sqlExpression: "products.stock_quantity",
        aggregation: "sum",
        format: "integer",
        table: "products",
      },
      {
        name: "avg_catalog_price",
        title: "Average Catalog Price",
        description: "Average unit price across catalog products.",
        sqlExpression: "products.price",
        aggregation: "avg",
        format: "currency",
        table: "products",
      },
    ],
  },
];

// Initial Dashboard state for the Dashboard & Export tab
const INITIAL_DASHBOARD_STATE: Partial<DashboardState> = {
  title: "E-Commerce Executive Overview",
  tiles: [
    {
      id: "tile-rev-kpi",
      title: "Total Completed Revenue ($)",
      type: "kpi",
      kpiConfig: {
        valueField: "revenue",
        statusColor: "#a6e3a1",
      },
      layout: { x: 0, y: 0, w: 1, h: 1 },
      cachedRows: [
        { category: "Electronics", status: "COMPLETED", revenue: 2878.98, orders: 2 },
        { category: "Home & Kitchen", status: "COMPLETED", revenue: 119.5, orders: 1 },
      ],
    },
    {
      id: "tile-cat-chart",
      title: "Revenue by Product Category",
      type: "chart",
      chartType: "bar",
      layout: { x: 1, y: 0, w: 2, h: 1 },
      cachedRows: [
        { category: "Electronics", region: "North America", revenue: 2828.98, units: 3 },
        { category: "Apparel", region: "Europe", revenue: 234.95, units: 2 },
        { category: "Home & Kitchen", region: "North America", revenue: 199.49, units: 2 },
        { category: "Books & Media", region: "North America", revenue: 45.0, units: 1 },
      ],
    },
    {
      id: "tile-orders-table",
      title: "Recent Customer Orders",
      type: "table",
      layout: { x: 0, y: 1, w: 3, h: 1 },
      cachedRows: [
        { order_id: 1, customer: "Bob Builder", category: "Electronics", status: "COMPLETED", revenue: 1428.99 },
        { order_id: 2, customer: "Bob Builder", category: "Home & Kitchen", status: "COMPLETED", revenue: 119.5 },
        { order_id: 3, customer: "Charlie Chen", category: "Apparel", status: "PENDING", revenue: 234.95 },
        { order_id: 4, customer: "Diana Prince", category: "Electronics", status: "COMPLETED", revenue: 1344.99 },
        { order_id: 5, customer: "Diana Prince", category: "Home & Kitchen", status: "CANCELLED", revenue: 79.99 },
      ],
    },
  ],
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
  const [activeTab, setActiveTab] = useState<"visual" | "headless" | "adapters" | "dashboard">("visual");
  const [themeMode, setThemeMode] = useState<"dark" | "light">("dark");
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

  const isDark = themeMode === "dark";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        backgroundColor: isDark ? "#0f172a" : "#f8fafc",
        color: isDark ? "#f8fafc" : "#0f172a",
      }}
    >
      {/* Header bar */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 24px",
          borderBottom: `1px solid ${isDark ? "#1e293b" : "#e2e8f0"}`,
          backgroundColor: isDark ? "#1e293b" : "#ffffff",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <h1 style={{ margin: 0, fontSize: "1.25rem", color: isDark ? "#f8fafc" : "#0f172a" }}>
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

        {/* Tab switcher + Theme toggle */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <button
            onClick={() => setActiveTab("visual")}
            style={{
              padding: "8px 14px",
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              fontWeight: 500,
              backgroundColor: activeTab === "visual" ? "#3b82f6" : isDark ? "#334155" : "#e2e8f0",
              color: activeTab === "visual" ? "#fff" : isDark ? "#fff" : "#1e293b",
            }}
          >
            🎨 Visual Studio
          </button>
          <button
            onClick={() => setActiveTab("dashboard")}
            style={{
              padding: "8px 14px",
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              fontWeight: 500,
              backgroundColor: activeTab === "dashboard" ? "#3b82f6" : isDark ? "#334155" : "#e2e8f0",
              color: activeTab === "dashboard" ? "#fff" : isDark ? "#fff" : "#1e293b",
            }}
          >
            📊 Dashboard & Export
          </button>
          <button
            onClick={() => setActiveTab("headless")}
            style={{
              padding: "8px 14px",
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              fontWeight: 500,
              backgroundColor: activeTab === "headless" ? "#3b82f6" : isDark ? "#334155" : "#e2e8f0",
              color: activeTab === "headless" ? "#fff" : isDark ? "#fff" : "#1e293b",
            }}
          >
            🧩 Headless Mode
          </button>
          <button
            onClick={() => setActiveTab("adapters")}
            style={{
              padding: "8px 14px",
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              fontWeight: 500,
              backgroundColor: activeTab === "adapters" ? "#3b82f6" : isDark ? "#334155" : "#e2e8f0",
              color: activeTab === "adapters" ? "#fff" : isDark ? "#fff" : "#1e293b",
            }}
          >
            🔄 ORM Adapters
          </button>

          <button
            onClick={() => setThemeMode((prev) => (prev === "dark" ? "light" : "dark"))}
            title="Toggle Light / Dark Theme"
            style={{
              marginLeft: "8px",
              padding: "8px 12px",
              borderRadius: "6px",
              border: `1px solid ${isDark ? "#475569" : "#cbd5e1"}`,
              cursor: "pointer",
              fontWeight: 600,
              backgroundColor: isDark ? "#0f172a" : "#f1f5f9",
              color: isDark ? "#f8fafc" : "#0f172a",
            }}
          >
            {isDark ? "☀️ Light" : "🌙 Dark"}
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main style={{ flex: 1, overflow: "hidden" }}>
        {activeTab === "visual" && (
          <QueryBuilderProvider
            mode="styled"
            themeMode={themeMode}
            customOperators={customOperators}
            cellRenderers={cellRenderers}
          >
            <VisualQueryBuilder
              schema={schema}
              initialTable={Object.keys(schema.tables || {})[0] || "products"}
              dialect="sqlite"
              presets={STARTER_PRESETS}
              semanticModels={STARTER_SEMANTIC_MODELS}
              showPlanTab={true}
              showPipelineTab={true}
              showNlqBar={true}
              onExecuteQuery={handleExecuteQuery}
            />
          </QueryBuilderProvider>
        )}

        {activeTab === "dashboard" && (
          <QueryBuilderProvider mode="styled" themeMode={themeMode}>
            <DashboardAndExportDemo />
          </QueryBuilderProvider>
        )}

        {activeTab === "headless" && (
          <HeadlessDemo schema={schema} onExecuteQuery={handleExecuteQuery} />
        )}

        {activeTab === "adapters" && (
          <OrmAdaptersDemo
            onLoadSchema={(newSnapshot) => {
              setSchema(newSnapshot);
              setActiveTab("visual");
            }}
          />
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard & Export Workbench Demonstration Tab
// ---------------------------------------------------------------------------
function DashboardAndExportDemo() {
  const sampleExportSpec: QuerySpec = useMemo(
    () => ({
      table: "orders",
      columns: ["orders.id", "orders.status", "orders.total_amount", "orders.created_at"],
      joins: [
        {
          table: "users",
          type: "INNER JOIN",
          left_table: "orders",
          left_col: "user_id",
          right_col: "id",
        },
      ],
      filters: [{ column: "status", tablePrefix: "orders", op: "=", value: "COMPLETED" }],
      filter_join: "AND",
      order_by: [{ column: "total_amount", tablePrefix: "orders", direction: "DESC" }],
      distinct: false,
      limit: 25,
    }),
    [],
  );

  const handleExportStream = async (format: ExportFormat) => {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format, spec: sampleExportSpec, stream: true }),
    });
    if (!res.ok) {
      throw new Error(`Export failed with HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `orders_export.${format === "excel" ? "xlsx" : format}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      style={{
        padding: "24px",
        maxWidth: "1400px",
        margin: "0 auto",
        overflowY: "auto",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        gap: "24px",
      }}
    >
      <div>
        <h2 style={{ color: "#38bdf8", marginTop: 0, marginBottom: "6px" }}>
          📊 Interactive BI Dashboard & Multi-Format Export Workbench
        </h2>
        <p style={{ color: "#94a3b8", margin: 0 }}>
          Click any bar in a chart tile to cross-filter sibling tiles, or export queries below as TypeScript SDK code, dialect SQL, AST JSON, or streaming files.
        </p>
      </div>

      <DashboardWorkbench initialState={INITIAL_DASHBOARD_STATE} />

      <div>
        <h3 style={{ color: "#38bdf8", marginBottom: "12px" }}>
          📦 Code Generation & Streaming Dataset Exporter
        </h3>
        <ExportWorkbench
          spec={sampleExportSpec}
          dialect="sqlite"
          streamEndpoint="/api/export"
          onExportStream={handleExportStream}
        />
      </div>
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
function OrmAdaptersDemo({
  onLoadSchema,
}: {
  onLoadSchema: (snapshot: SchemaSnapshot) => void;
}) {
  const [selectedOrm, setSelectedOrm] = useState<"prisma" | "drizzle" | "sqlalchemy">("prisma");
  const [sources, setSources] = useState<Record<"prisma" | "drizzle" | "sqlalchemy", string>>({
    prisma: SAMPLE_PRISMA,
    drizzle: SAMPLE_DRIZZLE,
    sqlalchemy: SAMPLE_SQLALCHEMY,
  });

  const activeSource = sources[selectedOrm];

  const { title, convertedTables, parseError } = useMemo(() => {
    const label =
      selectedOrm === "prisma"
        ? "Prisma Schema Adapter (fromPrisma)"
        : selectedOrm === "drizzle"
          ? "Drizzle ORM Adapter (fromDrizzle)"
          : "SQLAlchemy Adapter (fromSqlAlchemy)";
    try {
      const tables =
        selectedOrm === "prisma"
          ? fromPrisma(activeSource)
          : selectedOrm === "drizzle"
            ? fromDrizzle(activeSource)
            : fromSqlAlchemy(activeSource);
      return { title: label, convertedTables: tables, parseError: null };
    } catch (err) {
      return {
        title: label,
        convertedTables: [],
        parseError: err instanceof Error ? err.message : String(err),
      };
    }
  }, [selectedOrm, activeSource]);

  const snapshot = useMemo(() => toSchemaSnapshot(convertedTables), [convertedTables]);

  return (
    <div style={{ padding: "24px", maxWidth: "1200px", margin: "0 auto", overflowY: "auto", height: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "16px", marginBottom: "16px" }}>
        <div>
          <h2 style={{ color: "#38bdf8", marginTop: 0, marginBottom: "6px" }}>🔄 Client-Side ORM Adapters</h2>
          <p style={{ color: "#94a3b8", margin: 0 }}>
            Edit any Prisma, Drizzle, or SQLAlchemy schema below to live-compile a Query-Builder SchemaSnapshot and load it directly into Visual Studio.
          </p>
        </div>
        <button
          onClick={() => onLoadSchema(snapshot)}
          disabled={convertedTables.length === 0}
          style={{
            padding: "10px 18px",
            borderRadius: "8px",
            border: "none",
            backgroundColor: convertedTables.length > 0 ? "#10b981" : "#475569",
            color: "#fff",
            fontWeight: 700,
            cursor: convertedTables.length > 0 ? "pointer" : "not-allowed",
            whiteSpace: "nowrap",
          }}
        >
          🚀 Load Schema into Visual Studio
        </button>
      </div>

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
          <div style={{ fontWeight: 600, marginBottom: "8px" }}>
            Editable Source Definition ({title})
          </div>
          <textarea
            value={activeSource}
            onChange={(e) =>
              setSources((prev) => ({
                ...prev,
                [selectedOrm]: e.target.value,
              }))
            }
            spellCheck={false}
            style={{
              width: "100%",
              boxSizing: "border-box",
              backgroundColor: "#020617",
              padding: "16px",
              borderRadius: "8px",
              color: "#f1f5f9",
              fontFamily: "monospace",
              fontSize: "0.85rem",
              border: "1px solid #1e293b",
              height: "420px",
              resize: "vertical",
            }}
          />
        </div>

        <div>
          <div style={{ fontWeight: 600, marginBottom: "8px", color: "#10b981" }}>
            Query-Builder Schema Snapshot (Tables: {convertedTables.length})
          </div>
          {parseError ? (
            <pre
              style={{
                backgroundColor: "#450a0a",
                padding: "16px",
                borderRadius: "8px",
                color: "#fca5a5",
                fontSize: "0.85rem",
                border: "1px solid #7f1d1d",
                height: "420px",
                overflowY: "auto",
                margin: 0,
              }}
            >
              {parseError}
            </pre>
          ) : (
            <pre
              style={{
                backgroundColor: "#020617",
                padding: "16px",
                borderRadius: "8px",
                color: "#10b981",
                fontSize: "0.85rem",
                border: "1px solid #1e293b",
                height: "420px",
                overflowY: "auto",
                margin: 0,
              }}
            >
              {JSON.stringify(snapshot, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
