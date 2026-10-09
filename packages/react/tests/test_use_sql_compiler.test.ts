import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSqlCompiler, type QuerySpec, type SqlDialect } from "../src";

describe("useSqlCompiler Headless Reactive Compiler", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  it("handles null or undefined input gracefully", () => {
    const { result } = renderHook(() => useSqlCompiler(null));

    expect(result.current.sql).toBe("");
    expect(result.current.countSql).toBe("");
    expect(result.current.params).toEqual([]);
    expect(result.current.isValid).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.isCompiling).toBe(false);
    expect(result.current.ast).toBeNull();
  });

  it("compiles QuerySpec synchronously and generates countSql", () => {
    const spec: QuerySpec = {
      table: "users",
      columns: ["users.id", "users.email"],
      joins: [],
      filters: [{ column: "users.id", op: ">", value: 10 }],
      filter_join: "AND",
      order_by: [{ column: "users.id", direction: "ASC" }],
      distinct: false,
      limit: 25,
    };

    const { result } = renderHook(() => useSqlCompiler(spec));

    expect(result.current.sql).toContain('SELECT "users"."id", "users"."email"');
    expect(result.current.sql).toContain('FROM "users"');
    expect(result.current.sql).toContain('WHERE "users"."id" > 10');
    expect(result.current.sql).toContain('ORDER BY "users"."id" ASC');
    expect(result.current.sql).toContain("LIMIT 25");
    expect(result.current.countSql).toContain("SELECT COUNT(*) FROM (");
    expect(result.current.countSql).toContain(") AS count_wrapper;");
    expect(result.current.isValid).toBe(true);
    expect(result.current.safety.valid).toBe(true);
    expect(result.current.params).toEqual([10]);
    expect(result.current.error).toBeNull();
    expect(result.current.compileTimeMs).toBeGreaterThanOrEqual(0);
  });

  it("supports dynamic dialect switching", () => {
    const spec: QuerySpec = {
      table: "users",
      columns: ["users.name"],
      joins: [],
      filters: [],
      filter_join: "AND",
      order_by: [],
      distinct: false,
      limit: 10,
    };

    const { result, rerender } = renderHook(
      ({ dialect }) => useSqlCompiler(spec, { dialect }),
      { initialProps: { dialect: "postgres" as SqlDialect } },
    );

    expect(result.current.sql).toContain('"users"."name"');

    // Switch to MySQL backticks
    rerender({ dialect: "mysql" });
    expect(result.current.sql).toContain("`users`.`name`");

    // Switch to MSSQL square brackets
    rerender({ dialect: "mssql" });
    expect(result.current.sql).toContain("[users].[name]");
  });

  it("supports debounced compilation with debounceMs", () => {
    vi.useFakeTimers();

    const spec1: QuerySpec = {
      table: "orders",
      columns: ["orders.id"],
      joins: [],
      filters: [],
      filter_join: "AND",
      order_by: [],
      distinct: false,
      limit: 10,
    };

    const spec2: QuerySpec = {
      ...spec1,
      limit: 50,
    };

    const { result, rerender } = renderHook(
      ({ spec }) => useSqlCompiler(spec, { debounceMs: 150 }),
      { initialProps: { spec: spec1 } },
    );

    expect(result.current.sql).toContain("LIMIT 10");

    // Trigger update
    rerender({ spec: spec2 });

    // Immediately after update, isCompiling is true and sql is not yet updated
    expect(result.current.isCompiling).toBe(true);

    // Fast-forward partially
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(result.current.isCompiling).toBe(true);

    // Fast-forward remaining
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(result.current.isCompiling).toBe(false);
    expect(result.current.sql).toContain("LIMIT 50");
  });

  it("handles compiler errors and sets error property", () => {
    // Pass object that triggers compiler edge-case or throws
    const throwingInput = {
      primaryTable: { invalid: "object" },
      selectedColumns: null,
    };

    const { result } = renderHook(() => useSqlCompiler(throwingInput));

    expect(result.current.isValid).toBe(false);
    expect(result.current.sql).toBe("");
  });

  it("compiles directly from visual QueryState-like object", () => {
    const visualState = {
      primaryTable: "users",
      selectedColumns: {
        "users.email": { table: "users", name: "email" },
      },
      orderedProjectionKeys: ["users.email"],
      joins: [
        {
          id: "j1",
          type: "INNER JOIN",
          left_table: "users",
          table: "orders",
          left_col: "id",
          right_col: "user_id",
        },
      ],
      filters: [
        {
          id: "f1",
          column: "email",
          tablePrefix: "users",
          operator: "LIKE",
          value: "%@corp.com",
        },
      ],
      sorts: [
        {
          id: "s1",
          column: "email",
          tablePrefix: "users",
          direction: "DESC" as const,
        },
      ],
      isDistinct: true,
      limit: 15,
    };

    const { result } = renderHook(() => useSqlCompiler(visualState));

    expect(result.current.isValid).toBe(true);
    expect(result.current.sql).toContain('SELECT DISTINCT "users"."email"');
    expect(result.current.sql).toContain('INNER JOIN "orders"');
    expect(result.current.sql).toContain('WHERE "users"."email" LIKE \'%@corp.com\'');
    expect(result.current.sql).toContain('ORDER BY "users"."email" DESC');
    expect(result.current.sql).toContain("LIMIT 15");
  });

  it("handles runtime compilation exceptions gracefully in catch block", () => {
    // Malformed join item causes TypeError inside spec parser
    const malformedSpec = {
      table: "users",
      joins: [null],
    };

    const { result } = renderHook(() => useSqlCompiler(malformedSpec));

    expect(result.current.isValid).toBe(false);
    expect(result.current.sql).toBe("");
    expect(result.current.error).not.toBeNull();
    expect(result.current.error).toContain("Cannot read properties of null");
  });
});
