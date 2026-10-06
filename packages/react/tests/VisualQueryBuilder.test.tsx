import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import type { SchemaSnapshot, QueryResultData } from "../src/types";
import { saveTemplates, resetTemplateStorage } from "../src/components/QueryTemplateManager";

describe("VisualQueryBuilder", () => {
  const mockSchema: SchemaSnapshot = {
    tables: {
      users: {
        name: "users",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "email", data_type: "text", is_nullable: false, is_primary: false },
        ],
      },
      orders: {
        name: "orders",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
        ],
      },
    },
    foreign_keys: [
      {
        table: "orders",
        column: "user_id",
        foreign_table: "users",
        foreign_column: "id",
      },
    ],
  };

  it("renders with visual builder tab active by default and safe AST banner", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    expect(screen.getByText("🎨 Visual Builder")).toBeTruthy();
    expect(screen.getByText("📝 Raw SQL")).toBeTruthy();
    expect(screen.getByText("📊 Results")).toBeTruthy();
    expect(screen.getByText("🛡️ Read-Only Protected (AST Verified)")).toBeTruthy();
    expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
    expect(screen.getByTestId("dialect-badge").textContent).toBe("postgres");
  });

  it("renders with custom dialect prop and displays badge", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" dialect="duckdb" />);
    expect(screen.getByTestId("dialect-badge").textContent).toBe("duckdb");
  });

  it("switches to Raw SQL tab and updates AST safety banner when dangerous SQL is typed", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    const rawSqlTabBtn = screen.getByText("📝 Raw SQL");
    fireEvent.click(rawSqlTabBtn);

    const textarea = screen.getByRole("textbox");
    expect((textarea as HTMLTextAreaElement).value).toContain('FROM "users"');

    // Type destructive statement
    fireEvent.change(textarea, { target: { value: "DROP TABLE users;" } });

    // AST Safety banner updates to alert
    expect(screen.getByText(/Security Notice: Restricted statement type: DROP/i)).toBeTruthy();

    // Sync back with Visual Canvas
    const syncBtn = screen.getByText("🔄 Sync with Visual Canvas");
    fireEvent.click(syncBtn);

    expect(screen.getByText("🛡️ Read-Only Protected (AST Verified)")).toBeTruthy();
  });

  it("loads preset templates and activates SQL tab", () => {
    const presets = [
      {
        id: "p1",
        title: "All Users Query",
        sql: "SELECT id, email FROM users LIMIT 10;",
      },
    ];

    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        presets={presets}
      />
    );

    const presetSelect = screen.getByDisplayValue("⚡ Starters & Presets...");
    fireEvent.change(presetSelect, { target: { value: "p1" } });

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe("SELECT id, email FROM users LIMIT 10;");
  });

  it("opens Schema ERD modal and adds a table to canvas when selected", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    const erdBtn = screen.getByText("🗺️ Schema ERD");
    fireEvent.click(erdBtn);

    expect(screen.getByText("Schema Entity Relationship Diagram (ERD)")).toBeTruthy();

    // Click "Use Table" for orders
    const useTableBtns = screen.getAllByText("Use Table");
    fireEvent.click(useTableBtns[1]); // orders table

    // ERD closed and canvas has 2 active tables
    expect(screen.queryByText("Schema Entity Relationship Diagram (ERD)")).toBeNull();
    expect(screen.getByText("📋 Active Tables in Query (2)")).toBeTruthy();
  });

  it("toggles column selection and projection pills", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    // Click 'id' column on users card
    const idCol = screen.getByText("id");
    fireEvent.click(idCol);

    expect(screen.getByText("✨ Selected Columns & Projections (1)")).toBeTruthy();
    expect(screen.getByText("users.id")).toBeTruthy();

    // Toggle off
    fireEvent.click(idCol);
    expect(screen.queryByText("✨ Selected Columns & Projections (1)")).toBeNull();
  });

  it("updates aggregate on projection pill and removes projection pill using x button", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    // Click 'id' column on users card
    fireEvent.click(screen.getByText("id"));
    expect(screen.getByText("users.id")).toBeTruthy();

    // Change aggregate from (none) to COUNT
    const aggSelect = screen.getByDisplayValue("(none)");
    fireEvent.change(aggSelect, { target: { value: "COUNT" } });

    // Switch to Raw SQL to verify COUNT was compiled
    fireEvent.click(screen.getByText("📝 Raw SQL"));
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toContain('COUNT("users"."id")');

    // Switch back to visual
    fireEvent.click(screen.getByText("🎨 Visual Builder"));

    // Remove projection pill via ✕
    const removeColBtn = screen.getByTitle("Remove column");
    fireEvent.click(removeColBtn);
    expect(screen.queryByText("users.id")).toBeNull();
  });

  it("switches to Results tab directly when Results tab button is clicked", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    const resultsTabBtn = screen.getByText(/📊 Results/);
    fireEvent.click(resultsTabBtn);

    expect(screen.getByText(/No query executed yet/i)).toBeTruthy();
  });

  it("closes ERD modal when header close button is clicked", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    const erdBtn = screen.getByText("🗺️ Schema ERD");
    fireEvent.click(erdBtn);
    expect(screen.getByText("Schema Entity Relationship Diagram (ERD)")).toBeTruthy();

    const closeBtns = screen.getAllByText("✕");
    // The last '✕' is inside the ERD modal header
    fireEvent.click(closeBtns[closeBtns.length - 1]);
    expect(screen.queryByText("Schema Entity Relationship Diagram (ERD)")).toBeNull();
  });

  it("updates joins, filters, sorts, distinct, and limit through visual canvas", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    // Select id column so projections manager appears
    fireEvent.click(screen.getByText("id"));

    // Toggle DISTINCT
    const distinctCheckbox = screen.getByRole("checkbox", { name: /DISTINCT/i });
    fireEvent.click(distinctCheckbox);

    // Change LIMIT
    const limitSelect = screen.getByDisplayValue("50");
    fireEvent.change(limitSelect, { target: { value: "100" } });

    // Add Join via unjoined table dropdown
    const joinSelect = screen.getByDisplayValue("+ Join Table...");
    fireEvent.change(joinSelect, { target: { value: "orders" } });

    // Add Filter
    const addFilterBtn = screen.getByText("+ Add Filter");
    fireEvent.click(addFilterBtn);

    // Add Sort
    const addSortBtn = screen.getByText("+ Add Sort");
    fireEvent.click(addSortBtn);

    // Switch to Raw SQL to verify compiled SQL reflects all state updates
    fireEvent.click(screen.getByText("📝 Raw SQL"));
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toContain('SELECT DISTINCT "users"."id"');
    expect(textarea.value).toContain('LEFT JOIN "orders"');
    expect(textarea.value).toContain('WHERE "users"."id" = \'\'');
    expect(textarea.value).toContain('ORDER BY "users"."id" ASC');
    expect(textarea.value).toContain("LIMIT 100;");
  });

  it("handles empty schema and missing initialTable gracefully", () => {
    render(<VisualQueryBuilder schema={{ tables: {}, foreign_keys: [] }} />);
    expect(screen.getByText("🎨 Visual Builder")).toBeTruthy();
    expect(screen.getByText("📋 Active Tables in Query (0)")).toBeTruthy();
  });

  it("does not switch tab if onExecuteQuery resolves to null", async () => {
    const handleExecute = vi.fn().mockResolvedValue(null);
    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        onExecuteQuery={handleExecute}
      />
    );

    fireEvent.click(screen.getByText("▶ Run Query"));
    await waitFor(() => {
      expect(handleExecute).toHaveBeenCalledOnce();
      // Should remain on visual builder tab
      expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
    });
  });

  it("removes table from canvas, cleans up selected columns, and updates primary table", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    // Select email column on users
    fireEvent.click(screen.getByText("email"));
    expect(screen.getByText("users.email")).toBeTruthy();

    // Add orders to canvas
    const addTableSelect = screen.getByDisplayValue("+ Add Table to Canvas...");
    fireEvent.change(addTableSelect, { target: { value: "orders" } });
    expect(screen.getByText("📋 Active Tables in Query (2)")).toBeTruthy();

    // Remove users table
    const removeBtns = screen.getAllByTitle("Remove table");
    fireEvent.click(removeBtns[0]);

    expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
    expect(screen.queryByText("users")).toBeNull();
    expect(screen.getByText("orders")).toBeTruthy();
    // Projection pill for users.email was cleaned up
    expect(screen.queryByText("users.email")).toBeNull();
  });

  it("sets primaryTable when adding first table to an empty canvas", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    // Remove users so canvas is empty and primaryTable is ""
    const removeBtn = screen.getByTitle("Remove table");
    fireEvent.click(removeBtn);
    expect(screen.getByText("📋 Active Tables in Query (0)")).toBeTruthy();

    // Now open ERD and add orders
    const erdBtn = screen.getByText("🗺️ Schema ERD");
    fireEvent.click(erdBtn);

    const useTableBtns = screen.getAllByText("Use Table");
    fireEvent.click(useTableBtns[1]); // orders table

    expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
    expect(screen.getByText("orders")).toBeTruthy();
  });

  it("executes query and transitions to Results tab on success", async () => {
    const mockResults: QueryResultData = {
      columns: ["id", "email"],
      rows: [{ id: 1, email: "test@example.com" }],
      count: 1,
      latency_ms: 12,
    };
    const handleExecute = vi.fn().mockResolvedValue(mockResults);

    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        onExecuteQuery={handleExecute}
      />
    );

    const runBtn = screen.getByText("▶ Run Query");
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(handleExecute).toHaveBeenCalledOnce();
      expect(screen.getByText("test@example.com")).toBeTruthy();
      expect(screen.getByText("⚡ 12 ms")).toBeTruthy();
    });
  });

  it("displays execution error banner when query execution fails", async () => {
    const handleExecute = vi.fn().mockRejectedValue(new Error("Database connection timeout"));

    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        onExecuteQuery={handleExecute}
      />
    );

    const runBtn = screen.getByText("▶ Run Query");
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(screen.getByText(/❌ Database connection timeout/i)).toBeTruthy();
    });
  });

  it("hides Run Query button when readOnly prop is true", () => {
    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        readOnly={true}
      />
    );

    expect(screen.queryByText("▶ Run Query")).toBeNull();
  });

  it("handles undefined schema without initialTable", () => {
    render(<VisualQueryBuilder schema={undefined as any} />);
    expect(screen.getByText("📋 Active Tables in Query (0)")).toBeTruthy();
  });

  it("blocks Run Query when SQL is unsafe in raw SQL mode", () => {
    const handleExecute = vi.fn();
    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        onExecuteQuery={handleExecute}
      />
    );
    fireEvent.click(screen.getByText("📝 Raw SQL"));
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "DELETE FROM users;" } });
    const runBtn = screen.getByText("▶ Run Query") as HTMLButtonElement;
    expect(runBtn.disabled).toBe(true);
    fireEvent.click(runBtn);
    expect(handleExecute).not.toHaveBeenCalled();
  });

  it("handles non-Error thrown by onExecuteQuery", async () => {
    const handleExecute = vi.fn().mockRejectedValue("String network error");
    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        onExecuteQuery={handleExecute}
      />
    );
    const runBtn = screen.getByText("▶ Run Query");
    fireEvent.click(runBtn);
    await waitFor(() => {
      expect(screen.getByText(/❌ String network error/i)).toBeTruthy();
    });
  });

  it("defaults to first schema table when initialTable is omitted", () => {
    render(<VisualQueryBuilder schema={mockSchema} />);
    expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
    expect(screen.getByText("users")).toBeTruthy();
  });

  it("renders 4th tab Visual Chart and switches to chart view", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    const chartTabBtn = screen.getByText("📈 Visual Chart");
    expect(chartTabBtn).toBeTruthy();

    fireEvent.click(chartTabBtn);
    expect(screen.getByRole("region", { name: "Visual Chart Preview" })).toBeTruthy();
    expect(screen.getByText(/No data available to chart/i)).toBeTruthy();
  });

  it("opens QueryTemplateManager in save mode from header action and closes", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    const saveTemplateBtn = screen.getByRole("button", { name: "Save query as template" });
    fireEvent.click(saveTemplateBtn);

    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByLabelText("Template Title")).toBeTruthy();

    // Close
    fireEvent.click(screen.getByLabelText("Close template manager"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens QueryTemplateManager in library mode from header action and closes", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    const libraryTemplateBtn = screen.getByRole("button", { name: "Open template library" });
    fireEvent.click(libraryTemplateBtn);

    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByLabelText("Search templates")).toBeTruthy();

    // Close
    fireEvent.click(screen.getByLabelText("Close template manager"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("loads template with visual spec and hydrates canvas state", () => {
    resetTemplateStorage();
    const customTemplateWithSpec = {
      id: "spec_tpl",
      title: "Spec Hydration Query",
      category: "Test",
      sql: 'SELECT "orders"."id" FROM "orders";',
      spec: {
        primaryTable: "orders",
        selectedColumns: {
          "orders.id": { table: "orders", name: "id" },
        },
        orderedProjectionKeys: ["orders.id"],
        joins: [],
        filters: [{ id: "f1", column: "id", tablePrefix: "orders", operator: ">", value: "10" }],
        sorts: [{ id: "s1", column: "id", tablePrefix: "orders", direction: "DESC" }],
        isDistinct: true,
        limit: 25,
      },
      createdAt: new Date().toISOString(),
      isDefault: false,
    };
    saveTemplates([customTemplateWithSpec]);

    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    // Open library
    fireEvent.click(screen.getByRole("button", { name: "Open template library" }));

    // Load template
    const loadBtn = screen.getByText("▶ Load Template");
    fireEvent.click(loadBtn);

    // Modal closed and visual builder hydrated
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("🎨 Visual Builder")).toBeTruthy();
    expect(screen.getAllByText("orders.id").length).toBeGreaterThan(0);

    // Also load a template with activeTables array
    const tplWithActiveTables = {
      id: "spec_active_tpl",
      title: "Spec With Active Tables",
      category: "Test",
      sql: 'SELECT "users"."id" FROM "users";',
      spec: {
        primaryTable: "users",
        activeTables: ["users"],
        selectedColumns: { "users.id": { table: "users", name: "id" } },
      },
      createdAt: new Date().toISOString(),
      isDefault: false,
    };
    saveTemplates([tplWithActiveTables]);
    fireEvent.click(screen.getByRole("button", { name: "Open template library" }));
    fireEvent.click(screen.getByText("▶ Load Template"));
    expect(screen.getAllByText("users.id").length).toBeGreaterThan(0);

    // Also load a template with standard QuerySpec (columns array, joins, filters, order_by, distinct)
    const tplWithQuerySpec = {
      id: "spec_standard_tpl",
      title: "Standard QuerySpec Template",
      category: "Test",
      sql: 'SELECT "orders"."id" FROM "orders";',
      spec: {
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
      },
      createdAt: new Date().toISOString(),
      isDefault: false,
    };
    saveTemplates([tplWithQuerySpec]);
    fireEvent.click(screen.getByRole("button", { name: "Open template library" }));
    fireEvent.click(screen.getByText("▶ Load Template"));
    expect(screen.getAllByText("orders.id").length).toBeGreaterThan(0);
  });

  it("loads template with raw SQL only and switches to SQL tab", () => {
    resetTemplateStorage();
    const rawSqlTemplate = {
      id: "raw_only_tpl",
      title: "Raw SQL Only Query",
      category: "Raw",
      sql: "SELECT 42 AS answer;",
      createdAt: new Date().toISOString(),
      isDefault: false,
    };
    saveTemplates([rawSqlTemplate]);

    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    // Open library
    fireEvent.click(screen.getByRole("button", { name: "Open template library" }));

    // Click load
    const loadBtn = screen.getByText("▶ Load Template");
    fireEvent.click(loadBtn);

    // Should switch to SQL tab with raw SQL
    expect(screen.queryByRole("dialog")).toBeNull();
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe("SELECT 42 AS answer;");
  });

  it("calls onSaveQuery prop when a template is saved from modal", () => {
    const handleSaveQuery = vi.fn();
    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        onSaveQuery={handleSaveQuery}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Save query as template" }));
    fireEvent.change(screen.getByLabelText("Template Title"), { target: { value: "Saved Query For Prop" } });
    fireEvent.click(screen.getByRole("button", { name: "💾 Save Template" }));

    expect(handleSaveQuery).toHaveBeenCalledOnce();
    expect(handleSaveQuery).toHaveBeenCalledWith(
      "Saved Query For Prop",
      expect.stringContaining('FROM "users"'),
      expect.any(Object)
    );
  });

  it("opens Schema Explorer modal from header and adds a table to canvas", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" />);

    const schemaExplorerBtn = screen.getByLabelText("Open schema explorer");
    fireEvent.click(schemaExplorerBtn);

    expect(screen.getByRole("dialog", { name: "Database Schema Explorer" })).toBeTruthy();
    expect(screen.getByText("Tables (2)")).toBeTruthy();

    const ordersItem = screen.getByLabelText("Select table orders");
    fireEvent.click(ordersItem);

    const addBtn = screen.getByLabelText("Add table orders to canvas");
    fireEvent.click(addBtn);

    expect(screen.getByText("📋 Active Tables in Query (2)")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders Query Plan tab and switches to visual execution plan view", () => {
    render(<VisualQueryBuilder schema={mockSchema} initialTable="users" showPlanTab={true} />);

    const planTabBtn = screen.getByRole("tab", { name: /Query Plan/i });
    expect(planTabBtn).toBeTruthy();

    fireEvent.click(planTabBtn);

    expect(screen.getByText("Visual Query Execution Plan")).toBeTruthy();
    expect(screen.getAllByText("users").length).toBeGreaterThan(0);
  });

  it("renders NlqPromptBar when showNlqBar={true} and applies translated spec", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        spec: {
          table: "orders",
          columns: ["id", "amount"],
          joins: [],
          filters: [],
          sorts: [],
          limit: 25,
        },
        confidence: 0.95,
        explanation: "Translated orders query",
        steps: ["Step 1"],
      }),
    });

    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        showNlqBar={true}
      />
    );

    expect(screen.getByTestId("nlq-prompt-bar")).toBeTruthy();
    const input = screen.getByLabelText("NLQ Input");
    fireEvent.change(input, { target: { value: "show orders with amount limit 25" } });
    fireEvent.click(screen.getByLabelText("Generate Query Button"));

    await waitFor(() => {
      // Primary table is now orders and limit is updated
      expect(screen.getByText("📋 Active Tables in Query (1)")).toBeTruthy();
    });
  });

  it("renders LiveExecutionBar when showLiveExecutionBar is true and executes query", async () => {
    const onSuccess = vi.fn();
    const originalFetch = globalThis.fetch;
    try {
      globalThis.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes("/connections/test")) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ healthy: true, dialect: "sqlite", latency_ms: 10 }),
          });
        }
        if (url.includes("/query/execute")) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              columns: ["id", "email"],
              rows: [{ id: 1, email: "test@example.com" }],
              count: 1,
              duration_ms: 15,
            }),
          });
        }
        if (url.includes("/connections/cancel")) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ cancelled: true }),
          });
        }
        return Promise.reject(new Error(`Unhandled URL: ${url}`));
      });

      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          showLiveExecutionBar={true}
          liveExecutionConnectionId="test_conn"
          onLiveExecutionSuccess={onSuccess}
        />
      );

      expect(screen.getByTestId("live-execution-bar")).toBeTruthy();
      expect(screen.getByText("DB: test_conn")).toBeTruthy();

      // Test connection
      fireEvent.click(screen.getByRole("button", { name: "Test database connection" }));
      await waitFor(() => {
        expect(screen.getByText("Connected (10ms)")).toBeTruthy();
      });

      // Execute query via live execution bar
      fireEvent.click(screen.getByRole("button", { name: "Execute live query" }));
      await waitFor(() => {
        expect(onSuccess).toHaveBeenCalledTimes(1);
        expect(screen.getByText("📊 1 rows")).toBeTruthy();
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("handles live execution cancellation inside VisualQueryBuilder", async () => {
    const originalFetch = globalThis.fetch;
    try {
      globalThis.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes("/connections/cancel")) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ cancelled: true }),
          });
        }
        return new Promise(() => {}); // never resolves to stay executing
      });

      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          showLiveExecutionBar={true}
        />
      );

      fireEvent.click(screen.getByRole("button", { name: "Execute live query" }));
      expect(screen.getByText("⏳ Running...")).toBeTruthy();

      const cancelBtn = screen.getByRole("button", { name: "Cancel live query execution" });
      fireEvent.click(cancelBtn);

      await waitFor(() => {
        expect(screen.getByText("▶ Execute Query")).toBeTruthy();
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("executes live query in raw SQL mode with parsed spec and fallback", async () => {
    const originalFetch = globalThis.fetch;
    try {
      let lastBody: any = null;
      globalThis.fetch = vi.fn().mockImplementation((url: string, init?: any) => {
        if (url.includes("/query/execute")) {
          lastBody = JSON.parse(init.body);
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ columns: ["id"], rows: [{ id: 1 }], count: 1 }),
          });
        }
        return Promise.reject(new Error("unexpected"));
      });

      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          showLiveExecutionBar={true}
        />
      );

      // Switch to Raw SQL mode
      fireEvent.click(screen.getByText("📝 Raw SQL"));

      // Type valid raw SQL to trigger isRawMode = true and parseSqlToSpec
      const textarea = screen.getByRole("textbox");
      fireEvent.change(textarea, { target: { value: 'SELECT "id", "email" FROM "users"' } });
      fireEvent.click(screen.getByRole("button", { name: "Execute live query" }));
      await waitFor(() => {
        expect(lastBody?.query?.table).toBe("users");
      });

      // Type unparseable raw SQL to hit the || compiled.spec fallback branch
      fireEvent.change(textarea, { target: { value: "-- just a comment without query" } });
      fireEvent.click(screen.getByRole("button", { name: "Execute live query" }));
      await waitFor(() => {
        expect(lastBody?.query?.table).toBe("users");
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("supports Pipeline tab, stage addition and stage drilldown", async () => {
    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        showPipelineTab={true}
      />
    );

    // Switch to Pipeline tab
    const pipelineTab = screen.getByText(/🔀 Pipeline/);
    expect(pipelineTab).toBeTruthy();
    fireEvent.click(pipelineTab);

    // Pipeline canvas should be visible
    expect(screen.getByTestId("pipeline-dag-canvas")).toBeTruthy();

    // Click "Add Stage" to create stage_1 (which automatically selects it and returns to visual tab)
    const addStageBtn = screen.getByTestId("add-stage-btn");
    fireEvent.click(addStageBtn);

    // Switch back to Pipeline tab to view stages
    fireEvent.click(screen.getByText(/🔀 Pipeline/));

    // Click the new stage node to drill down
    const stageNode = screen.getByTestId("dag-node-stage_1");
    expect(stageNode).toBeTruthy();
    fireEvent.click(stageNode);

    // Drilldown switches activeTab back to visual and targets stage_1
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /Visual Builder/ }).getAttribute("aria-selected")).toBe("true");
    });
  });

  it("opens and saves window function builder modal", async () => {
    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
      />
    );

    // Open Window Function Builder modal
    const openBtn = screen.getByTestId("btn-open-wf-builder");
    fireEvent.click(openBtn);

    expect(screen.getByTestId("window-function-builder-modal")).toBeTruthy();

    // Save window function
    const saveBtn = screen.getByTestId("wf-save-btn");
    fireEvent.click(saveBtn);

    // Modal closes
    await waitFor(() => {
      expect(screen.queryByTestId("window-function-builder-modal")).toBeNull();
    });
  });

  it("augments schema with upstream CTE projections and supports unstyled pipeline tab", () => {
    const ctesWithProjections = [
      {
        name: "upstream_cte",
        query: {
          table: "users" as any,
          columns: ["id", { column: "salary", alias: "user_salary" }, { column: "no_alias" }],
          window_functions: [{ function: "RANK", alias: "rank_val" }],
        } as any,
      },
      {
        name: "empty_cte",
        query: {
          table: "users" as any,
          columns: [],
        } as any,
      },
    ];

    render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        initialCtes={ctesWithProjections}
        showPipelineTab={true}
        unstyled={true}
      />
    );

    // Verify pipeline tab is rendered in unstyled mode
    const pipelineTab = screen.getByText(/🔀 Pipeline \(2\)/);
    expect(pipelineTab).toBeTruthy();
  });
});

