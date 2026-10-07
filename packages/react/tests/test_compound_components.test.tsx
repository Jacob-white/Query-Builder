import React, { useState } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import {
  QueryBuilder,
  useCompoundQueryBuilder,
} from "../src/components/compound";
import type { SchemaSnapshot, QuerySpec, QueryResultData } from "../src/types";

describe("Milestone 3: Composable Compound Components (<QueryBuilder.*>)", () => {
  const mockSchema: SchemaSnapshot = {
    tables: {
      users: {
        name: "users",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "name", data_type: "text", is_nullable: false, is_primary: false },
          { name: "email", data_type: "text", is_nullable: false, is_primary: false },
        ],
      },
      orders: {
        name: "orders",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
          { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
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

  it("throws a descriptive error when compound components are rendered outside of QueryBuilder.Root", () => {
    function OrphanComponent() {
      useCompoundQueryBuilder();
      return <div>Orphan</div>;
    }

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<OrphanComponent />)).toThrow(
      /QueryBuilder compound components .* must be used within a <QueryBuilder.Root> provider/,
    );
    consoleSpy.mockRestore();
  });

  it("renders a full composable dashboard layout with all compound primitives", async () => {
    const initialSpec: QuerySpec = {
      table: "users",
      columns: ["users.id", "users.name"],
      filters: [{ column: "users.name", op: "=", value: "Alice" }],
      order_by: [{ column: "users.name", direction: "ASC" }],
      limit: 10,
    };

    render(
      <QueryBuilder.Root schema={mockSchema} initialSpec={initialSpec}>
        <div data-testid="custom-layout">
          <QueryBuilder.Canvas />
          <QueryBuilder.Columns />
          <QueryBuilder.Filters />
          <QueryBuilder.Joins />
          <QueryBuilder.Sorts />
          <QueryBuilder.SqlEditor />
          <QueryBuilder.Results />
        </div>
      </QueryBuilder.Root>,
    );

    // Verify root rendered
    expect(screen.getByTestId("custom-layout")).toBeTruthy();

    // Verify Canvas active table
    expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
    expect(screen.getByText("users")).toBeTruthy();

    // Verify Columns manager
    expect(screen.getByText("✨ Selected Columns & Projections (2)")).toBeTruthy();
    expect(screen.getAllByText("users.name").length).toBeGreaterThan(0);

    // Verify Filters
    expect(screen.getByText("⚡ Filter Conditions (1)")).toBeTruthy();

    // Verify Sorts
    expect(screen.getByText("↕️ Order & Sorts (1)")).toBeTruthy();

    // Verify SQL Editor contains compiled SQL
    const sqlTextarea = screen.getByLabelText("Raw SQL code") as HTMLTextAreaElement;
    expect(sqlTextarea.value).toContain('SELECT "users"."id", "users"."name"');
    expect(sqlTextarea.value).toContain('FROM "users"');
    expect(sqlTextarea.value).toContain("WHERE");
    expect(sqlTextarea.value).toContain("ORDER BY");

    // Verify Results empty state
    expect(screen.getByText(/No query executed yet/)).toBeTruthy();
  });

  it("supports controlled state via value and onChange across compound components", async () => {
    const handleChange = vi.fn();

    function ControlledHost() {
      const [spec, setSpec] = useState<QuerySpec>({
        table: "users",
        columns: ["users.id"],
        limit: 25,
      });

      return (
        <QueryBuilder.Root
          schema={mockSchema}
          value={spec}
          onChange={(newSpec, sql) => {
            setSpec(newSpec);
            handleChange(newSpec, sql);
          }}
        >
          <QueryBuilder.Canvas />
          <QueryBuilder.Columns />
          <QueryBuilder.SqlEditor />
        </QueryBuilder.Root>
      );
    }

    render(<ControlledHost />);

    expect(screen.getByText("✨ Selected Columns & Projections (1)")).toBeTruthy();

    // Toggle another column on users table card
    const emailCheckbox = screen.getByLabelText("Select column users.email");
    fireEvent.click(emailCheckbox);

    // onChange called with updated columns
    expect(handleChange).toHaveBeenCalled();
    const lastCall = handleChange.mock.calls[handleChange.mock.calls.length - 1];
    expect(lastCall[0].columns).toContain("users.email");
  });

  it("allows adding and modifying filters via QueryBuilder.Filters", async () => {
    render(
      <QueryBuilder.Root
        schema={mockSchema}
        initialSpec={{ table: "users", columns: ["users.id"] }}
      >
        <QueryBuilder.Filters />
        <QueryBuilder.SqlEditor />
      </QueryBuilder.Root>,
    );

    // Click Add Filter
    const addFilterBtn = screen.getByText("+ Add Filter");
    fireEvent.click(addFilterBtn);

    expect(screen.getByText("⚡ Filter Conditions (1)")).toBeTruthy();

    // Textarea reflects new filter condition in WHERE clause
    const sqlTextarea = screen.getByLabelText("Raw SQL code") as HTMLTextAreaElement;
    expect(sqlTextarea.value).toContain("WHERE");
  });

  it("allows adding joins and sorts via compound components", async () => {
    render(
      <QueryBuilder.Root
        schema={mockSchema}
        initialSpec={{ table: "users", columns: ["users.id"] }}
      >
        <QueryBuilder.Canvas />
        <QueryBuilder.Joins />
        <QueryBuilder.Sorts />
        <QueryBuilder.SqlEditor />
      </QueryBuilder.Root>,
    );

    // Add orders table via add table selector
    const addTableSelect = screen.getByLabelText("Add table to canvas");
    fireEvent.change(addTableSelect, { target: { value: "orders" } });

    expect(screen.getByText("📋 Active Tables in Query (2)")).toBeTruthy();

    // Add sort
    const addSortBtn = screen.getByText("+ Add Sort");
    fireEvent.click(addSortBtn);

    expect(screen.getByText("↕️ Order & Sorts (1)")).toBeTruthy();
    const sqlTextarea = screen.getByLabelText("Raw SQL code") as HTMLTextAreaElement;
    expect(sqlTextarea.value).toContain("ORDER BY");
  });

  it("executes queries through QueryBuilder.SqlEditor and updates QueryBuilder.Results", async () => {
    const mockResults: QueryResultData = {
      columns: ["id", "name"],
      rows: [
        { id: 1, name: "Alice" },
        { id: 2, name: "Bob" },
      ],
      count: 2,
      latency_ms: 12.5,
      dialect: "postgres",
    };

    const mockExecute = vi.fn().mockResolvedValue(mockResults);

    render(
      <QueryBuilder.Root
        schema={mockSchema}
        initialSpec={{ table: "users", columns: ["users.id", "users.name"] }}
        onExecuteQuery={mockExecute}
      >
        <QueryBuilder.SqlEditor showExecuteButton={true} />
        <QueryBuilder.Results />
      </QueryBuilder.Root>,
    );

    const runBtn = screen.getByText("▶ Run Query");
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(mockExecute).toHaveBeenCalled();
      expect(screen.getByText("Alice")).toBeTruthy();
      expect(screen.getByText("Bob")).toBeTruthy();
    });
  });

  it("supports continuous bidirectional sync from raw SQL editor back to visual state", async () => {
    let capturedSpec: QuerySpec | null = null;

    render(
      <QueryBuilder.Root
        schema={mockSchema}
        initialSpec={{ table: "users", columns: ["users.id"] }}
        onChange={(s) => {
          capturedSpec = s;
        }}
      >
        <QueryBuilder.Columns />
        <QueryBuilder.SqlEditor />
      </QueryBuilder.Root>,
    );

    const textarea = screen.getByLabelText("Raw SQL code") as HTMLTextAreaElement;
    fireEvent.change(textarea, {
      target: { value: "SELECT users.id, users.email FROM users LIMIT 50" },
    });

    await waitFor(() => {
      expect(screen.getByText("⚡ Synced with Visual Canvas")).toBeTruthy();
      expect(screen.getByText("users.email")).toBeTruthy();
    });
  });

  it("auto-fetches schema if client is supplied to QueryBuilder.Root without schema", async () => {
    const mockClient = {
      getSchema: vi.fn().mockResolvedValue(mockSchema),
      execute: vi.fn(),
      compile: vi.fn(),
      validate: vi.fn(),
      export: vi.fn(),
      query: vi.fn(),
    };

    render(
      <QueryBuilder.Root client={mockClient as any}>
        <QueryBuilder.Canvas />
      </QueryBuilder.Root>,
    );

    await waitFor(() => {
      expect(mockClient.getSchema).toHaveBeenCalled();
    });
  });

  it("exposes imperative ref handle methods (getSpec, getSql, setSpec, reset, execute, undo, redo)", async () => {
    const qbRef = React.createRef<any>();

    render(
      <QueryBuilder.Root
        ref={qbRef}
        schema={mockSchema}
        initialSpec={{ table: "users", columns: ["users.id"] }}
      >
        <QueryBuilder.Columns />
        <QueryBuilder.SqlEditor />
      </QueryBuilder.Root>,
    );

    const refHandle = qbRef.current;
    expect(refHandle).toBeTruthy();
    expect(refHandle.getSpec().table).toBe("users");
    expect(refHandle.getSql()).toContain('SELECT "users"."id"');

    // Imperative setSpec
    act(() => {
      refHandle.setSpec({ table: "orders", columns: ["orders.id", "orders.total"] });
    });
    expect(refHandle.getSpec().table).toBe("orders");
    expect(refHandle.getSql()).toContain('FROM "orders"');

    // Imperative undo
    expect(refHandle.canUndo()).toBe(true);
    act(() => {
      refHandle.undo();
    });
    expect(refHandle.getSpec().table).toBe("users");

    // Imperative redo
    expect(refHandle.canRedo()).toBe(true);
    act(() => {
      refHandle.redo();
    });
    expect(refHandle.getSpec().table).toBe("orders");

    // Imperative reset
    act(() => {
      refHandle.reset();
    });
    expect(refHandle.getSpec().table).toBe("users");
  });

  it("renders table cards and columns in headless mode without schema snapshot", async () => {
    render(
      <QueryBuilder.Root
        initialSpec={{
          table: "dynamic_table",
          columns: ["dynamic_table.col1", "dynamic_table.col2"],
        }}
      >
        <QueryBuilder.Canvas />
        <QueryBuilder.Columns />
      </QueryBuilder.Root>,
    );

    // Canvas renders synthetic table card
    expect(screen.getByText("dynamic_table")).toBeTruthy();
    // Columns renders projection chips
    expect(screen.getByText("dynamic_table.col1")).toBeTruthy();
    expect(screen.getByText("dynamic_table.col2")).toBeTruthy();
  });

  it("resets isRawMode to false when visual actions are invoked, preventing desync", async () => {
    render(
      <QueryBuilder.Root
        schema={mockSchema}
        initialSpec={{ table: "users", columns: ["users.id"] }}
      >
        <QueryBuilder.Canvas />
        <QueryBuilder.Filters />
        <QueryBuilder.SqlEditor />
      </QueryBuilder.Root>,
    );

    // Type custom raw SQL
    const textarea = screen.getByLabelText("Raw SQL code") as HTMLTextAreaElement;
    fireEvent.change(textarea, {
      target: { value: "SELECT users.id FROM users WHERE users.id = 42" },
    });

    await waitFor(() => {
      expect(screen.getByText("⚡ Synced with Visual Canvas")).toBeTruthy();
    });

    // Now user clicks "+ Add Filter" in visual UI
    const addFilterBtn = screen.getByText("+ Add Filter");
    fireEvent.click(addFilterBtn);

    // Visual interaction must reset raw mode and update SQL with the new visual state
    await waitFor(() => {
      const updatedTextarea = screen.getByLabelText("Raw SQL code") as HTMLTextAreaElement;
      expect(updatedTextarea.value).toContain('FROM "users"');
    });
  });

  it("displays execution error clearly in QueryBuilder.Results", async () => {
    const failingExecute = vi.fn().mockRejectedValue(new Error("Connection to Postgres timed out (ETIMEDOUT)"));

    render(
      <QueryBuilder.Root
        schema={mockSchema}
        initialSpec={{ table: "users", columns: ["users.id"] }}
        onExecuteQuery={failingExecute}
      >
        <QueryBuilder.SqlEditor />
        <QueryBuilder.Results />
      </QueryBuilder.Root>,
    );

    const runBtn = screen.getByText("▶ Run Query");
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(failingExecute).toHaveBeenCalled();
      expect(screen.getByText(/Query Execution Failed: Connection to Postgres timed out/)).toBeTruthy();
    });
  });

  it("supports initialTable prop to automatically select starting table", async () => {
    render(
      <QueryBuilder.Root
        schema={mockSchema}
        initialTable="orders"
      >
        <QueryBuilder.Canvas />
      </QueryBuilder.Root>,
    );

    expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
    expect(screen.getByText("orders")).toBeTruthy();
  });
});
