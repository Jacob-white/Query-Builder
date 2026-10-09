import React, { createRef } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, renderHook, act } from "@testing-library/react";

import { toDrizzle } from "../src/adapters/drizzle";
import { toPrisma } from "../src/adapters/prisma";
import { toSqlAlchemy } from "../src/adapters/sqlalchemy";
import { extractSnapshotData } from "../src/adapters/utils";

import { autoHealClientQuerySpec } from "../src/ai/selfHealing";
import { executeAgentToolCall } from "../src/ai/tools";
import { createQueryBuilderClient, createQuery, FluentQuery } from "../src/client";
import * as byoHook from "../src/hooks/useBringYourOwnAi";
import * as localIngest from "../src/utils/localDataIngest";

import { AiAssistantWidget } from "../src/components/AiAssistantWidget";
import { BiChartVisualizer } from "../src/components/BiChartVisualizer";
import { CalculatedFieldEditor } from "../src/components/CalculatedFieldEditor";
import { DashboardWorkbench } from "../src/components/DashboardWorkbench";
import { VisualQueryBuilder, VisualQueryBuilderRef } from "../src/components/VisualQueryBuilder";
import { WindowFunctionBuilder } from "../src/components/WindowFunctionBuilder";

import { QueryBuilder, useCompoundQueryBuilder } from "../src/components/compound";

import { InMemoryOlapEngine, evaluateCondition, getClientOlapEngine } from "../src/drivers/duckdbDriver";
import { useClientOlap } from "../src/hooks/useClientOlap";
import { useDashboardManager } from "../src/hooks/useDashboardManager";
import { useQueryState } from "../src/hooks/useQueryState";
import { ThemeProvider } from "../src/theme/ThemeProvider";
import { darkTheme, lightTheme } from "../src/theme/tokens";
import { compileVisualState, compileSpecToSql } from "../src/utils/compiler";
import type { ByoAiSchema } from "../src/ai/types";
import type { ExecuteAgentToolOptions } from "../src/ai/tools";
import type { QueryBuilderClient } from "../src/client";
import type { AiAssistantWidgetProps } from "../src/components/AiAssistantWidget";
import type {
  ColumnMeta,
  DashboardTile,
  DashboardTileLayout,
  FeatureConfig,
  QueryPlanNode,
  QueryResultData,
  QuerySpec,
  SchemaSnapshot,
  TableSchema,
  VisualColumnSelect,
  VisualQueryBuilderProps,
  WindowFunctionSpec,
} from "../src/types";
import { invalid } from "./helpers";
import { asMock, loose, olapTableData } from "./helpers/loose";

describe("Comprehensive 100% Coverage Final Step", () => {
  describe("Adapters: Drizzle, Prisma, SQLAlchemy, Utils", () => {
    it("drizzle: handles postgres types, non-int PKs, and sqlite composite PKs", () => {
      const schema = {
        tables: {
          metrics: {
            columns: [
              { name: "pk_text", dataType: "text", isPrimary: true },
              { name: "b_int", dataType: "bigint" },
              { name: "fl", dataType: "float" },
              { name: "dec", dataType: "decimal" },
              { name: "dt", dataType: "timestamp" },
            ],
          },
          composite_pk_tbl: {
            columns: [
              { name: "id1", dataType: "int", isPrimary: true },
              { name: "id2", dataType: "text", isPrimary: true },
            ],
          },
        },
      };
      const resPg = toDrizzle(schema, { dialect: "postgres" });
      expect(resPg).toContain('text("pk_text").primaryKey()');
      expect(resPg).toContain('bigint("b_int", { mode: "number" })');
      expect(resPg).toContain('doublePrecision("fl")');
      expect(resPg).toContain('numeric("dec")');
      expect(resPg).toContain('timestamp("dt")');

      const resSqlite = toDrizzle(schema, { dialect: "sqlite" });
      expect(resSqlite).toBeDefined();
    });

    it("prisma: handles nullable relations, self-relations, multi-relations, and missing data types", () => {
      const schema = {
        tables: {
          items: {
            columns: [
              { name: "id", dataType: "int", isPrimary: true },
              { name: "title" }, // no dataType -> defaults to "text"
              { name: "parent_id", dataType: "int", isNullable: true },
              { name: "alt_parent_id", dataType: "int", isNullable: true },
            ],
            foreignKeys: [
              { table: "items", column: "parent_id", foreign_table: "items", foreign_column: "id" },
              { table: "items", column: "alt_parent_id", foreign_table: "items", foreign_column: "id" },
            ],
          },
          standalone: {
            columns: [{ name: "id", dataType: "int", isPrimary: true }],
          },
        },
      };
      const res = toPrisma(schema);
      expect(res).toContain("title String?");
      expect(res).toContain("parent Items?");
      expect(res).toContain("childItemsByParentId");
      expect(res).toContain("model Standalone");
    });

    it("sqlalchemy: handles tables without FKs and columns without data types", () => {
      const schema = {
        tables: {
          users: {
            columns: [
              { name: "id", dataType: "int", isPrimary: true },
              { name: "notes" }, // no dataType
            ],
          },
        },
      };
      const res = toSqlAlchemy(schema);
      expect(res).toContain("notes = Column(Text");
    });

    it("extractSnapshotData: handles malformed objects, non-arrays, and missing column names", () => {
      const rawArray = [
        {
          name: "users",
          columns: ["id", { name: "name", dataType: "text" }, { dataType: "text" }],
          foreign_keys: [null, { table: "users", column: "org_id", foreign_table: "orgs", foreign_column: "id" }],
        },
        {
          name: "empty_fks",
          columns: [],
        },
      ];
      const extArray = extractSnapshotData(invalid<TableSchema[]>(rawArray));
      expect(extArray.tables.users).toBeDefined();

      const rawObj = {
        tables: {
          users: {
            columns: "not_an_array",
          },
          invalid_val: null,
        },
        foreignKeys: [{ table: "users", column: "x", foreignTable: "y", foreignColumn: "id" }],
        foreign_keys: [{ table: "users", column: "z", foreign_table: "y", foreign_column: "id" }],
      };
      const extObj = extractSnapshotData(rawObj);
      expect(extObj.tables.users.columns).toEqual([]);
      expect(extObj.foreignKeys.length).toBeGreaterThan(0);
    });
  });

  describe("AI & Client", () => {
    it("covers selfHealing and tools gap branches", () => {
      const healed = autoHealClientQuerySpec(
        {
          table: "orders",
          columns: ["orders.id", "users.name"],
        },
        invalid<ByoAiSchema>({
          tables: {
            orders: {},
            users: {
              foreignKeys: [
                { target_table: "orders", target_column: "id", column: "user_id" },
              ],
            },
          },
        }),
      );
      expect(healed.healedSpec.joins).toBeDefined();

      const resNum = executeAgentToolCall("get_schema_catalog", "123");
      expect(resNum.success).toBe(true);

      const resBad = executeAgentToolCall("get_schema_catalog", "{invalid");
      expect(resBad.success).toBe(false);

      const resExplain = executeAgentToolCall(
        "explain_query",
        JSON.stringify({ spec: { table: "orders" } }),
      );
      expect(resExplain.success).toBe(true);

      const resValidate = executeAgentToolCall(
        "validate_and_compile_query",
        JSON.stringify({
          spec: { table: "orders", columns: ["orders.id", "users.name"] },
        }),
        {
          schema: invalid<ExecuteAgentToolOptions["schema"]>({
            tables: {
              orders: {},
              users: {
                foreign_keys: [{ target_table: "orders", target_column: "id", column: "order_id" }],
              },
            },
          }),
        },
      );
      expect(resValidate.success).toBe(true);
      expect(resValidate.warnings).toBeDefined();
    });

    it("client: covers from, join without JOIN suffix, execute without client, and custom headers object", async () => {
      const fq = createQuery("users").from("accounts").join("orders", "user_id", "=", "id", "INNER");
      expect(fq.toSpec().table).toBe("accounts");
      expect(fq.toSpec().joins[0].type).toBe("INNER JOIN");

      await expect(createQuery("users").execute()).rejects.toThrow(/FluentQuery: No client provided/);

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ rows: [], columns: [], row_count: 0 }),
      });
      const client = createQueryBuilderClient({
        baseUrl: "https://api.example.com",
        headers: { "X-Test-Header": "CustomVal" },
        fetchFn: mockFetch,
      });
      await client.execute(loose<QuerySpec>({ table: "users" }));
      expect(mockFetch).toHaveBeenCalled();
      const headersUsed = mockFetch.mock.calls[0][1].headers;
      expect(headersUsed["X-Test-Header"]).toBe("CustomVal");
    });
  });

  describe("Components", () => {
    it("DashboardWorkbench: covers KPI, Pivot, overlay close, cancel close, and unstyled mode", () => {
      const { unmount } = render(
        <DashboardWorkbench
          initialState={{
            id: "d1",
            title: "Test Dashboard",
            tiles: [],
          }}
          unstyled={true}
        />,
      );
      const addFirstBtn = screen.getByText("Create First Tile");
      fireEvent.click(addFirstBtn);

      const overlay = screen.getByTestId("add-tile-modal-overlay");
      fireEvent.click(overlay);

      fireEvent.click(screen.getByText("Create First Tile"));
      const cancelBtn = screen.getByText("Cancel");
      fireEvent.click(cancelBtn);

      fireEvent.click(screen.getByText("Create First Tile"));
      const typeSelect = screen.getByTestId("new-tile-type-select");
      fireEvent.change(typeSelect, { target: { value: "kpi" } });
      const titleInput = screen.getByTestId("new-tile-title-input");
      fireEvent.change(titleInput, { target: { value: "Sales KPI" } });
      fireEvent.click(screen.getByTestId("confirm-add-tile-btn"));

      fireEvent.click(screen.getByTestId("add-tile-btn"));
      const typeSelect2 = screen.getByTestId("new-tile-type-select");
      fireEvent.change(typeSelect2, { target: { value: "pivot" } });
      const titleInput2 = screen.getByTestId("new-tile-title-input");
      fireEvent.change(titleInput2, { target: { value: "Sales Pivot" } });
      fireEvent.click(screen.getByTestId("confirm-add-tile-btn"));

      unmount();
    });

    it("BiChartVisualizer: category fallback and bar button", () => {
      const onTypeChange = vi.fn();
      render(
        <BiChartVisualizer
          results={loose<QueryResultData>({ columns: ["cat", "val"], rows: [{ cat: null, val: 10 }] })}
          defaultCategoryCol="cat"
          defaultMetricCol="val"
          defaultAggregation="NONE"
          chartType="line"
          onChartTypeChange={onTypeChange}
        />,
      );
      expect(screen.getByText(/Row 1/)).toBeDefined();
      const barBtn = screen.getByLabelText("Bar Chart");
      fireEvent.click(barBtn);
      expect(onTypeChange).toHaveBeenCalledWith("bar");
    });

    it("CalculatedFieldEditor: empty alias return and type switch", () => {
      const onSave = vi.fn();
      render(
        <CalculatedFieldEditor
          isOpen={true}
          onClose={() => {}}
          tables={[]}
          initialField={{ id: "c1", name: "", alias: "", type: "expression", expression: "1 + 1" }}
          onSave={onSave}
        />,
      );
      const caseWhenRadio = screen.getByLabelText(/CASE WHEN Conditional/i);
      fireEvent.click(caseWhenRadio);

      const submitBtn = screen.getByText("Save Column");
      fireEvent.click(submitBtn);
      expect(onSave).not.toHaveBeenCalled();
    });

    it("WindowFunctionBuilder: empty columns display", () => {
      render(
        <WindowFunctionBuilder
          isOpen={true}
          onClose={() => {}}
          onSave={() => {}}
          availableColumns={[]}
        />,
      );
      expect(screen.getByText("No columns available")).toBeDefined();
    });

    it("AiAssistantWidget: clicking suggestion when generating", () => {
      render(
        <AiAssistantWidget
          {...invalid<AiAssistantWidgetProps>({
            aiState: {
              isGenerating: true,
              messages: [{ id: "m1", sender: "ai", text: "Hello", timestamp: 123 }],
              error: null,
            },
          })}
        />,
      );
      const launcher = screen.getByTestId("ai-widget-launcher");
      fireEvent.click(launcher);
      const sugg = screen.getByTestId("ai-suggestion-0");
      fireEvent.click(sugg);
    });

    it("VisualQueryBuilder: client capability handling, schema failure, and ref execute", async () => {
      const mockClientSchemaRejects = asMock<QueryBuilderClient>({
        getSchema: vi.fn().mockRejectedValue(new Error("Schema load failed")),
        getCapabilities: vi.fn().mockResolvedValue({ window_functions: "true" }),
      });
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const { unmount } = render(
        <VisualQueryBuilder
          client={mockClientSchemaRejects}
          initialTable="users"
        />,
      );
      await act(async () => {
        await new Promise((r) => setTimeout(r, 50));
      });
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining("Failed to auto-fetch schema from client:"),
        expect.any(Error),
      );
      unmount();

      const mockClientCapRejects = asMock<QueryBuilderClient>({
        getSchema: vi.fn().mockResolvedValue({ tables: {} }),
        getCapabilities: vi.fn().mockRejectedValue(new Error("Caps failed")),
      });
      const { unmount: unmount2 } = render(
        <VisualQueryBuilder
          client={mockClientCapRejects}
          initialTable="users"
        />,
      );
      await act(async () => {
        await new Promise((r) => setTimeout(r, 50));
      });
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining("Failed to auto-fetch capabilities from client:"),
        expect.any(Error),
      );
      unmount2();
      warnSpy.mockRestore();
    });

    it("VisualQueryBuilder: clear advanced clauses, ref.execute, and shortcut", async () => {
      const ref = createRef<VisualQueryBuilderRef>();
      const onExecute = vi.fn().mockResolvedValue({ rows: [], columns: [], row_count: 0 });

      const initialSpec = invalid<QuerySpec>({
        table: "orders",
        columns: [
          { column: "orders.id" },
          { column: "orders.doubled", raw_expression: "orders.id * 2", alias: "doubled" },
        ],
        ctes: [{ name: "my_cte", query: { columns: ["id", "val"] } }],
        semantic_models: [{ name: "orders", tableName: "orders", metrics: [] }],
      });

      const schema = {
        tables: {
          orders: {
            name: "orders",
            columns: [{ name: "id", data_type: "int" }],
          },
        },
      };

      const { unmount } = render(
        <VisualQueryBuilder
          ref={ref}
          schema={invalid<SchemaSnapshot>(schema)}
          initialSpec={initialSpec}
          advancedMode={false}
          features={{ ctes: "advanced", calculated_fields: "advanced" }}
          semanticModels={[{ name: "orders", tableName: "orders", metrics: [] }]}
          onExecuteQuery={onExecute}
        />,
      );

      const clearBtn = screen.getByTestId("btn-clear-advanced-clauses");
      fireEvent.click(clearBtn);

      await act(async () => {
        await ref.current?.execute();
      });
      expect(onExecute).toHaveBeenCalled();

      fireEvent.keyDown(window, { key: "z", ctrlKey: true, shiftKey: true });

      const pipelineTab = document.getElementById("tab-pipeline");
      if (pipelineTab) {
        fireEvent.keyDown(pipelineTab, { key: "ArrowRight" });
      }

      unmount();
    });

    it("compound: QueryBuilderColumns unstyled, QueryBuilderRoot custom theme, and client auto-load", async () => {
      const { unmount: u1 } = render(
        <QueryBuilder initialSpec={loose<QuerySpec>({ table: "users", columns: [] })}>
          <QueryBuilder.Columns unstyled={true} />
        </QueryBuilder>,
      );
      expect(screen.getByText(/No columns selected/)).toBeDefined();
      u1();

      const compRef = createRef<VisualQueryBuilderRef>();
      const mockClient = asMock<QueryBuilderClient>({
        getSchema: vi.fn().mockResolvedValue({ tables: { orders: { name: "orders", columns: [] } } }),
        execute: vi.fn().mockResolvedValue({ rows: [], columns: [], row_count: 0 }),
      });

      const { unmount: u2 } = render(
        <QueryBuilder
          ref={compRef}
          theme={{ ...darkTheme, colors: { ...darkTheme.colors, background: "#000" } }}
          client={mockClient}
          initialTable="orders"
          initialSpec={loose<QuerySpec>({ table: "" })}
        >
          <QueryBuilder.Canvas classNames={{ canvasEmpty: "my-empty" }} />
          <QueryBuilder.SqlEditor classNames={{ sqlSyncBadge: "my-sync-badge" }} />
        </QueryBuilder>,
      );

      await act(async () => {
        await new Promise((r) => setTimeout(r, 50));
      });

      await act(async () => {
        await compRef.current?.execute();
      });
      expect(mockClient.execute).toHaveBeenCalled();
      u2();
    });
  });

  describe("Drivers & Hooks", () => {
    it("duckdbDriver: covers condition evaluators, null sorting, CSV short rows, and header-only CSV", async () => {
      const engine = new InMemoryOlapEngine();

      expect(evaluateCondition({ name: null }, "name", "LIKE", "%test%")).toBe(false);
      expect(evaluateCondition({ name: null }, "name", "ILIKE", "%test%")).toBe(false);
      expect(evaluateCondition({ id: 1 }, "id", "IN", [1, 2])).toBe(true);
      expect(evaluateCondition({ id: 3 }, "id", "NOT IN", [1, 2])).toBe(true);
      expect(evaluateCondition({ id: 1 }, "id", "CUSTOM_OP", 1)).toBe(true);

      await engine.ingestJson("users", [
        { id: 1, name: "Alice", role: "admin", val: "not_a_number" },
        { id: 2, name: "Bob", role: "user", val: "not_a_number" },
      ]);
      const qDouble = await engine.query('SELECT * FROM users WHERE name = "Alice"');
      expect(qDouble.rowCount).toBe(1);

      const qOther = await engine.query("FROM users");
      expect(qOther).toBeDefined();

      const qAgg = await engine.query("SELECT role, AVG(val), MIN(val), MAX(val) FROM users GROUP BY role");
      expect(qAgg.rowCount).toBe(2);

      const qAsc = await engine.query("SELECT * FROM users ORDER BY val ASC");
      expect(qAsc.rowCount).toBe(2);
      const qDesc = await engine.query("SELECT * FROM users ORDER BY val DESC");
      expect(qDesc.rowCount).toBe(2);

      await engine.ingestCsv("short_csv", "id,name,role\n1,Alice\n2,Bob,user");
      const qShort = await engine.query("SELECT * FROM short_csv");
      expect(qShort.rowCount).toBe(2);

      await engine.ingestCsv("header_only", "id,name,role\n");
      const qHeader = await engine.query("SELECT * FROM header_only");
      expect(qHeader.rowCount).toBe(0);
    });

    it("useClientOlap: handles non-Error rejections", async () => {
      const engine = getClientOlapEngine();
      const csvSpy = vi.spyOn(engine, "ingestCsv").mockRejectedValue("string csv error");
      const jsonSpy = vi.spyOn(engine, "ingestJson").mockRejectedValue("string json error");
      const regSpy = vi.spyOn(engine, "registerBackendResults").mockRejectedValue("string reg error");
      const qSpy = vi.spyOn(engine, "query").mockRejectedValue("string query error");
      const dropSpy = vi.spyOn(engine, "dropTable").mockRejectedValue("string drop error");
      const clearSpy = vi.spyOn(engine, "clear").mockRejectedValue("string clear error");

      const { result } = renderHook(() => useClientOlap());

      let caughtCsvErr: unknown;
      await act(async () => {
        try {
          await result.current.ingestCsv("t", "a,b");
        } catch (e) {
          caughtCsvErr = e;
        }
      });
      expect(caughtCsvErr).toBe("string csv error");
      expect(result.current.error?.message).toBe("string csv error");

      await act(async () => {
        try {
          await result.current.ingestJson("t", []);
        } catch {}
      });
      await act(async () => {
        try {
          await result.current.cacheQueryResults("t", []);
        } catch {}
      });
      await act(async () => {
        try {
          await result.current.query("SELECT 1");
        } catch {}
      });
      await act(async () => {
        try {
          await result.current.dropTable("t");
        } catch {}
      });
      await act(async () => {
        try {
          await result.current.clear();
        } catch {}
      });

      csvSpy.mockRestore();
      jsonSpy.mockRestore();
      regSpy.mockRestore();
      qSpy.mockRestore();
      dropSpy.mockRestore();
      clearSpy.mockRestore();
    });

    it("useDashboardManager: covers missing IDs, out-of-bounds moves, and matching crossFilter removal", () => {
      const { result } = renderHook(() =>
        useDashboardManager({
          initialState: {
            id: "d1",
            title: "Test",
            tiles: [loose<DashboardTile>({ id: "t1", title: "Tile 1", type: "table" })],
            globalFilters: [{ field: "status", operator: "=", value: "active" }],
            crossFilter: { sourceTileId: "t1", field: "cat", value: "A" },
          },
        }),
      );

      expect(result.current.dashboard.globalFilters).toHaveLength(1);

      act(() => {
        result.current.updateTile("non_existent", { title: "New" });
      });

      act(() => {
        result.current.moveTile("t1", "up");
        result.current.moveTile("t1", "down");
        result.current.moveTile("missing_tile", "up");
      });

      const kpiRes = result.current.computeKpi(loose<DashboardTile>({ id: "t2", title: "KPI", type: "kpi" }), []);
      expect(kpiRes.value).toBe(0);

      act(() => {
        result.current.removeTile("t1");
      });
      expect(result.current.dashboard.crossFilter).toBeNull();
    });

    it("useQueryState: covers rawExpression key, RAW filter operator, and camelCase search parameters", () => {
      const { result } = renderHook(() =>
        useQueryState({
          table: "users",
          columns: [
            { column: "users.id", raw_expression: "users.id * 10", alias: "scaled_id" },
          ],
          filters: [
            { column: "users.age", operator: "RAW", raw_expression: "users.age > 21" },
          ],
          vectorSearch: { column: "embedding", vector: [0.1, 0.2] },
          hybridSearch: { fullTextColumn: "body", queryText: "test" },
        }),
      );

      expect(result.current.state.selectedColumns["raw_1"]).toBeDefined();
      expect(result.current.state.filters[0].operator).toBe("RAW");
      expect(result.current.state.vectorSearch?.column).toBe("embedding");
      expect(Reflect.get(result.current.state.hybridSearch ?? {}, "fullTextColumn")).toBe("body");
    });
  });

  describe("Compiler", () => {
    it("compiler: handles empty primary with CTEs, alias collisions, metrics, and fallback expressions", () => {
      const emptyRes = compileVisualState(
        "",
        {},
        [],
        [],
        [],
        [],
        false,
        50,
        null,
        "postgres",
        "AND",
        undefined,
        null,
        null,
        [{ name: "cte1", query: {} }],
        [invalid<WindowFunctionSpec>({ name: "wf1", function: "ROW_NUMBER" })],
        [{ name: "sm1", tableName: "t", metrics: [] }],
      );
      expect(emptyRes.sql).toBe("");

      const collisionCols = invalid<Record<string, VisualColumnSelect>>({
        k1: { name: "calc", rawExpression: "1 + 1", alias: "calc" },
        k2: { name: "calc_sales", rawExpression: "2 + 2", alias: "calc_sales" },
        k3: { name: "calc_2", rawExpression: "3 + 3", alias: "calc_2" },
        k4: { name: "calc", rawExpression: "4 + 4", alias: "calc" },
      });
      const collisionCompiled = compileVisualState("sales", collisionCols, ["k1", "k2", "k3", "k4"], [], [], []);
      expect(collisionCompiled.sql).toContain('AS "calc_3"');

      const metricSql = compileSpecToSql(
        {
          table: "sales",
          columns: [
            { column: "sales.profit" },
            { column: "sales.revenue", alias: "custom_rev_alias" },
          ],
          semantic_models: [
            {
              name: "sales",
              tableName: "sales",
              metrics: [{ name: "revenue", aggregation: "sum" }],
            },
          ],
        },
        "postgres",
        invalid<SchemaSnapshot>({
          tables: {
            sales: {
              metrics: [{ name: "profit", aggregation: "sum" }],
            },
          },
        }),
      );
      expect(metricSql).toContain('AS "custom_rev_alias"');

      const rawFilterCompiled = compileSpecToSql({
        table: "sales",
        columns: ["id"],
        filters: [{ column: "sales.active = 1", operator: "RAW" }],
      });
      expect(rawFilterCompiled).toContain("active = 1");

      const wfSql = compileSpecToSql({
        table: "sales",
        columns: ["id"],
        window_functions: [
          {
            name: "wf",
            function: "ROW_NUMBER",
            order_by: [{ column: "id" }],
            frame: { frame_type: "ROWS" },
          },
        ],
      });
      expect(wfSql).toContain("UNBOUNDED PRECEDING AND CURRENT ROW");

      expect(compileSpecToSql({ table: "" })).toBe("");
      expect(compileSpecToSql({ table: "orders", columns: ["id"] })).toContain("orders");
    });

    it("covers final edge branch cases across modules", async () => {
      // 1. Drizzle with undefined options and missing data_type
      const drizzleRes = toDrizzle({ tables: { t: { columns: [{ name: "c" }] } } });
      expect(drizzleRes).toBeDefined();

      // 2. SelfHealing with empty targetMeta table (no foreign_keys, no foreignKeys)
      const healedEmpty = autoHealClientQuerySpec(
        { table: "orders", columns: ["orders.id", "users.name"] },
        invalid<ByoAiSchema>({ tables: { orders: {}, users: {} } }),
      );
      expect(healedEmpty.healedSpec.joins).toBeDefined();

      // 3. Tools: explain_query with columns, joins, and filters present
      const resFullExplain = executeAgentToolCall(
        "explain_query",
        JSON.stringify({
          spec: {
            table: "orders",
            columns: ["id"],
            joins: [{ table: "users", on: [{ left: "user_id", right: "id" }] }],
            filters: [{ column: "id", op: "eq", value: 1 }],
          },
        }),
      );
      expect(resFullExplain.success).toBe(true);

      // 4. FluentQuery without args
      const fqEmpty = new FluentQuery();
      expect(fqEmpty.toSpec().table).toBe("");

      // 5. Client with relative path, aborted signal, and execute with params
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        headers: { get: () => null },
        json: async () => ({ capabilities: { k: "v" }, schema: { tables: {} } }),
      });
      const client = createQueryBuilderClient({
        baseUrl: "https://api.example.com",
        fetchFn: mockFetch,
      });
      await client.getCapabilities();
      await client.execute({ sql: "SELECT 1" });

      const abortController = new AbortController();
      abortController.abort(new Error("pre-aborted"));
      await expect(client.execute({ sql: "SELECT 1" }, { signal: abortController.signal })).rejects.toThrow(/pre-aborted/);

      // 6. VisualQueryBuilder with showPipelineTab, settings gear, and error handling
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
      const { unmount: uVqb } = render(
        <VisualQueryBuilder
          showPipelineTab={true}
          initialTable="users"
          schema={invalid<SchemaSnapshot>({ tables: { users: { name: "users", columns: [{ name: "id", data_type: "int" }] } } })}
        />,
      );
      const pipelineTab = screen.getByRole("tab", { name: /pipeline/i });
      fireEvent.keyDown(pipelineTab, { key: "ArrowRight" });

      const settingsBtn = screen.getByTestId("btn-feature-settings");
      fireEvent.click(settingsBtn);
      const closeBtn = screen.getAllByText("✕")[0];
      fireEvent.click(closeBtn);
      uVqb();
      warnSpy.mockRestore();

      // 7. Compound QueryBuilderRoot themes and execution rejection
      const compRef = createRef<VisualQueryBuilderRef>();
      const failingClient = asMock<QueryBuilderClient>({
        getSchema: vi.fn().mockResolvedValue({ tables: {} }),
        execute: vi.fn().mockRejectedValue(new Error("comp fail")),
      });
      const { unmount: uComp } = render(
        <QueryBuilder
          ref={compRef}
          theme="light"
          client={failingClient}
          initialSpec={loose<QuerySpec>({ table: "users" })}
        >
          <QueryBuilder.Canvas />
        </QueryBuilder>,
      );
      await act(async () => {
        await expect(compRef.current?.execute()).rejects.toThrow(/comp fail/);
      });
      uComp();

      // QueryBuilderColumns with custom class
      const { unmount: uCols } = render(
        <QueryBuilder
          initialSpec={loose<QuerySpec>({
            table: "users",
            columns: ["users.id", "users.name"],
          })}
        >
          <QueryBuilder.Columns
            classNames={{ columns: "custom-cols", projectionItem: "custom-item" }}
          />
        </QueryBuilder>,
      );
      uCols();

      // 8. useClientOlap with actual Error instance
      const olapEngine = getClientOlapEngine();
      const csvErrSpy = vi.spyOn(olapEngine, "ingestCsv").mockRejectedValue(new Error("typed error"));
      const { result: olapResult } = renderHook(() => useClientOlap());
      await act(async () => {
        try {
          await olapResult.current.ingestCsv("t", "a,b");
        } catch {}
      });
      expect(olapResult.current.error?.message).toBe("typed error");
      csvErrSpy.mockRestore();

      // 9. useDashboardManager computeKpi with rows having keys but no valueField
      const { result: dashResult } = renderHook(() => useDashboardManager());
      const kpiWithRows = dashResult.current.computeKpi(loose<DashboardTile>({ id: "k1", title: "KPI", type: "kpi" }), [{ rev: 100 }, { rev: 50 }]);
      expect(kpiWithRows.value).toBe(150);

      // 10. duckdb SELECT * fallback when table has no columns and resultRows is empty
      const engine = new InMemoryOlapEngine();
      olapTableData(engine).set("empty_tbl", []);
      const qEmpty = await engine.query("SELECT * FROM empty_tbl");
      expect(qEmpty.columns).toEqual([]);

      // 11. Compiler: compileSpecToSql with table only (no columns)
      const specNoCols = compileSpecToSql({ table: "users" });
      expect(specNoCols).toContain("users");
    });

    it("covers final edge branch cases 100 percent across modules", async () => {
      // 1. Drizzle schema with column having missing dataType
      const resDrizzle = toDrizzle({
        tables: {
          metrics: {
            columns: [{ name: "c_empty_type" }],
          },
        },
      }, "postgres");
      expect(resDrizzle).toContain("text(");

      // 2. Prisma: FK referencing column not in table columns + multi-relation to same target
      const resPrisma = toPrisma({
        tables: {
          users: {
            columns: [{ name: "id", dataType: "int", isPrimary: true }],
            foreign_keys: [{ table: "users", column: "missing_col", foreign_table: "posts", foreign_column: "id" }],
          },
          posts: {
            columns: [
              { name: "id", dataType: "int", isPrimary: true },
              { name: "u1_id", dataType: "int" },
              { name: "u2_id", dataType: "int" },
            ],
            foreign_keys: [
              { table: "posts", column: "u1_id", foreign_table: "users", foreign_column: "id" },
              { table: "posts", column: "u2_id", foreign_table: "users", foreign_column: "id" },
            ],
          },
        },
      });
      expect(resPrisma).toContain("Users_u1Id");

      // 3. SQLAlchemy: table with no FKs and column with empty dataType
      const resSa = toSqlAlchemy({
        tables: {
          raw_data: {
            columns: [{ name: "payload" }],
          },
        },
      });
      expect(resSa).toContain("Column(");

      // 4. AI tools: rawSql whitespace and onCompile returning empty string, explain_query counts
      const resWs = executeAgentToolCall("validate_and_compile_query", { sql: "   " });
      expect(resWs.success).toBe(false);
      expect(resWs.error).toContain("Ready to validate");

      const resEmptyCompile = executeAgentToolCall(
        "validate_and_compile_query",
        { spec: { table: "users" } },
        { onCompile: () => "   " },
      );
      expect(resEmptyCompile.success).toBe(false);
      expect(resEmptyCompile.error).toContain("Ready to validate");

      const resExplainEmpty = executeAgentToolCall("explain_query", { spec: { table: "users" } });
      expect(resExplainEmpty.summary).toContain("selecting 1 projection(s), joined with 0 table(s), filtered by 0 predicate(s)");

      const resExplainFull = executeAgentToolCall("explain_query", {
        spec: {
          table: "users",
          columns: ["id"],
          joins: [{ table: "posts", on: "users.id = posts.user_id" }],
          filters: [{ column: "id", op: "=", value: 1 }],
        },
      });
      expect(resExplainFull.summary).toContain("selecting 1 projection(s), joined with 1 table(s), filtered by 1 predicate(s)");

      // 5. Client: error with object serverMsg, /schema 404 falling back to /introspect with .schema, /capabilities with .capabilities
      const mockFetchObj = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        headers: { get: () => "application/json" },
        json: async () => ({ detail: { code: "ERR_CODE" } }),
      });
      const clientObj = createQueryBuilderClient({ baseUrl: "https://api.example.com", fetchFn: mockFetchObj });
      await expect(clientObj.getSchema()).rejects.toThrow(/ERR_CODE/);

      const mockFetchIntrospect = vi.fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 404,
          statusText: "Not Found",
          headers: { get: () => "application/json" },
          json: async () => ({ error: "not found" }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          headers: { get: () => "application/json" },
          json: async () => ({ schema: { tables: { intro: { name: "intro", columns: [] } } } }),
        });
      const clientIntrospect = createQueryBuilderClient({ baseUrl: "https://api.example.com", fetchFn: mockFetchIntrospect });
      const schemaIntro = await clientIntrospect.getSchema();
      expect(schemaIntro.tables.intro).toBeDefined();

      const mockFetchCaps = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: async () => ({ capabilities: { custom: "ok" } }),
      });
      const clientCaps = createQueryBuilderClient({ baseUrl: "https://api.example.com", fetchFn: mockFetchCaps });
      const capsRes = await clientCaps.getCapabilities();
      expect(capsRes.custom).toBe("ok");

      // 6. AiAssistantWidget: click suggestion when not generating
      const { unmount: uAi } = render(
        <AiAssistantWidget
          isOpen={true}
          {...invalid<AiAssistantWidgetProps>({ onClose: () => {} })}
          schema={{ tables: {} }}
          currentSpec={loose<QuerySpec>({ table: "users" })}
          onApplySpec={() => {}}
        />,
      );
      const suggBtn = screen.getByTestId("ai-suggestion-0");
      await act(async () => {
        fireEvent.click(suggBtn);
      });
      uAi();

      // 6b. AI tools: json parse error fallback
      const parseSpy = vi.spyOn(JSON, "parse").mockImplementationOnce(() => {
        throw {};
      });
      const resMalformed = executeAgentToolCall("build_query", "{");
      expect(resMalformed.error).toContain("parse error");
      parseSpy.mockRestore();

      // 7. CalculatedFieldEditor: direct form submit with empty alias
      const onSaveCalc = vi.fn();
      const { container: calcContainer, unmount: uCalc } = render(
        <CalculatedFieldEditor
          isOpen={true}
          onClose={() => {}}
          tables={[]}
          initialField={{ id: "c1", name: "col", alias: "col", type: "expression", expression: "1 + 1" }}
          onSave={onSaveCalc}
        />,
      );
      const aliasInput = screen.getByLabelText("Calculated column alias");
      fireEvent.change(aliasInput, { target: { value: "" } });
      const formEl = calcContainer.querySelector("form");
      if (formEl) fireEvent.submit(formEl);
      expect(onSaveCalc).not.toHaveBeenCalled();
      uCalc();

      // 8. DashboardWorkbench: KPI tile with delta positive & negative, and chart tile with empty rows & fallback
      const { unmount: uBench } = render(
        <DashboardWorkbench
          initialState={{
            tiles: [
              loose<DashboardTile>({
                id: "kpi_pos",
                title: "Positive KPI",
                type: "kpi",
                cachedRows: [{ v: 100 }],
                kpiConfig: { deltaPercentage: 15, valueField: "v" },
              }),
              loose<DashboardTile>({
                id: "kpi_neg",
                title: "Negative KPI",
                type: "kpi",
                cachedRows: [{ v: 50 }],
                kpiConfig: { deltaPercentage: -8, valueField: "v" },
              }),
              loose<DashboardTile>({
                id: "chart_empty",
                title: "Empty Chart",
                type: "chart",
                cachedRows: [],
              }),
            ],
          }}
        />
      );
      expect(screen.getByText(/15% vs previous period/)).toBeDefined();
      expect(screen.getByText(/-8% vs previous period/)).toBeDefined();
      uBench();

      // 8b. DashboardWorkbench: Add tile modal submit with empty title, global filter submit with empty, and tile resize with spanW === 4
      const { unmount: uBenchEmpty } = render(<DashboardWorkbench />);
      fireEvent.click(screen.getByTestId("add-tile-btn"));
      fireEvent.click(screen.getByTestId("confirm-add-tile-btn"));
      fireEvent.click(screen.getByTestId("add-filter-submit-btn"));
      uBenchEmpty();

      const { unmount: uBenchResize } = render(
        <DashboardWorkbench
          initialState={{
            tiles: [
              loose<DashboardTile>({
                id: "tile_w4",
                title: "Wide Tile",
                type: "kpi",
                layout: loose<DashboardTileLayout>({ w: 4 }),
                cachedRows: [{ val: 10 }],
              }),
            ],
          }}
        />,
      );
      fireEvent.click(screen.getByTestId("resize-tile-tile_w4"));
      uBenchResize();

      // 9. VisualQueryBuilder: sqlTextarea className and WindowFunctionBuilder availableColumns string column mapping
      const { unmount: uVqb2 } = render(
        <VisualQueryBuilder
          classNames={{ sqlTextarea: "my-sql-area" }}
          schema={{
            tables: {
              users: {
                name: "users",
                columns: [{ name: "id", data_type: "int", is_nullable: false, is_primary: true }],
              },
              other: {
                name: "other",
                columns: invalid<ColumnMeta[]>(["str_col"]),
              },
            },
          }}
          initialSpec={loose<QuerySpec>({ table: "users" })}
        />,
      );
      const wfBtn = screen.getByLabelText(/Open window functions? builder/i);
      fireEvent.click(wfBtn);
      expect(screen.getByText(/Window Function Builder/i)).toBeDefined();
      uVqb2();

      // 9b. VisualQueryBuilder: Raw SQL mode tab switch and editing
      const { unmount: uVqbSql } = render(
        <VisualQueryBuilder
          classNames={{ sqlTextarea: "my-sql-area", sqlSyncBadge: "my-sync-badge" }}
          initialSpec={loose<QuerySpec>({ table: "users" })}
        />,
      );
      const sqlTab = screen.getByRole("tab", { name: /Raw SQL/i });
      fireEvent.click(sqlTab);
      const ta = screen.getByLabelText("Raw SQL code");
      fireEvent.change(ta, { target: { value: "SELECT * FROM users WHERE active = 1" } });
      expect(document.querySelector(".my-sync-badge")).not.toBeNull();
      expect(document.querySelector(".my-sql-area")).not.toBeNull();
      uVqbSql();

      // 10. WindowFunctionBuilder: fallback when theme.colors.textMuted is undefined
      const { unmount: uWf } = render(
        <ThemeProvider theme={{ colors: {} }}>
          <WindowFunctionBuilder
            isOpen={true}
            onClose={() => {}}
            onSave={() => {}}
            availableColumns={[]}
          />
        </ThemeProvider>,
      );
      expect(screen.getByText("No columns available")).toBeDefined();
      uWf();

      // 11. QueryBuilder compound: handleMoveProjection boundary checks, empty columns className, missing key in selectedColumns
      function StateManipulator() {
        const { actions, setRawSql } = useCompoundQueryBuilder();
        return (
          <div>
            <button onClick={() => actions.setOrderedProjectionKeys(["non_existent_key"])}>
              Break Key
            </button>
            <button onClick={() => setRawSql("SELECT * FROM users")}>
              Enable Raw
            </button>
          </div>
        );
      }

      const { unmount: uCompEdge } = render(
        <QueryBuilder
          theme="dark"
          initialSpec={loose<QuerySpec>({
            table: "users",
            columns: ["users.id", "users.name"],
          })}
        >
          <StateManipulator />
          <QueryBuilder.Columns />
          <QueryBuilder.SqlEditor classNames={{ sqlSyncBadge: "custom-sync-badge" }} />
        </QueryBuilder>,
      );

      const leftBtn = screen.getByLabelText(/Move users\.name left/i);
      fireEvent.click(leftBtn);
      const rightBtn = screen.getByLabelText(/Move users\.name right/i);
      fireEvent.click(rightBtn);

      // Boundary clicks to verify targetIndex < 0 and targetIndex >= length safety guards
      const boundaryLeft = screen.getByLabelText(/Move users\.id left/i);
      fireEvent.click(boundaryLeft);

      const boundaryRight = screen.getByLabelText(/Move users\.name right/i);
      fireEvent.click(boundaryRight);

      fireEvent.click(screen.getByText("Break Key"));
      fireEvent.click(screen.getByText("Enable Raw"));
      expect(document.querySelector(".custom-sync-badge")).not.toBeNull();
      uCompEdge();

      const { unmount: uColsEmpty } = render(
        <QueryBuilder initialSpec={loose<QuerySpec>({ table: "users", columns: [] })}>
          <QueryBuilder.Columns className="empty-cls" classNames={{ columns: "custom-cols" }} />
        </QueryBuilder>,
      );
      expect(document.querySelector(".custom-cols")).not.toBeNull();
      uColsEmpty();

      const compRefUndef = createRef<VisualQueryBuilderRef>();
      const { unmount: uCompUndef } = render(
        <QueryBuilder
          ref={compRefUndef}
          theme={undefined}
          onExecuteQuery={async () => invalid<QueryResultData>(undefined)}
          initialSpec={loose<QuerySpec>({ table: "users" })}
        >
          <QueryBuilder.Canvas />
        </QueryBuilder>,
      );
      await act(async () => {
        const res = await compRefUndef.current?.execute();
        expect(res).toBeUndefined();
      });
      uCompUndef();

      const { unmount: uThemeCtx } = render(
        <ThemeProvider theme={lightTheme}>
          <QueryBuilder initialSpec={loose<QuerySpec>({ table: "users" })}>
            <QueryBuilder.Canvas />
          </QueryBuilder>
        </ThemeProvider>,
      );
      uThemeCtx();

      // 12. duckdbDriver: empty bucket in aggregation with no GROUP BY, table without meta, null sorting ASC/DESC
      const engine = new InMemoryOlapEngine();
      olapTableData(engine).set("tbl_empty", []);
      const qAggEmpty = await engine.query("SELECT dept, COUNT(*) FROM tbl_empty");
      expect(qAggEmpty.rows[0].dept).toBeNull();

      olapTableData(engine).set("tbl_no_meta", [{ alpha: 1, beta: 2 }]);
      const qNoMeta = await engine.query("SELECT * FROM tbl_no_meta");
      expect(qNoMeta.columns).toEqual(["alpha", "beta"]);

      olapTableData(engine).set("tbl_nulls", [
        { id: 1, val: null },
        { id: 2, val: 10 },
        { id: 3, val: null },
        { id: 4, val: 5 },
      ]);
      const qSortAsc = await engine.query("SELECT * FROM tbl_nulls ORDER BY val ASC");
      expect(qSortAsc.rows[0].val).toBeNull();
      const qSortDesc = await engine.query("SELECT * FROM tbl_nulls ORDER BY val DESC");
      expect(qSortDesc.rows[0].val).toBe(10);

      // 13. useClientOlap: error handling with Error and non-Error string in query, dropTable, clear, ingestJson, cacheQueryResults
      const { result: hookOlap } = renderHook(() => useClientOlap());
      const querySpy1 = vi.spyOn(hookOlap.current.engine, "query").mockRejectedValue(new Error("q typed err"));
      await act(async () => { try { await hookOlap.current.query("SELECT 1"); } catch {} });
      expect(hookOlap.current.error?.message).toBe("q typed err");
      querySpy1.mockRestore();

      const querySpy2 = vi.spyOn(hookOlap.current.engine, "query").mockRejectedValue("string query err");
      await act(async () => { try { await hookOlap.current.query("SELECT 1"); } catch {} });
      expect(hookOlap.current.error?.message).toBe("string query err");
      querySpy2.mockRestore();

      const dropSpy1 = vi.spyOn(hookOlap.current.engine, "dropTable").mockRejectedValue(new Error("drop typed err"));
      await act(async () => { try { await hookOlap.current.dropTable("t"); } catch {} });
      expect(hookOlap.current.error?.message).toBe("drop typed err");
      dropSpy1.mockRestore();

      const dropSpy2 = vi.spyOn(hookOlap.current.engine, "dropTable").mockRejectedValue("string drop err");
      await act(async () => { try { await hookOlap.current.dropTable("t"); } catch {} });
      expect(hookOlap.current.error?.message).toBe("string drop err");
      dropSpy2.mockRestore();

      const clearSpy1 = vi.spyOn(hookOlap.current.engine, "clear").mockRejectedValue(new Error("clear typed err"));
      await act(async () => { try { await hookOlap.current.clear(); } catch {} });
      expect(hookOlap.current.error?.message).toBe("clear typed err");
      clearSpy1.mockRestore();

      const clearSpy2 = vi.spyOn(hookOlap.current.engine, "clear").mockRejectedValue("string clear err");
      await act(async () => { try { await hookOlap.current.clear(); } catch {} });
      expect(hookOlap.current.error?.message).toBe("string clear err");
      clearSpy2.mockRestore();

      const jsonSpy1 = vi.spyOn(hookOlap.current.engine, "ingestJson").mockRejectedValue(new Error("json typed err"));
      await act(async () => { try { await hookOlap.current.ingestJson("t", []); } catch {} });
      expect(hookOlap.current.error?.message).toBe("json typed err");
      jsonSpy1.mockRestore();

      const jsonSpy2 = vi.spyOn(hookOlap.current.engine, "ingestJson").mockRejectedValue("json raw err");
      await act(async () => { try { await hookOlap.current.ingestJson("t", []); } catch {} });
      expect(hookOlap.current.error?.message).toBe("json raw err");
      jsonSpy2.mockRestore();

      const resSpy1 = vi.spyOn(hookOlap.current.engine, "registerBackendResults").mockRejectedValue(new Error("res typed err"));
      await act(async () => { try { await hookOlap.current.cacheQueryResults("t", []); } catch {} });
      expect(hookOlap.current.error?.message).toBe("res typed err");
      resSpy1.mockRestore();

      const resSpy2 = vi.spyOn(hookOlap.current.engine, "registerBackendResults").mockRejectedValue("res raw err");
      await act(async () => { try { await hookOlap.current.cacheQueryResults("t", []); } catch {} });
      expect(hookOlap.current.error?.message).toBe("res raw err");
      resSpy2.mockRestore();

      // 13b. Client: signal aborted and headers null
      const dummyClient = createQueryBuilderClient({ baseUrl: "https://api.example.com", fetchFn: vi.fn() });
      await expect(dummyClient.getSchema({ signal: invalid<AbortSignal>({ aborted: true, reason: undefined }) })).rejects.toThrow("Request aborted");
      await expect(dummyClient.getSchema({ signal: invalid<AbortSignal>({ aborted: true, reason: new Error("Custom abort") }) })).rejects.toThrow("Custom abort");

      const mockNoH = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Server Error",
        headers: null,
        text: async () => "Plain error text",
      });
      const clientNoH = createQueryBuilderClient({ baseUrl: "https://api.example.com", fetchFn: mockNoH });
      await expect(clientNoH.getSchema()).rejects.toThrow(/Server Error/);

      const mock404Direct = vi.fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 404,
          statusText: "Not Found",
          headers: { get: () => "application/json" },
          json: async () => ({}),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          headers: { get: () => "application/json" },
          json: async () => ({ tables: { direct: { name: "direct", columns: [] } } }),
        });
      const client404Direct = createQueryBuilderClient({ baseUrl: "https://api.example.com", fetchFn: mock404Direct });
      const res404Direct = await client404Direct.getSchema();
      expect(res404Direct.tables.direct).toBeDefined();

      const mockCapsDirect = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: async () => ({ dialect: "postgres" }),
      });
      const clientCapsDirect = createQueryBuilderClient({ baseUrl: "https://api.example.com", fetchFn: mockCapsDirect });
      const capsDirect = await clientCapsDirect.getCapabilities();
      expect(capsDirect.dialect).toBe("postgres");

      // 14. Compiler: window function with empty frame and semantic models metric alias matching
      const wfSql = compileSpecToSql({
        table: "sales",
        columns: ["id"],
        window_functions: [
          {
            function: "AVG",
            arguments: ["amount"],
            frame: {},
            alias: "moving_avg",
          },
        ],
      });
      expect(wfSql).toContain("ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW");

      const rawSqlRes = compileVisualState(
        "users",
        {
          raw1: loose<VisualColumnSelect>({ table: "users", rawExpression: "NOW()" }),
          raw2: loose<VisualColumnSelect>({ table: "users", name: "named_col", rawExpression: "RANDOM()" }),
        },
        ["raw1", "raw2"],
        [],
        [],
        [],
        false,
        10,
      );
      expect(rawSqlRes.sql).toContain('NOW() AS "expr"');
      expect(rawSqlRes.sql).toContain('RANDOM() AS "named_col"');

      const smSql = compileSpecToSql({
        table: "orders",
        columns: [
          {
            table: "orders",
            column: "rev",
            isMetric: true,
          },
        ],
        semantic_models: [
          {
            name: "orders",
            tableName: "orders",
            dimensions: [],
            metrics: [
              {
                name: "rev",
                title: "Revenue",
                sqlExpression: "orders.rev",
                aggregation: "sum",
              },
            ],
          },
        ],
      });
      expect(smSql).toContain("orders.rev");
    });

    it("covers remaining client branches: empty baseUrl, relative path, headers without get or returning null", async () => {
      // 1. client with empty baseUrl and relative path without leading slash
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: async () => ({ success: true }),
      });
      const clientEmptyBase = createQueryBuilderClient({
        baseUrl: "",
        fetchFn: mockFetch,
      });
      const res = await clientEmptyBase.request("api/v1/test");
      expect(res).toEqual({ success: true });
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/v1/test",
        expect.objectContaining({ headers: expect.any(Object) })
      );

      // 2. response not ok with headers lacking .get or .get returning null
      const mockFetchNoGet = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Server Error",
        headers: {},
        text: async () => "Internal Failure",
      });
      const clientErr = createQueryBuilderClient({
        baseUrl: "https://api.example.com",
        fetchFn: mockFetchNoGet,
      });
      await expect(clientErr.request("/error")).rejects.toThrow("QueryBuilderClient HTTP 500: Server Error - Internal Failure");

      const mockFetchNullHeader = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        headers: { get: () => null },
        text: async () => "Bad",
      });
      const clientErrNull = createQueryBuilderClient({
        baseUrl: "https://api.example.com",
        fetchFn: mockFetchNullHeader,
      });
      await expect(clientErrNull.request("/bad")).rejects.toThrow("QueryBuilderClient HTTP 400: Bad Request - Bad");
    });

    it("covers AiAssistantWidget handleSuggestionClick when isGenerating is true", () => {
      const spy = vi.spyOn(byoHook, "useBringYourOwnAi").mockReturnValue({
        messages: [],
        isGenerating: true,
        error: null,
        latestSpec: null,
        latestSql: null,
        sendMessage: vi.fn(),
        applySpec: vi.fn(),
        clearMessages: vi.fn(),
        undoLast: vi.fn(),
      });

      render(
        <AiAssistantWidget
          widgetPosition="docked-right"
          suggestions={["Show top sales"]}
        />
      );

      const btn = screen.getByTestId("ai-suggestion-0");
      fireEvent.click(btn);
      expect(spy).toHaveBeenCalled();
      spy.mockRestore();
    });

    it("covers DashboardWorkbench submitting Add Tile modal with empty title", () => {
      render(<DashboardWorkbench />);
      const createFirstBtn = screen.getByRole("button", { name: "Create First Tile" });
      fireEvent.click(createFirstBtn);
      const form = screen.getByTestId("confirm-add-tile-btn").closest("form")!;
      fireEvent.submit(form);
      expect(screen.getByTestId("new-tile-title-input")).toBeTruthy();
    });

    it("covers WindowFunctionBuilder with empty availableColumns", () => {
      render(
        <WindowFunctionBuilder
          isOpen={true}
          onClose={vi.fn()}
          onSave={vi.fn()}
          availableColumns={[]}
        />
      );
      expect(screen.getByText("No columns available")).toBeTruthy();
    });

    it("covers VisualQueryBuilder tabs pipeline, plan, results, chart active classNames and initialWindowFunctions", async () => {
      const ref = createRef<VisualQueryBuilderRef>();
      const mockClient = asMock<QueryBuilderClient>({
        execute: vi.fn().mockResolvedValue({ data: [{ count: 1 }] }),
        getSchema: vi.fn().mockResolvedValue(null),
      });

      const { container } = render(
        <VisualQueryBuilder
          ref={ref}
          client={mockClient}
          showPipelineTab={true}
          showPlanTab={true}
          featurePreset="all"
          features={invalid<FeatureConfig>({ ctes: "always", query_plan: "always", raw_sql: "always", visual_chart: "always" })}
          {...invalid<VisualQueryBuilderProps>({ initialActiveTab: "pipeline" })}
          initialWindowFunctions={[{ function: "ROW_NUMBER", alias: "rn" }]}
          schema={invalid<SchemaSnapshot>({
            tables: {
              users: {
                name: "users",
                columns: [{ name: "id", data_type: "int" }],
              },
            },
          })}
          initialCtes={[{ name: "stage1", query: { table: "users", columns: [{}] } }]}
          queryPlan={invalid<QueryPlanNode>("Seq Scan on users")}
          classNames={{ tab: "custom-tab", tabActive: "custom-active" }}
        />
      );

      const pipelineTab = container.querySelector('[data-qb-tab="pipeline"]') as HTMLElement;
      expect(pipelineTab).not.toBeNull();
      fireEvent.click(pipelineTab);
      expect(pipelineTab.className).toContain("custom-active");

      const planTab = container.querySelector('[data-qb-tab="plan"]') as HTMLElement;
      expect(planTab).not.toBeNull();
      fireEvent.click(planTab);
      expect(planTab.className).toContain("custom-active");

      const resultsTab = container.querySelector('[data-qb-tab="results"]') as HTMLElement;
      expect(resultsTab).not.toBeNull();
      fireEvent.click(resultsTab);
      expect(resultsTab.className).toContain("custom-active");

      const chartTab = container.querySelector('[data-qb-tab="chart"]') as HTMLElement;
      expect(chartTab).not.toBeNull();
      fireEvent.click(chartTab);
      expect(chartTab.className).toContain("custom-active");

      // Client raw mode execution without spec
      const sqlTab = container.querySelector('[data-qb-tab="sql"]') as HTMLElement;
      if (sqlTab) {
        fireEvent.click(sqlTab);
        const sqlTextarea = container.querySelector('[data-qb="sql-editor"]') as HTMLTextAreaElement;
        if (sqlTextarea) {
          fireEvent.change(sqlTextarea, { target: { value: "SELECT 1" } });
        }
        await act(async () => {
          await ref.current?.execute();
        });
        expect(mockClient.execute).toHaveBeenCalledWith({ sql: "SELECT 1" });
      }

      // LocalStorage advanced mode branches
      localStorage.setItem("qb_advanced_mode", "true");
      render(<VisualQueryBuilder storageKey="qb_advanced_mode" />);

      const storageSpy = vi.spyOn(Storage.prototype, "getItem").mockImplementationOnce(() => {
        throw new Error("Storage fail");
      });
      render(<VisualQueryBuilder storageKey="qb_advanced_mode" />);
      storageSpy.mockRestore();
    });

    it("covers useClientOlap non-Error rejections", async () => {
      const engine = getClientOlapEngine();
      const spyCsv = vi.spyOn(engine, "ingestCsv").mockRejectedValueOnce("string error csv");
      const spyJson = vi.spyOn(engine, "ingestJson").mockRejectedValueOnce("string error json");
      const spyCache = vi.spyOn(engine, "registerBackendResults").mockRejectedValueOnce("string error results");
      const spyQuery = vi.spyOn(engine, "query").mockRejectedValueOnce("string error query");
      const spyDrop = vi.spyOn(engine, "dropTable").mockRejectedValueOnce("string error drop");
      const spyClear = vi.spyOn(engine, "clear").mockRejectedValueOnce("string error clear");
      const spyFile = vi.spyOn(localIngest, "ingestLocalFile").mockRejectedValueOnce("string error file");

      const { result } = renderHook(() => useClientOlap());

      await act(async () => {
        try {
          await result.current.ingestFile(new File(["content"], "test.csv"));
        } catch {}
      });
      expect(result.current.error?.message).toBe("string error file");

      await act(async () => {
        try {
          await result.current.ingestCsv("tbl", "a,b\n1,2");
        } catch {}
      });
      expect(result.current.error?.message).toBe("string error csv");

      await act(async () => {
        try {
          await result.current.ingestJson("tbl", [{ a: 1 }]);
        } catch {}
      });
      expect(result.current.error?.message).toBe("string error json");

      await act(async () => {
        try {
          await result.current.cacheQueryResults("tbl", [{ a: 1 }]);
        } catch {}
      });
      expect(result.current.error?.message).toBe("string error results");

      await act(async () => {
        try {
          await result.current.query("SELECT 1");
        } catch {}
      });
      expect(result.current.error?.message).toBe("string error query");

      await act(async () => {
        try {
          await result.current.dropTable("tbl");
        } catch {}
      });
      expect(result.current.error?.message).toBe("string error drop");

      await act(async () => {
        try {
          await result.current.clear();
        } catch {}
      });
      expect(result.current.error?.message).toBe("string error clear");

      spyCsv.mockRestore();
      spyJson.mockRestore();
      spyCache.mockRestore();
      spyQuery.mockRestore();
      spyDrop.mockRestore();
      spyClear.mockRestore();
      spyFile.mockRestore();
    });

    it("covers compiler metricDef resolution branches: sm.name === tableAlias, sm.tableName === item.table, sm.metrics undefined, m.name === colName, empty metricDef.name", () => {
      // 1. sm.name === tableAlias when sm.tableName !== tableAlias
      const resSmName = compileVisualState(
        "u",
        {
          col1: loose<VisualColumnSelect>({
            table: "u",
            name: "rev",
            metric: true,
          }),
        },
        ["col1"],
        [],
        [],
        [],
        false,
        50,
        null,
        "postgres",
        "AND",
        undefined,
        null,
        null,
        null,
        null,
        [
          {
            name: "u",
            tableName: "raw_users",
            dimensions: [],
            metrics: [
              {
                name: "rev",
                title: "Revenue",
                sqlExpression: "u.rev",
                aggregation: "sum",
              },
            ],
          },
        ],
      );
      expect(resSmName.sql).toContain("u.rev");

      // 2. sm.tableName === item.table when tableAlias !== sm.tableName and sm.name !== tableAlias
      // Also sm with metrics undefined
      const resSmTable = compileVisualState(
        "orders",
        {
          col1: loose<VisualColumnSelect>({
            table: "public.orders",
            name: "val",
            metric: true,
          }),
        },
        ["col1"],
        [],
        [],
        [],
        false,
        50,
        null,
        "postgres",
        "AND",
        undefined,
        null,
        null,
        null,
        null,
        [
          {
            name: "nomatch",
            tableName: "other",
            dimensions: [],
            metrics: undefined,
          },
          {
            name: "orders_model",
            tableName: "public.orders",
            dimensions: [],
            metrics: [
              {
                name: "val",
                title: "Value",
                sqlExpression: "orders.val",
                aggregation: "sum",
              },
            ],
          },
        ],
      );
      expect(resSmTable.sql).toContain("orders.val");

      // 3. m.name === colName when m.name !== metricName
      const resColName = compileVisualState(
        "orders",
        {
          col1: loose<VisualColumnSelect>({
            table: "orders",
            name: "amount",
            metric: "metric_alias",
          }),
        },
        ["col1"],
        [],
        [],
        [],
        false,
        50,
        null,
        "postgres",
        "AND",
        undefined,
        null,
        null,
        null,
        null,
        [
          {
            name: "orders",
            tableName: "orders",
            dimensions: [],
            metrics: [
              {
                name: "amount",
                title: "Amount",
                sqlExpression: "orders.amount",
                aggregation: "sum",
              },
            ],
          },
        ],
      );
      expect(resColName.sql).toContain("orders.amount");

      // 4. metricDef.name === "" falls back to colName in alias
      const resEmptyName = compileVisualState(
        "sales",
        {
          col1: loose<VisualColumnSelect>({
            table: "sales",
            name: "amount",
            metric: {
              name: "",
              title: "Amt",
              sqlExpression: "sales.amount",
              aggregation: "sum",
            },
          }),
        },
        ["col1"],
        [],
        [],
        [],
        false,
        10,
      );
      expect(resEmptyName.sql).toContain('AS "amount"');
    });
  });
});
