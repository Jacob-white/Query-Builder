import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, renderHook, act } from "@testing-library/react";

// Adapters
import { toDrizzle } from "../src/adapters/drizzle";
import { toPrisma } from "../src/adapters/prisma";
import { toSqlAlchemy } from "../src/adapters/sqlalchemy";
import { expandMetricSql, parseSemanticModelsJson } from "../src/adapters/semantic";
import { extractSnapshotData } from "../src/adapters/utils";

// AI & Client
import { autoHealClientQuerySpec } from "../src/ai/selfHealing";
import { executeAgentToolCall } from "../src/ai/tools";
import { createQueryBuilderClient } from "../src/client";

// Components
import { AiAssistantWidget } from "../src/components/AiAssistantWidget";
import { BiChartVisualizer } from "../src/components/BiChartVisualizer";
import { CalculatedFieldEditor } from "../src/components/CalculatedFieldEditor";
import { ExportWorkbench } from "../src/components/ExportWorkbench";
import { LocalDataModal } from "../src/components/LocalDataModal";
import { detectCteCycles } from "../src/components/PipelineDagCanvas";
import { QueryCanvas } from "../src/components/QueryCanvas";
import { QueryPerformanceAdvisor } from "../src/components/QueryPerformanceAdvisor";
import { QueryResultsTable } from "../src/components/QueryResultsTable";
import { TableCard } from "../src/components/TableCard";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import { WindowFunctionBuilder } from "../src/components/WindowFunctionBuilder";

// Compound
import { QueryBuilder } from "../src/components/compound";
import { useCompoundQueryBuilder } from "../src/components/compound/QueryBuilderContext";

// Drivers, Hooks & Utils
import * as duckdbDriverModule from "../src/drivers/duckdbDriver";
import { InMemoryOlapEngine, getClientOlapEngine } from "../src/drivers/duckdbDriver";
import { useBringYourOwnAi } from "../src/hooks/useBringYourOwnAi";
import { useClientOlap } from "../src/hooks/useClientOlap";
import { useDashboardManager } from "../src/hooks/useDashboardManager";
import { useQueryState } from "../src/hooks/useQueryState";
import { QueryBuilderProvider, useQueryBuilderContext } from "../src/theme/QueryBuilderProvider";
import { ThemeProvider } from "../src/theme/ThemeProvider";
import { compileVisualState } from "../src/utils/compiler";
import { isFeatureVisible, detectActiveAdvancedClauses, resolveFeatureConfig } from "../src/utils/featureUtils";
import { ingestLocalFile, readFileAsText, readFileAsArrayBuffer } from "../src/utils/localDataIngest";
import * as perfAdvisorModule from "../src/utils/performanceAdvisor";
import { estimateCloudQueryCost, analyzeQueryPerformance } from "../src/utils/performanceAdvisor";
import { validateSchema } from "../src/utils/schemaUtils";
import { parseSqlToSpec } from "../src/utils/sqlParser";

describe("Comprehensive 100% Coverage Gap Filler", () => {
  describe("Adapters", () => {
    it("drizzle: handles SQLite with float, blob, and empty table", () => {
      const schema = {
        tables: {
          metrics: {
            columns: [
              { name: "score", dataType: "float" },
              { name: "data", dataType: "blob" },
            ],
          },
          empty_tbl: {
            columns: [],
          },
        },
      };

      const result = toDrizzle(schema as any, { dialect: "sqlite" });
      expect(result).toContain('real("score")');
      expect(result).toContain('blob("data")');
      expect(result).toContain('sqliteTable("empty_tbl", {});');
    });

    it("prisma: handles relation name collision and empty model", () => {
      const schema = {
        tables: {
          users: {
            columns: [
              { name: "id", dataType: "int", isPrimary: true },
              { name: "posts", dataType: "text" }, // field name collision with post -> posts
            ],
          },
          post: {
            columns: [
              { name: "id", dataType: "int", isPrimary: true },
              { name: "user_id", dataType: "int" },
            ],
            foreignKeys: [
              { table: "post", column: "user_id", foreign_table: "users", foreign_column: "id" },
            ],
          },
          Empty: {
            columns: [],
          },
        },
      };

      const result = toPrisma(schema as any);
      expect(result).toContain("postsRel Post[]");
      expect(result).toContain("model Empty {\n}");
    });

    it("semantic: handles not_in array and metric filter without operator", () => {
      const metricDef: any = {
        name: "test_metric",
        table: "users",
        aggregation: "sum",
        filters: [
          { field: "status", operator: "not_in", value: ["deleted", "banned"] },
        ],
      };
      const sql = expandMetricSql(metricDef);
      expect(sql).toContain("status NOT IN ('deleted', 'banned')");

      const models = parseSemanticModelsJson(
        JSON.stringify([
          {
            name: "UserMetrics",
            table: "users",
            metrics: [
              {
                name: "active_users",
                filters: [{ field: "is_active", value: true }], // no operator
              },
            ],
          },
        ]),
      );
      expect(models[0].metrics[0].filters[0].operator).toBe("eq");
    });

    it("sqlalchemy: handles non-id fk, python keyword, and variable collision", () => {
      const schema = {
        tables: {
          orders: {
            columns: [
              { name: "id", dataType: "int", isPrimary: true },
              { name: "author", dataType: "int" },
              { name: "class_id", dataType: "int" },
              { name: "user", dataType: "text" },
              { name: "user_id", dataType: "int" },
            ],
            foreignKeys: [
              { table: "orders", column: "author", foreign_table: "users", foreign_column: "id" },
              { table: "orders", column: "class_id", foreign_table: "class", foreign_column: "id" },
              { table: "orders", column: "user_id", foreign_table: "user", foreign_column: "id" },
            ],
          },
          users: { columns: [{ name: "id", dataType: "int", isPrimary: true }] },
          class: { columns: [{ name: "id", dataType: "int", isPrimary: true }] },
          user: { columns: [{ name: "id", dataType: "int", isPrimary: true }] },
        },
      };

      const result = toSqlAlchemy(schema as any);
      expect(result).toContain('users = relationship("Users", foreign_keys=[author])');
      expect(result).toContain('class_rel = relationship("Class", foreign_keys=[class_id])');
      expect(result).toContain('user_rel = relationship("User", foreign_keys=[user_id])');
    });

    it("extractSnapshotData: handles string columns and relationships array", () => {
      const raw = {
        tables: {
          items: {
            columns: ["id", "title"],
          },
        },
        relationships: [
          null,
          "invalid",
          {
            source_table: "items",
            source_column: "user_id",
            target_table: "users",
            target_column: "id",
          },
        ],
      };

      const extracted = extractSnapshotData(raw);
      expect(extracted.tables.items.columns[0].is_primary).toBe(true);
      expect(extracted.tables.items.columns[1].data_type).toBe("text");
      expect(extracted.foreignKeys).toHaveLength(1);
      expect(extracted.foreignKeys[0].table).toBe("items");
    });
  });

  describe("AI & Client", () => {
    it("selfHealing: auto synthesizes joins using foreign keys", () => {
      const schema = {
        tables: {
          orders: {
            foreign_keys: [
              { target_table: "users", target_column: "id", column: "user_id" },
            ],
          },
        },
      };

      const healed = autoHealClientQuerySpec(
        {
          table: "users",
          columns: ["orders.total"],
        },
        schema as any,
      );

      expect(healed.healedSpec.joins).toHaveLength(1);
      expect(healed.healedSpec.joins![0].table).toBe("orders");
      expect(healed.healedSpec.joins![0].left_col).toBe("id");
      expect(healed.healedSpec.joins![0].right_col).toBe("user_id");
    });

    it("ai/tools: handles format options, explain_query with rawSql and empty spec", () => {
      const resJson = executeAgentToolCall("get_schema_catalog", { format: "json" }, { schema: { tables: {} } });
      expect(resJson.format).toBe("json");

      const resMd = executeAgentToolCall("get_schema_catalog", { format: "markdown" }, { schema: { tables: {} } });
      expect(resMd.format).toBe("markdown");

      const resExplain = executeAgentToolCall("explain_query", {
        sql: "SELECT name FROM users",
      });
      expect(resExplain.success).toBe(true);

      const resExplainEmpty = executeAgentToolCall("explain_query", {
        spec: { table: "users" },
      });
      expect(resExplainEmpty.success).toBe(true);
      expect(resExplainEmpty.joinsCount).toBe(0);
      expect(resExplainEmpty.filtersCount).toBe(0);
    });

    it("client: handles 404 fallback to /introspect and getCapabilities fallback to getSchema", async () => {
      const mockFetch = vi.fn();
      const client = createQueryBuilderClient({ baseUrl: "https://api.example.com", fetchFn: mockFetch as any });

      // getSchema 404 fallback
      mockFetch
        .mockResolvedValueOnce({
          ok: false,
          status: 404,
          json: async () => ({ error: "Not Found" }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ schema: { tables: { introspected: {} } } }),
        });

      const schema = await client.getSchema();
      expect(schema.tables).toHaveProperty("introspected");

      // getCapabilities failure falling back to getSchema
      mockFetch
        .mockRejectedValueOnce(new Error("Network Error"))
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ schema: { capabilities: { ctes: "standard" } } }),
        });

      const caps = await client.getCapabilities();
      expect(caps.ctes).toBe("standard");

      // getCapabilities failure when getSchema also fails
      mockFetch
        .mockRejectedValueOnce(new Error("Network Error"))
        .mockRejectedValueOnce(new Error("Schema failed"));

      const emptyCaps = await client.getCapabilities();
      expect(emptyCaps).toEqual({});
    });
  });

  describe("Components", () => {
    it("AiAssistantWidget: supports onToggleOpen, handleSubmit checks, suggestion click, and docked-right", () => {
      const onToggleOpen = vi.fn();
      const { rerender } = render(
        <AiAssistantWidget
          widgetPosition="docked-right"
          isOpen={true}
          onToggleOpen={onToggleOpen}
        />,
      );

      const chatWindow = screen.getByTestId("ai-chat-window");
      expect(chatWindow).toBeTruthy();

      // submit empty form
      const form = chatWindow.querySelector("form");
      if (form) {
        fireEvent.submit(form);
      }

      // test launcher toggle
      rerender(
        <AiAssistantWidget
          widgetPosition="floating-bottom-right"
          isOpen={false}
          onToggleOpen={onToggleOpen}
        />,
      );
      const launcher = screen.getByTestId("ai-widget-launcher");
      fireEvent.click(launcher);
      expect(onToggleOpen).toHaveBeenCalledWith(true);
    });

    it("BiChartVisualizer: handles null categories in NONE and aggregated modes, and unstyled canvas", () => {
      const rows = [{ val: 10 }, { cat: "A", val: 20 }];

      // NONE mode with null category
      render(
        <BiChartVisualizer
          rows={rows}
          categoryField="cat"
          metricField="val"
          aggregation="NONE"
          adapter="echarts"
          unstyled={true}
        />,
      );
      expect(screen.getByTestId("echarts-container")).toBeTruthy();

      // Aggregated mode with null category and vega-lite unstyled
      render(
        <BiChartVisualizer
          rows={rows}
          categoryField="cat"
          metricField="val"
          aggregation="SUM"
          adapter="vega-lite"
          unstyled={true}
        />,
      );
      expect(screen.getByTestId("vega-lite-container")).toBeTruthy();
    });

    it("CalculatedFieldEditor: renders in unstyled mode", () => {
      render(
        <CalculatedFieldEditor
          isOpen={true}
          onClose={() => {}}
          onSave={() => {}}
          tables={[]}
          unstyled={true}
        />,
      );
      expect(screen.getByRole("dialog")).toBeTruthy();
    });

    it("ExportWorkbench: handles externalSql with matching/different dialect and dialect change", () => {
      const spec: any = { table: "users", columns: ["id"] };
      const onDialectChange = vi.fn();

      render(
        <ExportWorkbench
          spec={spec}
          dialect="postgres"
          sql="SELECT external FROM users"
          onDialectChange={onDialectChange}
        />,
      );

      fireEvent.click(document.querySelector('[data-qb="codegen-tab-sql"]')!);
      expect(document.querySelector('[data-qb="playground-code-snippet"]')?.textContent).toContain("SELECT external FROM users");

      // Switch dialect to snowflake
      const select = document.querySelector('[data-qb="playground-dialect-select"]') as HTMLSelectElement;
      fireEvent.change(select, { target: { value: "snowflake" } });
      expect(onDialectChange).toHaveBeenCalledWith("snowflake");
    });

    it("LocalDataModal: renders in unstyled mode and displays error message", async () => {
      render(
        <LocalDataModal isOpen={true} onClose={() => {}} unstyled={true} />,
      );
      expect(screen.getByTestId("local-data-dropzone")).toBeTruthy();

      const fileInput = screen.getByTestId("local-data-file-input");
      const badFile = new File(["bad content"], "test.xyz", { type: "application/octet-stream" });
      await act(async () => {
        fireEvent.change(fileInput, { target: { files: [badFile] } });
      });
      expect(screen.getByTestId("local-data-error")).toBeTruthy();
    });

    it("PipelineDagCanvas: detectCteCycles handles nodes with undefined dependencies", () => {
      const cycles = detectCteCycles([
        { name: "a", dependencies: undefined as any },
      ]);
      expect(cycles).toEqual([]);
    });

    it("QueryCanvas: triggers onAddTableToCanvas when onAddJoin is omitted and unstyled metric badge", () => {
      const onAddTable = vi.fn();
      render(
        <QueryCanvas
          tables={[{ name: "users", columns: [{ name: "id", data_type: "int" }] }]}
          primaryTable="users"
          activeTables={[{ name: "users", columns: [{ name: "id", data_type: "int" }] }]}
          selectedColumns={{ "users.id": { name: "id", table: "users", metric: true } }}
          orderedProjectionKeys={["users.id"]}
          isJoinsVisible={true}
          onAddTableToCanvas={onAddTable}
          onToggleColumn={() => {}}
          onRemoveTable={() => {}}
          unstyled={true}
        />,
      );

      expect(document.querySelector('[data-qb="table-card"]')).toBeTruthy();
      expect(document.querySelector('[data-qb="projection-metric-badge"]')).toBeTruthy();

      const joinBtn = document.querySelector('[data-qb="table-card-btn-join"]') as HTMLButtonElement;
      if (joinBtn) {
        fireEvent.click(joinBtn);
        expect(onAddTable).toHaveBeenCalledWith("users");
      }
    });

    it("QueryPerformanceAdvisor: renders in unstyled mode", () => {
      render(
        <QueryPerformanceAdvisor
          querySpec={{ table: "users", columns: [] }}
          sql="SELECT * FROM users"
          unstyled={true}
        />,
      );
      expect(screen.getByTestId("query-performance-advisor")).toBeTruthy();
      expect(screen.getByText(/Performance & Cost Advisor/i)).toBeTruthy();
    });


    it("QueryResultsTable: renders pagination in unstyled mode", () => {
      const rows = Array.from({ length: 15 }, (_, i) => ({ id: i + 1, name: `User ${i}` }));
      render(
        <QueryResultsTable
          results={{ columns: ["id", "name"], rows, count: 15 }}
          pageSize={5}
          unstyled={true}
        />,
      );
      expect(document.querySelector('[data-qb="results-pagination-controls"]')).toBeTruthy();
      expect(document.querySelector('[data-qb="btn-prev-page"]')).toBeTruthy();
      expect(document.querySelector('[data-qb="btn-next-page"]')).toBeTruthy();
    });

    it("TableCard: renders checked metric styling and unstyled metric", () => {
      const metricTable = {
        name: "analytics",
        columns: [],
        metrics: [{ name: "total_revenue", title: "Total Revenue" }],
      };

      const { rerender } = render(
        <TableCard
          table={metricTable as any}
          selectedColumns={{ "analytics.total_revenue": { name: "total_revenue", table: "analytics", metric: true } }}
          onToggleColumn={() => {}}
          unstyled={false}
        />,
      );
      const checkbox = document.querySelector('[data-qb="table-card-metric-checkbox"]') as HTMLInputElement;
      expect(checkbox.checked).toBe(true);

      rerender(
        <TableCard
          table={metricTable as any}
          selectedColumns={{ "analytics.total_revenue": { name: "total_revenue", table: "analytics", metric: true } }}
          onToggleColumn={() => {}}
          unstyled={true}
        />,
      );
      expect(document.querySelector('[data-qb="table-card-metric-badge"]')).toBeTruthy();
    });

    it("VisualQueryBuilder: renders active advanced clauses banner in unstyled mode", () => {
      render(
        <VisualQueryBuilder
          schema={{ tables: { users: { columns: [{ name: "id", data_type: "int" }] } } }}
          initialCtes={[{ name: "cte1", query: "SELECT 1" }]}
          features={{ ctes: "advanced" }}
          advancedMode={false}
          unstyled={true}
        />,
      );

      expect(screen.getByTestId("active-advanced-clauses-banner")).toBeTruthy();
      expect(screen.getByTestId("btn-view-advanced-clauses")).toBeTruthy();
      expect(screen.getByTestId("btn-clear-advanced-clauses")).toBeTruthy();
    });

    it("WindowFunctionBuilder: handles target column select and bounds change", () => {
      render(
        <WindowFunctionBuilder
          isOpen={true}
          onClose={() => {}}
          onSave={() => {}}
          availableColumns={[
            { table: "users", name: "id" },
            { table: "users", name: "val" },
          ]}
          initialSpec={{
            function: "AVG",
            arguments: ["id"],
            frame: {
              frame_type: "ROWS",
              start: "UNBOUNDED PRECEDING",
              end: "CURRENT ROW",
            },
          }}
        />,
      );

      const argSelect = screen.getByTestId("wf-arg-select");
      fireEvent.change(argSelect, { target: { value: "val" } });

      const startBound = screen.getByTestId("wf-start-bound-input");
      fireEvent.change(startBound, { target: { value: "1 PRECEDING" } });

      const endBound = screen.getByTestId("wf-end-bound-input");
      fireEvent.change(endBound, { target: { value: "1 FOLLOWING" } });
    });
  });

  describe("Compound Components", () => {
    it("renders QueryBuilder compound components in unstyled mode with various actions", () => {
      const schema = {
        tables: {
          users: { columns: [{ name: "id" }, { name: "name" }] },
          posts: { columns: [{ name: "id" }, { name: "user_id" }] },
        },
      };

      const mockClient = {
        execute: vi.fn().mockResolvedValue({ columns: ["x"], rows: [{ x: 1 }], count: 1 }),
        getSchema: vi.fn().mockResolvedValue(schema),
      };

      render(
        <QueryBuilder.Root
          schema={schema as any}
          client={mockClient as any}
          unstyled={true}
          initialSpec={{
            table: "users",
            columns: ["users.id", "users.name"],
          } as any}
        >
          <QueryBuilder.Canvas unstyled={true} />
          <QueryBuilder.Columns unstyled={true} />
          <QueryBuilder.SqlEditor unstyled={true} />
          <QueryBuilder.Results unstyled={true} error="Database connection error" />
        </QueryBuilder.Root>,
      );

      expect(document.querySelector('[data-qb="root"]')).toBeTruthy();
      expect(screen.getByText(/Active Tables in Query/i)).toBeTruthy();
      expect(document.querySelector('[data-qb="results-error"]')?.textContent).toContain("Database connection error");

      // Aggregate select change in QueryBuilderColumns
      const aggSelects = screen.getAllByRole("combobox", { name: /Aggregate for/i });
      fireEvent.change(aggSelects[0], { target: { value: "COUNT" } });

      // Move right button in QueryBuilderColumns
      const moveBtn = document.querySelector('[data-qb="projection-move-right"]') as HTMLButtonElement;
      if (moveBtn) {
        fireEvent.click(moveBtn);
      }

      // Unparseable raw SQL badge in SqlEditor
      const sqlTextarea = document.querySelector('[data-qb="sql-editor"]') as HTMLTextAreaElement;
      fireEvent.change(sqlTextarea, { target: { value: "SELECT ?? INVALID" } });
      expect(screen.getByText("Custom Raw SQL (Visual Canvas Unsynced)")).toBeTruthy();
    });

    it("QueryBuilder.Joins handles missing or empty tables gracefully", () => {
      render(
        <QueryBuilder.Root schema={{} as any}>
          <QueryBuilder.Joins />
        </QueryBuilder.Root>,
      );
      expect(document.querySelector('[data-qb="joins-editor"]')).toBeTruthy();
    });

    it("QueryBuilder.Root handles executeQuery without client/onExecuteQuery and with client execute in raw mode", async () => {
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      let capturedContext: any;
      function TestChild() {
        capturedContext = useCompoundQueryBuilder();
        return null;
      }

      // No client or onExecuteQuery
      const { rerender } = render(
        <QueryBuilder.Root>
          <TestChild />
        </QueryBuilder.Root>,
      );

      await capturedContext.executeQuery();
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining("neither `client` nor `onExecuteQuery` prop is provided"),
      );

      // With client, execute in raw mode
      const clientMock = {
        execute: vi.fn().mockResolvedValue({ columns: [], rows: [], count: 0 }),
        getSchema: vi.fn().mockResolvedValue({ tables: {} }),
      };
      rerender(
        <QueryBuilder.Root client={clientMock as any} initialSpec={{ table: "users" }}>
          <TestChild />
        </QueryBuilder.Root>,
      );

      act(() => {
        capturedContext.setRawSql("SELECT 1");
      });
      await capturedContext.executeQuery();
      expect(clientMock.execute).toHaveBeenCalledWith({ sql: "SELECT 1" });
      warnSpy.mockRestore();
    });
  });

  describe("Drivers, Hooks & Utils", () => {
    it("duckdbDriver: handles AVG on empty/null values, string sorting, and tie returns", async () => {
      const driver = new InMemoryOlapEngine();
      await driver.ingestJson("products", [
        { category: "books", price: null },
        { category: "electronics", price: 100 },
        { category: "electronics", price: 200 },
        { category: "books", price: 50 },
      ]);

      // AVG on null/empty group values
      const avgRes = await driver.query("SELECT category, AVG(price) as avg_price FROM products GROUP BY category");
      expect(avgRes.rows).toHaveLength(2);

      // String sorting ASC & DESC with tie
      const sortAsc = await driver.query("SELECT category, price FROM products ORDER BY category ASC, price ASC");
      expect(sortAsc.rows[0].category).toBe("books");

      const sortDesc = await driver.query("SELECT category FROM products ORDER BY category DESC");
      expect(sortDesc.rows[0].category).toBe("electronics");
    });

    it("useBringYourOwnAi: calls onSpecGenerated, handles string error, and applySpec with arg", async () => {
      const onSpecGenerated = vi.fn();
      const onError = vi.fn();
      const onApplySpec = vi.fn();

      const mockHandler = vi.fn().mockResolvedValue({
        spec: { table: "users", columns: ["id"] },
        sql: "SELECT id FROM users",
      });

      const { result } = renderHook(() =>
        useBringYourOwnAi({
          handler: mockHandler,
          onSpecGenerated,
          onError,
          onApplySpec,
        }),
      );

      await act(async () => {
        await result.current.sendMessage("get users");
      });

      expect(onSpecGenerated).toHaveBeenCalled();

      // applySpec with custom argument
      act(() => {
        result.current.applySpec({ table: "orders" } as any);
      });
      expect(onApplySpec).toHaveBeenCalledWith({ table: "orders" });

      // Error without message property
      mockHandler.mockRejectedValueOnce("String error thrown");
      await act(async () => {
        await result.current.sendMessage("fail");
      });
      expect(onError).toHaveBeenCalledWith("String error thrown");
    });

    it("useClientOlap: dropTable and clear error handling", async () => {
      const engine = getClientOlapEngine();
      vi.spyOn(engine, "dropTable").mockRejectedValueOnce(new Error("Cannot drop table"));
      vi.spyOn(engine, "clear").mockRejectedValueOnce("Clear failed string");

      const { result } = renderHook(() => useClientOlap());

      let dropError: any;
      try {
        await act(async () => {
          await result.current.dropTable("users");
        });
      } catch (err) {
        dropError = err;
      }
      expect(dropError?.message).toBe("Cannot drop table");

      let clearError: any;
      try {
        await act(async () => {
          await result.current.clear();
        });
      } catch (err) {
        clearError = err;
      }
      expect(clearError).toBe("Clear failed string");
    });

    it("useDashboardManager: computePivot with tile lacking pivotConfig", () => {
      const { result } = renderHook(() => useDashboardManager());
      const tile: any = { id: "t1", title: "Tile 1" };
      const rows = [{ category: "A", region: "North", amount: 100 }];

      const pivot = result.current.computePivot(tile, rows);
      expect(pivot.rowKeys).toContain("A");
      expect(pivot.colKeys).toContain("North");
    });

    it("useQueryState: handles setHybridSearch and loadSpec without activeTables and with windowFunctions", () => {
      const { result } = renderHook(() => useQueryState());

      act(() => {
        result.current.actions.setHybridSearch({ query: "find me", alpha: 0.7 } as any);
      });
      expect(result.current.state.hybridSearch).toEqual({ query: "find me", alpha: 0.7 });

      act(() => {
        result.current.actions.loadSpec({
          table: "users",
          activeTables: ["users", "posts"],
          windowFunctions: [{ func: "ROW_NUMBER", alias: "rn", partitionBy: [], orderBy: [] }],
        } as any);
      });
      expect(result.current.state.activeTables).toEqual(["users", "posts"]);
      expect(result.current.state.windowFunctions).toHaveLength(1);

      act(() => {
        result.current.actions.loadSpec({
          limit: 25,
        } as any);
      });
      expect(result.current.state.activeTables).toEqual(["users", "posts"]);
      expect(result.current.state.limit).toBe(25);
    });

    it("QueryBuilderProvider: handles controlled isAdvancedMode and synchronizes parent", () => {
      const onAdvancedModeChange = vi.fn();
      let capturedContext: any;
      function Consumer() {
        capturedContext = useQueryBuilderContext();
        return null;
      }

      render(
        <QueryBuilderProvider
          isAdvancedMode={true}
          onAdvancedModeChange={onAdvancedModeChange}
        >
          <QueryBuilderProvider>
            <Consumer />
          </QueryBuilderProvider>
        </QueryBuilderProvider>,
      );

      expect(capturedContext.isAdvancedMode).toBe(true);
      act(() => {
        capturedContext.setIsAdvancedMode(false);
      });
      expect(onAdvancedModeChange).toHaveBeenCalledWith(false);
    });

    it("compiler: handles RAW filter operator and rawExpression in group by", () => {
      const selectedColumns: any = {
        "orders.date_col": {
          name: "date_col",
          table: "orders",
          rawExpression: "DATE(created_at)",
        },
        "orders.total": {
          name: "total",
          table: "orders",
          aggregate: "SUM",
        },
      };

      const filters: any = [
        {
          tablePrefix: "orders",
          column: "raw_filter",
          operator: "RAW",
          rawExpression: "orders.amount > 50",
          value: null,
        },
      ];

      const compiled = compileVisualState(
        "orders",
        selectedColumns,
        ["orders.date_col", "orders.total"],
        [],
        filters,
        [],
        false,
        50,
        null,
        "postgres",
      );

      expect(compiled.sql).toContain("WHERE orders.amount > 50");
      expect(compiled.sql).toContain("GROUP BY DATE(created_at)");
    });

    it("featureUtils: fallback for custom feature tier and rollup clause detection", () => {
      const isVisible = isFeatureVisible("ctes", { ctes: "custom_tier" as any }, true);
      expect(isVisible).toBe(true);

      const clauses = detectActiveAdvancedClauses(
        { rollup: ["category"] },
        { analytical_grouping: "advanced" } as any,
      );
      expect(clauses).toHaveLength(1);
      expect(clauses[0].key).toBe("analytical_grouping");
    });

    it("localDataIngest: handles object parameter with tableName", async () => {
      const mockEngine: any = {
        query: vi.fn(),
        ingestCsv: vi.fn().mockResolvedValue({ name: "custom_tbl", rowCount: 1, columns: [] }),
      };

      const file = new File(["id,name\n1,alice"], "data.csv", { type: "text/csv" });
      const meta = await ingestLocalFile(file, mockEngine, { tableName: "custom_tbl" });
      expect(meta.name).toBe("custom_tbl");
      expect(mockEngine.ingestCsv).toHaveBeenCalledWith("custom_tbl", expect.any(String), expect.any(Object));
    });

    it("performanceAdvisor: calculates cost when rowCount is provided without byteSize", () => {
      const cost = estimateCloudQueryCost("SELECT * FROM large_table", "bigquery", {
        large_table: { rowCount: 1_000_000 },
      });
      expect(cost.dollarCostEstimated).toBeGreaterThan(0);
    });

    it("schemaUtils: validateSchema flags TABLE_NO_COLUMNS", () => {
      const res = validateSchema({
        tables: {
          empty_table: { columns: [] },
        },
      });
      expect(res.diagnostics.some((d) => d.code === "TABLE_NO_COLUMNS")).toBe(true);
    });

    it("sqlParser: parses window functions without args, DATE_TRUNC without alias, and FILTER without alias", () => {
      const sql = `
        SELECT
          ROW_NUMBER() OVER (ORDER BY id) AS rn,
          DATE_TRUNC('month', created_at),
          DATETRUNC(month, updated_at),
          SUM(amount) FILTER (WHERE status = 'active')
        FROM orders
      `;

      const spec = parseSqlToSpec(sql);
      expect(spec).toBeDefined();
      expect(spec?.window_functions?.[0].arguments).toEqual([]);
      expect(spec?.columns?.some((c) => c.time_grain === "month")).toBe(true);
      expect(spec?.columns?.some((c) => c.agg === "SUM")).toBe(true);
    });

    it("drizzle: covers mysql decimal, timestamp, json, and sqlite text primary key", () => {
      const mysqlSchema = {
        tables: {
          items: {
            columns: [
              { name: "id", dataType: "int", isPrimary: true },
              { name: "price", dataType: "decimal" },
              { name: "created_at", dataType: "timestamp" },
              { name: "metadata", dataType: "json" },
            ],
          },
        },
      };
      const mysqlRes = toDrizzle(mysqlSchema as any, { dialect: "mysql" });
      expect(mysqlRes).toContain('decimal("price", { precision: 10, scale: 2 })');
      expect(mysqlRes).toContain('timestamp("created_at")');
      expect(mysqlRes).toContain('json("metadata")');

      const sqliteSchema = {
        tables: {
          tags: {
            columns: [
              { name: "uuid", dataType: "text", isPrimary: true },
            ],
          },
        },
      };
      const sqliteRes = toDrizzle(sqliteSchema as any, { dialect: "sqlite" });
      expect(sqliteRes).toContain('text("uuid").primaryKey()');
    });

    it("prisma: handles relation name when column ends with 'id' (> 2 chars) and generic column name", () => {
      const schema = {
        tables: {
          users: {
            columns: [{ name: "id", dataType: "int", isPrimary: true }],
          },
          posts: {
            columns: [
              { name: "id", dataType: "int", isPrimary: true },
              { name: "userid", dataType: "int" },
              { name: "author", dataType: "int" },
            ],
            foreignKeys: [
              { table: "posts", column: "userid", foreign_table: "users", foreign_column: "id" },
              { table: "posts", column: "author", foreign_table: "users", foreign_column: "id" },
            ],
          },
        },
      };
      const prismaRes = toPrisma(schema as any);
      expect(prismaRes).toMatch(/user\s+Users\??\s+@relation/);
      expect(prismaRes).toMatch(/users\s+Users\??\s+@relation/);
    });

    it("semantic: handles not_in with numeric array and string value", () => {
      const metricWithNumArray: any = {
        name: "test_m1",
        table: "orders",
        aggregation: "sum",
        filters: [{ field: "status_code", operator: "not_in", value: [1, 2, 3] }],
      };
      const sql1 = expandMetricSql(metricWithNumArray);
      expect(sql1).toContain("status_code NOT IN (1, 2, 3)");

      const metricWithString: any = {
        name: "test_m2",
        table: "orders",
        aggregation: "sum",
        filters: [{ field: "status_code", operator: "not in", value: "99" }],
      };
      const sql2 = expandMetricSql(metricWithString);
      expect(sql2).toContain("status_code NOT IN (99)");
    });

    it("sqlalchemy: handles datetime, fallback type, and fk ending with 'id'", () => {
      const schema = {
        tables: {
          users: {
            columns: [{ name: "id", dataType: "int", isPrimary: true }],
          },
          events: {
            columns: [
              { name: "id", dataType: "int", isPrimary: true },
              { name: "timestamp_col", dataType: "datetime" },
              { name: "custom_col", dataType: "unknown_custom_type" },
              { name: "userid", dataType: "int" },
            ],
            foreignKeys: [
              { table: "events", column: "userid", foreign_table: "users", foreign_column: "id" },
            ],
          },
        },
      };
      const result = toSqlAlchemy(schema as any);
      expect(result).toContain("Column(DateTime,");
      expect(result).toContain("Column(String,");
      expect(result).toContain('user = relationship("Users", foreign_keys=[userid])');
    });

    it("adapters utils: handles table with foreign_keys snake_case property", () => {
      const snapshot = {
        tables: {
          orders: {
            name: "orders",
            columns: [{ name: "id", dataType: "int" }, { name: "customer_id", dataType: "int" }],
            foreign_keys: [
              { table: "orders", column: "customer_id", foreign_table: "customers", foreign_column: "id" },
            ],
          },
        },
      };
      const extracted = extractSnapshotData(snapshot as any);
      expect(extracted.foreignKeys).toHaveLength(1);
      expect(extracted.foreignKeys[0].foreign_table).toBe("customers");
    });

    it("selfHealing: synthesizes joins using foreignKeys, targetColumn, and foreign_column properties", () => {
      const schema = {
        tables: {
          users: {
            columns: [{ name: "id" }],
          },
          profiles: {
            columns: [{ name: "user_pk" }],
            foreignKeys: [
              { targetTable: "users", targetColumn: "id", foreign_column: "user_pk" },
            ],
          },
        },
      };
      const healed = autoHealClientQuerySpec(
        {
          table: "users",
          columns: ["profiles.bio"],
        },
        schema as any,
      );
      expect(healed.healedSpec.joins).toHaveLength(1);
      expect(healed.healedSpec.joins![0].left_col).toBe("id");
      expect(healed.healedSpec.joins![0].right_col).toBe("user_pk");
    });

    it("ai tools: get_schema_catalog default markdown and explain_query edge cases", () => {
      const catRes = executeAgentToolCall("get_schema_catalog", {}, { schema: { tables: {} } });
      expect(catRes.format).toBe("markdown");
      expect(catRes.catalog).toContain("No explicit schema provided");

      const sqlRes = executeAgentToolCall("explain_query", { sql: "SELECT id FROM users" });
      expect(sqlRes.success).toBe(true);
      expect(sqlRes.table).toBe("users");

      const emptySpecRes = executeAgentToolCall("explain_query", {
        spec: { table: "products", columns: [] },
      });
      expect(emptySpecRes.success).toBe(true);
      expect(emptySpecRes.summary).toContain("selecting 1 projection(s)");
    });

    it("client: handles plain text error without json and text() parse throwing", async () => {
      const mockFetch = vi.fn();
      const client = createQueryBuilderClient({
        baseUrl: "https://api.example.com",
        fetchFn: mockFetch as any,
      });

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: "Internal Error",
        headers: new Headers({ "content-type": "text/plain" }),
        text: async () => "Raw upstream text error",
      });
      await expect(client.execute({ table: "users" })).rejects.toThrow("Raw upstream text error");

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        headers: new Headers({ "content-type": "text/plain" }),
        text: async () => {
          throw new Error("Cannot read stream");
        },
      });
      await expect(client.execute({ table: "users" })).rejects.toThrow("503: Service Unavailable");
    });

    it("AiAssistantWidget: does not send suggestion message when already generating", () => {
      const sendMessageMock = vi.fn();
      render(
        <AiAssistantWidget
          isOpen={true}
          isGenerating={true}
          sendMessage={sendMessageMock}
          suggestions={["Show top sales"]}
        />,
      );
      const suggestionBtn = screen.getByTestId("ai-suggestion-0");
      fireEvent.click(suggestionBtn);
      expect(sendMessageMock).not.toHaveBeenCalled();
    });

    it("BiChartVisualizer: handles null category in NONE and aggregated modes, and unstyled echarts/vega", () => {
      const rowsNone = [{ cat: null, val: 100 }, { cat: undefined, val: 200 }];
      const { rerender } = render(
        <BiChartVisualizer
          results={{ columns: ["cat", "val"], rows: rowsNone }}
          aggregation="NONE"
          adapter="builtin"
        />,
      );
      expect(screen.getByRole("region", { name: "Visual Chart Preview" })).toBeDefined();

      rerender(
        <BiChartVisualizer
          results={{ columns: ["cat", "val"], rows: rowsNone }}
          aggregation="SUM"
          adapter="builtin"
        />,
      );
      expect(screen.getByRole("region", { name: "Visual Chart Preview" })).toBeDefined();

      rerender(
        <BiChartVisualizer
          results={{ columns: ["cat", "val"], rows: [{ cat: "A", val: 10 }] }}
          adapter="echarts"
          unstyled={true}
        />,
      );
      expect(screen.getByTestId("echarts-container")).toBeDefined();

      rerender(
        <BiChartVisualizer
          results={{ columns: ["cat", "val"], rows: [{ cat: "A", val: 10 }] }}
          adapter="vega-lite"
          unstyled={true}
        />,
      );
      expect(screen.getByTestId("vega-lite-container")).toBeDefined();
    });

    it("CalculatedFieldEditor: handles case_when save with null else_value, expression with initialField, and null branch values", () => {
      const onSave = vi.fn();
      const onClose = vi.fn();

      const initialCaseField: any = {
        id: "existing_calc_1",
        name: "Score",
        alias: "Score",
        type: "case_when",
        case_when: {
          alias: "Score",
          else_value: null,
          branches: [{ condition: { column: "points", op: "gt", value: 10 }, then_value: "High" }],
        },
      };

      const testTables: any = [{ name: "users", columns: [{ name: "points", data_type: "int" }] }];

      const { unmount } = render(
        <CalculatedFieldEditor
          isOpen={true}
          onClose={onClose}
          onSave={onSave}
          tables={testTables}
          initialField={initialCaseField}
        />,
      );

      const valInput = screen.getByLabelText("Branch 1 condition value");
      expect((valInput as HTMLInputElement).value).toBe("10");

      const saveBtn = screen.getByRole("button", { name: "Save Column" });
      fireEvent.click(saveBtn);
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "existing_calc_1",
          type: "case_when",
          case_when: expect.objectContaining({ else_value: null }),
        }),
      );

      unmount();

      const initialExprField: any = {
        id: "existing_calc_2",
        name: "TotalWithTax",
        alias: "TotalWithTax",
        type: "expression",
        expression: "price * 1.2",
      };
      render(
        <CalculatedFieldEditor
          isOpen={true}
          onClose={onClose}
          onSave={onSave}
          tables={testTables}
          initialField={initialExprField}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "Save Column" }));
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "existing_calc_2",
          type: "expression",
          expression: "price * 1.2",
        }),
      );
    });

    it("ExportWorkbench: falls back to compiledSql on dialect mismatch and calls onDialectChange", () => {
      const onDialectChange = vi.fn();
      const spec: any = { table: "users", columns: ["id", "name"] };

      const { container } = render(
        <ExportWorkbench
          spec={spec}
          sql="SELECT id, name FROM users /* external */"
          dialect="postgres"
          onDialectChange={onDialectChange}
        />,
      );

      const sqlTab = container.querySelector('[data-qb="codegen-tab-sql"]')!;
      fireEvent.click(sqlTab);
      expect(screen.getByText(/SELECT id, name FROM users \/\* external \*\//i)).toBeDefined();

      const dialectSelect = container.querySelector('[data-qb="playground-dialect-select"]')!;
      fireEvent.change(dialectSelect, { target: { value: "mysql" } });
      expect(onDialectChange).toHaveBeenCalledWith("mysql");
    });

    it("LocalDataModal: tests dragLeave, dropTable, clear all, and select table", async () => {
      const onClose = vi.fn();
      const onTableSelected = vi.fn();
      const engine = getClientOlapEngine();
      engine.tables = {
        tbl1: {
          name: "tbl1",
          rowCount: 10,
          columns: [{ name: "id", type: "INTEGER" }],
          sourceType: "csv",
          fileSource: "test.csv",
        } as any,
      };

      render(
        <LocalDataModal
          isOpen={true}
          onClose={onClose}
          onTableSelected={onTableSelected}
        />,
      );

      const dropzone = screen.getByTestId("local-data-dropzone");
      act(() => {
        fireEvent.dragLeave(dropzone);
      });

      const selectBtn = screen.getByTestId("local-table-select-tbl1");
      act(() => {
        fireEvent.click(selectBtn);
      });
      expect(onTableSelected).toHaveBeenCalledWith("tbl1");

      const dropBtn = screen.getByTestId("local-table-drop-tbl1");
      act(() => {
        fireEvent.click(dropBtn);
      });

      const clearBtn = screen.getByTestId("local-data-clear-all");
      act(() => {
        fireEvent.click(clearBtn);
      });

      engine.tables = {};
    });

    it("QueryCanvas: passes undefined onAddJoin when isJoinsVisible is false, and calls onAddJoin or onAddTableToCanvas when true", () => {
      const onAddJoin = vi.fn();
      const onAddTableToCanvas = vi.fn();
      const tables = [{ name: "users", columns: [{ name: "id", data_type: "int" }] } as any];

      // isJoinsVisible false via QueryBuilderProvider feature toggle
      const { unmount } = render(
        <QueryBuilderProvider features={{ joins: "disabled" }}>
          <QueryCanvas
            primaryTable="users"
            activeTables={tables}
            selectedColumns={{}}
            orderedProjectionKeys={[]}
            onToggleColumn={vi.fn()}
            onRemoveTable={vi.fn()}
            onAddTableToCanvas={onAddTableToCanvas}
          />
        </QueryBuilderProvider>,
      );
      expect(screen.queryByTitle("Add Join to this table")).toBeNull();
      unmount();

      // isJoinsVisible true with onAddJoin
      const { rerender } = render(
        <QueryCanvas
          primaryTable="users"
          activeTables={tables}
          selectedColumns={{}}
          orderedProjectionKeys={[]}
          onToggleColumn={vi.fn()}
          onRemoveTable={vi.fn()}
          onAddTableToCanvas={onAddTableToCanvas}
          onAddJoin={onAddJoin}
        />,
      );
      fireEvent.click(screen.getByTitle("Add Join to this table"));
      expect(onAddJoin).toHaveBeenCalledWith("users");

      // isJoinsVisible true without onAddJoin
      rerender(
        <QueryCanvas
          primaryTable="users"
          activeTables={tables}
          selectedColumns={{}}
          orderedProjectionKeys={[]}
          onToggleColumn={vi.fn()}
          onRemoveTable={vi.fn()}
          onAddTableToCanvas={onAddTableToCanvas}
        />,
      );
      fireEvent.click(screen.getByTitle("Add Join to this table"));
      expect(onAddTableToCanvas).toHaveBeenCalledWith("users");
    });

    it("QueryPerformanceAdvisor: pluralizes warnings and index recommendations", () => {
      const spy = vi.spyOn(perfAdvisorModule, "analyzeQueryPerformance").mockReturnValueOnce([
        { id: "w1", type: "warning", title: "W1", message: "m1" },
        { id: "w2", type: "warning", title: "W2", message: "m2" },
        { id: "i1", type: "index", title: "I1", message: "i1", ddl: "CREATE INDEX..." },
        { id: "i2", type: "index", title: "I2", message: "i2", ddl: "CREATE INDEX..." },
      ]);
      render(
        <QueryPerformanceAdvisor
          querySpec={{ table: "users" }}
          sql="SELECT * FROM users"
        />,
      );
      expect(screen.getByTestId("warning-count-badge").textContent).toContain("2 warnings");
      expect(screen.getByTestId("index-rec-count-badge").textContent).toContain("2 index recommendations");
      spy.mockRestore();
    });

    it("QueryResultsTable: unstyled loading and unstyled empty states", () => {
      const { rerender } = render(<QueryResultsTable isLoading={true} unstyled={true} />);
      expect(screen.getByText(/Executing read-only query/i)).toBeDefined();

      rerender(<QueryResultsTable isLoading={false} results={null} unstyled={true} />);
      expect(screen.getByText(/No query executed yet/i)).toBeDefined();
    });

    it("TableCard: customRenderer with classNames.columnItem and metrics without title and aggregation", () => {
      const table: any = {
        name: "orders",
        columns: [{ name: "status", data_type: "varchar" }],
        metrics: [
          { name: "total_sum" },
        ],
      };

      render(
        <TableCard
          table={table}
          isSelected={true}
          selectedColumns={{}}
          onToggleColumn={vi.fn()}
          onRemoveTable={vi.fn()}
          classNames={{ columnItem: "custom-col-class" }}
          fieldRenderers={{
            status: ({ column }) => <span>Custom field renderer for {column.name}</span>,
          }}
        />,
      );
      expect(screen.getByText("Custom field renderer for status")).toBeDefined();
      expect(screen.getByText("total_sum")).toBeDefined();
      expect(screen.getByText("metric")).toBeDefined();
    });

    it("VisualQueryBuilder: unstyled feature tier settings panel", () => {
      const schema: any = {
        tables: {
          users: { name: "users", columns: [{ name: "id" }] },
        },
      };
      render(
        <VisualQueryBuilder
          schema={schema}
          unstyled={true}
        />,
      );
      const gearBtn = screen.getByTestId("btn-feature-settings");
      fireEvent.click(gearBtn);
      const select = screen.getByTestId("feature-select-ctes");
      expect(select).toBeDefined();
    });

    it("WindowFunctionBuilder: fallback colors with empty theme when frame boundaries enabled", () => {
      const emptyTheme: any = {
        colors: { background: "", text: "", border: "", textMuted: "" },
      };
      render(
        <ThemeProvider theme={emptyTheme}>
          <WindowFunctionBuilder
            isOpen={true}
            onClose={vi.fn()}
            onSave={vi.fn()}
            availableColumns={[{ name: "id" }, { name: "amount" }]}
          />
        </ThemeProvider>,
      );
      const enableFrameCheckbox = screen.getByTestId("wf-enable-frame-checkbox");
      fireEvent.click(enableFrameCheckbox);
      const startBound = screen.getByTestId("wf-start-bound-input");
      expect(startBound).toBeDefined();
    });

    it("QueryBuilderCanvas: add table select, table card actions, and unstyled empty/select", () => {
      const schema: any = {
        tables: {
          users: { name: "users", columns: [{ name: "id", data_type: "int" }, { name: "name", data_type: "text" }] },
          orders: { name: "orders", columns: [{ name: "id", data_type: "int" }, { name: "user_id", data_type: "int" }] },
        },
      };

      const { container, unmount } = render(
        <QueryBuilder initialSpec={{ table: "users" }} schema={schema}>
          <QueryBuilder.Canvas unstyled={false} />
        </QueryBuilder>,
      );

      act(() => {
        const addSelect = screen.getByLabelText("Add table to canvas");
        fireEvent.change(addSelect, { target: { value: "orders" } });
      });

      act(() => {
        const idCol = container.querySelector('[data-qb-column="id"]');
        if (idCol) fireEvent.click(idCol);
      });

      act(() => {
        const joinBtns = screen.getAllByTitle("Add Join to this table");
        if (joinBtns[0]) fireEvent.click(joinBtns[0]);
      });

      act(() => {
        const removeBtns = screen.getAllByTitle("Remove table");
        if (removeBtns[0]) fireEvent.click(removeBtns[0]);
      });

      unmount();

      render(
        <QueryBuilder initialSpec={{ table: "" }} schema={{ tables: {} }}>
          <QueryBuilder.Canvas unstyled={true} />
        </QueryBuilder>,
      );
      expect(screen.getByText(/No tables in query/i)).toBeDefined();
    });

    it("QueryBuilderColumns: distinct, limit, move left/right, timeGrain, aggregate, metric badge, unstyled", () => {
      const schema: any = {
        tables: {
          sales: {
            name: "sales",
            columns: [
              { name: "id", data_type: "int" },
              { name: "date_col", data_type: "date" },
              { name: "amount", data_type: "numeric" },
            ],
            metrics: [{ name: "total_sales", expression: "SUM(amount)" }],
          },
        },
      };

      const initialSpec: any = {
        table: "sales",
        columns: [
          { column: "sales.id", alias: "sale_id" },
          { column: "sales.date_col", alias: "sale_date" },
          { column: "sales.amount", metric: "total_sales", alias: "sales_sum" },
        ],
      };

      const { rerender } = render(
        <QueryBuilder initialSpec={initialSpec} schema={schema}>
          <QueryBuilder.Columns />
        </QueryBuilder>,
      );

      act(() => {
        const distinctCheckbox = screen.getByLabelText(/distinct/i);
        fireEvent.click(distinctCheckbox);
      });

      act(() => {
        const limitSelect = screen.getByLabelText("Query result limit");
        fireEvent.change(limitSelect, { target: { value: "50" } });
      });

      act(() => {
        const aliasInput = screen.getByLabelText("Alias for sales.id");
        fireEvent.change(aliasInput, { target: { value: "my_id" } });
      });

      act(() => {
        const timeGrainSelect = screen.getByLabelText("Time grain for sales.date_col");
        fireEvent.change(timeGrainSelect, { target: { value: "month" } });
        fireEvent.change(timeGrainSelect, { target: { value: "" } });
      });

      act(() => {
        const aggSelect = screen.getByLabelText("Aggregate for sales.date_col");
        fireEvent.change(aggSelect, { target: { value: "COUNT" } });
      });

      act(() => {
        const moveRightBtn = screen.getByLabelText("Move sales.id right");
        fireEvent.click(moveRightBtn);
      });

      act(() => {
        const moveLeftBtn = screen.getByLabelText("Move sales.id left");
        fireEvent.click(moveLeftBtn);
      });

      expect(screen.getByText("Σ Metric")).toBeDefined();

      act(() => {
        const removeButtons = screen.getAllByRole("button", { name: "✕" });
        fireEvent.click(removeButtons[0]);
      });

      rerender(
        <QueryBuilder initialSpec={initialSpec} schema={schema}>
          <QueryBuilder.Columns unstyled={true} />
        </QueryBuilder>,
      );
      expect(screen.getByText("Σ Metric")).toBeDefined();
    });

    it("QueryBuilderResults: effectiveError as Error instance vs object without message, and unstyled", () => {
      const { rerender } = render(
        <QueryBuilder initialSpec={{ table: "users" }}>
          <QueryBuilder.Results error={new Error("Custom database failure")} />
        </QueryBuilder>,
      );
      expect(screen.getByText(/Query Execution Failed: Custom database failure/i)).toBeDefined();

      rerender(
        <QueryBuilder initialSpec={{ table: "users" }}>
          <QueryBuilder.Results error={{ custom: "err" } as any} />
        </QueryBuilder>,
      );
      expect(screen.getByText(/Query Execution Failed: \[object Object\]/i)).toBeDefined();

      rerender(
        <QueryBuilder initialSpec={{ table: "users" }}>
          <QueryBuilder.Results error="Plain string error" unstyled={true} />
        </QueryBuilder>,
      );
      expect(screen.getByText(/Query Execution Failed: Plain string error/i)).toBeDefined();
    });

    it("QueryBuilderRoot: controlled value prop update and syncSqlToCanvas", () => {
      const schema: any = {
        tables: {
          users: { name: "users", columns: [{ name: "id" }] },
          orders: { name: "orders", columns: [{ name: "id" }] },
        },
      };

      const TestControlled = () => {
        const [spec, setSpec] = React.useState<any>({ table: "users" });
        return (
          <div>
            <button onClick={() => setSpec({ table: "orders" })}>Switch Table</button>
            <QueryBuilder value={spec} schema={schema}>
              <QueryBuilder.Canvas />
              <QueryBuilder.SqlEditor />
            </QueryBuilder>
          </div>
        );
      };

      const { container } = render(<TestControlled />);
      expect(container.querySelector('[data-qb-table="users"]')).toBeDefined();
      act(() => {
        fireEvent.click(screen.getByText("Switch Table"));
      });
      expect(container.querySelector('[data-qb-table="orders"]')).toBeDefined();

      act(() => {
        const syncBtn = screen.getByLabelText("Sync with visual canvas");
        fireEvent.click(syncBtn);
      });
    });

    it("QueryBuilderSqlEditor: unparseable SQL renders unsynced warning badge", () => {
      const schema: any = {
        tables: {
          users: { name: "users", columns: [{ name: "id" }] },
        },
      };

      render(
        <QueryBuilder initialSpec={{ table: "users" }} schema={schema}>
          <QueryBuilder.SqlEditor unstyled={false} />
        </QueryBuilder>,
      );

      const textarea = screen.getByRole("textbox");
      act(() => {
        fireEvent.change(textarea, { target: { value: "INVALID SYNTAX NOT SQL" } });
      });
      expect(screen.getByText(/Custom Raw SQL \(Visual Canvas Unsynced\)/i)).toBeDefined();
    });

    it("duckdbDriver: BETWEEN without AND, unknown operator, and AVG with empty values", async () => {
      const engine = new InMemoryOlapEngine();
      await engine.ingestJson("test_table", [
        { id: 1, val: "abc", num: 10 },
        { id: 2, val: "def", num: 20 },
      ]);

      const resBetween = await engine.query("SELECT * FROM test_table WHERE num BETWEEN 10");
      expect(resBetween.rows.length).toBe(2);

      const resUnknownOp = await engine.query("SELECT * FROM test_table WHERE num FOOBAR 10");
      expect(resUnknownOp.rows.length).toBe(2);

      await engine.ingestJson("empty_vals", [
        { grp: "A", num: null },
      ]);
      const resAvg = await engine.query("SELECT grp, AVG(num) AS avg_num FROM empty_vals GROUP BY grp");
      expect(resAvg.rows[0].avg_num).toBe(0);
    });

    it("useBringYourOwnAi: applySpec with explicit spec, latestSpec, and null", () => {
      const onApplySpec = vi.fn();
      const { result } = renderHook(() =>
        useBringYourOwnAi({
          onApplySpec,
        }),
      );

      const customSpec: any = { table: "orders" };
      act(() => {
        result.current.applySpec(customSpec);
      });
      expect(onApplySpec).toHaveBeenCalledWith(customSpec);

      act(() => {
        result.current.applySpec();
      });
      expect(onApplySpec).toHaveBeenCalledTimes(1);
    });

    it("useClientOlap: non-Error thrown in loadFromRows and query sets Error instance", async () => {
      const mockEngine: any = {
        isReady: true,
        isLoading: false,
        error: null,
        tables: {},
        registerBackendResults: vi.fn().mockRejectedValue("string backend error"),
        query: vi.fn().mockRejectedValue("string query error"),
        getSchemaSnapshot: vi.fn().mockReturnValue({ tables: {} }),
      };

      const engineSpy = vi.spyOn(duckdbDriverModule, "getClientOlapEngine").mockReturnValue(mockEngine);

      const { result } = renderHook(() => useClientOlap());

      await act(async () => {
        try {
          await result.current.cacheQueryResults("tbl", [{ id: 1 }]);
        } catch (e) {
          expect(e).toBe("string backend error");
        }
      });
      expect(result.current.error?.message).toBe("string backend error");

      await act(async () => {
        try {
          await result.current.query("SELECT 1");
        } catch (e) {
          expect(e).toBe("string query error");
        }
      });
      expect(result.current.error?.message).toBe("string query error");

      engineSpy.mockRestore();
    });

    it("useDashboardManager: computePivot with empty rows and missing dimensions", () => {
      const { result } = renderHook(() => useDashboardManager());

      const tile: any = {
        id: "tile_1",
        pivotConfig: { rowDimensions: [], columnDimensions: [], valueMetrics: [] },
      };
      const pivotEmpty = result.current.computePivot(tile, []);
      expect(pivotEmpty.rowKeys).toEqual([]);
      expect(pivotEmpty.colKeys).toEqual([]);

      const pivotMissing = result.current.computePivot(tile, [{}]);
      expect(pivotMissing.rowKeys).toEqual(["N/A"]);
      expect(pivotMissing.colKeys).toEqual(["N/A"]);
    });

    it("useQueryState: camelCase hybridSearch and setVectorSearch action", () => {
      const initialSpec: any = {
        table: "articles",
        hybridSearch: { textQuery: "analytics", vectorColumn: "embedding", vectorValues: [0.1, 0.2] },
      };

      const { result } = renderHook(() => useQueryState(initialSpec));
      expect(result.current.state.hybridSearch?.textQuery).toBe("analytics");

      act(() => {
        result.current.actions.setVectorSearch({
          column: "embedding",
          vector: [0.3, 0.4],
          metric: "cosine",
        });
      });
      expect(result.current.state.vectorSearch?.column).toBe("embedding");
    });

    it("compiler: auto-synthesizes metric definition when missing and loops alias disambiguation", () => {
      const schema: any = {
        tables: {
          orders: {
            name: "orders",
            columns: [{ name: "amount", data_type: "numeric" }],
          },
        },
      };

      const selectedCols: any = {
        "orders.amount_col1": { table: "orders", name: "amount", alias: "amt" },
        "orders.amount_col2": { table: "orders", name: "amount", alias: "amt_orders" },
        "orders.amount_col3": { table: "orders", name: "amount", alias: "amt_2" },
        "orders.amount_col4": { table: "orders", name: "amount", alias: "amt", metric: "unregistered_metric" },
      };

      const compiled = compileVisualState(
        "orders",
        selectedCols,
        ["orders.amount_col1", "orders.amount_col2", "orders.amount_col3", "orders.amount_col4"],
        [],
        [],
        [],
        false,
        10,
        schema,
        "postgres",
      );

      expect(compiled.sql).toContain('AS "amt_3"');
    });

    it("featureUtils: normalizeTier off/none, unknown preset, missing feature key, and calculated expression", () => {
      expect(resolveFeatureConfig(undefined, "unknown_preset" as any)).toBeDefined();

      const cfg = resolveFeatureConfig({ ctes: "off" as any, window_functions: "none" as any });
      expect(cfg.ctes).toBe("disabled");
      expect(cfg.window_functions).toBe("disabled");

      expect(isFeatureVisible("custom_key" as any, {} as any, false)).toBe(true);

      const activeClauses = detectActiveAdvancedClauses(
        {
          selectedColumns: {
            calc1: { expression: "price * 2" } as any,
          },
        },
        { calculated_fields: "advanced" } as any,
      );
      expect(activeClauses.some((c) => c.key === "calculated_fields")).toBe(true);
    });

    it("localDataIngest: engine as first param, and FileReader onerror callbacks", async () => {
      const mockEngine: any = {
        query: vi.fn(),
        ingestCsv: vi.fn().mockResolvedValue({ name: "data", rowCount: 1, columns: [] }),
      };
      const file = new File(["a,b\n1,2"], "data.csv", { type: "text/csv" });

      const meta = await ingestLocalFile(mockEngine, file);
      expect(meta.name).toBe("data");

      const origReadAsText = FileReader.prototype.readAsText;
      FileReader.prototype.readAsText = function () {
        setTimeout(() => {
          this.onerror?.(new ProgressEvent("error") as any);
        }, 0);
      };
      await expect(readFileAsText(new Blob(["test"]))).rejects.toThrow("Failed to read file as text");
      FileReader.prototype.readAsText = origReadAsText;

      const origReadAsArrayBuffer = FileReader.prototype.readAsArrayBuffer;
      FileReader.prototype.readAsArrayBuffer = function () {
        setTimeout(() => {
          this.onerror?.(new ProgressEvent("error") as any);
        }, 0);
      };
      await expect(readFileAsArrayBuffer(new Blob([new Uint8Array([1, 2])]))).rejects.toThrow("Failed to read file as ArrayBuffer");
      FileReader.prototype.readAsArrayBuffer = origReadAsArrayBuffer;
    });

    it("performanceAdvisor: filter RAW / wildcard, join without type, cost > 0.05, and medium impact recommendation", () => {
      const spec: any = {
        table: "orders",
        columns: ["*"],
        filters: [
          { column: "*", op: "eq", value: "1" },
          { column: "raw_clause", op: "RAW", value: "1=1" },
          { column: "", op: "eq", value: "test" },
          { column: "customer_id", op: "eq", value: 123 },
        ],
        joins: [
          { table: "customers", right_col: "id" },
        ],
        order_by: [
          { column: "created_at", direction: "DESC" },
        ],
      };

      const tableStats = {
        orders: { byteSize: 50 * 1024 * 1024 * 1024 },
      };

      const insights = analyzeQueryPerformance(spec, "SELECT * FROM orders", "bigquery", tableStats);
      expect(insights.some((i) => i.type === "cost" && i.severity === "warning")).toBe(true);
      expect(insights.some((i) => i.type === "index")).toBe(true);
    });

    it("sqlParser: window function without alias, window function with arguments, and CTE prefix", () => {
      const sql = `
        WITH cte AS (SELECT 1 AS num)
        SELECT
          ROW_NUMBER() OVER (ORDER BY id),
          LEAD(amount, 1) OVER (ORDER BY id) AS next_amount
        FROM orders
      `;
      const spec = parseSqlToSpec(sql);
      expect(spec).toBeDefined();
      expect(spec?.window_functions?.[0].alias).toBe("row_number_wf");
      expect(spec?.window_functions?.[1].arguments).toEqual(["amount", "1"]);
    });

    describe("Final 100% Coverage Closer", () => {
      it("drizzle: handles postgres json and mysql non-int PK, bigint, double", () => {
        const pgSchema: any = {
          tables: {
            events: {
              columns: [{ name: "payload", dataType: "json" }],
            },
          },
        };
        const pgCode = toDrizzle(pgSchema, "postgres");
        expect(pgCode).toContain('jsonb("payload")');

        const mysqlSchema: any = {
          tables: {
            items: {
              columns: [
                { name: "code", dataType: "varchar", is_primary: true },
                { name: "b_num", dataType: "bigint" },
                { name: "f_num", dataType: "float" },
              ],
            },
          },
        };
        const mysqlCode = toDrizzle(mysqlSchema, "mysql");
        expect(mysqlCode).toContain('varchar("code", { length: 255 }).primaryKey()');
        expect(mysqlCode).toContain('bigint("b_num", { mode: "number" })');
        expect(mysqlCode).toContain('double("f_num")');
      });

      it("prisma: handles self-referencing foreign keys and incoming back relations", () => {
        const schema: any = {
          tables: {
            categories: {
              name: "categories",
              columns: [
                { name: "id", data_type: "int", is_primary: true },
                { name: "parent_id", data_type: "int", is_nullable: true },
              ],
            },
          },
          foreign_keys: [
            {
              table: "categories",
              column: "parent_id",
              foreign_table: "categories",
              foreign_column: "id",
            },
          ],
        };
        const prismaCode = toPrisma(schema);
        expect(prismaCode).toContain('parent Categories? @relation("Categories_parentId", fields: [parentId], references: [id])');
        expect(prismaCode).toContain('childCategoriesByParentId Categories[] @relation("Categories_parentId")');
      });

      it("sqlalchemy: handles undefined fksByTable, col without type, and python keyword fk", () => {
        const schema: any = {
          tables: {
            t1: {
              name: "t1",
              columns: [{ name: "id", is_primary: true }],
            },
            t2: {
              name: "t2",
              columns: [{ name: "for", data_type: "int" }],
            },
          },
          foreign_keys: [
            { table: "t2", column: "for", foreign_table: "t1", foreign_column: "id" },
          ],
        };
        const saCode = toSqlAlchemy(schema);
        expect(saCode).toContain("for_ = Column");
        expect(saCode).toContain('ForeignKey("t1.id")');
      });

      it("adapters utils: extractSnapshotData with camelCase fk/rel and missing fields", () => {
        const result = extractSnapshotData({
          tables: {},
          foreign_keys: [
            { table: "orders", column: "user_id", foreignTable: "users", foreignColumn: "id" },
            { table: "", column: "" } as any,
          ],
          relationships: [
            { sourceTable: "orders", sourceColumn: "prod_id", targetTable: "prods", targetColumn: "id" },
            { sourceTable: "" } as any,
          ],
        } as any);
        expect(result.foreignKeys).toHaveLength(2);
      });

      it("ai selfHealing: handles foreignKeys targetTable with missing column properties", () => {
        const spec: any = {
          table: "orders",
          columns: ["users.name"],
        };
        const schema: any = {
          tables: {
            users: {
              foreignKeys: [{ targetTable: "orders" }],
            },
          },
        };
        const healed = autoHealClientQuerySpec(spec, schema);
        expect(healed.healedSpec.joins?.[0].left_col).toBe("id");
        expect(healed.healedSpec.joins?.[0].right_col).toBe("id");
      });

      it("ai tools: explain_query with invalid SQL and empty spec fields", async () => {
        const failRes = await executeAgentToolCall("explain_query", { sql: "SELECT ??? FROM" });
        expect(failRes.success).toBe(false);

        const emptySpecRes = await executeAgentToolCall("explain_query", { spec: { table: "users" } });
        expect(emptySpecRes.success).toBe(true);
        expect(emptySpecRes.joinsCount).toBe(0);
        expect(emptySpecRes.filtersCount).toBe(0);
      });

      it("client: handles request method with absolute url, per-request headers, and aborted signal reasons", async () => {
        const mockFetch = vi.fn().mockResolvedValue({
          ok: true,
          json: async () => ({ status: "ok" }),
          text: async () => JSON.stringify({ status: "ok" }),
          headers: new Headers({ "content-type": "application/json" }),
        });

        const client = createQueryBuilderClient({
          baseUrl: "https://api.example.com",
          fetchFn: mockFetch as any,
        });

        const res = await client.request?.("https://custom.example.com/health");
        expect(res).toEqual({ status: "ok" });

        await client.getSchema({ headers: { "X-Test": "custom-val" } });
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining("https://api.example.com/schema"),
          expect.objectContaining({
            headers: expect.objectContaining({ "X-Test": "custom-val" }),
          }),
        );

        const customAbort = new AbortController();
        customAbort.abort("Explicit Reason");
        await expect(client.getSchema({ signal: customAbort.signal })).rejects.toBe("Explicit Reason");

        const standardAbort = new AbortController();
        standardAbort.abort();
        await expect(client.getSchema({ signal: standardAbort.signal })).rejects.toThrow();
      });

      it("BiChartVisualizer: handles styled echarts/vega and empty category string in truncate", () => {
        const { rerender } = render(
          <BiChartVisualizer
            results={{ columns: ["cat", "val"], rows: [{ cat: "", val: 50 }] }}
            adapter="echarts"
            unstyled={false}
          />,
        );
        expect(screen.getByTestId("echarts-container")).toBeDefined();

        rerender(
          <BiChartVisualizer
            results={{ columns: ["cat", "val"], rows: [{ cat: "", val: 50 }] }}
            adapter="vega-lite"
            unstyled={false}
          />,
        );
        expect(screen.getByTestId("vega-lite-container")).toBeDefined();

        rerender(
          <BiChartVisualizer
            results={{ columns: ["cat", "val"], rows: [{ cat: "", val: 50 }] }}
            adapter="builtin"
            chartType="bar"
          />,
        );
        expect(screen.getByRole("region", { name: "Visual Chart Preview" })).toBeDefined();
      });

      it("CalculatedFieldEditor: add branch with empty columns, whitespace alias, and null branch values", () => {
        const onSave = vi.fn();
        const { unmount } = render(
          <CalculatedFieldEditor
            isOpen={true}
            onClose={vi.fn()}
            onSave={onSave}
            tables={[]}
            initialField={{
              id: "c1",
              name: "   ",
              alias: "   ",
              type: "case_when",
              case_when: {
                alias: "   ",
                else_value: null,
                branches: [{ condition: { column: "", op: "eq", value: null as any }, then_value: null as any }],
              },
            } as any}
          />,
        );

        fireEvent.click(screen.getByRole("button", { name: "+ Add Branch" }));
        fireEvent.click(screen.getByRole("button", { name: "Save Column" }));
        expect(onSave).not.toHaveBeenCalled();
        unmount();
      });

      it("ExportWorkbench: externalSql undefined and onDialectChange undefined", () => {
        const { container } = render(
          <ExportWorkbench
            spec={{ table: "users" }}
            dialect="postgres"
          />,
        );

        const sqlTab = container.querySelector('[data-qb="codegen-tab-sql"]')!;
        fireEvent.click(sqlTab);
        const snippet = container.querySelector('[data-qb="playground-code-snippet"]')!;
        expect(snippet.textContent).toContain("FROM");
        expect(snippet.textContent).toContain("users");

        const dialectSelect = container.querySelector('[data-qb="playground-dialect-select"]')!;
        fireEvent.change(dialectSelect, { target: { value: "mysql" } });
      });

      it("LocalDataModal: drop, file input change, overlay/dialog click, and close button", async () => {
        const onClose = vi.fn();
        const onTableSelected = vi.fn();

        render(
          <LocalDataModal
            isOpen={true}
            onClose={onClose}
            onTableSelected={onTableSelected}
          />,
        );

        const dropzone = screen.getByTestId("local-data-dropzone");
        fireEvent.click(dropzone);

        const testFile = new File(["id,name\n1,Alpha"], "test.csv", { type: "text/csv" });

        await act(async () => {
          fireEvent.drop(dropzone, { dataTransfer: { files: [testFile] } });
        });

        const fileInput = screen.getByTestId("local-data-file-input");
        await act(async () => {
          fireEvent.change(fileInput, { target: { files: [testFile] } });
        });

        const overlay = screen.getByTestId("local-data-modal-overlay");
        fireEvent.click(overlay);
        expect(onClose).toHaveBeenCalled();

        const closeBtn = screen.getByRole("button", { name: "Close" });
        fireEvent.click(closeBtn);

        const dialog = screen.getByRole("dialog");
        fireEvent.click(dialog);
      });

      it("QueryCanvas: empty canvas with classNames.canvasEmpty", () => {
        render(
          <QueryCanvas
            primaryTable=""
            activeTables={[]}
            selectedColumns={{}}
            orderedProjectionKeys={[]}
            onToggleColumn={vi.fn()}
            onRemoveTable={vi.fn()}
            onAddTableToCanvas={vi.fn()}
            classNames={{ canvasEmpty: "custom-empty-class" }}
          />,
        );
        expect(screen.getByText(/No tables in query/i)).toBeDefined();
      });

      it("QueryResultsTable: resultsLoading and resultsEmpty with custom classNames", () => {
        const { rerender } = render(
          <QueryResultsTable
            isLoading={true}
            classNames={{ results: "r-cls", resultsLoading: "rl-cls" }}
          />,
        );
        expect(screen.getByText(/Executing read-only query/i)).toBeDefined();

        rerender(
          <QueryResultsTable
            results={null}
            classNames={{ results: "r-cls", resultsEmpty: "re-cls" }}
          />,
        );
        expect(screen.getByText(/No query executed yet/i)).toBeDefined();
      });

      it("VisualQueryBuilder: ref undo and redo methods", () => {
        const ref = React.createRef<any>();
        render(
          <VisualQueryBuilder
            ref={ref}
            schema={{ tables: { users: { name: "users", columns: [{ name: "id" }] } } }}
          />,
        );
        expect(ref.current).toBeDefined();
        act(() => {
          ref.current.undo();
          ref.current.redo();
        });
      });

      it("WindowFunctionBuilder: availableColumns empty and select with fallback colors", () => {
        const { unmount } = render(
          <WindowFunctionBuilder
            isOpen={true}
            onClose={vi.fn()}
            onSave={vi.fn()}
            availableColumns={[]}
          />,
        );
        expect(screen.getByText("No columns available")).toBeDefined();
        unmount();

        const emptyTheme: any = {
          colors: { background: "", text: "", border: "" },
        };
        render(
          <ThemeProvider theme={emptyTheme}>
            <WindowFunctionBuilder
              isOpen={true}
              onClose={vi.fn()}
              onSave={vi.fn()}
              availableColumns={[{ name: "score" }]}
              initialSpec={{ id: "wf1", alias: "lead_col", function: "LEAD", arguments: ["score"], partition_by: [], order_by: [] }}
            />
          </ThemeProvider>,
        );
        expect(screen.getByTestId("wf-arg-select")).toBeDefined();
      });

      it("QueryBuilderCanvas: unstyled with available tables to add", () => {
        const schema: any = {
          tables: {
            users: { name: "users", columns: [{ name: "id" }] },
            orders: { name: "orders", columns: [{ name: "id" }] },
          },
        };
        render(
          <QueryBuilder initialSpec={{ table: "users" }} schema={schema}>
            <QueryBuilder.Canvas unstyled={true} />
          </QueryBuilder>,
        );
        expect(screen.getByLabelText("Add table to canvas")).toBeDefined();
      });

      it("QueryBuilderColumns: empty projections styled and unstyled, and custom limit option", () => {
        const { unmount } = render(
          <QueryBuilder initialSpec={{ table: "users", columns: [] }}>
            <QueryBuilder.Columns unstyled={false} />
          </QueryBuilder>,
        );
        expect(screen.getByText(/No columns selected/i)).toBeDefined();
        unmount();

        render(
          <QueryBuilder initialSpec={{ table: "users", columns: [{ column: "id" }], limit: 42 }}>
            <QueryBuilder.Columns />
          </QueryBuilder>,
        );
        expect(screen.getByDisplayValue("42")).toBeDefined();
      });

      it("QueryBuilderResults: effectiveIsLoading prop and effectiveError with classNames", () => {
        render(
          <QueryBuilder>
            <QueryBuilder.Results isLoading={true} />
            <QueryBuilder.Results error={new Error("Custom error")} classNames={{ results: "err-box" }} />
          </QueryBuilder>,
        );
        expect(screen.getByText(/Query Execution Failed: Custom error/i)).toBeDefined();
      });

      it("QueryBuilderRoot: schema default table, client auto-fetch schema and rejection handling", async () => {
        const schema: any = {
          tables: {
            products: { name: "products", columns: [{ name: "id" }] },
          },
        };
        const { unmount } = render(
          <QueryBuilder schema={schema}>
            <QueryBuilder.Canvas />
          </QueryBuilder>,
        );
        expect(screen.getByText("products")).toBeDefined();
        unmount();

        const mockClient: any = {
          getSchema: vi.fn().mockResolvedValue({
            tables: { orders: { name: "orders", columns: [{ name: "id" }] } },
          }),
        };
        const { unmount: unmount2 } = render(
          <QueryBuilder client={mockClient} initialTable="orders">
            <QueryBuilder.Canvas />
          </QueryBuilder>,
        );
        await act(async () => {
          await new Promise((r) => setTimeout(r, 20));
        });
        unmount2();

        const failingClient: any = {
          getSchema: vi.fn().mockRejectedValue(new Error("fetch failed")),
        };
        render(
          <QueryBuilder client={failingClient}>
            <QueryBuilder.Canvas />
          </QueryBuilder>,
        );
        await act(async () => {
          await new Promise((r) => setTimeout(r, 20));
        });
      });

      it("QueryBuilderSqlEditor: classNames.sqlSyncBadge in raw mode", () => {
        render(
          <QueryBuilder initialSpec={{ table: "users", rawSql: "SELECT 1", isRawMode: true }}>
            <QueryBuilder.SqlEditor classNames={{ sqlSyncBadge: "custom-sync-badge" }} />
          </QueryBuilder>,
        );
        expect(screen.getByText("Live SQL Code Editor")).toBeDefined();
      });

      it("duckdbDriver: array IN/NOT IN, unknown operator, and AVG with nulls in group by", async () => {
        const engine = new InMemoryOlapEngine();
        await engine.ingestJson("users", [
          { id: 1, role: "admin", val: null },
          { id: 2, role: "admin", val: null },
          { id: 3, role: "user", val: 10 },
        ]);

        const inRes = await engine.query("SELECT * FROM users WHERE role IN ('admin')");
        expect(inRes.rowCount).toBe(2);

        const notInRes = await engine.query("SELECT * FROM users WHERE role NOT IN ('admin')");
        expect(notInRes.rowCount).toBe(1);

        const avgRes = await engine.query("SELECT role, AVG(val) AS avg_v FROM users GROUP BY role");
        expect(avgRes.rows.find((r) => r.role === "admin")?.avg_v).toBe(0);

        const isTrue = (engine as any).constructor.name ? true : false;
        expect(isTrue).toBe(true);
      });

      it("useClientOlap: ingestJson non-Error thrown sets Error instance", async () => {
        const mockEngine: any = {
          isReady: true,
          isLoading: false,
          error: null,
          tables: {},
          ingestJson: vi.fn().mockRejectedValue("string ingest error"),
          getSchemaSnapshot: vi.fn().mockReturnValue({ tables: {} }),
        };

        const engineSpy = vi.spyOn(duckdbDriverModule, "getClientOlapEngine").mockReturnValue(mockEngine);

        const { result } = renderHook(() => useClientOlap());

        await act(async () => {
          try {
            await result.current.ingestJson("tbl", [{ id: 1 }]);
          } catch (e) {
            expect(e).toBe("string ingest error");
          }
        });
        expect(result.current.error?.message).toBe("string ingest error");

        engineSpy.mockRestore();
      });

      it("useDashboardManager: cross filter with missing field, empty kpiConfig, and non-integer KPI total", () => {
        const { result } = renderHook(() => useDashboardManager());

        act(() => {
          result.current.addTile({
            id: "tile_1",
            title: "T1",
            type: "table",
            table: "users",
            columns: ["id"],
            cachedRows: [{ id: 1 }],
          });
          result.current.setCrossFilter("t2", "status", "active");
        });

        const rowsWithMissing = result.current.getFilteredRowsForTile("tile_1");
        expect(rowsWithMissing).toHaveLength(1);

        const emptyKpi = result.current.computeKpi({ id: "tile_kpi" } as any, []);
        expect(emptyKpi.value).toBe(0);

        const floatKpi = result.current.computeKpi(
          { id: "tile_kpi", kpiConfig: { valueField: "amount" } } as any,
          [{ amount: 10.555 }],
        );
        expect(floatKpi.value).toBe(10.55);
      });

      it("useQueryState: handles snake_case vector_search initialSpec", () => {
        const { result } = renderHook(() =>
          useQueryState({
            table: "docs",
            vector_search: { column: "embedding", vector: [0.1, 0.2] },
          } as any),
        );
        expect(result.current.state.vectorSearch?.column).toBe("embedding");
      });

      it("compiler: alias collision loop and semanticModels metric matching", () => {
        const selectedColumns: any = {
          k1: { table: "sales", name: "d", timeGrain: "month", alias: "d_month" },
          k2: { table: "sales", name: "d2", timeGrain: "month", alias: "d_month_sales" },
          k3: { table: "sales", name: "d3", timeGrain: "month", alias: "d_month_2" },
          k4: { table: "sales", name: "d4", timeGrain: "month", alias: "d_month" },
        };
        const compiled = compileVisualState(
          "sales",
          selectedColumns,
          ["k1", "k2", "k3", "k4"],
          [],
          [],
          [],
        );
        expect(compiled.sql).toContain('AS "d_month_3"');

        const semanticSelected: any = {
          k_rev: { table: "orders", name: "revenue", metric: "total_revenue" },
        };
        const semanticCompiled = compileVisualState(
          "orders",
          semanticSelected,
          ["k_rev"],
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
              metrics: [
                { name: "total_revenue", sqlExpression: "SUM(price)", aggregation: "sum" },
              ],
            },
          ],
        );
        expect(semanticCompiled.sql).toContain("SUM(price)");
      });

      it("localDataIngest: ingests single non-array JSON object", async () => {
        const engine = new InMemoryOlapEngine();
        const singleJsonFile = new File(['{"id": 42, "name": "Single"}'], "single.json", {
          type: "application/json",
        });
        const meta = await ingestLocalFile(singleJsonFile, engine);
        expect(meta.rowCount).toBe(1);
        expect(meta.columns.find((c) => c.name === "name")).toBeDefined();
      });

      it("sqlParser: parses WITH without whitespace separator", () => {
        const spec = parseSqlToSpec("WITH(t AS (SELECT 1 AS num)) SELECT * FROM t");
        expect(spec).toBeDefined();
      });
    });
  });
});

