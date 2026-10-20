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
  type SerializedQuerySpec,
  type ExecuteQueryHandler,
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
  const [schema, setSchema] = useState<SchemaSnapshot>(FALLBACK_SCHEMA);
  const [serverStatus, setServerStatus] = useState<string>("checking...");
  const [selectedPreset, setSelectedPreset] = useState<SqlPreset | null>(null);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const [copiedQuery, setCopiedQuery] = useState(false);

  // Modern theme controller supporting system default, dark override, and light override
  const [themePreference, setThemePreference] = useState<"system" | "dark" | "light">(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("qb-theme-preference");
      if (stored === "dark" || stored === "light" || stored === "system") {
        return stored;
      }
    }
    return "system";
  });

  const [systemIsDark, setSystemIsDark] = useState<boolean>(() => {
    if (typeof window !== "undefined" && window.matchMedia) {
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    }
    return true;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => setSystemIsDark(e.matches);
    media.addEventListener("change", handler);
    return () => media.removeEventListener("change", handler);
  }, []);

  const resolvedTheme: "dark" | "light" = useMemo(() => {
    if (themePreference === "system") return systemIsDark ? "dark" : "light";
    return themePreference;
  }, [themePreference, systemIsDark]);

  useEffect(() => {
    if (typeof document !== "undefined") {
      let meta = document.querySelector('meta[name="color-scheme"]') as HTMLMetaElement | null;
      if (!meta) {
        meta = document.createElement("meta");
        meta.name = "color-scheme";
        document.head.appendChild(meta);
      }
      meta.content = themePreference === "system" ? "light dark" : resolvedTheme;
      document.documentElement.style.colorScheme = resolvedTheme;
    }
  }, [themePreference, resolvedTheme]);

  const cycleTheme = () => {
    setThemePreference((prev) => {
      const next = prev === "system" ? "dark" : prev === "dark" ? "light" : "system";
      localStorage.setItem("qb-theme-preference", next);
      return next;
    });
  };

  // Keyboard shortcut listener for Cmd+K / Ctrl+K
  useEffect(() => {
    const handleGlobalKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
      } else if (e.key === "Escape") {
        setIsCommandPaletteOpen(false);
      }
    };
    window.addEventListener("keydown", handleGlobalKey);
    return () => window.removeEventListener("keydown", handleGlobalKey);
  }, []);

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
    spec?: QuerySpec | SerializedQuerySpec | Record<string, unknown> | null,
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

  const isDark = resolvedTheme === "dark";

  const handleSelectPreset = (preset: SqlPreset) => {
    setSelectedPreset(preset);
    setActiveTab("visual");
    setIsCommandPaletteOpen(false);
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        backgroundColor: isDark ? "#090d16" : "#f8fafc",
        color: isDark ? "#f8fafc" : "#0f172a",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Header bar */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 24px",
          borderBottom: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#e2e8f0"}`,
          backgroundColor: isDark ? "rgba(19, 27, 46, 0.85)" : "rgba(255, 255, 255, 0.9)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          zIndex: 10,
        }}
      >
        {/* Brand & live status */}
        <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                fontSize: "1.3rem",
                background: "linear-gradient(135deg, #3b82f6, #8b5cf6)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                fontWeight: 800,
                letterSpacing: "-0.02em",
              }}
            >
              ⚡ Query-Builder Studio
            </span>
            <span
              style={{
                fontSize: "0.68rem",
                fontWeight: 700,
                padding: "2px 6px",
                borderRadius: "4px",
                backgroundColor: isDark ? "rgba(59, 130, 246, 0.18)" : "rgba(59, 130, 246, 0.1)",
                color: isDark ? "#93c5fd" : "#2563eb",
                border: "1px solid rgba(59, 130, 246, 0.3)",
              }}
            >
              v1.0.0
            </span>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              fontSize: "0.72rem",
              padding: "3px 10px",
              borderRadius: "9999px",
              backgroundColor: serverStatus.includes("Connected")
                ? isDark
                  ? "rgba(16, 185, 129, 0.15)"
                  : "rgba(16, 185, 129, 0.1)"
                : isDark
                  ? "rgba(245, 158, 11, 0.15)"
                  : "rgba(245, 158, 11, 0.1)",
              color: serverStatus.includes("Connected") ? "#10b981" : "#f59e0b",
              border: `1px solid ${
                serverStatus.includes("Connected")
                  ? "rgba(16, 185, 129, 0.35)"
                  : "rgba(245, 158, 11, 0.35)"
              }`,
            }}
          >
            <span
              style={{
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                backgroundColor: serverStatus.includes("Connected") ? "#10b981" : "#f59e0b",
                display: "inline-block",
                boxShadow: serverStatus.includes("Connected")
                  ? "0 0 8px #10b981"
                  : "0 0 8px #f59e0b",
              }}
            />
            {serverStatus}
          </div>
        </div>

        {/* Command Palette Trigger */}
        <button
          type="button"
          onClick={() => setIsCommandPaletteOpen(true)}
          title="Open Natural Language Command Palette (Cmd+K)"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            padding: "5px 12px",
            borderRadius: "8px",
            backgroundColor: isDark ? "rgba(15, 23, 42, 0.6)" : "#f1f5f9",
            color: isDark ? "#94a3b8" : "#64748b",
            border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"}`,
            cursor: "pointer",
            fontSize: "0.78rem",
            transition: "all 0.15s ease",
          }}
        >
          <span>✨ Natural Language & Presets...</span>
          <kbd
            style={{
              padding: "1px 5px",
              borderRadius: "4px",
              backgroundColor: isDark ? "rgba(255, 255, 255, 0.1)" : "#e2e8f0",
              fontSize: "0.68rem",
              fontWeight: 700,
            }}
          >
            ⌘K
          </kbd>
        </button>

        {/* Tab switcher + Theme toggle */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <div
            style={{
              display: "flex",
              backgroundColor: isDark ? "rgba(15, 23, 42, 0.7)" : "#f1f5f9",
              borderRadius: "8px",
              padding: "3px",
              border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#e2e8f0"}`,
            }}
          >
            {[
              { id: "visual", label: "🎨 Visual Studio" },
              { id: "dashboard", label: "📊 Dashboard & BI" },
              { id: "headless", label: "🧩 Headless Mode" },
              { id: "adapters", label: "🔄 ORM Adapters" },
            ].map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as typeof activeTab)}
                  style={{
                    padding: "6px 13px",
                    borderRadius: "6px",
                    border: "none",
                    cursor: "pointer",
                    fontSize: "0.82rem",
                    fontWeight: isActive ? 600 : 500,
                    backgroundColor: isActive
                      ? isDark
                        ? "#3b82f6"
                        : "#2563eb"
                      : "transparent",
                    color: isActive ? "#ffffff" : isDark ? "#94a3b8" : "#475569",
                    boxShadow: isActive ? "0 2px 8px rgba(37, 99, 235, 0.3)" : "none",
                    transition: "all 0.15s ease",
                  }}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Tri-state Theme Toggle */}
          <button
            onClick={cycleTheme}
            title={`Current theme: ${themePreference}. Click to cycle (System -> Dark -> Light)`}
            style={{
              marginLeft: "6px",
              padding: "6px 12px",
              borderRadius: "8px",
              border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.12)" : "#cbd5e1"}`,
              cursor: "pointer",
              fontWeight: 600,
              fontSize: "0.78rem",
              backgroundColor: isDark ? "#131b2e" : "#f1f5f9",
              color: isDark ? "#f8fafc" : "#0f172a",
              display: "flex",
              alignItems: "center",
              gap: "6px",
              transition: "all 0.15s ease",
            }}
          >
            {themePreference === "system" ? (
              <>
                <span>🌓</span>
                <span>System ({resolvedTheme})</span>
              </>
            ) : themePreference === "dark" ? (
              <>
                <span>🌙</span>
                <span>Dark</span>
              </>
            ) : (
              <>
                <span>☀️</span>
                <span>Light</span>
              </>
            )}
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {activeTab === "visual" && (
          <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
            {/* Quick Starters & Presets Bar */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "10px",
                padding: "8px 24px",
                backgroundColor: isDark ? "rgba(15, 23, 42, 0.4)" : "#ffffff",
                borderBottom: `1px solid ${isDark ? "rgba(255, 255, 255, 0.05)" : "#e2e8f0"}`,
                overflowX: "auto",
              }}
            >
              <span
                style={{
                  fontSize: "0.78rem",
                  fontWeight: 700,
                  color: isDark ? "#94a3b8" : "#64748b",
                  whiteSpace: "nowrap",
                }}
              >
                ⚡ Starters & Presets:
              </span>
              {STARTER_PRESETS.map((preset) => {
                const isSelected = selectedPreset?.id === preset.id;
                return (
                  <button
                    key={preset.id}
                    onClick={() => setSelectedPreset(preset)}
                    style={{
                      padding: "4px 10px",
                      borderRadius: "6px",
                      border: isSelected
                        ? "1px solid #3b82f6"
                        : `1px solid ${isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"}`,
                      backgroundColor: isSelected
                        ? "rgba(59, 130, 246, 0.15)"
                        : isDark
                          ? "rgba(30, 41, 59, 0.5)"
                          : "#f8fafc",
                      color: isSelected ? "#3b82f6" : isDark ? "#cbd5e1" : "#334155",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      cursor: "pointer",
                      whiteSpace: "nowrap",
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      transition: "all 0.15s ease",
                    }}
                  >
                    <span
                      style={{
                        fontSize: "0.65rem",
                        padding: "1px 5px",
                        borderRadius: "4px",
                        backgroundColor:
                          preset.category === "Sales"
                            ? "rgba(16, 185, 129, 0.18)"
                            : preset.category === "Inventory"
                              ? "rgba(59, 130, 246, 0.18)"
                              : preset.category === "Operations"
                                ? "rgba(245, 158, 11, 0.18)"
                                : "rgba(139, 92, 246, 0.18)",
                        color:
                          preset.category === "Sales"
                            ? "#10b981"
                            : preset.category === "Inventory"
                              ? "#3b82f6"
                              : preset.category === "Operations"
                                ? "#f59e0b"
                                : "#8b5cf6",
                      }}
                    >
                      {preset.category}
                    </span>
                    {preset.title}
                  </button>
                );
              })}
            </div>

            {/* Visual Builder Canvas */}
            <div style={{ flex: 1, overflowY: "auto", padding: "16px 24px" }}>
              <QueryBuilderProvider
                mode="styled"
                themeMode={resolvedTheme}
                customOperators={customOperators}
                cellRenderers={cellRenderers}
              >
                <VisualQueryBuilder
                  key={selectedPreset?.id || "default"}
                  schema={schema}
                  initialTable={
                    selectedPreset?.spec?.table ||
                    Object.keys(schema.tables || {})[0] ||
                    "products"
                  }
                  initialSpec={selectedPreset?.spec}
                  dialect="sqlite"
                  presets={STARTER_PRESETS}
                  semanticModels={STARTER_SEMANTIC_MODELS}
                  showPlanTab={true}
                  showPipelineTab={true}
                  showNlqBar={true}
                  onExecuteQuery={handleExecuteQuery}
                />
              </QueryBuilderProvider>
            </div>
          </div>
        )}

        {activeTab === "dashboard" && (
          <QueryBuilderProvider mode="styled" themeMode={resolvedTheme}>
            <DashboardAndExportDemo isDark={isDark} />
          </QueryBuilderProvider>
        )}

        {activeTab === "headless" && (
          <HeadlessDemo schema={schema} onExecuteQuery={handleExecuteQuery} isDark={isDark} />
        )}

        {activeTab === "adapters" && (
          <OrmAdaptersDemo
            isDark={isDark}
            onLoadSchema={(newSnapshot) => {
              setSchema(newSnapshot);
              setSelectedPreset(null);
              setActiveTab("visual");
            }}
          />
        )}
      </main>

      {/* Command Palette Modal (Cmd+K) */}
      {isCommandPaletteOpen && (
        <div
          onClick={() => setIsCommandPaletteOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.65)",
            backdropFilter: "blur(6px)",
            WebkitBackdropFilter: "blur(6px)",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "center",
            paddingTop: "12vh",
            zIndex: 100,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "100%",
              maxWidth: "640px",
              backgroundColor: isDark ? "#131b2e" : "#ffffff",
              borderRadius: "14px",
              border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.12)" : "#cbd5e1"}`,
              boxShadow: "0 20px 40px rgba(0, 0, 0, 0.4)",
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
            }}
          >
            {/* Search Input */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                padding: "16px 20px",
                borderBottom: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#e2e8f0"}`,
                gap: "12px",
              }}
            >
              <span style={{ fontSize: "1.2rem" }}>✨</span>
              <input
                type="text"
                autoFocus
                placeholder="Ask in English or search queries (e.g. 'Completed orders breakdown')..."
                style={{
                  flex: 1,
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  fontSize: "1rem",
                  color: isDark ? "#f8fafc" : "#0f172a",
                }}
              />
              <kbd
                style={{
                  padding: "2px 6px",
                  borderRadius: "4px",
                  backgroundColor: isDark ? "rgba(255, 255, 255, 0.1)" : "#e2e8f0",
                  fontSize: "0.72rem",
                  color: isDark ? "#94a3b8" : "#64748b",
                }}
              >
                ESC
              </kbd>
            </div>

            {/* Presets and suggestions list */}
            <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: "8px" }}>
              <span
                style={{
                  fontSize: "0.72rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: isDark ? "#94a3b8" : "#64748b",
                }}
              >
                Suggested Queries & Presets
              </span>
              {STARTER_PRESETS.map((preset) => (
                <div
                  key={preset.id}
                  onClick={() => handleSelectPreset(preset)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "10px 14px",
                    borderRadius: "8px",
                    cursor: "pointer",
                    backgroundColor: isDark ? "rgba(30, 41, 59, 0.5)" : "#f8fafc",
                    border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.05)" : "#e2e8f0"}`,
                    transition: "all 0.15s ease",
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{ fontWeight: 600, fontSize: "0.88rem" }}>{preset.title}</span>
                      <span
                        style={{
                          fontSize: "0.68rem",
                          padding: "1px 6px",
                          borderRadius: "4px",
                          backgroundColor: "rgba(59, 130, 246, 0.15)",
                          color: "#3b82f6",
                          fontWeight: 600,
                        }}
                      >
                        {preset.category}
                      </span>
                    </div>
                    <span style={{ fontSize: "0.75rem", color: isDark ? "#94a3b8" : "#64748b" }}>
                      {preset.description}
                    </span>
                  </div>
                  <span style={{ fontSize: "0.8rem", color: "#3b82f6", fontWeight: 600 }}>
                    Load →
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard & Export Workbench Demonstration Tab
// ---------------------------------------------------------------------------
function DashboardAndExportDemo({ isDark = true }: { isDark?: boolean }) {
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
        <h2
          style={{
            color: isDark ? "#38bdf8" : "#0284c7",
            marginTop: 0,
            marginBottom: "6px",
            fontSize: "1.3rem",
            fontWeight: 700,
          }}
        >
          📊 Interactive BI Dashboard & Multi-Format Export Workbench
        </h2>
        <p style={{ color: isDark ? "#94a3b8" : "#64748b", margin: 0, fontSize: "0.88rem" }}>
          Click any bar in a chart tile to cross-filter sibling tiles, or export queries below as TypeScript SDK code, dialect SQL, AST JSON, or streaming files.
        </p>
      </div>

      <DashboardWorkbench initialState={INITIAL_DASHBOARD_STATE} />

      <div>
        <h3
          style={{
            color: isDark ? "#38bdf8" : "#0284c7",
            marginBottom: "12px",
            fontSize: "1.1rem",
            fontWeight: 700,
          }}
        >
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
  isDark = true,
}: {
  schema: SchemaSnapshot;
  onExecuteQuery: (
    sql: string,
    spec?: QuerySpec | SerializedQuerySpec | Record<string, unknown> | null,
  ) => Promise<QueryResultData>;
  isDark?: boolean;
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

  const [copiedSql, setCopiedSql] = useState(false);
  const activeColumns = schema.tables[state.primaryTable]?.columns || [];

  const handleCopySql = () => {
    if (!compiled.sql) return;
    navigator.clipboard.writeText(compiled.sql);
    setCopiedSql(true);
    setTimeout(() => setCopiedSql(false), 2000);
  };

  const handleSelectAllColumns = () => {
    activeColumns.forEach((c) => {
      const colKey = `${state.primaryTable}.${c.name}`;
      if (!state.selectedColumns[colKey]) {
        actions.toggleColumn(state.primaryTable, c.name);
      }
    });
  };

  const handleClearAllColumns = () => {
    activeColumns.forEach((c) => {
      const colKey = `${state.primaryTable}.${c.name}`;
      if (state.selectedColumns[colKey]) {
        actions.toggleColumn(state.primaryTable, c.name);
      }
    });
  };

  const handleExportCsv = () => {
    if (!results || !results.rows.length) return;
    const header = results.columns.join(",");
    const rows = results.rows.map((row) =>
      results.columns
        .map((col) => {
          const val = row[col];
          if (val === null || val === undefined) return "";
          const str = String(val);
          return str.includes(",") ? `"${str.replace(/"/g, '""')}"` : str;
        })
        .join(","),
    );
    const csvContent = "data:text/csv;charset=utf-8," + [header, ...rows].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `${state.primaryTable}_headless_export.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const selectedCount = activeColumns.filter(
    (c) => state.selectedColumns[`${state.primaryTable}.${c.name}`],
  ).length;

  return (
    <div
      style={{
        padding: "24px",
        maxWidth: "1300px",
        margin: "0 auto",
        overflowY: "auto",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        gap: "20px",
      }}
    >
      <div>
        <h2
          style={{
            color: isDark ? "#38bdf8" : "#0284c7",
            marginTop: 0,
            marginBottom: "6px",
            fontSize: "1.3rem",
            fontWeight: 700,
          }}
        >
          🧩 Unstyled Headless Query Builder Architecture
        </h2>
        <p style={{ color: isDark ? "#94a3b8" : "#64748b", margin: 0, fontSize: "0.88rem" }}>
          Demonstrating <code>useQueryBuilder</code> and <code>useQueryExecution</code> hooks driving custom HTML elements with zero opinionated library CSS dependencies.
        </p>
      </div>

      {/* Control Surface Card */}
      <div
        style={{
          padding: "20px",
          borderRadius: "12px",
          backgroundColor: isDark ? "rgba(19, 27, 46, 0.7)" : "#ffffff",
          border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#e2e8f0"}`,
          boxShadow: isDark ? "0 4px 20px rgba(0, 0, 0, 0.25)" : "0 2px 10px rgba(0, 0, 0, 0.04)",
          display: "flex",
          flexDirection: "column",
          gap: "18px",
        }}
      >
        {/* Table Selector & AST Safety Row */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "12px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <label
              style={{
                fontSize: "0.85rem",
                fontWeight: 600,
                color: isDark ? "#e2e8f0" : "#334155",
              }}
            >
              Primary Table:
            </label>
            <select
              value={state.primaryTable}
              onChange={(e) => actions.setPrimaryTable(e.target.value)}
              style={{
                padding: "7px 14px",
                borderRadius: "8px",
                backgroundColor: isDark ? "#0f172a" : "#f8fafc",
                color: isDark ? "#f8fafc" : "#0f172a",
                border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.15)" : "#cbd5e1"}`,
                fontSize: "0.85rem",
                fontWeight: 600,
                cursor: "pointer",
                outline: "none",
              }}
            >
              {tableNames.map((tbl) => (
                <option key={tbl} value={tbl}>
                  {tbl}
                </option>
              ))}
            </select>
            <span
              style={{
                fontSize: "0.75rem",
                color: isDark ? "#64748b" : "#94a3b8",
                fontWeight: 500,
              }}
            >
              ({tableNames.length} tables available)
            </span>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "4px 12px",
              borderRadius: "9999px",
              fontSize: "0.78rem",
              fontWeight: 600,
              backgroundColor: safety.valid
                ? "rgba(16, 185, 129, 0.12)"
                : "rgba(239, 68, 68, 0.12)",
              color: safety.valid ? "#10b981" : "#ef4444",
              border: `1px solid ${
                safety.valid ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"
              }`,
            }}
          >
            <span>{safety.valid ? "🛡️" : "⚠️"}</span>
            <span>
              AST Safety:{" "}
              {safety.valid
                ? "Read-Only Safe"
                : safety.violations.join(", ") || safety.message}
            </span>
          </div>
        </div>

        {/* Column Selectors */}
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "10px",
            }}
          >
            <div
              style={{
                fontSize: "0.85rem",
                fontWeight: 600,
                color: isDark ? "#e2e8f0" : "#334155",
              }}
            >
              Select Columns to Project:{" "}
              <span
                style={{
                  fontSize: "0.78rem",
                  fontWeight: 500,
                  color: isDark ? "#94a3b8" : "#64748b",
                }}
              >
                ({selectedCount} of {activeColumns.length} selected)
              </span>
            </div>

            <div style={{ display: "flex", gap: "8px" }}>
              <button
                type="button"
                onClick={handleSelectAllColumns}
                style={{
                  padding: "3px 8px",
                  borderRadius: "5px",
                  border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"}`,
                  backgroundColor: isDark ? "rgba(30, 41, 59, 0.5)" : "#f1f5f9",
                  color: isDark ? "#94a3b8" : "#475569",
                  fontSize: "0.72rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Select All
              </button>
              <button
                type="button"
                onClick={handleClearAllColumns}
                style={{
                  padding: "3px 8px",
                  borderRadius: "5px",
                  border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"}`,
                  backgroundColor: isDark ? "rgba(30, 41, 59, 0.5)" : "#f1f5f9",
                  color: isDark ? "#94a3b8" : "#475569",
                  fontSize: "0.72rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Clear
              </button>
            </div>
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
            {activeColumns.map((col) => {
              const isSelected = Boolean(
                state.selectedColumns[`${state.primaryTable}.${col.name}`],
              );
              return (
                <button
                  key={col.name}
                  type="button"
                  onClick={() => actions.toggleColumn(state.primaryTable, col.name)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "6px 12px",
                    borderRadius: "7px",
                    border: isSelected
                      ? "1px solid #3b82f6"
                      : `1px solid ${isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"}`,
                    backgroundColor: isSelected
                      ? isDark
                        ? "#1d4ed8"
                        : "#2563eb"
                      : isDark
                        ? "rgba(30, 41, 59, 0.6)"
                        : "#f8fafc",
                    color: isSelected ? "#ffffff" : isDark ? "#e2e8f0" : "#334155",
                    cursor: "pointer",
                    fontSize: "0.82rem",
                    fontWeight: 500,
                    transition: "all 0.15s ease",
                  }}
                >
                  <span>{isSelected ? "✓" : "+"}</span>
                  <span style={{ fontWeight: 600 }}>{col.name}</span>
                  <span
                    style={{
                      fontSize: "0.68rem",
                      padding: "1px 5px",
                      borderRadius: "4px",
                      backgroundColor: isSelected
                        ? "rgba(255, 255, 255, 0.2)"
                        : isDark
                          ? "rgba(255, 255, 255, 0.08)"
                          : "#e2e8f0",
                      color: isSelected ? "#ffffff" : isDark ? "#94a3b8" : "#64748b",
                      fontFamily: "monospace",
                    }}
                  >
                    {col.data_type}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Compiled SQL Output Box */}
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "8px",
            }}
          >
            <span
              style={{
                fontSize: "0.85rem",
                fontWeight: 600,
                color: isDark ? "#e2e8f0" : "#334155",
              }}
            >
              Compiled SQL:
            </span>
            <button
              type="button"
              onClick={handleCopySql}
              style={{
                padding: "3px 10px",
                borderRadius: "5px",
                border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"}`,
                backgroundColor: isDark ? "rgba(30, 41, 59, 0.6)" : "#f1f5f9",
                color: copiedSql ? "#10b981" : isDark ? "#94a3b8" : "#475569",
                fontSize: "0.75rem",
                fontWeight: 600,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "4px",
              }}
            >
              <span>{copiedSql ? "✓ Copied" : "📋 Copy SQL"}</span>
            </button>
          </div>
          <pre
            style={{
              backgroundColor: isDark ? "#020617" : "#0f172a",
              padding: "14px 18px",
              borderRadius: "8px",
              color: "#38bdf8",
              fontFamily: "ui-monospace, monospace",
              fontSize: "0.85rem",
              lineHeight: 1.5,
              overflowX: "auto",
              margin: 0,
              border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#334155"}`,
            }}
          >
            {compiled.sql || "SELECT * FROM ..."}
          </pre>
        </div>

        {/* Action Button */}
        <div>
          <button
            type="button"
            onClick={() => executeQuery(compiled.sql, compiled.spec)}
            disabled={isLoading || !safety.valid}
            style={{
              padding: "10px 24px",
              borderRadius: "8px",
              border: "none",
              backgroundColor: isLoading || !safety.valid ? "#64748b" : "#10b981",
              backgroundImage:
                isLoading || !safety.valid
                  ? "none"
                  : "linear-gradient(135deg, #10b981, #059669)",
              color: "#ffffff",
              fontWeight: 700,
              fontSize: "0.88rem",
              cursor: isLoading || !safety.valid ? "not-allowed" : "pointer",
              boxShadow:
                isLoading || !safety.valid
                  ? "none"
                  : "0 2px 10px rgba(16, 185, 129, 0.35)",
              display: "flex",
              alignItems: "center",
              gap: "8px",
              transition: "all 0.15s ease",
            }}
          >
            {isLoading ? (
              <>
                <span>⏳</span>
                <span>Executing Headless Query...</span>
              </>
            ) : (
              <>
                <span>▶</span>
                <span>Run Query</span>
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            padding: "14px 18px",
            backgroundColor: isDark ? "rgba(127, 29, 29, 0.4)" : "#fee2e2",
            color: isDark ? "#fca5a5" : "#b91c1c",
            borderRadius: "8px",
            border: `1px solid ${isDark ? "#7f1d1d" : "#fca5a5"}`,
            fontSize: "0.85rem",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <span>❌</span>
          <span>{error}</span>
        </div>
      )}

      {/* Results View */}
      {results ? (
        <div
          style={{
            padding: "20px",
            borderRadius: "12px",
            backgroundColor: isDark ? "rgba(19, 27, 46, 0.7)" : "#ffffff",
            border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#e2e8f0"}`,
            boxShadow: isDark ? "0 4px 20px rgba(0, 0, 0, 0.25)" : "0 2px 10px rgba(0, 0, 0, 0.04)",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "14px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <h3
                style={{
                  margin: 0,
                  fontSize: "1.05rem",
                  fontWeight: 700,
                  color: isDark ? "#f8fafc" : "#0f172a",
                }}
              >
                Query Results ({results.count} rows)
              </h3>
              <span
                style={{
                  fontSize: "0.75rem",
                  padding: "2px 8px",
                  borderRadius: "9999px",
                  backgroundColor: isDark ? "rgba(59, 130, 246, 0.15)" : "#dbeafe",
                  color: isDark ? "#93c5fd" : "#1d4ed8",
                  fontWeight: 600,
                }}
              >
                ⚡ Latency: {results.latency_ms} ms
              </span>
            </div>

            <button
              type="button"
              onClick={handleExportCsv}
              style={{
                padding: "5px 12px",
                borderRadius: "6px",
                border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"}`,
                backgroundColor: isDark ? "rgba(30, 41, 59, 0.6)" : "#f1f5f9",
                color: isDark ? "#cbd5e1" : "#334155",
                fontSize: "0.78rem",
                fontWeight: 600,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              <span>📥</span>
              <span>Export CSV</span>
            </button>
          </div>

          <div
            style={{
              overflowX: "auto",
              border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#cbd5e1"}`,
              borderRadius: "8px",
            }}
          >
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                textAlign: "left",
                fontSize: "0.85rem",
              }}
            >
              <thead
                style={{
                  backgroundColor: isDark ? "rgba(15, 23, 42, 0.9)" : "#f1f5f9",
                }}
              >
                <tr>
                  {results.columns.map((col) => (
                    <th
                      key={col}
                      style={{
                        padding: "10px 14px",
                        borderBottom: `1px solid ${
                          isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"
                        }`,
                        color: isDark ? "#e2e8f0" : "#334155",
                        fontWeight: 700,
                        fontSize: "0.8rem",
                      }}
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.rows.map((row, idx) => (
                  <tr
                    key={idx}
                    style={{
                      backgroundColor:
                        idx % 2 === 0
                          ? isDark
                            ? "rgba(15, 23, 42, 0.4)"
                            : "#ffffff"
                          : isDark
                            ? "rgba(30, 41, 59, 0.3)"
                            : "#f8fafc",
                      borderBottom: `1px solid ${
                        isDark ? "rgba(255, 255, 255, 0.05)" : "#f1f5f9"
                      }`,
                    }}
                  >
                    {results.columns.map((col) => (
                      <td
                        key={col}
                        style={{
                          padding: "9px 14px",
                          color:
                            row[col] === null || row[col] === undefined
                              ? isDark
                                ? "#64748b"
                                : "#94a3b8"
                              : isDark
                                ? "#f1f5f9"
                                : "#1e293b",
                          fontStyle:
                            row[col] === null || row[col] === undefined
                              ? "italic"
                              : "normal",
                        }}
                      >
                        {String(row[col] ?? "NULL")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div
          style={{
            padding: "40px 20px",
            textAlign: "center",
            borderRadius: "12px",
            border: `2px dashed ${isDark ? "rgba(255, 255, 255, 0.08)" : "#cbd5e1"}`,
            color: isDark ? "#64748b" : "#94a3b8",
            fontSize: "0.88rem",
          }}
        >
          Select columns above and click <strong>"▶ Run Query"</strong> to test headless execution.
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
  isDark = true,
}: {
  onLoadSchema: (snapshot: SchemaSnapshot) => void;
  isDark?: boolean;
}) {
  const [selectedOrm, setSelectedOrm] = useState<"prisma" | "drizzle" | "sqlalchemy">("prisma");
  const [sources, setSources] = useState<Record<"prisma" | "drizzle" | "sqlalchemy", string>>({
    prisma: SAMPLE_PRISMA,
    drizzle: SAMPLE_DRIZZLE,
    sqlalchemy: SAMPLE_SQLALCHEMY,
  });

  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

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

  const handleReset = () => {
    const defaultVal =
      selectedOrm === "prisma"
        ? SAMPLE_PRISMA
        : selectedOrm === "drizzle"
          ? SAMPLE_DRIZZLE
          : SAMPLE_SQLALCHEMY;
    setSources((prev) => ({ ...prev, [selectedOrm]: defaultVal }));
  };

  const handleCopyCode = () => {
    navigator.clipboard.writeText(activeSource);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  const handleCopySnapshot = () => {
    navigator.clipboard.writeText(JSON.stringify(snapshot, null, 2));
    setCopiedSnapshot(true);
    setTimeout(() => setCopiedSnapshot(false), 2000);
  };

  const handleLoad = () => {
    setToastMessage("Schema loaded successfully! Switching to Visual Studio...");
    setTimeout(() => {
      onLoadSchema(snapshot);
    }, 600);
  };

  const ormMeta = {
    prisma: { label: "Prisma", filename: "schema.prisma", icon: "💎" },
    drizzle: { label: "Drizzle", filename: "schema.ts", icon: "💧" },
    sqlalchemy: { label: "SQLAlchemy", filename: "models.py", icon: "🐍" },
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
        gap: "20px",
      }}
    >
      {/* Toast Notification */}
      {toastMessage && (
        <div
          style={{
            position: "fixed",
            bottom: "24px",
            right: "24px",
            backgroundColor: "#10b981",
            color: "#ffffff",
            padding: "12px 20px",
            borderRadius: "8px",
            boxShadow: "0 4px 16px rgba(16, 185, 129, 0.4)",
            fontWeight: 600,
            fontSize: "0.85rem",
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <span>✓</span>
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Header Row */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "16px",
          flexWrap: "wrap",
        }}
      >
        <div>
          <h2
            style={{
              color: isDark ? "#38bdf8" : "#0284c7",
              marginTop: 0,
              marginBottom: "6px",
              fontSize: "1.3rem",
              fontWeight: 700,
            }}
          >
            🔄 Client-Side ORM Adapters
          </h2>
          <p style={{ color: isDark ? "#94a3b8" : "#64748b", margin: 0, fontSize: "0.88rem" }}>
            Edit any Prisma, Drizzle, or SQLAlchemy schema below to live-compile a Query-Builder SchemaSnapshot and load it directly into Visual Studio.
          </p>
        </div>

        <button
          type="button"
          onClick={handleLoad}
          disabled={convertedTables.length === 0}
          style={{
            padding: "10px 20px",
            borderRadius: "8px",
            border: "none",
            backgroundColor: convertedTables.length > 0 ? "#10b981" : "#475569",
            backgroundImage:
              convertedTables.length > 0
                ? "linear-gradient(135deg, #10b981, #059669)"
                : "none",
            color: "#ffffff",
            fontWeight: 700,
            fontSize: "0.85rem",
            cursor: convertedTables.length > 0 ? "pointer" : "not-allowed",
            whiteSpace: "nowrap",
            boxShadow:
              convertedTables.length > 0
                ? "0 2px 10px rgba(16, 185, 129, 0.3)"
                : "none",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            transition: "all 0.15s ease",
          }}
        >
          <span>🚀</span>
          <span>Load Schema into Visual Studio</span>
        </button>
      </div>

      {/* Segmented ORM Switcher Bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
        }}
      >
        <div
          style={{
            display: "flex",
            gap: "6px",
            backgroundColor: isDark ? "rgba(15, 23, 42, 0.7)" : "#f1f5f9",
            padding: "4px",
            borderRadius: "8px",
            border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#e2e8f0"}`,
          }}
        >
          {(["prisma", "drizzle", "sqlalchemy"] as const).map((orm) => {
            const meta = ormMeta[orm];
            const isSelected = selectedOrm === orm;
            return (
              <button
                key={orm}
                type="button"
                onClick={() => setSelectedOrm(orm)}
                style={{
                  padding: "7px 16px",
                  borderRadius: "6px",
                  border: "none",
                  backgroundColor: isSelected
                    ? isDark
                      ? "#3b82f6"
                      : "#2563eb"
                    : "transparent",
                  color: isSelected ? "#ffffff" : isDark ? "#94a3b8" : "#475569",
                  fontWeight: isSelected ? 600 : 500,
                  fontSize: "0.82rem",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  boxShadow: isSelected ? "0 2px 8px rgba(37, 99, 235, 0.3)" : "none",
                  transition: "all 0.15s ease",
                }}
              >
                <span>{meta.icon}</span>
                <span>{meta.label}</span>
              </button>
            );
          })}
        </div>

        <button
          type="button"
          onClick={handleReset}
          style={{
            padding: "6px 12px",
            borderRadius: "6px",
            border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"}`,
            backgroundColor: isDark ? "rgba(30, 41, 59, 0.5)" : "#f1f5f9",
            color: isDark ? "#94a3b8" : "#475569",
            fontSize: "0.78rem",
            fontWeight: 600,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: "5px",
          }}
        >
          <span>↺</span>
          <span>Reset Sample</span>
        </button>
      </div>

      {/* Two Column Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "20px",
          flex: 1,
          minHeight: "480px",
        }}
      >
        {/* Left Column: Editable Source */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            borderRadius: "10px",
            overflow: "hidden",
            border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#cbd5e1"}`,
            backgroundColor: isDark ? "#020617" : "#0f172a",
          }}
        >
          <div
            style={{
              padding: "10px 16px",
              backgroundColor: isDark ? "rgba(15, 23, 42, 0.9)" : "#1e293b",
              borderBottom: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#334155"}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "0.85rem", fontWeight: 700, color: "#e2e8f0" }}>
                {title}
              </span>
              <span
                style={{
                  fontSize: "0.68rem",
                  padding: "1px 6px",
                  borderRadius: "4px",
                  backgroundColor: "rgba(59, 130, 246, 0.15)",
                  color: "#60a5fa",
                  fontFamily: "monospace",
                }}
              >
                {ormMeta[selectedOrm].filename}
              </span>
            </div>

            <button
              type="button"
              onClick={handleCopyCode}
              style={{
                padding: "3px 10px",
                borderRadius: "5px",
                border: "1px solid rgba(255, 255, 255, 0.15)",
                backgroundColor: "rgba(255, 255, 255, 0.05)",
                color: copiedCode ? "#10b981" : "#94a3b8",
                fontSize: "0.72rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {copiedCode ? "✓ Copied" : "📋 Copy"}
            </button>
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
              flex: 1,
              width: "100%",
              boxSizing: "border-box",
              backgroundColor: "transparent",
              padding: "16px",
              color: "#f1f5f9",
              fontFamily: "ui-monospace, monospace",
              fontSize: "0.85rem",
              lineHeight: 1.5,
              border: "none",
              outline: "none",
              resize: "none",
            }}
          />
        </div>

        {/* Right Column: Schema Snapshot */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            borderRadius: "10px",
            overflow: "hidden",
            border: `1px solid ${
              parseError
                ? isDark
                  ? "#7f1d1d"
                  : "#fca5a5"
                : isDark
                  ? "rgba(255, 255, 255, 0.08)"
                  : "#cbd5e1"
            }`,
            backgroundColor: parseError
              ? isDark
                ? "rgba(69, 10, 10, 0.5)"
                : "#fef2f2"
              : isDark
                ? "#020617"
                : "#0f172a",
          }}
        >
          <div
            style={{
              padding: "10px 16px",
              backgroundColor: isDark ? "rgba(15, 23, 42, 0.9)" : "#1e293b",
              borderBottom: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#334155"}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span
                style={{
                  fontSize: "0.85rem",
                  fontWeight: 700,
                  color: parseError ? "#f87171" : "#10b981",
                }}
              >
                Query-Builder Schema Snapshot
              </span>
              <span
                style={{
                  fontSize: "0.68rem",
                  padding: "1px 6px",
                  borderRadius: "4px",
                  backgroundColor: parseError
                    ? "rgba(239, 68, 68, 0.15)"
                    : "rgba(16, 185, 129, 0.15)",
                  color: parseError ? "#f87171" : "#34d399",
                  fontWeight: 600,
                }}
              >
                {parseError ? "Parse Error" : `${convertedTables.length} tables parsed`}
              </span>
            </div>

            {!parseError && (
              <button
                type="button"
                onClick={handleCopySnapshot}
                style={{
                  padding: "3px 10px",
                  borderRadius: "5px",
                  border: "1px solid rgba(255, 255, 255, 0.15)",
                  backgroundColor: "rgba(255, 255, 255, 0.05)",
                  color: copiedSnapshot ? "#10b981" : "#94a3b8",
                  fontSize: "0.72rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {copiedSnapshot ? "✓ Copied" : "📋 Copy JSON"}
              </button>
            )}
          </div>

          {parseError ? (
            <div
              style={{
                flex: 1,
                padding: "20px",
                color: isDark ? "#fca5a5" : "#b91c1c",
                fontSize: "0.85rem",
                fontFamily: "ui-monospace, monospace",
                lineHeight: 1.5,
                overflowY: "auto",
                whiteSpace: "pre-wrap",
              }}
            >
              ⚠️ Adapter Parse Error:
              {"\n\n"}
              {parseError}
            </div>
          ) : (
            <pre
              style={{
                flex: 1,
                margin: 0,
                padding: "16px",
                color: "#10b981",
                fontFamily: "ui-monospace, monospace",
                fontSize: "0.82rem",
                lineHeight: 1.45,
                overflowY: "auto",
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
