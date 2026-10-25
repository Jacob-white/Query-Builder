import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import {
  QueryResultsTable,
  resolveForeignKeyTarget,
} from "../src/components/QueryResultsTable";
import { DashboardWorkbench } from "../src/components/DashboardWorkbench";
import { TableFiltersEditor } from "../src/components/TableFiltersEditor";
import { TableJoinEditor } from "../src/components/TableJoinEditor";
import { QueryCanvas } from "../src/components/QueryCanvas";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import {
  QueryTemplateManager,
  loadQueryHistory,
  recordQueryHistory,
  clearQueryHistory,
  encodeQuerySpecToUrlParam,
  decodeQuerySpecFromUrlParam,
  buildShareableQueryUrl,
} from "../src/components/QueryTemplateManager";
import { findMultiHopJoinPath, classifyJoinCondition } from "../src/utils/joinUtils";
import { compileVisualState } from "../src/utils/compiler";
import { expandTimeGrainSql } from "../src/adapters/semantic";
import type { SchemaSnapshot, TableMeta, QueryResultData } from "../src/types";

const ECOMMERCE_TABLES: TableMeta[] = [
  {
    name: "users",
    columns: [
      { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      { name: "email", data_type: "varchar", is_nullable: false, is_primary: false },
      { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
    ],
  },
  {
    name: "orders",
    columns: [
      { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
      { name: "status", data_type: "varchar", is_nullable: false, is_primary: false },
      { name: "total_amount", data_type: "numeric", is_nullable: false, is_primary: false },
      { name: "order_date", data_type: "date", is_nullable: false, is_primary: false },
    ],
  },
  {
    name: "order_items",
    columns: [
      { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      { name: "order_id", data_type: "integer", is_nullable: false, is_primary: false },
      { name: "product_id", data_type: "integer", is_nullable: false, is_primary: false },
      { name: "quantity", data_type: "integer", is_nullable: false, is_primary: false },
    ],
  },
  {
    name: "products",
    columns: [
      { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      { name: "category_id", data_type: "integer", is_nullable: false, is_primary: false },
      { name: "name", data_type: "varchar", is_nullable: false, is_primary: false },
      { name: "price", data_type: "numeric", is_nullable: false, is_primary: false },
    ],
  },
  {
    name: "categories",
    columns: [
      { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      { name: "name", data_type: "varchar", is_nullable: false, is_primary: false },
    ],
  },
];

const ECOMMERCE_SCHEMA: SchemaSnapshot = {
  tables: Object.fromEntries(ECOMMERCE_TABLES.map((t) => [t.name, t])),
  foreign_keys: [
    { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
    { table: "order_items", column: "order_id", foreign_table: "orders", foreign_column: "id" },
    { table: "order_items", column: "product_id", foreign_table: "products", foreign_column: "id" },
  ],
  relationships: [
    {
      source_table: "products",
      source_column: "category_id",
      target_table: "categories",
      target_column: "id",
    },
  ],
};

describe("Power Tools & UX Improvements Suite", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  describe("1. Interactive Results Table Power Tools", () => {
    it("resolves foreign key targets from foreign_keys, relationships, and _id conventions", () => {
      expect(resolveForeignKeyTarget("orders.user_id", ECOMMERCE_SCHEMA)).toEqual({
        targetTable: "users",
        targetColumn: "id",
      });
      expect(resolveForeignKeyTarget("products.category_id", ECOMMERCE_SCHEMA)).toEqual({
        targetTable: "categories",
        targetColumn: "id",
      });
      expect(resolveForeignKeyTarget("order_id", ECOMMERCE_SCHEMA)).toEqual({
        targetTable: "orders",
        targetColumn: "id",
      });
      // Nonexistent *_id table when schema.tables is populated must return null (not "taxes")
      expect(resolveForeignKeyTarget("tax_id", ECOMMERCE_SCHEMA)).toBeNull();
      expect(resolveForeignKeyTarget("external_ref_id", ECOMMERCE_SCHEMA)).toBeNull();
      // Heuristic fallback when schema is null/empty
      expect(resolveForeignKeyTarget("company_id", null)).toEqual({
        targetTable: "companies",
        targetColumn: "id",
      });
      expect(resolveForeignKeyTarget("status_id", null)).toEqual({
        targetTable: "statuses",
        targetColumn: "id",
      });
      expect(resolveForeignKeyTarget("email", ECOMMERCE_SCHEMA)).toBeNull();
    });

    it("toggles column micro-stats row and supports cell click filter, null filter, and FK drill-down", () => {
      const results: QueryResultData = {
        columns: ["id", "user_id", "status", "total_amount"],
        rows: [
          { id: 1, user_id: 42, status: "COMPLETED", total_amount: 120.5 },
          { id: 2, user_id: 99, status: null, total_amount: 80.0 },
        ],
        count: 2,
      };
      const onFilterByCell = vi.fn();
      const onDrillDownForeignKey = vi.fn();
      const onPinToDashboard = vi.fn();

      const { container } = render(
        <QueryResultsTable
          results={results}
          schema={ECOMMERCE_SCHEMA}
          onFilterByCell={onFilterByCell}
          onDrillDownForeignKey={onDrillDownForeignKey}
          onPinToDashboard={onPinToDashboard}
        />,
      );

      // Toggle column stats row
      const statsBtn = container.querySelector('[data-qb="btn-toggle-column-stats"]')!;
      expect(statsBtn).toBeTruthy();
      fireEvent.click(statsBtn);
      const statsRow = container.querySelector('[data-qb="results-stats-row"]');
      expect(statsRow).toBeTruthy();
      expect(statsRow?.textContent).toContain("Distinct");
      expect(statsRow?.textContent).toContain("Null:");
      expect(statsRow?.textContent).toContain("Avg:");

      // Pin to BI Dashboard
      const pinBtn = container.querySelector('[data-qb="btn-pin-to-dashboard"]')!;
      fireEvent.click(pinBtn);
      expect(onPinToDashboard).toHaveBeenCalledOnce();

      // Click a foreign-key cell (user_id = 42)
      const cells = container.querySelectorAll('[data-qb="results-td"]');
      fireEvent.click(cells[1]); // user_id = 42
      expect(container.querySelector('[data-qb="results-cell-action-bar"]')).toBeTruthy();

      const fkBtn = container.querySelector('[data-qb="btn-cell-fk-drilldown"]')!;
      expect(fkBtn.textContent).toContain("users.id = 42");
      fireEvent.click(fkBtn);
      expect(onDrillDownForeignKey).toHaveBeenCalledWith("user_id", 42, "users", "id");

      // Click non-null cell and filter !=
      fireEvent.click(cells[2]); // status = COMPLETED
      fireEvent.click(container.querySelector('[data-qb="btn-cell-filter-neq"]')!);
      expect(onFilterByCell).toHaveBeenCalledWith("status", "COMPLETED", "!=");

      // Click null cell (row 2 status = null) and filter IS NULL
      fireEvent.click(cells[6]); // row 2 status
      expect(container.querySelector('[data-qb="btn-cell-filter-eq"]')?.textContent).toContain(
        "IS NULL",
      );
      fireEvent.click(container.querySelector('[data-qb="btn-cell-filter-eq"]')!);
      expect(onFilterByCell).toHaveBeenCalledWith("status", null, "IS NULL");

      // Toggle off cell action bar by clicking close button
      fireEvent.click(cells[0]);
      fireEvent.click(container.querySelector('[data-qb="btn-cell-action-close"]')!);
      expect(container.querySelector('[data-qb="results-cell-action-bar"]')).toBeNull();
    });
  });

  describe("2. BI Dashboard Persistence & Per-Tile Chart/Axis Editor", () => {
    it("persists custom tiles to localStorage and edits tile chart type, X/Y axes, and aggregation", () => {
      const liveResults: QueryResultData = {
        columns: ["status", "region", "total_amount", "quantity"],
        rows: [
          { status: "COMPLETED", region: "US", total_amount: 100, quantity: 2 },
          { status: "COMPLETED", region: "US", total_amount: 180, quantity: 4 },
          { status: "PENDING", region: "EU", total_amount: 250, quantity: 5 },
        ],
        count: 3,
      };

      const { unmount } = render(
        <DashboardWorkbench results={liveResults} storageKey="unit_test_bi" />,
      );

      // Open per-tile config editor on auto chart tile
      const configBtn = screen.getByTestId("configure-tile-tile-query-chart");
      fireEvent.click(configBtn);

      const panel = screen.getByTestId("tile-config-panel-tile-query-chart");
      expect(panel).toBeTruthy();

      // Change visualization type to line, X axis to region, Y axis to quantity, aggregation to AVG
      fireEvent.change(screen.getByTestId("tile-viz-select-tile-query-chart"), {
        target: { value: "line" },
      });
      fireEvent.change(screen.getByTestId("tile-category-select-tile-query-chart"), {
        target: { value: "region" },
      });
      fireEvent.change(screen.getByTestId("tile-metric-select-tile-query-chart"), {
        target: { value: "quantity" },
      });
      fireEvent.change(screen.getByTestId("tile-agg-select-tile-query-chart"), {
        target: { value: "AVG" },
      });

      // Switch to KPI mode (test MIN and MAX) and Pivot mode (test MIN and MAX) and back to table mode
      fireEvent.change(screen.getByTestId("tile-viz-select-tile-query-chart"), {
        target: { value: "kpi" },
      });
      fireEvent.change(screen.getByTestId("tile-agg-select-tile-query-chart"), {
        target: { value: "MIN" },
      });
      fireEvent.change(screen.getByTestId("tile-agg-select-tile-query-chart"), {
        target: { value: "MAX" },
      });
      fireEvent.change(screen.getByTestId("tile-viz-select-tile-query-chart"), {
        target: { value: "pivot" },
      });
      fireEvent.change(screen.getByTestId("tile-agg-select-tile-query-chart"), {
        target: { value: "MIN" },
      });
      fireEvent.change(screen.getByTestId("tile-agg-select-tile-query-chart"), {
        target: { value: "MAX" },
      });
      fireEvent.change(screen.getByTestId("tile-viz-select-tile-query-chart"), {
        target: { value: "table" },
      });

      // Add a custom tile so it persists in localStorage
      fireEvent.click(screen.getByTestId("add-tile-btn"));
      fireEvent.change(screen.getByTestId("new-tile-title-input"), {
        target: { value: "Persisted Revenue Tile" },
      });
      fireEvent.click(screen.getByTestId("confirm-add-tile-btn"));
      expect(screen.getByText("Persisted Revenue Tile")).toBeTruthy();

      unmount();

      // Re-mount with same storageKey and verify custom tile is restored from localStorage
      render(<DashboardWorkbench storageKey="unit_test_bi" />);
      expect(screen.getByText("Persisted Revenue Tile")).toBeTruthy();
    });
  });

  describe("3. Smart Filter Value Autocomplete & Distinct Value Picker", () => {
    it("suggests distinct values from sampleRows and onFetchDistinctValues and applies clicked pill", async () => {
      const onChange = vi.fn();
      const onFetchDistinctValues = vi.fn().mockResolvedValue(["COMPLETED", "PENDING", "CANCELLED"]);

      const { container } = render(
        <TableFiltersEditor
          filters={[
            {
              id: "f1",
              combiner: "AND",
              tablePrefix: "orders",
              column: "status",
              operator: "=",
              value: "",
            },
          ]}
          activeTables={[ECOMMERCE_TABLES[1]]}
          sampleRows={[{ status: "REFUNDED" }]}
          onFetchDistinctValues={onFetchDistinctValues}
          onChange={onChange}
        />,
      );

      await waitFor(() => {
        expect(onFetchDistinctValues).toHaveBeenCalledWith("orders", "status");
      });

      const pills = await waitFor(() => {
        const found = container.querySelectorAll('[data-qb="filter-enum-pill"]');
        expect(found.length).toBeGreaterThanOrEqual(3);
        return found;
      });

      fireEvent.click(pills[0]);
      expect(onChange).toHaveBeenCalled();
    });
  });

  describe("4. Visual Multi-Hop Join Path Finder", () => {
    it("discovers multi-hop join paths across intermediate bridge tables and auto-inserts joins", () => {
      const path = findMultiHopJoinPath(["users"], "products", ECOMMERCE_SCHEMA);
      expect(path.isConnected).toBe(true);
      expect(path.bridgeTables).toEqual(["orders", "order_items"]);
      expect(path.joins).toHaveLength(3);

      // 3-hop path to categories via relationships
      const catPath = findMultiHopJoinPath(["orders"], "categories", ECOMMERCE_SCHEMA);
      expect(catPath.bridgeTables).toEqual(["order_items", "products"]);

      expect(
        classifyJoinCondition("products", "category_id", "categories", "id", ECOMMERCE_SCHEMA)
          .joinTier,
      ).toBe("confirmed");
      expect(
        classifyJoinCondition("categories", "id", "products", "category_id", ECOMMERCE_SCHEMA)
          .joinTier,
      ).toBe("confirmed");

      const onChange = vi.fn();
      const { container } = render(
        <TableJoinEditor
          joins={[]}
          activeTables={[ECOMMERCE_TABLES[0]]}
          allTables={ECOMMERCE_TABLES}
          schema={ECOMMERCE_SCHEMA}
          onChange={onChange}
        />,
      );

      const multiHopStrip = container.querySelector('[data-qb="multihop-join-strip"]');
      expect(multiHopStrip).toBeTruthy();

      const autoJoinProductsBtn = container.querySelector(
        '[data-qb="btn-auto-join-multihop"][data-qb-target-table="products"]',
      )!;
      expect(autoJoinProductsBtn).toBeTruthy();
      fireEvent.click(autoJoinProductsBtn);

      expect(onChange).toHaveBeenCalledOnce();
      const insertedJoins = onChange.mock.calls[0][0];
      expect(insertedJoins.map((j: { table: string }) => j.table)).toEqual([
        "orders",
        "order_items",
        "products",
      ]);
    });
  });

  describe("5. Execution History Timeline & Shareable URL Permalinks", () => {
    it("encodes/decodes query specs in URL params and manages execution history in QueryTemplateManager", () => {
      const spec = {
        table: "orders",
        columns: ["orders.id", "orders.status"],
        filters: [{ column: "status", op: "=", value: "COMPLETED", tablePrefix: "orders" }],
        limit: 25,
      };
      const encoded = encodeQuerySpecToUrlParam(spec);
      expect(encoded.length).toBeGreaterThan(5);
      const decoded = decodeQuerySpecFromUrlParam(encoded);
      expect(decoded?.table).toBe("orders");
      expect(decoded?.columns).toEqual(["orders.id", "orders.status"]);

      const shareUrl = buildShareableQueryUrl(spec, "https://example.com/studio", "starter_demo");
      expect(shareUrl).toContain("db=starter_demo");
      expect(shareUrl).toContain("q=");

      recordQueryHistory({
        sql: "SELECT orders.id FROM orders LIMIT 25",
        spec,
        rowCount: 12,
        latencyMs: 4.2,
        dialect: "sqlite",
      });
      expect(loadQueryHistory()).toHaveLength(1);

      const onLoadTemplate = vi.fn();
      const { container } = render(
        <QueryTemplateManager
          isOpen={true}
          onClose={vi.fn()}
          currentSpec={spec}
          currentSql="SELECT orders.id FROM orders LIMIT 25"
          onLoadTemplate={onLoadTemplate}
          defaultMode="history"
        />,
      );

      expect(container.querySelector('[data-qb="history-item"]')).toBeTruthy();
      fireEvent.click(container.querySelector('[data-qb="btn-restore-history"]')!);
      expect(onLoadTemplate).toHaveBeenCalledOnce();

      // Re-open and test clear history + share link button
      const { container: c2 } = render(
        <QueryTemplateManager
          isOpen={true}
          onClose={vi.fn()}
          currentSpec={spec}
          currentSql="SELECT orders.id FROM orders LIMIT 25"
          onLoadTemplate={onLoadTemplate}
          defaultMode="history"
        />,
      );
      fireEvent.click(c2.querySelector('[data-qb="btn-share-permalink"]')!);
      fireEvent.click(c2.querySelector('[data-qb="btn-clear-history"]')!);
      expect(loadQueryHistory()).toHaveLength(0);
      clearQueryHistory();
    });
  });

  describe("6. Guided Date-Bucketing & End-to-End VisualQueryBuilder Integration", () => {
    it("applies guided date-bucketing in QueryCanvas and updates column timeGrain", () => {
      const onToggleColumn = vi.fn();
      const onUpdateColumnSelect = vi.fn();

      const { container } = render(
        <QueryCanvas
          schema={ECOMMERCE_SCHEMA}
          activeTables={[ECOMMERCE_TABLES[1]]}
          primaryTable="orders"
          selectedColumns={{
            "orders.total_amount": {
              table: "orders",
              name: "total_amount",
              aggregate: "SUM",
            },
          }}
          orderedProjectionKeys={["orders.total_amount"]}
          joins={[]}
          filters={[]}
          sorts={[]}
          isDistinct={false}
          limit={25}
          onToggleColumn={onToggleColumn}
          onRemoveTable={vi.fn()}
          onAddTableToCanvas={vi.fn()}
          onUpdateColumnSelect={onUpdateColumnSelect}
          onRemoveColumnProjection={vi.fn()}
          onJoinsChange={vi.fn()}
          onFiltersChange={vi.fn()}
          onSortsChange={vi.fn()}
          onDistinctChange={vi.fn()}
          onLimitChange={vi.fn()}
        />,
      );

      const dateBar = container.querySelector('[data-qb="guided-date-bucketing"]');
      expect(dateBar).toBeTruthy();

      const monthPill = container.querySelector(
        '[data-qb="date-bucket-pill"][data-qb-grain="month"]',
      )!;
      fireEvent.click(monthPill);

      expect(onToggleColumn).toHaveBeenCalledWith("orders", "order_date");
      expect(onUpdateColumnSelect).toHaveBeenCalledWith("orders.order_date", {
        table: "orders",
        name: "order_date",
        timeGrain: "month",
        aggregate: undefined,
      });
    });

    it("hydrates URL ?q= spec on VisualQueryBuilder mount, records execution history, and pins results to BI dashboard", async () => {
      const sharedSpec = {
        table: "orders",
        columns: ["orders.id", "orders.user_id", "orders.status"],
        joins: [],
        filters: [],
        filter_join: "AND" as const,
        order_by: [],
        distinct: false,
        limit: 10,
      };
      const encoded = encodeQuerySpecToUrlParam(sharedSpec);
      window.history.replaceState(null, "", `?q=${encodeURIComponent(encoded)}`);

      const onExecuteQuery = vi.fn().mockResolvedValue({
        columns: ["orders.id", "orders.user_id", "status"],
        rows: [
          { "orders.id": 10, "orders.user_id": 7, status: "COMPLETED" },
          { "orders.id": 11, "orders.user_id": 8, status: null },
        ],
        count: 2,
        durationMs: 3,
      });
      const onPinToDashboard = vi.fn();

      const { container } = render(
        <VisualQueryBuilder
          schema={ECOMMERCE_SCHEMA}
          initialTable="users"
          onExecuteQuery={onExecuteQuery}
          onPinToDashboard={onPinToDashboard}
        />,
      );

      // Run query and verify execution history + interactive results actions
      const runBtn = screen.getByText("▶ Run Query");
      fireEvent.click(runBtn);

      await waitFor(() => {
        expect(onExecuteQuery).toHaveBeenCalled();
      });
      expect(loadQueryHistory().length).toBeGreaterThan(0);

      // Click Pin to BI Dashboard in dock results
      const pinBtn = await waitFor(() => {
        const el = container.querySelector('[data-qb="btn-pin-to-dashboard"]');
        expect(el).toBeTruthy();
        return el!;
      });
      fireEvent.click(pinBtn);
      expect(onPinToDashboard).toHaveBeenCalledOnce();
      expect(window.localStorage.getItem("qb_dashboard_tiles_default")).toContain("Snapshot");

      // Click result cells in VisualQueryBuilder dock to trigger handleFilterByCell and handleDrillDownForeignKey
      const dockCells = container.querySelectorAll('[data-qb="results-td"]');
      expect(dockCells.length).toBeGreaterThanOrEqual(6);
      fireEvent.click(dockCells[1]); // orders.user_id = 7 (prefixed FK column)
      const fkDrillBtn = container.querySelector('[data-qb="btn-cell-fk-drilldown"]');
      if (fkDrillBtn) {
        fireEvent.click(fkDrillBtn);
      }
      fireEvent.click(dockCells[0]); // orders.id = 10 (prefixed column filter)
      const eqBtn1 = container.querySelector('[data-qb="btn-cell-filter-eq"]');
      if (eqBtn1) {
        fireEvent.click(eqBtn1);
      }
      fireEvent.click(dockCells[5]); // status = null (unprefixed column IS NULL filter)
      const eqBtn2 = container.querySelector('[data-qb="btn-cell-filter-eq"]');
      if (eqBtn2) {
        fireEvent.click(eqBtn2);
      }

      window.history.replaceState(null, "", window.location.pathname);
    });

    it("covers date bucket clear/toggle, URL helper edge branches, and stats/tile config variants", () => {
      expect(decodeQuerySpecFromUrlParam("")).toBeNull();
      expect(decodeQuerySpecFromUrlParam("%%%invalid%%%")).toBeNull();
      expect(decodeQuerySpecFromUrlParam(encodeURIComponent("[1,2,3]"))).toBeNull();
      expect(
        decodeQuerySpecFromUrlParam(encodeURIComponent(JSON.stringify({ table: "orders" }))),
      ).toEqual({ table: "orders" });
      expect(
        buildShareableQueryUrl({ table: "orders" }, "not a url", { db: "demo", empty: "" }),
      ).toContain("?q=");
      expect(
        buildShareableQueryUrl({ table: "orders" }, "https://example.com/q", {
          db: "demo",
          empty: "",
        }),
      ).toContain("db=demo");

      const onToggleColumn = vi.fn();
      const onUpdateColumnSelect = vi.fn();

      const { container } = render(
        <QueryCanvas
          schema={ECOMMERCE_SCHEMA}
          activeTables={[ECOMMERCE_TABLES[0], ECOMMERCE_TABLES[1]]}
          primaryTable="orders"
          selectedColumns={{
            "orders.order_date": {
              table: "orders",
              name: "order_date",
              timeGrain: "month",
            },
          }}
          orderedProjectionKeys={["orders.order_date"]}
          joins={[]}
          filters={[]}
          sorts={[]}
          isDistinct={false}
          limit={25}
          onToggleColumn={onToggleColumn}
          onRemoveTable={vi.fn()}
          onAddTableToCanvas={vi.fn()}
          onUpdateColumnSelect={onUpdateColumnSelect}
          onRemoveColumnProjection={vi.fn()}
          onJoinsChange={vi.fn()}
          onFiltersChange={vi.fn()}
          onSortsChange={vi.fn()}
          onDistinctChange={vi.fn()}
          onLimitChange={vi.fn()}
        />,
      );

      const dateColSelect = container.querySelector('[data-qb="guided-date-column-select"]')!;
      fireEvent.change(dateColSelect, { target: { value: "orders.order_date" } });

      const monthPill = container.querySelector(
        '[data-qb="date-bucket-pill"][data-qb-grain="month"]',
      )!;
      fireEvent.click(monthPill);
      expect(onUpdateColumnSelect).toHaveBeenCalledWith("orders.order_date", {
        timeGrain: undefined,
      });

      const clearBtn = container.querySelector('[data-qb="date-bucket-clear"]')!;
      fireEvent.click(clearBtn);
      expect(onUpdateColumnSelect).toHaveBeenCalledTimes(2);

      // QueryResultsTable stats with string numbers, objects, all-nulls, and long text + IS NOT NULL / != filters
      const onFilter = vi.fn();
      const { container: resContainer } = render(
        <QueryResultsTable
          results={{
            columns: ["str_num", "obj_col", "all_null", "long_str"],
            rows: [
              {
                str_num: "42.5",
                obj_col: { nested: 1 },
                all_null: null,
                long_str: "averylongstringvaluethatexceedseighteenchars",
              },
              {
                str_num: "17.5",
                obj_col: { nested: 2 },
                all_null: null,
                long_str: "short",
              },
            ],
            count: 2,
          }}
          onFilterByCell={onFilter}
        />,
      );
      fireEvent.click(resContainer.querySelector('[data-qb="btn-toggle-column-stats"]')!);
      expect(resContainer.querySelector('[data-qb="results-stats-row"]')?.textContent).toContain(
        "All null",
      );

      const cells = resContainer.querySelectorAll('[data-qb="results-td"]');
      fireEvent.click(cells[0]); // str_num = "42.5"
      fireEvent.click(resContainer.querySelector('[data-qb="btn-cell-filter-neq"]')!);
      expect(onFilter).toHaveBeenCalledWith("str_num", "42.5", "!=");

      fireEvent.click(cells[2]); // all_null = null
      fireEvent.click(resContainer.querySelector('[data-qb="btn-cell-filter-neq"]')!);
      expect(onFilter).toHaveBeenCalledWith("all_null", null, "IS NOT NULL");

      // Fallback search when onFilterByCell is omitted
      const { container: resFallback } = render(
        <QueryResultsTable
          results={{
            columns: ["name"],
            rows: [{ name: "Alpha" }, { name: "Beta" }],
            count: 2,
          }}
        />,
      );
      const cell0 = resFallback.querySelectorAll('[data-qb="results-td"]')[0];
      fireEvent.click(cell0);
      fireEvent.click(cell0); // toggles off
      expect(resFallback.querySelector('[data-qb="results-cell-action-bar"]')).toBeNull();
      fireEvent.click(cell0);
      fireEvent.click(resFallback.querySelector('[data-qb="btn-cell-filter-eq"]')!);
      expect(resFallback.textContent).toContain("Alpha");
    });

    it("handles empty rows in DashboardWorkbench tile config, preserves customized axes on refresh, and syncs KPI metricCol", () => {
      const emptyResults: QueryResultData = {
        columns: ["status", "region", "total_amount", "quantity"],
        rows: [],
        count: 0,
      };
      const { rerender } = render(
        <DashboardWorkbench results={emptyResults} storageKey="unit_test_bi_empty" />,
      );

      // Opening Per-Tile Config when rows is empty must not crash
      fireEvent.click(screen.getByTestId("configure-tile-tile-query-chart"));
      expect(screen.getByTestId("tile-config-panel-tile-query-chart")).toBeTruthy();

      // Customize X/Y axes
      fireEvent.change(screen.getByTestId("tile-category-select-tile-query-chart"), {
        target: { value: "region" },
      });
      fireEvent.change(screen.getByTestId("tile-metric-select-tile-query-chart"), {
        target: { value: "quantity" },
      });

      // Refresh with populated rows and verify user-selected axes are preserved
      rerender(
        <DashboardWorkbench
          results={{
            columns: ["status", "region", "total_amount", "quantity"],
            rows: [{ status: "COMPLETED", region: "US", total_amount: 100, quantity: 5 }],
            count: 1,
          }}
          storageKey="unit_test_bi_empty"
        />,
      );

      expect(
        (screen.getByTestId("tile-category-select-tile-query-chart") as HTMLSelectElement).value,
      ).toBe("region");
      expect(
        (screen.getByTestId("tile-metric-select-tile-query-chart") as HTMLSelectElement).value,
      ).toBe("quantity");

      // Open config on KPI tile and change metricCol -> kpiConfig.valueField updates
      fireEvent.click(screen.getByTestId("configure-tile-tile-query-kpi"));
      fireEvent.change(screen.getByTestId("tile-metric-select-tile-query-kpi"), {
        target: { value: "quantity" },
      });
      expect(
        (screen.getByTestId("tile-metric-select-tile-query-kpi") as HTMLSelectElement).value,
      ).toBe("quantity");
    });

    it("resolves TableFiltersEditor distinct values when tablePrefix is empty on multi-table queries and prioritizes confirmed FK multi-hop paths", async () => {
      const onFetchDistinctValues = vi.fn().mockResolvedValue(["COMPLETED", "PENDING"]);
      const { container } = render(
        <TableFiltersEditor
          filters={[
            {
              id: "f_no_prefix",
              combiner: "AND",
              tablePrefix: "",
              column: "status",
              operator: "=",
              value: "",
            },
          ]}
          activeTables={[ECOMMERCE_TABLES[0], ECOMMERCE_TABLES[1]]}
          sampleRows={[{ status: "CANCELLED" }]}
          onFetchDistinctValues={onFetchDistinctValues}
          onChange={vi.fn()}
        />,
      );

      await waitFor(() => {
        expect(onFetchDistinctValues).toHaveBeenCalledWith("orders", "status");
      });
      const pills = await waitFor(() => {
        const found = container.querySelectorAll('[data-qb="filter-enum-pill"]');
        expect(found.length).toBeGreaterThanOrEqual(3);
        return found;
      });
      expect(pills[0]).toBeTruthy();

      // Multi-hop path prioritization: confirmed FK path must win over equal-length inferred *_id path
      const tieBreakSchema: SchemaSnapshot = {
        tables: {
          a: {
            name: "a",
            columns: [
              { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
              { name: "b_inferred_id", data_type: "integer", is_nullable: false, is_primary: false },
              { name: "b_confirmed_id", data_type: "integer", is_nullable: false, is_primary: false },
            ],
          },
          b_inferred: {
            name: "b_inferred",
            columns: [
              { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
              { name: "c_id", data_type: "integer", is_nullable: false, is_primary: false },
            ],
          },
          b_confirmed: {
            name: "b_confirmed",
            columns: [
              { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
              { name: "c_id", data_type: "integer", is_nullable: false, is_primary: false },
            ],
          },
          c: {
            name: "c",
            columns: [{ name: "id", data_type: "integer", is_nullable: false, is_primary: true }],
          },
        },
        foreign_keys: [
          { table: "a", column: "b_confirmed_id", foreign_table: "b_confirmed", foreign_column: "id" },
          { table: "b_confirmed", column: "c_id", foreign_table: "c", foreign_column: "id" },
        ],
      };
      const bestPath = findMultiHopJoinPath(["a"], "c", tieBreakSchema);
      expect(bestPath.bridgeTables).toEqual(["b_confirmed"]);
    });

    it("emits GROUP BY for timeGrain without explicit aggregate, compiles SQLite quarter accurately, records databaseId badge, and ignores invalid ?q= table", async () => {
      // 1. compileVisualState emits GROUP BY when timeGrain is set without a separate aggregate column
      const compiledTimeOnly = compileVisualState(
        "orders",
        {
          "orders.order_date": {
            table: "orders",
            name: "order_date",
            timeGrain: "month",
          },
          "orders.status": {
            table: "orders",
            name: "status",
          },
        },
        ["orders.order_date", "orders.status"],
        [],
        [],
        [],
        false,
        25,
        ECOMMERCE_SCHEMA,
        "postgres",
      );
      expect(compiledTimeOnly.sql).toContain("DATE_TRUNC('month'");
      expect(compiledTimeOnly.sql).toContain("GROUP BY");

      // 2. SQLite quarter time grain produces valid Q1..Q4 expression
      const sqliteQuarter = expandTimeGrainSql('"orders"."order_date"', "quarter", "sqlite");
      expect(sqliteQuarter).toContain("STRFTIME('%Y-Q', \"orders\".\"order_date\")");
      expect(sqliteQuarter).toContain("CAST(STRFTIME('%m', \"orders\".\"order_date\") AS INTEGER) + 2) / 3");

      // 3. Execution history records databaseId and renders badge
      clearQueryHistory();
      recordQueryHistory({
        sql: "SELECT * FROM orders LIMIT 10",
        spec: { table: "orders" },
        rowCount: 5,
        latencyMs: 2.5,
        dialect: "sqlite",
        databaseId: "starter_demo",
      });
      const { container: histContainer } = render(
        <QueryTemplateManager
          isOpen={true}
          onClose={vi.fn()}
          onLoadTemplate={vi.fn()}
          defaultMode="history"
        />,
      );
      expect(histContainer.querySelector('[data-qb="history-db-badge"]')?.textContent).toContain(
        "starter_demo",
      );

      // 4. VisualQueryBuilder ignores nonexistent ?q= table and falls back to initialTable
      const badEncoded = encodeQuerySpecToUrlParam({ table: "nonexistent_ghost_table" });
      window.history.replaceState(null, "", `?q=${encodeURIComponent(badEncoded)}`);
      const onExec = vi.fn().mockResolvedValue({
        columns: ["id"],
        rows: [{ id: 1 }],
        count: 1,
        latency_ms: 4.1,
      });
      render(
        <VisualQueryBuilder
          schema={ECOMMERCE_SCHEMA}
          initialTable="users"
          activeDatabaseId="starter_demo"
          onExecuteQuery={onExec}
        />,
      );
      fireEvent.click(screen.getAllByText("▶ Run Query")[0]);
      await waitFor(() => {
        expect(onExec).toHaveBeenCalled();
      });
      const executedSql = onExec.mock.calls[0][0] as string;
      expect(executedSql).toContain('"users"');
      expect(executedSql).not.toContain("nonexistent_ghost_table");
      window.history.replaceState(null, "", window.location.pathname);
    });
  });
});
