import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import {
  SchemaErdModal,
  QueryCanvas,
  TableFiltersEditor,
  VisualQueryBuilder,
  useQueryBuilder,
  useQueryState,
  compileVisualState,
  type SchemaSnapshot,
  type TableMeta,
} from "../src";
import { renderHook } from "@testing-library/react";

describe("M3 Remediation Comprehensive Suite", () => {
  const mockSchema: SchemaSnapshot = {
    tables: {
      users: {
        name: "users",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "name", data_type: "varchar", is_nullable: false, is_primary: false },
        ],
      },
      orders: {
        name: "orders",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
        ],
      },
      order_items: {
        name: "order_items",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "order_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "product_id", data_type: "integer", is_nullable: false, is_primary: false },
        ],
      },
      products: {
        name: "products",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "title", data_type: "varchar", is_nullable: false, is_primary: false },
        ],
      },
      isolated: {
        name: "isolated",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        ],
      },
    },
    foreign_keys: [
      { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
      { table: "order_items", column: "order_id", foreign_table: "orders", foreign_column: "id" },
      { table: "order_items", column: "product_id", foreign_table: "products", foreign_column: "id" },
    ],
  };

  describe("SchemaErdModal Enhancements", () => {
    it("filters tables in ERD modal via search input", () => {
      render(<SchemaErdModal isOpen={true} onClose={vi.fn()} schema={mockSchema} />);

      const searchInput = screen.getByLabelText("Search tables or columns");
      expect(searchInput).toBeTruthy();

      // Initially all tables rendered
      expect(screen.getByText("users")).toBeTruthy();
      expect(screen.getByText("products")).toBeTruthy();

      // Search for 'product'
      act(() => {
        fireEvent.change(searchInput, { target: { value: "product" } });
      });

      expect(screen.getByText("products")).toBeTruthy();
      expect(screen.queryByText("users")).toBeNull();
    });

    it("displays detailed foreign key relationship mappings", () => {
      render(<SchemaErdModal isOpen={true} onClose={vi.fn()} schema={mockSchema} />);

      expect(
        screen.getAllByText("orders.user_id ➔ users.id (FK)"),
      ).toHaveLength(2);
    });

    it("discovers multi-hop foreign key bridge and invokes onAddJoins", () => {
      const onAddJoins = vi.fn();
      const onClose = vi.fn();

      render(
        <SchemaErdModal
          isOpen={true}
          onClose={onClose}
          schema={mockSchema}
          onAddJoins={onAddJoins}
        />,
      );

      // Select source: users, target: products
      const sourceSelect = screen.getByLabelText("Bridge source table");
      const targetSelect = screen.getByLabelText("Bridge target table");
      const findBtn = screen.getByText("Discover Bridge");

      act(() => {
        fireEvent.change(sourceSelect, { target: { value: "users" } });
        fireEvent.change(targetSelect, { target: { value: "products" } });
        fireEvent.click(findBtn);
      });

      expect(screen.getByText(/Path \(3 hops\):/)).toBeTruthy();

      const addBtn = screen.getByText("Add Bridge Joins to Canvas");
      act(() => {
        fireEvent.click(addBtn);
      });

      expect(onAddJoins).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });

    it("shows notice when no bridge path can be found", () => {
      render(<SchemaErdModal isOpen={true} onClose={vi.fn()} schema={mockSchema} />);

      const sourceSelect = screen.getByLabelText("Bridge source table");
      const targetSelect = screen.getByLabelText("Bridge target table");
      const findBtn = screen.getByText("Discover Bridge");

      act(() => {
        fireEvent.change(sourceSelect, { target: { value: "users" } });
        fireEvent.change(targetSelect, { target: { value: "isolated" } });
        fireEvent.click(findBtn);
      });

      expect(screen.getByText("No bridge path found between selected tables.")).toBeTruthy();
    });

    it("handles keyboard focus trap on Tab and Shift+Tab", () => {
      render(<SchemaErdModal isOpen={true} onClose={vi.fn()} schema={mockSchema} />);

      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeTruthy();

      // Trigger Tab key
      fireEvent.keyDown(window, { key: "Tab" });
      // Trigger Shift+Tab key
      fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    });
  });

  describe("QueryCanvas & TableCard Fixes", () => {
    it("renders empty state container when activeTables is empty", () => {
      render(
        <QueryCanvas
          schema={mockSchema}
          activeTables={[]}
          primaryTable=""
          selectedColumns={{}}
          orderedProjectionKeys={[]}
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
        />,
      );

      expect(
        screen.getByText("No tables in query. Select a table to start building."),
      ).toBeTruthy();
    });

    it("renders onAddJoin button on TableCard and invokes onAddJoin", () => {
      const onAddJoin = vi.fn();
      render(
        <QueryCanvas
          schema={mockSchema}
          activeTables={[mockSchema.tables.users]}
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
          onAddTableToCanvas={vi.fn()}
          onAddJoin={onAddJoin}
          onUpdateColumnSelect={vi.fn()}
          onRemoveColumnProjection={vi.fn()}
          onJoinsChange={vi.fn()}
          onFiltersChange={vi.fn()}
          onSortsChange={vi.fn()}
          onDistinctChange={vi.fn()}
          onLimitChange={vi.fn()}
        />,
      );

      const joinBtn = screen.getByLabelText("Add join for table users");
      expect(joinBtn).toBeTruthy();

      act(() => {
        fireEvent.click(joinBtn);
      });

      expect(onAddJoin).toHaveBeenCalledWith("users");
    });

    it("supports projection alias edit input and pill reordering", () => {
      const onUpdateCol = vi.fn();
      const onReorder = vi.fn();

      render(
        <QueryCanvas
          schema={mockSchema}
          activeTables={[mockSchema.tables.users]}
          primaryTable="users"
          selectedColumns={{
            "users.id": { table: "users", name: "id", alias: "uid" },
            "users.name": { table: "users", name: "name" },
          }}
          orderedProjectionKeys={["users.id", "users.name"]}
          joins={[]}
          filters={[]}
          sorts={[]}
          isDistinct={false}
          limit={50}
          onToggleColumn={vi.fn()}
          onRemoveTable={vi.fn()}
          onAddTableToCanvas={vi.fn()}
          onReorderProjections={onReorder}
          onUpdateColumnSelect={onUpdateCol}
          onRemoveColumnProjection={vi.fn()}
          onJoinsChange={vi.fn()}
          onFiltersChange={vi.fn()}
          onSortsChange={vi.fn()}
          onDistinctChange={vi.fn()}
          onLimitChange={vi.fn()}
        />,
      );

      // Edit alias
      const aliasInput = screen.getByLabelText("Alias for users.id");
      act(() => {
        fireEvent.change(aliasInput, { target: { value: "user_ident" } });
      });
      expect(onUpdateCol).toHaveBeenCalledWith("users.id", { alias: "user_ident" });

      // Move left and right
      const moveRight = screen.getByLabelText("Move users.id right");
      act(() => {
        fireEvent.click(moveRight);
      });
      expect(onReorder).toHaveBeenCalledWith(["users.name", "users.id"]);

      const moveLeft = screen.getByLabelText("Move users.name left");
      act(() => {
        fireEvent.click(moveLeft);
      });
      expect(onReorder).toHaveBeenCalled();
    });

    it("compiler disambiguates alias collisions automatically", () => {
      const res = compileVisualState(
        "users",
        {
          "users.id": { table: "users", name: "id", aggregate: "COUNT" },
          "orders.id": { table: "orders", name: "id", aggregate: "COUNT" },
        },
        ["users.id", "orders.id"],
        [{ id: "j1", table: "orders", type: "LEFT JOIN", left_col: "id", right_col: "user_id" }],
        [],
        [],
      );

      // Two count(id) projections should produce different aliases: count_id and count_orders_id
      expect(res.sql).toContain('COUNT("users"."id") AS "count_id"');
      expect(res.sql).toContain('COUNT("orders"."id") AS "count_orders_id"');
    });
  });

  describe("TableFiltersEditor & Boolean Combiner", () => {
    it("toggles combiner between AND and OR in TableFiltersEditor", () => {
      const onFiltersChange = vi.fn();
      render(
        <TableFiltersEditor
          activeTables={[mockSchema.tables.users]}
          filters={[
            { id: "f1", tablePrefix: "users", column: "id", operator: "=", value: 1 },
            { id: "f2", tablePrefix: "users", column: "name", operator: "=", value: "Alice", combiner: "AND" },
          ]}
          onChange={onFiltersChange}
        />,
      );

      const toggleBtn = screen.getByLabelText("Toggle combiner for filter 1");
      expect(toggleBtn).toBeTruthy();
      expect(toggleBtn.textContent).toBe("AND");

      act(() => {
        fireEvent.click(toggleBtn);
      });

      expect(onFiltersChange).toHaveBeenCalledWith([
        { id: "f1", tablePrefix: "users", column: "id", operator: "=", value: 1 },
        { id: "f2", tablePrefix: "users", column: "name", operator: "=", value: "Alice", combiner: "OR" },
      ]);
    });

    it("compiler respects individual filter combiner and filter_join", () => {
      const res = compileVisualState(
        "users",
        { "users.id": { table: "users", name: "id" } },
        ["users.id"],
        [],
        [
          { id: "f1", tablePrefix: "users", column: "id", operator: ">", value: 5 },
          { id: "f2", tablePrefix: "users", column: "name", operator: "=", value: "Alice", combiner: "OR" },
        ],
        [],
      );

      expect(res.sql).toContain('WHERE "users"."id" > 5 OR "users"."name" = \'Alice\'');
      expect(res.spec.filter_join).toBe("OR");
    });
  });

  describe("Headless Hooks Hardening", () => {
    it("autoJoinTable in useQueryState uses findJoinPath and updates activeTables", () => {
      const { result } = renderHook(() =>
        useQueryState({
          table: "users",
          columns: ["users.id"],
        }),
      );

      act(() => {
        result.current.actions.autoJoinTable("products", mockSchema);
      });

      // Should automatically find multi-hop join: users -> orders -> order_items -> products
      expect(result.current.state.joins.length).toBeGreaterThanOrEqual(1);
      expect(result.current.state.activeTables).toContain("products");
    });

    it("autoJoinTable in useQueryState fallbacks to findBestJoinCondition when no FK path", () => {
      const { result } = renderHook(() =>
        useQueryState({
          table: "users",
          columns: ["users.id"],
        }),
      );

      act(() => {
        result.current.actions.autoJoinTable("isolated", mockSchema);
      });

      expect(result.current.state.joins).toHaveLength(1);
      expect(result.current.state.activeTables).toContain("isolated");
    });

    it("autoJoinTable in useQueryBuilder performs auto join", () => {
      const { result } = renderHook(() =>
        useQueryBuilder({
          schema: mockSchema,
          initialTable: "users",
        }),
      );

      act(() => {
        result.current.actions.autoJoinTable("orders");
      });

      expect(result.current.state.joins).toHaveLength(1);
      expect(result.current.state.activeTableNames).toContain("orders");
    });
  });

  describe("VisualQueryBuilder Bidirectional Sync", () => {
    it("synchronizes raw SQL edits to visual canvas and QuerySpec state", async () => {
      const onExecute = vi.fn().mockResolvedValue({ columns: ["id"], rows: [], count: 0 });

      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          onExecuteQuery={onExecute}
        />,
      );

      // Switch to SQL tab
      const sqlTab = screen.getByText("📝 Raw SQL");
      act(() => {
        fireEvent.click(sqlTab);
      });

      const sqlEditor = screen.getByLabelText("Raw SQL code") as HTMLTextAreaElement;

      // Edit raw SQL to target orders table with WHERE and LIMIT
      act(() => {
        fireEvent.change(sqlEditor, {
          target: {
            value: "SELECT orders.id, orders.total FROM orders WHERE orders.total > 50 LIMIT 15;",
          },
        });
      });

      // Run query
      const runBtn = screen.getByText("▶ Run Query");
      await act(async () => {
        fireEvent.click(runBtn);
      });

      expect(onExecute).toHaveBeenCalled();
      const calledSpec = onExecute.mock.calls[0][1];
      expect(calledSpec.table).toBe("orders");
      expect(calledSpec.limit).toBe(15);
      expect(calledSpec.filters).toHaveLength(1);
    });

    it("shows un-synced warning badge when custom SQL cannot be parsed", () => {
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
        />,
      );

      // Switch to SQL tab
      act(() => {
        fireEvent.click(screen.getByText("📝 Raw SQL"));
      });

      const sqlEditor = screen.getByLabelText("Raw SQL code");

      act(() => {
        fireEvent.change(sqlEditor, {
          target: { value: "INVALID UNPARSABLE SQL" },
        });
      });

      expect(screen.getByText("Custom Raw SQL (Visual Canvas Unsynced)")).toBeTruthy();
    });

    it("Sync with Visual Canvas button resets raw mode to compiled SQL", () => {
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
        />,
      );

      act(() => {
        fireEvent.click(screen.getByText("📝 Raw SQL"));
      });

      const sqlEditor = screen.getByLabelText("Raw SQL code") as HTMLTextAreaElement;

      act(() => {
        fireEvent.change(sqlEditor, {
          target: { value: "SELECT id FROM users LIMIT 10;" },
        });
      });

      const syncBtn = screen.getByLabelText("Sync with visual canvas");
      act(() => {
        fireEvent.click(syncBtn);
      });

      expect(sqlEditor.value).toContain('FROM "users"');
    });
  });
});
