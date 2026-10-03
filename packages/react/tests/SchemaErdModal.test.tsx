import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SchemaErdModal } from "../src/components/SchemaErdModal";
import type { SchemaSnapshot } from "../src/types";

describe("SchemaErdModal", () => {
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

  it("returns null and renders nothing when isOpen is false", () => {
    const { container } = render(
      <SchemaErdModal isOpen={false} onClose={vi.fn()} schema={mockSchema} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders ERD dialog when isOpen is true with tables and relationship stats", () => {
    render(
      <SchemaErdModal isOpen={true} onClose={vi.fn()} schema={mockSchema} />
    );

    expect(screen.getByText("Schema Entity Relationship Diagram (ERD)")).toBeTruthy();
    expect(screen.getByText("2 tables · 1 foreign keys")).toBeTruthy();
    expect(screen.getByText("users")).toBeTruthy();
    expect(screen.getByText("orders")).toBeTruthy();
    expect(screen.getAllByText(/id 🔑/)).toHaveLength(2);
    expect(screen.getAllByText(/1 relationship/)).toHaveLength(2); // users and orders both match the FK
  });

  it("calls onClose when close button ✕ is clicked", () => {
    const handleClose = vi.fn();
    render(
      <SchemaErdModal isOpen={true} onClose={handleClose} schema={mockSchema} />
    );

    const closeBtn = screen.getByText("✕");
    fireEvent.click(closeBtn);
    expect(handleClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when backdrop overlay is clicked", () => {
    const handleClose = vi.fn();
    const { container } = render(
      <SchemaErdModal isOpen={true} onClose={handleClose} schema={mockSchema} />
    );

    const backdrop = container.firstChild as HTMLElement;
    fireEvent.click(backdrop);
    expect(handleClose).toHaveBeenCalledOnce();
  });

  it("does not call onClose when clicking inside the modal content box", () => {
    const handleClose = vi.fn();
    render(
      <SchemaErdModal isOpen={true} onClose={handleClose} schema={mockSchema} />
    );

    const title = screen.getByText("Schema Entity Relationship Diagram (ERD)");
    fireEvent.click(title);
    expect(handleClose).not.toHaveBeenCalled();
  });

  it("calls onSelectTable and onClose when 'Use Table' button is clicked", () => {
    const handleSelect = vi.fn();
    const handleClose = vi.fn();
    render(
      <SchemaErdModal
        isOpen={true}
        onClose={handleClose}
        schema={mockSchema}
        onSelectTable={handleSelect}
      />
    );

    const useTableButtons = screen.getAllByText("Use Table");
    fireEvent.click(useTableButtons[0]);

    expect(handleSelect).toHaveBeenCalledWith("users");
    expect(handleClose).toHaveBeenCalledOnce();
  });

  it("handles null or empty schema gracefully without crashing", () => {
    render(<SchemaErdModal isOpen={true} onClose={vi.fn()} schema={null} />);
    expect(screen.getByText("0 tables · 0 foreign keys")).toBeTruthy();
  });

  it("renders plural 'relationships' when a table has more than 1 relationship", () => {
    const multiFkSchema: SchemaSnapshot = {
      tables: {
        orders: {
          name: "orders",
          columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }],
        },
      },
      foreign_keys: [
        { table: "orders", column: "c1", foreign_table: "t1", foreign_column: "id" },
        { table: "orders", column: "c2", foreign_table: "t2", foreign_column: "id" },
      ],
    };
    render(<SchemaErdModal isOpen={true} onClose={vi.fn()} schema={multiFkSchema} />);
    expect(screen.getByText(/2 relationships/)).toBeTruthy();
  });
});
