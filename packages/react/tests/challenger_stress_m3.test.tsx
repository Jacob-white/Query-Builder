import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, renderHook } from "@testing-library/react";
import {
  useQueryBuilder,
  useQueryExecution,
  useSchemaIntrospection,
  ThemeProvider,
  useTheme,
  mergeTheme,
  darkTheme,
  lightTheme,
  VisualQueryBuilder,
  ComponentShowcase,
  TableCard,
  SchemaErdModal,
  type QueryBuilderTheme,
  type SchemaSnapshot,
  type QueryResultData,
} from "../src/index";

const MOCK_STRESS_SCHEMA: SchemaSnapshot = {
  tables: {
    customers: {
      name: "customers",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "company", data_type: "VARCHAR", is_nullable: false, is_primary: false },
        { name: "tier", data_type: "VARCHAR", is_nullable: true, is_primary: false },
      ],
      has_user_id: false,
    },
    invoices: {
      name: "invoices",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "customer_id", data_type: "INTEGER", is_nullable: false, is_primary: false },
        { name: "amount", data_type: "DECIMAL", is_nullable: false, is_primary: false },
        { name: "status", data_type: "VARCHAR", is_nullable: false, is_primary: false },
      ],
      has_user_id: true,
    },
  },
  foreign_keys: [
    { table: "invoices", column: "customer_id", foreign_table: "customers", foreign_column: "id" },
  ],
};

describe("Milestone 3 Challenger Empirical Stress Harness", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.clear();
    }
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // =========================================================================
  // 1. Headless Hook Stress: useQueryBuilder
  // =========================================================================
  describe("useQueryBuilder Extreme State Mutations & Fuzzing", () => {
    it("handles rapid high-volume table, column, filter, and sort state mutations", () => {
      const { result } = renderHook(() =>
        useQueryBuilder({
          schema: MOCK_STRESS_SCHEMA,
          initialTable: "customers",
        }),
      );

      expect(result.current.state.isDirty).toBe(false);

      act(() => {
        // Add table
        result.current.actions.addTable("invoices");
        // Add 50 joins, 50 filters, 50 sorts
        for (let i = 0; i < 50; i++) {
          result.current.actions.addJoin({
            id: `join_${i}`,
            type: "LEFT JOIN",
            table: "invoices",
            left_table: "customers",
            left_col: "id",
            right_col: "customer_id",
          });
          result.current.actions.addFilter({
            id: `filter_${i}`,
            tablePrefix: "invoices",
            column: "amount",
            operator: ">",
            value: `${i * 100}`,
          });
          result.current.actions.addSort({
            id: `sort_${i}`,
            tablePrefix: "invoices",
            column: "amount",
            direction: i % 2 === 0 ? "ASC" : "DESC",
          });
        }
      });

      expect(result.current.state.joins.length).toBe(50);
      expect(result.current.state.filters.length).toBe(50);
      expect(result.current.state.sorts.length).toBe(50);
      expect(result.current.state.isDirty).toBe(true);

      // Verify compiled query generated valid SQL (compiler caps joins to 20 safely)
      expect(result.current.compiled.sql).toContain('FROM "customers"');
      expect(result.current.compiled.sql).toContain('LEFT JOIN "invoices"');
      expect(result.current.safety.valid).toBe(true);

      // Mark clean
      act(() => {
        result.current.actions.markClean();
      });
      expect(result.current.state.isDirty).toBe(false);

      // Reset restores back to initial state
      act(() => {
        result.current.actions.reset();
      });
      expect(result.current.state.joins.length).toBe(0);
      expect(result.current.state.filters.length).toBe(0);
      expect(result.current.state.sorts.length).toBe(0);
      expect(result.current.state.isDirty).toBe(false);
    });

    it("survives malformed and adversarial specs passed to loadSpec", () => {
      const { result } = renderHook(() =>
        useQueryBuilder({
          schema: MOCK_STRESS_SCHEMA,
          initialTable: "customers",
        }),
      );

      // Fuzz loadSpec with unexpected data shapes
      const malformedSpecs: Record<string, unknown>[] = [
        {},
        { table: null, joins: "not an array", limit: "not a number" },
        { primaryTable: 12345, activeTables: "orders" },
        { selectedColumns: null, orderedProjectionKeys: null },
        { isDistinct: "yes", distinct: null },
      ];

      for (const badSpec of malformedSpecs) {
        expect(() => {
          act(() => {
            result.current.actions.loadSpec(badSpec);
          });
        }).not.toThrow();
      }
    });

    it("detects SQL injection patterns via safety analysis", () => {
      const { result } = renderHook(() =>
        useQueryBuilder({
          schema: MOCK_STRESS_SCHEMA,
          initialTable: "customers",
        }),
      );

      act(() => {
        result.current.actions.setIsRawMode(true);
        result.current.actions.setRawSql("SELECT * FROM customers; DROP TABLE invoices;");
      });

      expect(result.current.safety.valid).toBe(false);
      expect(result.current.safety.injectionRisk).toBe("CRITICAL");
      expect(result.current.safety.violations.length).toBeGreaterThan(0);
    });
  });

  // =========================================================================
  // 2. Headless Hook Stress: useQueryExecution
  // =========================================================================
  describe("useQueryExecution Concurrency, Abort & Timeout Stress", () => {
    it("cancels prior in-flight query when new query is triggered (race condition guard)", async () => {
      const slowExecutor = vi.fn().mockImplementation((sql: string) => {
        return new Promise<QueryResultData>((resolve) => {
          setTimeout(() => {
            resolve({
              columns: ["col"],
              rows: [{ col: sql }],
              count: 1,
            });
          }, 50);
        });
      });

      const { result } = renderHook(() =>
        useQueryExecution({
          onExecuteQuery: slowExecutor,
        }),
      );

      // Trigger 3 executions in rapid succession
      act(() => {
        result.current.executeQuery("QUERY_1");
        result.current.executeQuery("QUERY_2");
        result.current.executeQuery("QUERY_3");
      });

      expect(result.current.isLoading).toBe(true);

      // Wait for queries to settle
      await act(async () => {
        await new Promise((r) => setTimeout(r, 80));
      });

      expect(result.current.isLoading).toBe(false);
      // Results should be set from the last execution
      expect(result.current.results?.rows[0].col).toBe("QUERY_3");
    });

    it("aborts query execution when defaultTimeoutMs is reached with remote endpoint", async () => {
      let aborted = false;
      global.fetch = vi.fn().mockImplementation((_url, options) => {
        return new Promise((_resolve, reject) => {
          if (options?.signal) {
            options.signal.addEventListener("abort", () => {
              aborted = true;
              const err = new Error("The operation was aborted");
              err.name = "AbortError";
              reject(err);
            });
          }
        });
      });

      const { result } = renderHook(() =>
        useQueryExecution({
          apiEndpoint: "/api/slow",
          defaultTimeoutMs: 25,
        }),
      );

      let promiseResult: QueryResultData | null = null;
      act(() => {
        result.current.executeQuery("SLOW_QUERY").then((res) => {
          promiseResult = res;
        });
      });

      expect(result.current.isLoading).toBe(true);

      await act(async () => {
        await new Promise((r) => setTimeout(r, 50));
      });

      expect(aborted).toBe(true);
      expect(result.current.isLoading).toBe(false);
      expect(promiseResult).toBeNull();
      expect(result.current.results).toBeNull();
    });

    it("safely handles unmount during in-flight asynchronous query execution", async () => {
      const slowExecutor = vi.fn().mockImplementation(() => {
        return new Promise<QueryResultData>((resolve) => {
          setTimeout(() => {
            resolve({
              columns: ["id"],
              rows: [{ id: 1 }],
              count: 1,
            });
          }, 50);
        });
      });

      const { result, unmount } = renderHook(() =>
        useQueryExecution({
          onExecuteQuery: slowExecutor,
        }),
      );

      act(() => {
        result.current.executeQuery("SELECT 1;");
      });

      // Unmount while query is pending
      expect(() => unmount()).not.toThrow();

      await act(async () => {
        await new Promise((r) => setTimeout(r, 60));
      });
    });

    it("handles executor rejection with non-Error objects gracefully", async () => {
      const onErrorMock = vi.fn();
      const stringRejectExecutor = vi.fn().mockRejectedValue("Fatal database deadlock!");

      const { result } = renderHook(() =>
        useQueryExecution({
          onExecuteQuery: stringRejectExecutor,
          onError: onErrorMock,
        }),
      );

      await act(async () => {
        await result.current.executeQuery("BAD_QUERY");
      });

      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBe("Fatal database deadlock!");
      expect(onErrorMock).toHaveBeenCalledTimes(1);
      expect(onErrorMock.mock.calls[0][0].message).toBe("Fatal database deadlock!");
    });
  });

  // =========================================================================
  // 3. Headless Hook Stress: useSchemaIntrospection
  // =========================================================================
  describe("useSchemaIntrospection Storage Failure Resilience", () => {
    it("handles localStorage SecurityError without throwing during init, refresh, and clear", async () => {
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new DOMException("The operation is insecure.", "SecurityError");
      });
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new DOMException("The operation is insecure.", "SecurityError");
      });
      vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
        throw new DOMException("The operation is insecure.", "SecurityError");
      });

      const { result } = renderHook(() =>
        useSchemaIntrospection({
          initialSchema: MOCK_STRESS_SCHEMA,
          cacheKey: "qb_schema_cache",
        }),
      );

      expect(result.current.schema).toEqual(MOCK_STRESS_SCHEMA);

      // Clear schema with throwing removeItem
      act(() => {
        result.current.clearSchema();
      });
      expect(result.current.schema).toBeNull();
    });

    it("handles remote fetch returning non-OK HTTP status", async () => {
      const onErrorMock = vi.fn();
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
      } as Response);

      const { result } = renderHook(() =>
        useSchemaIntrospection({
          apiEndpoint: "/api/v1/introspect",
          onError: onErrorMock,
        }),
      );

      await act(async () => {
        const res = await result.current.refreshSchema();
        expect(res).toBeNull();
      });

      expect(result.current.error).toContain("HTTP error 503");
      expect(result.current.isLoading).toBe(false);
      expect(onErrorMock).toHaveBeenCalledTimes(1);
    });
  });

  // =========================================================================
  // 4. Design Tokens & Theming Immutability
  // =========================================================================
  describe("Theming Immutability & Deep-Merge Boundaries", () => {
    it("guarantees frozen base themes are never mutated by mergeTheme", () => {
      // Deep freeze darkTheme
      const frozenDark = Object.freeze({
        ...darkTheme,
        colors: Object.freeze({ ...darkTheme.colors }),
        typography: Object.freeze({ ...darkTheme.typography }),
        radii: Object.freeze({ ...darkTheme.radii }),
        shadows: Object.freeze({ ...darkTheme.shadows }),
      });

      expect(() => {
        const merged = mergeTheme(frozenDark as QueryBuilderTheme, {
          colors: { primary: "#e11d48" },
        });
        expect(merged.colors.primary).toBe("#e11d48");
        expect(frozenDark.colors.primary).toBe("#3b82f6");
      }).not.toThrow();
    });

    it("handles mergeTheme with undefined, empty, or partial slices", () => {
      const mergedUndef = mergeTheme(lightTheme, undefined);
      expect(mergedUndef).toEqual(lightTheme);

      const mergedPartial = mergeTheme(darkTheme, {
        typography: { fontFamily: "Courier New" },
      });
      expect(mergedPartial.typography.fontFamily).toBe("Courier New");
      expect(mergedPartial.typography.fontSizeBase).toBe(darkTheme.typography.fontSizeBase);
    });

    it("allows rapid mode toggling without state corruption", () => {
      const Harness: React.FC = () => {
        const { mode, toggleMode } = useTheme();
        return (
          <div>
            <span data-testid="mode-val">{mode}</span>
            <button type="button" onClick={toggleMode}>
              Toggle
            </button>
          </div>
        );
      };

      render(
        <ThemeProvider>
          <Harness />
        </ThemeProvider>,
      );

      const btn = screen.getByText("Toggle");
      // Rapidly toggle 20 times
      for (let i = 0; i < 20; i++) {
        fireEvent.click(btn);
      }
      // 20 toggles returns back to dark
      expect(screen.getByTestId("mode-val").textContent).toBe("dark");
    });
  });

  // =========================================================================
  // 5. Accessibility (WCAG 2.1 AA) Trapping & Boundary Navigation
  // =========================================================================
  describe("WCAG 2.1 AA Keyboard Navigation & Dialog Dismissals", () => {
    it("handles bidirectional tab wrap-around and Home/End jumping in VisualQueryBuilder", () => {
      render(<VisualQueryBuilder schema={MOCK_STRESS_SCHEMA} />);

      const tabVisual = screen.getByRole("tab", { name: /Visual Builder/i });
      const tabSql = screen.getByRole("tab", { name: /Raw SQL/i });
      const tabResults = screen.getByRole("tab", { name: /Results/i });
      const tabChart = screen.getByRole("tab", { name: /Visual Chart/i });

      // Initial tab: Visual
      expect(tabVisual.getAttribute("aria-selected")).toBe("true");
      expect(tabVisual.getAttribute("tabIndex")).toBe("0");
      expect(tabSql.getAttribute("tabIndex")).toBe("-1");

      // ArrowRight -> sql
      fireEvent.keyDown(tabVisual, { key: "ArrowRight" });
      expect(tabSql.getAttribute("aria-selected")).toBe("true");

      // ArrowRight -> results
      fireEvent.keyDown(tabSql, { key: "ArrowRight" });
      expect(tabResults.getAttribute("aria-selected")).toBe("true");

      // ArrowRight -> chart
      fireEvent.keyDown(tabResults, { key: "ArrowRight" });
      expect(tabChart.getAttribute("aria-selected")).toBe("true");

      // ArrowRight from last tab -> wrap around to visual
      fireEvent.keyDown(tabChart, { key: "ArrowRight" });
      expect(tabVisual.getAttribute("aria-selected")).toBe("true");

      // ArrowLeft from first tab -> wrap around to chart
      fireEvent.keyDown(tabVisual, { key: "ArrowLeft" });
      expect(tabChart.getAttribute("aria-selected")).toBe("true");

      // Home key jumps from chart to first tab (visual)
      fireEvent.keyDown(tabChart, { key: "Home" });
      expect(tabVisual.getAttribute("aria-selected")).toBe("true");

      // End key jumps from visual to last tab (chart)
      fireEvent.keyDown(tabVisual, { key: "End" });
      expect(tabChart.getAttribute("aria-selected")).toBe("true");
    });

    it("verifies SchemaErdModal Escape key and backdrop dismissal semantics", () => {
      const handleClose = vi.fn();
      render(
        <SchemaErdModal
          isOpen={true}
          onClose={handleClose}
          schema={MOCK_STRESS_SCHEMA}
        />,
      );

      const dialog = screen.getByRole("dialog");
      expect(dialog.getAttribute("aria-modal")).toBe("true");
      expect(dialog.getAttribute("aria-labelledby")).toBe("schema-erd-title");

      // Clicking dialog content does NOT close
      fireEvent.click(dialog);
      expect(handleClose).not.toHaveBeenCalled();

      // Escape key dismisses
      fireEvent.keyDown(window, { key: "Escape" });
      expect(handleClose).toHaveBeenCalledTimes(1);

      // Backdrop click dismisses
      const backdrop = dialog.parentElement!;
      fireEvent.click(backdrop);
      expect(handleClose).toHaveBeenCalledTimes(2);
    });

    it("verifies TableCard accessible landmarks, column checkboxes, and action labels", () => {
      const onToggle = vi.fn();
      const onRemove = vi.fn();
      const onAddJoin = vi.fn();

      render(
        <TableCard
          table={MOCK_STRESS_SCHEMA.tables.customers}
          selectedColumns={{}}
          onToggleColumn={onToggle}
          onRemoveTable={onRemove}
          onAddJoin={onAddJoin}
        />,
      );

      // Region landmark
      const region = screen.getByRole("region", { name: "Table customers" });
      expect(region).toBeTruthy();

      // Buttons
      const removeBtn = screen.getByRole("button", { name: "Remove table customers" });
      fireEvent.click(removeBtn);
      expect(onRemove).toHaveBeenCalledTimes(1);

      const joinBtn = screen.getByRole("button", { name: "Add join for table customers" });
      fireEvent.click(joinBtn);
      expect(onAddJoin).toHaveBeenCalledTimes(1);

      // Column checkbox
      const checkbox = screen.getByLabelText("Select column customers.company");
      fireEvent.click(checkbox);
      expect(onToggle).toHaveBeenCalledWith("company");
    });
  });

  // =========================================================================
  // 6. ComponentShowcase Interactive Catalog
  // =========================================================================
  describe("ComponentShowcase All Modes & Interactive Snippets", () => {
    it("renders and switches across all 5 showcase modes seamlessly", () => {
      render(<ComponentShowcase initialTab="studio" />);

      expect(screen.getByRole("heading", { name: /Component Catalog & Documentation/i })).toBeTruthy();
      expect(screen.getByText(/🎨 Visual Builder/i)).toBeTruthy();

      // Switch to Headless Hooks
      fireEvent.click(screen.getByRole("button", { name: "Headless Hooks" }));
      expect(screen.getByText("Headless Query State & Controls")).toBeTruthy();

      // Toggle a column in headless demo
      const colCheckbox = screen.getByLabelText("name");
      fireEvent.click(colCheckbox);

      // Switch to Visual Charts
      fireEvent.click(screen.getByRole("button", { name: "Visual Charts" }));
      expect(screen.getByRole("region", { name: "Visual Chart Preview" })).toBeTruthy();
      expect(screen.getByRole("img", { name: /chart of sales/i })).toBeTruthy();

      // Switch to Theming Playground
      fireEvent.click(screen.getByRole("button", { name: "Theming Playground" }));
      expect(screen.getByText("🌙 Dark Mode")).toBeTruthy();
      expect(screen.getByText("☀️ Light Mode")).toBeTruthy();

      // Toggle Light Mode in theming playground
      fireEvent.click(screen.getByText("☀️ Light Mode"));

      // Click color button
      const emeraldBtn = screen.getByTitle("Emerald");
      fireEvent.click(emeraldBtn);

      // Switch to Template Library
      fireEvent.click(screen.getByRole("button", { name: "Template Library" }));
      expect(screen.getByText("Active Users Directory")).toBeTruthy();

      // Select a template card
      fireEvent.click(screen.getByText("Active Users Directory"));
      expect(screen.getByText(/Selected Template:/i)).toBeTruthy();

      // Open and close Template Manager modal
      fireEvent.click(screen.getByRole("button", { name: "📚 Open Template Manager" }));
      expect(screen.getByRole("dialog")).toBeTruthy();
      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("copies active tab code snippet to clipboard and provides visual feedback", async () => {
      const mockClipboard = {
        writeText: vi.fn().mockResolvedValue(undefined),
      };
      Object.assign(navigator, { clipboard: mockClipboard });

      render(<ComponentShowcase initialTab="headless" />);

      const copyBtn = screen.getByRole("button", { name: /Copy Code/i });
      await act(async () => {
        fireEvent.click(copyBtn);
      });

      expect(mockClipboard.writeText).toHaveBeenCalledTimes(1);
      expect(mockClipboard.writeText.mock.calls[0][0]).toContain("useQueryBuilder");
      expect(screen.getByText("✅ Copied!")).toBeTruthy();
    });
  });
});
