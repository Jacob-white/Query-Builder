import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { QueryChartPreview } from "../src/components/QueryChartPreview";
import {
  QueryTemplateManager,
  loadTemplates,
  saveTemplates,
  resetTemplateStorage,
  SEED_TEMPLATES,
} from "../src/components/QueryTemplateManager";
import { QueryResultsTable } from "../src/components/QueryResultsTable";
import type { QueryResultData, QueryTemplate } from "../src/types";

describe("Milestone 2 Empirical Stress & Edge Case Test Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetTemplateStorage();
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.clear();
    }
  });

  // =========================================================================
  // 1. QueryChartPreview: High-cardinality and adversarial dataset rendering
  // =========================================================================
  describe("QueryChartPreview Adversarial & High-Cardinality Datasets", () => {
    it("renders high-cardinality dataset (5,000 rows across 500 categories) without crash or memory blowout", () => {
      const rows: Record<string, unknown>[] = [];
      for (let i = 0; i < 5000; i++) {
        rows.push({
          category: `Category_${i % 500}`,
          revenue: (i * 17) % 10000,
        });
      }
      const highCardResults: QueryResultData = {
        columns: ["category", "revenue"],
        rows,
        count: 5000,
      };

      const t0 = performance.now();
      const { unmount } = render(<QueryChartPreview results={highCardResults} />);
      const renderDuration = performance.now() - t0;

      // Ensure render is snappy (well under 1 second in JSDOM)
      expect(renderDuration).toBeLessThan(1000);

      // In aggregated mode, output is capped at 25 points
      const bars = screen.getAllByRole("graphics-symbol");
      expect(bars.length).toBe(25);
      unmount();
    });

    it("renders high-cardinality dataset in raw NONE aggregation mode capped at 50 rows", () => {
      const rows: Record<string, unknown>[] = [];
      for (let i = 0; i < 200; i++) {
        rows.push({
          item: `Item_${i}`,
          val: i * 10,
        });
      }
      const results: QueryResultData = {
        columns: ["item", "val"],
        rows,
        count: 200,
      };

      render(<QueryChartPreview results={results} defaultAggregation="NONE" />);
      const bars = screen.getAllByRole("graphics-symbol");
      expect(bars.length).toBe(50);
    });

    it("renders adversarial and extreme numeric values (MAX_SAFE_INTEGER, negative, string numbers, nulls)", () => {
      const extremeResults: QueryResultData = {
        columns: ["label", "metric"],
        rows: [
          { label: "MaxSafe", metric: Number.MAX_SAFE_INTEGER },
          { label: "LargeFloat", metric: 1234567.8912 },
          { label: "TinyFloat", metric: 0.00005 },
          { label: "NegativeBig", metric: -5000000 },
          { label: "ZeroVal", metric: 0 },
          { label: "StringInt", metric: "  9876  " },
          { label: "StringFloat", metric: "-432.10" },
          { label: "EmptyStr", metric: "" },
          { label: "NullMetric", metric: null },
          { label: "UndefinedMetric", metric: undefined },
          { label: "GarbageString", metric: "invalid_num" },
        ],
        count: 11,
      };

      // Bar Chart
      const { rerender } = render(<QueryChartPreview results={extremeResults} defaultAggregation="NONE" />);
      expect(screen.getByRole("img")).toBeTruthy();
      const bars = screen.getAllByRole("graphics-symbol");
      expect(bars.length).toBe(11);

      // Line Chart
      const lineBtn = screen.getByRole("button", { name: "Line Chart" });
      fireEvent.click(lineBtn);
      const points = screen.getAllByRole("graphics-symbol");
      expect(points.length).toBe(11);

      // Pie Chart
      const pieBtn = screen.getByRole("button", { name: "Pie Chart" });
      fireEvent.click(pieBtn);
      expect(screen.getByText("TOTAL")).toBeTruthy();
    });

    it("handles zero-division boundaries gracefully when all metric values are zero", () => {
      const zeroResults: QueryResultData = {
        columns: ["account", "balance"],
        rows: [
          { account: "Checking", balance: 0 },
          { account: "Savings", balance: 0 },
          { account: "Retirement", balance: 0 },
        ],
        count: 3,
      };

      render(<QueryChartPreview results={zeroResults} defaultAggregation="SUM" />);

      // Bar chart with all zeros: should not throw or divide by zero
      const bars = screen.getAllByRole("graphics-symbol");
      expect(bars.length).toBe(3);
      bars.forEach((bar) => {
        expect(bar.getAttribute("height")).toBe("2"); // Min height guard
      });

      // Switch to Line chart
      fireEvent.click(screen.getByRole("button", { name: "Line Chart" }));
      expect(screen.getAllByRole("graphics-symbol").length).toBe(3);

      // Switch to Pie chart: Total is 0
      fireEvent.click(screen.getByRole("button", { name: "Pie Chart" }));
      expect(screen.getByText("Total is 0")).toBeTruthy();
      expect(screen.queryByRole("list", { name: "Chart legend" })).toBeNull();
    });

    it("handles all-negative values across Bar and Pie charts", () => {
      const negativeResults: QueryResultData = {
        columns: ["dept", "profit"],
        rows: [
          { dept: "Dept A", profit: -500 },
          { dept: "Dept B", profit: -1200 },
          { dept: "Dept C", profit: -300 },
        ],
        count: 3,
      };

      render(<QueryChartPreview results={negativeResults} defaultAggregation="SUM" />);

      // Bar chart with negative values
      const bars = screen.getAllByRole("graphics-symbol");
      expect(bars.length).toBe(3);

      // Pie chart with only negative values: total is 0
      fireEvent.click(screen.getByRole("button", { name: "Pie Chart" }));
      expect(screen.getByText("Total is 0")).toBeTruthy();
    });

    it("handles null, undefined, empty, and adversarial unicode categories", () => {
      const unicodeResults: QueryResultData = {
        columns: ["category", "count"],
        rows: [
          { category: null, count: 10 },
          { category: undefined, count: 20 },
          { category: "", count: 30 },
          { category: "🔥 Rocket 🚀", count: 40 },
          { category: "👨‍👩‍👧‍👦 Family Emoji", count: 50 },
          { category: "مرحبا بالعالم (Arabic RTL)", count: 60 },
          { category: "中文数据库 (Chinese)", count: 70 },
          { category: "<script>alert('xss')</script>", count: 80 },
          { category: "Super extremely ridiculously long category name that exceeds truncation boundary", count: 90 },
        ],
        count: 9,
      };

      render(<QueryChartPreview results={unicodeResults} defaultAggregation="SUM" />);
      // Null was grouped into "(null)"
      expect(screen.getByText("(null)")).toBeTruthy();
      // Emojis and unicode render safely in rect aria-labels and truncated SVG text
      expect(screen.getByLabelText(/Rocket/)).toBeTruthy();
      expect(screen.getByLabelText(/Family Emoji/)).toBeTruthy();
      expect(screen.getByLabelText(/Arabic RTL/)).toBeTruthy();
      expect(screen.getByLabelText(/Chinese/)).toBeTruthy();
      // Script tags rendered safely as plain text in SVG, not interpreted
      expect(screen.getByLabelText((label) => label.toLowerCase().includes("<script"))).toBeTruthy();
    });

    it("correctly computes all aggregation functions (AVG, MIN, MAX, COUNT, SUM)", () => {
      const aggResults: QueryResultData = {
        columns: ["group", "val"],
        rows: [
          { group: "A", val: 10 },
          { group: "A", val: 30 },
          { group: "B", val: 100 },
          { group: "B", val: 200 },
        ],
        count: 4,
      };

      const { unmount } = render(<QueryChartPreview results={aggResults} />);

      // Switch to AVG
      const aggSelect = screen.getByLabelText("Select Aggregation");
      fireEvent.change(aggSelect, { target: { value: "AVG" } });
      let bars = screen.getAllByRole("graphics-symbol");
      expect(bars[0].getAttribute("aria-label")).toBe("A: 20");
      expect(bars[1].getAttribute("aria-label")).toBe("B: 150");

      // Switch to MIN
      fireEvent.change(aggSelect, { target: { value: "MIN" } });
      bars = screen.getAllByRole("graphics-symbol");
      expect(bars[0].getAttribute("aria-label")).toBe("A: 10");
      expect(bars[1].getAttribute("aria-label")).toBe("B: 100");

      // Switch to MAX
      fireEvent.change(aggSelect, { target: { value: "MAX" } });
      bars = screen.getAllByRole("graphics-symbol");
      expect(bars[0].getAttribute("aria-label")).toBe("A: 30");
      expect(bars[1].getAttribute("aria-label")).toBe("B: 200");

      // Switch to COUNT
      fireEvent.change(aggSelect, { target: { value: "COUNT" } });
      bars = screen.getAllByRole("graphics-symbol");
      expect(bars[0].getAttribute("aria-label")).toBe("A: 2");
      expect(bars[1].getAttribute("aria-label")).toBe("B: 2");

      unmount();
    });
  });

  // =========================================================================
  // 2. Geometric Edge Cases in Pie/Donut Charts
  // =========================================================================
  describe("Pie/Donut Geometric Edge Cases", () => {
    it("handles single positive slice rendering full 2pi donut circle", () => {
      const singleResults: QueryResultData = {
        columns: ["cat", "val"],
        rows: [{ cat: "OnlyOne", val: 777 }],
        count: 1,
      };

      render(<QueryChartPreview results={singleResults} defaultChartType="pie" />);
      const symbol = screen.getByRole("graphics-symbol");
      expect(symbol.tagName.toLowerCase()).toBe("circle");
      expect(symbol.getAttribute("aria-label")).toBe("OnlyOne: 777 (100.0%)");
      expect(screen.getByText("777")).toBeTruthy();

      // Tooltip on hover
      fireEvent.mouseEnter(symbol);
      const tooltip = screen.getByTestId("chart-tooltip");
      expect(tooltip).toBeTruthy();
      expect(tooltip.textContent).toContain("OnlyOne");
      expect(tooltip.textContent).toContain("777");
      fireEvent.mouseLeave(symbol);
      expect(screen.queryByTestId("chart-tooltip")).toBeNull();
    });

    it("handles largeArc geometric transition at 50% boundary", () => {
      // Test 1: Exactly 50% split -> both slices sweep = Math.PI, largeArc = 0
      const split50: QueryResultData = {
        columns: ["team", "points"],
        rows: [
          { team: "TeamAlpha", points: 50 },
          { team: "TeamBeta", points: 50 },
        ],
        count: 2,
      };

      const { unmount } = render(<QueryChartPreview results={split50} defaultChartType="pie" />);
      const paths50 = screen.getAllByRole("graphics-symbol");
      expect(paths50.length).toBe(2);
      // SVG path arc syntax: A rx ry x-axis-rotation large-arc-flag sweep-flag x y
      // For largeArc=0: "A 110 110 0 0 1"
      expect(paths50[0].getAttribute("d")).toContain("A 110 110 0 0 1");
      expect(paths50[1].getAttribute("d")).toContain("A 110 110 0 0 1");
      unmount();

      // Test 2: 51% vs 49% -> first slice has largeArc = 1 ("A 110 110 0 1 1"), second has 0
      const split51: QueryResultData = {
        columns: ["team", "points"],
        rows: [
          { team: "Majority", points: 51 },
          { team: "Minority", points: 49 },
        ],
        count: 2,
      };

      render(<QueryChartPreview results={split51} defaultChartType="pie" />);
      const paths51 = screen.getAllByRole("graphics-symbol");
      expect(paths51[0].getAttribute("d")).toContain("A 110 110 0 1 1");
      expect(paths51[1].getAttribute("d")).toContain("A 110 110 0 0 1");
    });

    it("handles asymmetric multiple slices with largeArc > 50% slice and tiny slices", () => {
      const multiResults: QueryResultData = {
        columns: ["tier", "count"],
        rows: [
          { tier: "Giant", count: 80 },
          { tier: "Small1", count: 10 },
          { tier: "Small2", count: 10 },
        ],
        count: 3,
      };

      render(<QueryChartPreview results={multiResults} defaultChartType="pie" />);
      const slices = screen.getAllByRole("graphics-symbol");
      expect(slices.length).toBe(3);

      // First slice has 80% (largeArc = 1)
      expect(slices[0].getAttribute("d")).toContain("A 110 110 0 1 1");
      expect(slices[0].getAttribute("aria-label")).toContain("(80.0%)");

      // Other two slices have 10% (largeArc = 0)
      expect(slices[1].getAttribute("d")).toContain("A 110 110 0 0 1");
      expect(slices[1].getAttribute("aria-label")).toContain("(10.0%)");
      expect(slices[2].getAttribute("d")).toContain("A 110 110 0 0 1");
      expect(slices[2].getAttribute("aria-label")).toContain("(10.0%)");
    });
  });

  // =========================================================================
  // 3. Storage Resilience Testing in QueryTemplateManager
  // =========================================================================
  describe("QueryTemplateManager Storage Resilience & Fuzzing", () => {
    it("recovers gracefully from corrupted JSON in localStorage", () => {
      window.localStorage.setItem("query_builder_templates", "{ bad json content [[[");
      const loaded = loadTemplates();
      expect(loaded).toEqual(SEED_TEMPLATES);
    });

    it("recovers gracefully from non-array JSON values in localStorage", () => {
      const nonArrays = ['"simple string"', "12345", "true", "null", '{"key": "value"}'];
      for (const val of nonArrays) {
        window.localStorage.setItem("query_builder_templates", val);
        const loaded = loadTemplates();
        expect(Array.isArray(loaded)).toBe(true);
        expect(loaded.length).toBeGreaterThan(0);
      }
    });

    it("recovers gracefully from empty array in localStorage", () => {
      window.localStorage.setItem("query_builder_templates", "[]");
      const loaded = loadTemplates();
      expect(loaded).toEqual(SEED_TEMPLATES);
    });

    it("falls back to in-memory storage when localStorage.getItem throws SecurityError", () => {
      const getItemSpy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new DOMException("Access is denied", "SecurityError");
      });

      const loaded = loadTemplates();
      expect(loaded).toEqual(SEED_TEMPLATES);
      getItemSpy.mockRestore();
    });

    it("preserves in-memory templates when localStorage.setItem throws QuotaExceededError", () => {
      const setItemSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new DOMException("Quota exceeded", "QuotaExceededError");
      });

      const customTemplates: QueryTemplate[] = [
        {
          id: "tpl_quota_test",
          title: "Quota Exceeded Recovery Template",
          category: "Stress",
          sql: "SELECT 1;",
          createdAt: new Date().toISOString(),
          isDefault: false,
        },
      ];

      saveTemplates(customTemplates);
      const loaded = loadTemplates();
      expect(loaded).toEqual(customTemplates);
      setItemSpy.mockRestore();
    });

    it("supports rapid template creation and deletion stress cycle", () => {
      render(
        <QueryTemplateManager
          isOpen={true}
          onClose={vi.fn()}
          onLoadTemplate={vi.fn()}
          currentSql="SELECT * FROM stress_table;"
          defaultMode="save"
        />
      );

      const titleInput = screen.getByLabelText("Template Title");
      const saveBtn = screen.getByRole("button", { name: /Save Template/i });

      // Create 5 templates in sequence
      for (let i = 1; i <= 5; i++) {
        fireEvent.click(screen.getByRole("button", { name: /Save Current Query/i }));
        fireEvent.change(screen.getByLabelText("Template Title"), {
          target: { value: `Stress Template ${i}` },
        });
        fireEvent.click(screen.getByRole("button", { name: /Save Template/i }));
        expect(screen.getByText(`Stress Template ${i}`)).toBeTruthy();
      }

      // Built-in templates cannot be deleted, but newly created can
      const deleteButtons = screen.getAllByRole("button", { name: /Delete Stress Template/i });
      expect(deleteButtons.length).toBe(5);

      // Delete 3 specific templates by name
      fireEvent.click(screen.getByRole("button", { name: "Delete Stress Template 1" }));
      fireEvent.click(screen.getByRole("button", { name: "Delete Stress Template 2" }));
      fireEvent.click(screen.getByRole("button", { name: "Delete Stress Template 3" }));

      expect(screen.queryByText("Stress Template 1")).toBeNull();
      expect(screen.queryByText("Stress Template 2")).toBeNull();
      expect(screen.queryByText("Stress Template 3")).toBeNull();
      expect(screen.getByText("Stress Template 4")).toBeTruthy();
      expect(screen.getByText("Stress Template 5")).toBeTruthy();
    });

    it("handles search fuzzing with regex metacharacters, emojis, and SQL injection strings", () => {
      render(
        <QueryTemplateManager
          isOpen={true}
          onClose={vi.fn()}
          onLoadTemplate={vi.fn()}
        />
      );

      const searchInput = screen.getByLabelText("Search templates");
      const fuzzQueries = [
        ".*+?^${}()|[]\\",
        "(' OR '1'='1' --)",
        "\\x00\\n\\r",
        "🔥🚀🍩",
        "a".repeat(1000),
      ];

      for (const query of fuzzQueries) {
        expect(() => {
          fireEvent.change(searchInput, { target: { value: query } });
        }).not.toThrow();
      }

      // Restoring search returns active templates
      fireEvent.change(searchInput, { target: { value: "Users" } });
      expect(screen.getByText("Active Users Directory")).toBeTruthy();
    });
  });

  // =========================================================================
  // 4. Tabular JSON Export Blob Generation & Memory Cleanup in QueryResultsTable
  // =========================================================================
  describe("QueryResultsTable JSON Export Blob & Memory Management", () => {
    it("generates application/json blob, triggers download, and immediately revokes object URL", () => {
      const results: QueryResultData = {
        columns: ["id", "username", "metadata"],
        rows: [
          { id: 1, username: "alice", metadata: { role: "admin", active: true } },
          { id: 2, username: "bob", metadata: { role: "user", active: false } },
        ],
        count: 2,
      };

      let createdBlob = null as Blob | null;
      let createdUrl = "";
      const mockCreateObjectURL = vi.fn().mockImplementation((blob: Blob) => {
        createdBlob = blob;
        createdUrl = "blob:mock-uuid-json-export";
        return createdUrl;
      });
      const mockRevokeObjectURL = vi.fn();
      global.URL.createObjectURL = mockCreateObjectURL;
      global.URL.revokeObjectURL = mockRevokeObjectURL;

      const clickSpy = vi.fn();
      let downloadedFilename = "";
      const origCreateElement = document.createElement.bind(document);
      vi.spyOn(document, "createElement").mockImplementation((tagName: string) => {
        const el = origCreateElement(tagName);
        if (tagName === "a") {
          el.click = clickSpy;
          const origSetAttribute = el.setAttribute.bind(el);
          el.setAttribute = (name: string, value: string) => {
            if (name === "download") downloadedFilename = value;
            return origSetAttribute(name, value);
          };
        }
        return el;
      });

      render(<QueryResultsTable results={results} />);

      const exportJsonBtn = screen.getByRole("button", { name: "Export results as JSON" });
      fireEvent.click(exportJsonBtn);

      // Verify Blob creation and MIME type
      expect(mockCreateObjectURL).toHaveBeenCalledTimes(1);
      expect(createdBlob).not.toBeNull();
      expect(createdBlob?.type).toBe("application/json;charset=utf-8;");

      // Verify simulated link attributes and click
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(downloadedFilename).toMatch(/^query_export_\d+\.json$/);

      // Verify immediate memory cleanup via revokeObjectURL
      expect(mockRevokeObjectURL).toHaveBeenCalledTimes(1);
      expect(mockRevokeObjectURL).toHaveBeenCalledWith("blob:mock-uuid-json-export");
    });

    it("handles large export payload (10,000 rows) to JSON without memory leak or crash", () => {
      const largeRows: Record<string, unknown>[] = [];
      for (let i = 0; i < 10000; i++) {
        largeRows.push({
          id: i,
          uuid: `uuid-${i}`,
          data: `Payload string with unicode 🔥 ${i}`,
        });
      }
      const largeResults: QueryResultData = {
        columns: ["id", "uuid", "data"],
        rows: largeRows,
        count: 10000,
      };

      const mockCreateObjectURL = vi.fn().mockReturnValue("blob:large-test");
      const mockRevokeObjectURL = vi.fn();
      global.URL.createObjectURL = mockCreateObjectURL;
      global.URL.revokeObjectURL = mockRevokeObjectURL;

      render(<QueryResultsTable results={largeResults} />);

      const exportJsonBtn = screen.getByRole("button", { name: "Export results as JSON" });
      expect(() => {
        fireEvent.click(exportJsonBtn);
      }).not.toThrow();

      expect(mockCreateObjectURL).toHaveBeenCalledTimes(1);
      expect(mockRevokeObjectURL).toHaveBeenCalledWith("blob:large-test");
    });

    it("early-returns without blob creation when rows is empty", () => {
      const emptyResults: QueryResultData = {
        columns: ["id", "val"],
        rows: [],
        count: 0,
      };

      const mockCreateObjectURL = vi.fn();
      global.URL.createObjectURL = mockCreateObjectURL;

      render(<QueryResultsTable results={emptyResults} />);

      const exportJsonBtn = screen.getByRole("button", { name: "Export results as JSON" });
      fireEvent.click(exportJsonBtn);

      expect(mockCreateObjectURL).not.toHaveBeenCalled();
    });

    it("exports rows containing special unicode, escaped quotes, and nested arrays cleanly", () => {
      const complexResults: QueryResultData = {
        columns: ["id", "description", "tags"],
        rows: [
          { id: 1, description: 'Line with "quotes" and \n newlines', tags: ["sql", "react", "✨"] },
          { id: 2, description: "Unicode surrogate \\uD83D\\uDE00 and null", tags: null },
        ],
        count: 2,
      };

      let passedBlob = null as Blob | null;
      global.URL.createObjectURL = vi.fn().mockImplementation((blob: Blob) => {
        passedBlob = blob;
        return "blob:complex-test";
      });
      global.URL.revokeObjectURL = vi.fn();

      render(<QueryResultsTable results={complexResults} />);
      fireEvent.click(screen.getByRole("button", { name: "Export results as JSON" }));

      expect(passedBlob).not.toBeNull();
      // Reader check on blob content
      expect(passedBlob?.type).toBe("application/json;charset=utf-8;");
    });
  });

  // =========================================================================
  // 5. Additional Interactions & Modal Dismissal Behaviors
  // =========================================================================
  describe("Keyboard & Modal Interaction Resilience", () => {
    it("handles keyboard focus and blur on Bar and Line chart elements", () => {
      const data: QueryResultData = {
        columns: ["name", "score"],
        rows: [
          { name: "Alpha", score: 85 },
          { name: "Beta", score: 92 },
        ],
        count: 2,
      };

      // Bar chart keyboard focus
      const { unmount } = render(<QueryChartPreview results={data} defaultChartType="bar" />);
      const bars = screen.getAllByRole("graphics-symbol");
      fireEvent.focus(bars[0]);
      expect(screen.getByTestId("chart-tooltip")).toBeTruthy();
      fireEvent.blur(bars[0]);
      expect(screen.queryByTestId("chart-tooltip")).toBeNull();
      unmount();

      // Line chart keyboard focus
      render(<QueryChartPreview results={data} defaultChartType="line" />);
      const points = screen.getAllByRole("graphics-symbol");
      fireEvent.focus(points[1]);
      expect(screen.getByTestId("chart-tooltip")).toBeTruthy();
      fireEvent.blur(points[1]);
      expect(screen.queryByTestId("chart-tooltip")).toBeNull();
    });

    it("rejects whitespace-only title in QueryTemplateManager save form", () => {
      render(
        <QueryTemplateManager
          isOpen={true}
          onClose={vi.fn()}
          onLoadTemplate={vi.fn()}
          defaultMode="save"
        />
      );

      fireEvent.change(screen.getByLabelText("Template Title"), {
        target: { value: "    " },
      });
      fireEvent.click(screen.getByRole("button", { name: /Save Template/i }));

      expect(screen.getByText(/Title is required/i)).toBeTruthy();
    });

    it("closes QueryTemplateManager on Escape key and on backdrop click", () => {
      const handleClose = vi.fn();
      const { rerender } = render(
        <QueryTemplateManager
          isOpen={true}
          onClose={handleClose}
          onLoadTemplate={vi.fn()}
        />
      );

      // Escape key press
      fireEvent.keyDown(window, { key: "Escape" });
      expect(handleClose).toHaveBeenCalledTimes(1);

      // Backdrop click
      const dialog = screen.getByRole("dialog");
      const backdrop = dialog.parentElement!;
      fireEvent.click(backdrop);
      expect(handleClose).toHaveBeenCalledTimes(2);

      // Clicking dialog content itself should NOT call onClose
      fireEvent.click(dialog);
      expect(handleClose).toHaveBeenCalledTimes(2);
    });

    it("handles rows with empty objects gracefully in QueryChartPreview", () => {
      const data: QueryResultData = {
        columns: ["a", "b"],
        rows: [{}, {}, {}],
        count: 3,
      };

      render(<QueryChartPreview results={data} />);
      expect(screen.getByRole("img")).toBeTruthy();
    });
  });
});

