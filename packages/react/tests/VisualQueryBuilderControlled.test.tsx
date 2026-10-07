import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import type {
  SchemaSnapshot,
  QuerySpec,
  VisualQueryBuilderRef,
  QueryResultData,
} from "../src/types";
import type { QueryBuilderClient } from "../src/client/index";

describe("VisualQueryBuilder Controlled/Uncontrolled & Undo/Redo & Client", () => {
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
          { name: "amount", data_type: "numeric", is_nullable: false, is_primary: false },
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

  it("supports controlled mode with value and onChange propagation", async () => {
    const handleChange = vi.fn();
    const controlledSpec: QuerySpec = {
      table: "orders",
      columns: ["orders.id", "orders.amount"],
      limit: 25,
    };

    const { rerender } = render(
      <VisualQueryBuilder
        schema={mockSchema}
        value={controlledSpec}
        onChange={handleChange}
      />,
    );

    // Initial render reflects controlledSpec
    expect(screen.getByText("orders")).toBeTruthy();
    expect(screen.getByText("orders.amount")).toBeTruthy();

    // Toggle a column in orders table (e.g. user_id)
    const userColToggle = screen.getByText("user_id");
    fireEvent.click(userColToggle);

    await waitFor(() => {
      expect(handleChange).toHaveBeenCalled();
      const lastCall = handleChange.mock.calls[handleChange.mock.calls.length - 1];
      const updatedSpec = lastCall[0] as QuerySpec;
      expect(updatedSpec.columns).toContain("orders.user_id");
    });

    // Outer prop update
    const nextSpec: QuerySpec = {
      table: "users",
      columns: ["users.id", "users.email"],
      limit: 10,
    };
    rerender(
      <VisualQueryBuilder
        schema={mockSchema}
        value={nextSpec}
        onChange={handleChange}
      />,
    );

    expect(screen.getByText("users")).toBeTruthy();
    expect(screen.getByText("users.email")).toBeTruthy();
  });

  it("supports controlled mode with real React state, single-step undo and redo", async () => {
    function ControlledHost() {
      const [spec, setSpec] = React.useState<QuerySpec>({
        table: "orders",
        columns: ["orders.id"],
        limit: 25,
      });
      return (
        <VisualQueryBuilder
          schema={mockSchema}
          value={spec}
          onChange={(newSpec) => setSpec(newSpec)}
        />
      );
    }

    render(<ControlledHost />);

    // On mount, history should be clean (canUndo is false)
    const undoBtn = screen.getByText("↶ Undo") as HTMLButtonElement;
    const redoBtn = screen.getByText("↷ Redo") as HTMLButtonElement;
    expect(undoBtn.disabled).toBe(true);
    expect(redoBtn.disabled).toBe(true);

    // Toggle user_id
    const userColToggle = screen.getByText("user_id");
    fireEvent.click(userColToggle);

    await waitFor(() => {
      expect(screen.getByText("orders.user_id")).toBeTruthy();
    });
    expect(undoBtn.disabled).toBe(false);
    expect(redoBtn.disabled).toBe(true);

    // Click Undo
    fireEvent.click(undoBtn);

    await waitFor(() => {
      expect(screen.queryByText("orders.user_id")).toBeNull();
    });
    expect(redoBtn.disabled).toBe(false);

    // Click Redo
    fireEvent.click(redoBtn);

    await waitFor(() => {
      expect(screen.getByText("orders.user_id")).toBeTruthy();
    });
  });

  it("supports uncontrolled mode with initialSpec", () => {
    const initialSpec: QuerySpec = {
      table: "orders",
      columns: ["orders.id", "orders.amount"],
      limit: 100,
      distinct: true,
    };

    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialSpec={initialSpec}
      />,
    );

    expect(screen.getByText("orders")).toBeTruthy();
    expect(screen.getByText("orders.amount")).toBeTruthy();
    expect(screen.getByDisplayValue("100")).toBeTruthy();
  });

  it("exposes imperative ref handle methods (getSpec, getSql, setSpec, reset, undo, redo)", () => {
    const ref = React.createRef<VisualQueryBuilderRef>();

    render(
      <VisualQueryBuilder
        ref={ref}
        schema={mockSchema}
        initialTable="users"
      />,
    );

    expect(ref.current).toBeDefined();
    expect(typeof ref.current?.getSpec).toBe("function");
    expect(typeof ref.current?.getSql).toBe("function");
    expect(typeof ref.current?.setSpec).toBe("function");
    expect(typeof ref.current?.reset).toBe("function");
    expect(typeof ref.current?.undo).toBe("function");
    expect(typeof ref.current?.redo).toBe("function");

    const spec = ref.current!.getSpec();
    expect(spec.table).toBe("users");

    const sql = ref.current!.getSql();
    expect(sql).toContain('FROM "users"');

    // setSpec imperatively inside act
    act(() => {
      ref.current!.setSpec({
        table: "orders",
        columns: ["orders.id", "orders.amount"],
        limit: 42,
      });
    });

    const updatedSpec = ref.current!.getSpec();
    expect(updatedSpec.table).toBe("orders");

    // reset imperatively inside act
    act(() => {
      ref.current!.reset();
    });
    const resetSpec = ref.current!.getSpec();
    expect(resetSpec.table).toBe("users");
  });

  it("supports undo and redo via actions-bar buttons", async () => {
    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
      />,
    );

    const undoBtn = screen.getByText("↶ Undo") as HTMLButtonElement;
    const redoBtn = screen.getByText("↷ Redo") as HTMLButtonElement;

    // Initially nothing to undo or redo
    expect(undoBtn.disabled).toBe(true);
    expect(redoBtn.disabled).toBe(true);

    // Make a change: toggle users.email column
    const emailToggle = screen.getByText("email");
    fireEvent.click(emailToggle);

    expect(screen.getByText("users.email")).toBeTruthy();
    expect(undoBtn.disabled).toBe(false);

    // Click Undo
    fireEvent.click(undoBtn);

    // Column users.email should be undone
    expect(screen.queryByText("users.email")).toBeNull();
    expect(redoBtn.disabled).toBe(false);

    // Click Redo
    fireEvent.click(redoBtn);

    // Column users.email should be restored
    expect(screen.getByText("users.email")).toBeTruthy();
  });

  it("supports undo and redo via keyboard shortcuts (Cmd+Z / Ctrl+Z and Cmd+Shift+Z / Ctrl+Y)", () => {
    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
      />,
    );

    // Toggle column
    const emailToggle = screen.getByText("email");
    fireEvent.click(emailToggle);
    expect(screen.getByText("users.email")).toBeTruthy();

    // Trigger Ctrl+Z / Cmd+Z
    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    expect(screen.queryByText("users.email")).toBeNull();

    // Trigger Ctrl+Y / Cmd+Y
    fireEvent.keyDown(window, { key: "y", ctrlKey: true });
    expect(screen.getByText("users.email")).toBeTruthy();
  });

  it("auto-wires schema fetching and query execution when client is passed without schema or execute handler", async () => {
    const mockResultData: QueryResultData = {
      columns: ["id", "email"],
      rows: [{ id: 1, email: "alice@example.com" }],
      count: 1,
      durationMs: 15,
    };

    const mockClient: QueryBuilderClient = {
      getSchema: vi.fn().mockResolvedValue(mockSchema),
      compile: vi.fn(),
      validate: vi.fn(),
      execute: vi.fn().mockResolvedValue(mockResultData),
      export: vi.fn(),
      query: vi.fn(),
    };

    render(<VisualQueryBuilder client={mockClient} />);

    // Auto-fetches schema from client
    await waitFor(() => {
      expect(mockClient.getSchema).toHaveBeenCalled();
    });

    // Wait for table to appear on canvas
    await waitFor(() => {
      expect(screen.getByText("users")).toBeTruthy();
    });

    // Execute query button click
    const runBtn = screen.getByText("▶ Run Query");
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(mockClient.execute).toHaveBeenCalled();
      expect(screen.getByText("alice@example.com")).toBeTruthy();
    });
  });

  it("is insensitive to object key ordering in controlled value prop and does not trigger false history entries", async () => {
    const handleChange = vi.fn();

    // Pass value with keys ordered differently
    const specA: QuerySpec = {
      limit: 50,
      columns: ["orders.id"],
      table: "orders",
    };

    const { rerender } = render(
      <VisualQueryBuilder
        schema={mockSchema}
        value={specA}
        onChange={handleChange}
      />,
    );

    const undoBtn = screen.getByText("↶ Undo") as HTMLButtonElement;
    expect(undoBtn.disabled).toBe(true);

    // Re-render with equivalent spec having reversed key order
    const specB: any = {
      table: "orders",
      limit: 50,
      columns: ["orders.id"],
    };

    rerender(
      <VisualQueryBuilder
        schema={mockSchema}
        value={specB}
        onChange={handleChange}
      />,
    );

    // Undo should still be disabled because no actual state change occurred
    expect(undoBtn.disabled).toBe(true);
    expect(handleChange).not.toHaveBeenCalled();
  });
});
