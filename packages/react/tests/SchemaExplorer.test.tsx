import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { SchemaExplorer } from "../src/components/SchemaExplorer";
import type { SchemaSnapshot } from "../src/types";

describe("SchemaExplorer", () => {
  const mockSchema: SchemaSnapshot = {
    tables: {
      users: {
        name: "users",
        comment: "Registered users table",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "email", data_type: "varchar(255)", is_nullable: false, is_primary: false, comment: "User email address" },
          { name: "created_at", data_type: "timestamp", is_nullable: true, is_primary: false },
        ],
      },
      orders: {
        name: "orders",
        comment: "Customer orders",
        has_user_id: true,
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "total_amount", data_type: "decimal(10,2)", is_nullable: false, is_primary: false },
          { name: "is_completed", data_type: "boolean", is_nullable: true, is_primary: false },
          { name: "metadata", data_type: "jsonb", is_nullable: true, is_primary: false },
          { name: "tracking_uuid", data_type: "uuid", is_nullable: true, is_primary: false },
        ],
      },
      order_items: {
        name: "order_items",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "order_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "sku", data_type: "text", is_nullable: false, is_primary: false },
        ],
      },
      standalone_logs: {
        name: "standalone_logs",
        columns: [
          { name: "log_id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "message", data_type: "text", is_nullable: true, is_primary: false },
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
      {
        table: "order_items",
        column: "order_id",
        foreign_table: "orders",
        foreign_column: "id",
      },
    ],
    categories: {
      Commerce: ["orders", "order_items"],
      Auth: ["users"],
    },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockImplementation(() => Promise.resolve()),
      },
    });
  });

  it("renders schema explorer header, statistics, and tables list", () => {
    render(<SchemaExplorer schema={mockSchema} />);

    expect(screen.getByRole("region", { name: "Schema Explorer" })).toBeTruthy();
    expect(screen.getByText("Schema Explorer")).toBeTruthy();
    expect(screen.getByTestId("stat-tables-badge").textContent).toBe("4 Tables");
    expect(screen.getByTestId("stat-fks-badge").textContent).toBe("2 Foreign Keys");

    const nav = screen.getByRole("navigation", { name: "Database Tables List" });
    expect(within(nav).getByText("Tables (4)")).toBeTruthy();
    expect(within(nav).getByText("users")).toBeTruthy();
    expect(within(nav).getByText("orders")).toBeTruthy();
    expect(within(nav).getByText("order_items")).toBeTruthy();
    expect(within(nav).getByText("standalone_logs")).toBeTruthy();
  });

  it("displays columns with data types, PK/FK badges, nullability, and comments", () => {
    render(<SchemaExplorer schema={mockSchema} selectedTable="orders" />);

    expect(screen.getByTestId("detail-table-title").textContent).toBe("orders");
    expect(screen.getByTestId("table-comment").textContent).toBe("Customer orders");

    // Check column rows
    expect(screen.getByText("total_amount")).toBeTruthy();
    expect(screen.getByText("decimal(10,2)")).toBeTruthy();
    expect(screen.getByText("boolean")).toBeTruthy();
    expect(screen.getByText("jsonb")).toBeTruthy();
    expect(screen.getByText("uuid")).toBeTruthy();

    // Check PK badge
    expect(screen.getByTitle("Primary Key")).toBeTruthy();

    // Check FK badge on user_id
    expect(screen.getByTitle("Foreign Key")).toBeTruthy();

    // Nullable text
    expect(screen.getAllByText("Nullable").length).toBeGreaterThan(0);
    expect(screen.getAllByText("NOT NULL").length).toBeGreaterThan(0);
  });

  it("filters tables by name using the global search input", () => {
    render(<SchemaExplorer schema={mockSchema} />);

    const searchInput = screen.getByLabelText("Search schema");
    fireEvent.change(searchInput, { target: { value: "order" } });

    const nav = screen.getByRole("navigation", { name: "Database Tables List" });
    expect(within(nav).getByText("Tables (2)")).toBeTruthy();
    expect(within(nav).getByText("orders")).toBeTruthy();
    expect(within(nav).getByText("order_items")).toBeTruthy();
    expect(within(nav).queryByText("standalone_logs")).toBeNull();

    // Clear search
    const clearBtn = screen.getByLabelText("Clear schema search");
    fireEvent.click(clearBtn);

    expect(within(nav).getByText("Tables (4)")).toBeTruthy();
    expect(within(nav).getByText("standalone_logs")).toBeTruthy();
  });

  it("filters tables by column name using the search input", () => {
    render(<SchemaExplorer schema={mockSchema} />);

    const searchInput = screen.getByLabelText("Search schema");
    fireEvent.change(searchInput, { target: { value: "tracking_uuid" } });

    const nav = screen.getByRole("navigation", { name: "Database Tables List" });
    expect(within(nav).getByText("Tables (1)")).toBeTruthy();
    expect(within(nav).getByText("orders")).toBeTruthy();
    expect(within(nav).queryByText("users")).toBeNull();
  });

  it("filters tables using category pills", () => {
    render(<SchemaExplorer schema={mockSchema} />);

    const nav = screen.getByRole("navigation", { name: "Database Tables List" });
    const authBtn = screen.getByRole("button", { name: "Auth" });
    fireEvent.click(authBtn);

    expect(within(nav).getByText("Tables (1)")).toBeTruthy();
    expect(within(nav).getByText("users")).toBeTruthy();
    expect(within(nav).queryByText("orders")).toBeNull();

    const commerceBtn = screen.getByRole("button", { name: "Commerce" });
    fireEvent.click(commerceBtn);

    expect(within(nav).getByText("Tables (2)")).toBeTruthy();
    expect(within(nav).getByText("orders")).toBeTruthy();
    expect(within(nav).getByText("order_items")).toBeTruthy();

    const allBtn = screen.getByRole("button", { name: "All" });
    fireEvent.click(allBtn);
    expect(within(nav).getByText("Tables (4)")).toBeTruthy();
  });

  it("switches active table when clicking a table item or pressing Enter", () => {
    const handleSelectTable = vi.fn();
    render(<SchemaExplorer schema={mockSchema} onSelectTable={handleSelectTable} />);

    const ordersItem = screen.getByLabelText("Select table orders");
    fireEvent.click(ordersItem);

    expect(handleSelectTable).toHaveBeenCalledWith("orders");
    expect(screen.getByTestId("detail-table-title").textContent).toBe("orders");

    // Keyboard navigation
    const usersItem = screen.getByLabelText("Select table users");
    fireEvent.keyDown(usersItem, { key: "Enter" });
    expect(handleSelectTable).toHaveBeenCalledWith("users");
    expect(screen.getByTestId("detail-table-title").textContent).toBe("users");
  });

  it("filters columns inside the detail inspector", () => {
    render(<SchemaExplorer schema={mockSchema} selectedTable="orders" />);

    const colFilter = screen.getByLabelText("Filter columns");
    fireEvent.change(colFilter, { target: { value: "uuid" } });

    expect(screen.getByText("tracking_uuid")).toBeTruthy();
    expect(screen.queryByText("total_amount")).toBeNull();
  });

  it("triggers onAddToCanvas when clicking Add to Canvas button", () => {
    const handleAddToCanvas = vi.fn();
    render(<SchemaExplorer schema={mockSchema} selectedTable="orders" onAddToCanvas={handleAddToCanvas} />);

    const addBtn = screen.getByLabelText("Add table orders to canvas");
    fireEvent.click(addBtn);

    expect(handleAddToCanvas).toHaveBeenCalledWith("orders");
  });

  it("triggers onOpenErd when clicking Interactive ERD buttons", () => {
    const handleOpenErd = vi.fn();
    render(<SchemaExplorer schema={mockSchema} selectedTable="users" onOpenErd={handleOpenErd} />);

    const erdBtn = screen.getByLabelText("View interactive ERD graph");
    fireEvent.click(erdBtn);

    expect(handleOpenErd).toHaveBeenCalledWith("users");
  });

  it("triggers onQuickQuery when clicking Quick Query button", () => {
    const handleQuickQuery = vi.fn();
    render(<SchemaExplorer schema={mockSchema} selectedTable="orders" onQuickQuery={handleQuickQuery} />);

    const quickBtn = screen.getByLabelText("Quick query table orders");
    fireEvent.click(quickBtn);

    expect(handleQuickQuery).toHaveBeenCalledWith("orders");
  });

  it("copies table name and SQL query to clipboard with status feedback", async () => {
    render(<SchemaExplorer schema={mockSchema} selectedTable="users" />);

    const copyNameBtn = screen.getByLabelText("Copy table name");
    fireEvent.click(copyNameBtn);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("users");
    expect(screen.getByText('✓ Copied "users"')).toBeTruthy();

    const copySqlBtn = screen.getByLabelText("Copy SQL select template");
    fireEvent.click(copySqlBtn);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('FROM "users"')
    );
    expect(screen.getByText("✓ Copied SQL query!")).toBeTruthy();
  });

  it("handles outgoing and incoming foreign keys with interactive table jumping", () => {
    render(<SchemaExplorer schema={mockSchema} selectedTable="orders" />);

    // Outgoing reference: orders.user_id -> users.id
    expect(screen.getByText("References Other Tables (1)")).toBeTruthy();
    const jumpToUsers = screen.getByLabelText("Jump to table users");
    fireEvent.click(jumpToUsers);

    // After clicking jump, active table is now users
    expect(screen.getByTestId("detail-table-title").textContent).toBe("users");

    // users is referenced by orders:
    expect(screen.getByText("Referenced By (1)")).toBeTruthy();
    const jumpBackToOrders = screen.getByLabelText("Jump to table orders");
    fireEvent.click(jumpBackToOrders);

    expect(screen.getByTestId("detail-table-title").textContent).toBe("orders");
  });

  it("shows empty state when table has no relationships", () => {
    render(<SchemaExplorer schema={mockSchema} selectedTable="standalone_logs" />);

    expect(screen.getByText("No direct foreign keys configured for this table.")).toBeTruthy();
  });

  it("shows empty state when search matches zero tables", () => {
    render(<SchemaExplorer schema={mockSchema} />);

    const searchInput = screen.getByLabelText("Search schema");
    fireEvent.change(searchInput, { target: { value: "nonexistent_table_xyz" } });

    expect(screen.getByText('No tables match "nonexistent_table_xyz"')).toBeTruthy();
  });

  it("renders in unstyled mode without inline styles crashing", () => {
    const { container } = render(<SchemaExplorer schema={mockSchema} unstyled />);
    expect(container.querySelector('[data-qb="schema-explorer"]')).toBeTruthy();
    expect(container.querySelector('[data-qb="table-item"]')).toBeTruthy();
  });
});
