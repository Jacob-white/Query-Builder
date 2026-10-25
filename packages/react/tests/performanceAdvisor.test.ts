import { describe, it, expect } from "vitest";
import {
  estimateCloudQueryCost,
  recommendIndexes,
  analyzeQueryPerformance,
} from "../src/utils/performanceAdvisor";
import { estimateClientPlan } from "../src/utils/compiler";
import type { QuerySpec, SchemaSnapshot } from "../src/types";

describe("performanceAdvisor Utilities", () => {
  describe("estimateCloudQueryCost", () => {
    it("estimates cost for BigQuery with default heuristics and minimum 10MB quantum", () => {
      const sql = "SELECT * FROM orders WHERE status = 'shipped';";
      const cost = estimateCloudQueryCost(sql, "bigquery");

      expect(cost.pricingTier).toContain("BigQuery On-Demand");
      expect(cost.bytesScannedEstimated).toBeGreaterThanOrEqual(10 * 1024 * 1024);
      expect(cost.dollarCostEstimated).toBeGreaterThan(0);
      expect(cost.isCached).toBe(false);
    });

    it("estimates cost for BigQuery using explicit tableStats byteSize", () => {
      const sql = "SELECT id FROM events;";
      const cost = estimateCloudQueryCost(sql, "bigquery", {
        events: { byteSize: 500 * 1024 * 1024 * 1024 }, // 500 GB
      });

      expect(cost.bytesScannedEstimated).toBe(500 * 1024 * 1024 * 1024);
      expect(cost.dollarCostEstimated).toBeCloseTo((500 / 1024) * 6.25, 2);
    });

    it("estimates cost for Snowflake warehouse execution", () => {
      const sql = "SELECT * FROM sales JOIN customers ON customer_id = id;";
      const cost = estimateCloudQueryCost(sql, "snowflake");

      expect(cost.pricingTier).toContain("Snowflake");
      expect(cost.creditsEstimated).toBeGreaterThan(0);
      expect(cost.dollarCostEstimated).toBeGreaterThan(0);
    });

    it("returns zero cost for local / hosted Postgres or DuckDB", () => {
      const sql = "SELECT * FROM users;";
      const cost = estimateCloudQueryCost(sql, "postgres");

      expect(cost.dollarCostEstimated).toBe(0);
      expect(cost.pricingTier).toContain("Zero-Cost Local");
    });
  });

  describe("recommendIndexes", () => {
    const mockSchema: SchemaSnapshot = {
      tables: {
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "int", is_nullable: false, is_primary: true },
            { name: "email", data_type: "text", is_nullable: false, is_primary: false },
          ],
        },
      },
    };

    it("recommends indexes for WHERE filters", () => {
      const spec: Partial<QuerySpec> = {
        table: "users",
        filters: [{ column: "email", op: "=", value: "test@example.com" }],
      };

      const recs = recommendIndexes(spec, mockSchema);
      expect(recs).toHaveLength(1);
      expect(recs[0].indexName).toBe("idx_users_email");
      expect(recs[0].ddl).toBe("CREATE INDEX idx_users_email ON users (email);");
      expect(recs[0].estimatedImpact).toBe("high");
    });

    it("skips primary keys already indexed", () => {
      const spec: Partial<QuerySpec> = {
        table: "users",
        filters: [{ column: "id", op: "=", value: 1 }],
      };

      const recs = recommendIndexes(spec, mockSchema);
      expect(recs).toHaveLength(0);
    });

    it("recommends indexes for JOIN foreign keys", () => {
      const spec: Partial<QuerySpec> = {
        table: "orders",
        joins: [
          {
            table: "customers",
            type: "INNER",
            left_table: "orders",
            left_col: "customer_id",
            right_col: "id",
          },
          {
            table: "order_items",
            type: "LEFT",
            left_table: "orders",
            left_col: "id",
            right_col: "order_id",
          },
        ],
      };

      const recs = recommendIndexes(spec);
      expect(recs.some((r) => r.indexName === "idx_order_items_order_id")).toBe(true);
    });

    it("recommends composite index for filter and sort column combinations", () => {
      const spec: Partial<QuerySpec> = {
        table: "logs",
        filters: [{ column: "service", op: "=", value: "auth" }],
        order_by: [{ column: "timestamp", direction: "DESC" }],
      };

      const recs = recommendIndexes(spec);
      const comp = recs.find((r) => r.columns.length === 2);
      expect(comp).toBeDefined();
      expect(comp?.ddl).toBe("CREATE INDEX idx_logs_comp_service_timestamp ON logs (service, timestamp);");
      expect(comp?.estimatedImpact).toBe("medium");
    });

    it("returns empty recommendations when table is missing", () => {
      expect(recommendIndexes({})).toEqual([]);
    });

    it("resolves joined table aliases, skips joined table primary keys, and deduplicates indexes", () => {
      const multiTableSchema: SchemaSnapshot = {
        tables: {
          orders: {
            name: "orders",
            columns: [
              { name: "order_id", data_type: "int", is_nullable: false, is_primary: true },
              { name: "customer_id", data_type: "int", is_nullable: false, is_primary: false },
            ],
          },
          customers: {
            name: "customers",
            columns: [
              { name: "cust_id", data_type: "int", is_nullable: false, is_primary: true },
              { name: "region", data_type: "text", is_nullable: false, is_primary: false },
            ],
          },
        },
      };

      const spec: Partial<QuerySpec> = {
        table: "public.orders",
        joins: [
          {
            table: "public.customers",
            type: "INNER",
            alias: "c",
            left_col: "customer_id",
            right_col: "c.cust_id",
          },
        ],
        filters: [
          { column: "t0.order_id", op: "=", value: 10 },
          { column: "c.region", op: "=", value: "US" },
          { column: "t1.region", op: "=", value: "EU" },
        ],
      };

      const recs = recommendIndexes(spec, multiTableSchema);
      // order_id on orders and cust_id on customers are primary keys -> skipped
      // c.region and t1.region both resolve to customers.region -> deduplicated to 1 recommendation
      expect(recs).toHaveLength(1);
      expect(recs[0].table).toBe("customers");
      expect(recs[0].indexName).toBe("idx_customers_region");
    });
  });

  describe("analyzeQueryPerformance", () => {
    it("flags unbounded table scan when SELECT * is used without LIMIT", () => {
      const spec: Partial<QuerySpec> = { table: "analytics", columns: ["*"] };
      const sql = "SELECT * FROM analytics;";
      const insights = analyzeQueryPerformance(spec, sql, "postgres");

      const warn = insights.find((i) => i.title.includes("Unbounded Table Scan"));
      expect(warn).toBeDefined();
      expect(warn?.severity).toBe("warning");
    });

    it("flags full table scan when query has no WHERE filters", () => {
      const spec: Partial<QuerySpec> = { table: "products", columns: ["id", "price"], limit: 10 };
      const sql = "SELECT id, price FROM products LIMIT 10;";
      const insights = analyzeQueryPerformance(spec, sql, "bigquery");

      const opt = insights.find((i) => i.title === "Full Table Scan");
      expect(opt).toBeDefined();
    });

    it("forwards schema to recommendIndexes to suppress primary key index suggestions", () => {
      const schema: SchemaSnapshot = {
        tables: {
          users: {
            name: "users",
            columns: [
              { name: "user_uuid", data_type: "uuid", is_nullable: false, is_primary: true },
            ],
          },
        },
      };
      const spec: Partial<QuerySpec> = {
        table: "users",
        columns: ["user_uuid"],
        filters: [{ column: "user_uuid", op: "=", value: "u-1" }],
        limit: 10,
      };
      const insights = analyzeQueryPerformance(
        spec,
        "SELECT user_uuid FROM users WHERE user_uuid = 'u-1' LIMIT 10;",
        "postgres",
        undefined,
        schema,
      );
      expect(insights.filter((i) => i.type === "index")).toHaveLength(0);
    });
  });

  describe("estimateClientPlan with schema", () => {
    it("emits Index Scan for primary key filter and joined primary key when schema is supplied", () => {
      const schema: SchemaSnapshot = {
        tables: {
          orders: {
            name: "orders",
            columns: [
              { name: "order_id", data_type: "int", is_nullable: false, is_primary: true },
            ],
          },
          customers: {
            name: "customers",
            columns: [
              { name: "cust_id", data_type: "int", is_nullable: false, is_primary: true },
            ],
          },
        },
      };
      const plan = estimateClientPlan(
        {
          table: "orders",
          filters: [{ column: "orders.order_id", op: "=", value: 42 }],
          joins: [
            {
              table: "customers",
              type: "INNER",
              left_col: "customer_id",
              right_col: "customers.cust_id",
            },
          ],
          limit: 10,
        },
        schema,
      );
      const sortNode = plan.children?.[0];
      const joinNode = sortNode?.children?.[0];
      expect(joinNode?.node_type).toBe("INNER Join");
      expect(joinNode?.children?.[0]?.node_type).toBe("Index Scan");
      expect(joinNode?.children?.[1]?.node_type).toBe("Index Scan");
    });

    it("handles composite primary keys, non-PK id columns, and cross-table filter/sort pairs", () => {
      const compositeSchema: SchemaSnapshot = {
        tables: {
          order_items: {
            name: "order_items",
            columns: [
              { name: "order_id", data_type: "int", is_nullable: false, is_primary: true },
              { name: "item_id", data_type: "int", is_nullable: false, is_primary: true },
            ],
          },
          orders: {
            name: "orders",
            columns: [
              { name: "order_uuid", data_type: "uuid", is_nullable: false, is_primary: true },
              { name: "id", data_type: "int", is_nullable: false, is_primary: false },
            ],
          },
          customers: {
            name: "customers",
            columns: [
              { name: "cust_id", data_type: "int", is_nullable: false, is_primary: true },
              { name: "region", data_type: "text", is_nullable: false, is_primary: false },
              { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
            ],
          },
        },
      };

      // Non-leading column of composite PK filtered alone -> Seq Scan and index recommended
      const nonLeadingPlan = estimateClientPlan(
        {
          table: "order_items",
          filters: [{ column: "item_id", op: "=", value: 5 }],
          limit: 10,
        },
        compositeSchema,
      );
      expect(nonLeadingPlan.children?.[0]?.children?.[0]?.node_type).toBe("Seq Scan");

      const nonLeadingRecs = recommendIndexes(
        {
          table: "order_items",
          filters: [{ column: "item_id", op: "=", value: 5 }],
        },
        compositeSchema,
      );
      expect(nonLeadingRecs.some((r) => r.indexName === "idx_order_items_item_id")).toBe(true);

      // Leading + second composite PK columns filtered together -> covered by composite PK
      const bothRecs = recommendIndexes(
        {
          table: "order_items",
          filters: [
            { column: "order_id", op: "=", value: 10 },
            { column: "item_id", op: "=", value: 5 },
          ],
        },
        compositeSchema,
      );
      expect(bothRecs).toHaveLength(0);

      // Explicit non-PK 'id' column when table has PK 'order_uuid' -> recommends idx_orders_id
      const nonPkIdRecs = recommendIndexes(
        {
          table: "orders",
          filters: [{ column: "id", op: "=", value: 99 }],
        },
        compositeSchema,
      );
      expect(nonPkIdRecs.some((r) => r.indexName === "idx_orders_id")).toBe(true);

      // Cross-table filter (c.region) + sort (orders.id) -> no single-table composite index
      const crossTableRecs = recommendIndexes(
        {
          table: "orders",
          joins: [
            {
              table: "customers",
              type: "INNER",
              alias: "c",
              left_col: "cust_id",
              right_col: "c.cust_id",
            },
          ],
          filters: [{ column: "c.region", op: "=", value: "US" }],
          order_by: [{ column: "orders.id", direction: "DESC" }],
        },
        compositeSchema,
      );
      expect(crossTableRecs.some((r) => r.columns.length === 2)).toBe(false);

      // Same-table aliased filter (c.region) + sort (c.created_at) -> composite index on customers
      const sameAliasRecs = recommendIndexes(
        {
          table: "orders",
          joins: [
            {
              table: "customers",
              type: "INNER",
              alias: "c",
              left_col: "cust_id",
              right_col: "c.cust_id",
            },
          ],
          filters: [{ column: "c.region", op: "=", value: "US" }],
          order_by: [{ column: "c.created_at", direction: "DESC" }],
        },
        compositeSchema,
      );
      const comp = sameAliasRecs.find((r) => r.columns.length === 2);
      expect(comp?.table).toBe("customers");
      expect(comp?.indexName).toBe("idx_customers_comp_region_created_at");
    });
  });
});

