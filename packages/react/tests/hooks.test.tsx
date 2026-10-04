import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  useQueryBuilder,
  useQueryExecution,
  useSchemaIntrospection,
} from "../src/index";
import type { SchemaSnapshot, QueryResultData } from "../src/types";

const TEST_SCHEMA: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "name", data_type: "VARCHAR", is_nullable: false, is_primary: false },
        { name: "email", data_type: "VARCHAR", is_nullable: false, is_primary: false },
      ],
      has_user_id: false,
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "INTEGER", is_nullable: false, is_primary: false },
        { name: "total", data_type: "DECIMAL", is_nullable: false, is_primary: false },
      ],
      has_user_id: true,
    },
  },
  foreign_keys: [
    { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
  ],
};

describe("useQueryBuilder Hook", () => {
  it("initializes with default options and handles empty schema", () => {
    const { result } = renderHook(() => useQueryBuilder());

    expect(result.current.state.primaryTable).toBe("");
    expect(result.current.state.activeTableNames).toEqual([]);
    expect(result.current.state.limit).toBe(50);
    expect(result.current.state.isDistinct).toBe(false);
    expect(result.current.state.dialect).toBe("postgres");
    expect(result.current.state.isRawMode).toBe(false);
    expect(result.current.state.isDirty).toBe(false);

    // Schema with empty tables object
    const { result: emptyTablesResult } = renderHook(() =>
      useQueryBuilder({ schema: { tables: {} } }),
    );
    expect(emptyTablesResult.current.state.primaryTable).toBe("");
  });

  it("initializes with custom options, initialSql, and initialSpec", () => {
    const { result } = renderHook(() =>
      useQueryBuilder({
        schema: TEST_SCHEMA,
        initialTable: "users",
        dialect: "snowflake",
        initialLimit: 100,
        initialDistinct: true,
        initialActiveTables: ["users", "orders"],
      }),
    );

    expect(result.current.state.primaryTable).toBe("users");
    expect(result.current.state.activeTableNames).toEqual(["users", "orders"]);
    expect(result.current.state.limit).toBe(100);
    expect(result.current.state.isDistinct).toBe(true);
    expect(result.current.state.dialect).toBe("snowflake");
    expect(result.current.state.activeTables).toHaveLength(2);
    expect(result.current.safety.valid).toBe(true);

    // Test initialization from initialSpec when initialLimit and initialTable are omitted
    const { result: specResult } = renderHook(() =>
      useQueryBuilder({
        schema: TEST_SCHEMA,
        initialSpec: {
          primaryTable: "orders",
          activeTables: ["orders"],
          selectedColumns: { "orders.total": { table: "orders", name: "total" } },
          orderedProjectionKeys: ["orders.total"],
          joins: [],
          filters: [],
          sorts: [],
          limit: 35,
          distinct: true,
        },
      }),
    );
    expect(specResult.current.state.primaryTable).toBe("orders");
    expect(specResult.current.state.limit).toBe(35);
    expect(specResult.current.state.isDistinct).toBe(true);
    expect(specResult.current.state.orderedProjectionKeys).toEqual(["orders.total"]);

    // Test initialization with initialSql
    const { result: rawResult } = renderHook(() =>
      useQueryBuilder({
        initialSql: "SELECT 42;",
      }),
    );
    expect(rawResult.current.state.isRawMode).toBe(true);
    expect(rawResult.current.state.rawSql).toBe("SELECT 42;");
  });

  it("manages tables correctly: addTable, removeTable, setPrimaryTable", () => {
    const { result } = renderHook(() =>
      useQueryBuilder({
        schema: TEST_SCHEMA,
      }),
    );

    // Initial table inferred from schema
    expect(result.current.state.primaryTable).toBe("users");

    // Add table
    act(() => {
      result.current.actions.addTable("orders");
    });
    expect(result.current.state.activeTableNames).toContain("orders");

    // Add duplicate table is a no-op
    act(() => {
      result.current.actions.addTable("orders");
    });
    expect(result.current.state.activeTableNames).toHaveLength(2);

    // Add table when primary table is empty sets primary table
    act(() => {
      result.current.actions.setPrimaryTable("");
    });
    expect(result.current.state.primaryTable).toBe("");
    act(() => {
      result.current.actions.addTable("users");
    });
    expect(result.current.state.primaryTable).toBe("users");

    // Select column on orders, then remove orders to test column cleanup in removeTable
    act(() => {
      result.current.actions.toggleColumn("orders", "total");
      result.current.actions.addJoin({
        id: "j_ord",
        table: "orders",
        left_table: "users",
        left_col: "id",
        right_col: "user_id",
        type: "LEFT JOIN",
      });
    });
    expect(result.current.state.selectedColumns["orders.total"]).toBeDefined();
    expect(result.current.state.joins).toHaveLength(1);

    // Set primary table directly to orders
    act(() => {
      result.current.actions.setPrimaryTable("orders");
    });
    expect(result.current.state.primaryTable).toBe("orders");

    // Remove primary table updates primary to remaining and prunes columns and joins
    act(() => {
      result.current.actions.removeTable("orders");
    });
    expect(result.current.state.activeTableNames).toEqual(["users"]);
    expect(result.current.state.primaryTable).toBe("users");
    expect(result.current.state.selectedColumns["orders.total"]).toBeUndefined();
    expect(result.current.state.joins).toHaveLength(0);

    // Add join where users is left_table, then remove users to test left_table join cleanup
    act(() => {
      result.current.actions.addTable("orders");
      result.current.actions.addJoin({
        id: "j_left",
        table: "orders",
        left_table: "users",
        left_col: "id",
        right_col: "user_id",
        type: "LEFT JOIN",
      });
    });
    expect(result.current.state.joins).toHaveLength(1);

    act(() => {
      result.current.actions.removeTable("users");
    });
    expect(result.current.state.joins).toHaveLength(0);

    // Remove last table leaves primaryTable empty
    act(() => {
      result.current.actions.removeTable("orders");
    });
    expect(result.current.state.activeTableNames).toEqual([]);
    expect(result.current.state.primaryTable).toBe("");
  });

  it("manages column selection and projections: toggleColumn, updateColumnSelect, removeColumnProjection", () => {
    const { result } = renderHook(() =>
      useQueryBuilder({
        schema: TEST_SCHEMA,
        initialTable: "users",
      }),
    );

    // Toggle column on
    act(() => {
      result.current.actions.toggleColumn("users", "name");
    });
    expect(result.current.state.selectedColumns["users.name"]).toEqual({
      table: "users",
      name: "name",
    });
    expect(result.current.state.orderedProjectionKeys).toContain("users.name");

    // Update column select alias and aggregate
    act(() => {
      result.current.actions.updateColumnSelect("users.name", {
        alias: "user_name",
        aggregate: "COUNT",
      });
    });
    expect(result.current.state.selectedColumns["users.name"].alias).toBe("user_name");
    expect(result.current.state.selectedColumns["users.name"].aggregate).toBe("COUNT");

    // Update non-existent column is safe
    act(() => {
      result.current.actions.updateColumnSelect("users.nonexistent", { alias: "test" });
    });

    // Remove column projection
    act(() => {
      result.current.actions.removeColumnProjection("users.name");
    });
    expect(result.current.state.selectedColumns["users.name"]).toBeUndefined();
    expect(result.current.state.orderedProjectionKeys).not.toContain("users.name");

    // Toggle column off
    act(() => {
      result.current.actions.toggleColumn("users", "email");
    });
    expect(result.current.state.selectedColumns["users.email"]).toBeDefined();
    act(() => {
      result.current.actions.toggleColumn("users", "email");
    });
    expect(result.current.state.selectedColumns["users.email"]).toBeUndefined();
  });

  it("manages joins: setJoins, addJoin, updateJoin, removeJoin", () => {
    const { result } = renderHook(() => useQueryBuilder({ schema: TEST_SCHEMA }));

    const join1 = {
      id: "j1",
      type: "INNER JOIN" as const,
      left_table: "users",
      table: "orders",
      left_col: "id",
      right_col: "user_id",
    };
    const join2 = {
      id: "j2",
      type: "LEFT JOIN" as const,
      left_table: "users",
      table: "orders",
      left_col: "id",
      right_col: "user_id",
    };

    act(() => {
      result.current.actions.addJoin(join1);
      result.current.actions.addJoin(join2);
    });
    expect(result.current.state.joins).toHaveLength(2);

    act(() => {
      result.current.actions.updateJoin("j1", { type: "RIGHT JOIN" });
    });
    expect(result.current.state.joins[0].type).toBe("RIGHT JOIN");
    expect(result.current.state.joins[1].type).toBe("LEFT JOIN");

    act(() => {
      result.current.actions.setJoins([
        { ...join1, id: "j3" },
      ]);
    });
    expect(result.current.state.joins[0].id).toBe("j3");

    act(() => {
      result.current.actions.removeJoin("j3");
    });
    expect(result.current.state.joins).toHaveLength(0);
  });

  it("manages filters: setFilters, addFilter, updateFilter, removeFilter", () => {
    const { result } = renderHook(() => useQueryBuilder());

    const filter1 = {
      id: "f1",
      column: "status",
      operator: "=" as const,
      value: "ACTIVE",
    };
    const filter2 = {
      id: "f2",
      column: "role",
      operator: "=" as const,
      value: "ADMIN",
    };

    act(() => {
      result.current.actions.addFilter(filter1);
      result.current.actions.addFilter(filter2);
    });
    expect(result.current.state.filters).toHaveLength(2);

    act(() => {
      result.current.actions.updateFilter("f1", { value: "INACTIVE" });
    });
    expect(result.current.state.filters[0].value).toBe("INACTIVE");
    expect(result.current.state.filters[1].value).toBe("ADMIN");

    act(() => {
      result.current.actions.setFilters([
        { ...filter1, id: "f3" },
      ]);
    });
    expect(result.current.state.filters[0].id).toBe("f3");

    act(() => {
      result.current.actions.removeFilter("f3");
    });
    expect(result.current.state.filters).toHaveLength(0);
  });

  it("manages sorts: setSorts, addSort, updateSort, removeSort", () => {
    const { result } = renderHook(() => useQueryBuilder());

    const sort1 = {
      id: "s1",
      column: "created_at",
      direction: "DESC" as const,
    };
    const sort2 = {
      id: "s2",
      column: "id",
      direction: "ASC" as const,
    };

    act(() => {
      result.current.actions.addSort(sort1);
      result.current.actions.addSort(sort2);
    });
    expect(result.current.state.sorts).toHaveLength(2);

    act(() => {
      result.current.actions.updateSort("s1", { direction: "ASC" });
    });
    expect(result.current.state.sorts[0].direction).toBe("ASC");
    expect(result.current.state.sorts[1].direction).toBe("ASC");

    act(() => {
      result.current.actions.setSorts([
        { ...sort1, id: "s3" },
      ]);
    });
    expect(result.current.state.sorts[0].id).toBe("s3");

    act(() => {
      result.current.actions.removeSort("s3");
    });
    expect(result.current.state.sorts).toHaveLength(0);
  });

  it("manages limits, distinct, dialect, and raw SQL mode", () => {
    const { result } = renderHook(() => useQueryBuilder());

    act(() => {
      result.current.actions.setLimit(25);
      result.current.actions.setIsDistinct(true);
      result.current.actions.setDialect("mysql");
    });
    expect(result.current.state.limit).toBe(25);
    expect(result.current.state.isDistinct).toBe(true);
    expect(result.current.state.dialect).toBe("mysql");

    // Raw mode
    act(() => {
      result.current.actions.setRawSql("SELECT 1;");
      result.current.actions.setIsRawMode(true);
    });
    expect(result.current.state.isRawMode).toBe(true);
    expect(result.current.currentSql).toBe("SELECT 1;");
    expect(result.current.safety.valid).toBe(true);

    // Unsafe SQL
    act(() => {
      result.current.actions.setRawSql("DROP TABLE users;");
    });
    expect(result.current.safety.valid).toBe(false);
  });

  it("handles isDirty tracking, markClean, and reset", () => {
    const { result } = renderHook(() =>
      useQueryBuilder({
        initialTable: "users",
        initialLimit: 50,
      }),
    );

    expect(result.current.state.isDirty).toBe(false);

    // Modify limit
    act(() => {
      result.current.actions.setLimit(100);
    });
    expect(result.current.state.isDirty).toBe(true);

    // Mark clean
    act(() => {
      result.current.actions.markClean();
    });
    expect(result.current.state.isDirty).toBe(false);

    // Modify distinct
    act(() => {
      result.current.actions.setIsDistinct(true);
    });
    expect(result.current.state.isDirty).toBe(true);

    // Reset restores initial state and cleans isDirty
    act(() => {
      result.current.actions.reset();
    });
    expect(result.current.state.limit).toBe(50);
    expect(result.current.state.isDistinct).toBe(false);
    expect(result.current.state.isDirty).toBe(false);
  });

  it("supports loadSpec and loadTemplate", () => {
    const { result } = renderHook(() => useQueryBuilder({ schema: TEST_SCHEMA }));

    // Load visual spec with table and distinct
    act(() => {
      result.current.actions.loadSpec({
        table: "orders",
        activeTables: ["orders", "users"],
        selectedColumns: { "orders.total": { table: "orders", name: "total" } },
        orderedProjectionKeys: ["orders.total"],
        joins: [],
        filters: [],
        sorts: [],
        distinct: true,
        limit: 15,
      });
    });

    expect(result.current.state.primaryTable).toBe("orders");
    expect(result.current.state.activeTableNames).toEqual(["orders", "users"]);
    expect(result.current.state.limit).toBe(15);
    expect(result.current.state.isDistinct).toBe(true);

    // Call loadSpec without activeTables when table is NOT in activeTableNames
    act(() => {
      result.current.actions.setPrimaryTable("");
      result.current.actions.loadSpec({
        table: "new_table",
      });
    });
    expect(result.current.state.primaryTable).toBe("new_table");
    expect(result.current.state.activeTableNames).toContain("new_table");

    // Call loadSpec without activeTables when table IS ALREADY in activeTableNames
    act(() => {
      result.current.actions.loadSpec({
        table: "new_table",
      });
    });
    expect(result.current.state.primaryTable).toBe("new_table");

    // Load spec with primaryTable and isDistinct
    act(() => {
      result.current.actions.loadSpec({
        primaryTable: "users",
        isDistinct: false,
      });
    });
    expect(result.current.state.primaryTable).toBe("users");

    // Load standard QuerySpec (columns array, joins array, filters array, order_by array)
    act(() => {
      result.current.actions.loadSpec({
        table: "orders",
        columns: [
          "*",
          "orders.id",
          "total",
          { column: "users.email", agg: "count", alias: "cnt" },
          { column: "notes" },
        ],
        joins: [
          { table: "users", type: "LEFT", on: [{ left: "orders.user_id", right: "users.id" }] },
          { table: "products", type: "LEFT", on: [{ left: "product_id", right: "id" }] },
        ],
        filters: [
          { column: "total", op: "gt", value: "100" },
        ],
        order_by: [
          { column: "orders.total", direction: "DESC" },
          { column: "id", tablePrefix: "orders", direction: "ASC" },
        ],
        distinct: true,
        limit: 35,
      });
    });
    expect(result.current.state.primaryTable).toBe("orders");
    expect(result.current.state.orderedProjectionKeys).toContain("orders.id");
    expect(result.current.state.orderedProjectionKeys).toContain("orders.total");
    expect(result.current.state.selectedColumns["users.email"]?.aggregate).toBe("COUNT");
    expect(result.current.state.joins[0]?.type).toBe("LEFT JOIN");
    expect(result.current.state.joins[0]?.left_table).toBe("orders");
    expect(result.current.state.joins[0]?.left_col).toBe("user_id");
    expect(result.current.state.joins[0]?.right_col).toBe("id");
    expect(result.current.state.filters[0]?.operator).toBe("GT");

    // Load template with visual spec
    act(() => {
      result.current.actions.loadTemplate({
        id: "t1",
        title: "Test Template",
        createdAt: "2026-10-03",
        sql: "SELECT * FROM users",
        spec: {
          primaryTable: "users",
          limit: 30,
          isDistinct: false,
        },
      });
    });
    expect(result.current.state.primaryTable).toBe("users");
    expect(result.current.state.limit).toBe(30);
    expect(result.current.state.isRawMode).toBe(false);

    // Load template with raw SQL only
    act(() => {
      result.current.actions.loadTemplate({
        id: "t2",
        title: "Raw Template",
        createdAt: "2026-10-03",
        sql: "SELECT id, email FROM users WHERE id = 1;",
      });
    });
    expect(result.current.state.isRawMode).toBe(true);
    expect(result.current.state.rawSql).toContain("WHERE id = 1");

    // Load template with empty object
    act(() => {
      result.current.actions.loadTemplate({
        id: "t3",
        title: "Empty",
        createdAt: "2026-10-03",
        sql: "",
      });
    });
  });
});

describe("useQueryExecution Hook", () => {
  it("initializes with default state", () => {
    const { result } = renderHook(() => useQueryExecution());

    expect(result.current.results).toBeNull();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.latencyMs).toBeNull();
  });

  it("executes query via custom onExecuteQuery successfully", async () => {
    const mockData: QueryResultData = {
      columns: ["id", "val"],
      rows: [{ id: 1, val: "A" }],
      count: 1,
    };

    const onSuccess = vi.fn();
    const { result } = renderHook(() =>
      useQueryExecution({
        onExecuteQuery: async () => mockData,
        onSuccess,
      }),
    );

    let returned: QueryResultData | null = null;
    await act(async () => {
      returned = await result.current.executeQuery("SELECT 1;");
    });

    expect(returned).not.toBeNull();
    expect(result.current.results?.count).toBe(1);
    expect(result.current.latencyMs).toBeTypeOf("number");
    expect(result.current.isLoading).toBe(false);
    expect(onSuccess).toHaveBeenCalledWith(result.current.results);

    // onExecuteQuery returning void/null
    const { result: nullResult } = renderHook(() =>
      useQueryExecution({
        onExecuteQuery: async () => {},
      }),
    );
    await act(async () => {
      const res = await nullResult.current.executeQuery("SELECT 1;");
      expect(res).toBeNull();
    });
  });

  it("handles onExecuteQuery errors", async () => {
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useQueryExecution({
        onExecuteQuery: async () => {
          throw new Error("Query execution failed");
        },
        onError,
      }),
    );

    await act(async () => {
      const res = await result.current.executeQuery("SELECT 1;");
      expect(res).toBeNull();
    });

    expect(result.current.error).toBe("Query execution failed");
    expect(result.current.isLoading).toBe(false);
    expect(onError).toHaveBeenCalled();
  });

  it("handles non-Error throwables gracefully", async () => {
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useQueryExecution({
        onExecuteQuery: async () => {
          // eslint-disable-next-line no-throw-literal
          throw "String error";
        },
        onError,
      }),
    );

    await act(async () => {
      await result.current.executeQuery("SELECT 1;");
    });

    expect(result.current.error).toBe("String error");
    expect(onError).toHaveBeenCalled();
  });

  it("returns null when neither onExecuteQuery nor apiEndpoint is configured", async () => {
    const { result } = renderHook(() => useQueryExecution());
    let res: QueryResultData | null = null;
    await act(async () => {
      res = await result.current.executeQuery("SELECT 1;");
    });
    expect(res).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it("executes query via apiEndpoint with data wrapper and timeout", async () => {
    const mockData = {
      columns: ["col1"],
      rows: [{ col1: "test" }],
      count: 1,
    };

    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: mockData }),
    } as Response);

    const { result } = renderHook(() =>
      useQueryExecution({
        apiEndpoint: "/api/v1/execute",
        defaultTimeoutMs: 5000,
      }),
    );

    await act(async () => {
      await result.current.executeQuery("SELECT * FROM test");
    });

    expect(result.current.results?.count).toBe(1);
    expect(result.current.error).toBeNull();

    // Direct object without data wrapper
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockData,
    } as Response);

    await act(async () => {
      await result.current.executeQuery("SELECT * FROM test");
    });
    expect(result.current.results?.count).toBe(1);

    global.fetch = originalFetch;
  });

  it("handles apiEndpoint HTTP errors", async () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    } as Response);

    const { result } = renderHook(() =>
      useQueryExecution({
        apiEndpoint: "/api/v1/execute",
        defaultTimeoutMs: 5000,
      }),
    );

    await act(async () => {
      await result.current.executeQuery("SELECT 1");
    });

    expect(result.current.error).toBe("HTTP error 500");
    global.fetch = originalFetch;
  });

  it("handles AbortError in fetch gracefully", async () => {
    const originalFetch = global.fetch;
    const abortErr = new Error("The operation was aborted");
    abortErr.name = "AbortError";
    global.fetch = vi.fn().mockRejectedValue(abortErr);

    const { result } = renderHook(() =>
      useQueryExecution({
        apiEndpoint: "/api/v1/execute",
      }),
    );

    await act(async () => {
      const res = await result.current.executeQuery("SELECT 1");
      expect(res).toBeNull();
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();

    global.fetch = originalFetch;
  });

  it("supports cancellation, clearResults, and setResults", async () => {
    const { result } = renderHook(() =>
      useQueryExecution({
        onExecuteQuery: async () => {
          await new Promise((r) => setTimeout(r, 100));
          return { columns: [], rows: [], count: 0 };
        },
      }),
    );

    act(() => {
      result.current.executeQuery("SELECT 1;");
    });
    expect(result.current.isLoading).toBe(true);

    act(() => {
      result.current.cancelExecution();
    });
    expect(result.current.isLoading).toBe(false);

    // Direct setter
    act(() => {
      result.current.setResults({ columns: ["x"], rows: [], count: 0 });
    });
    expect(result.current.results?.columns).toEqual(["x"]);

    act(() => {
      result.current.clearResults();
    });
    expect(result.current.results).toBeNull();
  });

  it("triggers controller.abort when defaultTimeoutMs expires", async () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockImplementation((_url, options) => {
      return new Promise((_resolve, reject) => {
        if (options?.signal) {
          options.signal.addEventListener("abort", () => {
            const err = new Error("The operation was aborted");
            err.name = "AbortError";
            reject(err);
          });
        }
      });
    });

    vi.useFakeTimers();

    const { result } = renderHook(() =>
      useQueryExecution({
        defaultTimeoutMs: 100,
        apiEndpoint: "/api/slow",
      }),
    );

    let execPromise: Promise<unknown>;
    act(() => {
      execPromise = result.current.executeQuery("SELECT 1;");
    });

    expect(result.current.isLoading).toBe(true);

    // Fast-forward fake timer
    await act(async () => {
      vi.advanceTimersByTime(150);
      await execPromise;
    });

    expect(result.current.isLoading).toBe(false);

    vi.useRealTimers();
    global.fetch = originalFetch;
  });
});

describe("useSchemaIntrospection Hook", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("initializes with initialSchema without fetching", () => {
    const { result } = renderHook(() =>
      useSchemaIntrospection({
        initialSchema: TEST_SCHEMA,
      }),
    );

    expect(result.current.schema).toEqual(TEST_SCHEMA);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("supports fetchOnInit with apiEndpoint", async () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ schema: TEST_SCHEMA }),
    } as Response);

    const { result } = renderHook(() =>
      useSchemaIntrospection({
        apiEndpoint: "/api/v1/introspect",
        fetchOnInit: true,
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.schema).toEqual(TEST_SCHEMA);
    global.fetch = originalFetch;
  });

  it("fetches schema on refreshSchema call", async () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ schema: TEST_SCHEMA }),
    } as Response);

    const onSchemaLoaded = vi.fn();
    const { result } = renderHook(() =>
      useSchemaIntrospection({
        apiEndpoint: "/api/v1/introspect",
        onSchemaLoaded,
      }),
    );

    await act(async () => {
      const res = await result.current.refreshSchema();
      expect(res).toEqual(TEST_SCHEMA);
    });

    expect(result.current.schema).toEqual(TEST_SCHEMA);
    expect(onSchemaLoaded).toHaveBeenCalledWith(TEST_SCHEMA);

    global.fetch = originalFetch;
  });

  it("handles fetch errors in refreshSchema", async () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
    } as Response);

    const onError = vi.fn();
    const { result } = renderHook(() =>
      useSchemaIntrospection({
        apiEndpoint: "/api/v1/introspect",
        onError,
      }),
    );

    await act(async () => {
      const res = await result.current.refreshSchema();
      expect(res).toBeNull();
    });

    expect(result.current.error).toBe("HTTP error 404");
    expect(onError).toHaveBeenCalled();

    global.fetch = originalFetch;
  });

  it("returns current schema when refreshSchema is called without apiEndpoint", async () => {
    const { result } = renderHook(() =>
      useSchemaIntrospection({
        initialSchema: TEST_SCHEMA,
      }),
    );

    await act(async () => {
      const res = await result.current.refreshSchema();
      expect(res).toEqual(TEST_SCHEMA);
    });
  });

  it("supports localStorage caching, corrupt cache recovery, and clearing", async () => {
    const cacheKey = "test_schema_cache";
    window.localStorage.setItem(cacheKey, JSON.stringify(TEST_SCHEMA));

    // Mounts and reads cached schema
    const { result } = renderHook(() =>
      useSchemaIntrospection({
        cacheKey,
      }),
    );
    expect(result.current.schema).toEqual(TEST_SCHEMA);

    // Corrupt JSON in cache falls back safely
    window.localStorage.setItem("corrupt_key", "invalid-json{{");
    const { result: corruptResult } = renderHook(() =>
      useSchemaIntrospection({
        cacheKey: "corrupt_key",
        initialSchema: TEST_SCHEMA,
      }),
    );
    expect(corruptResult.current.schema).toEqual(TEST_SCHEMA);

    // Clear schema also clears localStorage
    act(() => {
      result.current.clearSchema();
    });
    expect(result.current.schema).toBeNull();
    expect(window.localStorage.getItem(cacheKey)).toBeNull();

    // Storage setItem exception safety
    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ schema: TEST_SCHEMA }),
    } as Response);
    const mockSetItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceeded");
    });

    const { result: writeErrResult } = renderHook(() =>
      useSchemaIntrospection({
        apiEndpoint: "/api/v1/introspect",
        cacheKey: "quota_fail",
      }),
    );
    await act(async () => {
      await writeErrResult.current.refreshSchema();
    });
    expect(writeErrResult.current.schema).toEqual(TEST_SCHEMA);

    // Storage removeItem exception safety
    const mockRemoveItem = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("RemoveError");
    });
    act(() => {
      writeErrResult.current.clearSchema();
    });
    expect(writeErrResult.current.schema).toBeNull();

    mockSetItem.mockRestore();
    mockRemoveItem.mockRestore();
    global.fetch = originalFetch;
  });

  it("handles non-wrapped schema responses and non-Error exceptions", async () => {
    const originalFetch = global.fetch;
    // Direct schema without .schema
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => TEST_SCHEMA,
    } as Response);

    const { result } = renderHook(() =>
      useSchemaIntrospection({
        apiEndpoint: "/api/direct",
      }),
    );

    await act(async () => {
      const s = await result.current.refreshSchema();
      expect(s).toEqual(TEST_SCHEMA);
    });

    // Non-Error rejection
    global.fetch = vi.fn().mockRejectedValue("string rejection");
    await act(async () => {
      const res = await result.current.refreshSchema();
      expect(res).toBeNull();
    });
    expect(result.current.error).toBe("string rejection");

    global.fetch = originalFetch;
  });
});
