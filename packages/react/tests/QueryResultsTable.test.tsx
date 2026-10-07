import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryResultsTable } from "../src/components/QueryResultsTable";
import type { QueryResultData } from "../src/types";

describe("QueryResultsTable", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.URL.revokeObjectURL = vi.fn();
  });

  it("renders loading indicator when isLoading is true", () => {
    render(<QueryResultsTable results={null} isLoading={true} />);
    expect(screen.getByText(/Executing read-only query/i)).toBeTruthy();
  });

  it("renders empty state message when results is null", () => {
    render(<QueryResultsTable results={null} isLoading={false} />);
    expect(screen.getByText(/No query executed yet/i)).toBeTruthy();
  });

  it("renders table headers, rows, count, and latency badge", () => {
    const results: QueryResultData = {
      columns: ["id", "username", "score"],
      rows: [
        { id: 1, username: "alice", score: 95 },
        { id: 2, username: "bob", score: null },
      ],
      count: 2,
      latency_ms: 14.5,
    };

    render(<QueryResultsTable results={results} />);

    expect(screen.getByText("id")).toBeTruthy();
    expect(screen.getByText("username")).toBeTruthy();
    expect(screen.getByText("score")).toBeTruthy();
    expect(screen.getByText("alice")).toBeTruthy();
    expect(screen.getByText("95")).toBeTruthy();
    expect(screen.getByText("null")).toBeTruthy();
    expect(screen.getByText(/Showing/)).toBeTruthy();
    expect(screen.getByText("⚡ 14.5 ms")).toBeTruthy();
  });

  it("filters rows dynamically as user types in search box", () => {
    const results: QueryResultData = {
      columns: ["id", "username"],
      rows: [
        { id: 1, username: "alice" },
        { id: 2, username: "bob" },
        { id: 3, username: "charlie" },
      ],
      count: 3,
    };

    render(<QueryResultsTable results={results} />);

    expect(screen.getByText("alice")).toBeTruthy();
    expect(screen.getByText("bob")).toBeTruthy();
    expect(screen.getByText("charlie")).toBeTruthy();

    const searchInput = screen.getByPlaceholderText("Search results...");
    fireEvent.change(searchInput, { target: { value: "bob" } });

    expect(screen.queryByText("alice")).toBeNull();
    expect(screen.getByText("bob")).toBeTruthy();
    expect(screen.queryByText("charlie")).toBeNull();
    expect(screen.getByText(/Showing/)).toBeTruthy();
  });

  it("handles CSV export trigger correctly", () => {
    const results: QueryResultData = {
      columns: ["id", "name"],
      rows: [
        { id: 1, name: 'Alice "The Great"' },
        { id: 2, name: "Bob" },
      ],
      count: 2,
    };

    // Mock URL.createObjectURL and revokeObjectURL
    const mockCreateObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    global.URL.createObjectURL = mockCreateObjectURL;

    // Spy on appendChild and click
    const clickSpy = vi.fn();
    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tagName: string) => {
      const el = origCreateElement(tagName);
      if (tagName === "a") {
        el.click = clickSpy;
      }
      return el;
    });

    render(<QueryResultsTable results={results} />);

    const exportBtn = screen.getByText("📥 Export CSV");
    fireEvent.click(exportBtn);

    expect(mockCreateObjectURL).toHaveBeenCalledOnce();
    expect(clickSpy).toHaveBeenCalledOnce();
  });

  it("does not attempt export when rows array is empty", () => {
    const results: QueryResultData = {
      columns: ["id", "name"],
      rows: [],
      count: 0,
    };

    const mockCreateObjectURL = vi.fn();
    global.URL.createObjectURL = mockCreateObjectURL;

    render(<QueryResultsTable results={results} />);

    const exportBtn = screen.getByText("📥 Export CSV");
    fireEvent.click(exportBtn);

    expect(mockCreateObjectURL).not.toHaveBeenCalled();
  });

  it("handles undefined columns/rows, and null values in search filter and CSV export", () => {
    // 1. undefined columns and rows (lines 50-51)
    const { unmount: unmount1 } = render(<QueryResultsTable results={{} as any} />);
    expect(screen.getByText(/Showing/)).toBeTruthy();
    unmount1();

    // 2. null values in row during search filter (line 57)
    const resultsWithNull: QueryResultData = {
      columns: ["id", "val"],
      rows: [
        { id: 1, val: null },
        { id: 2, val: undefined },
        { id: 3, val: "matched" },
      ],
      count: 3,
    };
    const { unmount } = render(<QueryResultsTable results={resultsWithNull} />);
    const searchInput = screen.getByPlaceholderText("Search results...");
    fireEvent.change(searchInput, { target: { value: "matched" } });
    expect(screen.getByText("matched")).toBeTruthy();
    unmount();

    // 3. null values during CSV export (line 68)
    const mockCreateObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    global.URL.createObjectURL = mockCreateObjectURL;
    render(<QueryResultsTable results={resultsWithNull} />);
    const exportBtn = screen.getByText("📥 Export CSV");
    fireEvent.click(exportBtn);
    expect(mockCreateObjectURL).toHaveBeenCalledOnce();
  });

  it("handles JSON export trigger correctly", () => {
    const results: QueryResultData = {
      columns: ["id", "name"],
      rows: [
        { id: 1, name: "Alice" },
        { id: 2, name: "Bob" },
      ],
      count: 2,
    };

    const mockCreateObjectURL = vi.fn().mockReturnValue("blob:mock-json-url");
    const mockRevokeObjectURL = vi.fn();
    global.URL.createObjectURL = mockCreateObjectURL;
    global.URL.revokeObjectURL = mockRevokeObjectURL;

    const clickSpy = vi.fn();
    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tagName: string) => {
      const el = origCreateElement(tagName);
      if (tagName === "a") {
        el.click = clickSpy;
      }
      return el;
    });

    render(<QueryResultsTable results={results} />);

    const exportBtn = screen.getByText("📥 Export JSON");
    fireEvent.click(exportBtn);

    expect(mockCreateObjectURL).toHaveBeenCalledOnce();
    expect(clickSpy).toHaveBeenCalledOnce();
    expect(mockRevokeObjectURL).toHaveBeenCalledOnce();
  });

  it("does not attempt JSON export when rows array is empty", () => {
    const results: QueryResultData = {
      columns: ["id", "name"],
      rows: [],
      count: 0,
    };

    const mockCreateObjectURL = vi.fn();
    global.URL.createObjectURL = mockCreateObjectURL;

    render(<QueryResultsTable results={results} />);

    const exportBtn = screen.getByText("📥 Export JSON");
    fireEvent.click(exportBtn);

    expect(mockCreateObjectURL).not.toHaveBeenCalled();
  });

  it("verifies ARIA labels and table accessibility roles", () => {
    const results: QueryResultData = {
      columns: ["id", "name"],
      rows: [{ id: 1, name: "Alice" }],
      count: 1,
    };

    render(<QueryResultsTable results={results} />);

    expect(screen.getByRole("button", { name: "Export results as CSV" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Export results as JSON" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Search query results" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Query results" })).toBeTruthy();
    expect(screen.getAllByRole("row").length).toBe(2);
    expect(screen.getAllByRole("columnheader").length).toBe(2);
    expect(screen.getAllByRole("cell").length).toBe(2);
  });

  it("paginates results according to pageSize and supports Next/Previous navigation", () => {
    const results: QueryResultData = {
      columns: ["id", "name"],
      rows: [
        { id: 1, name: "Item 1" },
        { id: 2, name: "Item 2" },
        { id: 3, name: "Item 3" },
        { id: 4, name: "Item 4" },
        { id: 5, name: "Item 5" },
      ],
      count: 5,
    };

    render(<QueryResultsTable results={results} pageSize={2} />);

    // Page 1 should show Item 1 and Item 2
    expect(screen.getByText("Item 1")).toBeTruthy();
    expect(screen.getByText("Item 2")).toBeTruthy();
    expect(screen.queryByText("Item 3")).toBeNull();
    const paginationControls = document.querySelector('[data-qb="results-pagination-controls"]');
    expect(paginationControls?.textContent).toContain("Page 1 of 3");

    const nextBtn = screen.getByRole("button", { name: "Next page" });
    const prevBtn = screen.getByRole("button", { name: "Previous page" });

    expect((prevBtn as HTMLButtonElement).disabled).toBe(true);
    expect((nextBtn as HTMLButtonElement).disabled).toBe(false);

    // Navigate to Page 2
    fireEvent.click(nextBtn);
    expect(screen.queryByText("Item 1")).toBeNull();
    expect(screen.getByText("Item 3")).toBeTruthy();
    expect(screen.getByText("Item 4")).toBeTruthy();
    expect(paginationControls?.textContent).toContain("Page 2 of 3");
    expect((prevBtn as HTMLButtonElement).disabled).toBe(false);

    // Navigate to Page 3
    fireEvent.click(nextBtn);
    expect(screen.getByText("Item 5")).toBeTruthy();
    expect(paginationControls?.textContent).toContain("Page 3 of 3");
    expect((nextBtn as HTMLButtonElement).disabled).toBe(true);

    // Navigate back to Page 2
    fireEvent.click(prevBtn);
    expect(screen.getByText("Item 3")).toBeTruthy();
    expect(paginationControls?.textContent).toContain("Page 2 of 3");
  });
});
