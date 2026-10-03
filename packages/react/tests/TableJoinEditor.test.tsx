import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TableJoinEditor } from "../src/components/TableJoinEditor";
import type { TableMeta, VisualJoin, SchemaSnapshot } from "../src/types";

describe("TableJoinEditor", () => {
  const allTables: TableMeta[] = [
    {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      ],
    },
    {
      name: "orders",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
      ],
    },
    {
      name: "products",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      ],
    },
  ];

  const mockSchema: SchemaSnapshot = {
    tables: {
      users: allTables[0],
      orders: allTables[1],
      products: allTables[2],
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

  it("renders empty state message when no joins configured", () => {
    render(
      <TableJoinEditor
        joins={[]}
        activeTables={[allTables[0]]}
        allTables={allTables}
        schema={mockSchema}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText(/Single table query/i)).toBeTruthy();
    expect(screen.getByText("🔗 Table Relationships & Joins (0)")).toBeTruthy();
  });

  it("offers unjoined tables in dropdown and adds join when selected", () => {
    const handleChange = vi.fn();
    render(
      <TableJoinEditor
        joins={[]}
        activeTables={[allTables[0]]}
        allTables={allTables}
        schema={mockSchema}
        onChange={handleChange}
      />
    );

    const select = screen.getByRole("combobox");
    // options should include orders and products, but NOT users
    expect(screen.getByText("+ orders")).toBeTruthy();
    expect(screen.getByText("+ products")).toBeTruthy();
    expect(screen.queryByText("+ users")).toBeNull();

    fireEvent.change(select, { target: { value: "orders" } });

    expect(handleChange).toHaveBeenCalledOnce();
    const newJoins = handleChange.mock.calls[0][0] as VisualJoin[];
    expect(newJoins).toHaveLength(1);
    expect(newJoins[0].type).toBe("LEFT JOIN");
    expect(newJoins[0].left_table).toBe("users");
    expect(newJoins[0].left_col).toBe("id");
    expect(newJoins[0].table).toBe("orders");
    expect(newJoins[0].right_col).toBe("user_id");
  });

  it("updates join type (e.g. INNER JOIN)", () => {
    const handleChange = vi.fn();
    const joins: VisualJoin[] = [
      {
        id: "j1",
        type: "LEFT JOIN",
        left_table: "users",
        left_col: "id",
        table: "orders",
        right_col: "user_id",
      },
    ];

    render(
      <TableJoinEditor
        joins={joins}
        activeTables={[allTables[0], allTables[1]]}
        allTables={allTables}
        schema={mockSchema}
        onChange={handleChange}
      />
    );

    const typeSelect = screen.getByDisplayValue("LEFT JOIN");
    fireEvent.change(typeSelect, { target: { value: "INNER JOIN" } });

    expect(handleChange).toHaveBeenCalledWith([
      { ...joins[0], type: "INNER JOIN" },
    ]);
  });

  it("updates left table and col when input is edited", () => {
    const handleChange = vi.fn();
    const joins: VisualJoin[] = [
      {
        id: "j1",
        type: "LEFT JOIN",
        left_table: "users",
        left_col: "id",
        table: "orders",
        right_col: "user_id",
      },
    ];

    render(
      <TableJoinEditor
        joins={joins}
        activeTables={[allTables[0], allTables[1]]}
        allTables={allTables}
        schema={mockSchema}
        onChange={handleChange}
      />
    );

    const leftInput = screen.getByDisplayValue("users.id");
    fireEvent.change(leftInput, { target: { value: "users.account_id" } });

    expect(handleChange).toHaveBeenCalledWith([
      { ...joins[0], left_table: "users", left_col: "account_id" },
    ]);
  });

  it("updates right col when input is edited", () => {
    const handleChange = vi.fn();
    const joins: VisualJoin[] = [
      {
        id: "j1",
        type: "LEFT JOIN",
        left_table: "users",
        left_col: "id",
        table: "orders",
        right_col: "user_id",
      },
    ];

    render(
      <TableJoinEditor
        joins={joins}
        activeTables={[allTables[0], allTables[1]]}
        allTables={allTables}
        schema={mockSchema}
        onChange={handleChange}
      />
    );

    const rightInput = screen.getByDisplayValue("orders.user_id");
    fireEvent.change(rightInput, { target: { value: "orders.customer_fk" } });

    expect(handleChange).toHaveBeenCalledWith([
      { ...joins[0], right_col: "customer_fk" },
    ]);
  });

  it("removes join when delete button is clicked", () => {
    const handleChange = vi.fn();
    const joins: VisualJoin[] = [
      {
        id: "j1",
        type: "LEFT JOIN",
        left_table: "users",
        left_col: "id",
        table: "orders",
        right_col: "user_id",
      },
    ];

    render(
      <TableJoinEditor
        joins={joins}
        activeTables={[allTables[0], allTables[1]]}
        allTables={allTables}
        schema={mockSchema}
        onChange={handleChange}
      />
    );

    const removeBtn = screen.getByTitle("Remove join");
    fireEvent.click(removeBtn);

    expect(handleChange).toHaveBeenCalledWith([]);
  });
});
