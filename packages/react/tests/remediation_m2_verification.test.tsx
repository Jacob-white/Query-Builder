import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, act, renderHook } from "@testing-library/react";
import { useSqlCompiler } from "../src/hooks/useSqlCompiler";
import { useQueryBuilder } from "../src/hooks/useQueryBuilder";
import { useQueryState } from "../src/hooks/useQueryState";
import { useStreamingQuery } from "../src/hooks/useStreamingQuery";
import { ThemeProvider, useTheme } from "../src/theme/ThemeProvider";
import { TableJoinEditor } from "../src/components/TableJoinEditor";
import { TableSortsEditor } from "../src/components/TableSortsEditor";
import { QueryCanvas } from "../src/components/QueryCanvas";
import { WindowFunctionBuilder } from "../src/components/WindowFunctionBuilder";
import { CalculatedFieldEditor } from "../src/components/CalculatedFieldEditor";
import { parseSqlToSpec } from "../src/utils/sqlParser";
import { invalid, makeSpec } from "./helpers";
import { makeCanvasProps } from "./helpers/canvas";
import { VisualQueryBuilder, type VisualQueryBuilderRef } from "../src/components/VisualQueryBuilder";
import type { CteSpec, SchemaSnapshot } from "../src/types";

describe("Milestone 2 Remediations Verification", () => {
  const sampleSchema: SchemaSnapshot = {
    tables: {
      users: {
        name: "users",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "name", data_type: "varchar", is_nullable: true, is_primary: false },
          { name: "embedding", data_type: "vector", is_nullable: true, is_primary: false },
        ],
      },
      orders: {
        name: "orders",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "amount", data_type: "numeric", is_nullable: false, is_primary: false },
        ],
      },
    },
  };

  describe("1. useSqlCompiler & useQueryBuilder forward advanced clauses", () => {
    it("compiles CTEs, window functions, and vector search in useSqlCompiler", () => {
      const spec = {
        table: "users",
        columns: ["users.id", "users.name"],
        ctes: [
          {
            name: "recent_users",
            query: "SELECT id FROM users WHERE id > 10",
          },
        ],
        window_functions: [
          {
            function: "ROW_NUMBER",
            arguments: [],
            order_by: [{ column: "id", direction: "ASC" as const }],
            alias: "row_num",
          },
        ],
        vector_search: {
          column: "embedding",
          vector: [0.1, 0.2, 0.3],
          topK: 5,
          metric: "cosine" as const,
        },
      };

      const { result } = renderHook(() =>
        useSqlCompiler(spec, { schema: sampleSchema, dialect: "postgres" }),
      );

      expect(result.current.sql).toContain('WITH "recent_users" AS');
      expect(result.current.sql).toContain("ROW_NUMBER() OVER");
      expect(result.current.ast?.ctes).toHaveLength(1);
      expect(result.current.ast?.window_functions).toHaveLength(1);
      expect(result.current.ast?.vector_search).toBeDefined();
    });

    it("compiles CTEs and window functions in useQueryBuilder", () => {
      const { result } = renderHook(() =>
        useQueryBuilder({
          schema: sampleSchema,
          initialTable: "users",
          ctes: [
            {
              name: "v_active",
              query: invalid<CteSpec["query"]>("SELECT id FROM users"), // legacy string form: deliberately off-type
            },
          ],
          windowFunctions: [
            {
              function: "RANK",
              arguments: [],
              order_by: [{ column: "id", direction: "DESC" as const }],
              alias: "rk",
            },
          ],
        }),
      );

      expect(result.current.compiled.sql).toContain('WITH "v_active" AS');
      expect(result.current.compiled.sql).toContain("RANK() OVER");
      expect(result.current.state.ctes).toHaveLength(1);
      expect(result.current.state.windowFunctions).toHaveLength(1);
    });
  });

  describe("2. VisualQueryBuilder onAddJoins & isRawMode reset", () => {
    it("resets isRawMode to false when canvas mutations or imperative methods execute", () => {
      const ref = React.createRef<VisualQueryBuilderRef>();
      render(
        <VisualQueryBuilder
          ref={ref}
          schema={sampleSchema}
          initialTable="users"
        />,
      );

      // Switch to SQL tab and type raw SQL
      const sqlTab = screen.getByText(/Raw SQL/i);
      fireEvent.click(sqlTab);

      const textarea = screen.getByLabelText("Raw SQL code");
      fireEvent.change(textarea, { target: { value: "SELECT id FROM users WHERE id = 1" } });

      // Check that imperative getSql returns the raw SQL while in raw mode
      expect(ref.current?.getSql()).toBe("SELECT id FROM users WHERE id = 1");

      // Imperatively set spec -> should reset isRawMode to false
      act(() => {
        ref.current?.setSpec(makeSpec({
          table: "users",
          columns: ["users.id", "users.name"],
        }));
      });

      // Now currentSql reflects compiled SQL, not stale raw SQL
      expect(ref.current?.getSql()).toContain('"users"."name"');

      // Switch back to SQL and modify again
      fireEvent.change(textarea, { target: { value: "SELECT * FROM orders" } });
      expect(ref.current?.getSql()).toBe("SELECT * FROM orders");

      // Calling undo resets isRawMode
      act(() => {
        ref.current?.undo();
      });
      expect(ref.current?.getSql()).not.toBe("SELECT * FROM orders");
    });
  });

  describe("3. useQueryState pure updaters and stable actions", () => {
    it("maintains stable actions memoization and executes consecutive undo/redo without stale closure", () => {
      const { result } = renderHook(() => useQueryState({ table: "users" }));

      const initialActions = result.current.actions;

      // Mutation 1
      act(() => {
        result.current.actions.addTable("orders");
      });
      expect(result.current.state.activeTables).toContain("orders");

      // Actions reference must remain referentially stable
      expect(result.current.actions).toBe(initialActions);

      // Mutation 2
      act(() => {
        result.current.actions.setLimit(100);
      });
      expect(result.current.state.limit).toBe(100);
      expect(result.current.actions).toBe(initialActions);

      // Consecutive undo
      act(() => {
        result.current.actions.undo();
        result.current.actions.undo();
      });
      expect(result.current.state.limit).toBe(50);
      expect(result.current.state.activeTables).not.toContain("orders");

      // Consecutive redo
      act(() => {
        result.current.actions.redo();
        result.current.actions.redo();
      });
      expect(result.current.state.limit).toBe(100);
      expect(result.current.state.activeTables).toContain("orders");
      expect(result.current.actions).toBe(initialActions);
    });
  });

  describe("4. useStreamingQuery onComplete guard", () => {
    it("invokes onComplete strictly once when receiving event: done", async () => {
      const onComplete = vi.fn();
      const streamChunks = [
        'event: metadata\ndata: {"columns": ["id"]}\n\n',
        'event: batch\ndata: {"rows": [{"id": 1}]}\n\n',
        'event: done\ndata: {}\n\n',
      ];

      const encoder = new TextEncoder();
      const mockStream = new ReadableStream({
        start(controller) {
          for (const chunk of streamChunks) {
            controller.enqueue(encoder.encode(chunk));
          }
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
        await result.current.execute({ table: "test" });
      });

      expect(onComplete).toHaveBeenCalledTimes(1);
      expect(onComplete).toHaveBeenCalledWith(1);
    });
  });

  describe("6. ThemeProvider custom token preservation", () => {
    it("preserves custom tokens when toggling and setting mode", () => {
      const customTheme = {
        colors: {
          primary: "#123456",
        },
      };

      const Consumer = () => {
        const { theme, mode, setMode, toggleMode } = useTheme();
        return (
          <div>
            <span data-testid="mode">{mode}</span>
            <span data-testid="primary">{theme.colors.primary}</span>
            <button onClick={() => toggleMode()}>toggle</button>
            <button onClick={() => setMode("light")}>setLight</button>
            <button onClick={() => setMode("dark")}>setDark</button>
          </div>
        );
      };

      render(
        <ThemeProvider theme={customTheme}>
          <Consumer />
        </ThemeProvider>,
      );

      expect(screen.getByTestId("primary").textContent).toBe("#123456");

      // Toggle to light mode -> custom token must persist
      fireEvent.click(screen.getByText("toggle"));
      expect(screen.getByTestId("mode").textContent).toBe("light");
      expect(screen.getByTestId("primary").textContent).toBe("#123456");

      // Set to dark mode -> custom token must persist
      fireEvent.click(screen.getByText("setDark"));
      expect(screen.getByTestId("mode").textContent).toBe("dark");
      expect(screen.getByTestId("primary").textContent).toBe("#123456");
    });
  });

  describe("7. Accessibility aria-labels and Modal Escape key listeners", () => {
    it("renders aria-labels on TableJoinEditor controls", () => {
      render(
        <TableJoinEditor
          joins={[
            {
              id: "j1",
              type: "LEFT JOIN",
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
    });

    it("renders aria-labels on TableSortsEditor controls", () => {
      render(
        <TableSortsEditor
          sorts={[
            {
              id: "s1",
              tablePrefix: "users",
              column: "id",
              direction: "ASC",
            },
          ]}
          activeTables={[
            {
              name: "users",
              columns: [{ name: "id", data_type: "int", is_nullable: true, is_primary: false }],
            },
          ]}
          onChange={() => {}}
        />,
      );

      expect(screen.getByLabelText("Add sort")).toBeDefined();
      expect(screen.getByLabelText("Sort column")).toBeDefined();
      expect(screen.getByLabelText("Toggle sort direction")).toBeDefined();
      expect(screen.getByLabelText("Remove sort")).toBeDefined();
    });

    it("renders aria-labels on QueryCanvas controls", () => {
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

    it("closes WindowFunctionBuilder on Escape key", () => {
      const onClose = vi.fn();
      render(
        <WindowFunctionBuilder
          isOpen={true}
          onClose={onClose}
          onSave={() => {}}
          availableColumns={[{ table: "users", name: "id" }]}
        />,
      );

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("closes CalculatedFieldEditor on Escape key", () => {
      const onClose = vi.fn();
      render(
        <CalculatedFieldEditor
          isOpen={true}
          onClose={onClose}
          onSave={() => {}}
          tables={[{ name: "users", columns: [{ name: "id", data_type: "int", is_nullable: true, is_primary: false }] }]}
        />,
      );

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("8. sqlParser JOIN alias matching", () => {
    it("resolves table aliases in JOIN ... ON clauses accurately", () => {
      const sql = `
        SELECT u.id, o.amount
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id;
      `;
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.table).toBe("users");
      expect(spec?.joins).toHaveLength(1);
      expect(spec?.joins[0].table).toBe("orders");
      expect(spec?.joins[0].left_table).toBe("users");
      expect(spec?.joins[0].left_col).toBe("id");
      expect(spec?.joins[0].right_col).toBe("user_id");
    });

    it("resolves table aliases when condition is reversed (o.user_id = u.id) with explicit AS", () => {
      const sql = `
        SELECT usr.id, ord.amount
        FROM users AS usr
        INNER JOIN orders AS ord ON ord.user_id = usr.id;
      `;
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.table).toBe("users");
      expect(spec?.joins).toHaveLength(1);
      expect(spec?.joins[0].table).toBe("orders");
      expect(spec?.joins[0].left_table).toBe("users");
      expect(spec?.joins[0].left_col).toBe("id");
      expect(spec?.joins[0].right_col).toBe("user_id");
    });
  });
});
