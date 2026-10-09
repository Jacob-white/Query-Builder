import React from "react";
import { render, screen, fireEvent, waitFor, renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  getAgentToolDefinitions,
  executeAgentToolCall,
  autoHealClientQuerySpec,
  useBringYourOwnAi,
  AiAssistantWidget,
} from "../src/ai";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import type { QuerySpec, DatabaseSchemaDefinition } from "../src/types";
import type { SchemaDict } from "./helpers/partial";
import { invalid } from "./helpers";
import type { ByoAiHandler, ByoAiResponse } from "../src/ai/types";

describe("BYO-AI Agent Tool Definitions & Execution", () => {
  it("generates agent tool definitions for all supported formats", () => {
    const openaiTools = getAgentToolDefinitions("openai");
    expect(openaiTools.length).toBe(4);
    expect(openaiTools[0].type).toBe("function");
    expect(openaiTools[0].function.name).toBe("build_query");

    const anthropicTools = getAgentToolDefinitions("anthropic");
    expect(anthropicTools.length).toBe(4);
    expect(anthropicTools[0].name).toBe("build_query");
    expect(anthropicTools[0].input_schema).toBeDefined();

    const geminiTools = getAgentToolDefinitions("gemini");
    expect(geminiTools.length).toBe(4);
    expect(geminiTools[0].name).toBe("build_query");
    expect(geminiTools[0].parameters).toBeDefined();

    const langchainTools = getAgentToolDefinitions("langchain");
    expect(langchainTools.length).toBe(4);
    expect(langchainTools[0].args_schema).toBeDefined();

    const mcpTools = getAgentToolDefinitions("mcp");
    expect(mcpTools.length).toBe(4);
    expect(mcpTools[0].inputSchema).toBeDefined();

    expect(() => getAgentToolDefinitions(invalid<"openai">("unsupported"))).toThrow(
      /Unsupported agent tool format 'unsupported'/
    );
  });

  const mockSchema: SchemaDict = {
    tables: {
      users: {
        columns: {
          id: { data_type: "int" },
          email: { data_type: "text" },
          role: { data_type: "text" },
        },
      },
      orders: {
        columns: {
          id: { data_type: "int" },
          user_id: { data_type: "int" },
          total: { data_type: "float" },
        },
        foreign_keys: [
          { target_table: "users", target_column: "id", column: "user_id" },
        ],
      },
    },
  };

  it("executes build_query tool call correctly", () => {
    // Missing intent
    const errRes = executeAgentToolCall("build_query", {});
    expect(errRes.success).toBe(false);
    expect(errRes.error).toMatch(/Missing required argument 'intent'/);

    // Matching schema table from intent
    const res = executeAgentToolCall(
      "build_query",
      JSON.stringify({ intent: "Find top orders by total", limit: 10 }),
      { schema: mockSchema, dialect: "postgres" }
    );
    expect(res.success).toBe(true);
    expect(res.tool).toBe("build_query");
    expect(res.spec!.table).toBe("orders");
    expect(res.spec!.limit).toBe(10);
    expect(res.sql).toContain("orders");

    // Custom onCompile callback
    const customRes = executeAgentToolCall(
      "build_query",
      { intent: "Find all users" },
      {
        schema: mockSchema,
        onCompile: (spec, dialect) => `SELECT * FROM ${spec.table} -- ${dialect}`,
      }
    );
    expect(customRes.success).toBe(true);
    expect(customRes.sql).toBe("SELECT * FROM users -- postgres");

    // Matching array schema
    const arrRes = executeAgentToolCall(
      "build_query",
      { intent: "Find invoices" },
      { schema: [{ name: "invoices" }] }
    );
    expect(arrRes.spec!.table).toBe("invoices");

    // Matching dict schema
    const dictRes = executeAgentToolCall(
      "build_query",
      { intent: "Find customers" },
      { schema: { customers: {} } }
    );
    expect(dictRes.spec!.table).toBe("customers");

    // Unmatched words in intent defaults to users
    const unmatchRes = executeAgentToolCall(
      "build_query",
      { intent: "Something completely different" },
      { schema: mockSchema }
    );
    expect(unmatchRes.spec!.table).toBe("users");
  });

  it("executes validate_and_compile_query tool call", () => {
    // Missing both spec and sql
    const errRes = executeAgentToolCall("validate_and_compile_query", {});
    expect(errRes.success).toBe(false);

    // With raw SQL
    const sqlRes = executeAgentToolCall("validate_and_compile_query", {
      sql: "SELECT id, email FROM users WHERE id > 5 LIMIT 20",
    });
    expect(sqlRes.success).toBe(true);
    expect(sqlRes.valid).toBe(true);
    expect(sqlRes.spec!.table).toBe("users");
    expect(sqlRes.sql).toContain("users");

    // With unparsable SQL (valid SELECT statement structure, but lacking FROM table)
    const badSqlRes = executeAgentToolCall("validate_and_compile_query", {
      sql: "SELECT 1",
    });
    expect(badSqlRes.success).toBe(false);
    expect(badSqlRes.valid).toBe(false);
    expect(badSqlRes.error).toContain("Failed to parse SQL query: SELECT 1");

    // With spec AST and custom onCompile
    const specRes = executeAgentToolCall(
      "validate_and_compile_query",
      {
        spec: {
          table: "users",
          columns: ["id", "email"],
          limit: 15,
        },
      },
      {
        onCompile: (s, d) => `SELECT custom FROM ${s.table} [${d}]`,
      }
    );
    expect(specRes.success).toBe(true);
    expect(specRes.valid).toBe(true);
    expect(specRes.spec!.table).toBe("users");
    expect(specRes.sql).toBe("SELECT custom FROM users [postgres]");
  });

  it("enforces security validation and input hardening in executeAgentToolCall", () => {
    // 1. Non-string tool name
    const badNameRes = executeAgentToolCall(invalid<string>(12345), {});
    expect(badNameRes.success).toBe(false);
    expect(badNameRes.error).toContain("Tool name must be a string");

    // 2. Malformed JSON argument string
    const badJsonRes = executeAgentToolCall("build_query", "{ not valid json");
    expect(badJsonRes.success).toBe(false);
    expect(badJsonRes.error).toContain("Invalid JSON arguments");

    // 3. Invalid argument types (neither object nor string)
    const badTypeRes = executeAgentToolCall("build_query", invalid<string>(9999));
    expect(badTypeRes.success).toBe(false);
    expect(badTypeRes.error).toContain("Arguments must be an object or JSON string");

    // 4. Dangerous raw SQL blocked by validateSqlSafety
    const dropRes = executeAgentToolCall("validate_and_compile_query", {
      sql: "DROP TABLE users;",
    });
    expect(dropRes.success).toBe(false);
    expect(dropRes.valid).toBe(false);
    expect(dropRes.error).toContain("Security validation failed");

    // 5. Dangerous compiled query blocked by validateSqlSafety
    const dangerousCompileRes = executeAgentToolCall(
      "validate_and_compile_query",
      {
        spec: { table: "users" },
      },
      {
        onCompile: () => "DROP TABLE users;",
      }
    );
    expect(dangerousCompileRes.success).toBe(false);
    expect(dangerousCompileRes.valid).toBe(false);
    expect(dangerousCompileRes.error).toContain("Security validation failed on compiled query");
  });

  it("executes get_schema_catalog tool call in markdown and json formats", () => {
    const mdRes = executeAgentToolCall(
      "get_schema_catalog",
      { format: "markdown" },
      { schema: mockSchema }
    );
    expect(mdRes.success).toBe(true);
    expect(mdRes.format).toBe("markdown");
    expect(mdRes.catalog).toContain("users");
    expect(mdRes.catalog).toContain("orders");

    // Filter tables
    const jsonRes = executeAgentToolCall(
      "get_schema_catalog",
      { format: "json", tables: ["users"] },
      { schema: mockSchema }
    );
    expect(jsonRes.success).toBe(true);
    expect(jsonRes.format).toBe("json");
    expect(jsonRes.tables).toEqual(["users"]);

    // Schema as array of objects
    const arrSchemaRes = executeAgentToolCall(
      "get_schema_catalog",
      { format: "json" },
      { schema: [{ name: "customers" }, { name: "invoices" }] }
    );
    expect(arrSchemaRes.tables).toEqual(["customers", "invoices"]);

    // Schema as simple dictionary
    const dictSchemaRes = executeAgentToolCall(
      "get_schema_catalog",
      { format: "json" },
      { schema: { members: {}, clubs: {} } }
    );
    expect(dictSchemaRes.tables).toEqual(["members", "clubs"]);

    // Empty schema
    const emptyRes = executeAgentToolCall("get_schema_catalog", { format: "markdown" });
    expect(emptyRes.success).toBe(true);
    expect(emptyRes.catalog).toContain("No explicit schema provided");
  });

  it("executes explain_query tool call", () => {
    const res = executeAgentToolCall("explain_query", {
      sql: "SELECT id, email FROM users LEFT JOIN orders ON orders.user_id = users.id WHERE email = 'test@example.com'",
    });
    expect(res.success).toBe(true);
    expect(res.tool).toBe("explain_query");
    expect(res.table).toBe("users");
    expect(res.summary).toContain("Queries from table 'users'");

    const errRes = executeAgentToolCall("explain_query", {});
    expect(errRes.success).toBe(false);
  });

  it("returns error for unknown tool call", () => {
    const res = executeAgentToolCall("non_existent_tool", {});
    expect(res.success).toBe(false);
    expect(res.error).toContain("Unknown tool");
  });
});

describe("Client-Side Self-Healing Engine (autoHealClientQuerySpec)", () => {
  const schema: SchemaDict = {
    tables: {
      users: {
        columns: { id: { data_type: "int" } },
      },
      orders: {
        columns: {
          id: { data_type: "int" },
          user_id: { data_type: "int" },
        },
        foreign_keys: [
          { target_table: "users", target_column: "id", column: "user_id" },
        ],
      },
      line_items: {
        columns: {
          id: { data_type: "int" },
          order_id: { data_type: "int" },
        },
      },
    },
  };

  it("infers table name from column references when missing", () => {
    const { healedSpec, notes } = autoHealClientQuerySpec({
      columns: ["users.email", "users.first_name"],
    });
    expect(healedSpec.table).toBe("users");
    expect(notes.some((n) => n.includes("Inferred primary table 'users'"))).toBe(true);
  });

  it("infers table name from filter prefix when missing", () => {
    const { healedSpec, notes } = autoHealClientQuerySpec({
      filters: [{ column: "status", op: "=", value: "active", tablePrefix: "accounts" }],
    });
    expect(healedSpec.table).toBe("accounts");
    expect(notes.some((n) => n.includes("Inferred primary table 'accounts'"))).toBe(true);
  });

  it("defaults primary table to 'data' if no hints present", () => {
    const { healedSpec, notes } = autoHealClientQuerySpec({});
    expect(healedSpec.table).toBe("data");
    expect(notes.some((n) => n.includes("Assigned default primary table 'data'"))).toBe(true);
  });

  it("auto-synthesizes missing joins from schema foreign keys", () => {
    const { healedSpec, notes } = autoHealClientQuerySpec(
      {
        table: "users",
        columns: ["users.id", "orders.total"],
      },
      schema
    );
    expect(healedSpec.joins.length).toBe(1);
    expect(healedSpec.joins[0].table).toBe("orders");
    expect(healedSpec.joins[0].left_table).toBe("users");
    expect(notes.some((n) => n.includes("Auto-synthesized join"))).toBe(true);
  });

  it("synthesizes join from filter and order_by references", () => {
    const { healedSpec } = autoHealClientQuerySpec(
      {
        table: "users",
        filters: [{ column: "orders.status", op: "=", value: "paid" }],
        order_by: [{ column: "orders.created_at", direction: "DESC" }],
      },
      schema
    );
    expect(healedSpec.joins.length).toBe(1);
    expect(healedSpec.joins[0].table).toBe("orders");
  });

  it("infers table from filter column without prefix", () => {
    const { healedSpec, notes } = autoHealClientQuerySpec({
      filters: [{ column: "profiles.bio", op: "!=", value: "" }],
    });
    expect(healedSpec.table).toBe("profiles");
    expect(notes.some((n) => n.includes("Inferred primary table 'profiles' from filter column"))).toBe(true);
  });

  it("handles order_by tablePrefix and joins", () => {
    const { healedSpec } = autoHealClientQuerySpec(
      {
        table: "users",
        order_by: [{ column: "total", direction: "DESC", tablePrefix: "orders" }],
      },
      schema
    );
    expect(healedSpec.joins.length).toBe(1);
    expect(healedSpec.joins[0].table).toBe("orders");
  });

  it("handles object columns and camelCase foreign key metadata", () => {
    const customSchema = {
      tables: {
        users: { columns: { id: { data_type: "int" } } },
        members: {
          columns: { id: { data_type: "int" }, member_fk: { data_type: "int" } },
          foreignKeys: [
            { targetTable: "users", targetColumn: "id", foreign_column: "member_fk" },
          ],
        },
      },
    };

    const { healedSpec } = autoHealClientQuerySpec(
      {
        columns: [{ column: "users.id" }, { column: "members.member_fk" }],
      },
      customSchema
    );
    expect(healedSpec.table).toBe("users");
    expect(healedSpec.joins.length).toBe(1);
    expect(healedSpec.joins[0].table).toBe("members");
    expect(healedSpec.joins[0].right_col).toBe("member_fk");
  });
});

describe("useBringYourOwnAi Hook", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("handles empty prompt gracefully", async () => {
    const { result } = renderHook(() => useBringYourOwnAi({}));

    let res = null as ByoAiResponse | null;
    await act(async () => {
      res = await result.current.sendMessage("   ");
    });
    expect(res).toBeNull();
    expect(result.current.error).toBe("Prompt cannot be empty.");
  });

  it("works with a custom function handler returning raw SQL", async () => {
    const mockHandler = vi.fn().mockResolvedValue("SELECT id, name FROM users LIMIT 10");
    const onApply = vi.fn();

    const { result } = renderHook(() =>
      useBringYourOwnAi({
        handler: mockHandler,
        autoApply: true,
        onApplySpec: onApply,
      })
    );

    await act(async () => {
      await result.current.sendMessage("Fetch active users");
    });
    expect(mockHandler).toHaveBeenCalled();
    expect(result.current.messages.length).toBe(2);
    expect(result.current.messages[0].role).toBe("user");
    expect(result.current.messages[1].role).toBe("assistant");
    expect(result.current.latestSpec).toBeDefined();
    expect(result.current.latestSpec?.table).toBe("users");
    expect(onApply).toHaveBeenCalled();
  });

  it("works with client object handlers having .generate or .ask", async () => {
    const client = {
      generate: vi.fn().mockResolvedValue({
        spec: { table: "products", columns: ["id", "price"], limit: 5 },
        explanation: "Top 5 products",
        confidence: 0.98,
      }),
    };

    const { result } = renderHook(() =>
      useBringYourOwnAi({ handler: client })
    );

    await act(async () => {
      await result.current.sendMessage("Show top products");
    });
    expect(client.generate).toHaveBeenCalled();
    expect(result.current.latestSpec?.table).toBe("products");
    expect(result.current.messages[1].content).toBe("Top 5 products");
    expect(result.current.messages[1].confidence).toBe(0.98);
  });

  it("handles fallback fetch API and error status", async () => {
    const onError = vi.fn();
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    } as unknown as Response);

    const { result } = renderHook(() =>
      useBringYourOwnAi({ apiUrl: "/api/test-ai", onError })
    );

    await act(async () => {
      await result.current.sendMessage("Find users");
    });
    expect(result.current.error).toContain("HTTP 500");
    expect(onError).toHaveBeenCalled();
  });

  it("handles fallback fetch API on HTTP 200 success", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        spec: { table: "departments", columns: ["id", "dept_name"] },
        explanation: "Departments list",
      }),
    } as unknown as Response);

    const { result } = renderHook(() =>
      useBringYourOwnAi({ apiUrl: "/api/test-ai" })
    );

    await act(async () => {
      await result.current.sendMessage("Show departments");
    });
    expect(result.current.latestSpec?.table).toBe("departments");
    expect(result.current.messages[1].content).toBe("Departments list");
  });

  it("supports clearMessages and undoLast", async () => {
    const mockHandler = vi.fn().mockResolvedValue("SELECT * FROM users");

    const { result } = renderHook(() =>
      useBringYourOwnAi({ handler: mockHandler })
    );

    await act(async () => {
      await result.current.sendMessage("Query 1");
    });
    expect(result.current.messages.length).toBe(2);

    act(() => {
      result.current.undoLast();
    });
    expect(result.current.messages.length).toBe(0);

    await act(async () => {
      await result.current.sendMessage("Query 2");
    });
    expect(result.current.messages.length).toBe(2);

    act(() => {
      result.current.clearMessages();
    });
    expect(result.current.messages.length).toBe(0);
    expect(result.current.latestSpec).toBeNull();
  });

  it("works with client handler having .generateQuery and .ask", async () => {
    const clientQuery = {
      generateQuery: vi.fn().mockResolvedValue("SELECT * FROM audit_logs"),
    };
    const { result: r1 } = renderHook(() =>
      useBringYourOwnAi({ handler: clientQuery })
    );
    await act(async () => {
      await r1.current.sendMessage("Check logs");
    });
    expect(clientQuery.generateQuery).toHaveBeenCalled();
    expect(r1.current.latestSpec?.table).toBe("audit_logs");

    const clientAsk = {
      ask: vi.fn().mockResolvedValue(JSON.stringify({ table: "metrics", columns: ["val"] })),
    };
    const { result: r2 } = renderHook(() =>
      useBringYourOwnAi({ handler: clientAsk })
    );
    await act(async () => {
      await r2.current.sendMessage("Get metrics");
    });
    expect(clientAsk.ask).toHaveBeenCalled();
    expect(r2.current.latestSpec?.table).toBe("metrics");
  });

  it("parses raw response JSON strings and handles plain text explanations", async () => {
    const handlerJson = vi.fn().mockResolvedValue(
      JSON.stringify({
        spec: { table: "invoices", columns: ["id"] },
        explanation: "Invoices report",
      })
    );
    const { result: r1 } = renderHook(() =>
      useBringYourOwnAi({ handler: handlerJson })
    );
    await act(async () => {
      await r1.current.sendMessage("Show invoices");
    });
    expect(r1.current.latestSpec?.table).toBe("invoices");
    expect(r1.current.messages[1].content).toBe("Invoices report");

    // Plain string
    const handlerPlain = vi.fn().mockResolvedValue("I do not know how to answer this.");
    const { result: r2 } = renderHook(() =>
      useBringYourOwnAi({ handler: handlerPlain })
    );
    await act(async () => {
      await r2.current.sendMessage("Random text");
    });
    expect(r2.current.messages[1].content).toBe("I do not know how to answer this.");
  });

  it("handles autoHeal disabled and invalid handler error", async () => {
    const handler = vi.fn().mockResolvedValue({
      table: "custom_tbl",
      columns: ["a", "b"],
    });
    const { result: r1 } = renderHook(() =>
      useBringYourOwnAi({ handler, autoHeal: false })
    );
    await act(async () => {
      await r1.current.sendMessage("No heal");
    });
    expect(r1.current.latestSpec?.table).toBe("custom_tbl");

    const { result: r2 } = renderHook(() =>
      useBringYourOwnAi({ handler: invalid<ByoAiHandler>({ bad: 123 }) })
    );
    await act(async () => {
      await r2.current.sendMessage("Bad handler");
    });
    expect(r2.current.error).toContain("Invalid BYO-AI handler format");
  });
});

describe("<AiAssistantWidget /> UI Component", () => {
  it("renders floating launcher button and opens chat window when clicked", () => {
    render(<AiAssistantWidget widgetPosition="floating-bottom-right" />);

    const launcher = screen.getByTestId("ai-widget-launcher");
    expect(launcher).toBeTruthy();
    expect(screen.queryByTestId("ai-chat-window")).toBeNull();

    fireEvent.click(launcher);
    expect(screen.getByTestId("ai-chat-window")).toBeTruthy();

    const closeBtn = screen.getByTestId("ai-widget-close");
    fireEvent.click(closeBtn);
    expect(screen.queryByTestId("ai-chat-window")).toBeNull();
  });

  it("renders launcher in unstyled mode", () => {
    render(<AiAssistantWidget widgetPosition="floating-bottom-right" unstyled={true} />);
    expect(screen.getByTestId("ai-widget-launcher")).toBeTruthy();
  });

  it("handles suggestion chip click and custom handler response", async () => {
    const mockHandler = vi.fn().mockResolvedValue({
      spec: { table: "revenue", columns: ["total"], limit: 20 },
      explanation: "Calculated total revenue",
    });

    render(
      <AiAssistantWidget
        isOpen={true}
        handler={mockHandler}
        suggestions={["Total revenue grouped by category"]}
      />
    );

    const chip = screen.getByTestId("ai-suggestion-0");
    expect(chip.textContent).toContain("Total revenue grouped by category");

    fireEvent.click(chip);

    await waitFor(() => {
      expect(screen.getByText("Calculated total revenue")).toBeTruthy();
    });
    expect(mockHandler).toHaveBeenCalled();
  });

  it("allows typing prompt and triggers onApplySpec when clicking Apply to Builder", async () => {
    const onApply = vi.fn();
    const mockHandler = vi.fn().mockResolvedValue({
      spec: { table: "customers", columns: ["id", "name"], limit: 50 },
      explanation: "List of customers",
    });

    render(
      <AiAssistantWidget
        isOpen={true}
        handler={mockHandler}
        onApplySpec={onApply}
      />
    );

    const input = screen.getByTestId("ai-widget-input");
    const submitBtn = screen.getByTestId("ai-widget-submit");

    fireEvent.change(input, { target: { value: "Show customers" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText("List of customers")).toBeTruthy();
    });

    const applyBtn = screen.getByTestId("ai-apply-spec-btn");
    expect(applyBtn).toBeTruthy();
    fireEvent.click(applyBtn);

    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({ table: "customers" })
    );
  });

  it("renders healing notes and clears messages on clear button click", async () => {
    const handler = vi.fn().mockResolvedValue({
      spec: { table: "users", columns: ["users.id", "orders.total"] },
      explanation: "Joined users and orders",
    });
    render(
      <AiAssistantWidget
        isOpen={true}
        handler={handler}
        schema={{
          tables: {
            users: { columns: { id: { data_type: "int" } } },
            orders: {
              columns: { id: { data_type: "int" }, user_id: { data_type: "int" }, total: { data_type: "float" } },
              foreign_keys: [{ target_table: "users", target_column: "id", column: "user_id" }],
            },
          },
        }}
      />
    );
    const input = screen.getByTestId("ai-widget-input");
    fireEvent.change(input, { target: { value: "Show users and orders" } });
    fireEvent.click(screen.getByTestId("ai-widget-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("ai-healing-notes")).toBeTruthy();
      expect(screen.getByTestId("ai-healing-notes").textContent).toContain("Auto-synthesized join");
    });

    const clearBtn = screen.getByTestId("ai-widget-clear");
    expect(clearBtn).toBeTruthy();
    fireEvent.click(clearBtn);
    expect(screen.queryByTestId("ai-healing-notes")).toBeNull();
  });

  it("renders error alerts when handler fails", async () => {
    const mockHandler = vi.fn().mockRejectedValue(new Error("AI Gateway Offline"));

    render(
      <AiAssistantWidget
        isOpen={true}
        handler={mockHandler}
      />
    );

    const input = screen.getByTestId("ai-widget-input");
    fireEvent.change(input, { target: { value: "Show users" } });
    fireEvent.click(screen.getByTestId("ai-widget-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("ai-error-banner")).toBeTruthy();
      expect(screen.getByTestId("ai-error-banner").textContent).toContain("AI Gateway Offline");
    });
  });

  it("renders in docked-right mode and unstyled mode without errors", () => {
    const { unmount } = render(
      <AiAssistantWidget
        widgetPosition="docked-right"
        unstyled={true}
        isOpen={true}
      />
    );
    expect(screen.getByTestId("ai-chat-window")).toBeTruthy();
    unmount();
  });

  it("renders in embedded position and unstyled mode with messages and close button", async () => {
    const handler = vi.fn().mockResolvedValue({
      spec: { table: "users", columns: ["id"] },
      sql: "SELECT id FROM users",
    });

    const { unmount } = render(
      <AiAssistantWidget
        widgetPosition={invalid<"docked-right">("embedded")}
        isOpen={true}
      />
    );
    expect(screen.getByTestId("ai-chat-window")).toBeTruthy();
    unmount();

    render(
      <AiAssistantWidget
        widgetPosition="floating-bottom-right"
        isOpen={true}
        unstyled={true}
        handler={handler}
        onApplySpec={vi.fn()}
      />
    );

    const input = screen.getByTestId("ai-widget-input");
    fireEvent.change(input, { target: { value: "Show users" } });
    fireEvent.click(screen.getByTestId("ai-widget-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("ai-apply-spec-btn")).toBeTruthy();
    });

    const closeBtn = screen.getByTestId("ai-widget-close");
    expect(closeBtn).toBeTruthy();
    fireEvent.click(closeBtn);
  });
});

describe("<VisualQueryBuilder /> BYO-AI Integration", () => {
  const schema: DatabaseSchemaDefinition = {
    tables: {
      users: {
        columns: {
          id: { dataType: "int" },
          username: { dataType: "text" },
        },
      },
    },
  };

  it("mounts <AiAssistantWidget /> when ai prop is provided", () => {
    const { rerender } = render(<VisualQueryBuilder schema={schema} />);
    expect(screen.queryByTestId("ai-assistant-widget")).toBeNull();

    rerender(
      <VisualQueryBuilder
        schema={schema}
        ai={{
          widgetPosition: "floating-bottom-right",
          handler: async () => "SELECT * FROM users",
        }}
      />
    );
    expect(screen.getByTestId("ai-assistant-widget")).toBeTruthy();
  });
});
