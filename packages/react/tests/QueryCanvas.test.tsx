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
});
