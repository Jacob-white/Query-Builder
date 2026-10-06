import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDashboardManager } from "../src/hooks/useDashboardManager";
import type { DashboardTile } from "../src/types";

describe("useDashboardManager Hook", () => {
  it("initializes with default state", () => {
    const { result } = renderHook(() => useDashboardManager());
    expect(result.current.dashboard.id).toBe("dashboard_1");
    expect(result.current.tiles).toHaveLength(0);
    expect(result.current.globalFilters).toHaveLength(0);
    expect(result.current.crossFilter).toBeNull();
  });

  it("adds, updates, duplicates, and removes tiles", () => {
    const { result } = renderHook(() => useDashboardManager());

    let tileId = "";
    act(() => {
      tileId = result.current.addTile({
        title: "Revenue KPI",
        type: "kpi",
        layout: { w: 1, h: 1 },
      });
    });

    expect(result.current.tiles).toHaveLength(1);
    expect(result.current.tiles[0].title).toBe("Revenue KPI");

    // Update
    act(() => {
      result.current.updateTile(tileId, { title: "Updated Revenue" });
    });
    expect(result.current.tiles[0].title).toBe("Updated Revenue");

    // Duplicate
    let clonedId = "";
    act(() => {
      clonedId = result.current.duplicateTile(tileId);
    });
    expect(result.current.tiles).toHaveLength(2);
    expect(result.current.tiles[1].title).toBe("Updated Revenue (Copy)");

    // Remove
    act(() => {
      result.current.removeTile(tileId);
    });
    expect(result.current.tiles).toHaveLength(1);
    expect(result.current.tiles[0].id).toBe(clonedId);
  });

  it("handles duplicateTile with invalid id gracefully", () => {
    const { result } = renderHook(() => useDashboardManager());
    let res = "";
    act(() => {
      res = result.current.duplicateTile("non_existent");
    });
    expect(res).toBe("");
  });

  it("moves and resizes tiles", () => {
    const { result } = renderHook(() => useDashboardManager());

    let t1 = "";
    let t2 = "";
    act(() => {
      t1 = result.current.addTile({ title: "Tile 1", type: "table", layout: { w: 2, h: 1 } });
      t2 = result.current.addTile({ title: "Tile 2", type: "chart", layout: { w: 2, h: 1 } });
    });

    // Move t2 up
    act(() => {
      result.current.moveTile(t2, "up");
    });
    expect(result.current.tiles[0].id).toBe(t2);
    expect(result.current.tiles[1].id).toBe(t1);

    // Boundary move
    act(() => {
      result.current.moveTile(t2, "up");
    });
    expect(result.current.tiles[0].id).toBe(t2);

    // Move invalid tile
    act(() => {
      result.current.moveTile("invalid", "down");
    });

    // Resize tile
    act(() => {
      result.current.resizeTile(t2, 4, 2);
    });
    expect(result.current.tiles[0].layout).toEqual({ w: 4, h: 2 });

    // Clamps resize
    act(() => {
      result.current.resizeTile(t2, 10);
    });
    expect(result.current.tiles[0].layout.w).toBe(4);
  });

  it("manages global parameter filters", () => {
    const { result } = renderHook(() => useDashboardManager());

    act(() => {
      result.current.setGlobalFilter({ field: "region", operator: "=", value: "North" });
    });
    expect(result.current.globalFilters).toHaveLength(1);

    // Update existing
    act(() => {
      result.current.setGlobalFilter({ field: "region", operator: "=", value: "South" });
    });
    expect(result.current.globalFilters).toHaveLength(1);
    expect(result.current.globalFilters[0].value).toBe("South");

    // Remove
    act(() => {
      result.current.removeGlobalFilter("region");
    });
    expect(result.current.globalFilters).toHaveLength(0);

    // Clear all
    act(() => {
      result.current.setGlobalFilter({ field: "f1", operator: "=", value: "1" });
      result.current.setGlobalFilter({ field: "f2", operator: "=", value: "2" });
      result.current.clearGlobalFilters();
    });
    expect(result.current.globalFilters).toHaveLength(0);
  });

  it("manages cross-filtering event bus and row filtering", () => {
    const sampleRows1 = [
      { id: 1, region: "North", dept: "Sales", amount: 100 },
      { id: 2, region: "South", dept: "Sales", amount: 200 },
      { id: 3, region: "North", dept: "Eng", amount: 300 },
    ];
    const sampleRows2 = [
      { dept: "Sales", headcount: 10 },
      { dept: "Eng", headcount: 25 },
    ];

    const { result } = renderHook(() =>
      useDashboardManager({
        initialState: {
          tiles: [
            {
              id: "t1",
              title: "Regional Sales",
              type: "chart",
              cachedRows: sampleRows1,
              layout: { w: 2, h: 1 },
            },
            {
              id: "t2",
              title: "Headcount",
              type: "table",
              cachedRows: sampleRows2,
              layout: { w: 2, h: 1 },
            },
          ],
        },
      }),
    );

    // Apply global filter
    act(() => {
      result.current.setGlobalFilter({ field: "region", operator: "=", value: "North" });
    });

    // t1 has region column, so it filters to 2 rows
    const rowsT1 = result.current.getFilteredRowsForTile("t1");
    expect(rowsT1).toHaveLength(2);

    // t2 does NOT have region column, so it passes through 2 rows
    const rowsT2 = result.current.getFilteredRowsForTile("t2");
    expect(rowsT2).toHaveLength(2);

    // Trigger cross-filter from t1 on dept = Sales
    act(() => {
      result.current.setCrossFilter("t1", "dept", "Sales");
    });
    expect(result.current.crossFilter).toEqual({ sourceTileId: "t1", field: "dept", value: "Sales" });

    // t1 is the SOURCE, so its rows are NOT filtered by its own cross-filter
    expect(result.current.getFilteredRowsForTile("t1")).toHaveLength(2);

    // t2 is a TARGET with dept column, so it is filtered down to 1 row
    expect(result.current.getFilteredRowsForTile("t2")).toHaveLength(1);
    expect(result.current.getFilteredRowsForTile("t2")[0].dept).toBe("Sales");

    // Clicking same cross-filter toggles it off
    act(() => {
      result.current.setCrossFilter("t1", "dept", "Sales");
    });
    expect(result.current.crossFilter).toBeNull();

    // Clear cross-filter manually
    act(() => {
      result.current.setCrossFilter("t1", "dept", "Eng");
      result.current.clearCrossFilter();
    });
    expect(result.current.crossFilter).toBeNull();

    // Query non-existent tile
    expect(result.current.getFilteredRowsForTile("unknown")).toEqual([]);
  });

  it("computes KPI and Pivot aggregations accurately", () => {
    const { result } = renderHook(() => useDashboardManager());
    const tile: DashboardTile = {
      id: "k1",
      title: "Quarterly Revenue",
      type: "kpi",
      layout: { w: 1, h: 1 },
      kpiConfig: { valueField: "rev", deltaPercentage: 8.5 },
      pivotConfig: {
        rowDimensions: ["product"],
        columnDimensions: ["quarter"],
        valueMetrics: [{ field: "rev", agg: "sum" }],
      },
    };

    const rows = [
      { product: "SaaS", quarter: "Q1", rev: 100 },
      { product: "SaaS", quarter: "Q2", rev: 150 },
      { product: "Hardware", quarter: "Q1", rev: 50 },
    ];

    const kpi = result.current.computeKpi(tile, rows);
    expect(kpi.value).toBe(300);
    expect(kpi.delta).toBe(8.5);

    const pivot = result.current.computePivot(tile, rows);
    expect(pivot.rowKeys).toEqual(["SaaS", "Hardware"]);
    expect(pivot.colKeys).toEqual(["Q1", "Q2"]);
    expect(pivot.data["SaaS"]["Q1"]).toBe(100);
    expect(pivot.data["SaaS"]["Q2"]).toBe(150);
    expect(pivot.data["Hardware"]["Q1"]).toBe(50);
  });
});
