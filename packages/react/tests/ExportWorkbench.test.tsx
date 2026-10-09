import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { ExportWorkbench, generateSdkSnippet } from "../src/components/ExportWorkbench";
import type { QuerySpec } from "../src/types";
import { makeSpec } from "./helpers";

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
    expect(screen.getByText(/import \{ createQuery, createQueryBuilderClient \} from "@jacob-white\/query-builder-react\/client"/)).toBeTruthy();
    expect(screen.getByText(/\.from\("users"\)/)).toBeTruthy();
    expect(screen.getByText(/\.join\("orders", "id", "=", "user_id"\)/)).toBeTruthy();
    expect(screen.getByText(/\.where\("users\.id", ">", 10\)/)).toBeTruthy();
    expect(screen.getByText(/\.orderBy\("users\.id", "DESC"\)/)).toBeTruthy();
    expect(screen.getByText(/\.distinct\(\)/)).toBeTruthy();
    expect(screen.getByText(/\.limit\(25\)/)).toBeTruthy();
    const snippet = generateSdkSnippet(sampleSpec);
    expect(snippet).not.toContain('"@jacob-white/query-builder"');
    expect(snippet).toContain('"@jacob-white/query-builder-react/client"');
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

  it("switches to Streaming Export tab and selects different formats", () => {
    render(<ExportWorkbench spec={sampleSpec} />);

    const exportTab = screen.getByText("Streaming Export");
    act(() => {
      fireEvent.click(exportTab);
    });

    expect(screen.getByLabelText("Select Export Format")).toBeTruthy();
    expect(screen.getByText("⬇ Download Stream")).toBeTruthy();
    expect(screen.getByText(/Streaming Export Config/)).toBeTruthy();

    const select = screen.getByLabelText("Select Export Format");
    act(() => {
      fireEvent.change(select, { target: { value: "parquet" } });
    });
    expect(screen.getByText(/Format: parquet/)).toBeTruthy();

    act(() => {
      fireEvent.change(select, { target: { value: "arrow" } });
    });
    expect(screen.getByText(/Format: arrow/)).toBeTruthy();

    act(() => {
      fireEvent.change(select, { target: { value: "excel" } });
    });
    expect(screen.getByText(/Format: excel/)).toBeTruthy();
  });

  it("handles stream download using onExportStream prop callback", async () => {
    const onExportStream = vi.fn().mockResolvedValue(undefined);
    render(<ExportWorkbench spec={sampleSpec} onExportStream={onExportStream} />);

    act(() => {
      fireEvent.click(screen.getByText("Streaming Export"));
    });

    const downloadBtn = screen.getByText("⬇ Download Stream");
    await act(async () => {
      fireEvent.click(downloadBtn);
    });

    expect(onExportStream).toHaveBeenCalledWith("csv");
    expect(screen.getByText("Download complete!")).toBeTruthy();
  });

  it("handles stream download using global fetch and triggers anchor click", async () => {
    const createObjectURLMock = vi.fn().mockReturnValue("blob:http://localhost/test");
    const revokeObjectURLMock = vi.fn();
    window.URL.createObjectURL = createObjectURLMock;
    window.URL.revokeObjectURL = revokeObjectURLMock;

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(new Blob(["mock content"])),
    });
    globalThis.fetch = mockFetch;

    render(<ExportWorkbench spec={sampleSpec} />);

    act(() => {
      fireEvent.click(screen.getByText("Streaming Export"));
    });

    // Change to excel to test .xlsx extension
    const select = screen.getByLabelText("Select Export Format");
    act(() => {
      fireEvent.change(select, { target: { value: "excel" } });
    });

    const downloadBtn = screen.getByText("⬇ Download Stream");
    await act(async () => {
      fireEvent.click(downloadBtn);
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/export/stream",
      expect.objectContaining({
        method: "POST",
      })
    );
    expect(createObjectURLMock).toHaveBeenCalled();
    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:http://localhost/test");
    expect(screen.getByText("Download complete!")).toBeTruthy();
  });

  it("handles fetch stream download HTTP error and network rejection", async () => {
    // HTTP error response (500)
    const mockFailFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    });
    globalThis.fetch = mockFailFetch;

    const { rerender } = render(<ExportWorkbench spec={sampleSpec} />);

    act(() => {
      fireEvent.click(screen.getByText("Streaming Export"));
    });

    await act(async () => {
      fireEvent.click(screen.getByText("⬇ Download Stream"));
    });

    expect(screen.getByText("Export error: Export failed with HTTP 500")).toBeTruthy();

    // Network rejection error
    globalThis.fetch = vi.fn().mockRejectedValue(new Error("Network connection dropped"));
    rerender(<ExportWorkbench spec={sampleSpec} unstyled={true} />);

    await act(async () => {
      fireEvent.click(screen.getByText("⬇ Download Stream"));
    });

    expect(screen.getByText("Export error: Network connection dropped")).toBeTruthy();
  });

  it("resets copy visual feedback after timeout", async () => {
    vi.useFakeTimers();
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
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

    expect(screen.getByText("✓ Copied!")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(2100);
    });

    expect(screen.getByText("📋 Copy Snippet")).toBeTruthy();
    vi.useRealTimers();
  });

  it("renders in unstyled mode without inline styles", () => {
    const { container } = render(
      <ExportWorkbench spec={sampleSpec} unstyled={true} />,
    );

    const root = container.querySelector('[data-qb="export-workbench"]');
    expect(root?.getAttribute("data-qb-unstyled")).toBe("true");
    expect(root?.getAttribute("style")).toBeNull();

    // Switch to SQL tab in unstyled mode
    act(() => {
      fireEvent.click(screen.getByText("Compiled SQL"));
    });
    expect(screen.getByLabelText("Select Dialect for compiled SQL")).toBeTruthy();

    // Switch to JSON AST tab in unstyled mode
    act(() => {
      fireEvent.click(screen.getByText("JSON AST"));
    });
    expect(screen.getByText(/"table": "users"/)).toBeTruthy();

    // Switch to Streaming Export tab in unstyled mode
    act(() => {
      fireEvent.click(screen.getByText("Streaming Export"));
    });
    expect(screen.getByLabelText("Select Export Format")).toBeTruthy();
  });

  it("generates SDK snippet with column without alias and join without cols", () => {
    const customSpec: QuerySpec = makeSpec({
      table: "users",
      columns: [{ column: "name" }],
      joins: [{ table: "roles", type: "INNER JOIN" }],
      limit: 10,
    });
    const code = generateSdkSnippet(customSpec);
    expect(code).toContain('.select(["name"])');
    expect(code).toContain('.join("roles", "id", "=", "id")');
  });

  it("handles csv download and string rejection error", async () => {
    const createObjectURLMock = vi.fn().mockReturnValue("blob:http://localhost/test-csv");
    const revokeObjectURLMock = vi.fn();
    window.URL.createObjectURL = createObjectURLMock;
    window.URL.revokeObjectURL = revokeObjectURLMock;

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(new Blob(["csv content"])),
    });
    globalThis.fetch = mockFetch;

    const { rerender } = render(<ExportWorkbench spec={sampleSpec} />);
    act(() => {
      fireEvent.click(screen.getByText("Streaming Export"));
    });
    await act(async () => {
      fireEvent.click(screen.getByText("⬇ Download Stream"));
    });
    expect(screen.getByText("Download complete!")).toBeTruthy();

    // String rejection error (no .message property)
    globalThis.fetch = vi.fn().mockRejectedValue("Raw string failure");
    rerender(<ExportWorkbench spec={sampleSpec} />);
    await act(async () => {
      fireEvent.click(screen.getByText("⬇ Download Stream"));
    });
    expect(screen.getByText("Export error: Raw string failure")).toBeTruthy();
  });

  it("generates SDK snippet with fallback defaults when spec is minimal", () => {
    const minimalSpec = { table: "" };
    const code = generateSdkSnippet(minimalSpec);
    expect(code).toContain('.from("table")');
    expect(code).toContain(".select([])");
  });
});
