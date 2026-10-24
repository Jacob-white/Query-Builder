import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryCanvas } from "../src/components/QueryCanvas";
import type { SchemaSnapshot, TableMeta } from "../src/types";
import { invalid } from "./helpers";

describe("QueryCanvas", () => {
  const usersTable: TableMeta = {
    name: "users",
    columns: [
      { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      { name: "email", data_type: "text", is_nullable: false, is_primary: false },
    ],
  };

  const ordersTable: TableMeta = {
    name: "orders",
    columns: [
      { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      { name: "amount", data_type: "numeric", is_nullable: false, is_primary: false },
    ],
  };

  const mockSchema: SchemaSnapshot = {
    tables: {
      users: usersTable,
      orders: ordersTable,
    },
    foreign_keys: [],
  };

  it("renders active tables and allows adding unjoined table from dropdown", () => {
    const handleAddTable = vi.fn();
    render(
      <QueryCanvas
        schema={mockSchema}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{}}
        orderedProjectionKeys={[]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        onToggleColumn={vi.fn()}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={handleAddTable}
        onUpdateColumnSelect={vi.fn()}
        onRemoveColumnProjection={vi.fn()}
        onJoinsChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onSortsChange={vi.fn()}
        onDistinctChange={vi.fn()}
        onLimitChange={vi.fn()}
      />
    );

    expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
    expect(screen.getByText("users")).toBeTruthy();

    const addSelect = screen.getByDisplayValue("+ Add Table to Canvas...");
    expect(screen.getAllByText("+ orders")).toHaveLength(2);
    fireEvent.change(addSelect, { target: { value: "orders" } });

    expect(handleAddTable).toHaveBeenCalledWith("orders");
  });

  it("renders projection manager with DISTINCT, LIMIT, and aggregation controls", () => {
    const handleDistinct = vi.fn();
    const handleLimit = vi.fn();
    const handleUpdateCol = vi.fn();
    const handleRemoveCol = vi.fn();

    render(
      <QueryCanvas
        schema={mockSchema}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{
          "users.id": { table: "users", name: "id", aggregate: undefined },
          "users.email": { table: "users", name: "email", aggregate: "COUNT" },
        }}
        orderedProjectionKeys={["users.id", "users.email"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        onToggleColumn={vi.fn()}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={vi.fn()}
        onUpdateColumnSelect={handleUpdateCol}
        onRemoveColumnProjection={handleRemoveCol}
        onJoinsChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onSortsChange={vi.fn()}
        onDistinctChange={handleDistinct}
        onLimitChange={handleLimit}
      />
    );

    expect(screen.getByText("✨ Selected Columns & Projections (2)")).toBeTruthy();
    expect(screen.getByText("users.id")).toBeTruthy();

    // Toggle DISTINCT
    const distinctCheckbox = screen.getByRole("checkbox", { name: /DISTINCT/i });
    fireEvent.click(distinctCheckbox);
    expect(handleDistinct).toHaveBeenCalledWith(true);

    // Change LIMIT
    const limitSelect = screen.getByDisplayValue("50");
    fireEvent.change(limitSelect, { target: { value: "100" } });
    expect(handleLimit).toHaveBeenCalledWith(100);

    // Update aggregate
    const aggSelect = screen.getByDisplayValue("(none)");
    fireEvent.change(aggSelect, { target: { value: "COUNT" } });
    expect(handleUpdateCol).toHaveBeenCalledWith("users.id", { aggregate: "COUNT" });

    // Remove projection pill
    const removeBtns = screen.getAllByTitle("Remove column");
    fireEvent.click(removeBtns[0]);
    expect(handleRemoveCol).toHaveBeenCalledWith("users.id");
  });

  it("calls onToggleColumn and onRemoveTable from table card actions", () => {
    const handleToggle = vi.fn();
    const handleRemove = vi.fn();

    render(
      <QueryCanvas
        schema={mockSchema}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{}}
        orderedProjectionKeys={[]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        onToggleColumn={handleToggle}
        onRemoveTable={handleRemove}
        onAddTableToCanvas={vi.fn()}
        onUpdateColumnSelect={vi.fn()}
        onRemoveColumnProjection={vi.fn()}
        onJoinsChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onSortsChange={vi.fn()}
        onDistinctChange={vi.fn()}
        onLimitChange={vi.fn()}
      />
    );

    // Click column to toggle
    fireEvent.click(screen.getByText("email"));
    expect(handleToggle).toHaveBeenCalledWith("users", "email");

    // Click table remove button
    const removeBtn = screen.getByTitle("Remove table");
    fireEvent.click(removeBtn);
    expect(handleRemove).toHaveBeenCalledWith("users");
  });

  it("handles undefined schema tables and missing items in orderedProjectionKeys", () => {
    render(
      <QueryCanvas
        schema={invalid<SchemaSnapshot>(undefined)}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{}}
        orderedProjectionKeys={["non_existent_key"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        onToggleColumn={vi.fn()}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={vi.fn()}
        onUpdateColumnSelect={vi.fn()}
        onRemoveColumnProjection={vi.fn()}
        onJoinsChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onSortsChange={vi.fn()}
        onDistinctChange={vi.fn()}
        onLimitChange={vi.fn()}
      />
    );

    expect(screen.getByText("✨ Selected Columns & Projections (1)")).toBeTruthy();
    expect(screen.queryByTitle("Remove column")).toBeNull();
  });

  it("renders custom limit option when limit is not in standard list", () => {
    const { container } = render(
      <QueryCanvas
        schema={mockSchema}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{ "users.id": { table: "users", name: "id" } }}
        orderedProjectionKeys={["users.id"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={42}
        onToggleColumn={vi.fn()}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={vi.fn()}
        onUpdateColumnSelect={vi.fn()}
        onRemoveColumnProjection={vi.fn()}
        onJoinsChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onSortsChange={vi.fn()}
        onDistinctChange={vi.fn()}
        onLimitChange={vi.fn()}
      />
    );
    expect(container.querySelector('option[value="42"]')).not.toBeNull();
  });

  it("renders Step Tab Bar, switches tabs, auto-opens Free-Form Query in Advanced mode, and supports bidirectional SQL editing and column reordering", () => {
    const handleRawSqlChange = vi.fn();
    const handleReorderProjections = vi.fn();

    const { container, rerender } = render(
      <QueryCanvas
        schema={mockSchema}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{
          "users.id": { table: "users", name: "id" },
          "users.email": { table: "users", name: "email" },
        }}
        orderedProjectionKeys={["users.id", "users.email"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        compiledSql="SELECT users.id, users.email FROM users LIMIT 50;"
        rawSql="SELECT users.id, users.email FROM users LIMIT 50;"
        isRawMode={false}
        onRawSqlChange={handleRawSqlChange}
        onReorderProjections={handleReorderProjections}
        isAdvancedMode={false}
        onToggleColumn={vi.fn()}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={vi.fn()}
        onUpdateColumnSelect={vi.fn()}
        onRemoveColumnProjection={vi.fn()}
        onJoinsChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onSortsChange={vi.fn()}
        onDistinctChange={vi.fn()}
        onLimitChange={vi.fn()}
      />
    );

    const stepTabs = container.querySelector('[data-qb="query-step-tabs"]');
    expect(stepTabs).not.toBeNull();

    // Default active tab is columns
    const columnsTab = container.querySelector('[data-qb-step-tab="columns"]');
    expect(columnsTab?.getAttribute("aria-pressed")).toBe("true");

    // Click Filters tab
    const filtersTab = container.querySelector('[data-qb-step-tab="filters"]') as HTMLElement;
    fireEvent.click(filtersTab);
    expect(filtersTab.getAttribute("aria-pressed")).toBe("true");

    // Toggling isAdvancedMode to true automatically switches to Free-Form Query tab
    rerender(
      <QueryCanvas
        schema={mockSchema}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{
          "users.id": { table: "users", name: "id" },
          "users.email": { table: "users", name: "email" },
        }}
        orderedProjectionKeys={["users.id", "users.email"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        compiledSql="SELECT users.id, users.email FROM users LIMIT 50;"
        rawSql="SELECT users.id, users.email FROM users LIMIT 50;"
        isRawMode={false}
        onRawSqlChange={handleRawSqlChange}
        onReorderProjections={handleReorderProjections}
        isAdvancedMode={true}
        onToggleColumn={vi.fn()}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={vi.fn()}
        onUpdateColumnSelect={vi.fn()}
        onRemoveColumnProjection={vi.fn()}
        onJoinsChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onSortsChange={vi.fn()}
        onDistinctChange={vi.fn()}
        onLimitChange={vi.fn()}
      />
    );

    const freeformTab = container.querySelector('[data-qb-step-tab="freeform"]');
    expect(freeformTab?.getAttribute("aria-pressed")).toBe("true");

    // Paste SQL into Free-Form SQL editor
    const sqlEditor = container.querySelector('[data-qb="free-form-sql-editor"]') as HTMLTextAreaElement;
    expect(sqlEditor).not.toBeNull();
    fireEvent.change(sqlEditor, {
      target: { value: "SELECT u.email, u.id FROM public.users u WHERE u.id > 10 LIMIT 25;" },
    });
    expect(handleRawSqlChange).toHaveBeenCalledWith(
      "SELECT u.email, u.id FROM public.users u WHERE u.id > 10 LIMIT 25;"
    );

    // Reorder column right from Free-Form column order strip
    const moveRightBtns = container.querySelectorAll('[data-qb="free-form-col-right"]');
    expect(moveRightBtns.length).toBe(2);
    fireEvent.click(moveRightBtns[0]);
    expect(handleReorderProjections).toHaveBeenCalledWith(["users.email", "users.id"]);
  });

  it("syncs columns, filters, sorts, and limit in standalone QueryCanvas free-form fallback and prioritizes FK tables in Joins", () => {
    const onToggleColumn = vi.fn();
    const onFiltersChange = vi.fn();
    const onSortsChange = vi.fn();
    const onLimitChange = vi.fn();

    const multiSchema: SchemaSnapshot = {
      tables: {
        users: usersTable,
        alpha_logs: {
          name: "alpha_logs",
          columns: [{ name: "id", data_type: "integer", is_nullable: false, is_primary: true }],
        },
        orders: {
          ...ordersTable,
          columns: [
            ...ordersTable.columns,
            { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
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

    const { container } = render(
      <QueryCanvas
        schema={multiSchema}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{
          "users.id": { table: "users", name: "id" },
        }}
        orderedProjectionKeys={["users.id"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        isAdvancedMode={true}
        onToggleColumn={onToggleColumn}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={vi.fn()}
        onUpdateColumnSelect={vi.fn()}
        onRemoveColumnProjection={vi.fn()}
        onJoinsChange={vi.fn()}
        onFiltersChange={onFiltersChange}
        onSortsChange={onSortsChange}
        onDistinctChange={vi.fn()}
        onLimitChange={onLimitChange}
      />
    );

    // Check that FK-linked table "orders" is ordered before non-FK "alpha_logs" in join pills
    const joinPills = Array.from(container.querySelectorAll('[data-qb="join-table-pill"]')).map(
      (el) => el.getAttribute("data-qb-table")
    );
    expect(joinPills[0]).toBe("orders");
    expect(joinPills).toContain("alpha_logs");

    // Enter SQL into standalone QueryCanvas without onRawSqlChange prop
    const sqlEditor = container.querySelector('[data-qb="free-form-sql-editor"]') as HTMLTextAreaElement;
    fireEvent.change(sqlEditor, {
      target: { value: "SELECT email FROM users WHERE email = 'a@b.com' ORDER BY email DESC LIMIT 15" },
    });

    // Should deselect users.id and select users.email
    expect(onToggleColumn).toHaveBeenCalledWith("users", "id");
    expect(onToggleColumn).toHaveBeenCalledWith("users", "email");
    expect(onFiltersChange).toHaveBeenCalled();
    expect(onSortsChange).toHaveBeenCalled();
    expect(onLimitChange).toHaveBeenCalledWith(15);
  });

  it("reorders columns via HTML5 drag-and-drop on projection-item and free-form-col-chip", () => {
    const handleReorderProjections = vi.fn();

    const { container } = render(
      <QueryCanvas
        schema={mockSchema}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{
          "users.id": { table: "users", name: "id" },
          "users.email": { table: "users", name: "email" },
        }}
        orderedProjectionKeys={["users.id", "users.email"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        isAdvancedMode={true}
        onReorderProjections={handleReorderProjections}
        onToggleColumn={vi.fn()}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={vi.fn()}
        onUpdateColumnSelect={vi.fn()}
        onRemoveColumnProjection={vi.fn()}
        onJoinsChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onSortsChange={vi.fn()}
        onDistinctChange={vi.fn()}
        onLimitChange={vi.fn()}
      />
    );

    // 1. Drag projection-item #0 onto projection-item #1
    const projItems = container.querySelectorAll('[data-qb="projection-item"]');
    expect(projItems.length).toBe(2);
    expect(projItems[0].getAttribute("draggable")).toBe("true");
    fireEvent.dragStart(projItems[0]);
    fireEvent.dragEnter(projItems[1]);
    fireEvent.dragOver(projItems[1]);
    fireEvent.drop(projItems[1]);
    fireEvent.dragEnd(projItems[0]);
    expect(handleReorderProjections).toHaveBeenCalledWith(["users.email", "users.id"]);

    handleReorderProjections.mockClear();

    // 2. Drag free-form-col-chip #1 onto free-form-col-chip #0
    const freeFormChips = container.querySelectorAll('[data-qb="free-form-col-chip"]');
    expect(freeFormChips.length).toBe(2);
    expect(freeFormChips[1].getAttribute("draggable")).toBe("true");
    fireEvent.dragStart(freeFormChips[1]);
    fireEvent.dragEnter(freeFormChips[0]);
    fireEvent.dragOver(freeFormChips[0]);
    fireEvent.drop(freeFormChips[0]);
    fireEvent.dragEnd(freeFormChips[1]);
    expect(handleReorderProjections).toHaveBeenCalledWith(["users.email", "users.id"]);
  });

  it("supports studioMode and hideSummaryBar to visually hide QuerySummaryBar with srOnlyStyle while keeping DOM selectors", () => {
    const { container, rerender } = render(
      <QueryCanvas
        schema={mockSchema}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{ "users.id": { table: "users", name: "id" } }}
        orderedProjectionKeys={["users.id"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        studioMode={true}
        onToggleColumn={vi.fn()}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={vi.fn()}
        onUpdateColumnSelect={vi.fn()}
        onRemoveColumnProjection={vi.fn()}
        onJoinsChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onSortsChange={vi.fn()}
        onDistinctChange={vi.fn()}
        onLimitChange={vi.fn()}
      />
    );

    const canvas = container.querySelector('[data-qb="canvas"]');
    expect(canvas?.getAttribute("data-qb-studio")).toBe("true");

    const summaryBar = container.querySelector('[data-qb="query-summary-bar"]') as HTMLElement;
    expect(summaryBar).toBeTruthy();
    expect(summaryBar.getAttribute("data-qb-hidden")).toBe("true");
    expect(summaryBar.style.position).toBe("absolute");
    expect(summaryBar.style.width).toBe("1px");

    // All selectors inside summary bar remain accessible
    expect(container.querySelector('[data-qb="query-summary-text"]')).toBeTruthy();

    // Query Step Tabs are the prominent top navigation
    const stepTabs = container.querySelector('[data-qb="query-step-tabs"]');
    expect(stepTabs).toBeTruthy();

    // Re-render with studioMode=false, hideSummaryBar=true
    rerender(
      <QueryCanvas
        schema={mockSchema}
        activeTables={[usersTable]}
        primaryTable="users"
        selectedColumns={{ "users.id": { table: "users", name: "id" } }}
        orderedProjectionKeys={["users.id"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        studioMode={false}
        hideSummaryBar={true}
        onToggleColumn={vi.fn()}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={vi.fn()}
        onUpdateColumnSelect={vi.fn()}
        onRemoveColumnProjection={vi.fn()}
        onJoinsChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onSortsChange={vi.fn()}
        onDistinctChange={vi.fn()}
        onLimitChange={vi.fn()}
      />
    );

    const summaryBarHidden = container.querySelector('[data-qb="query-summary-bar"]') as HTMLElement;
    expect(summaryBarHidden.getAttribute("data-qb-hidden")).toBe("true");
    expect(summaryBarHidden.style.position).toBe("absolute");
  });
});


