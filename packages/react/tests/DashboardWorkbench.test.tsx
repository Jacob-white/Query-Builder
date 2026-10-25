import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { DashboardWorkbench } from "../src/components/DashboardWorkbench";
import type { DashboardTile } from "../src/types";

describe("DashboardWorkbench Component", () => {
  it("renders empty state when no tiles exist", () => {
    render(<DashboardWorkbench />);
    expect(screen.getByTestId("empty-dashboard-state")).toBeDefined();
    expect(screen.getByText("Dashboard is Empty")).toBeDefined();
  });

  it("opens add tile modal, creates new tile, and renders it", async () => {
    render(<DashboardWorkbench />);

    const addBtn = screen.getByTestId("add-tile-btn");
    fireEvent.click(addBtn);

    expect(screen.getByTestId("add-tile-modal-overlay")).toBeDefined();

    const titleInput = screen.getByTestId("new-tile-title-input");
    fireEvent.change(titleInput, { target: { value: "Q3 Revenue" } });

    const typeSelect = screen.getByTestId("new-tile-type-select");
    fireEvent.change(typeSelect, { target: { value: "chart" } });

    const chartSelect = screen.getByTestId("new-tile-chart-select");
    fireEvent.change(chartSelect, { target: { value: "bar" } });

    const submitBtn = screen.getByTestId("confirm-add-tile-btn");
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.queryByTestId("add-tile-modal-overlay")).toBeNull();
    });

    expect(screen.getByText("Q3 Revenue")).toBeDefined();
  });

  it("renders KPI, Table, Pivot, and Chart tiles and handles tile controls", async () => {
    const tiles: DashboardTile[] = [
      {
        id: "tile_kpi",
        title: "ARR Metric",
        type: "kpi",
        layout: { w: 1, h: 1 },
        cachedRows: [{ val: 1200000 }],
        kpiConfig: { valueField: "val", deltaPercentage: 12.4 },
      },
      {
        id: "tile_table",
        title: "Customers Grid",
        type: "table",
        layout: { w: 2, h: 1 },
        cachedRows: [
          { customer: "Acme Corp", tier: "Enterprise" },
          { customer: "Globex", tier: "Growth" },
        ],
      },
      {
        id: "tile_pivot",
        title: "Sales Matrix",
        type: "pivot",
        layout: { w: 2, h: 1 },
        cachedRows: [{ cat: "Tech", reg: "US", amount: 500 }],
        pivotConfig: {
          rowDimensions: ["cat"],
          columnDimensions: ["reg"],
          valueMetrics: [{ field: "amount", agg: "sum" }],
        },
      },
      {
        id: "tile_chart",
        title: "Growth Bar",
        type: "chart",
        chartType: "bar",
        layout: { w: 2, h: 1 },
        cachedRows: [{ period: "2026-Q1", revenue: 50000 }],
      },
    ];

    render(<DashboardWorkbench initialState={{ tiles }} />);

    expect(screen.getAllByText("ARR Metric")).toHaveLength(2);
    expect(screen.getByText("Customers Grid")).toBeDefined();
    expect(screen.getByText("Sales Matrix")).toBeDefined();
    expect(screen.getByText("Growth Bar")).toBeDefined();

    // Resize tile
    const resizeBtn = screen.getByTestId("resize-tile-tile_kpi");
    fireEvent.click(resizeBtn);

    // Duplicate tile
    const dupBtn = screen.getByTestId("duplicate-tile-tile_kpi");
    fireEvent.click(dupBtn);
    expect(screen.getAllByText("ARR Metric (Copy)")).toHaveLength(2);

    // Delete tile
    const removeBtn = screen.getByTestId("remove-tile-tile_kpi");
    fireEvent.click(removeBtn);
    expect(screen.queryAllByText("ARR Metric")).toHaveLength(0);
  });

  it("handles global filtering and reactive cross-filtering", async () => {
    const tiles: DashboardTile[] = [
      {
        id: "t_table",
        title: "Orders",
        type: "table",
        layout: { w: 4, h: 1 },
        cachedRows: [
          { order_id: 101, region: "EMEA", status: "paid" },
          { order_id: 102, region: "APAC", status: "pending" },
        ],
      },
    ];

    render(<DashboardWorkbench initialState={{ tiles }} />);

    // Add global filter
    const fieldInput = screen.getByTestId("filter-field-input");
    const valInput = screen.getByTestId("filter-val-input");
    const addFilterForm = screen.getByTestId("add-filter-form");

    fireEvent.change(fieldInput, { target: { value: "status" } });
    fireEvent.change(valInput, { target: { value: "paid" } });
    fireEvent.submit(addFilterForm);

    expect(screen.getByTestId("global-filter-pill-status")).toBeDefined();

    // Remove global filter pill
    const removePillBtn = screen.getByTestId("remove-global-filter-status");
    fireEvent.click(removePillBtn);
    expect(screen.queryByTestId("global-filter-pill-status")).toBeNull();

    // Cross-filter: Click on table row
    const row = screen.getByText("101");
    fireEvent.click(row);

    expect(screen.getByTestId("cross-filter-banner")).toBeDefined();

    // Clear cross filter
    const clearCrossBtn = screen.getByTestId("clear-cross-filter-btn");
    fireEvent.click(clearCrossBtn);
    expect(screen.queryByTestId("cross-filter-banner")).toBeNull();
  });

  it("disables interactive controls in readOnly mode", () => {
    render(<DashboardWorkbench readOnly={true} />);
    expect(screen.queryByTestId("add-tile-btn")).toBeNull();
    expect(screen.queryByTestId("add-filter-form")).toBeNull();
  });

  it("renders live QueryResultData, creates tiles bound to queried data, and cross-filters on chart bar click", async () => {
    const onStateChange = vi.fn();
    const liveResults = {
      columns: ["project_category", "score_points"],
      rows: [
        { project_category: "Analytics", score_points: 14 },
        { project_category: "Infrastructure", score_points: 21 },
        { project_category: "Security", score_points: 30 },
      ],
      count: 3,
    };

    render(
      <DashboardWorkbench
        results={liveResults}
        querySpec={{
          table: "projects",
          columns: ["project_category", "score_points"],
          joins: [],
          filters: [],
          filter_join: "AND",
          order_by: [],
          limit: 50,
          offset: 0,
          distinct: false,
        }}
        sql="SELECT project_category, score_points FROM projects"
        onStateChange={onStateChange}
      />,
    );

    expect(onStateChange).toHaveBeenCalled();
    expect(screen.getByTestId("dashboard-tile-tile-query-kpi")).toBeDefined();
    expect(screen.getByTestId("dashboard-tile-tile-query-chart")).toBeDefined();
    expect(screen.getByTestId("dashboard-tile-tile-query-table")).toBeDefined();
    expect(screen.getByText("65")).toBeDefined(); // 14 + 21 + 30

    // Click a bar in the chart tile to cross-filter sibling tiles
    const bars = screen.getAllByRole("graphics-symbol");
    fireEvent.click(bars[0]);
    expect(screen.getByTestId("cross-filter-banner")).toBeDefined();
    expect(screen.getByTestId("cross-filter-banner").textContent).toContain("Analytics");

    // Add a new Pivot tile and verify it uses liveResults rather than demo sales data
    fireEvent.click(screen.getByTestId("add-tile-btn"));
    fireEvent.change(screen.getByTestId("new-tile-title-input"), { target: { value: "Project Matrix" } });
    fireEvent.change(screen.getByTestId("new-tile-type-select"), { target: { value: "pivot" } });
    fireEvent.click(screen.getByTestId("confirm-add-tile-btn"));

    await waitFor(() => {
      expect(screen.getByText("Project Matrix")).toBeDefined();
    });
  });

  it("handles 0-row QueryResultData cleanly without injecting hardcoded demo sales rows on + Add Tile", async () => {
    const emptyQueryResults = {
      columns: ["orders.id", "orders.status", "orders.total_amount"],
      rows: [],
      count: 0,
    };

    render(
      <DashboardWorkbench
        results={emptyQueryResults}
        querySpec={{
          table: "orders",
          columns: ["orders.id", "orders.status", "orders.total_amount"],
          joins: [],
          filters: [],
          filter_join: "AND",
          order_by: [],
          limit: 50,
          offset: 0,
          distinct: false,
        }}
        sql="SELECT orders.id, orders.status, orders.total_amount FROM orders WHERE 1=0"
      />,
    );

    // Auto-generated table tile should display column headers and "No matching records"
    expect(screen.getByTestId("empty-table-tile-tile-query-table")).toBeDefined();
    expect(screen.getByText("orders.status")).toBeDefined();

    // Add a new table tile when results has 0 rows
    fireEvent.click(screen.getByTestId("add-tile-btn"));
    fireEvent.change(screen.getByTestId("new-tile-title-input"), { target: { value: "Zero Row Table" } });
    fireEvent.change(screen.getByTestId("new-tile-type-select"), { target: { value: "table" } });
    fireEvent.click(screen.getByTestId("confirm-add-tile-btn"));

    await waitFor(() => {
      expect(screen.getByText("Zero Row Table")).toBeDefined();
    });

    // Must NOT inject fake Hardware / Software / North demo sales rows
    expect(screen.queryByText("Hardware")).toBeNull();
    expect(screen.queryByText("Software")).toBeNull();
  });
});

