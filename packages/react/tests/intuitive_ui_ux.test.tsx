import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QuerySummaryBar } from "../src/components/QuerySummaryBar";
import { TableCard } from "../src/components/TableCard";
import { TableJoinEditor } from "../src/components/TableJoinEditor";
import { TableFiltersEditor } from "../src/components/TableFiltersEditor";
import { TableSortsEditor } from "../src/components/TableSortsEditor";
import { WorkspaceDock } from "../src/components/visual-query-builder/WorkspaceDock";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import type { SchemaSnapshot, QueryResultData, TableMeta } from "../src/types";

const mockSchema: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "email", data_type: "text", is_nullable: false, is_primary: false },
      ],
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
        { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
        { name: "status", data_type: "text", is_nullable: false, is_primary: false },
      ],
    },
  },
  foreign_keys: [
    {
      table: "orders",
      column: "user_id",
      foreign_table: "users",
      foreign_column: "id",
    },
  ],
};

describe("QuerySummaryBar (Plain-English breadcrumb)", () => {
  it("renders natural language breadcrumb and handles reset clauses", () => {
    const handleClear = vi.fn();
    const handleNav = vi.fn();

    render(
      <QuerySummaryBar
        primaryTable="orders"
        activeTables={["orders", "users"]}
        selectedColumns={{
          "orders.total": { table: "orders", name: "total", aggregate: "SUM" },
          "orders.status": { table: "orders", name: "status" },
        }}
        orderedProjectionKeys={["orders.total", "orders.status"]}
        joins={[{ table: "users", type: "LEFT JOIN", left_table: "orders", left_col: "user_id", right_col: "id" }]}
        filters={[{ column: "status", tablePrefix: "orders", operator: "=", value: "COMPLETED", dataType: "text" }]}
        sorts={[{ column: "orders.total", direction: "DESC" }]}
        limit={25}
        isDistinct={true}
        onClearClauses={handleClear}
        onNavigateSection={handleNav}
      />
    );

    const summaryEl = document.querySelector('[data-qb="query-summary-bar"]');
    expect(summaryEl).toBeTruthy();
    expect(screen.getByText(/from orders/i)).toBeTruthy();
    expect(screen.getByText(/joined with users/i)).toBeTruthy();
    expect(screen.getByText(/Sum of total/i)).toBeTruthy();

    // Check clause chips
    expect(screen.getByText("📋 orders")).toBeTruthy();
    expect(screen.getByText("✨ 2 columns")).toBeTruthy();
    expect(screen.getByText("🔗 1 join")).toBeTruthy();
    expect(screen.getByText("🔍 1 filter")).toBeTruthy();
    expect(screen.getByText("⚡ 1 sort")).toBeTruthy();
    expect(screen.getByText("DISTINCT")).toBeTruthy();

    // Reset clauses action
    const resetBtn = screen.getByText("↺ Reset clauses");
    fireEvent.click(resetBtn);
    expect(handleClear).toHaveBeenCalledOnce();

    // Chip navigation
    fireEvent.click(screen.getByText("🔗 1 join"));
    expect(handleNav).toHaveBeenCalledWith("joins");

    fireEvent.click(screen.getByText("📋 orders"));
    expect(handleNav).toHaveBeenCalledWith("tables");

    fireEvent.click(screen.getByText("✨ 2 columns"));
    expect(handleNav).toHaveBeenCalledWith("columns");

    fireEvent.click(screen.getByText("🔍 1 filter"));
    expect(handleNav).toHaveBeenCalledWith("filters");

    fireEvent.click(screen.getByText("⚡ 1 sort"));
    expect(handleNav).toHaveBeenCalledWith("sorts");
  });

  it("handles unstyled mode, window functions, and empty projection fallback", () => {
    const handleClear = vi.fn();
    const { rerender } = render(
      <QuerySummaryBar
        primaryTable="orders"
        joins={[{ table: "users" }]}
        filters={[{ column: "active", operator: "=", value: true }]}
        sorts={[{ column: "created_at", direction: "ASC" }]}
        windowFunctions={[{ function: "ROW_NUMBER", alias: "rn" }]}
        onClearClauses={handleClear}
        unstyled={true}
      />
    );

    expect(screen.getByText(/All columns from orders/i)).toBeTruthy();
    const resetBtn = screen.getByText("Reset clauses");
    fireEvent.click(resetBtn);
    expect(handleClear).toHaveBeenCalledOnce();

    // Empty state returns null
    rerender(<QuerySummaryBar activeTables={[]} orderedProjectionKeys={[]} />);
    expect(document.querySelector('[data-qb="query-summary-bar"]')).toBeNull();
  });
});

describe("TableCard inline column quick-actions", () => {
  it("triggers filter, sort, aggregate, and FK join actions from column rows", () => {
    const table: TableMeta = mockSchema.tables.orders;
    const handleToggleCol = vi.fn();
    const handleQuickFilter = vi.fn();
    const handleQuickSort = vi.fn();
    const handleQuickAggregate = vi.fn();
    const handleQuickJoinFk = vi.fn();

    render(
      <TableCard
        table={table}
        selectedColumns={{ "orders.total": { table: "orders", name: "total", aggregate: "SUM" } }}
        onToggleColumn={handleToggleCol}
        onQuickFilterColumn={handleQuickFilter}
        onQuickSortColumn={handleQuickSort}
        onQuickAggregateColumn={handleQuickAggregate}
        onQuickJoinForeignKey={handleQuickJoinFk}
        activeFilterColumns={new Set(["status"])}
        activeSortMap={{ total: "DESC" }}
        foreignKeys={mockSchema.foreign_keys}
      />
    );

    // 1. Filter quick-action on 'status'
    const filterBtns = screen.getAllByLabelText(/Filter by/);
    expect(filterBtns.length).toBe(4);
    fireEvent.click(filterBtns[3]); // status
    expect(handleQuickFilter).toHaveBeenCalledWith("orders", "status", "text");
    expect(handleToggleCol).not.toHaveBeenCalled(); // stopPropagation verified

    // 2. Sort quick-action on 'total'
    const sortBtns = screen.getAllByLabelText(/Sort by/);
    fireEvent.click(sortBtns[2]); // total
    expect(handleQuickSort).toHaveBeenCalledWith("orders", "total");

    // 3. Aggregate quick-action on 'total'
    const aggBtns = screen.getAllByLabelText(/Aggregate/);
    fireEvent.click(aggBtns[2]); // total (shows SUM)
    expect(handleQuickAggregate).toHaveBeenCalledWith("orders", "total", "SUM");

    // 4. FK Join quick-action on 'user_id' -> users
    const fkBtn = screen.getByText("🔗 users");
    expect(fkBtn).toBeTruthy();
    fireEvent.click(fkBtn);
    expect(handleQuickJoinFk).toHaveBeenCalledWith("users");
  });

  it("handles TableCard column search, clear search, and selection counter", () => {
    const tableWithManyCols: TableMeta = {
      name: "orders",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
        { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
        { name: "status", data_type: "text", is_nullable: false, is_primary: false },
        { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
        { name: "updated_at", data_type: "timestamp", is_nullable: false, is_primary: false },
        { name: "notes", data_type: "text", is_nullable: true, is_primary: false },
      ],
    };
    const handleToggle = vi.fn();

    render(
      <TableCard
        table={tableWithManyCols}
        selectedColumns={{
          "orders.id": { table: "orders", name: "id" },
          "orders.total": { table: "orders", name: "total" },
        }}
        onToggleColumn={handleToggle}
      />
    );

    // Counter shows 2 of 7 selected
    expect(screen.getByTitle("2 of 7 columns selected")).toBeTruthy();
    expect(screen.getByText("2/7")).toBeTruthy();

    // Search filter (appears when > 6 columns)
    const searchInput = screen.getByPlaceholderText(/Filter columns/);
    fireEvent.change(searchInput, { target: { value: "tot" } });
    expect(screen.getByText("total")).toBeTruthy();
    expect(screen.queryByText("user_id")).toBeNull();

    // Clear search
    const clearBtn = screen.getByLabelText("Clear filter search");
    fireEvent.click(clearBtn);
    expect(screen.getByText("user_id")).toBeTruthy();
  });
});

describe("Progressive disclosure compact clause strips", () => {
  it("renders compact single-line strips when empty", () => {
    const handleJoins = vi.fn();
    const handleFilters = vi.fn();
    const handleSorts = vi.fn();

    render(
      <div>
        <TableJoinEditor
          joins={[]}
          activeTables={[mockSchema.tables.users]}
          allTables={Object.values(mockSchema.tables)}
          schema={mockSchema}
          onChange={handleJoins}
        />
        <TableFiltersEditor
          filters={[]}
          activeTables={[mockSchema.tables.users]}
          onChange={handleFilters}
        />
        <TableSortsEditor
          sorts={[]}
          activeTables={[mockSchema.tables.users]}
          selectedColumns={{}}
          onChange={handleSorts}
        />
      </div>
    );

    // All empty-state indicators and action buttons are present in compact strip
    expect(screen.getByText(/Single table query/i)).toBeTruthy();
    expect(screen.getByText("+ Join Table...")).toBeTruthy();

    expect(screen.getByText(/No filters applied/i)).toBeTruthy();
    expect(screen.getByText("+ Add Filter")).toBeTruthy();

    expect(screen.getByText(/Default database ordering/i)).toBeTruthy();
    expect(screen.getByText("+ Add Sort")).toBeTruthy();
  });

  it("verifies proven foreign keys with FK Verified badge in TableJoinEditor", () => {
    render(
      <TableJoinEditor
        joins={[
          {
            id: "j1",
            table: "users",
            type: "LEFT JOIN",
            left_table: "orders",
            left_col: "user_id",
            right_col: "id",
          },
        ]}
        activeTables={[mockSchema.tables.orders, mockSchema.tables.users]}
        allTables={Object.values(mockSchema.tables)}
        schema={mockSchema}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText("✓ FK Verified")).toBeTruthy();
  });
});

describe("Split-View WorkspaceDock & 1-Click FK Suggestions", () => {
  it("renders suggested joins strip on canvas and keeps canvas visible when running query", async () => {
    const mockResults: QueryResultData = {
      columns: ["id", "user_id", "total"],
      rows: [{ id: 1, user_id: 10, total: 99.5 }],
      count: 1,
      durationMs: 8,
    };
    const handleExecute = vi.fn().mockResolvedValue(mockResults);

    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="orders"
        onExecuteQuery={handleExecute}
      />
    );

    // Verify 1-click FK suggestion is shown below the table card
    const suggestionBtn = screen.getByTestId("fk-join-suggestion-users");
    expect(suggestionBtn).toBeTruthy();
    expect(suggestionBtn.textContent).toContain("+ Join users");

    // Click Run Query
    const runBtn = screen.getByText("▶ Run Query");
    fireEvent.click(runBtn);

    // In split-view mode, canvas remains visible while results dock appears
    await waitFor(() => {
      expect(document.querySelector('[data-qb-panel="results"]')).not.toBeNull();
      expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
      expect(screen.getByText("⚡ Docked Workspace")).toBeTruthy();
    });

    // Sub-tab switching inside dock
    const chartDockTab = screen.getByRole("button", { name: /Visual Chart/ });
    fireEvent.click(chartDockTab);
    expect(screen.getByRole("region", { name: "Visual Chart Preview" })).toBeTruthy();

    const sqlDockTab = document.querySelector<HTMLButtonElement>('[data-qb-dock-tab="sql"]')!;
    expect(sqlDockTab).toBeTruthy();
    fireEvent.click(sqlDockTab);
    expect(screen.getAllByText(/FROM "orders"/i).length).toBeGreaterThan(0);

    // Collapse dock toggle
    const collapseBtn = screen.getByRole("button", { name: /Collapse/ });
    fireEvent.click(collapseBtn);
    expect(screen.queryByRole("region", { name: "Visual Chart Preview" })).toBeNull();
  });

  it("handles WorkspaceDock unstyled mode, copy SQL, full view, and dormant state", () => {
    const handleToggle = vi.fn();
    const handleSelectTab = vi.fn();
    const handleExpandFull = vi.fn();

    // 1. Dormant state when no results, not loading, and not open
    const { rerender } = render(
      <WorkspaceDock
        results={null}
        isLoading={false}
        currentSql="SELECT 1"
        isOpen={false}
        onToggleOpen={handleToggle}
        dockTab="results"
        onSelectDockTab={handleSelectTab}
        onExpandFullTab={handleExpandFull}
      />
    );
    expect(document.querySelector('[data-qb="workspace-dock"]')).toBeNull();

    // 2. Unstyled mode
    const mockResults: QueryResultData = {
      columns: ["id"],
      rows: [{ id: 1 }],
      count: 1,
      durationMs: 4,
    };
    rerender(
      <WorkspaceDock
        results={mockResults}
        isLoading={false}
        currentSql="SELECT id FROM users"
        isOpen={true}
        onToggleOpen={handleToggle}
        dockTab="sql"
        onSelectDockTab={handleSelectTab}
        onExpandFullTab={handleExpandFull}
        unstyled={true}
      />
    );

    expect(screen.getByText("Live SQL")).toBeTruthy();
    expect(screen.getByText("Full View")).toBeTruthy();
    fireEvent.click(screen.getByText("Full View"));
    expect(handleExpandFull).toHaveBeenCalledWith("sql");

    // Copy SQL
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
    const copyBtn = screen.getByText("Copy SQL");
    fireEvent.click(copyBtn);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("SELECT id FROM users");

    // Tab switching
    fireEvent.click(screen.getByText(/Results \(1\)/));
    expect(handleSelectTab).toHaveBeenCalledWith("results");

    fireEvent.click(screen.getByText("Chart"));
    expect(handleSelectTab).toHaveBeenCalledWith("chart");
  });
});
