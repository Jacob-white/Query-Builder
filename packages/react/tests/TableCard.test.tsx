import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TableCard } from "../src/components/TableCard";
import type { TableMeta } from "../src/types";

describe("TableCard", () => {
  const mockTable: TableMeta = {
    name: "users",
    columns: [
      { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      { name: "email", data_type: "text", is_nullable: false, is_primary: false },
      { name: "created_at", data_type: "timestamp", is_nullable: true, is_primary: false },
    ],
  };

  it("renders table name and all columns with data types", () => {
    render(
      <TableCard
        table={mockTable}
        selectedColumns={{}}
        onToggleColumn={vi.fn()}
      />
    );

    expect(screen.getByText("users")).toBeTruthy();
    expect(screen.getByText("id")).toBeTruthy();
    expect(screen.getByText("email")).toBeTruthy();
    expect(screen.getByText("created_at")).toBeTruthy();
    expect(screen.getByText("integer")).toBeTruthy();
    expect(screen.getByText("text")).toBeTruthy();
    expect(screen.getByText("timestamp")).toBeTruthy();
    expect(screen.getByText("PK")).toBeTruthy();
  });

  it("renders with selection border styling when isSelected is true", () => {
    const { container } = render(
      <TableCard
        table={mockTable}
        isSelected={true}
        selectedColumns={{}}
        onToggleColumn={vi.fn()}
      />
    );
    const cardEl = container.firstChild as HTMLElement;
    expect(cardEl.style.border).toContain("rgb(59, 130, 246)");
  });

  it("renders checked state for selected columns", () => {
    render(
      <TableCard
        table={mockTable}
        selectedColumns={{
          "users.id": { table: "users", name: "id" },
        }}
        onToggleColumn={vi.fn()}
      />
    );

    const checkboxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(checkboxes[0].checked).toBe(true);
    expect(checkboxes[1].checked).toBe(false);
    expect(checkboxes[2].checked).toBe(false);
  });

  it("calls onToggleColumn when column row is clicked", () => {
    const handleToggle = vi.fn();
    render(
      <TableCard
        table={mockTable}
        selectedColumns={{}}
        onToggleColumn={handleToggle}
      />
    );

    fireEvent.click(screen.getByText("email"));
    expect(handleToggle).toHaveBeenCalledWith("email");
  });

  it("calls onToggleColumn when checkbox is clicked directly", () => {
    const handleToggle = vi.fn();
    render(
      <TableCard
        table={mockTable}
        selectedColumns={{}}
        onToggleColumn={handleToggle}
      />
    );

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);
    expect(handleToggle).toHaveBeenCalledWith("email");
  });

  it("calls onAddJoin when join button is clicked", () => {
    const handleAddJoin = vi.fn();
    render(
      <TableCard
        table={mockTable}
        selectedColumns={{}}
        onToggleColumn={vi.fn()}
        onAddJoin={handleAddJoin}
      />
    );

    const joinBtn = screen.getByTitle("Add Join to this table");
    fireEvent.click(joinBtn);
    expect(handleAddJoin).toHaveBeenCalledOnce();
  });

  it("calls onRemoveTable when remove button is clicked", () => {
    const handleRemoveTable = vi.fn();
    render(
      <TableCard
        table={mockTable}
        selectedColumns={{}}
        onToggleColumn={vi.fn()}
        onRemoveTable={handleRemoveTable}
      />
    );

    const removeBtn = screen.getByTitle("Remove table");
    fireEvent.click(removeBtn);
    expect(handleRemoveTable).toHaveBeenCalledOnce();
  });

  it("reorders column rows via HTML5 drag-and-drop and calls onReorderColumns", () => {
    const handleReorder = vi.fn();
    const { container } = render(
      <TableCard
        table={mockTable}
        selectedColumns={{}}
        onToggleColumn={vi.fn()}
        onReorderColumns={handleReorder}
      />
    );

    const rowsBefore = Array.from(
      container.querySelectorAll('[data-qb="table-card-column-row"]'),
    ).map((r) => r.getAttribute("data-qb-column"));
    expect(rowsBefore).toEqual(["id", "email", "created_at"]);

    const rows = container.querySelectorAll('[data-qb="table-card-column-row"]');
    expect(rows[2].getAttribute("draggable")).toBe("true");

    fireEvent.dragStart(rows[2]);
    fireEvent.dragEnter(rows[0]);
    fireEvent.dragOver(rows[0]);
    fireEvent.drop(rows[0]);
    fireEvent.dragEnd(rows[2]);

    expect(handleReorder).toHaveBeenCalledWith("users", ["created_at", "id", "email"]);

    const rowsAfter = Array.from(
      container.querySelectorAll('[data-qb="table-card-column-row"]'),
    ).map((r) => r.getAttribute("data-qb-column"));
    expect(rowsAfter).toEqual(["created_at", "id", "email"]);
  });

  it("supports clean focus and keyboard navigation (Space/Enter) on column rows", () => {
    const handleToggle = vi.fn();
    const { container } = render(
      <TableCard
        table={mockTable}
        selectedColumns={{}}
        onToggleColumn={handleToggle}
      />
    );

    const rows = container.querySelectorAll('[data-qb="table-card-column-row"]');
    expect(rows[1].getAttribute("tabindex")).toBe("0");

    // Focus row
    fireEvent.focus(rows[1]);
    expect((rows[1] as HTMLElement).style.outline).toContain("#38bdf8");

    // Press Space
    fireEvent.keyDown(rows[1], { key: " " });
    expect(handleToggle).toHaveBeenCalledWith("email");

    // Press Enter
    fireEvent.keyDown(rows[1], { key: "Enter" });
    expect(handleToggle).toHaveBeenCalledWith("email");

    // Blur row
    fireEvent.blur(rows[1]);
    expect((rows[1] as HTMLElement).style.outline).toBe("");
  });
});

