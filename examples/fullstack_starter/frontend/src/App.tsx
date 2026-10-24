import React, { useState, useEffect, useMemo, useRef } from "react";
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
  findBestJoinCondition,
  type VisualQueryBuilderRef,
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

const SR_ONLY_STYLE: React.CSSProperties = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

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
  let bg = "var(--qb-color-none-bg, rgba(148, 163, 184, 0.18))";
  let fg = "var(--qb-color-text-secondary, #475569)";
  let border = "var(--qb-color-none-border, rgba(148, 163, 184, 0.35))";

  if (status === "IN_STOCK" || status === "COMPLETED") {
    bg = "var(--qb-color-confirmed-bg, rgba(16, 185, 129, 0.16))";
    fg = "var(--qb-color-confirmed-text, #047857)";
    border = "var(--qb-color-confirmed-border, rgba(16, 185, 129, 0.4))";
  } else if (status === "LOW_STOCK" || status === "PENDING") {
    bg = "var(--qb-color-warn-bg, rgba(245, 158, 11, 0.16))";
    fg = "var(--qb-color-warn-text, #b45309)";
    border = "var(--qb-color-warn-border, rgba(245, 158, 11, 0.4))";
  } else if (status === "OUT_OF_STOCK" || status === "CANCELLED") {
    bg = "rgba(239, 68, 68, 0.14)";
    fg = "var(--qb-color-error, #dc2626)";
    border = "rgba(239, 68, 68, 0.38)";
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
      bg: "rgba(139, 92, 246, 0.14)",
      fg: "var(--qb-color-logical-text, #6d28d9)",
      border: "rgba(139, 92, 246, 0.4)",
    },
    CUSTOMER: {
      bg: "var(--qb-color-logical-bg, rgba(59, 130, 246, 0.14))",
      fg: "var(--qb-color-logical-text, #1d4ed8)",
      border: "var(--qb-color-logical-border, rgba(59, 130, 246, 0.4))",
    },
    GUEST: {
      bg: "var(--qb-color-none-bg, rgba(148, 163, 184, 0.14))",
      fg: "var(--qb-color-text-secondary, #475569)",
      border: "var(--qb-color-none-border, rgba(148, 163, 184, 0.35))",
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

// 3. Curated Query Presets per Home Server Database
interface DatabaseInfo {
  id: string;
  name: string;
  group: string;
  dialect: "postgres" | "sqlite";
  schema_name: string;
  description: string;
  icon: string;
  default_table: string;
  available: boolean;
  table_count: number | null;
  foreign_key_count: number | null;
}

const DATABASE_PRESETS: Record<string, SqlPreset[]> = {
  federated_hub: [
    {
      id: "fed_jellyseerr_radarr_join",
      title: "Jellyseerr Movie Requests × Radarr Catalog",
      category: "Cross-DB Join",
      description: "Joins Jellyseerr media requests (jellyseerr.db) with Radarr MovieMetadata (radarr.db) on TMDB ID.",
      spec: {
        table: "jellyseerr__media",
        columns: [
          "jellyseerr__media.id",
          "jellyseerr__media.tmdbId",
          "jellyseerr__media.status",
          "radarr__MovieMetadata.Title",
          "radarr__MovieMetadata.Year",
          "radarr__MovieMetadata.Studio",
          "radarr__MovieMetadata.Runtime",
        ],
        joins: [
          {
            table: "radarr__MovieMetadata",
            type: "INNER JOIN",
            left_table: "jellyseerr__media",
            left_col: "tmdbId",
            right_col: "TmdbId",
          },
        ],
        limit: 25,
      },
    },
    {
      id: "fed_jellyseerr_sonarr_join",
      title: "Jellyseerr TV Requests × Sonarr Series",
      category: "Cross-DB Join",
      description: "Joins Jellyseerr TV requests (jellyseerr.db) with Sonarr Series (sonarr.db) on TVDB ID.",
      spec: {
        table: "jellyseerr__media",
        columns: [
          "jellyseerr__media.id",
          "jellyseerr__media.tvdbId",
          "jellyseerr__media.status",
          "sonarr__Series.Title",
          "sonarr__Series.Network",
          "sonarr__Series.Year",
          "sonarr__Series.Status",
        ],
        joins: [
          {
            table: "sonarr__Series",
            type: "INNER JOIN",
            left_table: "jellyseerr__media",
            left_col: "tvdbId",
            right_col: "TvdbId",
          },
        ],
        limit: 25,
      },
    },
    {
      id: "fed_radarr_plex_join",
      title: "Radarr Movies × Plex Library Items",
      category: "Cross-DB Join",
      description: "Cross-database join comparing Radarr movies (radarr.db) with Plex metadata_items (com.plexapp.plugins.library.db).",
      spec: {
        table: "radarr__MovieMetadata",
        columns: [
          "radarr__MovieMetadata.Title",
          "radarr__MovieMetadata.Year",
          "radarr__MovieMetadata.Studio",
          "plex_library__metadata_items.rating",
          "plex_library__metadata_items.duration",
        ],
        joins: [
          {
            table: "plex_library__metadata_items",
            type: "INNER JOIN",
            left_table: "radarr__MovieMetadata",
            left_col: "Title",
            right_col: "title",
          },
        ],
        limit: 25,
      },
    },
    {
      id: "fed_sonarr_plex_join",
      title: "Sonarr TV Series × Plex Library Items",
      category: "Cross-DB Join",
      description: "Cross-database join comparing Sonarr TV series (sonarr.db) with Plex metadata_items.",
      spec: {
        table: "sonarr__Series",
        columns: [
          "sonarr__Series.Title",
          "sonarr__Series.Network",
          "sonarr__Series.Year",
          "plex_library__metadata_items.rating",
          "plex_library__metadata_items.media_item_count",
        ],
        joins: [
          {
            table: "plex_library__metadata_items",
            type: "INNER JOIN",
            left_table: "sonarr__Series",
            left_col: "Title",
            right_col: "title",
          },
        ],
        limit: 25,
      },
    },
  ],
  firm_production: [
    {
      id: "top_firms_by_aum",
      title: "Top Advisory Firms by Total AUM",
      category: "Wealth Intelligence",
      description: "Largest registered investment advisers ranked by total assets under management (total_aum).",
      spec: {
        table: "firm_master",
        columns: [
          "firm_master.crd_number",
          "firm_master.legal_name",
          "firm_master.dba_name",
          "firm_master.main_office_city",
          "firm_master.main_office_state",
          "firm_master.total_aum",
          "firm_master.advisory_employees",
        ],
        filters: [
          {
            tablePrefix: "firm_master",
            column: "total_aum",
            op: ">",
            value: 0,
          },
        ],
        order_by: [
          {
            tablePrefix: "firm_master",
            column: "total_aum",
            direction: "DESC",
          },
        ],
        limit: 25,
      },
    },
    {
      id: "firms_by_state",
      title: "Firm Count & Total AUM by State",
      category: "Geographic",
      description: "Aggregate count of registered firms and combined AUM grouped by headquarters state.",
      spec: {
        table: "firm_master",
        columns: [
          "firm_master.main_office_state",
          { column: "firm_master.crd_number", agg: "COUNT", alias: "firm_count" },
          { column: "firm_master.total_aum", agg: "SUM", alias: "combined_aum" },
        ],
        order_by: [
          {
            tablePrefix: "firm_master",
            column: "main_office_state",
            direction: "ASC",
          },
        ],
        limit: 50,
      },
    },
  ],
  hobbyhabbit: [
    {
      id: "hh_security_logs",
      title: "Recent Security Audit Events",
      category: "Security",
      description: "Recent authentication and security log entries from HobbyHabbit.",
      spec: {
        table: "engine_securitylog",
        columns: [],
        limit: 25,
      },
    },
    {
      id: "hh_user_profiles",
      title: "User Profiles Overview",
      category: "Users",
      description: "Registered HobbyHabbit user profiles and progression settings.",
      spec: {
        table: "engine_userprofile",
        columns: [],
        limit: 25,
      },
    },
    {
      id: "hh_hobbies",
      title: "Hobbies Catalog",
      category: "Core",
      description: "Browse hobbies table structure and entries.",
      spec: {
        table: "hobbies",
        columns: [],
        limit: 25,
      },
    },
  ],
  synfinii_lab: [
    {
      id: "synfinii_top_sales",
      title: "Top Distribution Sales by Amount",
      category: "Distribution",
      description: "Fund distribution transactions sorted by sale amount descending.",
      spec: {
        table: "distribution_sales",
        columns: [
          "distribution_sales.transaction_id",
          "distribution_sales.fund_name",
          "distribution_sales.distributor",
          "distribution_sales.region",
          "distribution_sales.amount",
          "distribution_sales.sale_date",
        ],
        order_by: [
          {
            tablePrefix: "distribution_sales",
            column: "amount",
            direction: "DESC",
          },
        ],
        limit: 25,
      },
    },
    {
      id: "synfinii_by_region",
      title: "Sales Volume by Region",
      category: "Analytics",
      description: "Aggregate transaction count and total sales volume by region.",
      spec: {
        table: "distribution_sales",
        columns: [
          "distribution_sales.region",
          { column: "distribution_sales.transaction_id", agg: "COUNT", alias: "tx_count" },
          { column: "distribution_sales.amount", agg: "SUM", alias: "total_volume" },
        ],
        limit: 25,
      },
    },
  ],
  plex_library: [
    {
      id: "plex_metadata_items",
      title: "Plex Media Catalog (metadata_items)",
      category: "Media",
      description: "Movies, shows, seasons, and episodes indexed in Plex Media Server.",
      spec: {
        table: "metadata_items",
        columns: [
          "metadata_items.id",
          "metadata_items.title",
          "metadata_items.year",
          "metadata_items.rating",
          "metadata_items.duration",
          "metadata_items.added_at",
        ],
        order_by: [
          {
            tablePrefix: "metadata_items",
            column: "added_at",
            direction: "DESC",
          },
        ],
        limit: 25,
      },
    },
    {
      id: "plex_largest_files",
      title: "Largest Media Items by File Size",
      category: "Storage",
      description: "Video and audio streams ranked by byte size and bitrate.",
      spec: {
        table: "media_items",
        columns: [
          "media_items.id",
          "media_items.metadata_item_id",
          "media_items.width",
          "media_items.height",
          "media_items.bitrate",
          "media_items.size",
          "media_items.container",
        ],
        order_by: [
          {
            tablePrefix: "media_items",
            column: "size",
            direction: "DESC",
          },
        ],
        limit: 25,
      },
    },
  ],
  sonarr: [
    {
      id: "sonarr_series",
      title: "TV Series Library",
      category: "TV Shows",
      description: "Monitored TV series tracked in Sonarr.",
      spec: {
        table: "Series",
        columns: [
          "Series.Id",
          "Series.Title",
          "Series.Year",
          "Series.Network",
          "Series.Status",
          "Series.Runtime",
          "Series.Monitored",
        ],
        order_by: [
          {
            tablePrefix: "Series",
            column: "Title",
            direction: "ASC",
          },
        ],
        limit: 25,
      },
    },
    {
      id: "sonarr_episodes",
      title: "Episodes Catalog",
      category: "TV Shows",
      description: "All TV episodes with season/episode numbers and air dates.",
      spec: {
        table: "Episodes",
        columns: [
          "Episodes.Id",
          "Episodes.SeriesId",
          "Episodes.SeasonNumber",
          "Episodes.EpisodeNumber",
          "Episodes.Title",
          "Episodes.AirDateUtc",
          "Episodes.Monitored",
        ],
        order_by: [
          {
            tablePrefix: "Episodes",
            column: "AirDateUtc",
            direction: "DESC",
          },
        ],
        limit: 25,
      },
    },
  ],
  radarr: [
    {
      id: "radarr_movie_metadata",
      title: "Movie Metadata & Release Years",
      category: "Movies",
      description: "Movies cataloged in Radarr with studio, runtime, and release year.",
      spec: {
        table: "MovieMetadata",
        columns: [
          "MovieMetadata.Id",
          "MovieMetadata.Title",
          "MovieMetadata.Year",
          "MovieMetadata.Runtime",
          "MovieMetadata.Studio",
          "MovieMetadata.Status",
        ],
        order_by: [
          {
            tablePrefix: "MovieMetadata",
            column: "Year",
            direction: "DESC",
          },
        ],
        limit: 25,
      },
    },
    {
      id: "radarr_movies",
      title: "Monitored Movies & Paths",
      category: "Storage",
      description: "Radarr movie records and filesystem paths.",
      spec: {
        table: "Movies",
        columns: [
          "Movies.Id",
          "Movies.MovieMetadataId",
          "Movies.Path",
          "Movies.Monitored",
          "Movies.Added",
        ],
        order_by: [
          {
            tablePrefix: "Movies",
            column: "Added",
            direction: "DESC",
          },
        ],
        limit: 25,
      },
    },
  ],
};

// 3b. Curated E-Commerce Query Presets (Starter Demo)
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

const KNOWN_DB_DEFAULTS: Record<string, { dialect: "postgres" | "sqlite"; default_table: string }> = {
  federated_hub: { dialect: "sqlite", default_table: "jellyseerr__media" },
  hobbyhabbit: { dialect: "postgres", default_table: "hobbies" },
  firm_production: { dialect: "postgres", default_table: "firm_master" },
  firm_staging: { dialect: "postgres", default_table: "sec_raw_firms" },
  firm_history: { dialect: "postgres", default_table: "advisory_team_history" },
  firm_public: { dialect: "postgres", default_table: "dag" },
  synfinii_lab: { dialect: "postgres", default_table: "distribution_sales" },
  plex_library: { dialect: "sqlite", default_table: "metadata_items" },
  sonarr: { dialect: "sqlite", default_table: "Series" },
  radarr: { dialect: "sqlite", default_table: "Movies" },
  prowlarr: { dialect: "sqlite", default_table: "Indexers" },
  jellyseerr: { dialect: "sqlite", default_table: "media" },
  npm: { dialect: "sqlite", default_table: "proxy_host" },
  plex_blobs: { dialect: "sqlite", default_table: "blobs" },
  sonarr_logs: { dialect: "sqlite", default_table: "Logs" },
  radarr_logs: { dialect: "sqlite", default_table: "Logs" },
  prowlarr_logs: { dialect: "sqlite", default_table: "Logs" },
  starter_demo: { dialect: "sqlite", default_table: "products" },
};

const CURATED_CROSS_DB_LINKS: [string, string, string, string][] = [
  ["jellyseerr__media", "tmdbId", "radarr__MovieMetadata", "TmdbId"],
  ["jellyseerr__media", "imdbId", "radarr__MovieMetadata", "ImdbId"],
  ["jellyseerr__media", "tvdbId", "sonarr__Series", "TvdbId"],
  ["jellyseerr__media", "imdbId", "sonarr__Series", "ImdbId"],
  ["radarr__MovieMetadata", "Title", "plex_library__metadata_items", "title"],
  ["sonarr__Series", "Title", "plex_library__metadata_items", "title"],
  ["firm_staging__sec_raw_firms", "raw_crd_number", "firm_production__firm_master", "crd_number"],
  ["firm_staging__firm_master_history", "firm_master_id", "firm_production__firm_master", "firm_master_id"],
  ["firm_history__advisory_team_history", "firm_id", "firm_production__firm_master", "firm_master_id"],
];

export function App() {
  const builderRef = useRef<VisualQueryBuilderRef | null>(null);
  const topAiInputRef = useRef<HTMLInputElement | null>(null);
  const aiReplyInputRef = useRef<HTMLInputElement | null>(null);
  const pendingSpecRef = useRef<QuerySpec | null>(null);
  const schemaFetchSeqRef = useRef<number>(0);

  const [activeTab, setActiveTab] = useState<"visual" | "headless" | "adapters" | "dashboard">("visual");
  const [schema, setSchema] = useState<SchemaSnapshot>(FALLBACK_SCHEMA);
  const [loadedSchemaDbId, setLoadedSchemaDbId] = useState<string | null>(null);
  const [schemaLoadCount, setSchemaLoadCount] = useState<number>(0);
  const [serverStatus, setServerStatus] = useState<string>("checking...");
  const [geminiConfigured, setGeminiConfigured] = useState<boolean>(true);
  const [selectedPreset, setSelectedPreset] = useState<SqlPreset | null>(null);
  const [isPresetsMenuOpen, setIsPresetsMenuOpen] = useState<boolean>(false);

  // Right-Docked Multi-Shot AI Assistant Drawer state
  const [isAiAssistantOpen, setIsAiAssistantOpen] = useState<boolean>(false);
  const [paletteQuery, setPaletteQuery] = useState("");
  const [isPaletteTranslating, setIsPaletteTranslating] = useState(false);
  const [paletteError, setPaletteError] = useState<string | null>(null);
  const [paletteTurns, setPaletteTurns] = useState<
    { prompt: string; spec: QuerySpec; explanation: string; steps?: string[]; followUps: string[] }[]
  >([]);

  // Left Explorer Sidebar & Cross-DB Pinning state
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(true);
  const [isDbSwitcherExpanded, setIsDbSwitcherExpanded] = useState<boolean>(false);
  const [isCrossDbExpanded, setIsCrossDbExpanded] = useState<boolean>(false);
  const [pinnedCrossDbId, setPinnedCrossDbId] = useState<string>("radarr");
  const [pinnedCrossDbSchema, setPinnedCrossDbSchema] = useState<SchemaSnapshot | null>(null);
  const [isLoadingPinnedSchema, setIsLoadingPinnedSchema] = useState<boolean>(false);
  const [pinnedTableSearch, setPinnedTableSearch] = useState<string>("");

  const [showDevTabs, setShowDevTabs] = useState<boolean>(false);
  const [showSystemTables, setShowSystemTables] = useState<boolean>(false);
  const [dbFilterGroup, setDbFilterGroup] = useState<string>("ALL");
  const [tableSearch, setTableSearch] = useState<string>("");
  const [fedSourceFilter, setFedSourceFilter] = useState<string>("ALL");
  const [databases, setDatabases] = useState<DatabaseInfo[]>([]);
  const [activeDbId, setActiveDbId] = useState<string>(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const fromUrl = params.get("db");
      if (fromUrl) return fromUrl;
      const stored = localStorage.getItem("qb-active-database");
      if (stored) return stored;
    }
    return "hobbyhabbit";
  });
  const [isLoadingSchema, setIsLoadingSchema] = useState<boolean>(false);

  // Default to crisp dark studio theme when no preference is stored
  const [themePreference, setThemePreference] = useState<"system" | "dark" | "light">(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("qb-theme-preference");
      if (stored === "dark" || stored === "light" || stored === "system") {
        return stored;
      }
    }
    return "dark";
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
      const next = prev === "dark" ? "light" : prev === "light" ? "system" : "dark";
      localStorage.setItem("qb-theme-preference", next);
      return next;
    });
  };

  // Keyboard shortcut listener for Cmd+K / Ctrl+K -> focuses Top Bar AI Input & opens AI Assistant Drawer
  useEffect(() => {
    const handleGlobalKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setIsAiAssistantOpen(true);
        setTimeout(() => {
          topAiInputRef.current?.focus();
          topAiInputRef.current?.select();
        }, 20);
      } else if (e.key === "Escape") {
        setIsPresetsMenuOpen(false);
      }
    };
    window.addEventListener("keydown", handleGlobalKey);
    return () => window.removeEventListener("keydown", handleGlobalKey);
  }, []);

  // Load health and registered databases from FastAPI backend in parallel
  useEffect(() => {
    async function loadInitialCatalog() {
      const [healthResult, dbResult] = await Promise.allSettled([
        fetch("/health"),
        fetch("/api/databases"),
      ]);

      if (healthResult.status === "fulfilled" && healthResult.value.ok) {
        try {
          const healthData = await healthResult.value.json();
          setServerStatus(
            `Connected (${healthData.registered_databases || 18} Home Server DBs)`,
          );
          if (typeof healthData.gemini_configured === "boolean") {
            setGeminiConfigured(healthData.gemini_configured);
          }
        } catch {
          setServerStatus("Backend Offline (using mock schema)");
        }
      } else {
        setServerStatus("Backend Offline (using mock schema)");
      }

      if (dbResult.status === "fulfilled" && dbResult.value.ok) {
        try {
          const dbData = await dbResult.value.json();
          const list: DatabaseInfo[] = dbData.databases || [];
          setDatabases(list);
          if (list.length > 0 && !list.some((d) => d.id === activeDbId)) {
            const fallbackId = dbData.default_database || list[0].id;
            setActiveDbId(fallbackId);
          }
        } catch {
          // Ignore if offline
        }
      }
    }
    void loadInitialCatalog();
  }, []);

  // Load live schema whenever activeDbId changes, guarding against out-of-order responses
  const fetchSchemaForDb = async (dbId: string, forceRefresh = false) => {
    const reqSeq = ++schemaFetchSeqRef.current;
    setIsLoadingSchema(true);
    try {
      const url = `/api/schema?db=${encodeURIComponent(dbId)}${
        forceRefresh ? "&refresh=true" : ""
      }`;
      const schemaRes = await fetch(url, {
        headers: { "X-QB-Database": dbId },
      });
      if (reqSeq !== schemaFetchSeqRef.current) return;
      if (schemaRes.ok) {
        const schemaData: SchemaSnapshot = await schemaRes.json();
        if (reqSeq !== schemaFetchSeqRef.current) return;
        setSchema(schemaData);
        setLoadedSchemaDbId(dbId);
        if (!forceRefresh) {
          setSchemaLoadCount((c) => c + 1);
        }
      }
    } catch {
      // Fallback remains active
    } finally {
      if (reqSeq === schemaFetchSeqRef.current) {
        setIsLoadingSchema(false);
      }
    }
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.setItem("qb-active-database", activeDbId);
    }
    setSelectedPreset(null);
    setTableSearch("");
    setFedSourceFilter("ALL");
    void fetchSchemaForDb(activeDbId, false);
  }, [activeDbId]);

  // Keep pinnedCrossDbId distinct from activeDbId and federated_hub
  useEffect(() => {
    if (pinnedCrossDbId !== activeDbId && pinnedCrossDbId !== "federated_hub") return;
    const candidates = databases
      .filter((d) => d.id !== "federated_hub" && d.id !== activeDbId && d.available)
      .map((d) => d.id);
    const fallbackCandidate =
      candidates[0] ||
      (activeDbId === "radarr" ? "jellyseerr" : "radarr");
    setPinnedCrossDbId(fallbackCandidate);
  }, [activeDbId, pinnedCrossDbId, databases]);

  // Fetch schema for pinned secondary database when Cross-DB Join section is expanded
  useEffect(() => {
    if (!isCrossDbExpanded || !pinnedCrossDbId) return;
    let cancelled = false;
    async function loadPinnedSchema() {
      setIsLoadingPinnedSchema(true);
      try {
        const res = await fetch(`/api/schema?db=${encodeURIComponent(pinnedCrossDbId)}`, {
          headers: { "X-QB-Database": pinnedCrossDbId },
        });
        if (res.ok && !cancelled) {
          const data: SchemaSnapshot = await res.json();
          setPinnedCrossDbSchema(data);
        }
      } catch {
        // Ignore
      } finally {
        if (!cancelled) setIsLoadingPinnedSchema(false);
      }
    }
    void loadPinnedSchema();
    return () => {
      cancelled = true;
    };
  }, [isCrossDbExpanded, pinnedCrossDbId]);

  const activeDbInfo = useMemo(
    () => databases.find((d) => d.id === activeDbId),
    [databases, activeDbId],
  );

  const activeDialect: "postgres" | "sqlite" =
    activeDbInfo?.dialect || KNOWN_DB_DEFAULTS[activeDbId]?.dialect || "sqlite";

  const schemaStats = useMemo(() => {
    const tableCount = Object.keys(schema.tables || {}).length;
    const fkCount = (schema.foreign_keys || []).length;
    return { tableCount, fkCount };
  }, [schema]);

  const resolvedInitialTable = useMemo(() => {
    const tablesMap = schema.tables || {};
    const tableKeys = Object.keys(tablesMap);
    if (selectedPreset?.spec?.table && tablesMap[selectedPreset.spec.table]) {
      return selectedPreset.spec.table;
    }
    const candidateDefault =
      activeDbInfo?.default_table || KNOWN_DB_DEFAULTS[activeDbId]?.default_table;
    if (candidateDefault && tablesMap[candidateDefault]) {
      return candidateDefault;
    }
    return tableKeys[0] || "products";
  }, [schema, selectedPreset, activeDbInfo, activeDbId]);

  const [sidebarPrimaryTable, setSidebarPrimaryTable] = useState<string>("");
  const effectiveSidebarPrimaryTable = sidebarPrimaryTable || resolvedInitialTable;

  useEffect(() => {
    setSidebarPrimaryTable(resolvedInitialTable);
  }, [resolvedInitialTable]);

  const applyAndExecuteSpec = (spec: QuerySpec) => {
    setActiveTab("visual");
    if (spec.table) {
      setSidebarPrimaryTable(spec.table);
    }
    if (builderRef.current) {
      builderRef.current.setSpec(spec);
      void builderRef.current.execute(spec);
    } else {
      pendingSpecRef.current = spec;
    }
  };

  // Flush any pending spec when switching from BI/Headless/ORM tabs back to Visual
  useEffect(() => {
    if (activeTab !== "visual" || !pendingSpecRef.current || loadedSchemaDbId !== activeDbId) {
      return;
    }
    const timer = setTimeout(() => {
      if (builderRef.current && pendingSpecRef.current) {
        const specToApply = pendingSpecRef.current;
        pendingSpecRef.current = null;
        builderRef.current.setSpec(specToApply);
        void builderRef.current.execute(specToApply);
      }
    }, 20);
    return () => clearTimeout(timer);
  }, [activeTab, loadedSchemaDbId, activeDbId]);

  // Auto-run preview query (or pending Cross-DB spec) whenever a database's schema finishes loading
  useEffect(() => {
    if (loadedSchemaDbId !== activeDbId || schemaLoadCount === 0) return;
    const timer = setTimeout(() => {
      if (!builderRef.current) return;
      if (pendingSpecRef.current) {
        const specToApply = pendingSpecRef.current;
        pendingSpecRef.current = null;
        builderRef.current.setSpec(specToApply);
        void builderRef.current.execute(specToApply);
        return;
      }
      const candidateDefault =
        activeDbInfo?.default_table || KNOWN_DB_DEFAULTS[activeDbId]?.default_table;
      const defaultTbl =
        candidateDefault && schema.tables?.[candidateDefault]
          ? candidateDefault
          : Object.keys(schema.tables || {})[0];
      if (defaultTbl) {
        const previewSpec: QuerySpec = {
          table: defaultTbl,
          columns: [],
          joins: [],
          filters: [],
          filter_join: "AND",
          order_by: [],
          distinct: false,
          limit: 25,
        };
        builderRef.current.setSpec(previewSpec);
        void builderRef.current.execute(previewSpec);
      }
    }, 30);
    return () => clearTimeout(timer);
  }, [loadedSchemaDbId, activeDbId, schemaLoadCount]);

  const activePresets: SqlPreset[] = useMemo(() => {
    if (activeDbId === "starter_demo") return STARTER_PRESETS;
    if (DATABASE_PRESETS[activeDbId]) return DATABASE_PRESETS[activeDbId];
    const defaultTbl =
      activeDbInfo?.default_table ||
      KNOWN_DB_DEFAULTS[activeDbId]?.default_table ||
      Object.keys(schema.tables || {})[0] ||
      "users";
    const cols = schema.tables?.[defaultTbl]?.columns || [];
    const firstCol = cols[0]?.name;
    const presets: SqlPreset[] = [
      {
        id: `${activeDbId}_preview`,
        title: `Preview ${defaultTbl} (First 25 Rows)`,
        category: "Explore",
        description: `Inspect sample records from ${defaultTbl} in ${activeDbInfo?.name || activeDbId}.`,
        spec: {
          table: defaultTbl,
          columns: [],
          limit: 25,
        },
      },
    ];
    if (firstCol) {
      presets.push({
        id: `${activeDbId}_count`,
        title: `Total Record Count (${defaultTbl})`,
        category: "Metrics",
        description: `Count total rows in ${defaultTbl}.`,
        spec: {
          table: defaultTbl,
          columns: [
            {
              column: `${defaultTbl}.${firstCol}`,
              agg: "COUNT",
              alias: "total_records",
            },
          ],
          limit: 10,
        },
      });
    }
    return presets;
  }, [activeDbId, activeDbInfo, schema]);

  // Execution handler talking to backend /api/execute for the active database
  const handleExecuteQuery = async (
    sql: string,
    spec?: QuerySpec | SerializedQuerySpec | Record<string, unknown> | null,
  ): Promise<QueryResultData> => {
    const res = await fetch(`/api/execute?db=${encodeURIComponent(activeDbId)}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-QB-Database": activeDbId,
      },
      body: JSON.stringify({ db: activeDbId, spec: spec ?? undefined, sql }),
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
    setIsPresetsMenuOpen(false);
    if (preset.spec) {
      applyAndExecuteSpec(preset.spec as QuerySpec);
    } else {
      setActiveTab("visual");
    }
  };

  const handleSidebarSetPrimary = (tblName: string) => {
    setSelectedPreset(null);
    applyAndExecuteSpec({
      table: tblName,
      columns: [],
      joins: [],
      filters: [],
      filter_join: "AND",
      order_by: [],
      distinct: false,
      limit: 25,
    });
  };

  const handleSidebarJoinTable = (tblName: string) => {
    const cur = builderRef.current?.getSpec() ?? pendingSpecRef.current;
    const baseTbl = cur?.table || resolvedInitialTable;
    if (!baseTbl || baseTbl === tblName) {
      handleSidebarSetPrimary(tblName);
      return;
    }
    const existingJoins = Array.isArray(cur?.joins) ? cur.joins : [];
    if (existingJoins.some((j) => j.table === tblName)) {
      setActiveTab("visual");
      return;
    }
    const cond = findBestJoinCondition(baseTbl, tblName, schema);
    const nextSpec: QuerySpec = {
      ...(cur || {}),
      table: baseTbl,
      columns: cur?.columns || [],
      filters: cur?.filters || [],
      filter_join: cur?.filter_join || "AND",
      order_by: cur?.order_by || [],
      distinct: Boolean(cur?.distinct),
      limit: cur?.limit ?? 25,
      joins: [
        ...existingJoins,
        {
          table: cond.rightTable,
          type: "LEFT JOIN",
          left_table: cond.leftTable,
          left_col: cond.leftCol,
          right_col: cond.rightCol,
        },
      ],
    };
    applyAndExecuteSpec(nextSpec);
  };

  const handleSidebarPreviewTable = (tblName: string) => {
    handleSidebarSetPrimary(tblName);
  };

  // Cross-DB Pinning Join Handler: transparently joins a table from another database via federated_hub
  const handleCrossDbJoinTable = (targetDbId: string, targetTableName: string) => {
    const cur = builderRef.current?.getSpec() ?? pendingSpecRef.current;
    const rawBaseTbl = cur?.table || resolvedInitialTable;
    const fedBaseTbl =
      activeDbId === "federated_hub"
        ? rawBaseTbl
        : `${activeDbId}__${rawBaseTbl}`;
    const fedTargetTbl = `${targetDbId}__${targetTableName}`;

    // Infer best join column between base table and target table
    const baseCols = (schema.tables?.[rawBaseTbl]?.columns || []).map((c) => c.name);
    const targetCols = (pinnedCrossDbSchema?.tables?.[targetTableName]?.columns || []).map(
      (c) => c.name,
    );
    const targetLowerMap = new Map(targetCols.map((c) => [c.toLowerCase(), c]));

    let leftCol = baseCols[0] || "id";
    let rightCol = targetCols[0] || "id";
    let matchedCurated = false;

    for (const [srcT, srcC, dstT, dstC] of CURATED_CROSS_DB_LINKS) {
      if (srcT === fedBaseTbl && dstT === fedTargetTbl) {
        leftCol = srcC;
        rightCol = dstC;
        matchedCurated = true;
        break;
      }
      if (dstT === fedBaseTbl && srcT === fedTargetTbl) {
        leftCol = dstC;
        rightCol = srcC;
        matchedCurated = true;
        break;
      }
    }

    if (!matchedCurated) {
      const candidateShareCols = [
        "tmdbid",
        "tvdbid",
        "imdbid",
        "title",
        "user_id",
        "email",
        "crd_number",
        "firm_master_id",
        "id",
      ];
      for (const cand of candidateShareCols) {
        const bMatch = baseCols.find((c) => c.toLowerCase() === cand);
        const tMatch = targetLowerMap.get(cand);
        if (bMatch && tMatch) {
          leftCol = bMatch;
          rightCol = tMatch;
          matchedCurated = true;
          break;
        }
      }
    }

    if (!matchedCurated) {
      // Check known cross-schema column aliases (e.g., raw_crd_number <-> crd_number, firm_id <-> firm_master_id)
      const aliasPairs: [string, string][] = [
        ["raw_crd_number", "crd_number"],
        ["firm_id", "firm_master_id"],
      ];
      for (const [colA, colB] of aliasPairs) {
        if (baseCols.includes(colA) && targetCols.includes(colB)) {
          leftCol = colA;
          rightCol = colB;
          break;
        }
        if (baseCols.includes(colB) && targetCols.includes(colA)) {
          leftCol = colB;
          rightCol = colA;
          break;
        }
      }
    }

    const existingFedJoins =
      activeDbId === "federated_hub" && cur?.table === fedBaseTbl && Array.isArray(cur?.joins)
        ? cur.joins.filter((j) => j.table !== fedTargetTbl)
        : [];

    const crossSpec: QuerySpec = {
      table: fedBaseTbl,
      columns: activeDbId === "federated_hub" && cur?.table === fedBaseTbl ? cur.columns || [] : [],
      joins: [
        ...existingFedJoins,
        {
          table: fedTargetTbl,
          type: "INNER JOIN",
          left_table: fedBaseTbl,
          left_col: leftCol,
          right_col: rightCol,
        },
      ],
      filters: activeDbId === "federated_hub" && cur?.table === fedBaseTbl ? cur.filters || [] : [],
      filter_join:
        activeDbId === "federated_hub" && cur?.table === fedBaseTbl ? cur.filter_join || "AND" : "AND",
      order_by:
        activeDbId === "federated_hub" && cur?.table === fedBaseTbl ? cur.order_by || [] : [],
      distinct:
        activeDbId === "federated_hub" && cur?.table === fedBaseTbl ? Boolean(cur.distinct) : false,
      limit: activeDbId === "federated_hub" && cur?.table === fedBaseTbl ? cur.limit ?? 25 : 25,
    };

    if (activeDbId === "federated_hub") {
      applyAndExecuteSpec(crossSpec);
    } else {
      setActiveTab("visual");
      pendingSpecRef.current = crossSpec;
      setActiveDbId("federated_hub");
    }
  };

  // Multi-Shot AI Assistant translation handler
  const handlePaletteTranslate = async (promptText?: string) => {
    const q = (promptText ?? paletteQuery).trim();
    if (!q) return;
    setIsAiAssistantOpen(true);
    setIsPaletteTranslating(true);
    setPaletteError(null);
    try {
      const latestTurnSpec =
        paletteTurns.length > 0 ? paletteTurns[paletteTurns.length - 1].spec : undefined;
      const canvasSpec = builderRef.current?.getSpec();
      const activeSpec = latestTurnSpec || (canvasSpec?.table ? canvasSpec : undefined);

      const resp = await fetch(`/api/nlq/translate?db=${encodeURIComponent(activeDbId)}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-QB-Database": activeDbId,
        },
        body: JSON.stringify({
          prompt: q,
          provider: geminiConfigured ? "gemini" : "mock",
          dialect: activeDialect,
          current_spec: activeSpec,
          history: paletteTurns.map((t) => ({
            prompt: t.prompt,
            spec: t.spec,
            explanation: t.explanation,
          })),
        }),
      });
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        throw new Error(errBody?.detail || errBody?.error?.message || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      if (data?.spec?.table) {
        const rawSpec = data.spec as QuerySpec;
        const cleanedCols = Array.isArray(rawSpec.columns)
          ? rawSpec.columns.filter((c) => {
              if (typeof c === "string") {
                const trimmed = c.trim();
                return trimmed !== "*" && !trimmed.endsWith(".*");
              }
              return true;
            })
          : [];
        const cleanedFilters = Array.isArray(rawSpec.filters)
          ? rawSpec.filters.map((f) => {
              if (f && typeof f.column === "string" && !f.tablePrefix && f.column.includes(".")) {
                const lastDot = f.column.lastIndexOf(".");
                return {
                  ...f,
                  tablePrefix: f.column.substring(0, lastDot),
                  column: f.column.substring(lastDot + 1),
                };
              }
              return f;
            })
          : rawSpec.filters;
        const normalizedSpec: QuerySpec = {
          ...rawSpec,
          columns: cleanedCols,
          ...(cleanedFilters ? { filters: cleanedFilters } : {}),
        };
        setSelectedPreset(null);
        setPaletteQuery("");
        setPaletteTurns((prev) => [
          ...prev,
          {
            prompt: q,
            spec: normalizedSpec,
            explanation: data.explanation || `Updated query on ${normalizedSpec.table}`,
            steps: Array.isArray(data.steps) ? data.steps : [],
            followUps: Array.isArray(data.follow_ups) ? data.follow_ups : [],
          },
        ]);
        applyAndExecuteSpec(normalizedSpec);
      }
    } catch (err) {
      setPaletteError(err instanceof Error ? err.message : "Failed to translate prompt");
    } finally {
      setIsPaletteTranslating(false);
    }
  };

  const handleRevertToTurn = (turnIdx: number) => {
    const targetTurn = paletteTurns[turnIdx];
    if (!targetTurn) return;
    setPaletteTurns((prev) => prev.slice(0, turnIdx + 1));
    applyAndExecuteSpec(targetTurn.spec);
  };

  const filteredDatabases = useMemo(() => {
    if (dbFilterGroup === "ALL") return databases;
    if (dbFilterGroup === "FEDERATED") return databases.filter((d) => d.id === "federated_hub");
    if (dbFilterGroup === "POSTGRES") return databases.filter((d) => d.dialect === "postgres");
    if (dbFilterGroup === "SQLITE")
      return databases.filter((d) => d.dialect === "sqlite" && d.id !== "federated_hub");
    return databases;
  }, [databases, dbFilterGroup]);

  const federatedPrefixes = useMemo(() => {
    if (activeDbId !== "federated_hub") return [];
    const prefixes = new Set<string>();
    for (const tName of Object.keys(schema.tables || {})) {
      const idx = tName.indexOf("__");
      if (idx > 0) prefixes.add(tName.slice(0, idx));
    }
    return Array.from(prefixes).sort();
  }, [activeDbId, schema.tables]);

  const isSystemPlumbingTable = (tableName: string): boolean => {
    const raw = tableName.includes("__") ? tableName.split("__").slice(1).join("__") : tableName;
    return /^(auth_|axes_|django_|account_|socialaccount_|token_blacklist_|authtoken_|celery_|sqlite_|pg_|information_schema)/i.test(
      raw,
    );
  };

  const filteredTablesList = useMemo(() => {
    const entries = Object.values(schema.tables || {}).filter((t) => {
      if (activeDbId === "federated_hub" && fedSourceFilter !== "ALL") {
        if (!t.name.startsWith(`${fedSourceFilter}__`)) return false;
      }
      if (tableSearch.trim()) {
        const q = tableSearch.trim().toLowerCase();
        const nameMatch = t.name.toLowerCase().includes(q);
        const colMatch = (t.columns || []).some((c) => c.name.toLowerCase().includes(q));
        return nameMatch || colMatch;
      }
      return true;
    });

    const rankTable = (tName: string): number => {
      if (tName === effectiveSidebarPrimaryTable) return 0;
      const cond = findBestJoinCondition(effectiveSidebarPrimaryTable, tName, schema);
      const tier = cond?.joinTier || (cond?.isFk ? "confirmed" : "none");
      if (tier === "confirmed") return 1;
      if (tier === "logical") return 2;
      return 3;
    };

    return [...entries].sort((a, b) => {
      const rDiff = rankTable(a.name) - rankTable(b.name);
      if (rDiff !== 0) return rDiff;
      return a.name.localeCompare(b.name);
    });
  }, [schema, activeDbId, fedSourceFilter, tableSearch, effectiveSidebarPrimaryTable]);

  const { coreTablesList, systemTablesList } = useMemo(() => {
    const core: typeof filteredTablesList = [];
    const sys: typeof filteredTablesList = [];
    for (const t of filteredTablesList) {
      if (t.name !== effectiveSidebarPrimaryTable && isSystemPlumbingTable(t.name)) {
        sys.push(t);
      } else {
        core.push(t);
      }
    }
    return {
      coreTablesList: core.length > 0 ? core : filteredTablesList,
      systemTablesList: core.length > 0 ? sys : [],
    };
  }, [filteredTablesList, effectiveSidebarPrimaryTable]);

  const pinnedTablesList = useMemo(() => {
    const entries = Object.values(pinnedCrossDbSchema?.tables || {});
    if (!pinnedTableSearch.trim()) return entries;
    const q = pinnedTableSearch.trim().toLowerCase();
    return entries.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.columns || []).some((c) => c.name.toLowerCase().includes(q)),
    );
  }, [pinnedCrossDbSchema, pinnedTableSearch]);

  const aiStarterPrompts = useMemo(() => {
    const tbl = resolvedInitialTable;
    const cols = schema.tables?.[tbl]?.columns || [];
    const sortCol =
      cols.find((c) => /aum|amount|total|score|count|date|created|year|id/i.test(c.name))?.name ||
      cols[0]?.name ||
      "id";
    const groupCol =
      cols.find((c) => /status|type|state|category|network|studio|role/i.test(c.name))?.name ||
      cols[1]?.name ||
      cols[0]?.name ||
      "id";
    return [
      `Show top 10 ${tbl} sorted by ${sortCol} descending`,
      `Count ${tbl} grouped by ${groupCol}`,
      ...(activePresets.slice(0, 2).map((p) => p.title)),
    ];
  }, [resolvedInitialTable, schema.tables, activePresets]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        width: "100vw",
        overflow: "hidden",
        backgroundColor: isDark ? "#070b14" : "#f8fafc",
        color: isDark ? "#f8fafc" : "#0f172a",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Top Studio Bar (52px Fixed Height) */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "14px",
          height: "52px",
          minHeight: "52px",
          maxHeight: "52px",
          boxSizing: "border-box",
          padding: "0 16px",
          borderBottom: `1px solid ${isDark ? "rgba(255, 255, 255, 0.07)" : "#e2e8f0"}`,
          backgroundColor: isDark ? "#0b0f19" : "#ffffff",
          zIndex: 30,
          overflow: "hidden",
        }}
      >
        {/* Left Cluster: Sidebar Toggle, Brand, Active DB Pill & +Cross-DB Join */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0, flexShrink: 1 }}>
          <button
            type="button"
            onClick={() => setIsSidebarOpen((prev) => !prev)}
            title={isSidebarOpen ? "Collapse Schema Explorer" : "Expand Schema Explorer"}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              padding: "6px 12px",
              borderRadius: "6px",
              border: `1px solid ${
                isSidebarOpen
                  ? isDark
                    ? "rgba(255, 255, 255, 0.16)"
                    : "#94a3b8"
                  : isDark
                    ? "rgba(255, 255, 255, 0.08)"
                    : "#cbd5e1"
              }`,
              backgroundColor: isSidebarOpen
                ? isDark
                  ? "rgba(255, 255, 255, 0.07)"
                  : "#e2e8f0"
                : isDark
                  ? "#10141f"
                  : "#f8fafc",
              color: isSidebarOpen ? (isDark ? "#f8fafc" : "#0f172a") : isDark ? "#94a3b8" : "#475569",
              fontSize: "0.85rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            <span>Tables</span>
          </button>

          <span
            style={{
              fontSize: "0.95rem",
              color: isDark ? "#f8fafc" : "#0f172a",
              fontWeight: 700,
              letterSpacing: "-0.01em",
              whiteSpace: "nowrap",
            }}
          >
            Query Studio
          </span>

          {databases.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <div
                title={`${serverStatus} — Switch database in the left sidebar`}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "8px",
                  padding: "5px 11px",
                  borderRadius: "999px",
                  backgroundColor: isDark ? "#10141f" : "#f8fafc",
                  color: isDark ? "#e2e8f0" : "#0f172a",
                  border: `1px solid ${isDark ? "rgba(56, 189, 248, 0.28)" : "#cbd5e1"}`,
                  fontSize: "0.84rem",
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                }}
              >
                <span
                  style={{
                    width: "7px",
                    height: "7px",
                    borderRadius: "50%",
                    backgroundColor: serverStatus.includes("Connected") ? "#10b981" : "#f59e0b",
                    display: "inline-block",
                  }}
                />
                <span
                  style={{
                    maxWidth: "200px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {activeDbInfo?.name || activeDbId}
                </span>
                <span
                  style={{
                    fontSize: "0.73rem",
                    padding: "1px 6px",
                    borderRadius: "999px",
                    backgroundColor: isDark ? "rgba(56, 189, 248, 0.14)" : "#e2e8f0",
                    color: isDark ? "#e0f2fe" : "#475569",
                    fontWeight: 600,
                  }}
                >
                  {isLoadingSchema ? "..." : `${schemaStats.tableCount} tables`}
                </span>
              </div>

              <button
                type="button"
                onClick={() => {
                  setIsSidebarOpen(true);
                  setIsCrossDbExpanded((prev) => !prev);
                }}
                title="Pin another database to join across databases via Federated Hub"
                style={{
                  padding: "5px 11px",
                  borderRadius: "999px",
                  border: `1px solid ${
                    isCrossDbExpanded || activeDbId === "federated_hub"
                      ? isDark
                        ? "rgba(56, 189, 248, 0.4)"
                        : "#94a3b8"
                      : isDark
                        ? "rgba(255, 255, 255, 0.08)"
                        : "#cbd5e1"
                  }`,
                  backgroundColor:
                    isCrossDbExpanded || activeDbId === "federated_hub"
                      ? isDark
                        ? "rgba(56, 189, 248, 0.14)"
                        : "#e2e8f0"
                      : isDark
                        ? "#10141f"
                        : "#f8fafc",
                  color:
                    isCrossDbExpanded || activeDbId === "federated_hub"
                      ? isDark
                        ? "#e0f2fe"
                        : "#0f172a"
                      : isDark
                        ? "#94a3b8"
                        : "#475569",
                  fontSize: "0.82rem",
                  fontWeight: 600,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                }}
              >
                + Cross-DB
              </button>
            </div>
          )}
        </div>

        {/* Center Cluster: Omnipresent Multi-Shot Gemini AI Prompt Input */}
        <div
          style={{
            flex: 1,
            maxWidth: "540px",
            minWidth: "220px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            padding: "5px 8px 5px 12px",
            borderRadius: "7px",
            backgroundColor: isDark ? "#10141f" : "#f8fafc",
            border: `1px solid ${
              isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"
            }`,
          }}
        >
          <input
            ref={topAiInputRef}
            type="text"
            value={paletteQuery}
            onChange={(e) => setPaletteQuery(e.target.value)}
            onFocus={() => setIsAiAssistantOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && paletteQuery.trim()) {
                e.preventDefault();
                void handlePaletteTranslate();
              }
            }}
            placeholder={
              paletteTurns.length > 0
                ? `Refine Turn #${paletteTurns.length} (e.g. "only active", "limit 10")...`
                : `Ask AI about ${activeDbInfo?.name || activeDbId} or refine query...`
            }
            aria-label="Ask AI or refine current query"
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              outline: "none",
              color: isDark ? "#e2e8f0" : "#0f172a",
              fontSize: "0.875rem",
              minWidth: 0,
            }}
          />
          {paletteQuery.trim() ? (
            <button
              type="button"
              disabled={isPaletteTranslating}
              onClick={() => void handlePaletteTranslate()}
              style={{
                padding: "4px 10px",
                borderRadius: "5px",
                border: "none",
                background: "#3b82f6",
                color: "#ffffff",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: isPaletteTranslating ? "not-allowed" : "pointer",
                whiteSpace: "nowrap",
              }}
            >
              {isPaletteTranslating
                ? "Running..."
                : paletteTurns.length > 0
                  ? "Refine ↵"
                  : "Ask AI ↵"}
            </button>
          ) : (
            <kbd
              style={{
                padding: "2px 6px",
                borderRadius: "4px",
                backgroundColor: isDark ? "rgba(255, 255, 255, 0.06)" : "#e2e8f0",
                color: isDark ? "#64748b" : "#64748b",
                fontSize: "0.75rem",
                fontWeight: 600,
                flexShrink: 0,
              }}
            >
              ⌘K
            </kbd>
          )}
        </div>

        {/* Right Cluster: 1-Click Preset Pills, AI Assistant Toggle, Mode Tabs & Theme Toggle */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0, flexShrink: 0 }}>
          {/* Direct 1-Click Preset Chips (no dropdown menu) */}
          {activePresets.length > 0 && (
            <div
              role="group"
              aria-label="Quick query presets"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "4px",
                maxWidth: "220px",
                overflowX: "auto",
                padding: "2px 0",
              }}
            >
              {activePresets.slice(0, 2).map((preset) => {
                const isSel = selectedPreset?.id === preset.id;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    className="studio-preset-item"
                    onClick={() => handleSelectPreset(preset)}
                    title={`${preset.title} — ${preset.description}`}
                    style={{
                      padding: "4px 10px",
                      borderRadius: "999px",
                      border: isSel
                        ? "1px solid rgba(56, 189, 248, 0.45)"
                        : `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#cbd5e1"}`,
                      backgroundColor: isSel
                        ? "rgba(56, 189, 248, 0.16)"
                        : isDark
                          ? "#10141f"
                          : "#f8fafc",
                      color: isSel
                        ? isDark
                          ? "#e0f2fe"
                          : "#0f172a"
                        : isDark
                          ? "#94a3b8"
                          : "#475569",
                      fontSize: "0.76rem",
                      fontWeight: isSel ? 700 : 500,
                      cursor: "pointer",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {preset.title.length > 18 ? `${preset.title.slice(0, 16)}…` : preset.title}
                  </button>
                );
              })}
            </div>
          )}

          {/* Right-Docked AI Assistant Drawer Toggle */}
          <button
            type="button"
            onClick={() => setIsAiAssistantOpen((prev) => !prev)}
            title={isAiAssistantOpen ? "Collapse AI Assistant Drawer" : "Open AI Assistant Drawer"}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              padding: "6px 12px",
              borderRadius: "6px",
              border: `1px solid ${
                isAiAssistantOpen
                  ? isDark
                    ? "rgba(255, 255, 255, 0.2)"
                    : "#94a3b8"
                  : isDark
                    ? "rgba(255, 255, 255, 0.08)"
                    : "#cbd5e1"
              }`,
              background: isAiAssistantOpen
                ? isDark
                  ? "rgba(255, 255, 255, 0.08)"
                  : "#e2e8f0"
                : isDark
                  ? "#10141f"
                  : "#f8fafc",
              color: isAiAssistantOpen ? (isDark ? "#f8fafc" : "#0f172a") : isDark ? "#94a3b8" : "#475569",
              fontSize: "0.84rem",
              fontWeight: 500,
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            <span>AI Assistant</span>
            {paletteTurns.length > 0 && (
              <span
                style={{
                  fontSize: "0.72rem",
                  padding: "0px 6px",
                  borderRadius: "4px",
                  backgroundColor: isDark ? "rgba(255, 255, 255, 0.08)" : "#cbd5e1",
                  color: isDark ? "#e2e8f0" : "#0f172a",
                  fontWeight: 600,
                }}
              >
                {paletteTurns.length}
              </span>
            )}
          </button>

          {/* Studio / Dashboard / Dev Demos Switcher */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              backgroundColor: isDark ? "#10141f" : "#f1f5f9",
              borderRadius: "6px",
              padding: "3px",
              border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#e2e8f0"}`,
              flexShrink: 0,
            }}
          >
            {(showDevTabs
              ? [
                  { id: "visual", label: "Studio" },
                  { id: "dashboard", label: "BI" },
                  { id: "headless", label: "Headless" },
                  { id: "adapters", label: "ORM" },
                ]
              : [
                  { id: "visual", label: "Studio" },
                  { id: "dashboard", label: "BI" },
                ]
            ).map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id as typeof activeTab)}
                  style={{
                    padding: "4px 10px",
                    borderRadius: "4px",
                    border: "none",
                    cursor: "pointer",
                    fontSize: "0.84rem",
                    fontWeight: isActive ? 600 : 500,
                    backgroundColor: isActive
                      ? isDark
                        ? "rgba(255, 255, 255, 0.1)"
                        : "#ffffff"
                      : "transparent",
                    color: isActive ? (isDark ? "#f8fafc" : "#0f172a") : isDark ? "#64748b" : "#64748b",
                  }}
                >
                  {tab.label}
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => setShowDevTabs((prev) => !prev)}
              title={showDevTabs ? "Hide developer SDK demos" : "Show Headless & ORM Adapter demos"}
              style={{
                padding: "4px 8px",
                borderRadius: "4px",
                border: "none",
                background: "transparent",
                color: isDark ? "#64748b" : "#94a3b8",
                fontSize: "0.8rem",
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              {showDevTabs ? "◂" : "⋯"}
            </button>
          </div>

          {/* Theme Toggle */}
          <button
            type="button"
            data-testid="toggle-theme"
            onClick={cycleTheme}
            title={`Theme: ${themePreference} (${resolvedTheme}). Click to switch`}
            style={{
              padding: "6px 10px",
              borderRadius: "6px",
              border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#cbd5e1"}`,
              cursor: "pointer",
              fontWeight: 600,
              fontSize: "0.82rem",
              backgroundColor: isDark ? "#10141f" : "#f8fafc",
              color: isDark ? "#e2e8f0" : "#0f172a",
              whiteSpace: "nowrap",
              flexShrink: 0,
            }}
          >
            {themePreference === "dark" ? "🌙 Dark" : themePreference === "light" ? "☀ Light" : "◐ Auto"}
          </button>
        </div>
      </header>

      {/* Main 3-Pane IDE Body (Left Explorer | Center Split Workspace | Right AI Assistant Drawer) */}
      <main style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "row" }}>
        {/* Left Pane: Schema & Cross-DB Explorer (260px) */}
        {isSidebarOpen && (
          <aside
            aria-label="Data Sources and Tables Explorer"
            style={{
              width: "260px",
              minWidth: "260px",
              height: "100%",
              display: "flex",
              flexDirection: "column",
              borderRight: `1px solid ${isDark ? "rgba(255, 255, 255, 0.07)" : "#e2e8f0"}`,
              backgroundColor: isDark ? "#0b0f19" : "#ffffff",
              overflow: "hidden",
            }}
          >
            {/* Section 1: Compact Database Switcher Trigger (No native <select>, expandable drawer) */}
            {databases.length > 0 && (
              <div
                style={{
                  padding: "8px 12px",
                  borderBottom: `1px solid ${isDark ? "rgba(255, 255, 255, 0.07)" : "#e2e8f0"}`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "8px",
                  backgroundColor: isDark ? "#0e1320" : "#f8fafc",
                  flexShrink: 0,
                  height: "38px",
                  boxSizing: "border-box",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "6px", minWidth: 0 }}>
                  <span
                    style={{
                      width: "8px",
                      height: "8px",
                      borderRadius: "50%",
                      backgroundColor: "#10b981",
                      flexShrink: 0,
                    }}
                    title="Database connected"
                  />
                  <span
                    style={{
                      fontSize: "0.8rem",
                      fontWeight: 600,
                      color: isDark ? "#f1f5f9" : "#0f172a",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                    title={activeDbInfo?.name || activeDbId}
                  >
                    {activeDbInfo?.name || activeDbId}
                  </span>
                  <span
                    style={{
                      fontSize: "0.68rem",
                      fontWeight: 500,
                      padding: "1px 5px",
                      borderRadius: "4px",
                      backgroundColor: isDark ? "rgba(255, 255, 255, 0.07)" : "#e2e8f0",
                      color: isDark ? "#94a3b8" : "#64748b",
                      textTransform: "uppercase",
                      flexShrink: 0,
                    }}
                  >
                    {(activeDbInfo?.dialect || KNOWN_DB_DEFAULTS[activeDbId]?.dialect || "sqlite").toUpperCase()}
                  </span>
                </div>

                <button
                  type="button"
                  data-qb="database-switcher-trigger"
                  aria-expanded={isDbSwitcherExpanded}
                  onClick={() => setIsDbSwitcherExpanded((prev) => !prev)}
                  title={isDbSwitcherExpanded ? "Collapse database switcher" : "Expand database switcher"}
                  style={{
                    padding: "3px 8px",
                    fontSize: "0.72rem",
                    fontWeight: 600,
                    borderRadius: "4px",
                    border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.12)" : "#cbd5e1"}`,
                    backgroundColor: isDbSwitcherExpanded
                      ? "rgba(56, 189, 248, 0.16)"
                      : isDark
                        ? "rgba(255, 255, 255, 0.04)"
                        : "#ffffff",
                    color: isDbSwitcherExpanded ? (isDark ? "#38bdf8" : "#0284c7") : isDark ? "#94a3b8" : "#475569",
                    cursor: "pointer",
                    flexShrink: 0,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "4px",
                  }}
                >
                  <span>{databases.length} DBs</span>
                  <span>{isDbSwitcherExpanded ? "▴" : "▾"}</span>
                </button>
              </div>
            )}

            {/* Preserved Legacy Database Pills Container (Visible when expanded, in DOM via SR_ONLY_STYLE when collapsed) */}
            {databases.length > 0 && (
              <div
                data-qb="sidebar-database-pills"
                style={
                  isDbSwitcherExpanded
                    ? {
                        padding: "8px 12px 10px",
                        borderBottom: `1px solid ${isDark ? "rgba(255, 255, 255, 0.07)" : "#e2e8f0"}`,
                        display: "flex",
                        flexDirection: "column",
                        gap: "6px",
                        backgroundColor: isDark ? "#090d16" : "#f1f5f9",
                        flexShrink: 0,
                      }
                    : SR_ONLY_STYLE
                }
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span
                    style={{
                      fontSize: "0.7rem",
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: isDark ? "#94a3b8" : "#64748b",
                    }}
                  >
                    Select Database ({filteredDatabases.length})
                  </span>
                  <div style={{ display: "flex", gap: "3px" }}>
                    {[
                      { id: "ALL", label: "All" },
                      { id: "FEDERATED", label: "Hub" },
                      { id: "POSTGRES", label: "PG" },
                      { id: "SQLITE", label: "SQLite" },
                    ].map((grp) => {
                      const active = dbFilterGroup === grp.id;
                      return (
                        <button
                          key={grp.id}
                          type="button"
                          onClick={() => setDbFilterGroup(grp.id)}
                          style={{
                            padding: "2px 6px",
                            fontSize: "0.68rem",
                            fontWeight: active ? 700 : 500,
                            borderRadius: "4px",
                            border: active
                              ? "1px solid rgba(56, 189, 248, 0.4)"
                              : "1px solid transparent",
                            backgroundColor: active
                              ? "rgba(56, 189, 248, 0.14)"
                              : "transparent",
                            color: active ? (isDark ? "#e0f2fe" : "#0f172a") : isDark ? "#64748b" : "#94a3b8",
                            cursor: "pointer",
                          }}
                        >
                          {grp.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "4px",
                    maxHeight: "120px",
                    overflowY: "auto",
                    paddingRight: "2px",
                  }}
                >
                  {filteredDatabases.map((db) => {
                    const isSelected = db.id === activeDbId;
                    return (
                      <button
                        key={db.id}
                        type="button"
                        data-qb="database-pill"
                        data-qb-db={db.id}
                        disabled={!db.available}
                        onClick={() => {
                          setActiveDbId(db.id);
                          setIsDbSwitcherExpanded(false);
                        }}
                        title={`Switch to ${db.name} (${db.dialect.toUpperCase()})`}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "5px",
                          padding: "3px 8px",
                          borderRadius: "999px",
                          border: isSelected
                            ? "1px solid rgba(56, 189, 248, 0.45)"
                            : `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#cbd5e1"}`,
                          background: isSelected
                            ? "rgba(56, 189, 248, 0.16)"
                            : isDark
                              ? "#10141f"
                              : "#f8fafc",
                          color: isSelected
                            ? isDark
                              ? "#e0f2fe"
                              : "#0f172a"
                            : isDark
                              ? "#94a3b8"
                              : "#475569",
                          fontSize: "0.75rem",
                          fontWeight: isSelected ? 700 : 500,
                          cursor: db.available ? "pointer" : "not-allowed",
                          opacity: db.available ? 1 : 0.45,
                          whiteSpace: "nowrap",
                        }}
                      >
                        <span>{db.name}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Section 2: Active Database Table Explorer (Zero-Lag CSS Hover) */}
            <div
              style={{
                flex: 1,
                padding: "12px",
                display: "flex",
                flexDirection: "column",
                gap: "8px",
                overflow: "hidden",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span
                  style={{
                    fontSize: "0.76rem",
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    color: isDark ? "#64748b" : "#64748b",
                  }}
                >
                  Tables ({filteredTablesList.length})
                </span>
                <button
                  type="button"
                  onClick={() => fetchSchemaForDb(activeDbId, true)}
                  title="Refresh database schema"
                  style={{
                    background: "transparent",
                    border: "none",
                    color: isDark ? "#64748b" : "#94a3b8",
                    fontSize: "0.85rem",
                    cursor: "pointer",
                    padding: "0 4px",
                  }}
                >
                  {isLoadingSchema ? "..." : "↻"}
                </button>
              </div>

              <input
                type="text"
                value={tableSearch}
                onChange={(e) => setTableSearch(e.target.value)}
                placeholder="Filter tables..."
                style={{
                  width: "100%",
                  padding: "7px 10px",
                  borderRadius: "6px",
                  border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.09)" : "#cbd5e1"}`,
                  backgroundColor: isDark ? "#10141f" : "#f8fafc",
                  color: isDark ? "#e2e8f0" : "#0f172a",
                  fontSize: "0.875rem",
                  outline: "none",
                }}
              />

              {/* Federated Hub Source Prefix Chips */}
              {activeDbId === "federated_hub" && federatedPrefixes.length > 0 && (
                <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={() => setFedSourceFilter("ALL")}
                    style={{
                      padding: "3px 8px",
                      fontSize: "0.75rem",
                      fontWeight: fedSourceFilter === "ALL" ? 600 : 500,
                      borderRadius: "4px",
                      border:
                        fedSourceFilter === "ALL"
                          ? `1px solid ${isDark ? "rgba(255, 255, 255, 0.2)" : "#94a3b8"}`
                          : "1px solid transparent",
                      backgroundColor:
                        fedSourceFilter === "ALL"
                          ? isDark
                            ? "rgba(255, 255, 255, 0.08)"
                            : "#e2e8f0"
                          : "transparent",
                      color: fedSourceFilter === "ALL" ? (isDark ? "#f8fafc" : "#0f172a") : isDark ? "#64748b" : "#64748b",
                      cursor: "pointer",
                    }}
                  >
                    All
                  </button>
                  {federatedPrefixes.map((pfx) => {
                    const active = fedSourceFilter === pfx;
                    return (
                      <button
                        key={pfx}
                        type="button"
                        onClick={() => setFedSourceFilter(pfx)}
                        style={{
                          padding: "3px 8px",
                          fontSize: "0.75rem",
                          fontWeight: active ? 600 : 500,
                          borderRadius: "4px",
                          border: active
                            ? `1px solid ${isDark ? "rgba(255, 255, 255, 0.2)" : "#94a3b8"}`
                            : "1px solid transparent",
                          backgroundColor: active
                            ? isDark
                              ? "rgba(255, 255, 255, 0.08)"
                              : "#e2e8f0"
                            : "transparent",
                          color: active ? (isDark ? "#f8fafc" : "#0f172a") : isDark ? "#64748b" : "#64748b",
                          cursor: "pointer",
                        }}
                      >
                        {pfx}
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Scrollable Table Rows */}
              <div
                data-qb="table-list"
                style={{
                  flex: 1,
                  overflowY: "auto",
                  display: "flex",
                  flexDirection: "column",
                  gap: "2px",
                  paddingRight: "2px",
                }}
              >
                {(() => {
                  const renderSidebarRow = (tbl: (typeof filteredTablesList)[number]) => {
                    const colCount = (tbl.columns || []).length;
                    const isPrimary = tbl.name === effectiveSidebarPrimaryTable;
                    const joinMatch = !isPrimary
                      ? findBestJoinCondition(effectiveSidebarPrimaryTable, tbl.name, schema)
                      : null;
                    const joinTier = joinMatch?.joinTier || (joinMatch?.isFk ? "confirmed" : "none");
                    const joinTierLabel =
                      joinTier === "confirmed"
                        ? "Confirmed Join"
                        : joinTier === "logical"
                          ? "Logical Join"
                          : "No Dedicated Join";
                    const joinShortBadge =
                      joinTier === "confirmed"
                        ? "✓ Confirmed"
                        : joinTier === "logical"
                          ? "⇄ Logical"
                          : `${colCount} cols`;
                    const joinColor =
                      joinTier === "confirmed"
                        ? isDark
                          ? "#6ee7b7"
                          : "#047857"
                        : joinTier === "logical"
                          ? isDark
                            ? "#93c5fd"
                            : "#1d4ed8"
                          : isDark
                            ? "#64748b"
                            : "#64748b";
                    const joinBg =
                      joinTier === "confirmed"
                        ? isDark
                          ? "rgba(16, 185, 129, 0.14)"
                          : "rgba(5, 150, 105, 0.1)"
                        : joinTier === "logical"
                          ? isDark
                            ? "rgba(59, 130, 246, 0.14)"
                            : "rgba(37, 99, 235, 0.1)"
                          : "transparent";

                    return (
                      <div
                        key={tbl.name}
                        data-qb="table-item"
                        data-qb-table={tbl.name}
                        data-qb-join-tier={isPrimary ? "primary" : joinTier}
                        className="studio-table-row"
                        onClick={() => handleSidebarPreviewTable(tbl.name)}
                        title={
                          isPrimary
                            ? `${tbl.name} (${colCount} columns) — Active primary table`
                            : `${tbl.name} (${colCount} columns) — ${joinTierLabel} with ${effectiveSidebarPrimaryTable}`
                        }
                      >
                        <span
                          style={{
                            fontSize: "0.875rem",
                            fontWeight: isPrimary ? 700 : 500,
                            color: isPrimary
                              ? isDark
                                ? "#38bdf8"
                                : "#0284c7"
                              : isDark
                                ? "#cbd5e1"
                                : "#1e293b",
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            flex: 1,
                          }}
                        >
                          {tbl.name}
                        </span>

                        <span
                          className="studio-row-meta"
                          style={{
                            color: isPrimary ? (isDark ? "#38bdf8" : "#0284c7") : joinColor,
                            backgroundColor: isPrimary
                              ? isDark
                                ? "rgba(56, 189, 248, 0.14)"
                                : "rgba(2, 132, 199, 0.1)"
                              : joinBg,
                            fontSize: "0.68rem",
                            fontWeight: 600,
                            padding: "1px 6px",
                            borderRadius: "999px",
                            flexShrink: 0,
                          }}
                        >
                          {isPrimary ? "Active" : joinShortBadge}
                        </span>

                        <div
                          className="studio-row-actions"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            type="button"
                            onClick={() => handleSidebarSetPrimary(tbl.name)}
                            title={`Explore ${tbl.name} as primary table`}
                            style={{
                              padding: "2px 7px",
                              fontSize: "0.75rem",
                              fontWeight: 500,
                              borderRadius: "4px",
                              border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.14)" : "#cbd5e1"}`,
                              backgroundColor: isDark ? "rgba(255, 255, 255, 0.08)" : "#f1f5f9",
                              color: isDark ? "#e2e8f0" : "#0f172a",
                              cursor: "pointer",
                            }}
                          >
                            Open
                          </button>
                          <button
                            type="button"
                            onClick={() => handleSidebarJoinTable(tbl.name)}
                            title={`${joinTierLabel}: Join ${tbl.name} onto ${effectiveSidebarPrimaryTable}${
                              joinMatch && joinTier !== "none"
                                ? ` (${joinMatch.leftTable}.${joinMatch.leftCol} = ${joinMatch.rightTable}.${joinMatch.rightCol})`
                                : ""
                            }`}
                            style={{
                              padding: "2px 7px",
                              fontSize: "0.75rem",
                              fontWeight: 600,
                              borderRadius: "4px",
                              border: `1px solid ${
                                joinTier === "confirmed"
                                  ? isDark
                                    ? "rgba(16, 185, 129, 0.4)"
                                    : "rgba(5, 150, 105, 0.4)"
                                  : joinTier === "logical"
                                    ? isDark
                                      ? "rgba(59, 130, 246, 0.4)"
                                      : "rgba(37, 99, 235, 0.4)"
                                    : isDark
                                      ? "rgba(255, 255, 255, 0.14)"
                                      : "#cbd5e1"
                              }`,
                              backgroundColor:
                                joinTier === "confirmed"
                                  ? isDark
                                    ? "rgba(16, 185, 129, 0.14)"
                                    : "rgba(5, 150, 105, 0.1)"
                                  : joinTier === "logical"
                                    ? isDark
                                      ? "rgba(59, 130, 246, 0.14)"
                                      : "rgba(37, 99, 235, 0.1)"
                                    : isDark
                                      ? "rgba(255, 255, 255, 0.08)"
                                      : "#f1f5f9",
                              color:
                                joinTier === "confirmed" || joinTier === "logical"
                                  ? joinColor
                                  : isDark
                                    ? "#e2e8f0"
                                    : "#0f172a",
                              cursor: "pointer",
                            }}
                          >
                            +Join
                          </button>
                        </div>
                      </div>
                    );
                  };

                  const isSysExpanded = showSystemTables || Boolean(tableSearch.trim());

                  return (
                    <>
                      {coreTablesList.slice(0, 120).map(renderSidebarRow)}
                      {systemTablesList.length > 0 && (
                        <div style={{ marginTop: "6px" }}>
                          <button
                            type="button"
                            data-testid="toggle-system-tables"
                            onClick={() => setShowSystemTables((prev) => !prev)}
                            style={{
                              width: "100%",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              padding: "6px 8px",
                              borderRadius: "6px",
                              border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.06)" : "#e2e8f0"}`,
                              backgroundColor: isDark ? "rgba(255, 255, 255, 0.03)" : "#f8fafc",
                              color: isDark ? "#94a3b8" : "#475569",
                              fontSize: "0.75rem",
                              fontWeight: 600,
                              cursor: "pointer",
                            }}
                          >
                            <span>System & Internal Tables ({systemTablesList.length})</span>
                            <span>{isSysExpanded ? "▾" : "▸"}</span>
                          </button>
                          {isSysExpanded && (
                            <div
                              style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: "2px",
                                marginTop: "4px",
                              }}
                            >
                              {systemTablesList.slice(0, 100).map(renderSidebarRow)}
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            </div>

            {/* Section 3: Inline Cross-DB Pinning (1-click secondary DB pills, no visible select dropdown) */}
            {isCrossDbExpanded && (
              <div
                style={{
                  borderTop: `1px solid ${isDark ? "rgba(255, 255, 255, 0.07)" : "#e2e8f0"}`,
                  backgroundColor: isDark ? "#0b0f19" : "#f8fafc",
                  padding: "10px 12px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "8px",
                  maxHeight: "46%",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span
                    style={{
                      color: isDark ? "#e2e8f0" : "#0f172a",
                      fontSize: "0.8rem",
                      fontWeight: 600,
                    }}
                  >
                    Join Another Database
                  </span>
                  <button
                    type="button"
                    onClick={() => setIsCrossDbExpanded(false)}
                    style={{
                      background: "transparent",
                      border: "none",
                      color: isDark ? "#94a3b8" : "#64748b",
                      fontSize: "0.82rem",
                      cursor: "pointer",
                    }}
                  >
                    ✕
                  </button>
                </div>

                <select
                  value={pinnedCrossDbId}
                  onChange={(e) => setPinnedCrossDbId(e.target.value)}
                  aria-label="Select secondary database for cross-DB join"
                  style={{
                    position: "absolute",
                    width: "1px",
                    height: "1px",
                    padding: 0,
                    margin: "-1px",
                    overflow: "hidden",
                    clip: "rect(0, 0, 0, 0)",
                    whiteSpace: "nowrap",
                    border: 0,
                  }}
                >
                  {databases
                    .filter((d) => d.id !== "federated_hub" && d.id !== activeDbId && d.available)
                    .map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name} ({d.dialect.toUpperCase()})
                      </option>
                    ))}
                </select>

                <div
                  data-qb="cross-db-target-pills"
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "4px",
                    maxHeight: "68px",
                    overflowY: "auto",
                  }}
                >
                  {databases
                    .filter((d) => d.id !== "federated_hub" && d.id !== activeDbId && d.available)
                    .map((d) => {
                      const active = d.id === pinnedCrossDbId;
                      return (
                        <button
                          key={d.id}
                          type="button"
                          onClick={() => setPinnedCrossDbId(d.id)}
                          style={{
                            padding: "2px 8px",
                            borderRadius: "999px",
                            fontSize: "0.73rem",
                            fontWeight: active ? 700 : 500,
                            border: active
                              ? "1px solid rgba(16, 185, 129, 0.45)"
                              : `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#cbd5e1"}`,
                            backgroundColor: active
                              ? "rgba(16, 185, 129, 0.16)"
                              : isDark
                                ? "#131c31"
                                : "#ffffff",
                            color: active
                              ? isDark
                                ? "#6ee7b7"
                                : "#047857"
                              : isDark
                                ? "#94a3b8"
                                : "#475569",
                            cursor: "pointer",
                          }}
                        >
                          {d.name}
                        </button>
                      );
                    })}
                </div>

                <input
                  type="text"
                  value={pinnedTableSearch}
                  onChange={(e) => setPinnedTableSearch(e.target.value)}
                  placeholder={`Filter ${pinnedCrossDbId} tables...`}
                  style={{
                    width: "100%",
                    padding: "6px 10px",
                    borderRadius: "6px",
                    border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "#cbd5e1"}`,
                    backgroundColor: isDark ? "#131c31" : "#ffffff",
                    color: isDark ? "#f8fafc" : "#0f172a",
                    fontSize: "0.84rem",
                    outline: "none",
                  }}
                />

                <div
                  style={{
                    flex: 1,
                    overflowY: "auto",
                    display: "flex",
                    flexDirection: "column",
                    gap: "2px",
                    maxHeight: "180px",
                  }}
                >
                  {isLoadingPinnedSchema ? (
                    <span style={{ fontSize: "0.82rem", color: "#38bdf8", padding: "4px" }}>
                      Loading {pinnedCrossDbId} tables...
                    </span>
                  ) : (
                    pinnedTablesList.slice(0, 60).map((t) => (
                      <div
                        key={t.name}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: "8px",
                          padding: "6px 8px",
                          borderRadius: "5px",
                          fontSize: "0.84rem",
                        }}
                      >
                        <span
                          style={{
                            color: isDark ? "#cbd5e1" : "#334155",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            flex: 1,
                          }}
                          title={`${pinnedCrossDbId}.${t.name}`}
                        >
                          {t.name}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleCrossDbJoinTable(pinnedCrossDbId, t.name)}
                          title={`Cross-DB Join ${pinnedCrossDbId}.${t.name} onto current query via Federated Hub`}
                          style={{
                            padding: "2px 8px",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                            borderRadius: "4px",
                            border: "1px solid rgba(16, 185, 129, 0.45)",
                            backgroundColor: "rgba(16, 185, 129, 0.16)",
                            color: isDark ? "#34d399" : "#047857",
                            cursor: "pointer",
                            flexShrink: 0,
                          }}
                        >
                          +Join
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </aside>
        )}

        {/* Center Pane: Split Workspace */}
        <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", minWidth: 0 }}>
          {activeTab === "visual" && (
            <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
              <QueryBuilderProvider
                mode="styled"
                themeMode={resolvedTheme}
                customOperators={customOperators}
                cellRenderers={cellRenderers}
              >
                <VisualQueryBuilder
                  ref={builderRef}
                  key={activeDbId}
                  schema={schema}
                  initialTable={resolvedInitialTable}
                  initialSpec={selectedPreset?.spec}
                  dialect={activeDialect}
                  presets={[]}
                  semanticModels={activeDbId === "starter_demo" ? STARTER_SEMANTIC_MODELS : []}
                  defaultAdvancedMode={false}
                  features={{ raw_sql: "standard", schema_tools: "advanced" }}
                  showPlanTab={true}
                  showPipelineTab={true}
                  showNlqBar={false}
                  hideNlqBar={true}
                  compactHeader={true}
                  studioMode={true}
                  nlqApiUrl={`/api/nlq?db=${encodeURIComponent(activeDbId)}`}
                  nlqDefaultProvider={geminiConfigured ? "gemini" : "mock"}
                  onExecuteQuery={handleExecuteQuery}
                />
              </QueryBuilderProvider>
            </div>
          )}

          {activeTab === "dashboard" && (
            <QueryBuilderProvider mode="styled" themeMode={resolvedTheme}>
              <DashboardAndExportDemo
                isDark={isDark}
                activeDbId={activeDbId}
                dialect={activeDialect}
                defaultTable={resolvedInitialTable}
              />
            </QueryBuilderProvider>
          )}

          {activeTab === "headless" && (
            <HeadlessDemo
              key={activeDbId}
              schema={schema}
              dialect={activeDialect}
              defaultTable={resolvedInitialTable}
              onExecuteQuery={handleExecuteQuery}
              isDark={isDark}
            />
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
        </div>

        {/* Right Pane: Collapsible Multi-Shot AI Assistant Drawer (340px) */}
        {isAiAssistantOpen && (
          <aside
            aria-label="AI Assistant"
            style={{
              width: "340px",
              minWidth: "340px",
              height: "100%",
              display: "flex",
              flexDirection: "column",
              borderLeft: `1px solid ${isDark ? "rgba(148, 163, 184, 0.12)" : "#e2e8f0"}`,
              backgroundColor: isDark ? "#0d1322" : "#ffffff",
              overflow: "hidden",
            }}
          >
            {/* AI Assistant Header */}
            <div
              style={{
                padding: "12px 14px",
                borderBottom: `1px solid ${isDark ? "rgba(148, 163, 184, 0.1)" : "#e2e8f0"}`,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "8px",
                backgroundColor: isDark ? "#11182b" : "#f8fafc",
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                <span style={{ fontSize: "0.875rem", fontWeight: 600, color: isDark ? "#f8fafc" : "#0f172a" }}>
                  AI Assistant
                </span>
                <span style={{ fontSize: "0.78rem", color: isDark ? "#94a3b8" : "#64748b" }}>
                  Iterative natural-language query refinement
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                {paletteTurns.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setPaletteTurns([])}
                    title="Clear conversation history and start a fresh chat"
                    style={{
                      padding: "4px 9px",
                      fontSize: "0.78rem",
                      fontWeight: 500,
                      borderRadius: "6px",
                      border: `1px solid ${isDark ? "rgba(148, 163, 184, 0.25)" : "#cbd5e1"}`,
                      background: "transparent",
                      color: isDark ? "#94a3b8" : "#64748b",
                      cursor: "pointer",
                    }}
                  >
                    New Chat
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setIsAiAssistantOpen(false)}
                  title="Collapse AI Assistant Drawer"
                  style={{
                    background: "transparent",
                    border: "none",
                    color: isDark ? "#94a3b8" : "#64748b",
                    cursor: "pointer",
                    fontSize: "0.875rem",
                    padding: "4px 6px",
                  }}
                >
                  ✕
                </button>
              </div>
            </div>

            {paletteError && (
              <div
                style={{
                  padding: "8px 12px",
                  backgroundColor: "rgba(239, 68, 68, 0.14)",
                  color: "#fca5a5",
                  fontSize: "0.8rem",
                  borderBottom: "1px solid rgba(239, 68, 68, 0.3)",
                }}
              >
                {paletteError}
              </div>
            )}

            {/* AI Assistant Conversation Thread */}
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "14px",
                display: "flex",
                flexDirection: "column",
                gap: "12px",
              }}
            >
              {paletteTurns.length === 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                  <div
                    style={{
                      padding: "12px 14px",
                      borderRadius: "8px",
                      backgroundColor: isDark ? "rgba(30, 41, 59, 0.45)" : "#f8fafc",
                      border: `1px solid ${isDark ? "rgba(148, 163, 184, 0.15)" : "#e2e8f0"}`,
                      fontSize: "0.84rem",
                      lineHeight: 1.5,
                      color: isDark ? "#cbd5e1" : "#334155",
                    }}
                  >
                    <div style={{ fontWeight: 600, color: isDark ? "#f8fafc" : "#0f172a", marginBottom: "4px" }}>
                      Natural-Language Query Builder
                    </div>
                    Ask a question in plain English, then reply turn-by-turn to filter, join tables, group, or sort. Every turn updates the visual canvas and runs live.
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    <span
                      style={{
                        fontSize: "0.78rem",
                        fontWeight: 600,
                        color: isDark ? "#94a3b8" : "#64748b",
                      }}
                    >
                      Try asking on {activeDbInfo?.name || activeDbId}:
                    </span>
                    {aiStarterPrompts.map((prompt, i) => (
                      <button
                        key={i}
                        type="button"
                        disabled={isPaletteTranslating}
                        onClick={() => void handlePaletteTranslate(prompt)}
                        className="studio-ai-chip"
                        style={{
                          padding: "8px 12px",
                          borderRadius: "7px",
                          border: `1px solid ${isDark ? "rgba(148, 163, 184, 0.2)" : "#cbd5e1"}`,
                          backgroundColor: isDark ? "#131c31" : "#f8fafc",
                          color: isDark ? "#e2e8f0" : "#1e293b",
                          fontSize: "0.84rem",
                          fontWeight: 500,
                          textAlign: "left",
                          cursor: "pointer",
                          lineHeight: 1.4,
                        }}
                      >
                        “{prompt}”
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <>
                  {paletteTurns.map((t, idx) => {
                    const isLatest = idx === paletteTurns.length - 1;
                    return (
                      <div
                        key={idx}
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          gap: "8px",
                          padding: "12px",
                          borderRadius: "8px",
                          backgroundColor: isDark ? "#131c31" : "#f8fafc",
                          border: `1px solid ${
                            isLatest
                              ? "rgba(16, 185, 129, 0.45)"
                              : isDark
                                ? "rgba(255, 255, 255, 0.08)"
                                : "#e2e8f0"
                          }`,
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <span
                            style={{
                              fontSize: "0.75rem",
                              fontWeight: 600,
                              padding: "2px 8px",
                              borderRadius: "999px",
                              backgroundColor: isLatest
                                ? "rgba(16, 185, 129, 0.18)"
                                : "rgba(59, 130, 246, 0.15)",
                              color: isLatest
                                ? isDark
                                  ? "#34d399"
                                  : "#047857"
                                : isDark
                                  ? "#60a5fa"
                                  : "#1d4ed8",
                            }}
                          >
                            Turn #{idx + 1} {isLatest ? "• Active" : ""}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleRevertToTurn(idx)}
                            title={`Revert canvas and conversation to Turn #${idx + 1}`}
                            style={{
                              background: "transparent",
                              border: `1px solid ${isDark ? "rgba(148, 163, 184, 0.25)" : "#cbd5e1"}`,
                              borderRadius: "5px",
                              padding: "3px 8px",
                              fontSize: "0.75rem",
                              color: isDark ? "#94a3b8" : "#64748b",
                              cursor: "pointer",
                              fontWeight: 500,
                            }}
                          >
                            {isLatest ? "Re-apply" : "Revert here"}
                          </button>
                        </div>

                        <div style={{ fontSize: "0.875rem", fontWeight: 600, color: isDark ? "#e2e8f0" : "#0f172a" }}>
                          “{t.prompt}”
                        </div>

                        <div style={{ fontSize: "0.82rem", color: isDark ? "#93c5fd" : "#1d4ed8", lineHeight: 1.45 }}>
                          {t.explanation}
                        </div>

                        {t.steps && t.steps.length > 0 && (
                          <div style={{ display: "flex", flexDirection: "column", gap: "3px", marginTop: "2px" }}>
                            {t.steps.slice(0, 3).map((step, sIdx) => (
                              <span
                                key={sIdx}
                                style={{ fontSize: "0.78rem", color: isDark ? "#94a3b8" : "#64748b" }}
                              >
                                • {step}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}

                  {/* Follow-up refinement chips for the latest turn */}
                  {paletteTurns[paletteTurns.length - 1].followUps.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "4px" }}>
                      <span style={{ fontSize: "0.78rem", fontWeight: 600, color: isDark ? "#34d399" : "#047857" }}>
                        Follow-up refinements:
                      </span>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                        {paletteTurns[paletteTurns.length - 1].followUps.map((chip, i) => (
                          <button
                            key={i}
                            type="button"
                            disabled={isPaletteTranslating}
                            onClick={() => void handlePaletteTranslate(chip)}
                            className="studio-ai-chip"
                            style={{
                              padding: "5px 10px",
                              fontSize: "0.8rem",
                              fontWeight: 500,
                              borderRadius: "6px",
                              border: "1px solid rgba(52, 211, 153, 0.4)",
                              backgroundColor: "rgba(16, 185, 129, 0.14)",
                              color: isDark ? "#a7f3d0" : "#065f46",
                              cursor: "pointer",
                            }}
                          >
                            + {chip}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* AI Assistant Bottom Reply Input */}
            <div
              style={{
                padding: "12px 14px",
                borderTop: `1px solid ${isDark ? "rgba(148, 163, 184, 0.12)" : "#e2e8f0"}`,
                backgroundColor: isDark ? "#11182b" : "#f8fafc",
                display: "flex",
                flexDirection: "column",
                gap: "8px",
              }}
            >
              <div style={{ display: "flex", gap: "8px" }}>
                <input
                  ref={aiReplyInputRef}
                  type="text"
                  value={paletteQuery}
                  onChange={(e) => setPaletteQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && paletteQuery.trim()) {
                      e.preventDefault();
                      void handlePaletteTranslate();
                    }
                  }}
                  placeholder={
                    paletteTurns.length > 0
                      ? "Reply to refine query..."
                      : "Ask AI to build or refine a query..."
                  }
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: "7px",
                    border: `1px solid ${isDark ? "rgba(148, 163, 184, 0.25)" : "#cbd5e1"}`,
                    backgroundColor: isDark ? "#070b14" : "#ffffff",
                    color: isDark ? "#f8fafc" : "#0f172a",
                    fontSize: "0.85rem",
                    outline: "none",
                  }}
                />
                <button
                  type="button"
                  disabled={isPaletteTranslating || !paletteQuery.trim()}
                  onClick={() => void handlePaletteTranslate()}
                  style={{
                    padding: "8px 14px",
                    borderRadius: "7px",
                    border: "none",
                    background: "#3b82f6",
                    color: "#ffffff",
                    fontSize: "0.84rem",
                    fontWeight: 600,
                    cursor: isPaletteTranslating || !paletteQuery.trim() ? "not-allowed" : "pointer",
                    opacity: isPaletteTranslating || !paletteQuery.trim() ? 0.5 : 1,
                    whiteSpace: "nowrap",
                  }}
                >
                  {isPaletteTranslating
                    ? "Running..."
                    : paletteTurns.length > 0
                      ? "Refine"
                      : "Send"}
                </button>
              </div>
            </div>
          </aside>
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard & Export Workbench Demonstration Tab
// ---------------------------------------------------------------------------
function DashboardAndExportDemo({
  isDark = true,
  activeDbId = "starter_demo",
  dialect = "sqlite",
  defaultTable = "orders",
}: {
  isDark?: boolean;
  activeDbId?: string;
  dialect?: "postgres" | "sqlite";
  defaultTable?: string;
}) {
  const sampleExportSpec: QuerySpec = useMemo(
    () =>
      activeDbId === "starter_demo"
        ? {
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
          }
        : {
            table: defaultTable,
            columns: [],
            joins: [],
            filters: [],
            filter_join: "AND",
            order_by: [],
            distinct: false,
            limit: 25,
          },
    [activeDbId, defaultTable],
  );

  const handleExportStream = async (format: ExportFormat) => {
    const res = await fetch(`/api/export?db=${encodeURIComponent(activeDbId)}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-QB-Database": activeDbId,
      },
      body: JSON.stringify({ db: activeDbId, format, spec: sampleExportSpec, stream: true }),
    });
    if (!res.ok) {
      throw new Error(`Export failed with HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${defaultTable}_export.${format === "excel" ? "xlsx" : format}`;
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
          📦 Code Generation & Streaming Dataset Exporter ({defaultTable})
        </h3>
        <ExportWorkbench
          spec={sampleExportSpec}
          dialect={dialect}
          streamEndpoint={`/api/export?db=${encodeURIComponent(activeDbId)}`}
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
  dialect = "sqlite",
  defaultTable: defaultTableProp,
  onExecuteQuery,
  isDark = true,
}: {
  schema: SchemaSnapshot;
  dialect?: "postgres" | "sqlite";
  defaultTable?: string;
  onExecuteQuery: (
    sql: string,
    spec?: QuerySpec | SerializedQuerySpec | Record<string, unknown> | null,
  ) => Promise<QueryResultData>;
  isDark?: boolean;
}) {
  const tableNames = useMemo(() => Object.keys(schema.tables || {}), [schema]);
  const defaultTable =
    defaultTableProp && tableNames.includes(defaultTableProp)
      ? defaultTableProp
      : tableNames.length > 0
        ? tableNames[0]
        : "products";

  const { state, compiled, actions, safety } = useQueryBuilder({
    schema,
    initialTable: defaultTable,
    dialect,
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
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", flex: 1 }}>
            <span
              style={{
                fontSize: "0.85rem",
                fontWeight: 600,
                color: isDark ? "#e2e8f0" : "#334155",
              }}
            >
              Primary Table ({tableNames.length}):
            </span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
              {tableNames.slice(0, 18).map((tbl) => {
                const isSelected = state.primaryTable === tbl;
                return (
                  <button
                    key={tbl}
                    type="button"
                    onClick={() => actions.setPrimaryTable(tbl)}
                    style={{
                      padding: "4px 10px",
                      borderRadius: "6px",
                      border: isSelected
                        ? "1px solid #3b82f6"
                        : `1px solid ${isDark ? "rgba(255, 255, 255, 0.12)" : "#cbd5e1"}`,
                      backgroundColor: isSelected
                        ? "rgba(59, 130, 246, 0.2)"
                        : isDark
                          ? "#0f172a"
                          : "#f8fafc",
                      color: isSelected ? "#60a5fa" : isDark ? "#cbd5e1" : "#334155",
                      fontSize: "0.76rem",
                      fontWeight: isSelected ? 700 : 500,
                      cursor: "pointer",
                    }}
                  >
                    {tbl}
                  </button>
                );
              })}
            </div>
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
                  <th
                    style={{
                      width: "48px",
                      minWidth: "48px",
                      maxWidth: "52px",
                      padding: "10px 10px",
                      textAlign: "right",
                      fontVariantNumeric: "tabular-nums",
                      borderBottom: `1px solid ${
                        isDark ? "rgba(255, 255, 255, 0.1)" : "#cbd5e1"
                      }`,
                      borderRight: `1px solid ${
                        isDark ? "rgba(255, 255, 255, 0.08)" : "#e2e8f0"
                      }`,
                      color: isDark ? "#64748b" : "#94a3b8",
                      fontWeight: 600,
                      fontSize: "0.78rem",
                      userSelect: "none",
                    }}
                  >
                    #
                  </th>
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
                    <td
                      style={{
                        width: "48px",
                        minWidth: "48px",
                        maxWidth: "52px",
                        padding: "9px 10px",
                        textAlign: "right",
                        fontVariantNumeric: "tabular-nums",
                        fontFamily: "ui-monospace, monospace",
                        fontSize: "0.8rem",
                        color: isDark ? "#64748b" : "#94a3b8",
                        borderRight: `1px solid ${
                          isDark ? "rgba(255, 255, 255, 0.08)" : "#e2e8f0"
                        }`,
                        userSelect: "none",
                      }}
                    >
                      {idx + 1}
                    </td>
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
