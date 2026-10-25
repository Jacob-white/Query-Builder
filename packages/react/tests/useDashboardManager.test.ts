import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  useDashboardManager,
  inferDashboardColumns,
  buildDashboardTilesFromResults,
} from "../src/hooks/useDashboardManager";
import type { DashboardTile, QueryResultData } from "../src/types";

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

  it("infers dashboard columns and builds tiles from live QueryResultData (numeric and non-numeric)", () => {
    // 1. Empty results
    expect(buildDashboardTilesFromResults({ columns: [], rows: [], count: 0 })).toEqual([]);

    // 2. Results with ID + category + numeric metric
    const ordersResult: QueryResultData = {
      columns: ["orders.id", "orders.status", "orders.total_amount"],
      rows: [
        { "orders.id": 1, "orders.status": "COMPLETED", "orders.total_amount": "1428.99" },
        { "orders.id": 2, "orders.status": "PENDING", "orders.total_amount": 250.5 },
      ],
      count: 2,
    };
    const inferredOrders = inferDashboardColumns(ordersResult.rows, ordersResult.columns);
    expect(inferredOrders.categoryCol).toBe("orders.status");
    expect(inferredOrders.metricCol).toBe("orders.total_amount");
    expect(inferredOrders.hasNonIdMetric).toBe(true);
    expect(inferredOrders.defaultAggregation).toBe("SUM");

    const orderTiles = buildDashboardTilesFromResults(ordersResult, "Orders");
    expect(orderTiles).toHaveLength(3);
    expect(orderTiles[0].title).toBe("Total total_amount");
    expect(orderTiles[1].title).toBe("total_amount by status");

    // 3. Results with only ID and string columns (no non-ID numeric metric -> COUNT mode)
    const usersResult: QueryResultData = {
      columns: ["id", "name", "role", "active"],
      rows: [
        { id: 1, name: "Alice", role: "ADMIN", active: true },
        { id: 2, name: "Bob", role: "CUSTOMER", active: false },
      ],
      count: 2,
    };
    const inferredUsers = inferDashboardColumns(usersResult.rows);
    expect(inferredUsers.categoryCol).toBe("name");
    expect(inferredUsers.secondaryCategoryCol).toBe("role");
    expect(inferredUsers.hasNonIdMetric).toBe(false);
    expect(inferredUsers.defaultAggregation).toBe("COUNT");

    const userTiles = buildDashboardTilesFromResults(usersResult);
    expect(userTiles[0].title).toBe("Total Queried Records");
    expect(userTiles[0].kpiConfig?.valueField).toBe("__count__");
    expect(userTiles[1].defaultAggregation).toBe("COUNT");
  });

  it("synchronizes dashboard tiles and custom tiles when live results update and supports qualified filters", () => {
    const initialResults: QueryResultData = {
      columns: ["orders.id", "orders.status", "orders.total_amount"],
      rows: [
        { "orders.id": 1, "orders.status": "COMPLETED", "orders.total_amount": 100 },
        { "orders.id": 2, "orders.status": "PENDING", "orders.total_amount": 50 },
      ],
      count: 2,
    };

    const { result, rerender } = renderHook(
      ({ res, title }: { res: QueryResultData | null; title?: string }) =>
        useDashboardManager({ results: res, initialState: { title } }),
      { initialProps: { res: initialResults, title: "Live Orders" } },
    );

    expect(result.current.tiles).toHaveLength(3);
    expect(result.current.dashboard.title).toBe("Live Orders");

    // Add a custom KPI and Pivot tile
    act(() => {
      result.current.addTile({
        title: "Custom KPI",
        type: "kpi",
        layout: { w: 1, h: 1 },
        cachedRows: initialResults.rows,
        kpiConfig: { valueField: "orders.total_amount" },
        pivotConfig: {
          rowDimensions: ["orders.status"],
          columnDimensions: ["orders.id"],
          valueMetrics: [{ field: "orders.total_amount", agg: "sum" }],
        },
      });
    });
    expect(result.current.tiles).toHaveLength(4);

    // Filter using unqualified column name "status" against "orders.status"
    act(() => {
      result.current.setGlobalFilter({ field: "status", operator: "=", value: "COMPLETED" });
    });
    expect(result.current.getFilteredRowsForTile("tile-query-table")).toHaveLength(1);

    // Cross-filter using unqualified column name
    act(() => {
      result.current.clearGlobalFilters();
      result.current.setCrossFilter("tile-query-chart", "status", "PENDING");
    });
    expect(result.current.getFilteredRowsForTile("tile-query-table")).toHaveLength(1);

    // Update results to a new table (e.g. users without numeric metrics)
    const nextResults: QueryResultData = {
      columns: ["id", "name", "role"],
      rows: [
        { id: 10, name: "Alice", role: "ADMIN" },
        { id: 20, name: "Bob", role: "USER" },
        { id: 30, name: "Carol", role: "USER" },
      ],
      count: 3,
    };
    rerender({ res: nextResults, title: "Live Users" });

    expect(result.current.dashboard.title).toBe("Live Users");
    expect(result.current.tiles).toHaveLength(4);
    expect(result.current.tiles[0].kpiConfig?.valueField).toBe("__count__");

    // Verify __count__ KPI and count Pivot computation
    const kpiVal = result.current.computeKpi(result.current.tiles[0], nextResults.rows);
    expect(kpiVal.value).toBe(3);

    const customTile = result.current.tiles[3];
    const pivotVal = result.current.computePivot(customTile, nextResults.rows);
    expect(pivotVal.data["Alice"]["ADMIN"]).toBe(1);
    expect(pivotVal.data["Bob"]["USER"]).toBe(1);

    // Also test when starting with empty tiles and results arrive later, or when non-auto tiles receive updated rows
    const { result: emptyInit, rerender: rerenderEmpty } = renderHook(
      ({ res }: { res: QueryResultData | null }) => useDashboardManager({ results: res }),
      { initialProps: { res: null as QueryResultData | null } },
    );
    expect(emptyInit.current.tiles).toHaveLength(0);
    rerenderEmpty({ res: nextResults });
    expect(emptyInit.current.tiles).toHaveLength(3);

    const { result: manualInit, rerender: rerenderManual } = renderHook(
      ({ res }: { res: QueryResultData | null }) =>
        useDashboardManager({
          initialState: {
            tiles: [{ id: "manual_1", title: "Manual", type: "table", layout: { w: 2, h: 1 }, cachedRows: [] }],
          },
          results: res,
        }),
      { initialProps: { res: null as QueryResultData | null } },
    );
    rerenderManual({ res: nextResults });
    expect(manualInit.current.tiles[0].cachedRows).toHaveLength(3);
  });

  it("infers numeric and categorical columns when rows are empty (0 rows) and preserves column metadata on tiles", () => {
    const zeroRowResults: QueryResultData = {
      columns: ["orders.id", "orders.status", "orders.total_amount"],
      rows: [],
      count: 0,
    };

    const inferred = inferDashboardColumns(zeroRowResults.rows, zeroRowResults.columns);
    expect(inferred.categoryCol).toBe("orders.status");
    expect(inferred.metricCol).toBe("orders.total_amount");
    expect(inferred.hasNonIdMetric).toBe(true);
    expect(inferred.defaultAggregation).toBe("SUM");

    const tiles = buildDashboardTilesFromResults(zeroRowResults, "Empty Orders");
    expect(tiles).toHaveLength(3);
    expect(tiles[0].columns).toEqual(["orders.id", "orders.status", "orders.total_amount"]);
    expect(tiles[1].categoryCol).toBe("orders.status");
    expect(tiles[1].metricCol).toBe("orders.total_amount");
  });

  it("disambiguates qualified column names sharing short names and clears tiles when results reset to null", () => {
    const joinedResults: QueryResultData = {
      columns: ["orders.id", "users.id", "orders.status"],
      rows: [
        { "orders.id": 1, "users.id": 42, "orders.status": "COMPLETED" },
        { "orders.id": 2, "users.id": 99, "orders.status": "PENDING" },
      ],
      count: 2,
    };

    const { result, rerender } = renderHook(
      ({ res, title }: { res: QueryResultData | null; title?: string }) =>
        useDashboardManager({ results: res, initialState: { title } }),
      { initialProps: { res: joinedResults as QueryResultData | null, title: "Joined Orders" } },
    );

    // Add a custom KPI referencing case-insensitive qualified "USERS.ID"
    act(() => {
      result.current.addTile({
        title: "User ID Sum",
        type: "kpi",
        layout: { w: 1, h: 1 },
        cachedRows: joinedResults.rows,
        kpiConfig: { valueField: "USERS.ID" },
      });
    });

    const customKpiTile = result.current.tiles.find((t) => t.title === "User ID Sum")!;
    // Should sum users.id (42 + 99 = 141), NOT orders.id (1 + 2 = 3)
    expect(result.current.computeKpi(customKpiTile, joinedResults.rows).value).toBe(141);

    // A qualified filter for a different table ("products.status") should NOT match "orders.status"
    act(() => {
      result.current.setGlobalFilter({ field: "products.status", operator: "=", value: "ARCHIVED" });
    });
    expect(result.current.getFilteredRowsForTile("tile-query-table")).toHaveLength(2);

    // Reset results to null (e.g. database switch or cleared query)
    rerender({ res: null, title: "Switched DB" });
    expect(result.current.dashboard.title).toBe("Switched DB");
    // Auto-generated tile-query-* tiles should be removed and custom tile cachedRows cleared
    expect(result.current.tiles).toHaveLength(1);
    expect(result.current.tiles[0].title).toBe("User ID Sum");
    expect(result.current.tiles[0].cachedRows).toEqual([]);
  });
});

