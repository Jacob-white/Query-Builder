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

  it("exercises inline pill strips, quick actions, table column reorder, and standalone free-form SQL branches", () => {
    const onToggleColumn = vi.fn();
    const onReorderProjections = vi.fn();
    const onUpdateColumnSelect = vi.fn();
    const onRemoveColumnProjection = vi.fn();
    const onJoinsChange = vi.fn();
    const onFiltersChange = vi.fn();
    const onSortsChange = vi.fn();
    const onLimitChange = vi.fn();
    const onAddTableToCanvas = vi.fn();
    const onAddJoin = vi.fn();
    const onSyncWithVisualCanvas = vi.fn();
    const onAddCalculatedField = vi.fn();
    const onRemoveWindowFunction = vi.fn();

    const richUsersTable = {
      name: "users",
      columns: [
        { name: "id", data_type: "uuid", is_nullable: false, is_primary: true },
        { name: "email", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "active", data_type: "boolean", is_nullable: false, is_primary: false },
        { name: "meta", data_type: "jsonb", is_nullable: true, is_primary: false },
        { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
        { name: "score", data_type: "integer", is_nullable: false, is_primary: false },
        { name: "role", data_type: "enum", is_nullable: false, is_primary: false, enums: ["admin", "user"] },
        { name: "tags", data_type: "text[]", is_nullable: true, is_primary: false },
        { name: "custom_col", data_type: "geography", is_nullable: true, is_primary: false },
      ],
      metrics: [
        { name: "total_users", title: "Total Users", aggregation: "count" as const, sqlExpression: "id" },
      ],
    };

    const bigSchema: SchemaSnapshot = {
      tables: {
        users: richUsersTable,
        orders: {
          ...ordersTable,
          columns: [
            ...ordersTable.columns,
            { name: "user_id", data_type: "uuid", is_nullable: false, is_primary: false },
          ],
        },
        t3: { name: "t3", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }] },
        t4: { name: "t4", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }] },
        t5: { name: "t5", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }] },
        t6: { name: "t6", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }] },
        t7: { name: "t7", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }] },
        t8: { name: "t8", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }] },
      },
      foreign_keys: [
        { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
        { table: "t3", column: "id", foreign_table: "users", foreign_column: "id" },
        { table: "t4", column: "id", foreign_table: "users", foreign_column: "id" },
        { table: "t5", column: "id", foreign_table: "users", foreign_column: "id" },
        { table: "t6", column: "id", foreign_table: "users", foreign_column: "id" },
      ],
    };

    const { container } = render(
      <QueryCanvas
        schema={bigSchema}
        activeTables={[richUsersTable, bigSchema.tables.orders]}
        primaryTable="users"
        selectedColumns={{
          "users.id": { table: "users", name: "id", alias: "user_id_alias" },
          "users.email": { table: "users", name: "email" },
        }}
        orderedProjectionKeys={["users.id", "users.email"]}
        joins={[
          {
            id: "j1",
            table: "orders",
            type: "LEFT JOIN",
            left_table: "users",
            left_col: "email",
            right_col: "total",
          },
        ]}
        filters={[
          { id: "f1", combiner: "AND", tablePrefix: "users", column: "role", operator: "=", value: "admin" },
          { id: "f2", combiner: "AND", tablePrefix: "users", column: "email", operator: "LIKE", value: "%a%" },
        ]}
        sorts={[
          { id: "s1", tablePrefix: "users", column: "id", direction: "ASC" },
          { id: "s2", tablePrefix: "users", column: "email", direction: "DESC" },
        ]}
        windowFunctions={[{ function: "ROW_NUMBER", alias: "rn", partition_by: ["id"], order_by: [] }]}
        isDistinct={false}
        limit={33}
        compiledSql="SELECT users.id, users.email FROM users"
        onToggleColumn={onToggleColumn}
        onRemoveTable={vi.fn()}
        onAddTableToCanvas={onAddTableToCanvas}
        onAddJoin={onAddJoin}
        onReorderProjections={onReorderProjections}
        onUpdateColumnSelect={onUpdateColumnSelect}
        onRemoveColumnProjection={onRemoveColumnProjection}
        onAddCalculatedField={onAddCalculatedField}
        onRemoveWindowFunction={onRemoveWindowFunction}
        onSyncWithVisualCanvas={onSyncWithVisualCanvas}
        onJoinsChange={onJoinsChange}
        onFiltersChange={onFiltersChange}
        onSortsChange={onSortsChange}
        onDistinctChange={vi.fn()}
        onLimitChange={onLimitChange}
      />
    );

    // 1. Standalone Free-Form SQL with JOIN, new table, SELECT *, and sync button
    const sqlEditor = container.querySelector('[data-qb="free-form-sql-editor"]') as HTMLTextAreaElement;
    fireEvent.change(sqlEditor, {
      target: {
        value:
          "SELECT t3.id, users.email FROM t3 LEFT JOIN orders ON t3.id = orders.id WHERE t3.id IN (1, 2) ORDER BY t3.id ASC LIMIT 10",
      },
    });
    expect(onAddTableToCanvas).toHaveBeenCalledWith("t3");
    expect(onReorderProjections).toHaveBeenCalled();
    expect(onJoinsChange).toHaveBeenCalled();

    fireEvent.change(sqlEditor, { target: { value: "SELECT * FROM users" } });
    fireEvent.click(container.querySelector('[data-qb="btn-sync-free-form-sql"]')!);
    expect(onSyncWithVisualCanvas).toHaveBeenCalled();
    fireEvent.click(container.querySelector('[data-qb="btn-copy-free-form-sql"]')!);

    // Breakdown pills & live SQL preview
    fireEvent.click(container.querySelector('[data-qb="breakdown-pill-table"]')!);
    fireEvent.click(container.querySelector('[data-qb="breakdown-pill-joins"]')!);
    fireEvent.click(container.querySelector('[data-qb="breakdown-pill-filters"]')!);
    fireEvent.click(container.querySelector('[data-qb="breakdown-pill-sorts"]')!);
    fireEvent.click(container.querySelector('[data-qb="btn-toggle-live-sql"]')!);
    fireEvent.click(container.querySelector('[data-qb="btn-copy-live-sql"]')!);

    // Free-form chip buttons (left, right, remove)
    const ffLeft = container.querySelectorAll('[data-qb="free-form-col-left"]');
    if (ffLeft[1]) fireEvent.click(ffLeft[1]);
    const ffRemove = container.querySelector('[data-qb="free-form-col-remove"]');
    if (ffRemove) fireEvent.click(ffRemove);
    const ffAdd = container.querySelector('[data-qb="free-form-col-add"]');
    if (ffAdd) fireEvent.click(ffAdd);

    // 2. Add Table strip & search & >4 suggested joins popover
    fireEvent.click(container.querySelector('[data-qb="btn-toggle-add-table-strip"]')!);
    const addTblInput = container.querySelector('[data-qb="add-table-pill-strip"] input') as HTMLInputElement;
    if (addTblInput) {
      fireEvent.change(addTblInput, { target: { value: "t7" } });
    }
    const addTblPill = container.querySelector('[data-qb="add-table-pill"]');
    if (addTblPill) fireEvent.click(addTblPill);

    const moreJoinsBtn = container.querySelector('[data-qb="btn-more-suggested-joins"]');
    if (moreJoinsBtn) fireEvent.click(moreJoinsBtn);

    // 3. Projection inline fx pills, move left/right, alias input, window function remove, limit pill
    const fxToggle = container.querySelector('[data-qb="projection-fx-toggle"]')!;
    fireEvent.click(fxToggle);
    const inlinePills = container.querySelectorAll('[data-qb="projection-inline-pills"] button');
    if (inlinePills[1]) fireEvent.click(inlinePills[1]); // aggregate pill
    fireEvent.click(fxToggle);
    const inlinePills2 = container.querySelectorAll('[data-qb="projection-inline-pills"] button');
    if (inlinePills2[inlinePills2.length - 1]) fireEvent.click(inlinePills2[inlinePills2.length - 1]); // time grain pill

    const moveLeftBtn = container.querySelector('[data-qb="projection-move-left"]');
    if (moveLeftBtn) fireEvent.click(moveLeftBtn);
    const moveRightBtn = container.querySelector('[data-qb="projection-move-right"]');
    if (moveRightBtn) fireEvent.click(moveRightBtn);
    const aliasInput = container.querySelector('[data-qb="projection-alias-input"]') as HTMLInputElement;
    fireEvent.change(aliasInput, { target: { value: "my_id" } });
    const limitPill = container.querySelector('[data-qb="limit-pill"][data-qb-limit="25"]');
    if (limitPill) fireEvent.click(limitPill);
    const wfRemoveBtn = container.querySelector('[data-qb="window-function-chip"] button');
    if (wfRemoveBtn) fireEvent.click(wfRemoveBtn);
    expect(onRemoveWindowFunction).toHaveBeenCalledWith(0);

    // 4. TableCard hover/focus/keyboard/drag-and-drop/quick actions/metrics
    const colRows = container.querySelectorAll('[data-qb="table-card-column-row"]');
    colRows.forEach((row) => {
      fireEvent.mouseEnter(row);
      fireEvent.focus(row);
      fireEvent.blur(row);
      fireEvent.mouseLeave(row);
    });
    if (colRows[0] && colRows[1]) {
      fireEvent.keyDown(colRows[0], { key: "Enter" });
      fireEvent.dragStart(colRows[0]);
      fireEvent.dragOver(colRows[1]);
      fireEvent.dragLeave(colRows[1]);
      fireEvent.drop(colRows[1]);
      fireEvent.dragEnd(colRows[0]);
    }
    const quickFilterBtns = container.querySelectorAll('[data-qb="col-btn-filter"]');
    if (quickFilterBtns[0]) fireEvent.click(quickFilterBtns[0]);
    const quickSortBtns = container.querySelectorAll('[data-qb="col-btn-sort"]');
    if (quickSortBtns[0]) fireEvent.click(quickSortBtns[0]); // ASC -> DESC
    if (quickSortBtns[1]) fireEvent.click(quickSortBtns[1]); // DESC -> remove
    if (quickSortBtns[2]) fireEvent.click(quickSortBtns[2]); // add new ASC
    const quickAggBtns = container.querySelectorAll('[data-qb="col-btn-aggregate"]');
    if (quickAggBtns[2]) fireEvent.click(quickAggBtns[2]);
    const metricRow = container.querySelector('[data-qb="table-card-metric-row"]');
    if (metricRow) fireEvent.click(metricRow);
    const metricCb = container.querySelector('[data-qb="table-card-metric-checkbox"]');
    if (metricCb) fireEvent.click(metricCb);

    // 5. TableJoinEditor pills & inputs
    const joinLeftPill = container.querySelector('[data-qb="join-left-col-pill"]');
    if (joinLeftPill) fireEvent.click(joinLeftPill);
    const joinRightPill = container.querySelector('[data-qb="join-right-col-pill"]');
    if (joinRightPill) fireEvent.click(joinRightPill);
    const joinExpandBtn = container.querySelector('[data-qb="join-expand-cols"]');
    if (joinExpandBtn) fireEvent.click(joinExpandBtn);
    const joinLeftInput = container.querySelector('[data-qb="join-left-col"]') as HTMLInputElement;
    if (joinLeftInput) fireEvent.change(joinLeftInput, { target: { value: "users.id" } });
    const joinRightInput = container.querySelector('[data-qb="join-right-col"]') as HTMLInputElement;
    if (joinRightInput) fireEvent.change(joinRightInput, { target: { value: "orders.user_id" } });

    // 6. TableFiltersEditor pills & search & badge reassignment & enum pill
    const filterColSearch = container.querySelector('[data-qb="filter-column-search"]') as HTMLInputElement;
    if (filterColSearch) fireEvent.change(filterColSearch, { target: { value: "email" } });
    const filterColBadge = container.querySelector('[data-qb="filter-column-badge"]');
    if (filterColBadge) fireEvent.click(filterColBadge);
    const filterColPill = container.querySelector('[data-qb="filter-column-pill"]');
    if (filterColPill) {
      fireEvent.click(filterColPill); // reassigns
      fireEvent.click(filterColPill); // adds new
    }
    const filterCombOr = container.querySelector('[data-qb="filter-combiner-or"]');
    if (filterCombOr) fireEvent.click(filterCombOr);
    const filterParenOpen = container.querySelector('[data-qb="filter-paren-open"]');
    if (filterParenOpen) fireEvent.click(filterParenOpen);
    const filterParenClose = container.querySelector('[data-qb="filter-paren-close"]');
    if (filterParenClose) fireEvent.click(filterParenClose);
    const filterOpPill = container.querySelector('[data-qb="filter-operator-pill"][data-qb-operator="!="]');
    if (filterOpPill) fireEvent.click(filterOpPill);
    const filterEnumPill = container.querySelector('[data-qb="filter-enum-pill"]');
    if (filterEnumPill) fireEvent.click(filterEnumPill);

    // 7. TableSortsEditor pills & search & badge reassignment & drag-and-drop & move up/down
    const sortColSearch = container.querySelector('[data-qb="sort-column-search"]') as HTMLInputElement;
    if (sortColSearch) fireEvent.change(sortColSearch, { target: { value: "email" } });
    const sortColBadge = container.querySelector('[data-qb="sort-column-badge"]');
    if (sortColBadge) fireEvent.click(sortColBadge);
    const sortColPill = container.querySelector('[data-qb="sort-column-pill"]');
    if (sortColPill) {
      fireEvent.click(sortColPill); // reassigns
      fireEvent.click(sortColPill); // toggles existing
    }
    const sortDirAsc = container.querySelectorAll('[data-qb="sort-dir-asc"]');
    if (sortDirAsc[1]) fireEvent.click(sortDirAsc[1]);
    const sortDirDesc = container.querySelectorAll('[data-qb="sort-dir-desc"]');
    if (sortDirDesc[0]) fireEvent.click(sortDirDesc[0]);
    const sortMoveDown = container.querySelectorAll('[data-qb="sort-move-down"]');
    if (sortMoveDown[0]) fireEvent.click(sortMoveDown[0]);
    const sortMoveUp = container.querySelectorAll('[data-qb="sort-move-up"]');
    if (sortMoveUp[1]) fireEvent.click(sortMoveUp[1]);
    const sortRows = container.querySelectorAll('[data-qb="sort-row"]');
    if (sortRows[0] && sortRows[1]) {
      fireEvent.dragStart(sortRows[0]);
      fireEvent.dragOver(sortRows[1]);
      fireEvent.dragLeave(sortRows[1]);
      fireEvent.drop(sortRows[1]);
      fireEvent.dragEnd(sortRows[0]);
    }

    // 8. Summary bar navigation chips, clear clauses, and calculated field editor modal
    for (const sec of ["table", "columns", "joins", "filters", "sorts"]) {
      const navChip = container.querySelector(`[data-qb-chip="${sec}"]`);
      if (navChip) fireEvent.click(navChip);
    }
    const clearAllBtn = container.querySelector('[data-qb="btn-clear-clauses"]');
    if (clearAllBtn) fireEvent.click(clearAllBtn);

    const calcFieldBtn = container.querySelector('[data-qb="btn-open-calculated-field"]');
    if (calcFieldBtn) {
      fireEvent.click(calcFieldBtn);
      fireEvent.keyDown(window, { key: "Escape" });
    }
  });
});


