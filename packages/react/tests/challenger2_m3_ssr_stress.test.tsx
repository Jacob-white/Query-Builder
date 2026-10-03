// @vitest-environment node
import { describe, it, expect } from "vitest";
import React from "react";
import { renderToString } from "react-dom/server";
import {
  VisualQueryBuilder,
  QueryPlayground,
  QueryCanvas,
  TableCard,
  TableFiltersEditor,
  TableJoinEditor,
  TableSortsEditor,
  QueryResultsTable,
  QueryChartPreview,
  QueryTemplateManager,
  SchemaErdModal,
  compileVisualState,
  validateSqlSafety,
  specToState,
  stateToSpec,
  type SchemaSnapshot,
  type QuerySpec,
  type QueryResultData,
} from "../src";

const enterpriseSsrSchema: SchemaSnapshot = {
  tables: {
    organizations: {
      name: "organizations",
      columns: [
        { name: "id", data_type: "uuid", is_nullable: false, is_primary: true },
        { name: "name", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "status", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "uuid", is_nullable: false, is_primary: true },
        { name: "org_id", data_type: "uuid", is_nullable: false, is_primary: false },
        { name: "email", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "uuid", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "uuid", is_nullable: false, is_primary: false },
        { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
  },
  foreign_keys: [
    { table: "users", column: "org_id", foreign_table: "organizations", foreign_column: "id" },
    { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
  ],
};

const ssrMockResults: QueryResultData = {
  columns: ["id", "email", "total"],
  rows: [
    { id: "1", email: "alice@company.com", total: 100 },
    { id: "2", email: "bob@company.com", total: 250 },
    { id: "3", email: "carol@company.com", total: null },
  ],
  count: 3,
  latency_ms: 12,
};

const ssrSpec: QuerySpec = {
  table: "organizations",
  columns: ["organizations.id", "organizations.name", "orders.total"],
  joins: [
    {
      table: "users",
      type: "INNER JOIN",
      left_table: "organizations",
      left_col: "id",
      right_col: "org_id",
    },
    {
      table: "orders",
      type: "LEFT JOIN",
      left_table: "users",
      left_col: "id",
      right_col: "user_id",
    },
  ],
  filters: [
    { column: "status", op: "=", value: "active", tablePrefix: "organizations" },
    { column: "total", op: ">=", value: 50, tablePrefix: "orders" },
  ],
  order_by: [{ column: "orders.total", direction: "DESC" }],
  distinct: false,
  limit: 25,
};

describe("Milestone 3 DX SSR Hydration Safety & Stress Suite (Challenger 2)", () => {
  it("strictly enforces pure Node.js runtime with zero DOM globals", () => {
    expect(typeof window).toBe("undefined");
    expect(typeof document).toBe("undefined");
    expect(typeof HTMLElement).toBe("undefined");
  });

  it("verifies zero global state pollution across server-side rendering cycles", () => {
    const initialGlobalKeys = new Set(Object.keys(globalThis));

    // Render multiple instances of VisualQueryBuilder and QueryPlayground
    for (let i = 0; i < 20; i++) {
      renderToString(
        <VisualQueryBuilder
          schema={enterpriseSsrSchema}
          initialTable="organizations"
          initialLimit={25}
        />,
      );
      renderToString(
        <QueryPlayground
          schema={enterpriseSsrSchema}
          initialSpec={ssrSpec}
          dialect="postgres"
        />,
      );
    }

    const postGlobalKeys = new Set(Object.keys(globalThis));

    // Check that no new properties were injected onto globalThis
    const addedKeys = Array.from(postGlobalKeys).filter((k) => !initialGlobalKeys.has(k));
    expect(addedKeys).toEqual([]);
  });

  it("executes 500 repeated renderToString cycles without memory leakage or reference errors", () => {
    // Run garbage collection if available
    if (typeof (globalThis as any).gc === "function") {
      (globalThis as any).gc();
    }

    const initialHeap = process.memoryUsage().heapUsed;

    for (let i = 0; i < 500; i++) {
      const html1 = renderToString(
        <VisualQueryBuilder
          schema={enterpriseSsrSchema}
          initialTable="organizations"
          unstyled={i % 2 === 0}
        />,
      );
      expect(html1).toContain('data-qb="root"');
      expect(html1).toContain("organizations");

      const html2 = renderToString(
        <QueryPlayground
          schema={enterpriseSsrSchema}
          initialSpec={ssrSpec}
          unstyled={i % 2 === 1}
          dialect="snowflake"
        />,
      );
      expect(html2).toContain('data-qb="playground-root"');
    }

    if (typeof (globalThis as any).gc === "function") {
      (globalThis as any).gc();
    }

    const finalHeap = process.memoryUsage().heapUsed;
    const heapGrowthMb = (finalHeap - initialHeap) / (1024 * 1024);

    // Heap growth after 500 iterations should not exceed 60MB
    expect(heapGrowthMb).toBeLessThan(60);
  });

  it("renders all isolated child components in pure Node SSR without DOM global crashes", () => {
    const activeTables = Object.values(enterpriseSsrSchema.tables);

    // QueryCanvas
    const canvasHtml = renderToString(
      <QueryCanvas
        schema={enterpriseSsrSchema}
        activeTables={activeTables}
        primaryTable="organizations"
        selectedColumns={{ "organizations.name": { table: "organizations", name: "name" } }}
        orderedProjectionKeys={["organizations.name"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        onToggleColumn={() => {}}
        onRemoveTable={() => {}}
        onAddTableToCanvas={() => {}}
        onUpdateColumnSelect={() => {}}
        onRemoveColumnProjection={() => {}}
        onJoinsChange={() => {}}
        onFiltersChange={() => {}}
        onSortsChange={() => {}}
        onDistinctChange={() => {}}
        onLimitChange={() => {}}
      />,
    );
    expect(canvasHtml).toContain('data-qb="canvas"');

    // TableCard
    const cardHtml = renderToString(
      <TableCard
        table={enterpriseSsrSchema.tables.users}
        isSelected={true}
        selectedColumns={{ "users.email": { table: "users", name: "email" } }}
        onToggleColumn={() => {}}
        onRemoveTable={() => {}}
      />,
    );
    expect(cardHtml).toContain('data-qb="table-card"');
    expect(cardHtml).toContain("users");

    // TableFiltersEditor
    const filtersHtml = renderToString(
      <TableFiltersEditor
        filters={[{ id: "f1", combiner: "AND", tablePrefix: "users", column: "email", operator: "=", value: "test" }]}
        activeTables={activeTables}
        onChange={() => {}}
      />,
    );
    expect(filtersHtml).toContain('data-qb="filters-editor"');

    // TableJoinEditor
    const joinsHtml = renderToString(
      <TableJoinEditor
        joins={[{ id: "j1", table: "orders", type: "LEFT JOIN", left_table: "users", left_col: "id", right_col: "user_id" }]}
        activeTables={activeTables}
        allTables={activeTables}
        schema={enterpriseSsrSchema}
        onChange={() => {}}
      />,
    );
    expect(joinsHtml).toContain('data-qb="joins-editor"');

    // TableSortsEditor
    const sortsHtml = renderToString(
      <TableSortsEditor
        sorts={[{ id: "s1", tablePrefix: "orders", column: "total", direction: "DESC" }]}
        activeTables={activeTables}
        onChange={() => {}}
      />,
    );
    expect(sortsHtml).toContain('data-qb="sorts-editor"');

    // QueryResultsTable
    const resultsHtml = renderToString(
      <QueryResultsTable
        results={ssrMockResults}
        isLoading={false}
      />,
    );
    expect(resultsHtml).toContain('data-qb="results-table-root"');

    // QueryChartPreview
    const chartHtml = renderToString(
      <QueryChartPreview
        results={ssrMockResults}
      />,
    );
    expect(chartHtml).toContain('data-qb="chart-preview-root"');

    // QueryTemplateManager
    const templatesHtml = renderToString(
      <QueryTemplateManager
        isOpen={true}
        onClose={() => {}}
        onLoadTemplate={() => {}}
      />,
    );
    expect(templatesHtml).toContain('data-qb="template-manager-modal"');

    // SchemaErdModal
    const erdHtml = renderToString(
      <SchemaErdModal
        isOpen={true}
        onClose={() => {}}
        schema={enterpriseSsrSchema}
      />,
    );
    expect(erdHtml).toContain('aria-labelledby="schema-erd-title"');
  });

  it("simulates 50 concurrent server-side render requests via Promise.all", async () => {
    const renderTasks = Array.from({ length: 50 }, (_, idx) => {
      return new Promise<string>((resolve) => {
        setImmediate(() => {
          const spec: QuerySpec = {
            ...ssrSpec,
            limit: 10 + idx,
          };
          const html = renderToString(
            <QueryPlayground
              schema={enterpriseSsrSchema}
              initialSpec={spec}
              dialect={idx % 2 === 0 ? "postgres" : "bigquery"}
            />,
          );
          resolve(html);
        });
      });
    });

    const results = await Promise.all(renderTasks);
    expect(results).toHaveLength(50);
    results.forEach((html) => {
      expect(html).toContain('data-qb="playground-root"');
      expect(html).toContain("organizations");
    });
  });
});
