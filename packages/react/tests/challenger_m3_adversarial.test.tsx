import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act, renderHook } from "@testing-library/react";
import {
  useQueryBuilder,
  useQueryState,
  useSqlCompiler,
  stateToSpec,
  specToState,
  MAX_HISTORY_LENGTH,
  normalizeSchema,
  isSchemaSnapshot,
  VisualQueryBuilder,
  QueryPlayground,
  QueryCanvas,
  TableCard,
  TableFiltersEditor,
  TableJoinEditor,
  TableSortsEditor,
  QueryResultsTable,
  QueryChartPreview,
  QueryTemplateManager,
  type DatabaseSchemaDefinition,
  type SchemaSnapshot,
  type QuerySpec,
  type QueryState,
  type QueryResultData,
  type SqlDialect,
} from "../src";

describe("Milestone 3 DX Empirical Adversarial Challenge Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // =========================================================================
  // 1. Generic Schema Type Validation & Edge Cases
  // =========================================================================
  describe("1. Generic Schema Type Validation & Edge Cases", () => {
    it("handles completely empty schemas ({ tables: {} }) without throwing", () => {
      const emptySchema: DatabaseSchemaDefinition = { tables: {} };

      // Normalization
      const normalized = normalizeSchema(emptySchema);
      expect(normalized).not.toBeNull();
      expect(normalized?.tables).toEqual({});
      expect(normalized?.foreign_keys).toEqual([]);
      expect(normalized?.relationships).toEqual([]);

      // useQueryState with empty schema
      const { result: stateResult } = renderHook(() => useQueryState());
      expect(stateResult.current.state.primaryTable).toBe("");
      expect(stateResult.current.state.activeTables).toEqual([]);

      // useSqlCompiler with empty schema
      const { result: compilerResult } = renderHook(() =>
        useSqlCompiler({ table: "" }, { schema: emptySchema }),
      );
      expect(compilerResult.current.sql).toBe("");
      expect(compilerResult.current.isValid).toBe(false);

      // useQueryBuilder with empty schema
      const { result: builderResult } = renderHook(() =>
        useQueryBuilder({ schema: emptySchema }),
      );
      expect(builderResult.current.state.primaryTable).toBe("");
      expect(builderResult.current.state.activeTables).toEqual([]);

      // QueryPlayground with empty schema
      expect(() => {
        render(<QueryPlayground schema={emptySchema} />);
      }).not.toThrow();
    });

    it("handles deeply nested dot-separated column names (e.g., JSONB / struct paths)", () => {
      const nestedSpec: QuerySpec = {
        table: "events",
        columns: [
          "events.payload.metadata.geo.coordinates.lat",
          {
            column: "events.payload.user.preferences.theme.color",
            alias: "preferred_color",
            agg: "MAX",
          },
        ],
        joins: [],
        filters: [
          {
            column: "payload.metadata.geo.country",
            op: "=",
            value: "US",
            tablePrefix: "events",
          },
        ],
        order_by: [
          {
            column: "events.payload.metadata.timestamp.epoch",
            direction: "DESC",
          },
        ],
        distinct: true,
        limit: 10,
      };

      const parsedState = specToState(nestedSpec);
      expect(parsedState.primaryTable).toBe("events");
      expect(
        parsedState.selectedColumns?.["events.payload.metadata.geo.coordinates.lat"],
      ).toEqual({
        table: "events",
        name: "payload.metadata.geo.coordinates.lat",
      });
      expect(
        parsedState.selectedColumns?.[
          "events.payload.user.preferences.theme.color"
        ]?.alias,
      ).toBe("preferred_color");

      const roundtripSpec = stateToSpec(parsedState as QueryState);
      expect(roundtripSpec.columns).toContain(
        "events.payload.metadata.geo.coordinates.lat",
      );

      // Verify compiler quotes correctly without crashing on multiple dots
      const { result } = renderHook(() => useSqlCompiler(nestedSpec));
      expect(result.current.isValid).toBe(true);
      expect(result.current.sql).toContain(
        '"events"."payload.metadata.geo.coordinates.lat"',
      );
      expect(result.current.sql).toContain('AS "preferred_color"');
    });

    it("handles circular relationships without infinite loops or recursion overflow", () => {
      const circularSchema: DatabaseSchemaDefinition = {
        tables: {
          nodes: {
            columns: {
              id: { dataType: "integer", primaryKey: true },
              next_id: { dataType: "integer" },
            },
            relationships: {
              rel_next: {
                targetTable: "nodes",
                sourceColumn: "next_id",
                targetColumn: "id",
              },
            },
          },
          edges: {
            columns: {
              source_node: { dataType: "integer" },
              target_node: { dataType: "integer" },
            },
            relationships: {
              to_node: {
                targetTable: "nodes",
                sourceColumn: "target_node",
                targetColumn: "id",
              },
            },
          },
        },
      };

      const normalized = normalizeSchema(circularSchema);
      expect(normalized).not.toBeNull();
      expect(normalized?.foreign_keys.length).toBe(2);

      // Add self-referential / circular joins in hook
      const { result } = renderHook(() =>
        useQueryBuilder({ schema: circularSchema, initialTable: "nodes" }),
      );

      act(() => {
        result.current.actions.addJoin({
          id: "circle_1",
          type: "INNER JOIN",
          left_table: "nodes",
          left_col: "next_id",
          table: "nodes",
          right_col: "id",
        });
      });

      expect(result.current.compiled.sql).toContain('INNER JOIN "nodes"');
      expect(result.current.safety.valid).toBe(true);
    });

    it("handles invalid column references and phantom tables gracefully", () => {
      const { result } = renderHook(() =>
        useQueryState({
          table: "real_table",
          columns: [
            "nonexistent_table.phantom_column",
            "real_table.ghost_field",
          ],
          joins: [
            {
              table: "missing_join_target",
              left_table: "real_table",
              left_col: "unknown_fk",
              right_col: "unknown_pk",
              type: "LEFT JOIN",
            },
          ],
        }),
      );

      expect(
        result.current.state.selectedColumns[
          "nonexistent_table.phantom_column"
        ],
      ).toBeDefined();

      // Compiler should compile without throwing, even if columns are not declared in schema
      const { result: compilerResult } = renderHook(() =>
        useSqlCompiler(result.current.spec),
      );
      expect(compilerResult.current.sql).toContain(
        '"nonexistent_table"."phantom_column"',
      );
      expect(compilerResult.current.sql).toContain(
        'LEFT JOIN "missing_join_target"',
      );
    });

    it("handles Unicode, symbols, and special characters in table and column identifiers", () => {
      const specialSpec: QuerySpec = {
        table: "t_résumé 📊",
        columns: ["t_résumé 📊.col_ñ", "t_résumé 📊.field$with_spaces #1"],
        joins: [],
        filters: [],
        filter_join: "AND",
        order_by: [],
        distinct: false,
        limit: 10,
      };

      const { result } = renderHook(() => useSqlCompiler(specialSpec));
      expect(result.current.isValid).toBe(true);
      expect(result.current.sql).toContain('"t_résumé 📊"');
      expect(result.current.sql).toContain('"col_ñ"');
      expect(result.current.sql).toContain('"field$with_spaces #1"');
    });
  });

  // =========================================================================
  // 2. Headless State Management Stress: useQueryState
  // =========================================================================
  describe("2. Headless State Management Stress: useQueryState", () => {
    it("survives rapid bursts of 65+ heterogeneous state mutations cleanly", () => {
      const { result } = renderHook(() => useQueryState());

      act(() => {
        // Step 1: Set tables and primary table
        result.current.actions.setTables(["users", "orders", "audit"]);
        result.current.actions.setPrimaryTable("users");

        // Step 2: Rapid column toggles (20 operations)
        for (let i = 0; i < 10; i++) {
          result.current.actions.toggleColumn("users", `col_${i}`);
        }
        for (let i = 0; i < 5; i++) {
          result.current.actions.toggleColumn("orders", `order_col_${i}`);
        }
        for (let i = 0; i < 5; i++) {
          result.current.actions.updateColumnSelect(`users.col_${i}`, {
            alias: `renamed_${i}`,
            aggregate: i % 2 === 0 ? "COUNT" : "MAX",
          });
        }

        // Step 3: Rapid Joins (15 operations)
        for (let i = 0; i < 10; i++) {
          result.current.actions.addJoin({
            id: `join_${i}`,
            type: "LEFT JOIN",
            left_table: "users",
            left_col: "id",
            table: "orders",
            right_col: "user_id",
          });
        }
        for (let i = 0; i < 5; i++) {
          result.current.actions.updateJoin(`join_${i}`, { type: "INNER JOIN" });
        }

        // Step 4: Rapid Filters (15 operations)
        for (let i = 0; i < 10; i++) {
          result.current.actions.addFilter({
            id: `filter_${i}`,
            tablePrefix: "users",
            column: `col_${i}`,
            operator: ">=",
            value: i * 10,
          });
        }
        for (let i = 0; i < 5; i++) {
          result.current.actions.updateFilter(`filter_${i}`, { value: i * 100 });
        }

        // Step 5: Rapid Sorts (10 operations)
        for (let i = 0; i < 5; i++) {
          result.current.actions.addSort({
            id: `sort_${i}`,
            tablePrefix: "users",
            column: `col_${i}`,
            direction: "ASC",
          });
        }
        for (let i = 0; i < 5; i++) {
          result.current.actions.updateSort(`sort_${i}`, { direction: "DESC" });
        }

        // Step 6: Dialect, Limit, Offset, Distinct (5 operations)
        result.current.actions.setLimit(100);
        result.current.actions.setOffset(25);
        result.current.actions.setDistinct(true);
        result.current.actions.setDialect("snowflake");
        result.current.actions.removeColumnProjection("users.col_0");
      });

      // Total operations executed > 65
      expect(result.current.state.isDirty).toBe(true);
      expect(result.current.state.limit).toBe(100);
      expect(result.current.state.offset).toBe(25);
      expect(result.current.state.isDistinct).toBe(true);
      expect(result.current.state.dialect).toBe("snowflake");
      expect(result.current.state.joins.length).toBe(10);
      expect(result.current.state.filters.length).toBe(10);
      expect(result.current.state.sorts.length).toBe(5);
      expect(result.current.state.selectedColumns["users.col_0"]).toBeUndefined();
      expect(result.current.state.selectedColumns["users.col_1"]).toBeDefined();
    });

    it("strictly clamps undo history at MAX_HISTORY_LENGTH = 50 and handles overflow/underflow", () => {
      const { result } = renderHook(() => useQueryState());

      // Trigger 80 discrete mutations
      act(() => {
        for (let i = 1; i <= 80; i++) {
          result.current.actions.setLimit(i);
        }
      });

      expect(result.current.state.limit).toBe(80);
      // History past stack must strictly never exceed 50
      expect(result.current.history.past.length).toBe(MAX_HISTORY_LENGTH);
      expect(result.current.history.canUndo).toBe(true);
      expect(result.current.history.canRedo).toBe(false);

      // Undo 50 discrete click cycles
      for (let i = 0; i < 50; i++) {
        act(() => {
          result.current.actions.undo();
        });
      }

      // After 50 undos from 80, the oldest surviving state is 30 (80 - 50 = 30)
      expect(result.current.state.limit).toBe(30);
      expect(result.current.history.past.length).toBe(0);
      expect(result.current.history.canUndo).toBe(false);
      expect(result.current.history.canRedo).toBe(true);

      // Excessive undo should be a safe no-op
      act(() => {
        result.current.actions.undo();
        result.current.actions.undo();
      });
      expect(result.current.state.limit).toBe(30);
      expect(result.current.history.canUndo).toBe(false);

      // Redo 50 discrete click cycles
      for (let i = 0; i < 50; i++) {
        act(() => {
          result.current.actions.redo();
        });
      }
      expect(result.current.state.limit).toBe(80);
      expect(result.current.history.canRedo).toBe(false);

      // Excessive redo should be a safe no-op
      act(() => {
        result.current.actions.redo();
      });
      expect(result.current.state.limit).toBe(80);

      // Breaking the future: undo 10 times, then dispatch a new action
      for (let i = 0; i < 10; i++) {
        act(() => {
          result.current.actions.undo();
        });
      }
      expect(result.current.state.limit).toBe(70);
      expect(result.current.history.future.length).toBe(10);
      expect(result.current.history.canRedo).toBe(true);

      // New action clears future stack
      act(() => {
        result.current.actions.setLimit(999);
      });
      expect(result.current.state.limit).toBe(999);
      expect(result.current.history.future.length).toBe(0);
      expect(result.current.history.canRedo).toBe(false);
    });

    it("guarantees 100% roundtrip fidelity between stateToSpec and specToState", () => {
      const complexState: QueryState = {
        primaryTable: "billing_records",
        activeTables: ["billing_records", "organizations", "plans"],
        selectedColumns: {
          "billing_records.id": {
            table: "billing_records",
            name: "id",
          },
          "billing_records.amount": {
            table: "billing_records",
            name: "amount",
            aggregate: "SUM",
            alias: "total_revenue",
          },
          "organizations.name": {
            table: "organizations",
            name: "name",
            alias: "org_name",
          },
        },
        orderedProjectionKeys: [
          "billing_records.id",
          "billing_records.amount",
          "organizations.name",
        ],
        joins: [
          {
            id: "j_org",
            type: "INNER JOIN",
            left_table: "billing_records",
            left_col: "org_id",
            table: "organizations",
            right_col: "id",
          },
          {
            id: "j_plan",
            type: "LEFT JOIN",
            left_table: "organizations",
            left_col: "plan_id",
            table: "plans",
            right_col: "id",
          },
        ],
        filters: [
          {
            id: "f1",
            tablePrefix: "billing_records",
            column: "status",
            operator: "=",
            value: "settled",
          },
          {
            id: "f2",
            tablePrefix: "billing_records",
            column: "amount",
            operator: ">",
            value: 50,
          },
        ],
        sorts: [
          {
            id: "s1",
            tablePrefix: "billing_records",
            column: "amount",
            direction: "DESC",
          },
        ],
        isDistinct: true,
        limit: 250,
        offset: 50,
        dialect: "postgres",
        isDirty: false,
      };

      const serializedSpec = stateToSpec(complexState);
      const deserializedState = specToState(serializedSpec);
      const reSerializedSpec = stateToSpec(deserializedState as QueryState);

      // Verify serialization roundtrip fidelity
      expect(reSerializedSpec.table).toBe(serializedSpec.table);
      expect(reSerializedSpec.columns).toEqual(serializedSpec.columns);
      expect(reSerializedSpec.joins).toEqual(serializedSpec.joins);
      expect(reSerializedSpec.filters).toEqual(serializedSpec.filters);
      expect(reSerializedSpec.order_by).toEqual(serializedSpec.order_by);
      expect(reSerializedSpec.distinct).toBe(serializedSpec.distinct);
      expect(reSerializedSpec.limit).toBe(serializedSpec.limit);
    });

    it("cascades table removals: purging joins, columns, and reassigning primaryTable", () => {
      const { result } = renderHook(() => useQueryState());

      act(() => {
        result.current.actions.setTables(["alpha", "beta", "gamma"]);
        result.current.actions.setPrimaryTable("alpha");
        result.current.actions.toggleColumn("alpha", "a1");
        result.current.actions.toggleColumn("beta", "b1");
        result.current.actions.toggleColumn("gamma", "g1");
        result.current.actions.addJoin({
          id: "j_ab",
          left_table: "alpha",
          table: "beta",
          left_col: "id",
          right_col: "a_id",
          type: "INNER JOIN",
        });
        result.current.actions.addJoin({
          id: "j_bg",
          left_table: "beta",
          table: "gamma",
          left_col: "id",
          right_col: "b_id",
          type: "LEFT JOIN",
        });
      });

      expect(result.current.state.activeTables).toEqual(["alpha", "beta", "gamma"]);
      expect(result.current.state.joins.length).toBe(2);

      // Remove "beta"
      act(() => {
        result.current.actions.removeTable("beta");
      });

      // Both joins involve "beta", so both must be purged
      expect(result.current.state.activeTables).toEqual(["alpha", "gamma"]);
      expect(result.current.state.joins.length).toBe(0);
      // beta's columns must be purged
      expect(result.current.state.selectedColumns["beta.b1"]).toBeUndefined();
      expect(result.current.state.selectedColumns["alpha.a1"]).toBeDefined();
      expect(result.current.state.selectedColumns["gamma.g1"]).toBeDefined();

      // Remove primary table "alpha" -> primary must fall back to next active table "gamma"
      act(() => {
        result.current.actions.removeTable("alpha");
      });

      expect(result.current.state.primaryTable).toBe("gamma");
      expect(result.current.state.activeTables).toEqual(["gamma"]);
      expect(result.current.state.selectedColumns["alpha.a1"]).toBeUndefined();
    });
  });

  // =========================================================================
  // 3. Headless Compiler Stress: useSqlCompiler
  // =========================================================================
  describe("3. Headless Compiler Stress: useSqlCompiler", () => {
    it("handles debounce cancellations during high-frequency spec updates", () => {
      vi.useFakeTimers();

      let specCounter = 0;
      const makeSpec = (num: number): QuerySpec => ({
        table: "logs",
        columns: [`logs.message_${num}`],
        joins: [],
        filters: [],
        filter_join: "AND",
        order_by: [],
        distinct: false,
        limit: num,
      });

      const { result, rerender } = renderHook(
        ({ spec }) => useSqlCompiler(spec, { debounceMs: 150 }),
        { initialProps: { spec: makeSpec(0) } },
      );

      expect(result.current.sql).toContain("LIMIT 0");

      // Rapidly fire 10 updates within 50ms (well under debounceMs of 150ms)
      for (let i = 1; i <= 10; i++) {
        specCounter = i;
        rerender({ spec: makeSpec(i) });
        act(() => {
          vi.advanceTimersByTime(5);
        });
      }

      // Should still be compiling intermediate state
      expect(result.current.isCompiling).toBe(true);

      // Advance timers by remaining 150ms
      act(() => {
        vi.advanceTimersByTime(150);
      });

      expect(result.current.isCompiling).toBe(false);
      // Output SQL must reflect the 10th spec, not intermediate ones
      expect(result.current.sql).toContain("LIMIT 10");
      expect(result.current.sql).toContain('"logs"."message_10"');
    });

    it("verifies identifier escaping across all 7 supported SQL dialects", () => {
      const spec: QuerySpec = {
        table: "accounts",
        columns: ["accounts.user_name"],
        joins: [],
        filters: [],
        filter_join: "AND",
        order_by: [],
        distinct: false,
        limit: 5,
      };

      const dialects: { dialect: SqlDialect; expectedToken: string }[] = [
        { dialect: "postgres", expectedToken: '"accounts"."user_name"' },
        { dialect: "mysql", expectedToken: "`accounts`.`user_name`" },
        { dialect: "sqlite", expectedToken: '"accounts"."user_name"' },
        { dialect: "snowflake", expectedToken: '"accounts"."user_name"' },
        { dialect: "bigquery", expectedToken: "`accounts`.`user_name`" },
        { dialect: "duckdb", expectedToken: '"accounts"."user_name"' },
        { dialect: "mssql", expectedToken: "[accounts].[user_name]" },
      ];

      for (const { dialect, expectedToken } of dialects) {
        const { result } = renderHook(() => useSqlCompiler(spec, { dialect }));
        expect(result.current.sql).toContain(expectedToken);
        expect(result.current.dialect).toBe(dialect);
      }
    });

    it("catches AST safety violations on malicious inputs and stacked queries", () => {
      const attacks = [
        "users; DROP TABLE sensitive_data;",
        "users; EXEC sp_executesql 'SELECT 1';",
        "auth_user",
        "django_session",
        "pg_shadow",
        "sqlite_master",
      ];

      for (const badTable of attacks) {
        const { result } = renderHook(() =>
          useSqlCompiler({
            table: badTable,
            columns: [`${badTable}.id`],
          }),
        );

        expect(result.current.safety.valid).toBe(false);
        expect(result.current.isValid).toBe(false);
        expect(result.current.safety.violations.length).toBeGreaterThan(0);
      }
    });

    it("generates correct count query wrapping with clean semicolon handling", () => {
      const specWithSemicolon: QuerySpec = {
        table: "customers",
        columns: ["customers.id"],
        joins: [],
        filters: [{ column: "customers.active", op: "=", value: true }],
        filter_join: "AND",
        order_by: [{ column: "customers.id", direction: "ASC" }],
        distinct: true,
        limit: 50,
      };

      const { result } = renderHook(() => useSqlCompiler(specWithSemicolon));

      expect(result.current.countSql).toMatch(/^SELECT COUNT\(\*\) FROM \(/);
      expect(result.current.countSql).toContain("DISTINCT");
      expect(result.current.countSql).toMatch(/\) AS count_wrapper;$/);
      // Ensure no trailing internal semicolon inside subquery
      expect(result.current.countSql).not.toContain(";;");
    });
  });

  // =========================================================================
  // 4. Zero-CSS Unstyled Mode Stress Across ALL 10 Components
  // =========================================================================
  describe("4. Zero-CSS Unstyled Mode Stress Across ALL 10 Components", () => {
    const mockSchema: SchemaSnapshot = {
      tables: {
        products: {
          name: "products",
          columns: [
            { name: "id", data_type: "int", is_nullable: false, is_primary: true },
            { name: "name", data_type: "varchar", is_nullable: false, is_primary: false },
          ],
        },
      },
    };

    const mockResults: QueryResultData = {
      columns: ["id", "name"],
      rows: [{ id: 1, name: "Widget" }],
      count: 1,
    };

    it("Component 1: VisualQueryBuilder has no default inline styles when unstyled={true}", () => {
      const { container } = render(
        <VisualQueryBuilder schema={mockSchema} initialTable="products" unstyled={true} />,
      );
      const root = container.querySelector('[data-qb="root"]');
      expect(root).not.toBeNull();
      expect(root?.getAttribute("data-qb-unstyled")).toBe("true");
      expect(root?.getAttribute("style")).toBeNull();
    });

    it("Component 2: QueryPlayground has no default inline styles when unstyled={true}", () => {
      const { container } = render(
        <QueryPlayground schema={mockSchema} unstyled={true} />,
      );
      const root = container.querySelector('[data-qb="playground-root"]');
      expect(root).not.toBeNull();
      expect(root?.getAttribute("data-qb-unstyled")).toBe("true");
      expect(root?.getAttribute("style")).toBeNull();
    });

    it("Component 3: QueryCanvas has no default inline styles when unstyled={true}", () => {
      const { container } = render(
        <QueryCanvas
          schema={mockSchema}
          activeTables={[mockSchema.tables.products]}
          primaryTable="products"
          selectedColumns={{}}
          orderedProjectionKeys={[]}
          joins={[]}
          filters={[]}
          sorts={[]}
          isDistinct={false}
          limit={50}
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
          unstyled={true}
        />,
      );
      const canvas = container.querySelector('[data-qb="canvas"]');
      expect(canvas).not.toBeNull();
      expect(canvas?.getAttribute("style")).toBeNull();
    });

    it("Component 4: TableCard has no default inline styles when unstyled={true}", () => {
      const { container } = render(
        <TableCard
          table={mockSchema.tables.products}
          selectedColumns={{}}
          onToggleColumn={() => {}}
          unstyled={true}
        />,
      );
      const card = container.querySelector('[data-qb="table-card"]');
      expect(card).not.toBeNull();
      expect(card?.getAttribute("style")).toBeNull();
    });

    it("Component 5: TableFiltersEditor has no default inline styles when unstyled={true}", () => {
      const { container } = render(
        <TableFiltersEditor
          filters={[]}
          activeTables={[mockSchema.tables.products]}
          onChange={() => {}}
          unstyled={true}
        />,
      );
      const editor = container.querySelector('[data-qb="filters-editor"]');
      expect(editor).not.toBeNull();
      expect(editor?.getAttribute("style")).toBeNull();
    });

    it("Component 6: TableJoinEditor has no default inline styles when unstyled={true}", () => {
      const { container } = render(
        <TableJoinEditor
          joins={[]}
          activeTables={[mockSchema.tables.products]}
          allTables={[mockSchema.tables.products]}
          onChange={() => {}}
          unstyled={true}
        />,
      );
      const editor = container.querySelector('[data-qb="joins-editor"]');
      expect(editor).not.toBeNull();
      expect(editor?.getAttribute("style")).toBeNull();
    });

    it("Component 7: TableSortsEditor has no default inline styles when unstyled={true}", () => {
      const { container } = render(
        <TableSortsEditor
          sorts={[]}
          activeTables={[mockSchema.tables.products]}
          onChange={() => {}}
          unstyled={true}
        />,
      );
      const editor = container.querySelector('[data-qb="sorts-editor"]');
      expect(editor).not.toBeNull();
      expect(editor?.getAttribute("style")).toBeNull();
    });

    it("Component 8: QueryResultsTable has no default inline styles when unstyled={true}", () => {
      const { container } = render(
        <QueryResultsTable results={mockResults} unstyled={true} />,
      );
      const root = container.querySelector('[data-qb="results-table-root"]');
      expect(root).not.toBeNull();
      expect(root?.getAttribute("style")).toBeNull();
    });

    it("Component 9: QueryChartPreview has no default inline styles when unstyled={true}", () => {
      const { container } = render(
        <QueryChartPreview results={mockResults} unstyled={true} />,
      );
      const root = container.querySelector('[data-qb="chart-preview-root"]');
      expect(root).not.toBeNull();
      expect(root?.getAttribute("style")).toBeNull();
    });

    it("Component 10: QueryTemplateManager has no default inline styles when unstyled={true}", () => {
      const { container } = render(
        <QueryTemplateManager
          isOpen={true}
          onClose={() => {}}
          onLoadTemplate={() => {}}
          unstyled={true}
        />,
      );
      const backdrop = container.querySelector('[data-qb="modal-backdrop"]');
      expect(backdrop).not.toBeNull();
      expect(backdrop?.getAttribute("style")).toBeNull();
    });

    it("preserves explicit user-provided custom style and className when unstyled={true}", () => {
      const { container } = render(
        <QueryPlayground
          schema={mockSchema}
          unstyled={true}
          className="custom-tailwind-class"
          style={{ marginTop: "24px" }}
        />,
      );
      const root = container.querySelector('[data-qb="playground-root"]');
      expect(root?.classList.contains("custom-tailwind-class")).toBe(true);
      expect(root?.getAttribute("style")).toBe("margin-top: 24px;");
    });
  });

  // =========================================================================
  // 5. QueryPlayground Interactive Stress & Error Resilience
  // =========================================================================
  describe("5. QueryPlayground Component Stress", () => {
    const playgroundSchema: SchemaSnapshot = {
      tables: {
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "int", is_nullable: false, is_primary: true },
            { name: "email", data_type: "varchar", is_nullable: false, is_primary: false },
          ],
        },
        orders: {
          name: "orders",
          columns: [
            { name: "id", data_type: "int", is_nullable: false, is_primary: true },
            { name: "amount", data_type: "decimal", is_nullable: false, is_primary: false },
          ],
        },
      },
    };

    it("synchronizes visual controls and live JSON spec bidirectionally", () => {
      render(<QueryPlayground schema={playgroundSchema} initialTable="users" />);

      // 1. Visual modification: select table orders
      const selectPrimary = screen.getByLabelText("Select Primary Table");
      act(() => {
        fireEvent.change(selectPrimary, { target: { value: "orders" } });
      });

      // 2. Switch to JSON tab -> verify table is orders
      const jsonSubtab = screen.getByText("Live JSON Spec");
      act(() => {
        fireEvent.click(jsonSubtab);
      });

      const textarea = screen.getByLabelText("JSON Query Spec Editor") as HTMLTextAreaElement;
      expect(textarea.value).toContain('"table": "orders"');

      // 3. Edit JSON textarea directly: change limit to 77
      const updatedJson = JSON.parse(textarea.value);
      updatedJson.limit = 77;
      act(() => {
        fireEvent.change(textarea, { target: { value: JSON.stringify(updatedJson, null, 2) } });
      });

      // 4. Switch back to Visual tab -> verify limit input updated
      const visualSubtab = screen.getByText("Visual Controls");
      act(() => {
        fireEvent.click(visualSubtab);
      });

      const limitInput = screen.getByLabelText("Limit rows") as HTMLInputElement;
      expect(limitInput.value).toBe("77");
    });

    it("handles invalid JSON syntax without crashing and recovers gracefully", () => {
      render(<QueryPlayground schema={playgroundSchema} initialTable="users" />);

      const jsonSubtab = screen.getByText("Live JSON Spec");
      act(() => {
        fireEvent.click(jsonSubtab);
      });

      const textarea = screen.getByLabelText("JSON Query Spec Editor") as HTMLTextAreaElement;

      // Enter completely broken JSON
      act(() => {
        fireEvent.change(textarea, { target: { value: '{"table": "users", BROKEN_JSON' } });
      });

      // Component must display syntax error alert
      const alert = screen.getByRole("alert");
      expect(alert).toBeDefined();
      expect(alert.textContent).toContain("Syntax Error:");

      // Fix JSON
      act(() => {
        fireEvent.change(textarea, {
          target: { value: JSON.stringify({ table: "users", limit: 33 }) },
        });
      });

      // Alert must disappear
      expect(screen.queryByRole("alert")).toBeNull();
    });

    it("safely handles clipboard API failures and permissions rejection", async () => {
      // Mock clipboard writeText to reject
      const writeTextMock = vi.fn().mockRejectedValue(new Error("Clipboard permission denied"));
      Object.assign(navigator, {
        clipboard: {
          writeText: writeTextMock,
        },
      });

      render(<QueryPlayground schema={playgroundSchema} initialTable="users" />);

      const codegenTab = screen.getByText("Code Generation");
      act(() => {
        fireEvent.click(codegenTab);
      });

      const copyBtn = screen.getByText("📋 Copy Snippet");

      // Clicking must not throw uncaught error
      await act(async () => {
        fireEvent.click(copyBtn);
      });

      expect(writeTextMock).toHaveBeenCalled();
      // UI remains active and doesn't crash
      expect(screen.getByText("Code Generation")).toBeDefined();
    });

    it("safely handles environments where navigator.clipboard is undefined", async () => {
      // Temporarily remove clipboard
      const originalClipboard = (navigator as any).clipboard;
      delete (navigator as any).clipboard;

      render(<QueryPlayground schema={playgroundSchema} initialTable="users" />);

      const codegenTab = screen.getByText("Code Generation");
      act(() => {
        fireEvent.click(codegenTab);
      });

      const copyBtn = screen.getByText("📋 Copy Snippet");

      // Clicking without clipboard must be safe no-op
      await act(async () => {
        fireEvent.click(copyBtn);
      });

      expect(screen.getByText("Code Generation")).toBeDefined();

      // Restore clipboard
      if (originalClipboard) {
        Object.assign(navigator, { clipboard: originalClipboard });
      }
    });

    it("disables all visual and JSON controls when readOnly={true}", () => {
      render(
        <QueryPlayground
          schema={playgroundSchema}
          initialTable="users"
          readOnly={true}
        />,
      );

      const tableSelect = screen.getByLabelText("Select Primary Table") as HTMLSelectElement;
      expect(tableSelect.disabled).toBe(true);

      const distinctCheckbox = screen.getByRole("checkbox", { name: "DISTINCT" }) as HTMLInputElement;
      expect(distinctCheckbox.disabled).toBe(true);

      const limitInput = screen.getByLabelText("Limit rows") as HTMLInputElement;
      expect(limitInput.disabled).toBe(true);

      // JSON textarea also disabled
      const jsonSubtab = screen.getByText("Live JSON Spec");
      act(() => {
        fireEvent.click(jsonSubtab);
      });
      const textarea = screen.getByLabelText("JSON Query Spec Editor") as HTMLTextAreaElement;
      expect(textarea.disabled).toBe(true);
    });
  });

  // =========================================================================
  // 6. Stress Edge Cases: Caps, Escaping & Batch History Dynamics
  // =========================================================================
  describe("6. Stress Edge Cases: Caps, Escaping & Batch History Dynamics", () => {
    it("safely escapes single quotes in filter values to prevent SQL breakout", () => {
      const maliciousValue = "admin' OR '1'='1' --";
      const spec: QuerySpec = {
        table: "users",
        columns: ["users.id"],
        joins: [],
        filters: [
          {
            column: "username",
            op: "=",
            value: maliciousValue,
            tablePrefix: "users",
          },
        ],
        filter_join: "AND",
        order_by: [],
        distinct: false,
        limit: 10,
      };

      const { result } = renderHook(() => useSqlCompiler(spec));
      expect(result.current.isValid).toBe(true);
      // The single quotes must be doubled up: 'admin'' OR ''1''=''1'' --'
      expect(result.current.sql).toContain("'admin'' OR ''1''=''1'' --'");
      expect(result.current.safety.valid).toBe(true);
    });

    it("compiler enforces safe upper bounds (caps joins at 20, filters at 50, sorts at 20)", () => {
      const hugeSpec: QuerySpec = {
        table: "base_table",
        columns: ["base_table.id"],
        joins: Array.from({ length: 40 }, (_, i) => ({
          table: `joined_${i}`,
          type: "LEFT JOIN",
          left_col: "id",
          right_col: "base_id",
        })),
        filters: Array.from({ length: 80 }, (_, i) => ({
          column: `col_${i}`,
          op: "=",
          value: i,
          tablePrefix: "base_table",
        })),
        filter_join: "AND",
        order_by: Array.from({ length: 35 }, (_, i) => ({
          column: `base_table.col_${i}`,
          direction: "ASC" as const,
        })),
        distinct: false,
        limit: 10,
      };

      const { result } = renderHook(() => useSqlCompiler(hugeSpec));
      expect(result.current.isValid).toBe(true);
      // In compiler.ts: joins capped to 20, filters capped to 50, sorts capped to 20
      expect(result.current.ast?.joins.length).toBe(20);
      expect(result.current.ast?.filters.length).toBe(50);
      expect(result.current.ast?.order_by.length).toBe(20);
    });

    it("verifies synchronous batch undo capture in a single render vs discrete render cycles", () => {
      const { result } = renderHook(() => useQueryState());

      act(() => {
        result.current.actions.setLimit(10);
        result.current.actions.setLimit(20);
        result.current.actions.setLimit(30);
      });

      expect(result.current.state.limit).toBe(30);
      expect(result.current.history.past.length).toBe(3);

      // Discrete undo cycle: 1 step per act()
      act(() => {
        result.current.actions.undo();
      });
      expect(result.current.state.limit).toBe(20);
      expect(result.current.history.future.length).toBe(1);

      act(() => {
        result.current.actions.undo();
      });
      expect(result.current.state.limit).toBe(10);
      expect(result.current.history.future.length).toBe(2);

      // Discrete redo cycle: 1 step per act()
      act(() => {
        result.current.actions.redo();
      });
      expect(result.current.state.limit).toBe(20);
      expect(result.current.history.future.length).toBe(1);
    });
  });
});
