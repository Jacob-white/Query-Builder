import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  useQueryState,
  stateToSpec,
  specToState,
  MAX_HISTORY_LENGTH,
  type QueryState,
} from "../src";

describe("useQueryState Standalone Hook & State History", () => {
  it("initializes with default empty state when given no args", () => {
    const { result } = renderHook(() => useQueryState());

    expect(result.current.state.primaryTable).toBe("");
    expect(result.current.state.activeTables).toEqual([]);
    expect(result.current.state.limit).toBe(50);
    expect(result.current.state.offset).toBe(0);
    expect(result.current.state.dialect).toBe("postgres");
    expect(result.current.state.isDistinct).toBe(false);
    expect(result.current.state.isDirty).toBe(false);
    expect(result.current.history.canUndo).toBe(false);
    expect(result.current.history.canRedo).toBe(false);
  });

  it("initializes from QuerySpec or partial QueryState", () => {
    const { result } = renderHook(() =>
      useQueryState({
        table: "orders",
        columns: ["orders.id", { column: "orders.total", agg: "SUM", alias: "sum_total" }],
        joins: [
          {
            table: "customers",
            type: "LEFT JOIN",
            on: [{ left: "orders.customer_id", right: "customers.id" }],
          },
        ],
        filters: [{ column: "orders.status", op: "=", value: "active" }],
        order_by: [{ column: "orders.created_at", direction: "DESC" }],
        distinct: true,
        limit: 100,
        offset: 20,
        dialect: "sqlite",
      }),
    );

    expect(result.current.state.primaryTable).toBe("orders");
    expect(result.current.state.activeTables).toEqual(["orders"]);
    expect(result.current.state.selectedColumns["orders.id"]).toBeDefined();
    expect(result.current.state.selectedColumns["orders.total"].aggregate).toBe("SUM");
    expect(result.current.state.selectedColumns["orders.total"].alias).toBe("sum_total");
    expect(result.current.state.joins.length).toBe(1);
    expect(result.current.state.joins[0].table).toBe("customers");
    expect(result.current.state.joins[0].left_table).toBe("orders");
    expect(result.current.state.joins[0].left_col).toBe("customer_id");
    expect(result.current.state.joins[0].right_col).toBe("id");
    expect(result.current.state.filters.length).toBe(1);
    expect(result.current.state.sorts.length).toBe(1);
    expect(result.current.state.isDistinct).toBe(true);
    expect(result.current.state.limit).toBe(100);
    expect(result.current.state.offset).toBe(20);
    expect(result.current.state.dialect).toBe("sqlite");
  });

  it("handles table management actions: setTables, setPrimaryTable, addTable, removeTable", () => {
    const { result } = renderHook(() => useQueryState());

    act(() => {
      result.current.actions.setPrimaryTable("users");
    });
    expect(result.current.state.primaryTable).toBe("users");
    expect(result.current.state.activeTables).toEqual(["users"]);

    act(() => {
      result.current.actions.addTable("profiles");
    });
    expect(result.current.state.activeTables).toEqual(["users", "profiles"]);

    // addTable ignores duplicate
    act(() => {
      result.current.actions.addTable("profiles");
    });
    expect(result.current.state.activeTables).toEqual(["users", "profiles"]);

    act(() => {
      result.current.actions.setTables(["accounts", "users"]);
    });
    expect(result.current.state.activeTables).toEqual(["accounts", "users"]);
    expect(result.current.state.primaryTable).toBe("users");

    // setPrimaryTable when already in activeTables
    act(() => {
      result.current.actions.setPrimaryTable("accounts");
    });
    expect(result.current.state.primaryTable).toBe("accounts");

    // Add columns across multiple tables and remove one table
    act(() => {
      result.current.actions.toggleColumn("accounts", "id");
      result.current.actions.toggleColumn("users", "email");
      result.current.actions.removeTable("users");
    });
    expect(result.current.state.selectedColumns["accounts.id"]).toBeDefined();
    expect(result.current.state.selectedColumns["users.email"]).toBeUndefined();

    act(() => {
      result.current.actions.removeTable("accounts");
    });
    expect(result.current.state.primaryTable).toBe("");
    expect(result.current.state.activeTables).toEqual([]);
  });

  it("handles column actions: toggleColumn, updateColumnSelect, removeColumnProjection", () => {
    const { result } = renderHook(() =>
      useQueryState({
        table: "users",
      }),
    );

    act(() => {
      result.current.actions.toggleColumn("users", "email");
      result.current.actions.toggleColumn("users", "name");
    });
    expect(result.current.state.orderedProjectionKeys).toEqual(["users.email", "users.name"]);

    act(() => {
      result.current.actions.updateColumnSelect("users.email", { alias: "user_email" });
    });
    expect(result.current.state.selectedColumns["users.email"].alias).toBe("user_email");

    // non-existent column update is no-op
    act(() => {
      result.current.actions.updateColumnSelect("users.nonexistent", { alias: "test" });
    });

    act(() => {
      result.current.actions.removeColumnProjection("users.email");
    });
    expect(result.current.state.selectedColumns["users.email"]).toBeUndefined();
    expect(result.current.state.orderedProjectionKeys).toEqual(["users.name"]);
  });

  it("handles join, filter, and sort actions", () => {
    const { result } = renderHook(() => useQueryState({ table: "users" }));

    // Joins
    act(() => {
      result.current.actions.addJoin({
        id: "j1",
        type: "LEFT JOIN",
        table: "orders",
        left_col: "id",
        right_col: "user_id",
      });
    });
    expect(result.current.state.joins.length).toBe(1);

    act(() => {
      result.current.actions.updateJoin("j1", { type: "INNER JOIN" });
    });
    expect(result.current.state.joins[0].type).toBe("INNER JOIN");

    act(() => {
      result.current.actions.removeJoin("j1");
    });
    expect(result.current.state.joins.length).toBe(0);

    // Filters
    act(() => {
      result.current.actions.addFilter({
        id: "f1",
        column: "age",
        operator: ">=",
        value: 18,
      });
    });
    expect(result.current.state.filters.length).toBe(1);

    act(() => {
      result.current.actions.updateFilter("f1", { value: 21 });
    });
    expect(result.current.state.filters[0].value).toBe(21);

    act(() => {
      result.current.actions.removeFilter("f1");
    });
    expect(result.current.state.filters.length).toBe(0);

    // Sorts
    act(() => {
      result.current.actions.addSort({
        id: "s1",
        column: "id",
        direction: "ASC",
      });
    });
    expect(result.current.state.sorts.length).toBe(1);

    act(() => {
      result.current.actions.updateSort("s1", { direction: "DESC" });
    });
    expect(result.current.state.sorts[0].direction).toBe("DESC");

    act(() => {
      result.current.actions.removeSort("s1");
    });
    expect(result.current.state.sorts.length).toBe(0);

    // Limit, Offset, Distinct, Dialect
    act(() => {
      result.current.actions.setLimit(10);
      result.current.actions.setOffset(5);
      result.current.actions.setDistinct(true);
      result.current.actions.setDialect("mysql");
    });
    expect(result.current.state.limit).toBe(10);
    expect(result.current.state.offset).toBe(5);
    expect(result.current.state.isDistinct).toBe(true);
    expect(result.current.state.dialect).toBe("mysql");
  });

  it("handles undo, redo, and history capping", () => {
    const { result } = renderHook(() => useQueryState({ table: "users" }));

    expect(result.current.history.canUndo).toBe(false);
    expect(result.current.history.canRedo).toBe(false);

    // Initial action
    act(() => {
      result.current.actions.setLimit(20);
    });
    expect(result.current.state.limit).toBe(20);
    expect(result.current.history.canUndo).toBe(true);
    expect(result.current.history.canRedo).toBe(false);

    // Another action
    act(() => {
      result.current.actions.setLimit(30);
    });
    expect(result.current.state.limit).toBe(30);

    // Undo once
    act(() => {
      result.current.actions.undo();
    });
    expect(result.current.state.limit).toBe(20);
    expect(result.current.history.canUndo).toBe(true);
    expect(result.current.history.canRedo).toBe(true);

    // Redo once
    act(() => {
      result.current.actions.redo();
    });
    expect(result.current.state.limit).toBe(30);
    expect(result.current.history.canUndo).toBe(true);
    expect(result.current.history.canRedo).toBe(false);

    // Undo all the way
    act(() => {
      result.current.actions.undo();
      result.current.actions.undo();
    });
    expect(result.current.state.limit).toBe(50);
    expect(result.current.history.canUndo).toBe(false);
    expect(result.current.history.canRedo).toBe(true);

    // Redo when nothing to redo or undo when nothing to undo
    act(() => {
      result.current.actions.undo();
    });
    expect(result.current.history.canUndo).toBe(false);

    // Redo all
    act(() => {
      result.current.actions.redo();
      result.current.actions.redo();
    });
    expect(result.current.state.limit).toBe(30);
    act(() => {
      result.current.actions.redo();
    });
    expect(result.current.history.canRedo).toBe(false);

    // Clear history
    act(() => {
      result.current.actions.clearHistory();
    });
    expect(result.current.history.canUndo).toBe(false);
    expect(result.current.history.canRedo).toBe(false);

    // Verify history stack capping
    act(() => {
      for (let i = 1; i <= MAX_HISTORY_LENGTH + 10; i++) {
        result.current.actions.setLimit(i);
      }
    });
    expect(result.current.history.past.length).toBe(MAX_HISTORY_LENGTH);

    // Reset restores initial state and clears history
    act(() => {
      result.current.actions.reset();
    });
    expect(result.current.state.limit).toBe(50);
    expect(result.current.history.past.length).toBe(0);
    expect(result.current.state.isDirty).toBe(false);
  });

  it("converts bidirectionally with stateToSpec and specToState", () => {
    const rawSpec = {
      primaryTable: "invoices",
      activeTables: ["invoices", "clients"],
      columns: [
        "invoices.id",
        { column: "invoices.amount", agg: "AVG", alias: "avg_amount" },
      ],
      joins: [
        {
          id: "join_1",
          table: "clients",
          type: "INNER JOIN",
          on: [{ left: "invoices.client_id", right: "clients.id" }],
        },
      ],
      filters: [
        {
          id: "f_1",
          column: "invoices.status",
          op: "=",
          value: "paid",
        },
      ],
      sorts: [
        {
          id: "s_1",
          tablePrefix: "invoices",
          column: "id",
          direction: "DESC",
        },
      ],
      distinct: true,
      limit: 10,
    };

    const state = specToState(rawSpec);
    expect(state.primaryTable).toBe("invoices");
    expect(state.activeTables).toEqual(["invoices", "clients"]);
    expect(state.selectedColumns?.["invoices.id"]).toBeDefined();
    expect(state.selectedColumns?.["invoices.amount"]?.aggregate).toBe("AVG");
    expect(state.joins?.[0].type).toBe("INNER JOIN");
    expect(state.filters?.[0].operator).toBe("=");
    expect(state.sorts?.[0].direction).toBe("DESC");

    const fullState: QueryState = {
      primaryTable: "invoices",
      activeTables: ["invoices"],
      selectedColumns: {
        "invoices.id": { table: "invoices", name: "id" },
        "invoices.amount": { table: "invoices", name: "amount", aggregate: "AVG", alias: "avg_amount" },
      },
      orderedProjectionKeys: ["invoices.id", "invoices.amount"],
      joins: [
        {
          id: "j1",
          type: "INNER JOIN",
          left_table: "invoices",
          left_col: "client_id",
          table: "clients",
          right_col: "id",
        },
      ],
      filters: [
        {
          id: "f1",
          column: "status",
          tablePrefix: "invoices",
          operator: "=",
          value: "paid",
        },
      ],
      sorts: [
        {
          id: "s1",
          tablePrefix: "invoices",
          column: "id",
          direction: "DESC",
        },
      ],
      isDistinct: true,
      limit: 10,
      offset: 0,
      dialect: "postgres",
      isDirty: false,
    };

    const generatedSpec = stateToSpec(fullState);
    expect(generatedSpec.table).toBe("invoices");
    expect(generatedSpec.columns).toEqual([
      "invoices.id",
      { column: "invoices.amount", agg: "AVG", alias: "avg_amount" },
    ]);
    expect(generatedSpec.joins[0].on).toEqual([
      { left: "invoices.client_id", right: "clients.id" },
    ]);
    expect(generatedSpec.filters[0]).toEqual({
      column: "status",
      op: "=",
      value: "paid",
      tablePrefix: "invoices",
    });
    expect(generatedSpec.order_by[0]).toEqual({
      column: "invoices.id",
      direction: "DESC",
    });
    expect(generatedSpec.distinct).toBe(true);
    expect(generatedSpec.limit).toBe(10);
  });

  it("marks state as clean via markClean action", () => {
    const { result } = renderHook(() => useQueryState({ table: "users" }));
    act(() => {
      result.current.actions.setLimit(99);
    });
    expect(result.current.state.isDirty).toBe(true);
    act(() => {
      result.current.actions.markClean();
    });
    expect(result.current.state.isDirty).toBe(false);
  });

  it("toggles column off when already selected in useQueryState", () => {
    const { result } = renderHook(() => useQueryState({ table: "users" }));
    act(() => {
      result.current.actions.toggleColumn("users", "email");
    });
    expect(result.current.state.selectedColumns["users.email"]).toBeDefined();
    expect(result.current.state.orderedProjectionKeys).toContain("users.email");

    act(() => {
      result.current.actions.toggleColumn("users", "email");
    });
    expect(result.current.state.selectedColumns["users.email"]).toBeUndefined();
    expect(result.current.state.orderedProjectionKeys).not.toContain("users.email");
  });

  it("loads spec into active state and exercises spec parser variations", () => {
    const { result } = renderHook(() => useQueryState());
    act(() => {
      result.current.actions.loadSpec({
        table: "orders",
        columns: [
          "id",
          { column: "amount", agg: "MAX", alias: "max_amount" },
        ],
        joins: [
          {
            table: "users",
            on: [{ left: "user_id", right: "id" }],
          },
        ],
        filters: [
          { column: "orders.id", operator: ">", value: 10 },
          { column: "amount", operator: "<", value: 500 },
        ],
        order_by: [
          { column: "orders.amount", direction: "DESC" },
          { column: "id", direction: "ASC" },
        ],
        distinct: false,
        limit: 30,
        offset: 10,
        dialect: "sqlite",
      });
    });

    expect(result.current.state.primaryTable).toBe("orders");
    expect(result.current.state.activeTables).toEqual(["orders"]);
    expect(result.current.state.limit).toBe(30);
    expect(result.current.state.offset).toBe(10);
    expect(result.current.state.dialect).toBe("sqlite");
    expect(result.current.state.selectedColumns["orders.id"]).toBeDefined();
    expect(result.current.state.selectedColumns["orders.amount"]?.aggregate).toBe("MAX");
    expect(result.current.state.joins[0].left_col).toBe("user_id");
    expect(result.current.state.joins[0].right_col).toBe("id");
    expect(result.current.state.filters.length).toBe(2);
    expect(result.current.state.filters[0].tablePrefix).toBe("orders");
    expect(result.current.state.sorts.length).toBe(2);
    expect(result.current.state.sorts[0].tablePrefix).toBe("orders");

    // loadSpec with empty spec maintains activeTables fallback
    act(() => {
      result.current.actions.loadSpec({});
    });
    expect(result.current.state.primaryTable).toBe("orders");
    expect(result.current.state.activeTables).toEqual(["orders"]);
  });

  it("handles initial state without primary table and isDistinct fallback in spec parser", () => {
    const { result } = renderHook(() => useQueryState({ limit: 10 }));
    expect(result.current.state.primaryTable).toBe("");
    expect(result.current.state.activeTables).toEqual([]);
    expect(result.current.state.limit).toBe(10);

    const parsedState = specToState({
      isDistinct: true,
      order_by: [{ id: "custom_s1", column: "id", direction: "ASC" }],
    });
    expect(parsedState.isDistinct).toBe(true);
    expect(parsedState.sorts?.[0].id).toBe("custom_s1");

    const withSelectedCols = specToState({
      selectedColumns: { "users.id": { table: "users", name: "id" } },
    });
    expect(withSelectedCols.orderedProjectionKeys).toEqual(["users.id"]);

    const withExplicitKeys = specToState({
      selectedColumns: { "users.id": { table: "users", name: "id" } },
      orderedProjectionKeys: ["users.id"],
    });
    expect(withExplicitKeys.orderedProjectionKeys).toEqual(["users.id"]);

    const withColObjectNoAgg = specToState({
      columns: [{ column: "users.email", alias: "e" }],
    });
    expect(withColObjectNoAgg.selectedColumns?.["users.email"]?.alias).toBe("e");
    expect(withColObjectNoAgg.selectedColumns?.["users.email"]?.aggregate).toBeUndefined();

    const specFromSortNoPrefix = stateToSpec({
      primaryTable: "users",
      selectedColumns: {},
      orderedProjectionKeys: [],
      joins: [],
      filters: [],
      sorts: [{ id: "s1", column: "id", direction: "ASC" }],
      isDistinct: false,
      limit: 10,
      offset: 0,
      dialect: "postgres",
      isDirty: false,
      activeTables: ["users"],
    });
    expect(specFromSortNoPrefix.order_by[0].column).toBe("id");
  });
});
