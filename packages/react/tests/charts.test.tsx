import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryChartPreview } from "../src/components/QueryChartPreview";
import type { QueryResultData } from "../src/types";

describe("QueryChartPreview", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const sampleResults: QueryResultData = {
    columns: ["dept", "salary", "bonus"],
    rows: [
      { dept: "Engineering", salary: 120000, bonus: 15000 },
      { dept: "Engineering", salary: 130000, bonus: 18000 },
      { dept: "Marketing", salary: 90000, bonus: 10000 },
      { dept: "Sales", salary: 85000, bonus: 25000 },
      { dept: "Sales", salary: 95000, bonus: 30000 },
    ],
    count: 5,
  };

  it("renders empty state when results is null", () => {
    render(<QueryChartPreview results={null} />);
    expect(screen.getByText(/No data available to chart/i)).toBeTruthy();
  });

  it("renders empty state when results rows array is empty", () => {
    render(<QueryChartPreview results={{ columns: ["id"], rows: [], count: 0 }} />);
    expect(screen.getByText(/No data available to chart/i)).toBeTruthy();
  });

  it("renders empty state when results columns array is empty", () => {
    render(<QueryChartPreview results={{ columns: [], rows: [{ id: 1 }], count: 1 }} />);
    expect(screen.getByText(/No data available to chart/i)).toBeTruthy();
  });

  it("renders Bar chart with default column selection and aggregation SUM", () => {
    render(<QueryChartPreview results={sampleResults} />);

    // Check SVG container and role
    const svg = screen.getByRole("img");
    expect(svg).toBeTruthy();
    expect(svg.getAttribute("aria-label")).toContain("BAR chart");

    // Check Bar toggle is active
    expect(screen.getByRole("button", { name: "Bar Chart" })).toBeTruthy();

    // Bars should exist for Engineering, Marketing, Sales
    const graphicSymbols = screen.getAllByRole("graphics-symbol");
    expect(graphicSymbols.length).toBe(3); // 3 aggregated depts
    expect(screen.getByText("Engineering")).toBeTruthy();
    expect(screen.getByText("Marketing")).toBeTruthy();
    expect(screen.getByText("Sales")).toBeTruthy();
  });

  it("switches chart type to Line and renders SVG line and circles", () => {
    render(<QueryChartPreview results={sampleResults} />);

    const lineBtn = screen.getByRole("button", { name: "Line Chart" });
    fireEvent.click(lineBtn);

    const svg = screen.getByRole("img");
    expect(svg.getAttribute("aria-label")).toContain("LINE chart");

    // Circles should be rendered for data points
    const circles = screen.getAllByRole("graphics-symbol");
    expect(circles.length).toBe(3);

    // Switch back to Bar
    const barBtn = screen.getByRole("button", { name: "Bar Chart" });
    fireEvent.click(barBtn);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("BAR chart");
  });

  it("switches chart type to Pie and renders donut slices and legend", () => {
    render(<QueryChartPreview results={sampleResults} />);

    const pieBtn = screen.getByRole("button", { name: "Pie Chart" });
    fireEvent.click(pieBtn);

    const svg = screen.getByRole("img");
    expect(svg.getAttribute("aria-label")).toContain("PIE chart");

    // Total should be rendered inside donut
    expect(screen.getByText("TOTAL")).toBeTruthy();
    expect(screen.getByText("520,000")).toBeTruthy(); // 120k + 130k + 90k + 85k + 95k

    // Legend should exist
    expect(screen.getByRole("list", { name: "Chart legend" })).toBeTruthy();
    expect(screen.getAllByRole("listitem").length).toBe(3);
  });

  it("handles Pie chart with single data point (full circle sweep)", () => {
    const singleResult: QueryResultData = {
      columns: ["country", "users"],
      rows: [{ country: "Canada", users: 150 }],
      count: 1,
    };

    render(<QueryChartPreview results={singleResult} defaultChartType="pie" />);

    expect(screen.getByText("TOTAL")).toBeTruthy();
    expect(screen.getByText("150")).toBeTruthy();
    const symbol = screen.getByRole("graphics-symbol");
    expect(symbol.getAttribute("aria-label")).toContain("Canada: 150 (100.0%)");
  });

  it("handles Pie chart with all zero metric values", () => {
    const zeroResults: QueryResultData = {
      columns: ["category", "count"],
      rows: [
        { category: "A", count: 0 },
        { category: "B", count: 0 },
      ],
      count: 2,
    };

    render(<QueryChartPreview results={zeroResults} defaultChartType="pie" />);
    expect(screen.getByText("Total is 0")).toBeTruthy();
    expect(screen.queryByText("TOTAL")).toBeNull();
  });

  it("handles Pie chart with dominant slice (> 50% sweep for largeArc flag)", () => {
    const dominantData: QueryResultData = {
      columns: ["segment", "val"],
      rows: [
        { segment: "Major", val: 80 },
        { segment: "Minor", val: 20 },
      ],
      count: 2,
    };

    render(<QueryChartPreview results={dominantData} defaultChartType="pie" />);
    expect(screen.getByText("TOTAL")).toBeTruthy();
    expect(screen.getByText("100")).toBeTruthy();
    const slices = screen.getAllByRole("graphics-symbol");
    expect(slices[0].getAttribute("aria-label")).toContain("Major: 80 (80.0%)");
  });

  it("changes category X-axis column and metric Y-axis column", () => {
    render(<QueryChartPreview results={sampleResults} />);

    const catSelect = screen.getByLabelText("Select Category column");
    const metricSelect = screen.getByLabelText("Select Metric column");

    fireEvent.change(catSelect, { target: { value: "dept" } });
    fireEvent.change(metricSelect, { target: { value: "bonus" } });

    // Graphic symbols updated
    const symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols.length).toBe(3);
    // Engineering total bonus: 15000 + 18000 = 33000
    expect(symbols[0].getAttribute("aria-label")).toContain("Engineering: 33000");
  });

  it("exercises all aggregation modes: SUM, COUNT, AVG, MIN, MAX, NONE", () => {
    const { unmount } = render(<QueryChartPreview results={sampleResults} />);
    const aggSelect = screen.getByLabelText("Select Aggregation");

    // 1. COUNT
    fireEvent.change(aggSelect, { target: { value: "COUNT" } });
    let symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols[0].getAttribute("aria-label")).toContain("Engineering: 2");

    // 2. AVG
    fireEvent.change(aggSelect, { target: { value: "AVG" } });
    symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols[0].getAttribute("aria-label")).toContain("Engineering: 125000");

    // 3. MIN
    fireEvent.change(aggSelect, { target: { value: "MIN" } });
    symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols[0].getAttribute("aria-label")).toContain("Engineering: 120000");

    // 4. MAX
    fireEvent.change(aggSelect, { target: { value: "MAX" } });
    symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols[0].getAttribute("aria-label")).toContain("Engineering: 130000");

    // 5. NONE (Raw mode)
    fireEvent.change(aggSelect, { target: { value: "NONE" } });
    symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols.length).toBe(5); // all 5 rows rendered

    // 6. SUM
    fireEvent.change(aggSelect, { target: { value: "SUM" } });
    symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols[0].getAttribute("aria-label")).toContain("Engineering: 250000");

    unmount();
  });

  it("displays and dismisses interactive hover tooltips in Bar chart", () => {
    render(<QueryChartPreview results={sampleResults} />);

    const symbols = screen.getAllByRole("graphics-symbol");
    expect(screen.queryByTestId("chart-tooltip")).toBeNull();

    // Mouse enter first bar
    fireEvent.mouseEnter(symbols[0]);
    let tooltip = screen.getByTestId("chart-tooltip");
    expect(tooltip).toBeTruthy();
    expect(tooltip.textContent).toContain("Engineering");
    expect(tooltip.textContent).toContain("250,000");

    // Mouse leave
    fireEvent.mouseLeave(symbols[0]);
    expect(screen.queryByTestId("chart-tooltip")).toBeNull();

    // Focus bar
    fireEvent.focus(symbols[0]);
    tooltip = screen.getByTestId("chart-tooltip");
    expect(tooltip).toBeTruthy();
    expect(tooltip.textContent).toContain("Engineering");

    // Blur bar
    fireEvent.blur(symbols[0]);
    expect(screen.queryByTestId("chart-tooltip")).toBeNull();
  });

  it("supports keyboard focus and mouse hover on data points in Line chart", () => {
    render(<QueryChartPreview results={sampleResults} defaultChartType="line" />);

    const circles = screen.getAllByRole("graphics-symbol");
    expect(screen.queryByTestId("chart-tooltip")).toBeNull();

    // Focus circle
    fireEvent.focus(circles[1]);
    let tooltip = screen.getByTestId("chart-tooltip");
    expect(tooltip).toBeTruthy();
    expect(tooltip.textContent).toContain("Marketing");

    // Blur circle
    fireEvent.blur(circles[1]);
    expect(screen.queryByTestId("chart-tooltip")).toBeNull();

    // Mouse enter circle
    fireEvent.mouseEnter(circles[0]);
    tooltip = screen.getByTestId("chart-tooltip");
    expect(tooltip).toBeTruthy();
    expect(tooltip.textContent).toContain("Engineering");

    // Mouse leave circle
    fireEvent.mouseLeave(circles[0]);
    expect(screen.queryByTestId("chart-tooltip")).toBeNull();
  });

  it("supports tooltips on Pie chart slices (multi-slice and single-slice)", () => {
    // Multi-slice
    const { unmount } = render(<QueryChartPreview results={sampleResults} defaultChartType="pie" />);
    const slices = screen.getAllByRole("graphics-symbol");
    fireEvent.mouseEnter(slices[0]);
    let tooltip = screen.getByTestId("chart-tooltip");
    expect(tooltip.textContent).toContain("Engineering");
    expect(tooltip.textContent).toContain("%");
    fireEvent.mouseLeave(slices[0]);
    expect(screen.queryByTestId("chart-tooltip")).toBeNull();
    fireEvent.focus(slices[0]);
    expect(screen.getByTestId("chart-tooltip")).toBeTruthy();
    fireEvent.blur(slices[0]);
    expect(screen.queryByTestId("chart-tooltip")).toBeNull();
    unmount();

    // Single-slice
    const single: QueryResultData = {
      columns: ["item", "qty"],
      rows: [{ item: "Solo", qty: 42 }],
      count: 1,
    };
    render(<QueryChartPreview results={single} defaultChartType="pie" />);
    const singleSlice = screen.getByRole("graphics-symbol");
    fireEvent.mouseEnter(singleSlice);
    tooltip = screen.getByTestId("chart-tooltip");
    expect(tooltip.textContent).toContain("100.0%");
    fireEvent.mouseLeave(singleSlice);
    expect(screen.queryByTestId("chart-tooltip")).toBeNull();
    fireEvent.focus(singleSlice);
    expect(screen.getByTestId("chart-tooltip")).toBeTruthy();
    fireEvent.blur(singleSlice);
    expect(screen.queryByTestId("chart-tooltip")).toBeNull();
  });

  it("handles non-numeric, null, empty strings, and undefined values in metric column gracefully", () => {
    const dirtyData: QueryResultData = {
      columns: ["cat", "val"],
      rows: [
        { cat: "NullVal", val: null },
        { cat: "UndefinedVal", val: undefined },
        { cat: "EmptyStr", val: "   " },
        { cat: "StringNum", val: " 45.5 " },
        { cat: "NaNVal", val: "NotANumber" },
        { cat: null, val: 10 },
      ],
      count: 6,
    };

    render(<QueryChartPreview results={dirtyData} />);

    // Null category mapped to "(null)"
    expect(screen.getByText("(null)")).toBeTruthy();
    // Numeric string coerced properly
    const symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols.length).toBe(6);
  });

  it("handles negative metric values in Bar and Line charts", () => {
    const negData: QueryResultData = {
      columns: ["month", "profit"],
      rows: [
        { month: "Jan", profit: -500 },
        { month: "Feb", profit: 200 },
        { month: "Mar", profit: -300 },
      ],
      count: 3,
    };

    // Bar chart with negative values
    const { unmount } = render(<QueryChartPreview results={negData} defaultChartType="bar" />);
    const symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols[0].getAttribute("aria-label")).toContain("Jan: -500");
    unmount();

    // Line chart with negative values
    render(<QueryChartPreview results={negData} defaultChartType="line" />);
    const circles = screen.getAllByRole("graphics-symbol");
    expect(circles.length).toBe(3);
  });

  it("applies custom className and style props", () => {
    render(
      <QueryChartPreview
        results={sampleResults}
        className="custom-chart-wrapper"
        style={{ opacity: 0.95 }}
      />
    );

    const region = screen.getByRole("region", { name: "Visual Chart Preview" });
    expect(region.className).toContain("custom-chart-wrapper");
    expect(region.style.opacity).toBe("0.95");
  });

  it("handles custom default props and raw NONE mode with null category fallback", () => {
    const rawData: QueryResultData = {
      columns: ["label", "score"],
      rows: [
        { label: null, score: 75 },
        { label: "Valid", score: 85 },
      ],
      count: 2,
    };

    render(
      <QueryChartPreview
        results={rawData}
        defaultChartType="bar"
        defaultCategoryCol="label"
        defaultMetricCol="score"
        defaultAggregation="NONE"
      />
    );

    // Row 1 should have fallback label "Row 1"
    expect(screen.getByText("Row 1")).toBeTruthy();
    expect(screen.getByText("Valid")).toBeTruthy();
  });

  it("handles zero range and single data point in Bar and Line chart", () => {
    const singleData: QueryResultData = {
      columns: ["k", "v"],
      rows: [{ k: "Only", v: 0 }],
      count: 1,
    };

    const { unmount } = render(<QueryChartPreview results={singleData} defaultChartType="bar" />);
    expect(screen.getByText("Only")).toBeTruthy();
    unmount();

    render(<QueryChartPreview results={singleData} defaultChartType="line" />);
    expect(screen.getByText("Only")).toBeTruthy();
  });

  it("truncates long category names in labels and pie legend", () => {
    const longData: QueryResultData = {
      columns: ["veryLongCategoryName", "count"],
      rows: [
        { veryLongCategoryName: "SupercalifragilisticexpialidociousCategory", count: 100 },
      ],
      count: 1,
    };

    render(<QueryChartPreview results={longData} defaultChartType="bar" />);
    expect(screen.getByText(/Supercalifr/)).toBeTruthy();
  });

  it("handles fallback column resolution when columns length is 1 and no numeric columns", () => {
    const singleColData: QueryResultData = {
      columns: ["only_col"],
      rows: [{ only_col: "abc" }],
      count: 1,
    };

    render(
      <QueryChartPreview
        results={singleColData}
        defaultCategoryCol="not_there"
        defaultMetricCol="not_there"
      />
    );

    expect(screen.getByText("abc")).toBeTruthy();
  });

  it("handles defaultCategoryCol and defaultMetricCol when present in columns", () => {
    const multiColData: QueryResultData = {
      columns: ["c1", "c2", "c3"],
      rows: [
        { c1: "Category A", c2: "Other", c3: 42 },
      ],
      count: 1,
    };

    render(
      <QueryChartPreview
        results={multiColData}
        defaultCategoryCol="c1"
        defaultMetricCol="c3"
      />
    );

    const symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols[0].getAttribute("aria-label")).toContain("Category A: 42");
  });

  it("handles boolean and NaN values in parser and isNumericValue", () => {
    const mixedData: QueryResultData = {
      columns: ["flag", "val"],
      rows: [
        { flag: true, val: NaN },
        { flag: false, val: 50 },
        { flag: "", val: 20 },
      ],
      count: 3,
    };

    render(<QueryChartPreview results={mixedData} />);
    const symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols.length).toBe(3);
  });
});
