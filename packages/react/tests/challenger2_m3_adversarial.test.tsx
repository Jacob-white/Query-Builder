import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { invalid } from "./helpers";
import { render, screen, fireEvent, act, renderHook } from "@testing-library/react";
import {
  useQueryBuilder,
  useQueryState,
  useSqlCompiler,
  stateToSpec,
  specToState,
  compileVisualState,
  MAX_HISTORY_LENGTH,
  normalizeSchema,
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
  type DatabaseSchemaDefinition,
  type SchemaSnapshot,
  type QuerySpec,
  type QueryState,
  type QueryResultData,
  type SqlDialect,
  type VisualJoin,
  type VisualFilter,
  type VisualSort,
  type VisualColumnSelect,
} from "../src";

const enterpriseSchema: SchemaSnapshot = {
  tables: {
    organizations: {
      name: "organizations",
      columns: [
        { name: "id", data_type: "uuid", is_nullable: false, is_primary: true },
        { name: "name", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "status", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
      ],
    },
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "uuid", is_nullable: false, is_primary: true },
        { name: "org_id", data_type: "uuid", is_nullable: false, is_primary: false },
        { name: "email", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "role", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "deleted_at", data_type: "timestamp", is_nullable: true, is_primary: false },
      ],
    },
    employees: {
      name: "employees",
      columns: [
        { name: "id", data_type: "int", is_nullable: false, is_primary: true },
        { name: "manager_id", data_type: "int", is_nullable: true, is_primary: false },
        { name: "name", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "salary", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "uuid", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "uuid", is_nullable: false, is_primary: false },
        { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
        { name: "status", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "placed_at", data_type: "timestamp", is_nullable: false, is_primary: false },
      ],
    },
    order_items: {
      name: "order_items",
      columns: [
        { name: "id", data_type: "uuid", is_nullable: false, is_primary: true },
        { name: "order_id", data_type: "uuid", is_nullable: false, is_primary: false },
        { name: "product_id", data_type: "uuid", is_nullable: false, is_primary: false },
        { name: "quantity", data_type: "int", is_nullable: false, is_primary: false },
        { name: "unit_price", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
    products: {
      name: "products",
      columns: [
        { name: "id", data_type: "uuid", is_nullable: false, is_primary: true },
        { name: "category_id", data_type: "uuid", is_nullable: false, is_primary: false },
        { name: "name", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "price", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
    categories: {
      name: "categories",
      columns: [
        { name: "id", data_type: "uuid", is_nullable: false, is_primary: true },
        { name: "parent_id", data_type: "uuid", is_nullable: true, is_primary: false },
        { name: "title", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
  },
  foreign_keys: [
    { table: "users", column: "org_id", foreign_table: "organizations", foreign_column: "id" },
    { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
    { table: "order_items", column: "order_id", foreign_table: "orders", foreign_column: "id" },
    { table: "order_items", column: "product_id", foreign_table: "products", foreign_column: "id" },
    { table: "products", column: "category_id", foreign_table: "categories", foreign_column: "id" },
    { table: "employees", column: "manager_id", foreign_table: "employees", foreign_column: "id" },
    { table: "categories", column: "parent_id", foreign_table: "categories", foreign_column: "id" },
  ],
};

const mockQueryResults: QueryResultData = {
  columns: ["id", "name", "total", "status"],
  rows: [
    { id: "u-1", name: "Alice", total: 420.5, status: "completed" },
    { id: "u-2", name: "Bob", total: 105.0, status: "pending" },
    { id: "u-3", name: "Charlie", total: null, status: "failed" },
  ],
  count: 3,
  latency_ms: 18,
};

const complexPlaygroundSpec: QuerySpec = {
  table: "customers",
  columns: [
    "customers.id",
    "customers.email",
    { column: "orders.total", agg: "sum", alias: "total_revenue" },
  ],
  joins: [
    {
      table: "orders",
      type: "INNER JOIN",
      left_table: "customers",
      left_col: "id",
      right_col: "customer_id",
    },
  ],
  filters: [
    { column: "status", op: "=", value: "active", tablePrefix: "customers" },
    { column: "total", op: ">=", value: 100, tablePrefix: "orders" },
  ],
  order_by: [{ column: "orders.total", direction: "DESC" }],
  filter_join: "AND",
  distinct: true,
  limit: 25,
};

describe("Milestone 3 DX Adversarial Challenge Suite 2 (Challenger 2)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // =========================================================================
  // 1. Highly Complex Query State Topologies
  // =========================================================================
  describe("1. Highly Complex Query State Topologies", () => {
    it("compiles multi-branch join tree spanning 6 tables with mixed join types", () => {
      const selectedColumns: Record<string, VisualColumnSelect> = {
        "organizations.name": { table: "organizations", name: "name", alias: "org_name" },
        "users.email": { table: "users", name: "email" },
        "orders.total": { table: "orders", name: "total", aggregate: "SUM", alias: "gross_sales" },
        "order_items.quantity": { table: "order_items", name: "quantity", aggregate: "COUNT", alias: "items_count" },
        "products.name": { table: "products", name: "name" },
        "categories.title": { table: "categories", name: "title" },
      };

      const joins: VisualJoin[] = [
        {
          id: "j1",
          table: "users",
          type: "INNER JOIN",
          left_table: "organizations",
          left_col: "id",
          right_col: "org_id",
        },
        {
          id: "j2",
          table: "orders",
          type: "LEFT JOIN",
          left_table: "users",
          left_col: "id",
          right_col: "user_id",
        },
        {
          id: "j3",
          table: "order_items",
          type: "LEFT JOIN",
          left_table: "orders",
          left_col: "id",
          right_col: "order_id",
        },
        {
          id: "j4",
          table: "products",
          type: "INNER JOIN",
          left_table: "order_items",
          left_col: "product_id",
          right_col: "id",
        },
        {
          id: "j5",
          table: "categories",
          type: "RIGHT JOIN",
          left_table: "products",
          left_col: "category_id",
          right_col: "id",
        },
      ];

      const filters: VisualFilter[] = [
        { id: "f1", combiner: "AND", tablePrefix: "organizations", column: "status", operator: "!=", value: "archived" },
        { id: "f2", combiner: "AND", tablePrefix: "users", column: "deleted_at", operator: "IS NULL", value: "" },
        { id: "f3", combiner: "AND", tablePrefix: "orders", column: "total", operator: ">=", value: 50 },
        { id: "f4", combiner: "AND", tablePrefix: "products", column: "name", operator: "CONTAINS", value: "Pro" },
        { id: "f5", combiner: "AND", tablePrefix: "categories", column: "title", operator: "NOT IN", value: "Spam, Junk, Test" },
      ];

      const sorts: VisualSort[] = [
        { id: "s1", tablePrefix: "organizations", column: "name", direction: "ASC" },
        { id: "s2", tablePrefix: "orders", column: "total", direction: "DESC" },
        { id: "s3", tablePrefix: "categories", column: "title", direction: "ASC" },
      ];

      const projectionKeys = Object.keys(selectedColumns);

      const compiled = compileVisualState(
        "organizations",
        selectedColumns,
        projectionKeys,
        joins,
        filters,
        sorts,
        false,
        100,
        enterpriseSchema,
        "postgres",
      );

      expect(compiled.sql).toContain('FROM "organizations"');
      expect(compiled.sql).toContain('INNER JOIN "users" ON "organizations"."id" = "users"."org_id"');
      expect(compiled.sql).toContain('LEFT JOIN "orders" ON "users"."id" = "orders"."user_id"');
      expect(compiled.sql).toContain('LEFT JOIN "order_items" ON "orders"."id" = "order_items"."order_id"');
      expect(compiled.sql).toContain('INNER JOIN "products" ON "order_items"."product_id" = "products"."id"');
      expect(compiled.sql).toContain('RIGHT JOIN "categories" ON "products"."category_id" = "categories"."id"');
      expect(compiled.sql).toContain('WHERE "organizations"."status" != \'archived\'');
      expect(compiled.sql).toContain('"users"."deleted_at" IS NULL');
      expect(compiled.sql).toContain('"orders"."total" >= 50');
      expect(compiled.sql).toContain('"products"."name" ILIKE \'%Pro%\'');
      expect(compiled.sql).toContain('"categories"."title" NOT IN (\'Spam\', \'Junk\', \'Test\')');
      expect(compiled.sql).toContain('GROUP BY "organizations"."name", "users"."email", "products"."name", "categories"."title"');
      expect(compiled.sql).toContain('ORDER BY "organizations"."name" ASC, "orders"."total" DESC, "categories"."title" ASC');
      expect(compiled.sql).toContain("LIMIT 100;");

      expect(compiled.spec.joins).toHaveLength(5);
      expect(compiled.spec.filters).toHaveLength(5);
      expect(compiled.spec.order_by).toHaveLength(3);
    });

    it("compiles self-referential join topology correctly", () => {
      const selectedColumns: Record<string, VisualColumnSelect> = {
        "employees.id": { table: "employees", name: "id" },
        "employees.name": { table: "employees", name: "name", alias: "emp_name" },
        "employees.salary": { table: "employees", name: "salary" },
      };

      const joins: VisualJoin[] = [
        {
          id: "j_self",
          table: "employees",
          type: "LEFT JOIN",
          left_table: "employees",
          left_col: "manager_id",
          right_col: "id",
        },
      ];

      const filters: VisualFilter[] = [
        {
          id: "f_mgr",
          combiner: "AND",
          tablePrefix: "employees",
          column: "manager_id",
          operator: "IS NOT NULL",
          value: "",
        },
      ];

      const compiled = compileVisualState(
        "employees",
        selectedColumns,
        Object.keys(selectedColumns),
        joins,
        filters,
        [],
        false,
        25,
        enterpriseSchema,
        "postgres",
      );

      expect(compiled.sql).toContain('FROM "employees"');
      expect(compiled.sql).toContain('LEFT JOIN "employees" ON "employees"."manager_id" = "employees"."id"');
      expect(compiled.sql).toContain('"employees"."manager_id" IS NOT NULL');
      expect(compiled.spec.joins[0].table).toBe("employees");
      expect(compiled.spec.joins[0].left_table).toBe("employees");
    });

    it("handles compound negation and boundary filter combinations", () => {
      const filters: VisualFilter[] = [
        { id: "f1", combiner: "AND", tablePrefix: "users", column: "email", operator: "!=", value: "admin@corp.com" },
        { id: "f2", combiner: "AND", tablePrefix: "users", column: "role", operator: "NOT IN", value: "guest, anonymous, banned" },
        { id: "f3", combiner: "AND", tablePrefix: "users", column: "deleted_at", operator: "IS NOT NULL", value: "" },
        { id: "f4", combiner: "AND", tablePrefix: "orders", column: "total", operator: "BETWEEN", value: "100 AND 500" },
        { id: "f5", combiner: "AND", tablePrefix: "orders", column: "status", operator: "LIKE", value: "%_pending" },
      ];

      const compiled = compileVisualState(
        "users",
        {},
        [],
        [],
        filters,
        [],
        false,
        50,
        null,
        "postgres",
      );

      expect(compiled.sql).toContain('"users"."email" != \'admin@corp.com\'');
      expect(compiled.sql).toContain('"users"."role" NOT IN (\'guest\', \'anonymous\', \'banned\')');
      expect(compiled.sql).toContain('"users"."deleted_at" IS NOT NULL');
      expect(compiled.sql).toContain('"orders"."total" BETWEEN 100 AND 500');
      expect(compiled.sql).toContain('"orders"."status" LIKE \'%_pending\'');
    });

    it("verifies lossless round-trip stateToSpec -> specToState -> stateToSpec", () => {
      const initialSpec: QuerySpec = {
        table: "orders",
        columns: [
          "orders.id",
          { column: "orders.total", agg: "sum", alias: "sum_total" },
          "users.email",
        ],
        joins: [
          {
            table: "users",
            type: "LEFT JOIN",
            left_table: "orders",
            left_col: "user_id",
            right_col: "id",
          },
        ],
        filters: [
          { column: "status", op: "=", value: "completed", tablePrefix: "orders" },
          { column: "total", op: ">=", value: 100, tablePrefix: "orders" },
        ],
        order_by: [
          { column: "orders.total", direction: "DESC" },
          { column: "orders.placed_at", direction: "ASC" },
        ],
        filter_join: "AND",
        distinct: true,
        limit: 75,
      };

      const state = specToState(initialSpec);
      expect(state.primaryTable).toBe("orders");
      expect(state.isDistinct).toBe(true);
      expect(state.limit).toBe(75);
      expect(state.joins).toHaveLength(1);
      expect(state.filters).toHaveLength(2);
      expect(state.sorts).toHaveLength(2);

      const reserializedSpec = stateToSpec(state as QueryState);
      expect(reserializedSpec.table).toBe("orders");
      expect(reserializedSpec.distinct).toBe(true);
      expect(reserializedSpec.limit).toBe(75);
      expect(reserializedSpec.joins).toHaveLength(1);
      expect(reserializedSpec.joins![0].table).toBe("users");
      expect(reserializedSpec.filters).toHaveLength(2);
      expect(reserializedSpec.order_by).toHaveLength(2);
    });

    it("stress tests useQueryState history capping at MAX_HISTORY_LENGTH (50) and undo/redo recursion", () => {
      const { result } = renderHook(() => useQueryState({ table: "orders", limit: 10 }));

      // Perform 60 mutations
      act(() => {
        for (let i = 1; i <= 60; i++) {
          result.current.actions.setLimit(10 + i);
        }
      });

      expect(result.current.state.limit).toBe(70);
      expect(result.current.history.past.length).toBeLessThanOrEqual(MAX_HISTORY_LENGTH);
      expect(result.current.history.past.length).toBe(MAX_HISTORY_LENGTH);
      expect(result.current.history.canUndo).toBe(true);
      expect(result.current.history.canRedo).toBe(false);

      // Perform 50 consecutive undos
      act(() => {
        for (let i = 0; i < 50; i++) {
          result.current.actions.undo();
        }
      });

      expect(result.current.history.canUndo).toBe(false);
      expect(result.current.history.canRedo).toBe(true);
      expect(result.current.history.future.length).toBe(MAX_HISTORY_LENGTH);

      // Perform 50 consecutive redos
      act(() => {
        for (let i = 0; i < 50; i++) {
          result.current.actions.redo();
        }
      });

      expect(result.current.state.limit).toBe(70);
      expect(result.current.history.canUndo).toBe(true);
      expect(result.current.history.canRedo).toBe(false);
    });
  });

  // =========================================================================
  // 2. Unstyled Mode Across Nested Component Hierarchies
  // =========================================================================
  describe("2. Unstyled Mode Across Nested Component Hierarchies", () => {
    it("renders VisualQueryBuilder with unstyled={true} completely omitting inline styles while preserving data-qb attributes", () => {
      const { container } = render(
        <VisualQueryBuilder
          schema={enterpriseSchema}
          initialTable="users"
          unstyled={true}
        />,
      );

      const root = container.querySelector('[data-qb="root"]');
      expect(root).not.toBeNull();
      expect(root?.getAttribute("data-qb-unstyled")).toBe("true");

      // Verify essential semantic data-qb attributes are present
      const expectedAttributes = [
        "top-bar",
        "tab-list",
        "canvas",
        "canvas-tables",
        "table-card",
        "filters-editor",
        "joins-editor",
        "sorts-editor",
      ];

      for (const attr of expectedAttributes) {
        const el = container.querySelector(`[data-qb="${attr}"]`);
        expect(el, `Expected element with data-qb="${attr}"`).not.toBeNull();
      }

      // Query all elements rendered inside the component
      const allElements = container.querySelectorAll("*");
      expect(allElements.length).toBeGreaterThan(20);

      // Verify that every single element has either no style attribute or null style
      allElements.forEach((el) => {
        const styleAttr = el.getAttribute("style");
        expect(
          styleAttr === null || styleAttr === "",
          `Element <${el.tagName.toLowerCase()} data-qb="${el.getAttribute("data-qb") || "none"}"> should not have inline styles, but got: "${styleAttr}"`,
        ).toBe(true);
      });
    });

    it("verifies unstyled mode in VisualQueryBuilder and child components across views", () => {
      const { container } = render(
        <VisualQueryBuilder
          schema={enterpriseSchema}
          initialTable="users"
          unstyled={true}
        />,
      );

      // Switch to SQL Code Editor tab
      const sqlTab = container.querySelector('[data-qb="tab"][data-qb-tab="sql"]');
      expect(sqlTab).not.toBeNull();
      fireEvent.click(sqlTab!);

      const sqlEditor = container.querySelector('[data-qb="sql-editor"]');
      expect(sqlEditor).not.toBeNull();
      expect(sqlEditor?.getAttribute("style")).toBeNull();

      // Render QueryResultsTable directly in unstyled mode with mock data
      const { container: resultsContainer } = render(
        <QueryResultsTable results={mockQueryResults} unstyled={true} />,
      );

      const resultsRoot = resultsContainer.querySelector('[data-qb="results-table-root"]');
      expect(resultsRoot).not.toBeNull();
      expect(resultsRoot?.getAttribute("style")).toBeNull();

      const resultsTable = resultsContainer.querySelector('[data-qb="results-table"]');
      expect(resultsTable).not.toBeNull();
      expect(resultsTable?.getAttribute("style")).toBeNull();

      // Render QueryChartPreview directly in unstyled mode
      const { container: chartContainer } = render(
        <QueryChartPreview results={mockQueryResults} unstyled={true} />,
      );

      const chartPreview = chartContainer.querySelector('[data-qb="chart-preview-root"]');
      expect(chartPreview).not.toBeNull();
      expect(chartPreview?.getAttribute("style")).toBeNull();
    });

    it("renders QueryPlayground with unstyled={true} completely omitting inline styles across all tabs", () => {
      const { container } = render(
        <QueryPlayground
          schema={enterpriseSchema}
          initialTable="users"
          unstyled={true}
        />,
      );

      const root = container.querySelector('[data-qb="playground-root"]');
      expect(root).not.toBeNull();
      expect(root?.getAttribute("data-qb-unstyled")).toBe("true");

      // Verify all elements in Builder tab have no inline styles
      let allElements = container.querySelectorAll("*");
      allElements.forEach((el) => {
        const styleAttr = el.getAttribute("style");
        expect(
          styleAttr === null || styleAttr === "",
          `Element <${el.tagName.toLowerCase()} data-qb="${el.getAttribute("data-qb") || "none"}"> should not have inline styles in builder tab, got: "${styleAttr}"`,
        ).toBe(true);
      });

      // Switch to JSON subtab
      const jsonSubtab = container.querySelector('[data-qb="builder-subtab-json"]');
      expect(jsonSubtab).not.toBeNull();
      fireEvent.click(jsonSubtab!);

      const jsonTextarea = container.querySelector('[data-qb="playground-json-textarea"]');
      expect(jsonTextarea).not.toBeNull();
      expect(jsonTextarea?.getAttribute("style")).toBeNull();

      // Switch to AST Visualizer tab
      const astTab = container.querySelector('[data-qb="playground-tab-ast"]');
      expect(astTab).not.toBeNull();
      fireEvent.click(astTab!);

      const astVisualizer = container.querySelector('[data-qb="playground-ast-visualizer"]');
      expect(astVisualizer).not.toBeNull();
      expect(astVisualizer?.getAttribute("style")).toBeNull();

      const astClauses = [
        "ast-clause-from",
        "ast-clause-select",
        "ast-clause-joins",
        "ast-clause-where",
        "ast-clause-orderby",
        "ast-clause-limits",
      ];
      for (const clause of astClauses) {
        const el = container.querySelector(`[data-qb="${clause}"]`);
        expect(el).not.toBeNull();
        expect(el?.getAttribute("style")).toBeNull();
      }

      // Switch to Codegen tab
      const codegenTab = container.querySelector('[data-qb="playground-tab-codegen"]');
      expect(codegenTab).not.toBeNull();
      fireEvent.click(codegenTab!);

      const codegenRoot = container.querySelector('[data-qb="playground-codegen"]');
      expect(codegenRoot).not.toBeNull();
      expect(codegenRoot?.getAttribute("style")).toBeNull();

      const snippetBlock = container.querySelector('[data-qb="playground-code-snippet"]');
      expect(snippetBlock).not.toBeNull();
      expect(snippetBlock?.getAttribute("style")).toBeNull();

      // Switch codegen subtabs: SQL, AST
      const sqlCodegenTab = container.querySelector('[data-qb="codegen-tab-sql"]');
      expect(sqlCodegenTab).not.toBeNull();
      fireEvent.click(sqlCodegenTab!);
      expect(snippetBlock?.getAttribute("style")).toBeNull();

      const astCodegenTab = container.querySelector('[data-qb="codegen-tab-json"]');
      expect(astCodegenTab).not.toBeNull();
      fireEvent.click(astCodegenTab!);
      expect(snippetBlock?.getAttribute("style")).toBeNull();
    });

    it("contrasts with styled mode (unstyled={false}) confirming styles are applied when not unstyled", () => {
      const { container: styledContainer } = render(
        <VisualQueryBuilder
          schema={enterpriseSchema}
          initialTable="users"
          unstyled={false}
        />,
      );

      const styledRoot = styledContainer.querySelector('[data-qb="root"]');
      expect(styledRoot).not.toBeNull();
      expect(styledRoot?.getAttribute("data-qb-unstyled")).toBeNull();
      // Should have inline style
      expect(styledRoot?.getAttribute("style")).not.toBeNull();
      expect(styledRoot?.getAttribute("style")).toContain("display");
    });
  });

  // =========================================================================
  // 3. QueryPlayground Code Generation Snippet Fidelity Across All Dialects
  // =========================================================================
  describe("3. QueryPlayground Code Generation Snippet Fidelity Across All Dialects", () => {

    it("verifies TypeScript SDK snippet generation fidelity", () => {
      const { container } = render(
        <QueryPlayground
          initialSpec={complexPlaygroundSpec}
          schema={enterpriseSchema}
        />,
      );

      // Switch to codegen tab
      const codegenTab = container.querySelector('[data-qb="playground-tab-codegen"]');
      expect(codegenTab).not.toBeNull();
      fireEvent.click(codegenTab!);

      // Default subtab is TypeScript SDK
      const snippetCode = container.querySelector('[data-qb="playground-code-snippet"] code');
      expect(snippetCode).not.toBeNull();
      const text = snippetCode?.textContent || "";

      expect(text).toContain('import { createQuery, createQueryBuilderClient } from "@jacob-white/query-builder-react/client";');
      expect(text).toContain('.from("customers")');
      expect(text).toContain('.select(["customers.id","customers.email","orders.total AS total_revenue"])');
      expect(text).toContain('.join("orders", "id", "=", "customer_id")');
      expect(text).toContain('.where("status", "=", "active")');
      expect(text).toContain('.where("total", ">=", 100)');
      expect(text).toContain('.orderBy("orders.total", "DESC")');
      expect(text).toContain('.distinct()');
      expect(text).toContain('.limit(25)');
      expect(text).toContain("const result = await client.execute(query.toSpec());");
    });

    it("verifies compiled SQL with distinct dialect quoting across PostgreSQL, MySQL, SQLite, Snowflake, BigQuery, DuckDB, MSSQL", () => {
      const dialects: SqlDialect[] = [
        "postgres",
        "mysql",
        "sqlite",
        "snowflake",
        "bigquery",
        "duckdb",
        "mssql",
      ];

      for (const d of dialects) {
        const { container } = render(
          <QueryPlayground
            initialSpec={complexPlaygroundSpec}
            dialect={d}
          />,
        );

        // Click codegen tab
        const codegenTab = container.querySelector('[data-qb="playground-tab-codegen"]');
        expect(codegenTab).not.toBeNull();
        fireEvent.click(codegenTab!);

        // Click SQL subtab
        const sqlTab = container.querySelector('[data-qb="codegen-tab-sql"]');
        expect(sqlTab).not.toBeNull();
        fireEvent.click(sqlTab!);

        const snippetCode = container.querySelector('[data-qb="playground-code-snippet"] code');
        expect(snippetCode).not.toBeNull();
        const sqlText = snippetCode?.textContent || "";

        if (d === "postgres") {
          expect(sqlText).toContain('FROM "customers"');
          expect(sqlText).toContain('INNER JOIN "orders" ON "customers"."id" = "orders"."customer_id"');
          expect(sqlText).toContain('SUM("orders"."total") AS "total_revenue"');
          expect(sqlText).toContain("LIMIT 25;");
        } else if (d === "mysql") {
          expect(sqlText).toContain("FROM `customers`");
          expect(sqlText).toContain("INNER JOIN `orders` ON `customers`.`id` = `orders`.`customer_id`");
          expect(sqlText).toContain("SUM(`orders`.`total`) AS `total_revenue`");
          expect(sqlText).toContain("LIMIT 25;");
        } else if (d === "sqlite") {
          expect(sqlText).toContain('FROM "customers"');
          expect(sqlText).toContain('INNER JOIN "orders" ON "customers"."id" = "orders"."customer_id"');
          expect(sqlText).toContain("LIMIT 25;");
        } else if (d === "snowflake") {
          expect(sqlText).toContain('FROM "customers"');
          expect(sqlText).toContain('INNER JOIN "orders" ON "customers"."id" = "orders"."customer_id"');
          expect(sqlText).toContain("LIMIT 25;");
        } else if (d === "bigquery") {
          expect(sqlText).toContain("FROM `customers`");
          expect(sqlText).toContain("INNER JOIN `orders` ON `customers`.`id` = `orders`.`customer_id`");
          expect(sqlText).toContain("LIMIT 25;");
        } else if (d === "duckdb") {
          expect(sqlText).toContain('FROM "customers"');
          expect(sqlText).toContain('INNER JOIN "orders" ON "customers"."id" = "orders"."customer_id"');
          expect(sqlText).toContain("LIMIT 25;");
        } else if (d === "mssql") {
          expect(sqlText).toContain("FROM [customers]");
          expect(sqlText).toContain("INNER JOIN [orders] ON [customers].[id] = [orders].[customer_id]");
          expect(sqlText).toContain("SUM([orders].[total]) AS [total_revenue]");
          expect(sqlText).toContain("OFFSET 0 ROWS FETCH NEXT 25 ROWS ONLY;");
        }
      }
    });

    it("verifies live interactive dialect switching in QueryPlayground dropdown", () => {
      const { container } = render(
        <QueryPlayground
          initialSpec={complexPlaygroundSpec}
          dialect="postgres"
        />,
      );

      // Codegen tab
      fireEvent.click(container.querySelector('[data-qb="playground-tab-codegen"]')!);
      // SQL tab
      fireEvent.click(container.querySelector('[data-qb="codegen-tab-sql"]')!);

      const dialectSelect = container.querySelector<HTMLSelectElement>('[data-qb="playground-dialect-select"]');
      expect(dialectSelect).not.toBeNull();
      expect(dialectSelect?.value).toBe("postgres");

      // Verify PostgreSQL quotes initially
      let snippetCode = container.querySelector('[data-qb="playground-code-snippet"] code');
      expect(snippetCode?.textContent).toContain('FROM "customers"');

      // Switch to MySQL
      fireEvent.change(dialectSelect!, { target: { value: "mysql" } });
      snippetCode = container.querySelector('[data-qb="playground-code-snippet"] code');
      expect(snippetCode?.textContent).toContain("FROM `customers`");

      // Switch to BigQuery
      fireEvent.change(dialectSelect!, { target: { value: "bigquery" } });
      snippetCode = container.querySelector('[data-qb="playground-code-snippet"] code');
      expect(snippetCode?.textContent).toContain("FROM `customers`");

      // Switch to SQLite
      fireEvent.change(dialectSelect!, { target: { value: "sqlite" } });
      snippetCode = container.querySelector('[data-qb="playground-code-snippet"] code');
      expect(snippetCode?.textContent).toContain('FROM "customers"');
    });

    it("verifies bi-directional JSON AST synchronization and error recovery", () => {
      const onSpecChange = vi.fn();
      const onSqlChange = vi.fn();

      const { container } = render(
        <QueryPlayground
          initialSpec={complexPlaygroundSpec}
          onSpecChange={onSpecChange}
          onSqlChange={onSqlChange}
        />,
      );

      // Switch to JSON editor
      fireEvent.click(container.querySelector('[data-qb="builder-subtab-json"]')!);

      let textarea = container.querySelector<HTMLTextAreaElement>('[data-qb="playground-json-textarea"]');
      expect(textarea).not.toBeNull();
      expect(textarea?.value).toContain('"customers"');

      // Edit JSON spec with valid modifications
      const updatedSpec = {
        ...complexPlaygroundSpec,
        table: "organizations",
        limit: 120,
      };

      fireEvent.change(textarea!, { target: { value: JSON.stringify(updatedSpec, null, 2) } });

      // Verify callbacks
      expect(onSpecChange).toHaveBeenCalledWith(expect.objectContaining({ table: "organizations", limit: 120 }));

      // Switch to AST tab to check live sync
      fireEvent.click(container.querySelector('[data-qb="playground-tab-ast"]')!);
      const fromClause = container.querySelector('[data-qb="ast-clause-from"]');
      expect(fromClause?.textContent).toContain("organizations");

      const limitsClause = container.querySelector('[data-qb="ast-clause-limits"]');
      expect(limitsClause?.textContent).toContain("120");

      // Switch back to builder tab
      fireEvent.click(container.querySelector('[data-qb="playground-tab-builder"]')!);
      // Re-query newly mounted textarea
      textarea = container.querySelector<HTMLTextAreaElement>('[data-qb="playground-json-textarea"]');
      expect(textarea).not.toBeNull();

      fireEvent.change(textarea!, { target: { value: "{ malformed: json, syntax-error" } });

      const errorAlert = container.querySelector('[data-qb="playground-json-error"]');
      expect(errorAlert).not.toBeNull();
      expect(errorAlert?.textContent).toContain("Syntax Error:");

      // Recover by providing valid JSON again
      fireEvent.change(textarea!, { target: { value: JSON.stringify({ table: "products", limit: 10 }) } });
      expect(container.querySelector('[data-qb="playground-json-error"]')).toBeNull();
    });

    it("handles clipboard copying with fallback without throwing", async () => {
      vi.useFakeTimers();

      const writeTextMock = vi.fn().mockResolvedValue(undefined);
      Object.assign(navigator, {
        clipboard: {
          writeText: writeTextMock,
        },
      });

      const { container } = render(
        <QueryPlayground initialSpec={complexPlaygroundSpec} />,
      );

      fireEvent.click(container.querySelector('[data-qb="playground-tab-codegen"]')!);

      const copyBtn = container.querySelector<HTMLButtonElement>('[data-qb="playground-copy-btn"]');
      expect(copyBtn).not.toBeNull();
      expect(copyBtn?.textContent).toContain("📋 Copy Snippet");

      await act(async () => {
        fireEvent.click(copyBtn!);
      });

      expect(writeTextMock).toHaveBeenCalled();
      expect(copyBtn?.textContent).toContain("✓ Copied!");

      // Advance timers to test revert
      act(() => {
        vi.advanceTimersByTime(2500);
      });

      expect(copyBtn?.textContent).toContain("📋 Copy Snippet");
    });
  });

  // =========================================================================
  // 4. Deep Branch Coverage Hardening & Edge Cases
  // =========================================================================
  describe("4. Deep Branch Coverage Hardening & Edge Cases", () => {
    it("renders AST clause views with active filters and order_by mappings", () => {
      // Styled mode
      const { container } = render(
        <QueryPlayground initialSpec={complexPlaygroundSpec} />,
      );

      fireEvent.click(container.querySelector('[data-qb="playground-tab-ast"]')!);

      const whereClause = container.querySelector('[data-qb="ast-clause-where"]');
      expect(whereClause).not.toBeNull();
      expect(whereClause?.textContent).toContain("status");
      expect(whereClause?.textContent).toContain("active");
      expect(whereClause?.textContent).toContain("total");
      expect(whereClause?.textContent).toContain("100");

      const orderClause = container.querySelector('[data-qb="ast-clause-orderby"]');
      expect(orderClause).not.toBeNull();
      expect(orderClause?.textContent).toContain("orders.total");
      expect(orderClause?.textContent).toContain("DESC");

      // Unstyled mode
      const { container: unstyledContainer } = render(
        <QueryPlayground initialSpec={complexPlaygroundSpec} unstyled={true} />,
      );
      fireEvent.click(unstyledContainer.querySelector('[data-qb="playground-tab-ast"]')!);
      const unstyledWhere = unstyledContainer.querySelector('[data-qb="ast-clause-where"]');
      expect(unstyledWhere?.textContent).toContain("status");
    });

    it("covers specToState and useQueryState fallback branches", () => {
      const stateWithDefaults = specToState({
        filters: [{ column: "test", op: "=", value: undefined }],
        order_by: [{ column: "", direction: invalid<"ASC" | "DESC">(undefined) }],
      });

      expect(stateWithDefaults.filters?.[0].value).toBe("");
      expect(stateWithDefaults.sorts?.[0].column).toBe("");
      expect(stateWithDefaults.sorts?.[0].direction).toBe("ASC");

      const stateWithMissingIds = specToState({
        joins: [{ table: "orders" }],
        filters: [{ column: "status", value: "active" }],
        order_by: [{ column: "created_at" }],
      });
      expect(stateWithMissingIds.joins?.[0].id).toBe("join_1");
      expect(stateWithMissingIds.filters?.[0].id).toBe("filter_1");
      expect(stateWithMissingIds.sorts?.[0].id).toBe("sort_1");

      const { result: stateHook } = renderHook(() => useQueryState({}));
      expect(stateHook.current.state.activeTables).toEqual([]);
    });

    it("covers useSqlCompiler error recovery and non-numeric limit fallbacks", () => {
      const explosiveObject = {
        get primaryTable(): string {
          throw new Error("Deliberate detonation for compiler catch test");
        },
        selectedColumns: {},
      };

      const { result: explodeResult } = renderHook(() =>
        useSqlCompiler(explosiveObject),
      );
      expect(explodeResult.current.isValid).toBe(false);
      expect(explodeResult.current.error).toContain("Deliberate detonation");

      const visualStateWithoutNumericLimit = {
        primaryTable: "users",
        selectedColumns: {},
        limit: undefined,
      };
      const { result: limitResult } = renderHook(() =>
        useSqlCompiler(visualStateWithoutNumericLimit),
      );
      expect(limitResult.current.sql).toContain("LIMIT 50;");

      const visualStateWithoutOrderedKeys = {
        primaryTable: "users",
        selectedColumns: { "users.id": { name: "id", table: "users" } },
        orderedProjectionKeys: undefined,
      };
      const { result: noOrderedKeysResult } = renderHook(() =>
        useSqlCompiler(visualStateWithoutOrderedKeys),
      );
      expect(noOrderedKeysResult.current.sql).toContain('"users"."id"');
    });
  });
});

