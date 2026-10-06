import { describe, it, expect } from "vitest";
import {
  estimateCloudQueryCost,
  recommendIndexes,
  analyzeQueryPerformance,
} from "../src/utils/performanceAdvisor";
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
  });
});
