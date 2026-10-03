import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import {
  VisualQueryBuilder,
  SchemaErdModal,
  TableCard,
  type SchemaSnapshot,
} from "../src/index";

const TEST_SCHEMA: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "name", data_type: "VARCHAR", is_nullable: false, is_primary: false },
      ],
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "INTEGER", is_nullable: false, is_primary: false },
      ],
    },
  },
  foreign_keys: [
    { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
  ],
};

describe("WCAG 2.1 AA Accessibility & Keyboard Navigation", () => {
  it("VisualQueryBuilder tablist supports Arrow keys, Home, and End navigation with wrap-around", () => {
    render(<VisualQueryBuilder schema={TEST_SCHEMA} initialTable="users" />);

    const tablist = screen.getByRole("tablist", { name: /query builder tabs/i });
    expect(tablist).toBeDefined();

    const visualTab = screen.getByRole("tab", { name: /visual builder/i });
    const sqlTab = screen.getByRole("tab", { name: /raw sql/i });
    const resultsTab = screen.getByRole("tab", { name: /results/i });
    const chartTab = screen.getByRole("tab", { name: /visual chart/i });

    expect(visualTab.getAttribute("aria-selected")).toBe("true");
    expect(visualTab.getAttribute("tabindex")).toBe("0");
    expect(sqlTab.getAttribute("aria-selected")).toBe("false");
    expect(sqlTab.getAttribute("tabindex")).toBe("-1");

    // Press ArrowRight from Visual Builder -> Raw SQL
    fireEvent.keyDown(visualTab, { key: "ArrowRight" });
    expect(sqlTab.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel", { name: /raw sql/i })).toBeDefined();

    // Press ArrowRight from Raw SQL -> Results
    fireEvent.keyDown(sqlTab, { key: "ArrowRight" });
    expect(resultsTab.getAttribute("aria-selected")).toBe("true");

    // Press ArrowRight from Results -> Chart
    fireEvent.keyDown(resultsTab, { key: "ArrowRight" });
    expect(chartTab.getAttribute("aria-selected")).toBe("true");

    // Press ArrowRight from Chart -> wraps around to Visual Builder
    fireEvent.keyDown(chartTab, { key: "ArrowRight" });
    expect(visualTab.getAttribute("aria-selected")).toBe("true");

    // Press ArrowLeft from Visual Builder -> wraps around to Chart
    fireEvent.keyDown(visualTab, { key: "ArrowLeft" });
    expect(chartTab.getAttribute("aria-selected")).toBe("true");

    // Press Home from Chart -> jumps to Visual Builder
    fireEvent.keyDown(chartTab, { key: "Home" });
    expect(visualTab.getAttribute("aria-selected")).toBe("true");

    // Press End from Visual Builder -> jumps to Chart
    fireEvent.keyDown(visualTab, { key: "End" });
    expect(chartTab.getAttribute("aria-selected")).toBe("true");
  });

  it("VisualQueryBuilder includes accessible live regions, action button labels, and Escape dismissal", () => {
    render(<VisualQueryBuilder schema={TEST_SCHEMA} initialTable="users" />);

    // Status live region
    const statusRegion = screen.getByRole("status");
    expect(statusRegion).toBeDefined();
    expect(statusRegion.getAttribute("aria-live")).toBe("polite");

    // Buttons with descriptive aria-labels
    expect(screen.getByRole("button", { name: /run query/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /open schema erd modal/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /save query as template/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /open template library/i })).toBeDefined();

    // Open Schema ERD modal then dismiss with Escape
    const erdBtn = screen.getByRole("button", { name: /open schema erd modal/i });
    fireEvent.click(erdBtn);
    expect(screen.getByRole("dialog")).toBeDefined();
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(screen.queryByRole("dialog")).toBeNull();

    // Open Template modal then dismiss with Escape
    const tplBtn = screen.getByRole("button", { name: /open template library/i });
    fireEvent.click(tplBtn);
    expect(screen.getByRole("dialog")).toBeDefined();
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("SchemaErdModal conforms to dialog role, modal semantics, and handles Escape key", () => {
    const onClose = vi.fn();
    const onSelectTable = vi.fn();

    const { rerender } = render(
      <SchemaErdModal
        isOpen={true}
        onClose={onClose}
        schema={TEST_SCHEMA}
        onSelectTable={onSelectTable}
      />,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeDefined();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-labelledby")).toBe("schema-erd-title");

    // Close button
    const closeBtn = screen.getByRole("button", { name: /close schema erd modal/i });
    expect(closeBtn).toBeDefined();

    // Select table button
    const selectTableBtn = screen.getByRole("button", { name: /select table users/i });
    fireEvent.click(selectTableBtn);
    expect(onSelectTable).toHaveBeenCalledWith("users");
    expect(onClose).toHaveBeenCalled();

    // Escape key listener
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);

    // Unopened modal renders nothing
    rerender(
      <SchemaErdModal
        isOpen={false}
        onClose={onClose}
        schema={TEST_SCHEMA}
      />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("TableCard provides region role, descriptive table label, and accessible controls", () => {
    const onToggleColumn = vi.fn();
    const onRemoveTable = vi.fn();
    const onAddJoin = vi.fn();

    render(
      <TableCard
        table={TEST_SCHEMA.tables.users}
        selectedColumns={{}}
        onToggleColumn={onToggleColumn}
        onRemoveTable={onRemoveTable}
        onAddJoin={onAddJoin}
      />,
    );

    // Region container
    const tableRegion = screen.getByRole("region", { name: /table users/i });
    expect(tableRegion).toBeDefined();

    // Accessible buttons
    const addJoinBtn = screen.getByRole("button", { name: /add join for table users/i });
    fireEvent.click(addJoinBtn);
    expect(onAddJoin).toHaveBeenCalled();

    const removeTableBtn = screen.getByRole("button", { name: /remove table users/i });
    fireEvent.click(removeTableBtn);
    expect(onRemoveTable).toHaveBeenCalled();

    // Column checkboxes
    const colCheckbox = screen.getByRole("checkbox", { name: /select column users\.id/i });
    expect(colCheckbox).toBeDefined();
    fireEvent.click(colCheckbox);
    expect(onToggleColumn).toHaveBeenCalledWith("id");
  });
});
