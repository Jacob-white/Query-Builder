import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import {
  formatMetricFilterSql,
  expandMetricSql,
  expandTimeGrainSql,
  parseSemanticModelsJson,
  attachSemanticModelsToTables,
  SUPPORTED_TIME_GRAINS,
  SUPPORTED_AGGREGATIONS,
} from "../src/adapters/semantic";
import { compileVisualState } from "../src/utils/compiler";
import { TableCard } from "../src/components/TableCard";
import { QueryCanvas } from "../src/components/QueryCanvas";
import type {
  MetricDefinition,
  SemanticModel,
  TableMeta,
  TimeGrain,
  SchemaSnapshot,
  VisualColumnSelect,
} from "../src/types";
import { invalid } from "./helpers";

describe("Semantic Metrics & Modeling Layer Adapter", () => {
  describe("formatMetricFilterSql", () => {
    it("formats eq and = operators for null, strings, and numbers", () => {
      expect(formatMetricFilterSql({ field: "status", operator: "eq", value: null })).toBe("status IS NULL");
      expect(formatMetricFilterSql({ field: "status", operator: "eq", value: undefined })).toBe("status IS NULL");
      expect(formatMetricFilterSql({ field: "status", operator: "eq", value: "active" })).toBe("status = 'active'");
      expect(formatMetricFilterSql({ field: "amount", operator: "=", value: 100 })).toBe("amount = 100");
    });

    it("formats neq, !=, and <> operators for null, strings, and numbers", () => {
      expect(formatMetricFilterSql({ field: "status", operator: "neq", value: null })).toBe("status IS NOT NULL");
      expect(formatMetricFilterSql({ field: "status", operator: "!=", value: undefined })).toBe("status IS NOT NULL");
      expect(formatMetricFilterSql({ field: "status", operator: "neq", value: "pending" })).toBe("status <> 'pending'");
      expect(formatMetricFilterSql({ field: "amount", operator: "<>", value: 0 })).toBe("amount <> 0");
    });

    it("formats numeric inequality operators gt, gte, lt, lte", () => {
      expect(formatMetricFilterSql({ field: "price", operator: "gt", value: 50 })).toBe("price > 50");
      expect(formatMetricFilterSql({ field: "price", operator: ">", value: 50 })).toBe("price > 50");
      expect(formatMetricFilterSql({ field: "price", operator: "gte", value: 50 })).toBe("price >= 50");
      expect(formatMetricFilterSql({ field: "price", operator: ">=", value: 50 })).toBe("price >= 50");
      expect(formatMetricFilterSql({ field: "price", operator: "lt", value: 100 })).toBe("price < 100");
      expect(formatMetricFilterSql({ field: "price", operator: "<", value: 100 })).toBe("price < 100");
      expect(formatMetricFilterSql({ field: "price", operator: "lte", value: 100 })).toBe("price <= 100");
      expect(formatMetricFilterSql({ field: "price", operator: "<=", value: 100 })).toBe("price <= 100");
    });

    it("formats in and not_in operators for arrays and raw strings", () => {
      expect(formatMetricFilterSql({ field: "tier", operator: "in", value: ["free", "pro", 3] })).toBe(
        "tier IN ('free', 'pro', 3)"
      );
      expect(formatMetricFilterSql({ field: "tier", operator: "in", value: "1, 2, 3" })).toBe("tier IN (1, 2, 3)");

      expect(formatMetricFilterSql({ field: "status", operator: "not_in", value: ["archived", "banned"] })).toBe(
        "status NOT IN ('archived', 'banned')"
      );
      expect(formatMetricFilterSql({ field: "status", operator: "not in", value: "4, 5" })).toBe(
        "status NOT IN (4, 5)"
      );
    });

    it("formats is_null and is_not_null operators", () => {
      expect(formatMetricFilterSql({ field: "deleted_at", operator: "is_null", value: null })).toBe(
        "deleted_at IS NULL"
      );
      expect(formatMetricFilterSql({ field: "deleted_at", operator: "is_not_null", value: null })).toBe(
        "deleted_at IS NOT NULL"
      );
    });

    it("falls back gracefully for unknown operators", () => {
      expect(formatMetricFilterSql({ field: "name", operator: "unknown_op", value: "test" })).toBe(
        "name = 'test'"
      );
      expect(formatMetricFilterSql({ field: "total", operator: "unknown_op", value: 42 })).toBe(
        "total = 42"
      );
    });
  });

  describe("expandMetricSql", () => {
    it("handles custom aggregation with and without filters", () => {
      const customMetric: MetricDefinition = {
        name: "custom_ratio",
        title: "Custom Ratio",
        sqlExpression: "SUM(a) / NULLIF(SUM(b), 0)",
        aggregation: "custom",
      };
      expect(expandMetricSql(customMetric)).toBe("(SUM(a) / NULLIF(SUM(b), 0))");

      const filteredCustom: MetricDefinition = {
        ...customMetric,
        filters: [{ field: "is_active", operator: "eq", value: true }],
      };
      expect(expandMetricSql(filteredCustom)).toBe(
        "CASE WHEN is_active = true THEN (SUM(a) / NULLIF(SUM(b), 0)) ELSE NULL END"
      );
    });

    it("handles count_distinct across Postgres/FILTER dialects and MySQL/CASE dialects", () => {
      const distinctMetric: MetricDefinition = {
        name: "unique_users",
        title: "Unique Users",
        sqlExpression: "user_id",
        aggregation: "count_distinct",
      };
      expect(expandMetricSql(distinctMetric, "postgres")).toBe("COUNT(DISTINCT user_id)");

      const filteredDistinct: MetricDefinition = {
        ...distinctMetric,
        filters: [{ field: "plan", operator: "eq", value: "enterprise" }],
      };
      expect(expandMetricSql(filteredDistinct, "postgres")).toBe(
        "COUNT(DISTINCT user_id) FILTER (WHERE plan = 'enterprise')"
      );
      expect(expandMetricSql(filteredDistinct, "duckdb")).toBe(
        "COUNT(DISTINCT user_id) FILTER (WHERE plan = 'enterprise')"
      );
      expect(expandMetricSql(filteredDistinct, "mysql")).toBe(
        "COUNT(DISTINCT CASE WHEN plan = 'enterprise' THEN user_id ELSE NULL END)"
      );
      expect(expandMetricSql(filteredDistinct, "snowflake")).toBe(
        "COUNT(DISTINCT CASE WHEN plan = 'enterprise' THEN user_id ELSE NULL END)"
      );
    });

    it("handles standard aggregations sum, avg, min, max, count across dialects", () => {
      const sumMetric: MetricDefinition = {
        name: "revenue",
        title: "Total Revenue",
        sqlExpression: "orders.amount",
        aggregation: "sum",
        filters: [{ field: "status", operator: "eq", value: "completed" }],
      };
      expect(expandMetricSql(sumMetric, "postgres")).toBe(
        "SUM(orders.amount) FILTER (WHERE status = 'completed')"
      );
      expect(expandMetricSql(sumMetric, "mysql")).toBe(
        "SUM(CASE WHEN status = 'completed' THEN orders.amount ELSE NULL END)"
      );

      const avgMetric: MetricDefinition = {
        name: "avg_spend",
        title: "Average Spend",
        sqlExpression: "amount",
        aggregation: "avg",
      };
      expect(expandMetricSql(avgMetric)).toBe("AVG(amount)");
    });
  });

  describe("expandTimeGrainSql", () => {
    it("truncates time grain for Postgres / DuckDB / Snowflake / Redshift", () => {
      expect(expandTimeGrainSql("created_at", "month", "postgres")).toBe("DATE_TRUNC('month', created_at)");
      expect(expandTimeGrainSql("created_at", "day", "duckdb")).toBe("DATE_TRUNC('day', created_at)");
      expect(expandTimeGrainSql("created_at", "year", "snowflake")).toBe("DATE_TRUNC('year', created_at)");
    });

    it("truncates time grain for BigQuery", () => {
      expect(expandTimeGrainSql("timestamp_col", "hour", "bigquery")).toBe(
        "DATE_TRUNC(timestamp_col, HOUR)"
      );
      expect(expandTimeGrainSql("timestamp_col", "quarter", "bigquery")).toBe(
        "DATE_TRUNC(timestamp_col, QUARTER)"
      );
    });

    it("formats time grains for SQLite", () => {
      for (const grain of SUPPORTED_TIME_GRAINS) {
        const sql = expandTimeGrainSql("dt", grain, "sqlite");
        expect(sql).toContain("STRFTIME(");
      }
      expect(expandTimeGrainSql("dt", invalid<TimeGrain>("custom_grain"), "sqlite")).toBe("STRFTIME('%Y-%m-%d', dt)");
    });

    it("formats time grains for MySQL and MariaDB", () => {
      for (const grain of SUPPORTED_TIME_GRAINS) {
        const sql = expandTimeGrainSql("dt", grain, "mysql");
        expect(sql).toContain("DATE_FORMAT(");
      }
      expect(expandTimeGrainSql("dt", invalid<TimeGrain>("custom_grain"), "mariadb")).toBe("DATE_FORMAT(dt, '%Y-%m-%d')");
    });

    it("formats time grains for MSSQL / SQL Server", () => {
      expect(expandTimeGrainSql("order_date", "week", "mssql")).toBe("DATETRUNC(week, order_date)");
      expect(expandTimeGrainSql("order_date", "month", "sqlserver")).toBe("DATETRUNC(month, order_date)");
    });

    it("formats time grains for Oracle", () => {
      expect(expandTimeGrainSql("tx_time", "day", "oracle")).toBe("TRUNC(tx_time, 'DD')");
      expect(expandTimeGrainSql("tx_time", "week", "oracle")).toBe("TRUNC(tx_time, 'IW')");
      expect(expandTimeGrainSql("tx_time", "month", "oracle")).toBe("TRUNC(tx_time, 'MM')");
      expect(expandTimeGrainSql("tx_time", "quarter", "oracle")).toBe("TRUNC(tx_time, 'Q')");
      expect(expandTimeGrainSql("tx_time", "year", "oracle")).toBe("TRUNC(tx_time, 'YYYY')");
      expect(expandTimeGrainSql("tx_time", "hour", "oracle")).toBe("TRUNC(tx_time, 'HH')");
      expect(expandTimeGrainSql("tx_time", "minute", "oracle")).toBe("TRUNC(tx_time, 'MI')");
      expect(expandTimeGrainSql("tx_time", "second", "oracle")).toBe("TRUNC(tx_time, 'SS')");
      expect(expandTimeGrainSql("tx_time", invalid<TimeGrain>("unknown"), "oracle")).toBe("TRUNC(tx_time, 'DD')");
    });

    it("falls back to DATE_TRUNC for unknown dialects", () => {
      expect(expandTimeGrainSql("log_ts", "hour", "generic_db")).toBe("DATE_TRUNC('hour', log_ts)");
    });
  });

  describe("parseSemanticModelsJson", () => {
    it("parses single model JSON, array, or object with models property", () => {
      const singleJson = JSON.stringify({
        name: "orders_model",
        tableName: "orders",
        dimensions: [
          { name: "status", sqlExpression: "orders.status", dataType: "string" },
        ],
        metrics: [
          {
            name: "total_revenue",
            title: "Total Revenue",
            sqlExpression: "amount",
            aggregation: "sum",
            filters: [{ field: "status", operator: "eq", value: "paid" }],
          },
        ],
      });

      const parsedSingle = parseSemanticModelsJson(singleJson);
      expect(parsedSingle).toHaveLength(1);
      expect(parsedSingle[0].tableName).toBe("orders");
      expect(parsedSingle[0].metrics?.[0].name).toBe("total_revenue");
      expect(parsedSingle[0].metrics?.[0].filters?.[0].field).toBe("status");

      const arrayJson = JSON.stringify([
        {
          model: "customers",
          table_name: "customers",
          dimensions: [{ name: "email" }],
          metrics: [{ name: "count", type: "count" }],
        },
      ]);
      const parsedArray = parseSemanticModelsJson(arrayJson);
      expect(parsedArray[0].name).toBe("customers");
      expect(parsedArray[0].dimensions?.[0].dataType).toBe("string");
      expect(parsedArray[0].metrics?.[0].aggregation).toBe("count");

      const wrappedJson = JSON.stringify({
        semantic_models: [
          {
            pk: "id",
            default_time_dimension: "created_at",
            dimensions: [{ name: "time", time_grains: ["day", "month"] }],
          },
        ],
      });
      const parsedWrapped = parseSemanticModelsJson(wrappedJson);
      expect(parsedWrapped[0].primaryKey).toBe("id");
      expect(parsedWrapped[0].defaultTimeDimension).toBe("created_at");
      expect(parsedWrapped[0].dimensions?.[0].timeGrains).toEqual(["day", "month"]);
    });
  });

  describe("attachSemanticModelsToTables", () => {
    it("attaches metrics and dimensions to schema tables matching exact or qualified name", () => {
      const tables: Record<string, TableMeta> = {
        "public.orders": {
          name: "public.orders",
          columns: [{ name: "id", data_type: "integer", is_nullable: false, is_primary: true }],
        },
        users: {
          name: "users",
          columns: [{ name: "id", data_type: "integer", is_nullable: false, is_primary: true }],
        },
      };

      const models: SemanticModel[] = [
        {
          name: "orders_model",
          tableName: "orders",
          metrics: [
            {
              name: "order_count",
              title: "Order Count",
              sqlExpression: "id",
              aggregation: "count",
            },
          ],
        },
        {
          name: "users_model",
          tableName: "users",
          dimensions: [
            {
              name: "full_name",
              title: "Full Name",
              sqlExpression: "first_name || ' ' || last_name",
            },
          ],
        },
      ];

      const attached = attachSemanticModelsToTables(tables, models);
      expect(attached["public.orders"].metrics).toHaveLength(1);
      expect(attached["public.orders"].metrics?.[0].name).toBe("order_count");
      expect(attached["users"].dimensions).toHaveLength(1);
      expect(attached["users"].dimensions?.[0].name).toBe("full_name");
    });
  });

  describe("compileVisualState with Semantic Metrics & Time Grains", () => {
    const schemaSnapshot: SchemaSnapshot = {
      tables: {
        orders: {
          name: "orders",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "amount", data_type: "decimal", is_nullable: false, is_primary: false },
            { name: "order_date", data_type: "timestamp", is_nullable: false, is_primary: false },
            { name: "status", data_type: "text", is_nullable: true, is_primary: false },
          ],
          metrics: [
            {
              name: "gross_sales",
              title: "Gross Sales",
              sqlExpression: "orders.amount",
              aggregation: "sum" as const,
              filters: [{ field: "orders.status", operator: "eq", value: "complete" }],
            },
          ],
        },
      },
    };

    it("compiles time grain projection and properly groups by truncated time", () => {
      const selectedColumns: Record<string, VisualColumnSelect> = {
        "orders.order_date": {
          table: "orders",
          name: "order_date",
          timeGrain: "month",
        },
        "orders.amount": {
          table: "orders",
          name: "amount",
          aggregate: "SUM",
        },
      };

      const result = compileVisualState(
        "orders",
        selectedColumns,
        ["orders.order_date", "orders.amount"],
        [],
        [],
        [],
        false,
        50,
        schemaSnapshot,
        "postgres"
      );

      expect(result.sql).toContain("DATE_TRUNC('month', \"orders\".\"order_date\") AS \"order_date_month\"");
      expect(result.sql).toContain("SUM(\"orders\".\"amount\") AS \"sum_amount\"");
      expect(result.sql).toContain("GROUP BY DATE_TRUNC('month', \"orders\".\"order_date\")");
      expect(result.spec.columns[0]).toEqual({
        column: "orders.order_date",
        time_grain: "month",
        alias: "order_date_month",
      });
    });

    it("compiles attached semantic metric projection with FILTER clause and excludes it from GROUP BY", () => {
      const selectedColumns: Record<string, VisualColumnSelect> = {
        "orders.status": {
          table: "orders",
          name: "status",
        },
        "orders.gross_sales": {
          table: "orders",
          name: "gross_sales",
          metric: true,
        },
      };

      const result = compileVisualState(
        "orders",
        selectedColumns,
        ["orders.status", "orders.gross_sales"],
        [],
        [],
        [],
        false,
        50,
        schemaSnapshot,
        "postgres"
      );

      expect(result.sql).toContain("SUM(orders.amount) FILTER (WHERE orders.status = 'complete') AS \"gross_sales\"");
      expect(result.sql).toContain("GROUP BY \"orders\".\"status\"");
      expect(result.sql).not.toContain("GROUP BY \"orders\".\"gross_sales\"");
    });

    it("disambiguates duplicate aliases in metrics and projections", () => {
      const selectedColumns: Record<string, VisualColumnSelect> = {
        col1: {
          table: "orders",
          name: "amount",
          alias: "sales",
          timeGrain: "day",
        },
        col2: {
          table: "orders",
          name: "amount",
          alias: "sales",
          timeGrain: "day",
        },
        col3: {
          table: "orders",
          name: "amount",
          alias: "sales",
          timeGrain: "day",
        },
      };

      const result = compileVisualState(
        "orders",
        selectedColumns,
        ["col1", "col2", "col3"],
        [],
        [],
        [],
        false,
        50,
        schemaSnapshot,
        "postgres"
      );

      expect(result.sql).toContain('"sales"');
      expect(result.sql).toContain('"sales_orders"');
      expect(result.sql).toContain('"sales_2"');
    });

    it("handles explicit MetricDefinition object passed in column select", () => {
      const explicitMetric: MetricDefinition = {
        name: "custom_kpi",
        title: "Custom KPI",
        sqlExpression: "orders.amount * 1.1",
        aggregation: "sum",
      };

      const selectedColumns: Record<string, VisualColumnSelect> = {
        kpi: {
          table: "orders",
          name: "kpi",
          metric: explicitMetric,
        },
      };

      const result = compileVisualState(
        "orders",
        selectedColumns,
        ["kpi"],
        [],
        [],
        [],
        false,
        50,
        null,
        "postgres"
      );

      expect(result.sql).toContain("SUM(orders.amount * 1.1) AS \"custom_kpi\"");
    });
  });

  describe("UI Component Integration: TableCard and QueryCanvas", () => {
    it("renders metrics section in TableCard and invokes onToggleColumn when clicked", () => {
      const mockToggle = vi.fn();
      const tableWithMetrics: TableMeta = {
        name: "orders",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        ],
        metrics: [
          {
            name: "total_revenue",
            title: "Total Revenue",
            sqlExpression: "amount",
            aggregation: "sum",
          },
        ],
      };

      const { container } = render(
        <TableCard
          table={tableWithMetrics}
          selectedColumns={{}}
          onToggleColumn={mockToggle}
        />
      );

      expect(screen.getByText(/Metrics \(1\)/i)).toBeInTheDocument();
      expect(screen.getByText("Total Revenue")).toBeInTheDocument();
      expect(screen.getByText("sum")).toBeInTheDocument();

      const metricRow = container.querySelector('[data-qb="table-card-metric-row"]') as HTMLElement;
      expect(metricRow).toBeTruthy();
      fireEvent.click(metricRow);
      expect(mockToggle).toHaveBeenCalledWith("total_revenue");
    });

    it("renders metric badge and time grain selector in QueryCanvas projection items", () => {
      const mockUpdate = vi.fn();
      const mockRemove = vi.fn();

      const selectedColumns: Record<string, VisualColumnSelect> = {
        "orders.created_at": {
          table: "orders",
          name: "created_at",
          timeGrain: "month",
        },
        "orders.m1": {
          table: "orders",
          name: "m1",
          metric: true,
        },
      };

      render(
        <QueryCanvas
          activeTables={[
            {
              name: "orders",
              columns: [{ name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false }],
            },
          ]}
          primaryTable="orders"
          selectedColumns={selectedColumns}
          orderedProjectionKeys={["orders.created_at", "orders.m1"]}
          joins={[]}
          filters={[]}
          sorts={[]}
          isDistinct={false}
          limit={50}
          onToggleColumn={vi.fn()}
          onRemoveTable={vi.fn()}
          onAddTableToCanvas={vi.fn()}
          onUpdateColumnSelect={mockUpdate}
          onRemoveColumnProjection={mockRemove}
          onJoinsChange={vi.fn()}
          onFiltersChange={vi.fn()}
          onSortsChange={vi.fn()}
          onDistinctChange={vi.fn()}
          onLimitChange={vi.fn()}
        />
      );

      expect(screen.getByText("Σ Metric")).toBeInTheDocument();

      const timeGrainSelect = screen.getByLabelText("Time grain for orders.created_at");
      expect(timeGrainSelect).toHaveValue("month");

      fireEvent.change(timeGrainSelect, { target: { value: "year" } });
      expect(mockUpdate).toHaveBeenCalledWith("orders.created_at", { timeGrain: "year" });
    });

    it("covers fallback defaults in expandMetricSql and parseSemanticModelsJson", () => {
      // Default dialect, empty sqlExpression, default aggregation
      const minimalMetric = {
        name: "test",
        title: "Test",
        sqlExpression: "",
        aggregation: invalid<MetricDefinition["aggregation"]>(undefined),
      };
      expect(expandMetricSql(minimalMetric, undefined)).toBe("SUM()");

      // JSON parsing with fallback snake_case fields and missing dimensions/metrics
      const json = JSON.stringify({
        name: "test_model",
        dimensions: undefined,
        metrics: [
          {
            name: "m1",
            filters: [
              {
                column: "col1",
                op: "eq",
                value: 123,
              },
            ],
          },
        ],
      });
      const parsed = parseSemanticModelsJson(json);
      expect(parsed[0].metrics?.[0].filters?.[0].field).toBe("col1");
      expect(formatMetricFilterSql({ field: "x", operator: invalid<string>(undefined), value: 5 })).toBe("x = 5");
      expect(formatMetricFilterSql({ field: "x", operator: "not_in", value: "a, b" })).toBe("x NOT IN (a, b)");
      expect(formatMetricFilterSql({ field: "x", operator: "not in", value: "a, b" })).toBe("x NOT IN (a, b)");
      expect(formatMetricFilterSql({ field: "x", operator: "not in", value: ["a", "b"] })).toBe("x NOT IN ('a', 'b')");
      expect(expandMetricSql(minimalMetric, "")).toBe("SUM()");
      expect(expandTimeGrainSql("", "month", "")).toBe("DATE_TRUNC('month', )");
    });
  });
});
