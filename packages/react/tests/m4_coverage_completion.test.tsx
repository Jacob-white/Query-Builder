import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, act, fireEvent, renderHook } from "@testing-library/react";
import {
  QueryPlayground,
  QueryCanvas,
  SchemaErdModal,
  TableFiltersEditor,
  VisualQueryBuilder,
  ExportWorkbench,
  useQueryState,
  useQueryBuilder,
  useQueryExecution,
  useSqlCompiler,
  stateToSpec,
  specToState,
  compileVisualState,
  parseSqlToSpec,
  type QueryState,
} from "../src";
import { generateSdkSnippet } from "../src/components/ExportWorkbench";

describe("Milestone 4: Full Branch Coverage Verification", () => {
  it("covers useSqlCompiler edge branches, missing performance, and error handling", () => {
    // 1. state with selectedColumns undefined
    const mockState = {
      primaryTable: "users",
      selectedColumns: undefined,
      joins: [],
      filters: [],
      sorts: [],
      isDistinct: false,
      limit: 10,
    };
    const { result: stateResult } = renderHook(() => useSqlCompiler(mockState as any));
    expect(stateResult.current.sql).toBeDefined();

    // 2. Exception with non-Error string
    const throwingNonErrorSpec = {
      get primaryTable(): string {
        throw "String exception";
      },
    };
    const { result: nonErrorResult } = renderHook(() =>
      useSqlCompiler(throwingNonErrorSpec as any),
    );
    expect(nonErrorResult.current.isValid).toBe(false);
    expect(nonErrorResult.current.error).toBe("String exception");

    // 3. Exception with Error instance
    const throwingErrorSpec = {
      get primaryTable(): string {
        throw new Error("Explicit Error instance");
      },
    };
    const { result: errorResult } = renderHook(() =>
      useSqlCompiler(throwingErrorSpec as any),
    );
    expect(errorResult.current.isValid).toBe(false);
    expect(errorResult.current.error).toBe("Explicit Error instance");

    // 4. Fallback when performance is undefined
    const origPerf = globalThis.performance;
    try {
      // @ts-ignore
      delete globalThis.performance;
      const { result: perfUndefinedResult } = renderHook(() =>
        useSqlCompiler({
          table: "users",
          columns: ["users.id"],
        }),
      );
      expect(perfUndefinedResult.current.isValid).toBe(true);
      expect(perfUndefinedResult.current.compileTimeMs).toBe(0);

      const { result: perfUndefinedErrorResult } = renderHook(() =>
        useSqlCompiler(throwingErrorSpec as any),
      );
      expect(perfUndefinedErrorResult.current.compileTimeMs).toBe(0);
    } finally {
      globalThis.performance = origPerf;
    }
  });

  it("covers useQueryState edge branches: stateToSpec, specToState, and initial states", () => {
    // 1. stateToSpec with undefined joins, filters, sorts, and column with aggregate but without alias
    const partialState: Partial<QueryState> = {
      primaryTable: "users",
      selectedColumns: {
        "users.id": {
          table: "users",
          name: "id",
          aggregate: "COUNT",
          alias: undefined,
        },
      },
      orderedProjectionKeys: ["users.id"],
      joins: undefined as any,
      filters: undefined as any,
      sorts: undefined as any,
      isDistinct: false,
      limit: 20,
    };
    const spec = stateToSpec(partialState as any);
    expect(spec.joins).toEqual([]);
    expect(spec.filters).toEqual([]);
    expect(spec.order_by).toEqual([]);
    expect(spec.columns[0]).toEqual({
      column: "users.id",
      alias: undefined,
      agg: "COUNT",
    });

    // 2. specToState with filter having missing column property
    const parsed = specToState({
      table: "users",
      filters: [{ op: "=", value: 42 } as any],
    });
    expect(parsed.filters?.[0]?.column).toBe("");

    // 3. useQueryState with empty primaryTable
    const { result } = renderHook(() => useQueryState({ table: "" } as any));
    expect(result.current.state.activeTables).toEqual([]);
  });

  it("covers QueryPlayground AST and Codegen fallback branches", () => {
    // Render QueryPlayground with sparse spec to exercise fallback branches:
    // - spec.table falsy ("")
    // - spec.columns undefined
    // - spec.joins undefined
    // - spec.filters undefined
    // - spec.order_by undefined
    const sparseSpec = {
      table: "",
      columns: undefined,
      joins: undefined,
      filters: undefined,
      order_by: undefined,
    };

    const { unmount: unmountFirst } = render(
      <QueryPlayground
        initialSpec={sparseSpec as any}
        schema={{ tables: {} }}
      />,
    );

    // Check status bar with empty table
    expect(screen.getByText("None")).toBeDefined();

    // Switch to AST Visualizer tab
    const astTab = screen.getByText("AST Visualizer");
    act(() => {
      fireEvent.click(astTab);
    });

    // Check AST tab labels
    expect(screen.getByText("* (all columns)")).toBeDefined();
    expect(screen.getByText("No joins configured")).toBeDefined();
    expect(screen.getByText("No filters applied")).toBeDefined();
    expect(screen.getByText("Default database ordering")).toBeDefined();

    unmountFirst();

    // Render QueryPlayground with string column, object column without alias/agg, object column with alias/agg, and joins with/without columns
    const joinColSpec = {
      table: "",
      columns: [
        "users.id",
        { column: "users.name" },
        { column: "users.email", agg: "COUNT", alias: "email_cnt" },
      ],
      joins: [
        { table: "orders" } as any,
        { table: "items", left_col: "id", right_col: "item_id" },
      ],
      filters: [],
      order_by: [],
    };

    const { container, unmount: unmountSecond } = render(
      <QueryPlayground
        initialSpec={joinColSpec as any}
        schema={{ tables: {} }}
      />,
    );

    // Switch to Codegen tab
    const codegenTab = container.querySelector('[data-qb="playground-tab-codegen"]');
    expect(codegenTab).not.toBeNull();
    act(() => {
      fireEvent.click(codegenTab!);
    });

    const snippetPre = container.querySelector('[data-qb="playground-code-snippet"]');
    expect(snippetPre).toBeDefined();

    // Switch to AST Visualizer tab to verify column without agg
    const astTab2 = container.querySelector('[data-qb="playground-tab-ast"]');
    expect(astTab2).not.toBeNull();
    act(() => {
      fireEvent.click(astTab2!);
    });
    expect(container.textContent).toContain("users.name");

    unmountSecond();
  });

  it("covers ExportWorkbench edge branches for join columns and unstyled", () => {
    const snippet = generateSdkSnippet({
      table: "users",
      columns: ["id"],
      joins: [
        { table: "orders" } as any,
        { table: "items", left_col: "", right_col: "" } as any,
      ],
    });
    expect(snippet).toContain('.join("orders", "id", "=", "id")');
    expect(snippet).toContain('.join("items", "id", "=", "id")');
  });

  it("covers QueryCanvas unstyled branches for empty state and projection reorder buttons", () => {
    // Empty state unstyled
    const { container, unmount } = render(
      <QueryCanvas
        activeTables={[]}
        primaryTable=""
        onSelectPrimaryTable={() => {}}
        onAddTable={() => {}}
        onRemoveTable={() => {}}
        selectedColumns={{}}
        orderedProjectionKeys={[]}
        onToggleColumn={() => {}}
        onUpdateColumnSelect={() => {}}
        onRemoveColumnProjection={() => {}}
        joins={[]}
        unstyled={true}
      />,
    );
    const emptyState = container.querySelector('[data-qb="canvas-empty-state"]');
    expect(emptyState).not.toBeNull();
    expect(emptyState?.getAttribute("style")).toBeNull();
    unmount();

    // Reorder buttons unstyled
    const onReorder = vi.fn();
    const { container: container2, unmount: unmount2 } = render(
      <QueryCanvas
        activeTables={[{ name: "users", columns: [{ name: "id", data_type: "int" }, { name: "name", data_type: "varchar" }] }] as any}
        primaryTable="users"
        selectedColumns={{
          "users.id": { table: "users", name: "id" },
          "users.name": { table: "users", name: "name" },
        }}
        orderedProjectionKeys={["users.id", "users.name"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={10}
        onToggleColumn={() => {}}
        onRemoveTable={() => {}}
        onAddTableToCanvas={() => {}}
        onUpdateColumnSelect={() => {}}
        onRemoveColumnProjection={() => {}}
        onJoinsChange={() => {}}
        onFiltersChange={() => {}}
        onSortsChange={() => {}}
        onDistinctChange={() => {}}
        onLimitChange={() => {}}
        onReorderProjections={onReorder}
        unstyled={true}
      />,
    );
    const moveRight = container2.querySelector('[data-qb="projection-move-right"]');
    expect(moveRight).not.toBeNull();
    expect(moveRight?.getAttribute("style")).toBeNull();
    const moveLeft = container2.querySelectorAll('[data-qb="projection-move-left"]');
    expect(moveLeft.length).toBeGreaterThan(0);
    expect(moveLeft[0].getAttribute("style")).toBeNull();
    unmount2();
  });

  it("covers SchemaErdModal focus trap loop and bridge discovery when src === tgt or empty", () => {
    vi.useFakeTimers();
    const handleClose = vi.fn();
    const schema = {
      tables: {
        users: { name: "users", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }] },
      },
    };
    const { unmount } = render(
      <SchemaErdModal isOpen={true} onClose={handleClose} schema={schema as any} />,
    );
    act(() => {
      vi.advanceTimersByTime(100);
    });
    vi.useRealTimers();

    // Click Discover Bridge when source and target are empty
    const findBtn = screen.getByText("Discover Bridge");
    act(() => {
      fireEvent.click(findBtn);
    });
    expect(screen.getByText("No bridge path found between selected tables.")).toBeDefined();

    // Select same source and target
    const sourceSelect = screen.getByLabelText("Bridge source table");
    const targetSelect = screen.getByLabelText("Bridge target table");
    act(() => {
      fireEvent.change(sourceSelect, { target: { value: "users" } });
      fireEvent.change(targetSelect, { target: { value: "users" } });
      fireEvent.click(findBtn);
    });
    expect(screen.getByText("No bridge path found between selected tables.")).toBeDefined();

    // Focus trap: Tab on last element wraps to first element
    const dialog = screen.getByRole("dialog");
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    const last = focusable[focusable.length - 1];
    last.focus();
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(window, { key: "Tab", shiftKey: false });

    // Focus trap: Shift+Tab on first element wraps to last element
    const first = focusable[0];
    first.focus();
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });

    unmount();
  });

  it("covers TableFiltersEditor combiner toggles and unstyled mode", () => {
    const onUpdate = vi.fn();
    const filters = [
      { id: "f1", tablePrefix: "users", column: "id", operator: "=", value: "1", combiner: "AND" },
      { id: "f2", tablePrefix: "users", column: "name", operator: "=", value: "A", combiner: "OR" },
    ];
    const { container, unmount } = render(
      <TableFiltersEditor
        filters={filters as any}
        activeTables={[{ name: "users", columns: [{ name: "id", data_type: "int" }, { name: "name", data_type: "varchar" }] }] as any}
        onChange={onUpdate}
        unstyled={false}
      />,
    );
    const combinerBtn = container.querySelector('[data-qb="filter-combiner"]');
    expect(combinerBtn).not.toBeNull();
    // Toggle OR to AND
    act(() => {
      fireEvent.click(combinerBtn!);
    });
    expect(onUpdate).toHaveBeenCalledWith([filters[0], { ...filters[1], combiner: "AND" }]);
    unmount();

    // Now test with combiner === "AND" to toggle to "OR"
    const onUpdate2 = vi.fn();
    const filters2 = [
      { id: "f1", tablePrefix: "users", column: "id", operator: "=", value: "1", combiner: "AND" },
      { id: "f2", tablePrefix: "users", column: "name", operator: "=", value: "A", combiner: "AND" },
    ];
    const { container: container2, unmount: unmount2 } = render(
      <TableFiltersEditor
        filters={filters2 as any}
        activeTables={[{ name: "users", columns: [{ name: "id", data_type: "int" }, { name: "name", data_type: "varchar" }] }] as any}
        onChange={onUpdate2}
        unstyled={true}
      />,
    );
    const combinerBtn2 = container2.querySelector('[data-qb="filter-combiner"]');
    expect(combinerBtn2?.getAttribute("style")).toBeNull();
    act(() => {
      fireEvent.click(combinerBtn2!);
    });
    expect(onUpdate2).toHaveBeenCalledWith([filters2[0], { ...filters2[1], combiner: "OR" }]);
    unmount2();
  });

  it("covers VisualQueryBuilder save query in raw mode, handleAddJoinToTable, and unsynced badge unstyled", () => {
    const onSave = vi.fn();
    const { container, unmount } = render(
      <VisualQueryBuilder
        initialTable="users"
        schema={{
          tables: {
            users: { name: "users", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }] },
            orders: { name: "orders", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }, { name: "user_id", data_type: "int", is_nullable: false, is_primary: false }] },
          },
        }}
        onSaveQuery={onSave}
        unstyled={true}
      />,
    );
    // Click 🔗 on TableCard to join orders
    const addJoinBtn = container.querySelector('[data-qb="table-card-btn-join"]');
    expect(addJoinBtn).not.toBeNull();
    act(() => {
      fireEvent.click(addJoinBtn!);
    });
    // Click 🔗 again when all tables are joined (candidate undefined)
    act(() => {
      fireEvent.click(addJoinBtn!);
    });

    // Switch to Raw SQL
    const rawSqlTab = screen.getByText("📝 Raw SQL");
    act(() => {
      fireEvent.click(rawSqlTab);
    });
    const sqlEditor = screen.getByLabelText("Raw SQL code");
    act(() => {
      fireEvent.change(sqlEditor, { target: { value: "INVALID SQL" } });
    });
    const badge = container.querySelector('[data-qb="sql-sync-badge"]');
    expect(badge).not.toBeNull();
    expect(badge?.getAttribute("style")).toBeNull();

    // Save Template
    const saveBtn = screen.getByText("💾 Save Template");
    act(() => {
      fireEvent.click(saveBtn);
    });
    // Modal input for title
    const titleInput = screen.getByPlaceholderText("e.g., Active Users Directory");
    act(() => {
      fireEvent.change(titleInput, { target: { value: "My Template" } });
    });
    const confirmSaveBtn = container.querySelector('button[type="submit"]');
    expect(confirmSaveBtn).not.toBeNull();
    act(() => {
      fireEvent.click(confirmSaveBtn!);
    });
    expect(onSave).toHaveBeenCalled();
    unmount();
  });

  it("covers useQueryBuilder autoJoinTable edge cases", () => {
    // 1. autoJoinTable("")
    const { result } = renderHook(() => useQueryBuilder());
    act(() => {
      result.current.actions.autoJoinTable("");
    });
    expect(result.current.state.joins).toHaveLength(0);

    // 2. autoJoinTable when primaryTable is empty and activeTableNames is empty
    act(() => {
      result.current.actions.autoJoinTable("orders");
    });
    expect(result.current.state.joins).toHaveLength(1);

    // 3. autoJoinTable when activeTableNames is empty but primaryTable is set
    const { result: result2 } = renderHook(() =>
      useQueryBuilder({
        initialTable: "users",
        schema: {
          tables: {
            users: { name: "users", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }] },
            orders: { name: "orders", columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }] },
          },
        },
      }),
    );
    // Remove users from activeTableNames and set primaryTable to "users"
    act(() => {
      result2.current.actions.removeTable("users");
      result2.current.actions.setPrimaryTable("users");
    });
    act(() => {
      result2.current.actions.autoJoinTable("orders");
    });
    expect(result2.current.state.joins).toHaveLength(1);
  });

  it("covers useQueryState autoJoinTable when activeTables is empty", () => {
    const { result } = renderHook(() =>
      useQueryState({
        table: "" as any,
        columns: [],
      }),
    );
    act(() => {
      result.current.actions.autoJoinTable("orders" as any);
    });
    expect(result.current.state.joins).toHaveLength(1);

    // When activeTables is empty but primaryTable is set
    const { result: result2 } = renderHook(() =>
      useQueryState({
        primaryTable: "users" as any,
        activeTables: [] as any,
      }),
    );
    act(() => {
      result2.current.actions.autoJoinTable("orders" as any);
    });
    expect(result2.current.state.joins).toHaveLength(1);
  });

  it("covers useQueryExecution performance fallback when performance is undefined", async () => {
    const origPerf = globalThis.performance;
    try {
      // @ts-ignore
      delete globalThis.performance;
      const { result } = renderHook(() =>
        useQueryExecution({
          onExecuteQuery: async () => ({
            columns: ["id"],
            rows: [[1]],
            total_rows: 1,
            latency_ms: 10,
          }),
        }),
      );
      await act(async () => {
        await result.current.executeQuery("SELECT 1");
      });
      expect(result.current.results).toBeDefined();
    } finally {
      globalThis.performance = origPerf;
    }
  });

  it("covers compiler numeric suffix loops for alias collisions", () => {
    // 1. Column aliases: 4 columns with same alias on same table
    const stateWithColCollisions: any = {
      primaryTable: "users",
      activeTables: ["users"],
      selectedColumns: {
        "users.c1": { table: "users", name: "c1", alias: "col" },
        "users.c2": { table: "users", name: "c2", alias: "col" },
        "users.c3": { table: "users", name: "c3", alias: "col" },
        "users.c4": { table: "users", name: "c4", alias: "col" },
      },
      orderedProjectionKeys: ["users.c1", "users.c2", "users.c3", "users.c4"],
      joins: [],
      filters: [],
      sorts: [],
      isDistinct: false,
      limit: 10,
      offset: 0,
    };
    const compiled1 = compileVisualState(
      stateWithColCollisions.primaryTable,
      stateWithColCollisions.selectedColumns,
      stateWithColCollisions.orderedProjectionKeys,
      [],
      [],
      [],
    );
    expect(compiled1.sql).toContain('"col"');
    expect(compiled1.sql).toContain('"col_users"');
    expect(compiled1.sql).toContain('"col_2"');
    expect(compiled1.sql).toContain('"col_3"');

    // 2. Aggregate aliases: 4 aggregates with same alias on same table
    const stateWithAggCollisions: any = {
      primaryTable: "users",
      activeTables: ["users"],
      selectedColumns: {
        "users.a1": { table: "users", name: "a1", aggregate: "COUNT", alias: "cnt" },
        "users.a2": { table: "users", name: "a2", aggregate: "COUNT", alias: "cnt" },
        "users.a3": { table: "users", name: "a3", aggregate: "COUNT", alias: "cnt" },
        "users.a4": { table: "users", name: "a4", aggregate: "COUNT", alias: "cnt" },
      },
      orderedProjectionKeys: ["users.a1", "users.a2", "users.a3", "users.a4"],
      joins: [],
      filters: [],
      sorts: [],
      isDistinct: false,
      limit: 10,
      offset: 0,
    };
    const compiled2 = compileVisualState(
      stateWithAggCollisions.primaryTable,
      stateWithAggCollisions.selectedColumns,
      stateWithAggCollisions.orderedProjectionKeys,
      [],
      [],
      [],
    );
    expect(compiled2.sql).toContain('"cnt"');
    expect(compiled2.sql).toContain('"cnt_users"');
    expect(compiled2.sql).toContain('"cnt_2"');
    expect(compiled2.sql).toContain('"cnt_3"');
  });

  it("covers sqlParser expression fallbacks and join ON without table prefixes", () => {
    // Fallback expression in SELECT
    const spec1 = parseSqlToSpec("SELECT (price * 1.1) FROM products;");
    expect(spec1).not.toBeNull();
    expect(spec1?.columns[0]).toMatchObject({ column: "(price * 1.1)", raw_expression: "(price * 1.1)" });

    // Join ON without table prefix on left or right
    const spec2 = parseSqlToSpec("SELECT * FROM users JOIN orders ON user_id = id;");
    expect(spec2).not.toBeNull();
    expect(spec2?.joins[0]).toMatchObject({
      left_col: "user_id",
      right_col: "id",
    });

    // Invalid non-clause SELECT like SELECT+1
    const invalidNonClause = parseSqlToSpec("SELECT+1");
    expect(invalidNonClause).toBeNull();

    // SELECT with explicit column and *
    const specWithStar = parseSqlToSpec("SELECT users.id, * FROM users;");
    expect(specWithStar?.columns).toContain("*");

    // WHERE with table prefix
    const specWithPrefixedWhere = parseSqlToSpec("SELECT * FROM users WHERE users.age > 21;");
    expect(specWithPrefixedWhere?.filters?.[0]).toMatchObject({
      tablePrefix: "users",
      column: "age",
      op: ">",
      value: 21,
    });
  });

  it("covers compiler filter parens and falsy filterJoin fallbacks", () => {
    // Empty primary table with falsy filterJoin
    const compiledEmpty = compileVisualState("" as any, {}, [], [], [], [], false, 10, null, "postgres", "" as any);
    expect(compiledEmpty.spec.filter_join).toBe("AND");

    // Filter with parenOpen, parenClose, and falsy combiner
    const compiledParens = compileVisualState(
      "users",
      {},
      [],
      [],
      [
        {
          id: "f1",
          tablePrefix: "users",
          column: "id",
          operator: "=",
          value: "1",
          parenOpen: "(",
          parenClose: ")",
          combiner: "" as any,
        },
      ],
      [],
      false,
      50,
      null,
      "postgres",
      "" as any,
    );
    expect(compiledParens.sql).toContain('("users"."id" = 1)');
  });

  it("covers SchemaErdModal column search and undefined table columns", () => {
    const schema = {
      tables: {
        tblA: { name: "tblA", columns: [{ name: "special_col", data_type: "text" }] },
        tblB: { name: "tblB", columns: undefined as any },
      },
    };
    const { unmount } = render(
      <SchemaErdModal isOpen={true} onClose={() => {}} schema={schema as any} />,
    );
    // Search for column name to trigger line 97
    const searchInput = screen.getByPlaceholderText("Search tables or columns...");
    act(() => {
      fireEvent.change(searchInput, { target: { value: "special_col" } });
    });
    expect(screen.getByText("tblA")).toBeDefined();
    unmount();

    // 2-hop bridge discovery test (line 321: Path (2 hops))
    const schemaWith2Hops = {
      tables: {
        users: { name: "users", columns: [{ name: "id", data_type: "int" }] },
        orders: { name: "orders", columns: [{ name: "id", data_type: "int" }, { name: "user_id", data_type: "int" }] },
        items: { name: "items", columns: [{ name: "id", data_type: "int" }, { name: "order_id", data_type: "int" }] },
      },
      foreign_keys: [
        { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
        { table: "items", column: "order_id", foreign_table: "orders", foreign_column: "id" },
      ],
    };
    const { container: container2, unmount: unmount2 } = render(
      <SchemaErdModal isOpen={true} onClose={() => {}} schema={schemaWith2Hops as any} />,
    );
    const srcSelect = screen.getByLabelText("Bridge source table");
    const tgtSelect = screen.getByLabelText("Bridge target table");
    const findBtn = screen.getByText("Discover Bridge");
    act(() => {
      fireEvent.change(srcSelect, { target: { value: "users" } });
      fireEvent.change(tgtSelect, { target: { value: "items" } });
      fireEvent.click(findBtn);
    });
    expect(container2.textContent).toContain("Path (2 hops)");
    unmount2();
  });
});
