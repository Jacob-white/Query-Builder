import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen, act, fireEvent, renderHook } from "@testing-library/react";
import {
  QueryPlayground,
  useQueryState,
  useSqlCompiler,
  stateToSpec,
  specToState,
  type QueryState,
} from "../src";

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
});
