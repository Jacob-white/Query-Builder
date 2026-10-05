import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { ExportWorkbench, generateSdkSnippet } from "../src/components/ExportWorkbench";
import type { QuerySpec } from "../src/types";

describe("ExportWorkbench Component", () => {
  const sampleSpec: QuerySpec = {
    table: "users",
    columns: ["users.id", { column: "users.email", agg: "COUNT", alias: "email_cnt" }],
    joins: [{ table: "orders", type: "LEFT JOIN", left_col: "id", right_col: "user_id" }],
    filters: [{ column: "users.id", op: ">", value: 10, tablePrefix: "users" }],
    filter_join: "AND",
    order_by: [{ column: "users.id", direction: "DESC", tablePrefix: "users" }],
    distinct: true,
    limit: 25,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders TypeScript SDK by default with code snippet", () => {
    render(<ExportWorkbench spec={sampleSpec} />);

    expect(screen.getByText("TypeScript SDK")).toBeTruthy();
    expect(screen.getByText("Compiled SQL")).toBeTruthy();
    expect(screen.getByText("JSON AST")).toBeTruthy();
    expect(screen.getByText(/import \{ createQuery \} from "@jacob-white\/query-builder"/)).toBeTruthy();
    expect(screen.getByText(/\.from\("users"\)/)).toBeTruthy();
    expect(screen.getByText(/\.join\("orders", "id", "=", "user_id"\)/)).toBeTruthy();
    expect(screen.getByText(/\.where\("users\.id", ">", 10\)/)).toBeTruthy();
    expect(screen.getByText(/\.orderBy\("users\.id", "DESC"\)/)).toBeTruthy();
    expect(screen.getByText(/\.distinct\(\)/)).toBeTruthy();
    expect(screen.getByText(/\.limit\(25\)/)).toBeTruthy();
  });

  it("switches to Compiled SQL and JSON AST tabs", () => {
    render(<ExportWorkbench spec={sampleSpec} sql="SELECT 1 FROM users;" />);

    // Switch to SQL
    const sqlTab = screen.getByText("Compiled SQL");
    act(() => {
      fireEvent.click(sqlTab);
    });

    expect(screen.getByText("SELECT 1 FROM users;")).toBeTruthy();
    expect(screen.getByLabelText("Select Dialect for compiled SQL")).toBeTruthy();

    // Switch to JSON AST
    const astTab = screen.getByText("JSON AST");
    act(() => {
      fireEvent.click(astTab);
    });

    expect(screen.getByText(/"table": "users"/)).toBeTruthy();
  });

  it("supports dialect switching and triggers onDialectChange", () => {
    const onDialectChange = vi.fn();
    render(
      <ExportWorkbench
        spec={sampleSpec}
        dialect="postgres"
        onDialectChange={onDialectChange}
      />,
    );

    // Switch to SQL
    act(() => {
      fireEvent.click(screen.getByText("Compiled SQL"));
    });

    const select = screen.getByLabelText("Select Dialect for compiled SQL");
    act(() => {
      fireEvent.change(select, { target: { value: "mysql" } });
    });

    expect(onDialectChange).toHaveBeenCalledWith("mysql");
    expect(screen.getByText(/`users`\.`id`/)).toBeTruthy();
  });

  it("handles copy snippet and invokes onCopy callback with visual feedback", async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    const onCopy = vi.fn();
    render(<ExportWorkbench spec={sampleSpec} onCopy={onCopy} />);

    const copyBtn = screen.getByText("📋 Copy Snippet");
    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(onCopy).toHaveBeenCalled();
    expect(writeTextMock).toHaveBeenCalled();
    expect(screen.getByText("✓ Copied!")).toBeTruthy();
  });

  it("handles clipboard failure gracefully", async () => {
    const writeTextMock = vi.fn().mockRejectedValue(new Error("Clipboard error"));
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(<ExportWorkbench spec={sampleSpec} />);

    const copyBtn = screen.getByText("📋 Copy Snippet");
    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(writeTextMock).toHaveBeenCalled();
  });

  it("renders in unstyled mode without inline styles", () => {
    const { container } = render(
      <ExportWorkbench spec={sampleSpec} unstyled={true} />,
    );

    const root = container.querySelector('[data-qb="export-workbench"]');
    expect(root?.getAttribute("data-qb-unstyled")).toBe("true");
    expect(root?.getAttribute("style")).toBeNull();
  });

  it("generates SDK snippet with fallback defaults when spec is minimal", () => {
    const minimalSpec = { table: "" };
    const code = generateSdkSnippet(minimalSpec);
    expect(code).toContain('.from("table")');
    expect(code).toContain(".select([])");
  });
});
