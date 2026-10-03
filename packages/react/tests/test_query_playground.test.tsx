import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { QueryPlayground, type SchemaSnapshot } from "../src";

const sampleSchema: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "email", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
        { name: "amount", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
  },
};

describe("QueryPlayground Interactive Component", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("mounts successfully with default props and schema", () => {
    render(<QueryPlayground schema={sampleSchema} />);

    expect(screen.getByText("Query-Builder Playground")).toBeDefined();
    expect(screen.getByText("AST Safe")).toBeDefined();
    expect(screen.getByText("Query Editor")).toBeDefined();
    expect(screen.getByText("AST Visualizer")).toBeDefined();
    expect(screen.getByText("Code Generation")).toBeDefined();
  });

  it("synchronizes visual controls and notifies callbacks", () => {
    const onSpecChange = vi.fn();
    const onSqlChange = vi.fn();

    render(
      <QueryPlayground
        schema={sampleSchema}
        initialTable="users"
        onSpecChange={onSpecChange}
        onSqlChange={onSqlChange}
      />,
    );

    expect(onSpecChange).toHaveBeenCalled();
    expect(onSqlChange).toHaveBeenCalled();

    // Toggle column
    const emailToggle = screen.getByText("+ email");
    act(() => {
      fireEvent.click(emailToggle);
    });

    // Should now show checked
    expect(screen.getByText("✓ email")).toBeDefined();
  });

  it("supports live editing of JSON spec editor and handles syntax errors", () => {
    render(<QueryPlayground schema={sampleSchema} initialTable="users" />);

    // Switch to JSON tab
    const jsonSubtab = screen.getByText("Live JSON Spec");
    act(() => {
      fireEvent.click(jsonSubtab);
    });

    const textarea = screen.getByLabelText("JSON Query Spec Editor");
    expect(textarea).toBeDefined();

    // Enter valid JSON update
    const updatedSpec = {
      table: "orders",
      columns: ["orders.id", "orders.amount"],
      joins: [],
      filters: [],
      distinct: true,
      limit: 15,
    };

    act(() => {
      fireEvent.change(textarea, { target: { value: JSON.stringify(updatedSpec, null, 2) } });
    });

    expect(screen.queryByRole("alert")).toBeNull();

    // Switch back to visual controls to see updated table
    const visualSubtab = screen.getByText("Visual Controls");
    act(() => {
      fireEvent.click(visualSubtab);
    });

    expect((screen.getByLabelText("Select Primary Table") as HTMLSelectElement).value).toBe("orders");

    // Switch to JSON tab again and enter invalid JSON
    act(() => {
      fireEvent.click(jsonSubtab);
    });

    const activeTextarea = screen.getByLabelText("JSON Query Spec Editor");
    act(() => {
      fireEvent.change(activeTextarea, { target: { value: "INVALID_JSON{" } });
    });

    // Alert should be visible
    expect(screen.getByRole("alert")).toBeDefined();
    expect(screen.getByText(/Syntax Error:/)).toBeDefined();
  });

  it("renders AST clause breakdown cards in AST Visualizer tab", () => {
    render(
      <QueryPlayground
        schema={sampleSchema}
        initialSpec={{
          table: "users",
          columns: ["users.id", { column: "users.email", agg: "COUNT", alias: "email_cnt" }],
          joins: [{ table: "orders", type: "LEFT JOIN", left_col: "id", right_col: "user_id" }],
          filters: [{ column: "users.id", op: ">", value: 5 }],
          order_by: [{ column: "users.id", direction: "ASC" }],
          distinct: true,
          limit: 25,
        }}
      />,
    );

    // Switch to AST Visualizer tab
    const astTab = screen.getByText("AST Visualizer");
    act(() => {
      fireEvent.click(astTab);
    });

    expect(screen.getByText("FROM (Data Source)")).toBeDefined();
    expect(screen.getByText(/SELECT \(Projections: 2\)/)).toBeDefined();
    expect(screen.getByText(/JOIN \(Relational: 1\)/)).toBeDefined();
    expect(screen.getByText(/WHERE \(Filters: 1\)/)).toBeDefined();
    expect(screen.getByText(/ORDER BY \(Sorts: 1\)/)).toBeDefined();
    expect(screen.getByText("OPTIONS (Limit & Distinct)")).toBeDefined();
    expect(screen.getByText("YES")).toBeDefined();
  });

  it("renders Code Generation tab, supports dialect switching and clipboard copy", async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(
      <QueryPlayground
        schema={sampleSchema}
        initialSpec={{
          table: "users",
          columns: ["users.id", "users.email"],
          joins: [{ table: "orders", type: "LEFT JOIN", left_col: "id", right_col: "user_id" }],
          filters: [{ column: "users.id", op: ">", value: 10 }],
          order_by: [{ column: "users.id", direction: "DESC" }],
          distinct: true,
          limit: 50,
        }}
      />,
    );

    // Switch to Codegen tab
    const codegenTab = screen.getByText("Code Generation");
    act(() => {
      fireEvent.click(codegenTab);
    });

    // Default target: TypeScript SDK
    expect(screen.getByText(/import \{ createQuery \} from "@jacob-white\/query-builder"/)).toBeDefined();

    // Copy TypeScript SDK snippet
    const copyBtn = screen.getByText("📋 Copy Snippet");
    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(writeTextMock).toHaveBeenCalled();
    expect(screen.getByText("✓ Copied!")).toBeDefined();

    // Switch to Compiled SQL view
    const sqlTab = screen.getByText("Compiled SQL");
    act(() => {
      fireEvent.click(sqlTab);
    });

    const dialectSelect = screen.getByLabelText("Select Dialect for compiled SQL");
    expect(dialectSelect).toBeDefined();

    // Switch dialect to MySQL
    act(() => {
      fireEvent.change(dialectSelect, { target: { value: "mysql" } });
    });

    expect(screen.getByText(/`users`\.`id`/)).toBeDefined();

    // Switch to JSON AST view
    const astTab = screen.getByText("JSON AST");
    act(() => {
      fireEvent.click(astTab);
    });

    expect(screen.getByText(/"table": "users"/)).toBeDefined();

    // Copy JSON AST snippet
    const copyAstBtn = screen.getByText("📋 Copy Snippet");
    await act(async () => {
      fireEvent.click(copyAstBtn);
    });
    expect(writeTextMock).toHaveBeenCalled();

    // Switch back to SQL and copy SQL snippet
    act(() => {
      fireEvent.click(sqlTab);
    });
    const copySqlBtn = screen.getByText("📋 Copy Snippet");
    await act(async () => {
      fireEvent.click(copySqlBtn);
    });
    expect(writeTextMock).toHaveBeenCalled();

    // Clipboard reject handling
    writeTextMock.mockRejectedValueOnce(new Error("Permission denied"));
    await act(async () => {
      fireEvent.click(copySqlBtn);
    });

    // Switch back to TypeScript SDK target
    const sdkTab = screen.getByText("TypeScript SDK");
    act(() => {
      fireEvent.click(sdkTab);
    });
    expect(screen.getByText(/import \{ createQuery \}/)).toBeDefined();

    // Advance timer to clear copied state (line 100)
    vi.useFakeTimers();
    await act(async () => {
      fireEvent.click(copyBtn);
    });
    act(() => {
      vi.advanceTimersByTime(2100);
    });
    vi.useRealTimers();
  });

  it("renders AST Risk safety badge when spec has safety validation failure", () => {
    const { container } = render(
      <QueryPlayground
        schema={sampleSchema}
        initialSpec={{
          table: "users; DROP TABLE users;",
        }}
      />,
    );
    const badge = container.querySelector('[data-qb="safety-badge"]');
    expect(badge).not.toBeNull();
    expect(badge?.getAttribute("data-qb-safety")).toBe("invalid");
    expect(badge?.textContent).toContain("AST Risk");
  });

  it("interacts with visual controls: columns toggle, distinct, limit, and table selection", () => {
    const onSpecChange = vi.fn();
    const onSqlChange = vi.fn();

    render(
      <QueryPlayground
        schema={sampleSchema}
        initialTable="users"
        onSpecChange={onSpecChange}
        onSqlChange={onSqlChange}
      />,
    );

    expect(onSpecChange).toHaveBeenCalled();
    expect(onSqlChange).toHaveBeenCalled();

    // Toggle email column
    const emailToggleBtn = screen.getByText("+ email");
    act(() => {
      fireEvent.click(emailToggleBtn);
    });
    expect(screen.getByText("✓ email")).toBeDefined();

    // Toggle DISTINCT
    const distinctCheckbox = screen.getByRole("checkbox", { name: "DISTINCT" });
    act(() => {
      fireEvent.click(distinctCheckbox);
    });
    expect((distinctCheckbox as HTMLInputElement).checked).toBe(true);

    // Change Limit
    const limitInput = screen.getByLabelText("Limit rows");
    act(() => {
      fireEvent.change(limitInput, { target: { value: "30" } });
    });
    expect((limitInput as HTMLInputElement).value).toBe("30");

    // Change Primary Table
    const tableSelect = screen.getByLabelText("Select Primary Table");
    act(() => {
      fireEvent.change(tableSelect, { target: { value: "orders" } });
    });
    expect((tableSelect as HTMLSelectElement).value).toBe("orders");
  });

  it("displays empty fallback cards in AST Visualizer when spec has no clauses", () => {
    render(
      <QueryPlayground
        schema={sampleSchema}
        initialSpec={{
          table: "users",
          columns: [],
          joins: [],
          filters: [],
          order_by: [],
          distinct: false,
          limit: 10,
        }}
      />,
    );

    const astTab = screen.getByText("AST Visualizer");
    act(() => {
      fireEvent.click(astTab);
    });

    expect(screen.getByText("* (all columns)")).toBeDefined();
    expect(screen.getByText("No joins configured")).toBeDefined();
    expect(screen.getByText("No filters applied")).toBeDefined();
    expect(screen.getByText("Default database ordering")).toBeDefined();
    expect(screen.getByText("NO")).toBeDefined();
  });

  it("handles empty schema and readOnly mode", () => {
    const { rerender } = render(
      <QueryPlayground
        schema={{ tables: {} }}
        readOnly={false}
      />,
    );

    const inputTable = screen.getByLabelText("Input Primary Table") as HTMLInputElement;
    expect(inputTable).toBeDefined();
    act(() => {
      fireEvent.change(inputTable, { target: { value: "custom_table" } });
    });
    expect(inputTable.value).toBe("custom_table");

    rerender(
      <QueryPlayground
        schema={{ tables: {} }}
        readOnly={true}
      />,
    );
    expect(inputTable.disabled).toBe(true);

    const distinct = screen.getByRole("checkbox", { name: "DISTINCT" }) as HTMLInputElement;
    expect(distinct.disabled).toBe(true);

    const limit = screen.getByLabelText("Limit rows") as HTMLInputElement;
    expect(limit.disabled).toBe(true);
  });

  it("renders with unstyled={true} and semantic data-qb attributes", () => {
    const { container } = render(
      <QueryPlayground schema={sampleSchema} unstyled={true} />,
    );

    const root = container.querySelector('[data-qb="playground-root"]');
    expect(root).not.toBeNull();
    expect(root?.getAttribute("data-qb-unstyled")).toBe("true");
    expect(root?.getAttribute("style")).toBeNull();

    const header = container.querySelector('[data-qb="playground-header"]');
    expect(header).not.toBeNull();
    expect(header?.getAttribute("style")).toBeNull();

    const tabs = container.querySelector('[data-qb="playground-tabs"]');
    expect(tabs).not.toBeNull();
    expect(tabs?.getAttribute("style")).toBeNull();

    // Switch to AST tab unstyled
    const astTab = screen.getByText("AST Visualizer");
    act(() => {
      fireEvent.click(astTab);
    });
    const astVisualizer = container.querySelector('[data-qb="playground-ast-visualizer"]');
    expect(astVisualizer?.getAttribute("style")).toBeNull();

    // Switch to Codegen tab unstyled
    const codegenTab = screen.getByText("Code Generation");
    act(() => {
      fireEvent.click(codegenTab);
    });
    const codegenRoot = container.querySelector('[data-qb="playground-codegen"]');
    expect(codegenRoot?.getAttribute("style")).toBeNull();

    // Switch to SQL target to test dialect select unstyled
    const sqlBtn = screen.getByText("Compiled SQL");
    act(() => {
      fireEvent.click(sqlBtn);
    });
    const dialectSelect = container.querySelector('[data-qb="playground-dialect-select"]');
    expect(dialectSelect?.getAttribute("style")).toBeNull();

    const copyBtn = container.querySelector('[data-qb="playground-copy-btn"]');
    expect(copyBtn?.getAttribute("style")).toBeNull();

    const snippetPre = container.querySelector('[data-qb="playground-code-snippet"]');
    expect(snippetPre?.getAttribute("style")).toBeNull();

    // Switch back to builder tab, then to JSON subtab unstyled
    const builderTab = screen.getByText("Query Editor");
    act(() => {
      fireEvent.click(builderTab);
    });
    const jsonSubtab = screen.getByText("Live JSON Spec");
    act(() => {
      fireEvent.click(jsonSubtab);
    });
    const jsonTextarea = screen.getByLabelText("JSON Query Spec Editor");
    expect(jsonTextarea.getAttribute("style")).toBeNull();

    // Enter invalid JSON in unstyled mode to trigger error banner unstyled
    act(() => {
      fireEvent.change(jsonTextarea, { target: { value: "INVALID_JSON{" } });
    });
    const jsonError = container.querySelector('[role="alert"]');
    expect(jsonError?.getAttribute("style")).toBeNull();
  });

  it("renders input primary table in unstyled mode when schema has no tables", () => {
    const { container } = render(
      <QueryPlayground schema={{ tables: {} }} unstyled={true} />,
    );
    const inputTable = container.querySelector('[data-qb="playground-input-table"]');
    expect(inputTable).not.toBeNull();
    expect(inputTable?.getAttribute("style")).toBeNull();
  });

  it("renders AST Visualizer with sorts in unstyled mode", () => {
    const { container } = render(
      <QueryPlayground
        schema={sampleSchema}
        initialSpec={{
          table: "users",
          order_by: [{ column: "users.id", direction: "ASC" }],
        }}
        unstyled={true}
      />,
    );
    const astTab = screen.getByText("AST Visualizer");
    act(() => {
      fireEvent.click(astTab);
    });
    const orderbyCard = container.querySelector('[data-qb="ast-clause-orderby"]');
    expect(orderbyCard).not.toBeNull();
    expect(orderbyCard?.getAttribute("style")).toBeNull();
  });

  it("covers object columns with and without alias/agg, joins with default id columns in AST and SDK snippets", () => {
    const { container } = render(
      <QueryPlayground
        schema={sampleSchema}
        initialSpec={{
          table: "users",
          columns: [
            { column: "users.email", alias: "user_email" },
            { column: "users.id" },
            { column: "orders.amount", agg: "SUM" },
          ],
          joins: [
            { table: "orders", left_col: "user_id", right_col: "order_id" },
            { table: "profiles", left_col: undefined, right_col: "profile_id" },
            { table: "logs", left_col: "log_user_id", right_col: undefined },
            { table: "audits", left_col: "", right_col: "" },
          ],
        }}
      />,
    );

    // Switch to Code Generation tab to exercise generateSdkSnippet
    const codegenTab = screen.getByText("Code Generation");
    act(() => {
      fireEvent.click(codegenTab);
    });
    const snippetPre = container.querySelector('[data-qb="playground-code-snippet"]');
    expect(snippetPre?.textContent).toContain("user_email");
    expect(snippetPre?.textContent).toContain('.join("orders", "user_id", "=", "order_id")');
    expect(snippetPre?.textContent).toContain('.join("profiles", "id", "=", "profile_id")');
    expect(snippetPre?.textContent).toContain('.join("logs", "log_user_id", "=", "id")');
    expect(snippetPre?.textContent).toContain('.join("audits", "id", "=", "id")');

    // Switch to AST Visualizer tab to exercise line 729 (c.agg truthy and falsy)
    const astTab = screen.getByText("AST Visualizer");
    act(() => {
      fireEvent.click(astTab);
    });
    expect(screen.getByText("orders.amount (SUM)")).toBeDefined();
    expect(screen.getByText("users.id")).toBeDefined();
  });
});
