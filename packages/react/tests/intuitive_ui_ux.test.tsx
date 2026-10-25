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
    const extraTables: TableMeta[] = [
      ...Object.values(mockSchema.tables),
      {
        name: "profiles",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
        ],
      },
      {
        name: "audit_logs",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        ],
      },
      {
        name: "unjoined_logs",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        ],
      },
    ];
    const { container } = render(
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
          {
            id: "j2",
            table: "profiles",
            type: "LEFT JOIN",
            left_table: "orders",
            left_col: "user_id",
            right_col: "user_id",
          },
          {
            id: "j3",
            table: "audit_logs",
            type: "LEFT JOIN",
            left_table: "orders",
            left_col: "id",
            right_col: "id",
          },
        ]}
        activeTables={[mockSchema.tables.orders]}
        allTables={extraTables}
        schema={mockSchema}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText("✓ FK Verified")).toBeTruthy();
    expect(screen.getAllByText("✓ Confirmed Join").length).toBeGreaterThan(0);
    expect(screen.getAllByText("⇄ Logical Join").length).toBeGreaterThan(0);
    expect(screen.getAllByText("○ No Dedicated Join").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-qb="join-tier-filter-bar"]')).not.toBeNull();
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

  it("joins the clicked target FK table in a 2-table schema and caps inline suggestions at 4 with a searchable popover", () => {
    const sixTableSchema: SchemaSnapshot = {
      tables: {
        hub: {
          name: "hub",
          columns: [{ name: "id", data_type: "integer", is_nullable: false, is_primary: true }],
        },
        t1: { name: "t1", columns: [{ name: "hub_id", data_type: "integer", is_nullable: false, is_primary: false }] },
        t2: { name: "t2", columns: [{ name: "hub_id", data_type: "integer", is_nullable: false, is_primary: false }] },
        t3: { name: "t3", columns: [{ name: "hub_id", data_type: "integer", is_nullable: false, is_primary: false }] },
        t4: { name: "t4", columns: [{ name: "hub_id", data_type: "integer", is_nullable: false, is_primary: false }] },
        t5: { name: "t5", columns: [{ name: "hub_id", data_type: "integer", is_nullable: false, is_primary: false }] },
        t6: { name: "t6", columns: [{ name: "hub_id", data_type: "integer", is_nullable: false, is_primary: false }] },
      },
      foreign_keys: [
        { table: "t1", column: "hub_id", foreign_table: "hub", foreign_column: "id" },
        { table: "t2", column: "hub_id", foreign_table: "hub", foreign_column: "id" },
        { table: "t3", column: "hub_id", foreign_table: "hub", foreign_column: "id" },
        { table: "t4", column: "hub_id", foreign_table: "hub", foreign_column: "id" },
        { table: "t5", column: "hub_id", foreign_table: "hub", foreign_column: "id" },
        { table: "t6", column: "hub_id", foreign_table: "hub", foreign_column: "id" },
      ],
    };

    const { unmount } = render(
      <VisualQueryBuilder schema={sixTableSchema} initialTable="hub" />,
    );

    // Inline suggestions capped at 4; "+2 more FK joins ▾" button rendered
    expect(screen.getByTestId("fk-join-suggestion-t1")).toBeTruthy();
    expect(screen.getByTestId("fk-join-suggestion-t4")).toBeTruthy();
    expect(screen.queryByTestId("fk-join-suggestion-t6")).toBeNull();

    const moreBtn = document.querySelector<HTMLButtonElement>('[data-qb="btn-more-suggested-joins"]')!;
    expect(moreBtn).toBeTruthy();
    expect(moreBtn.textContent).toContain("+2 more FK joins");
    fireEvent.click(moreBtn);

    // Popover opens and shows t5, t6
    const searchBox = screen.getByPlaceholderText(/Search 2 more FK tables/i);
    fireEvent.change(searchBox, { target: { value: "t6" } });
    const t6Btn = screen.getByTestId("fk-join-suggestion-t6");
    fireEvent.click(t6Btn);

    // t6 is now joined onto hub!
    expect(screen.getByText("📋 Active Tables in Query (2)")).toBeTruthy();
    expect(screen.getByText("✓ FK Verified")).toBeTruthy();
    unmount();

    // Also test 2-table schema where clicking "+ Join users" joins orders -> users
    render(<VisualQueryBuilder schema={mockSchema} initialTable="orders" />);
    expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
    expect(screen.getByText("✨ Projections: All Columns (SELECT *)")).toBeTruthy();
    expect(document.querySelector('[data-qb="checkbox-distinct"]')).not.toBeNull();
    expect(document.querySelector('[data-qb="input-limit"]')).not.toBeNull();

    fireEvent.click(screen.getByTestId("fk-join-suggestion-users"));
    expect(screen.getByText("📋 Active Tables in Query (2)")).toBeTruthy();
    expect(screen.getByText("✓ FK Verified")).toBeTruthy();
  });

  it("filters TableCard columns to selected-only when Selected pill is clicked and auto-resets when selection empties", () => {
    const wideTable: TableMeta = {
      name: "wide_tbl",
      columns: [
        { name: "c1", data_type: "int", is_nullable: false, is_primary: true },
        { name: "c2", data_type: "text", is_nullable: true, is_primary: false },
        { name: "c3", data_type: "text", is_nullable: true, is_primary: false },
        { name: "c4", data_type: "text", is_nullable: true, is_primary: false },
        { name: "c5", data_type: "text", is_nullable: true, is_primary: false },
        { name: "c6", data_type: "text", is_nullable: true, is_primary: false },
        { name: "c7", data_type: "text", is_nullable: true, is_primary: false },
      ],
    };

    const { rerender } = render(
      <TableCard
        table={wideTable}
        selectedColumns={{
          "wide_tbl.c1": { table: "wide_tbl", name: "c1" },
          "wide_tbl.c5": { table: "wide_tbl", name: "c5" },
        }}
        onToggleColumn={vi.fn()}
      />,
    );

    expect(screen.getByText("c2")).toBeTruthy();
    const selectedPill = document.querySelector<HTMLButtonElement>('[data-qb="table-card-filter-selected"]')!;
    expect(selectedPill).toBeTruthy();
    expect(selectedPill.textContent).toContain("All (7) | Selected (2)");
    fireEvent.click(selectedPill);

    expect(screen.getByText("c1")).toBeTruthy();
    expect(screen.getByText("c5")).toBeTruthy();
    expect(screen.queryByText("c2")).toBeNull();

    // When all columns are unchecked (selectedColumns becomes {}), showSelectedOnly auto-resets so all columns reappear
    rerender(
      <TableCard
        table={wideTable}
        selectedColumns={{}}
        onToggleColumn={vi.fn()}
      />,
    );
    expect(screen.getByText("c2")).toBeTruthy();
    expect(selectedPill.textContent).toBe("All (7) | Selected (0)");
  });

  it("guards against duplicate FK join clicks and joins unjoined canvas tables as targets", () => {
    const threeTableSchema: SchemaSnapshot = {
      tables: {
        orders: mockSchema.tables.orders,
        users: mockSchema.tables.users,
        audit_logs: {
          name: "audit_logs",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          ],
        },
      },
      foreign_keys: [
        { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
        { table: "audit_logs", column: "user_id", foreign_table: "users", foreign_column: "id" },
      ],
    };

    render(<VisualQueryBuilder schema={threeTableSchema} initialTable="orders" />);

    // Click 🔗 users on orders.user_id once -> joins users
    const fkBtn = screen.getByText("🔗 users");
    fireEvent.click(fkBtn);
    expect(screen.getByText("📋 Active Tables in Query (2)")).toBeTruthy();

    // Click 🔗 users on orders.user_id a second time -> should NOT join audit_logs or duplicate users
    fireEvent.click(screen.getAllByText("🔗 users")[0]);
    expect(screen.getByText("📋 Active Tables in Query (2)")).toBeTruthy();
    expect(screen.queryByText("audit_logs")).toBeNull();
  });

  it("executes overrideSpec immediately when passed to ref.execute(overrideSpec) without waiting for re-render", async () => {
    const builderRef = React.createRef<import("../src/types").VisualQueryBuilderRef>();
    const handleExecute = vi.fn().mockResolvedValue({
      columns: ["id", "email"],
      rows: [{ id: 1, email: "a@b.com" }],
      count: 1,
      durationMs: 2,
    });

    render(
      <VisualQueryBuilder
        ref={builderRef}
        schema={mockSchema}
        initialTable="orders"
        compactHeader={true}
        hideNlqBar={true}
        onExecuteQuery={handleExecute}
      />,
    );

    const nextSpec = {
      table: "users",
      columns: ["users.id", "users.email"],
      joins: [],
      filters: [],
      filter_join: "AND" as const,
      order_by: [],
      distinct: false,
      limit: 10,
    };

    await React.act(async () => {
      builderRef.current!.setSpec(nextSpec);
      await builderRef.current!.execute(nextSpec);
    });

    expect(handleExecute).toHaveBeenCalledTimes(1);
    const [executedSql, executedSpec] = handleExecute.mock.calls[0];
    expect(executedSql).toContain('FROM "users"');
    expect(executedSpec.table).toBe("users");
  });

  it("collapses idle column quick-actions to zero width, prevents reverse-FK pills on PK columns, and uses 3-col grid when clauses are empty", () => {
    const { container } = render(
      <VisualQueryBuilder schema={mockSchema} initialTable="users" />,
    );

    // 1. users.id is referenced by orders.user_id (reverse FK), so it should NOT render an inline col-btn-fk-join pill on users.id
    expect(container.querySelector('[data-qb="col-btn-fk-join"]')).toBeNull();
    // Instead, orders is offered in Suggested Joins bar
    const suggestedOrders = screen.getByTestId("fk-join-suggestion-orders");
    expect(suggestedOrders.textContent).toBe("+ Join orders");
    expect(suggestedOrders.getAttribute("title")).toContain("orders.user_id → users.id");

    // 2. Per-column quick-action buttons remain visually hidden (srOnlyStyle) even on row hover so TableCard is a focused column selector
    const firstRow = container.querySelector('[data-qb="table-card-column-row"]') as HTMLElement;
    const filterBtn = firstRow.querySelector('[data-qb="col-btn-filter"]') as HTMLElement;
    expect(filterBtn.style.width).toBe("1px");
    fireEvent.mouseEnter(firstRow);
    expect(filterBtn.style.width).toBe("1px");
    fireEvent.mouseLeave(firstRow);
    expect(filterBtn.style.width).toBe("1px");

    // 3. Clause editors grid is 3-column when empty, and expands to 1fr when a filter is added
    const clauseGrid = container.querySelector('[data-qb="clause-editors-grid"]') as HTMLElement;
    expect(clauseGrid.style.gridTemplateColumns).toContain("minmax(250px, 1fr)");
    fireEvent.click(filterBtn);
    expect(clauseGrid.style.gridTemplateColumns).toBe("1fr");

    // 4. TableCard uses 3-column grid, 8px 12px cell padding, short type tags, and supports collapsing the column grid
    const colGrid = container.querySelector('[data-qb="table-card-columns-list"]') as HTMLElement;
    expect(colGrid.style.gridTemplateColumns).toBe("repeat(3, minmax(240px, 1fr))");
    expect(firstRow.style.padding).toBe("8px 12px");
    const allRows = container.querySelectorAll('[data-qb="table-card-column-row"]');
    expect(allRows[1].textContent).toContain("str");

    const collapseBtn = container.querySelector('[data-qb="table-card-btn-collapse-columns"]') as HTMLButtonElement;
    expect(collapseBtn).toBeTruthy();
    expect(collapseBtn.textContent).toContain("Hide columns");
    fireEvent.click(collapseBtn);
    expect(colGrid.style.width).toBe("1px");
    expect(collapseBtn.textContent).toContain("Columns (2)");
    fireEvent.click(collapseBtn);
    expect(colGrid.style.display).toBe("grid");

    // 5. Clicking Select all in VisualQueryBuilder selects all columns (not just the last one), and Clear clears all
    const selectAllBtn = container.querySelector('[data-qb="table-card-btn-select-all"]') as HTMLButtonElement;
    const clearAllBtn = container.querySelector('[data-qb="table-card-btn-clear-all"]') as HTMLButtonElement;
    fireEvent.click(selectAllBtn);
    expect(screen.getByTitle("2 of 2 columns selected")).toBeTruthy();
    expect(container.querySelectorAll('[data-qb="projection-item"]').length).toBe(2);
    expect(clearAllBtn.textContent).toContain("Clear (2)");

    fireEvent.click(clearAllBtn);
    expect(screen.getByTitle("0 of 2 columns selected")).toBeTruthy();
    expect(container.querySelectorAll('[data-qb="projection-item"]').length).toBe(0);
  });

  it("renders plain-English non-SQL labels across projections, joins, filters, sorts, and primary keys", () => {
    const { container } = render(
      <div>
        <VisualQueryBuilder schema={mockSchema} initialTable="orders" />
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
          activeTables={[mockSchema.tables.orders]}
          allTables={Object.values(mockSchema.tables)}
          schema={mockSchema}
          onChange={vi.fn()}
        />
        <TableFiltersEditor
          filters={[
            {
              id: "f1",
              combiner: "AND",
              tablePrefix: "orders",
              column: "status",
              operator: "=",
              value: "PAID",
            },
          ]}
          activeTables={[mockSchema.tables.orders]}
          onChange={vi.fn()}
        />
        <TableSortsEditor
          sorts={[
            {
              id: "s1",
              tablePrefix: "orders",
              column: "total",
              direction: "DESC",
            },
          ]}
          activeTables={[mockSchema.tables.orders]}
          onChange={vi.fn()}
        />
      </div>,
    );

    expect(screen.getAllByText("Columns to show: All columns").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Unique rows only").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Max rows:").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Keep all rows (LEFT)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Matches only (INNER)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("matched where").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Keep rows where").length).toBeGreaterThan(0);
    expect(screen.getAllByText("equals (=)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("contains text").length).toBeGreaterThan(0);
    expect(screen.getAllByText("is empty").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Ascending ↑").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Descending ↓").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-qb="table-card-badge-pk"]')?.textContent).toContain("ID");
  });
});


