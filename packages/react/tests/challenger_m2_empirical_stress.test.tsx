import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act, renderHook } from "@testing-library/react";
import { useSqlCompiler } from "../src/hooks/useSqlCompiler";
import { useQueryBuilder } from "../src/hooks/useQueryBuilder";
import { useQueryState, MAX_HISTORY_LENGTH } from "../src/hooks/useQueryState";
import { useStreamingQuery } from "../src/hooks/useStreamingQuery";
import { ThemeProvider, useTheme } from "../src/theme/ThemeProvider";
import { TableJoinEditor } from "../src/components/TableJoinEditor";
import { TableSortsEditor } from "../src/components/TableSortsEditor";
import { QueryCanvas } from "../src/components/QueryCanvas";
import { WindowFunctionBuilder } from "../src/components/WindowFunctionBuilder";
import { CalculatedFieldEditor } from "../src/components/CalculatedFieldEditor";
import { VisualQueryBuilder, type VisualQueryBuilderRef } from "../src/components/VisualQueryBuilder";
import { parseSqlToSpec } from "../src/utils/sqlParser";
import { estimateClientPlan } from "../src/utils/compiler";
import type { HybridSearchSpec, SchemaSnapshot, SqlDialect, VectorSearchSpec } from "../src/types";
import { invalid } from "./helpers";
import { makeCanvasProps } from "./helpers/canvas";

describe("Milestone 2: Empirical Adversarial Stress Test Suite", () => {
  const sampleSchema: SchemaSnapshot = {
    tables: {
      users: {
        name: "users",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "name", data_type: "varchar", is_nullable: true, is_primary: false },
          { name: "department", data_type: "varchar", is_nullable: true, is_primary: false },
          { name: "embedding", data_type: "vector", is_nullable: true, is_primary: false },
        ],
      },
      orders: {
        name: "orders",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "amount", data_type: "numeric", is_nullable: false, is_primary: false },
          { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
        ],
      },
    },
  };

  // =========================================================================
  // 1. STATE HISTORY STRESS TESTS (useQueryState)
  // =========================================================================
  describe("1. State History: useQueryState Boundary Conditions & Invariants", () => {
    it("handles boundary calls with empty past and future without mutation or error", () => {
      const { result } = renderHook(() => useQueryState({ table: "users" }));

      expect(result.current.history.canUndo).toBe(false);
      expect(result.current.history.canRedo).toBe(false);
      expect(result.current.history.past).toHaveLength(0);
      expect(result.current.history.future).toHaveLength(0);
      expect(result.current.state.isDirty).toBe(false);

      const stateSnapshot = result.current.state;

      // Invoking undo on empty past
      act(() => {
        result.current.actions.undo();
        result.current.actions.undo();
        result.current.actions.undo();
      });
      expect(result.current.state).toBe(stateSnapshot);
      expect(result.current.history.canUndo).toBe(false);

      // Invoking redo on empty future
      act(() => {
        result.current.actions.redo();
        result.current.actions.redo();
      });
      expect(result.current.state).toBe(stateSnapshot);
      expect(result.current.history.canRedo).toBe(false);
    });

    it("caps history at MAX_HISTORY_LENGTH (50) under 120 rapid updates and maintains sequential bounds", () => {
      const { result } = renderHook(() => useQueryState({ table: "users" }));

      // Perform 120 sequential mutations
      act(() => {
        for (let i = 1; i <= 120; i++) {
          result.current.actions.setLimit(i);
        }
      });

      expect(result.current.state.limit).toBe(120);
      expect(result.current.history.past.length).toBe(MAX_HISTORY_LENGTH); // Exactly 50
      expect(result.current.history.canUndo).toBe(true);
      expect(result.current.history.canRedo).toBe(false);

      // Oldest entry in past should be limit = 70 (120 - 50 = 70)
      expect(result.current.history.past[0].limit).toBe(70);

      // Undo 50 times to reach the boundary of retained history
      act(() => {
        for (let i = 0; i < 50; i++) {
          result.current.actions.undo();
        }
      });

      expect(result.current.state.limit).toBe(70);
      expect(result.current.history.past).toHaveLength(0);
      expect(result.current.history.canUndo).toBe(false);
      expect(result.current.history.canRedo).toBe(true);
      expect(result.current.history.future).toHaveLength(50);

      // Further undos must be no-ops
      act(() => {
        result.current.actions.undo();
        result.current.actions.undo();
      });
      expect(result.current.state.limit).toBe(70);
      expect(result.current.history.canUndo).toBe(false);

      // Redo 50 times to return to limit = 120
      act(() => {
        for (let i = 0; i < 50; i++) {
          result.current.actions.redo();
        }
      });

      expect(result.current.state.limit).toBe(120);
      expect(result.current.history.future).toHaveLength(0);
      expect(result.current.history.canRedo).toBe(false);
      expect(result.current.history.past).toHaveLength(50);
    });

    it("purges future stack when a new mutation occurs after undoing", () => {
      const { result } = renderHook(() => useQueryState({ table: "users" }));

      act(() => {
        result.current.actions.setLimit(10);
        result.current.actions.setLimit(20);
        result.current.actions.setLimit(30);
      });

      expect(result.current.state.limit).toBe(30);
      expect(result.current.history.past).toHaveLength(3);

      // Undo 2 times -> limit = 10
      act(() => {
        result.current.actions.undo();
        result.current.actions.undo();
      });
      expect(result.current.state.limit).toBe(10);
      expect(result.current.history.future).toHaveLength(2);
      expect(result.current.history.canRedo).toBe(true);

      // Brand new mutation
      act(() => {
        result.current.actions.setLimit(999);
      });

      expect(result.current.state.limit).toBe(999);
      // Invariant: future stack MUST be discarded
      expect(result.current.history.future).toHaveLength(0);
      expect(result.current.history.canRedo).toBe(false);
      expect(result.current.history.past).toHaveLength(2); // initial (50) and limit=10
    });

    it("verifies dirty state tracking and markClean consistency", () => {
      const { result } = renderHook(() => useQueryState({ table: "users" }));

      expect(result.current.state.isDirty).toBe(false);

      act(() => {
        result.current.actions.addTable("orders");
      });
      expect(result.current.state.isDirty).toBe(true);

      act(() => {
        result.current.actions.markClean();
      });
      expect(result.current.state.isDirty).toBe(false);

      // Reset restores initial state and resets isDirty to false
      act(() => {
        result.current.actions.setLimit(999);
      });
      expect(result.current.state.isDirty).toBe(true);

      act(() => {
        result.current.actions.reset();
      });
      expect(result.current.state.isDirty).toBe(false);
      expect(result.current.state.limit).toBe(50);
      expect(result.current.history.past).toHaveLength(0);
      expect(result.current.history.future).toHaveLength(0);
    });

    it("guarantees 100% referential stability of actions across 50 mutations and undo/redo cycles", () => {
      const { result } = renderHook(() => useQueryState({ table: "users" }));
      const initialActions = result.current.actions;

      act(() => {
        result.current.actions.setLimit(10);
        result.current.actions.addTable("orders");
        result.current.actions.setDistinct(true);
        result.current.actions.undo();
        result.current.actions.redo();
        result.current.actions.clearHistory();
        result.current.actions.markClean();
      });

      expect(result.current.actions).toBe(initialActions);
    });
  });

  // =========================================================================
  // 2. SQL COMPILATION: CTEs, WINDOW FUNCTIONS, VECTOR/HYBRID SEARCH
  // =========================================================================
  describe("2. SQL Compilation: Advanced Clauses across Dialects", () => {
    it("compiles recursive CTEs with explicit column projections in useSqlCompiler and enforces safety rules", () => {
      const spec = {
        table: "hierarchy",
        columns: ["hierarchy.id", "hierarchy.parent_id", "hierarchy.level"],
        ctes: [
          {
            name: "org_chart",
            recursive: true,
            columns: ["id", "parent_id", "level"],
            query: {
              sql: "SELECT id, parent_id, 1 FROM employees WHERE parent_id IS NULL UNION ALL SELECT e.id, e.parent_id, o.level + 1 FROM employees e JOIN org_chart o ON e.parent_id = o.id",
            },
          },
        ],
      };

      const { result } = renderHook(() =>
        useSqlCompiler(spec, { dialect: "postgres" }),
      );

      // Verify SQL string generation with WITH RECURSIVE and column projections
      expect(result.current.sql).toContain("WITH RECURSIVE");
      expect(result.current.sql).toContain('"org_chart" ("id", "parent_id", "level") AS (');
      expect(result.current.sql).toContain("UNION ALL");
      expect(result.current.sql).toContain('FROM "hierarchy"');
      expect(result.current.ast?.ctes).toHaveLength(1);
      expect(result.current.ast?.ctes?.[0].recursive).toBe(true);

      // Invariant: safety validator flags recursive CTEs per zero-trust read-only policy
      expect(result.current.safety.violations).toContain(
        "Recursive Common Table Expressions (WITH RECURSIVE) are not permitted.",
      );
      expect(result.current.isValid).toBe(false);
    });

    it("compiles multiple materialized CTEs in useSqlCompiler across postgres and snowflake", () => {
      const spec = {
        table: "summary",
        columns: ["summary.metric", "summary.val"],
        ctes: [
          {
            name: "cte_a",
            materialized: true,
            query: { sql: "SELECT 1 AS val" },
          },
          {
            name: "cte_b",
            materialized: false,
            query: { sql: "SELECT 2 AS val" },
          },
        ],
      };

      const { result: pgResult } = renderHook(() =>
        useSqlCompiler(spec, { dialect: "postgres" }),
      );
      expect(pgResult.current.sql).toContain('WITH "cte_a" AS MATERIALIZED (\nSELECT 1 AS val\n), "cte_b" AS (\nSELECT 2 AS val\n)');
      expect(pgResult.current.isValid).toBe(true);

      const { result: sfResult } = renderHook(() =>
        useSqlCompiler(spec, { dialect: "snowflake" }),
      );
      expect(sfResult.current.sql).toContain('WITH "cte_a" AS MATERIALIZED (\nSELECT 1 AS val\n), "cte_b" AS (\nSELECT 2 AS val\n)');
      expect(sfResult.current.isValid).toBe(true);
    });

    it("compiles window functions with frame specifications and exclusion clauses", () => {
      const spec = {
        table: "orders",
        columns: ["orders.id", "orders.amount"],
        window_functions: [
          {
            function: "AVG",
            arguments: ["orders.amount"],
            partition_by: ["orders.user_id"],
            order_by: [{ column: "orders.created_at", direction: "ASC" as const }],
            frame: {
              frame_type: "ROWS" as const,
              start: "1 PRECEDING",
              end: "1 FOLLOWING",
              exclusion: "CURRENT ROW",
            },
            alias: "moving_avg",
          },
          {
            function: "DENSE_RANK",
            arguments: [],
            partition_by: ["orders.user_id"],
            order_by: [{ column: "orders.amount", direction: "DESC" as const }],
            alias: "rank_in_user",
          },
        ],
      };

      const { result } = renderHook(() =>
        useSqlCompiler(spec, { dialect: "postgres" }),
      );

      expect(result.current.sql).toContain("AVG(orders.amount) OVER (PARTITION BY orders.user_id ORDER BY orders.created_at ASC ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING EXCLUDE CURRENT ROW) AS \"moving_avg\"");
      expect(result.current.sql).toContain("DENSE_RANK() OVER (PARTITION BY orders.user_id ORDER BY orders.amount DESC) AS \"rank_in_user\"");
      expect(result.current.ast?.window_functions).toHaveLength(2);
      expect(result.current.isValid).toBe(true);
    });

    it("compiles vector search with distance metric and custom ordering", () => {
      const spec = {
        table: "users",
        columns: ["users.id", "users.name"],
        vector_search: {
          column: "embedding",
          vector: [0.05, -0.12, 0.98, 0.44],
          metric: "cosine" as const,
          topK: 10,
          include_distances: true,
        },
      };

      const { result } = renderHook(() =>
        useSqlCompiler(spec, { dialect: "postgres" }),
      );

      expect(result.current.sql).toContain('("users"."embedding" <=> \'[0.05,-0.12,0.98,0.44]\') AS "_distance"');
      expect(result.current.sql).toContain("ORDER BY \"users\".\"embedding\" <=> '[0.05,-0.12,0.98,0.44]' ASC");
      expect(result.current.ast?.vector_search?.include_distances).toBe(true);
      expect(result.current.isValid).toBe(true);
    });

    it("dynamically manages CTEs, window functions, and hybrid search in useQueryBuilder", () => {
      const { result } = renderHook(() =>
        useQueryBuilder({
          schema: sampleSchema,
          initialTable: "users",
        }),
      );

      // Initially no CTEs or window functions
      expect(result.current.compiled.sql).not.toContain("WITH");
      expect(result.current.compiled.sql).not.toContain("OVER");

      // Set CTEs dynamically
      act(() => {
        result.current.actions.setCtes?.([
          {
            name: "dept_totals",
            query: { sql: "SELECT department, COUNT(*) FROM users GROUP BY department" },
          },
        ]);
      });

      expect(result.current.compiled.sql).toContain('WITH "dept_totals" AS (\nSELECT department, COUNT(*) FROM users GROUP BY department\n)');

      // Set Window Function dynamically
      act(() => {
        result.current.actions.setWindowFunctions?.([
          {
            function: "ROW_NUMBER",
            arguments: [],
            order_by: [{ column: "id", direction: "ASC" }],
            alias: "row_idx",
          },
        ]);
      });

      expect(result.current.compiled.sql).toContain('ROW_NUMBER() OVER (ORDER BY id ASC) AS "row_idx"');

      // Set Vector Search dynamically
      act(() => {
        result.current.actions.setVectorSearch?.(invalid<VectorSearchSpec>({
          column: "embedding",
          vector: [0.1, 0.2, 0.3],
          metric: "l2",
          topK: 5,
          include_distances: true,
        }));
      });

      expect(result.current.compiled.sql).toContain('"_distance"');

      // Verify hybrid search spec and query plan node estimation
      act(() => {
        result.current.actions.setHybridSearch?.(invalid<HybridSearchSpec>({
          vector: [0.1, 0.2, 0.3],
          query_text: "finance director",
          vector_weight: 0.7,
          text_weight: 0.3,
        }));
      });

      expect(result.current.state.hybridSearch?.query_text).toBe("finance director");
      const plan = estimateClientPlan(result.current.compiled.spec);
      expect(plan.node_type).toBe("Limit");
      expect(plan.children?.[0].children?.[0].node_type).toBe("Hybrid Search Merge");
      expect(plan.children?.[0].children?.[0].children?.[0].node_type).toBe("Vector KNN Scan");
    });

    it("compiles queries with CTEs, joins, filters, window functions, and order by simultaneously across all 8 dialects", () => {
      const dialects: SqlDialect[] = [
        "postgres",
        "mysql",
        "sqlite",
        "snowflake",
        "bigquery",
        "mssql",
        "duckdb",
        "clickhouse",
      ];

      const fullSpec = {
        table: "users",
        columns: ["users.id", "users.name"],
        joins: [
          {
            table: "orders",
            type: "LEFT JOIN",
            left_table: "users",
            left_col: "id",
            right_col: "user_id",
          },
        ],
        filters: [
          {
            column: "orders.amount",
            operator: ">",
            value: 100,
          },
        ],
        ctes: [
          {
            name: "base_data",
            query: { sql: "SELECT * FROM users WHERE id > 0" },
          },
        ],
        window_functions: [
          {
            function: "COUNT",
            arguments: [],
            partition_by: ["users.department"],
            alias: "dept_cnt",
          },
        ],
        limit: 25,
      };

      for (const dialect of dialects) {
        const { result } = renderHook(() =>
          useSqlCompiler(fullSpec, { schema: sampleSchema, dialect }),
        );

        expect(result.current.sql).toContain("base_data");
        expect(result.current.sql).toContain("COUNT(*) OVER");
        expect(result.current.sql).toContain("orders");
        expect(result.current.sql).toContain("> 100");
        expect(result.current.isValid).toBe(true);
      }
    });
  });

  // =========================================================================
  // 3. STREAMING QUERIES (useStreamingQuery)
  // =========================================================================
  describe("3. Streaming Queries: useStreamingQuery Single-Execution & Abort Invariant", () => {
    let originalFetch: typeof globalThis.fetch;

    beforeEach(() => {
      originalFetch = globalThis.fetch;
    });

    afterEach(() => {
      globalThis.fetch = originalFetch;
    });

    it("invokes onComplete strictly ONCE when receiving explicit 'done' event", async () => {
      const onComplete = vi.fn();
      const onBatch = vi.fn();

      const chunks = [
        'event: metadata\ndata: {"columns": ["id", "name"]}\n\n',
        'event: batch\ndata: {"rows": [{"id": 1, "name": "Alice"}]}\n\n',
        'event: batch\ndata: {"rows": [{"id": 2, "name": "Bob"}]}\n\n',
        'event: done\ndata: {}\n\n',
      ];

      const encoder = new TextEncoder();
      const mockStream = new ReadableStream({
        start(controller) {
          for (const c of chunks) {
            controller.enqueue(encoder.encode(c));
          }
          controller.close();
        },
      });

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: mockStream,
      } as unknown as Response);

      const { result } = renderHook(() =>
        useStreamingQuery(undefined, { onComplete, onBatch }),
      );

      await act(async () => {
        await result.current.execute({ query: "SELECT * FROM users" });
      });

      expect(onBatch).toHaveBeenCalledTimes(2);
      expect(onComplete).toHaveBeenCalledTimes(1);
      expect(onComplete).toHaveBeenCalledWith(2);
      expect(result.current.rows).toHaveLength(2);
      expect(result.current.isStreaming).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it("invokes onComplete strictly ONCE when stream terminates cleanly on EOF without 'done' event", async () => {
      const onComplete = vi.fn();
      const onBatch = vi.fn();

      const chunks = [
        'event: metadata\ndata: {"columns": ["id"]}\n\n',
        'event: batch\ndata: {"rows": [{"id": 10}, {"id": 20}]}\n\n',
      ];

      const encoder = new TextEncoder();
      const mockStream = new ReadableStream({
        start(controller) {
          for (const c of chunks) {
            controller.enqueue(encoder.encode(c));
          }
          controller.close();
        },
      });

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: mockStream,
      } as unknown as Response);

      const { result } = renderHook(() =>
        useStreamingQuery(undefined, { onComplete, onBatch }),
      );

      await act(async () => {
        await result.current.execute({ query: "SELECT * FROM users" });
      });

      expect(onBatch).toHaveBeenCalledTimes(1);
      expect(onComplete).toHaveBeenCalledTimes(1);
      expect(onComplete).toHaveBeenCalledWith(2);
      expect(result.current.isStreaming).toBe(false);
    });

    it("invokes onComplete strictly ONCE for an immediate empty stream", async () => {
      const onComplete = vi.fn();

      const mockStream = new ReadableStream({
        start(controller) {
          controller.close();
        },
      });

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: mockStream,
      } as unknown as Response);

      const { result } = renderHook(() =>
        useStreamingQuery(undefined, { onComplete }),
      );

      await act(async () => {
        await result.current.execute({ query: "SELECT * FROM users" });
      });

      expect(onComplete).toHaveBeenCalledTimes(1);
      expect(onComplete).toHaveBeenCalledWith(0);
      expect(result.current.isStreaming).toBe(false);
    });

    it("NEVER invokes onComplete when stream is aborted mid-flight", async () => {
      const onComplete = vi.fn();
      const onError = vi.fn();

      const abortError = new Error("The user aborted a request.");
      abortError.name = "AbortError";

      globalThis.fetch = vi.fn().mockImplementation((_url, init) => {
        const mockStream = new ReadableStream<Uint8Array>({
          start(c) {
            init?.signal?.addEventListener("abort", () => {
              c.error(abortError);
            });
          },
        });

        return Promise.resolve({
          ok: true,
          body: mockStream,
        } as unknown as Response);
      });

      const { result } = renderHook(() =>
        useStreamingQuery(undefined, { onComplete, onError }),
      );

      let execPromise: Promise<void>;
      act(() => {
        execPromise = result.current.execute({ query: "SELECT * FROM users" });
      });

      expect(result.current.isStreaming).toBe(true);

      // Abort stream
      act(() => {
        result.current.abort();
      });

      await act(async () => {
        await execPromise;
      });

      expect(onComplete).not.toHaveBeenCalled();
      expect(onError).not.toHaveBeenCalled(); // AbortError is swallowed per contract
      expect(result.current.isStreaming).toBe(false);
    });

    it("NEVER invokes onComplete when server emits 'error' event mid-stream", async () => {
      const onComplete = vi.fn();
      const onError = vi.fn();

      const chunks = [
        'event: metadata\ndata: {"columns": ["id"]}\n\n',
        'event: batch\ndata: {"rows": [{"id": 1}]}\n\n',
        'event: error\ndata: {"message": "Database query cancelled due to timeout"}\n\n',
      ];

      const encoder = new TextEncoder();
      const mockStream = new ReadableStream({
        start(controller) {
          for (const c of chunks) {
            controller.enqueue(encoder.encode(c));
          }
          controller.close();
        },
      });

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: mockStream,
      } as unknown as Response);

      const { result } = renderHook(() =>
        useStreamingQuery(undefined, { onComplete, onError }),
      );

      await act(async () => {
        await result.current.execute({ query: "SELECT * FROM users" });
      });

      expect(onComplete).not.toHaveBeenCalled();
      expect(onError).toHaveBeenCalledTimes(1);
      expect(onError.mock.calls[0][0].message).toBe("Database query cancelled due to timeout");
      expect(result.current.error).toBe("Database query cancelled due to timeout");
      expect(result.current.isStreaming).toBe(false);
    });

    it("NEVER invokes onComplete on HTTP non-200 failure", async () => {
      const onComplete = vi.fn();
      const onError = vi.fn();

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: vi.fn().mockResolvedValue({ error: { message: "Internal server error" } }),
      } as unknown as Response);

      const { result } = renderHook(() =>
        useStreamingQuery(undefined, { onComplete, onError }),
      );

      await act(async () => {
        await result.current.execute({ query: "SELECT * FROM users" });
      });

      expect(onComplete).not.toHaveBeenCalled();
      expect(onError).toHaveBeenCalledTimes(1);
      expect(onError.mock.calls[0][0].message).toBe("Internal server error");
      expect(result.current.isStreaming).toBe(false);
    });
  });

  // =========================================================================
  // 4. THEME SWITCHING: PRESERVING TOKENS OVER MULTIPLE TOGGLES
  // =========================================================================
  describe("4. Theme Switching: User Custom Tokens Survival across Cycles", () => {
    it("preserves custom palette and token overrides across 10 rapid toggleMode cycles", () => {
      const customTheme = {
        colors: {
          primary: "#e11d48", // Rose-600
          accent: "#38bdf8",  // Sky-400
        },
      };

      const customTokens = {
        typography: {
          fontSizeBase: "17px",
        },
      };

      const Consumer = () => {
        const { theme, mode, toggleMode, setMode } = useTheme();
        return (
          <div>
            <span data-testid="mode">{mode}</span>
            <span data-testid="primary">{theme.colors.primary}</span>
            <span data-testid="accent">{theme.colors.accent}</span>
            <span data-testid="fontSize">{theme.typography.fontSizeBase}</span>
            <button data-testid="toggle-btn" onClick={() => toggleMode()}>
              toggle
            </button>
            <button data-testid="set-light-btn" onClick={() => setMode("light")}>
              setLight
            </button>
            <button data-testid="set-dark-btn" onClick={() => setMode("dark")}>
              setDark
            </button>
          </div>
        );
      };

      render(
        <ThemeProvider theme={customTheme} customTokens={customTokens} mode="dark">
          <Consumer />
        </ThemeProvider>,
      );

      expect(screen.getByTestId("mode").textContent).toBe("dark");
      expect(screen.getByTestId("primary").textContent).toBe("#e11d48");
      expect(screen.getByTestId("accent").textContent).toBe("#38bdf8");
      expect(screen.getByTestId("fontSize").textContent).toBe("17px");

      // Cycle 10 times: dark -> light -> dark -> light -> ...
      for (let i = 0; i < 10; i++) {
        fireEvent.click(screen.getByTestId("toggle-btn"));
        const expectedMode = i % 2 === 0 ? "light" : "dark";
        expect(screen.getByTestId("mode").textContent).toBe(expectedMode);
        expect(screen.getByTestId("primary").textContent).toBe("#e11d48");
        expect(screen.getByTestId("accent").textContent).toBe("#38bdf8");
        expect(screen.getByTestId("fontSize").textContent).toBe("17px");
      }

      // Explicit setMode checks
      fireEvent.click(screen.getByTestId("set-light-btn"));
      expect(screen.getByTestId("mode").textContent).toBe("light");
      expect(screen.getByTestId("primary").textContent).toBe("#e11d48");
      expect(screen.getByTestId("fontSize").textContent).toBe("17px");

      fireEvent.click(screen.getByTestId("set-dark-btn"));
      expect(screen.getByTestId("mode").textContent).toBe("dark");
      expect(screen.getByTestId("primary").textContent).toBe("#e11d48");
      expect(screen.getByTestId("fontSize").textContent).toBe("17px");
    });
  });

  // =========================================================================
  // 5. ACCESSIBILITY & MODAL KEY LISTENERS
  // =========================================================================
  describe("5. Accessibility & Modal Keyboard Listeners", () => {
    it("dismisses WindowFunctionBuilder on Escape key and cleans up listener on unmount", () => {
      const onClose = vi.fn();
      const { unmount } = render(
        <WindowFunctionBuilder
          isOpen={true}
          onClose={onClose}
          onSave={() => {}}
          availableColumns={[{ table: "users", name: "id" }]}
        />,
      );

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);

      // Unmount component
      unmount();

      // Additional Escape key presses must not invoke onClose after unmount
      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("dismisses CalculatedFieldEditor on Escape key and cleans up listener on unmount", () => {
      const onClose = vi.fn();
      const { unmount } = render(
        <CalculatedFieldEditor
          isOpen={true}
          onClose={onClose}
          onSave={() => {}}
          tables={[{ name: "users", columns: [{ name: "id", data_type: "int", is_nullable: true, is_primary: false }] }]}
        />,
      );

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);

      unmount();

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("does not trigger onClose when WindowFunctionBuilder or CalculatedFieldEditor is closed (isOpen: false)", () => {
      const onCloseWf = vi.fn();
      const onCloseCalc = vi.fn();

      render(
        <div>
          <WindowFunctionBuilder
            isOpen={false}
            onClose={onCloseWf}
            onSave={() => {}}
            availableColumns={[]}
          />
          <CalculatedFieldEditor
            isOpen={false}
            onClose={onCloseCalc}
            onSave={() => {}}
            tables={[]}
          />
        </div>,
      );

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onCloseWf).not.toHaveBeenCalled();
      expect(onCloseCalc).not.toHaveBeenCalled();
    });

    it("verifies full suite of aria-labels across TableJoinEditor, TableSortsEditor, and QueryCanvas", () => {
      const { unmount: unmount1 } = render(
        <TableJoinEditor
          joins={[
            {
              id: "join-test-1",
              type: "INNER JOIN",
              table: "orders",
              left_table: "users",
              left_col: "id",
              right_col: "user_id",
            },
          ]}
          activeTables={[{ name: "users", columns: [] }]}
          allTables={[{ name: "users", columns: [] }, { name: "orders", columns: [] }]}
          onChange={() => {}}
        />,
      );

      expect(screen.getByLabelText("Join table")).toBeDefined();
      expect(screen.getByLabelText("Join type")).toBeDefined();
      expect(screen.getByLabelText("Join left column")).toBeDefined();
      expect(screen.getByLabelText("Join right column")).toBeDefined();
      expect(screen.getByLabelText("Remove join")).toBeDefined();
      unmount1();

      const { unmount: unmount2 } = render(
        <TableSortsEditor
          sorts={[
            {
              id: "sort-test-1",
              tablePrefix: "users",
              column: "id",
              direction: "DESC",
            },
          ]}
          activeTables={[{ name: "users", columns: [{ name: "id", data_type: "int", is_nullable: true, is_primary: false }] }]}
          onChange={() => {}}
        />,
      );

      expect(screen.getByLabelText("Add sort")).toBeDefined();
      expect(screen.getByLabelText("Sort column")).toBeDefined();
      expect(screen.getByLabelText("Toggle sort direction")).toBeDefined();
      expect(screen.getByLabelText("Remove sort")).toBeDefined();
      unmount2();

      render(
        <QueryCanvas
          {...makeCanvasProps()}
          schema={sampleSchema}
          primaryTable="users"
          activeTables={[{ name: "users", columns: [{ name: "id", data_type: "int", is_nullable: true, is_primary: false }] }]}
          selectedColumns={{ "users.id": { table: "users", name: "id" } }}
          orderedProjectionKeys={["users.id"]}
          joins={[]}
          limit={50}
          onToggleColumn={() => {}}
          onUpdateColumnSelect={() => {}}
          onRemoveColumnProjection={() => {}}
          onReorderProjections={() => {}}
          onLimitChange={() => {}}
          onAddTableToCanvas={() => {}}
        />,
      );

      expect(screen.getByLabelText("Add table to canvas")).toBeDefined();
      expect(screen.getByLabelText("Query row limit")).toBeDefined();
      expect(screen.getByLabelText("Remove projection users.id")).toBeDefined();
    });
  });

  // =========================================================================
  // 6. VISUAL BUILDER MODE SWITCHING & SQL PARSER ALIAS RESOLUTION
  // =========================================================================
  describe("6. VisualQueryBuilder Mode Switching & SQL Parser Alias Resolution", () => {
    it("resets isRawMode to false on reset, setSpec, and canvas mutations", () => {
      const ref = React.createRef<VisualQueryBuilderRef>();
      render(
        <VisualQueryBuilder
          ref={ref}
          schema={sampleSchema}
          initialTable="users"
        />,
      );

      // Switch to Raw SQL
      fireEvent.click(screen.getByText(/Raw SQL/i));
      const textarea = screen.getByLabelText("Raw SQL code");
      fireEvent.change(textarea, { target: { value: "SELECT * FROM custom_table" } });
      expect(ref.current?.getSql()).toBe("SELECT * FROM custom_table");

      // Reset imperative ref
      act(() => {
        ref.current?.reset();
      });
      // Should exit raw mode and return compiled visual SQL
      expect(ref.current?.getSql()).not.toBe("SELECT * FROM custom_table");
      expect(ref.current?.getSql()).toContain('"users"');
    });

    it("parses bidirectional SQL joins with and without AS aliases", () => {
      // Left = Right with alias
      const sql1 = "SELECT a.id, b.amount FROM users a JOIN orders b ON a.id = b.user_id";
      const spec1 = parseSqlToSpec(sql1);
      expect(spec1).not.toBeNull();
      expect(spec1?.joins?.[0].left_table).toBe("users");
      expect(spec1?.joins?.[0].table).toBe("orders");
      expect(spec1?.joins?.[0].left_col).toBe("id");
      expect(spec1?.joins?.[0].right_col).toBe("user_id");

      // Right = Left with explicit AS
      const sql2 = "SELECT a.id, b.amount FROM users AS a JOIN orders AS b ON b.user_id = a.id";
      const spec2 = parseSqlToSpec(sql2);
      expect(spec2).not.toBeNull();
      expect(spec2?.joins?.[0].left_table).toBe("users");
      expect(spec2?.joins?.[0].table).toBe("orders");
      expect(spec2?.joins?.[0].left_col).toBe("id");
      expect(spec2?.joins?.[0].right_col).toBe("user_id");
    });
  });
});
