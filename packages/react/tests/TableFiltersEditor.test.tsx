import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TableFiltersEditor } from "../src/components/TableFiltersEditor";
import type { TableMeta, VisualFilter } from "../src/types";

describe("TableFiltersEditor", () => {
  const activeTables: TableMeta[] = [
    {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "email", data_type: "text", is_nullable: false, is_primary: false },
      ],
    },
    {
      name: "orders",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "amount", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
  ];

  it("renders empty state message when no filters exist", () => {
    render(
      <TableFiltersEditor
        filters={[]}
        activeTables={activeTables}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText(/No filters applied/i)).toBeTruthy();
    expect(screen.getByText("⚡ Filter Conditions (0)")).toBeTruthy();
  });

  it("adds a new filter with first available column when + Add Filter is clicked", () => {
    const handleChange = vi.fn();
    render(
      <TableFiltersEditor
        filters={[]}
        activeTables={activeTables}
        onChange={handleChange}
      />
    );

    fireEvent.click(screen.getByText("+ Add Filter"));
    expect(handleChange).toHaveBeenCalledOnce();
    const addedFilter = handleChange.mock.calls[0][0][0] as VisualFilter;
    expect(addedFilter.tablePrefix).toBe("users");
    expect(addedFilter.column).toBe("id");
    expect(addedFilter.operator).toBe("=");
    expect(addedFilter.value).toBe("");
  });

  it("renders existing filters with AND conjunction for subsequent rows", () => {
    const filters: VisualFilter[] = [
      { id: "f1", tablePrefix: "users", column: "id", operator: "=", value: "100" },
      { id: "f2", tablePrefix: "orders", column: "amount", operator: ">", value: "50" },
    ];

    render(
      <TableFiltersEditor
        filters={filters}
        activeTables={activeTables}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText("⚡ Filter Conditions (2)")).toBeTruthy();
    expect(screen.getByText("AND")).toBeTruthy();
    expect(screen.getByDisplayValue("100")).toBeTruthy();
    expect(screen.getByDisplayValue("50")).toBeTruthy();
  });

  it("updates column when dropdown changes", () => {
    const handleChange = vi.fn();
    const filters: VisualFilter[] = [
      { id: "f1", tablePrefix: "users", column: "id", operator: "=", value: "100" },
    ];

    render(
      <TableFiltersEditor
        filters={filters}
        activeTables={activeTables}
        onChange={handleChange}
      />
    );

    const selectEl = screen.getByDisplayValue("users.id");
    fireEvent.change(selectEl, { target: { value: "users.email" } });

    expect(handleChange).toHaveBeenCalledWith([
      { id: "f1", tablePrefix: "users", column: "email", operator: "=", value: "100" },
    ]);
  });

  it("updates operator when operator selector changes", () => {
    const handleChange = vi.fn();
    const filters: VisualFilter[] = [
      { id: "f1", tablePrefix: "users", column: "id", operator: "=", value: "100" },
    ];

    render(
      <TableFiltersEditor
        filters={filters}
        activeTables={activeTables}
        onChange={handleChange}
      />
    );

    const opSelect = screen.getByDisplayValue("=");
    fireEvent.change(opSelect, { target: { value: ">=" } });

    expect(handleChange).toHaveBeenCalledWith([
      { id: "f1", tablePrefix: "users", column: "id", operator: ">=", value: "100" },
    ]);
  });

  it("hides value input when operator is IS NULL or IS NOT NULL", () => {
    const filters: VisualFilter[] = [
      { id: "f1", tablePrefix: "users", column: "email", operator: "IS NULL", value: "" },
    ];

    render(
      <TableFiltersEditor
        filters={filters}
        activeTables={activeTables}
        onChange={vi.fn()}
      />
    );

    expect(screen.queryByPlaceholderText("Value...")).toBeNull();
  });

  it("renders special placeholder for BETWEEN operator", () => {
    const filters: VisualFilter[] = [
      { id: "f1", tablePrefix: "orders", column: "amount", operator: "BETWEEN", value: "" },
    ];

    render(
      <TableFiltersEditor
        filters={filters}
        activeTables={activeTables}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByPlaceholderText("10 AND 50")).toBeTruthy();
  });

  it("updates value when typing into value input", () => {
    const handleChange = vi.fn();
    const filters: VisualFilter[] = [
      { id: "f1", tablePrefix: "users", column: "email", operator: "=", value: "alice" },
    ];

    render(
      <TableFiltersEditor
        filters={filters}
        activeTables={activeTables}
        onChange={handleChange}
      />
    );

    const input = screen.getByDisplayValue("alice");
    fireEvent.change(input, { target: { value: "bob@example.com" } });

    expect(handleChange).toHaveBeenCalledWith([
      { id: "f1", tablePrefix: "users", column: "email", operator: "=", value: "bob@example.com" },
    ]);
  });

  it("removes filter when remove button is clicked", () => {
    const handleChange = vi.fn();
    const filters: VisualFilter[] = [
      { id: "f1", tablePrefix: "users", column: "id", operator: "=", value: "100" },
      { id: "f2", tablePrefix: "orders", column: "amount", operator: ">", value: "50" },
    ];

    render(
      <TableFiltersEditor
        filters={filters}
        activeTables={activeTables}
        onChange={handleChange}
      />
    );

    const removeButtons = screen.getAllByTitle("Remove condition");
    fireEvent.click(removeButtons[0]);

    expect(handleChange).toHaveBeenCalledWith([filters[1]]);
  });

  it("handles adding filter when activeTables is empty and preserves other filters during update", () => {
    // 1. Add filter with empty activeTables (lines 28-29)
    const handleAddChange = vi.fn();
    render(
      <TableFiltersEditor
        filters={[]}
        activeTables={[]}
        onChange={handleAddChange}
      />
    );
    fireEvent.click(screen.getByText("+ Add Filter"));
    expect(handleAddChange).toHaveBeenCalledOnce();
    const addedFilter = handleAddChange.mock.calls[0][0][0] as VisualFilter;
    expect(addedFilter.tablePrefix).toBe("");
    expect(addedFilter.column).toBe("");

    // 2. Update one of multiple filters (line 38: : f branch)
    const handleUpdateChange = vi.fn();
    const twoFilters: VisualFilter[] = [
      { id: "f1", tablePrefix: "users", column: "id", operator: "=", value: "100" },
      { id: "f2", tablePrefix: "orders", column: "amount", operator: ">", value: "50" },
    ];
    render(
      <TableFiltersEditor
        filters={twoFilters}
        activeTables={activeTables}
        onChange={handleUpdateChange}
      />
    );
    const firstInput = screen.getByDisplayValue("100");
    fireEvent.change(firstInput, { target: { value: "200" } });
    expect(handleUpdateChange).toHaveBeenCalledWith([
      { ...twoFilters[0], value: "200" },
      twoFilters[1],
    ]);
  });
});
