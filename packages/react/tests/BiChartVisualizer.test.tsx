import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { BiChartVisualizer } from "../src/components/BiChartVisualizer";
import type { QueryResultData } from "../src/types";

describe("BiChartVisualizer Component", () => {
  const sampleResults: QueryResultData = {
    columns: ["department", "salary", "bonus"],
    rows: [
      { department: "Engineering", salary: 120000, bonus: 15000 },
      { department: "Sales", salary: 90000, bonus: 30000 },
      { department: "Marketing", salary: 85000, bonus: 10000 },
      { department: "HR", salary: 70000, bonus: 5000 },
    ],
    count: 4,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders empty state when results is null or empty", () => {
    const { rerender } = render(<BiChartVisualizer results={null} />);
    expect(screen.getByText(/No data available to chart/)).toBeTruthy();

    rerender(<BiChartVisualizer results={{ columns: [], rows: [], count: 0 }} />);
    expect(screen.getByText(/No data available to chart/)).toBeTruthy();

    rerender(<BiChartVisualizer results={{ columns: ["id"], rows: [], count: 0 }} />);
    expect(screen.getByText(/No data available to chart/)).toBeTruthy();
  });

  it("renders Bar chart by default with controls and series", () => {
    render(<BiChartVisualizer results={sampleResults} />);

    expect(screen.getByLabelText("Bar Chart")).toBeTruthy();
    expect(screen.getByLabelText("Bar chart series")).toBeTruthy();
    const symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols.length).toBe(4);
  });

  it("switches to Line and Area charts", () => {
    render(<BiChartVisualizer results={sampleResults} />);

    // Switch to Line
    fireEvent.click(screen.getByLabelText("Line Chart"));
    expect(screen.getByLabelText("Line chart series")).toBeTruthy();

    // Switch to Area
    fireEvent.click(screen.getByLabelText("Area Chart"));
    expect(screen.getByLabelText("Area chart series")).toBeTruthy();
  });

  it("switches to Scatter plot and renders scatter points", () => {
    render(<BiChartVisualizer results={sampleResults} />);

    fireEvent.click(screen.getByLabelText("Scatter Plot"));
    expect(screen.getByLabelText("Scatter plot series")).toBeTruthy();
    const symbols = screen.getAllByRole("graphics-symbol");
    expect(symbols.length).toBe(4);
  });

  it("switches to Donut and Pie charts with center metrics and legend", () => {
    render(<BiChartVisualizer results={sampleResults} />);

    // Donut
    fireEvent.click(screen.getByLabelText("Donut Chart"));
    expect(screen.getByLabelText("Donut chart series")).toBeTruthy();
    expect(screen.getByText("TOTAL")).toBeTruthy();
    expect(screen.getByLabelText("Chart legend")).toBeTruthy();

    // Pie
    fireEvent.click(screen.getByLabelText("Pie Chart"));
    expect(screen.getByLabelText("Pie chart series")).toBeTruthy();
  });

  it("switches to KPI Card and renders formatted metric and trend badge", () => {
    render(
      <BiChartVisualizer
        results={sampleResults}
        kpiTitle="Total Department Salaries"
        kpiSubtitle="Quarterly Snapshot"
      />
    );

    fireEvent.click(screen.getByLabelText("KPI Card"));
    expect(screen.getByTestId("kpi-card")).toBeTruthy();
    expect(screen.getByText("Total Department Salaries")).toBeTruthy();
    expect(screen.getByText("Quarterly Snapshot")).toBeTruthy();
    expect(screen.getByTestId("kpi-value")).toBeTruthy();
    expect(screen.getByTestId("kpi-badge")).toBeTruthy();
    expect(screen.getByTestId("kpi-sparkline")).toBeTruthy();
  });

  it("supports controlled chartType and stacked props", () => {
    const onChartTypeChange = vi.fn();
    const onStackedChange = vi.fn();

    const { rerender } = render(
      <BiChartVisualizer
        results={sampleResults}
        chartType="bar"
        onChartTypeChange={onChartTypeChange}
        stacked={false}
        onStackedChange={onStackedChange}
      />
    );

    // Toggle stacked
    const toggleStackedBtn = screen.getByLabelText("Toggle stacked layout");
    expect(toggleStackedBtn.textContent).toContain("Stacked: Off");
    fireEvent.click(toggleStackedBtn);
    expect(onStackedChange).toHaveBeenCalledWith(true);

    // Click line button
    fireEvent.click(screen.getByLabelText("Line Chart"));
    expect(onChartTypeChange).toHaveBeenCalledWith("line");

    rerender(
      <BiChartVisualizer
        results={sampleResults}
        chartType="donut"
        stacked={true}
      />
    );
    expect(screen.getByLabelText("Donut chart series")).toBeTruthy();
  });

  it("exercises category, metric, and aggregation dropdown changes", () => {
    render(<BiChartVisualizer results={sampleResults} />);

    // Change category
    const catSelect = screen.getByLabelText("Select Category column");
    fireEvent.change(catSelect, { target: { value: "department" } });

    // Change metric
    const metricSelect = screen.getByLabelText("Select Metric column");
    fireEvent.change(metricSelect, { target: { value: "bonus" } });

    // Change aggregation to AVG, MIN, MAX, COUNT, NONE
    const aggSelect = screen.getByLabelText("Select Aggregation");
    fireEvent.change(aggSelect, { target: { value: "AVG" } });
    fireEvent.change(aggSelect, { target: { value: "MIN" } });
    fireEvent.change(aggSelect, { target: { value: "MAX" } });
    fireEvent.change(aggSelect, { target: { value: "COUNT" } });
    fireEvent.change(aggSelect, { target: { value: "NONE" } });

    expect(screen.getAllByRole("graphics-symbol").length).toBe(4);
  });

  it("handles interactive hover and focus tooltips on data symbols across all chart types", () => {
    // Bar
    const { rerender } = render(<BiChartVisualizer results={sampleResults} defaultChartType="bar" />);
    const bar = screen.getAllByRole("graphics-symbol")[0];
    fireEvent.mouseEnter(bar);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.mouseLeave(bar);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(bar);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.blur(bar);
    expect(screen.queryByRole("tooltip")).toBeNull();

    // Line
    rerender(<BiChartVisualizer results={sampleResults} chartType="line" />);
    const linePoint = screen.getAllByRole("graphics-symbol")[0];
    fireEvent.mouseEnter(linePoint);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.mouseLeave(linePoint);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(linePoint);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.blur(linePoint);
    expect(screen.queryByRole("tooltip")).toBeNull();

    // Area
    rerender(<BiChartVisualizer results={sampleResults} chartType="area" />);
    const areaPoint = screen.getAllByRole("graphics-symbol")[0];
    fireEvent.mouseEnter(areaPoint);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.mouseLeave(areaPoint);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(areaPoint);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.blur(areaPoint);
    expect(screen.queryByRole("tooltip")).toBeNull();

    // Scatter
    rerender(<BiChartVisualizer results={sampleResults} chartType="scatter" />);
    const scatterPoint = screen.getAllByRole("graphics-symbol")[0];
    fireEvent.mouseEnter(scatterPoint);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.mouseLeave(scatterPoint);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(scatterPoint);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.blur(scatterPoint);
    expect(screen.queryByRole("tooltip")).toBeNull();

    // Donut multi-slice
    rerender(<BiChartVisualizer results={sampleResults} chartType="donut" />);
    const donutSlice = screen.getAllByRole("graphics-symbol")[0];
    fireEvent.mouseEnter(donutSlice);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.mouseLeave(donutSlice);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(donutSlice);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.blur(donutSlice);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("handles single-slice pie/donut and zero pie total cleanly", () => {
    // Single slice
    const singleData: QueryResultData = {
      columns: ["category", "value"],
      rows: [{ category: "Single", value: 100 }],
      count: 1,
    };
    const { rerender } = render(<BiChartVisualizer results={singleData} chartType="pie" />);
    const singleSlice = screen.getByRole("graphics-symbol");
    expect(singleSlice).toBeTruthy();
    fireEvent.mouseEnter(singleSlice);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.mouseLeave(singleSlice);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(singleSlice);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.blur(singleSlice);
    expect(screen.queryByRole("tooltip")).toBeNull();

    // Zero pie total
    const zeroData: QueryResultData = {
      columns: ["category", "value"],
      rows: [
        { category: "A", value: 0 },
        { category: "B", value: 0 },
      ],
      count: 2,
    };
    rerender(<BiChartVisualizer results={zeroData} chartType="donut" />);
    expect(screen.getByText("Total is 0")).toBeTruthy();
  });

  it("handles KPI card negative metrics, AVG aggregation, and unstyled mode", () => {
    const negativeData: QueryResultData = {
      columns: ["dept", "profit"],
      rows: [
        { dept: "Loss-1", profit: -500 },
        { dept: "Loss-2", profit: -1500 },
      ],
      count: 2,
    };

    const { rerender } = render(
      <BiChartVisualizer
        results={negativeData}
        chartType="kpi"
        defaultAggregation="SUM"
      />
    );
    expect(screen.getByTestId("kpi-card")).toBeTruthy();
    expect(screen.getByText(/▼ Negative/)).toBeTruthy();
    expect(screen.getByText(/SUM of profit/)).toBeTruthy();

    // In unstyled mode
    rerender(
      <BiChartVisualizer
        results={negativeData}
        chartType="kpi"
        defaultAggregation="SUM"
        unstyled={true}
      />
    );
    expect(screen.getByTestId("kpi-card")).toBeTruthy();

    // AVG aggregation with default title
    fireEvent.change(screen.getByLabelText("Select Aggregation"), { target: { value: "AVG" } });
    expect(screen.getByText(/AVG of profit/)).toBeTruthy();
  });

  it("handles rows with zero valid numeric points gracefully", () => {
    const noNumericData: QueryResultData = {
      columns: ["item", "note"],
      rows: [
        { item: "A", note: "hello" },
        { item: "B", note: "world" },
      ],
      count: 2,
    };
    render(<BiChartVisualizer results={noNumericData} chartType="line" />);
    expect(screen.getByLabelText("Line chart series")).toBeTruthy();
  });

  it("parses strings, NaN, empty strings, and booleans in data safely", () => {
    const mixedData: QueryResultData = {
      columns: ["item", "flag", "amount"],
      rows: [
        { item: "Valid String Number", flag: true, amount: "123.45" },
        { item: "Empty String", flag: false, amount: "" },
        { item: "Invalid NaN", flag: null, amount: "not_a_number" },
        { item: "True Boolean", flag: true, amount: true as any },
        { item: "Raw NaN", flag: undefined, amount: NaN },
        { item: "Null Value", flag: false, amount: null },
      ],
      count: 6,
    };

    render(<BiChartVisualizer results={mixedData} chartType="bar" />);
    expect(screen.getByLabelText("Bar chart series")).toBeTruthy();
  });

  it("supports pluggable adapters (custom function, echarts, vega-lite)", () => {
    // Custom function adapter
    const customAdapter = vi.fn((ctx) => (
      <div data-testid="custom-canvas">Custom: {ctx.effectiveMetric}</div>
    ));

    const { rerender } = render(
      <BiChartVisualizer results={sampleResults} adapter={customAdapter} />
    );
    expect(screen.getByTestId("custom-canvas")).toBeTruthy();
    expect(customAdapter).toHaveBeenCalled();

    // ECharts adapter
    rerender(<BiChartVisualizer results={sampleResults} adapter="echarts" unstyled={true} />);
    expect(screen.getByTestId("echarts-container")).toBeTruthy();
    expect(screen.getByTestId("echarts-surface")).toBeTruthy();

    // Vega-Lite adapter
    rerender(<BiChartVisualizer results={sampleResults} adapter="vega-lite" unstyled={true} />);
    expect(screen.getByTestId("vega-lite-container")).toBeTruthy();
    expect(screen.getByTestId("vega-lite-surface")).toBeTruthy();
  });

  it("handles empty category/metric fallback producing zero points without crashing", () => {
    const emptyColsData: QueryResultData = {
      columns: [""],
      rows: [{ "": 10 }],
      count: 1,
    };
    render(<BiChartVisualizer results={emptyColsData} chartType="line" />);
    expect(screen.getByLabelText("Line chart series")).toBeTruthy();
  });

  it("renders bar chart with negative values and stacked layout", () => {
    const mixedBarData: QueryResultData = {
      columns: ["category", "profit"],
      rows: [
        { category: "Positive", profit: 100 },
        { category: "Negative", profit: -50 },
      ],
      count: 2,
    };
    render(<BiChartVisualizer results={mixedBarData} chartType="bar" stacked={true} />);
    const bars = screen.getAllByRole("graphics-symbol");
    expect(bars.length).toBe(2);
  });

  it("renders pie/donut chart with a dominant slice > 50%", () => {
    const dominantData: QueryResultData = {
      columns: ["category", "value"],
      rows: [
        { category: "Dominant", value: 80 },
        { category: "Minor", value: 20 },
      ],
      count: 2,
    };
    render(<BiChartVisualizer results={dominantData} chartType="donut" />);
    const slices = screen.getAllByRole("graphics-symbol");
    expect(slices.length).toBe(2);
  });

  it("renders in unstyled mode cleanly without crashing", () => {
    render(<BiChartVisualizer results={sampleResults} unstyled={true} />);
    expect(screen.getByLabelText("Visual Chart Preview")).toBeTruthy();
  });
});
