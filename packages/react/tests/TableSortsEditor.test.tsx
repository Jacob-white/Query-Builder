import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TableSortsEditor } from "../src/components/TableSortsEditor";
import type { TableMeta, VisualSort } from "../src/types";

describe("TableSortsEditor", () => {
  const activeTables: TableMeta[] = [
    {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
      ],
    },
  ];

  it("renders empty state message when no sorts exist", () => {
    render(
      <TableSortsEditor
        sorts={[]}
        activeTables={activeTables}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText(/Default database ordering/i)).toBeTruthy();
    expect(screen.getByText("↕️ Order & Sorts (0)")).toBeTruthy();
  });

  it("adds a new sort with first column and ASC direction when + Add Sort is clicked", () => {
    const handleChange = vi.fn();
    render(
      <TableSortsEditor
        sorts={[]}
        activeTables={activeTables}
        onChange={handleChange}
      />
    );

    fireEvent.click(screen.getByText("+ Add Sort"));
    expect(handleChange).toHaveBeenCalledOnce();
    const addedSort = handleChange.mock.calls[0][0][0] as VisualSort;
    expect(addedSort.tablePrefix).toBe("users");
    expect(addedSort.column).toBe("id");
    expect(addedSort.direction).toBe("ASC");
  });

  it("updates sort column when dropdown is changed", () => {
    const handleChange = vi.fn();
    const sorts: VisualSort[] = [
      { id: "s1", tablePrefix: "users", column: "id", direction: "ASC" },
    ];

    render(
      <TableSortsEditor
        sorts={sorts}
        activeTables={activeTables}
        onChange={handleChange}
      />
    );

    const select = screen.getByDisplayValue("users.id");
    fireEvent.change(select, { target: { value: "users.created_at" } });

    expect(handleChange).toHaveBeenCalledWith([
      { id: "s1", tablePrefix: "users", column: "created_at", direction: "ASC" },
    ]);
  });

  it("toggles sort direction between ASC and DESC", () => {
    const handleChange = vi.fn();
    const sorts: VisualSort[] = [
      { id: "s1", tablePrefix: "users", column: "id", direction: "ASC" },
    ];

    render(
      <TableSortsEditor
        sorts={sorts}
        activeTables={activeTables}
        onChange={handleChange}
      />
    );

    const dirBtn = screen.getByText("ASC ▲");
    fireEvent.click(dirBtn);

    expect(handleChange).toHaveBeenCalledWith([
      { id: "s1", tablePrefix: "users", column: "id", direction: "DESC" },
    ]);
  });

  it("toggles from DESC back to ASC", () => {
    const handleChange = vi.fn();
    const sorts: VisualSort[] = [
      { id: "s1", tablePrefix: "users", column: "id", direction: "DESC" },
    ];

    render(
      <TableSortsEditor
        sorts={sorts}
        activeTables={activeTables}
        onChange={handleChange}
      />
    );

    const dirBtn = screen.getByText("DESC ▼");
    fireEvent.click(dirBtn);

    expect(handleChange).toHaveBeenCalledWith([
      { id: "s1", tablePrefix: "users", column: "id", direction: "ASC" },
    ]);
  });

  it("removes sort when remove button is clicked", () => {
    const handleChange = vi.fn();
    const sorts: VisualSort[] = [
      { id: "s1", tablePrefix: "users", column: "id", direction: "ASC" },
    ];

    render(
      <TableSortsEditor
        sorts={sorts}
        activeTables={activeTables}
        onChange={handleChange}
      />
    );

    const removeBtn = screen.getByTitle("Remove sort");
    fireEvent.click(removeBtn);

    expect(handleChange).toHaveBeenCalledWith([]);
  });

  it("handles adding sort when activeTables is empty and preserves other sorts during update", () => {
    // 1. Add sort when activeTables is empty (lines 27-28)
    const handleAddChange = vi.fn();
    render(
      <TableSortsEditor
        sorts={[]}
        activeTables={[]}
        onChange={handleAddChange}
      />
    );
    fireEvent.click(screen.getByText("+ Add Sort"));
    expect(handleAddChange).toHaveBeenCalledOnce();
    const addedSort = handleAddChange.mock.calls[0][0][0] as VisualSort;
    expect(addedSort.tablePrefix).toBe("");
    expect(addedSort.column).toBe("");

    // 2. Update one of multiple sorts (line 35: : s branch)
    const handleUpdateChange = vi.fn();
    const twoSorts: VisualSort[] = [
      { id: "s1", tablePrefix: "users", column: "id", direction: "ASC" },
      { id: "s2", tablePrefix: "users", column: "created_at", direction: "DESC" },
    ];
    render(
      <TableSortsEditor
        sorts={twoSorts}
        activeTables={activeTables}
        onChange={handleUpdateChange}
      />
    );
    const firstSelect = screen.getByDisplayValue("users.id");
    fireEvent.change(firstSelect, { target: { value: "users.created_at" } });
    expect(handleUpdateChange).toHaveBeenCalledWith([
      { ...twoSorts[0], column: "created_at" },
      twoSorts[1],
    ]);
  });

  it("reorders sorts when dragging and dropping sort-row items", () => {
    const handleReorder = vi.fn();
    const twoSorts: VisualSort[] = [
      { id: "s1", tablePrefix: "users", column: "id", direction: "ASC" },
      { id: "s2", tablePrefix: "users", column: "created_at", direction: "DESC" },
    ];
    const { container } = render(
      <TableSortsEditor
        sorts={twoSorts}
        activeTables={activeTables}
        onChange={handleReorder}
      />
    );

    const rows = container.querySelectorAll('[data-qb="sort-row"]');
    expect(rows.length).toBe(2);
    expect(rows[0].getAttribute("draggable")).toBe("true");

    fireEvent.dragStart(rows[1]);
    fireEvent.dragEnter(rows[0]);
    fireEvent.dragOver(rows[0]);
    fireEvent.drop(rows[0]);
    fireEvent.dragEnd(rows[1]);

    expect(handleReorder).toHaveBeenCalledWith([twoSorts[1], twoSorts[0]]);
  });

  it("renders clean sort column pills and badges without table prefix repetition and segmented limit controls", () => {
    const handleLimitChange = vi.fn();
    const sorts: VisualSort[] = [
      { id: "s1", tablePrefix: "users", column: "id", direction: "ASC" },
    ];

    const { container } = render(
      <TableSortsEditor
        sorts={sorts}
        activeTables={activeTables}
        limit={25}
        onLimitChange={handleLimitChange}
        onChange={vi.fn()}
      />
    );

    // Sort column pills should show "↕ id (ASC)" and "↕ created_at", without "users." prefix
    const pills = container.querySelectorAll('[data-qb="sort-column-pill"]');
    const pillTexts = Array.from(pills).map((p) => p.textContent?.trim());
    expect(pillTexts).toContain("↕ id (ASC)");
    expect(pillTexts).toContain("↕ created_at");
    expect(pillTexts.some((t) => t?.includes("users."))).toBe(false);

    // Sort column badge should show "id" without table prefix
    const badge = container.querySelector('[data-qb="sort-column-badge"]');
    expect(badge?.textContent?.trim()).toBe("id");

    // Segmented sort direction buttons
    const ascBtn = container.querySelector('[data-qb="sort-dir-asc"]');
    const descBtn = container.querySelector('[data-qb="sort-dir-desc"]');
    expect(ascBtn).toBeTruthy();
    expect(descBtn).toBeTruthy();

    // Segmented row limit controls
    const limitPills = container.querySelectorAll('[data-qb="sort-limit-pill"]');
    expect(limitPills.length).toBeGreaterThan(0);
    const limitPill50 = container.querySelector('[data-qb="sort-limit-pill"][data-qb-limit="50"]');
    expect(limitPill50).toBeTruthy();
    fireEvent.click(limitPill50!);
    expect(handleLimitChange).toHaveBeenCalledWith(50);
  });
});
