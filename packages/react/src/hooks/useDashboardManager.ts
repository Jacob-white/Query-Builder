/**
 * Headless Hook for Interactive Multi-Tile Dashboard Workbench.
 * =============================================================
 * Manages tiles, responsive grid layouts, cascading global parameter filters,
 * reactive cross-filtering event bus, and KPI/Pivot aggregation compute.
 */

import { useState, useCallback, useEffect, useRef } from "react";
import type {
  AggregationMode,
  CrossFilterState,
  DashboardState,
  DashboardTile,
  DashboardTileLayout,
  GlobalFilter,
  QueryResultData,
} from "../types";

export interface UseDashboardManagerOptions {
  initialState?: Partial<DashboardState>;
  results?: QueryResultData | null;
  storageKey?: string;
}

function isNumericVal(val: unknown): boolean {
  if (val === null || val === undefined || typeof val === "boolean") return false;
  if (typeof val === "number") return !Number.isNaN(val);
  if (typeof val === "string") {
    const trimmed = val.trim();
    return trimmed !== "" && !Number.isNaN(Number(trimmed));
  }
  return false;
}

function shortColName(col: string): string {
  return col.slice(col.lastIndexOf(".") + 1);
}

function isIdColumnName(col: string): boolean {
  const base = shortColName(col).toLowerCase();
  return base === "id" || base.endsWith("_id");
}

const NUMERIC_COL_NAME_RE =
  /^(?:amount|total|price|cost|revenue|sales|quantity|qty|count|sum|avg|min|max|balance|score|rate|tax|discount|margin|profit|salary|bonus|units|views|streak)$/i;
const NUMERIC_COL_SUFFIX_RE =
  /(?:_amount|_total|_price|_cost|_revenue|_sales|_quantity|_qty|_count|_sum|_avg|_min|_max|_balance|_score|_rate|_tax|_discount|_margin|_profit|_salary|_bonus|_units|_views|_days)$/i;

function isLikelyNumericColName(col: string): boolean {
  if (isIdColumnName(col)) return true;
  const base = shortColName(col);
  return NUMERIC_COL_NAME_RE.test(base) || NUMERIC_COL_SUFFIX_RE.test(base);
}

export interface InferredDashboardColumns {
  columns: string[];
  categoryCol: string;
  secondaryCategoryCol: string;
  metricCol: string;
  hasNonIdMetric: boolean;
  defaultAggregation: AggregationMode;
}

export function inferDashboardColumns(
  rows: Record<string, unknown>[],
  columns?: string[],
): InferredDashboardColumns {
  const cols = columns?.length ? columns : rows[0] ? Object.keys(rows[0]) : [];
  const sample = rows.slice(0, 10);

  const numericCols =
    sample.length > 0
      ? cols.filter((c) => sample.some((r) => isNumericVal(r[c])))
      : cols.filter((c) => isLikelyNumericColName(c));
  const nonIdNumericCols = numericCols.filter((c) => !isIdColumnName(c));
  const nonNumericCols = cols.filter((c) => !numericCols.includes(c));

  const categoryCol = nonNumericCols[0] ?? cols[0] ?? "";
  const candidateMetrics = nonIdNumericCols.length > 0 ? nonIdNumericCols : numericCols;
  const metricCol =
    candidateMetrics.find((c) => c !== categoryCol) ??
    candidateMetrics[0] ??
    cols[1] ??
    categoryCol;
  const secondaryCategoryCol =
    cols.find((c) => c !== categoryCol && c !== metricCol) ??
    cols.find((c) => c !== categoryCol) ??
    categoryCol;

  const hasNonIdMetric = nonIdNumericCols.length > 0;
  const defaultAggregation: AggregationMode = hasNonIdMetric ? "SUM" : "COUNT";

  return {
    columns: cols,
    categoryCol,
    secondaryCategoryCol,
    metricCol,
    hasNonIdMetric,
    defaultAggregation,
  };
}

export function buildDashboardTilesFromResults(
  results: QueryResultData,
  titlePrefix?: string,
): DashboardTile[] {
  const rows = results.rows;
  const inferred = inferDashboardColumns(rows, results.columns);
  if (inferred.columns.length === 0 && rows.length === 0) {
    return [];
  }

  const metricLabel = shortColName(inferred.metricCol);
  const categoryLabel = shortColName(inferred.categoryCol);
  const prefix = titlePrefix ? `${titlePrefix} — ` : "";

  const kpiTile: DashboardTile = {
    id: "tile-query-kpi",
    title: inferred.hasNonIdMetric
      ? `Total ${metricLabel}`
      : "Total Queried Records",
    type: "kpi",
    columns: inferred.columns,
    kpiConfig: {
      title: inferred.hasNonIdMetric
        ? `Sum of ${metricLabel} (${rows.length} rows)`
        : `Queried Row Count`,
      valueField: inferred.hasNonIdMetric ? inferred.metricCol : "__count__",
      statusColor: "#a6e3a1",
    },
    layout: { x: 0, y: 0, w: 1, h: 1 },
    cachedRows: rows,
  };

  const chartTile: DashboardTile = {
    id: "tile-query-chart",
    title: inferred.hasNonIdMetric
      ? `${metricLabel} by ${categoryLabel}`
      : `Records by ${categoryLabel}`,
    type: "chart",
    chartType: "bar",
    columns: inferred.columns,
    categoryCol: inferred.categoryCol,
    metricCol: inferred.metricCol,
    defaultAggregation: inferred.defaultAggregation,
    layout: { x: 1, y: 0, w: 3, h: 1 },
    cachedRows: rows,
  };

  const tableTile: DashboardTile = {
    id: "tile-query-table",
    title: `${prefix}Queried Records (${rows.length})`,
    type: "table",
    columns: inferred.columns,
    layout: { x: 0, y: 1, w: 4, h: 1 },
    cachedRows: rows,
  };

  return [kpiTile, chartTile, tableTile];
}

function resolveRowFieldValue(row: Record<string, unknown>, field?: string): unknown {
  if (!field) return undefined;
  if (field in row) return row[field];
  const lowerField = field.toLowerCase();
  const keys = Object.keys(row);
  for (const key of keys) {
    if (key.toLowerCase() === lowerField) {
      return row[key];
    }
  }
  const fieldIsQualified = lowerField.includes(".");
  const shortTarget = shortColName(lowerField);
  for (const key of keys) {
    const lowerKey = key.toLowerCase();
    const keyIsQualified = lowerKey.includes(".");
    if ((!fieldIsQualified || !keyIsQualified) && shortColName(lowerKey) === shortTarget) {
      return row[key];
    }
  }
  return undefined;
}

export interface UseDashboardManagerReturn {
  dashboard: DashboardState;
  tiles: DashboardTile[];
  globalFilters: GlobalFilter[];
  crossFilter: CrossFilterState | null;
  addTile: (tile: Omit<DashboardTile, "id">) => string;
  updateTile: (id: string, updates: Partial<DashboardTile>) => void;
  removeTile: (id: string) => void;
  duplicateTile: (id: string) => string;
  moveTile: (id: string, direction: "up" | "down") => void;
  resizeTile: (id: string, w: number, h?: number) => void;
  setGlobalFilter: (filter: GlobalFilter) => void;
  removeGlobalFilter: (field: string) => void;
  clearGlobalFilters: () => void;
  setCrossFilter: (sourceTileId: string, field: string, value: unknown) => void;
  clearCrossFilter: () => void;
  getFilteredRowsForTile: (tileId: string) => Record<string, unknown>[];
  computeKpi: (tile: DashboardTile, rows: Record<string, unknown>[]) => {
    value: number | string;
    title: string;
    subtitle?: string;
    delta?: number;
    color?: string;
  };
  computePivot: (tile: DashboardTile, rows: Record<string, unknown>[]) => {
    rowKeys: string[];
    colKeys: string[];
    data: Record<string, Record<string, number>>;
  };
}

export function useDashboardManager(
  options: UseDashboardManagerOptions = {},
): UseDashboardManagerReturn {
  const storageKey = options.storageKey;
  const [dashboard, setDashboard] = useState<DashboardState>(() => {
    let persistedCustomTiles: DashboardTile[] = [];
    if (storageKey && typeof window !== "undefined" && window.localStorage) {
      try {
        const raw = window.localStorage.getItem(`qb_dashboard_tiles_${storageKey}`);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) {
            persistedCustomTiles = parsed;
          }
        }
      } catch {
        // Ignore storage read errors
      }
    }

    const baseTiles = options.initialState?.tiles
      ? [...options.initialState.tiles]
      : options.results
        ? buildDashboardTilesFromResults(options.results, options.initialState?.title)
        : [];
    const existingIds = new Set(baseTiles.map((t) => t.id));
    const mergedTiles = [
      ...baseTiles,
      ...persistedCustomTiles.filter((t) => !existingIds.has(t.id)),
    ];
    return {
      id: options.initialState?.id || "dashboard_1",
      title: options.initialState?.title || "Operational Analytics",
      tiles: mergedTiles,
      globalFilters: options.initialState?.globalFilters ? [...options.initialState.globalFilters] : [],
      crossFilter: options.initialState?.crossFilter || null,
    };
  });

  useEffect(() => {
    if (!storageKey || typeof window === "undefined" || !window.localStorage) return;
    try {
      const customToSave = dashboard.tiles.filter((t) => !t.id.startsWith("tile-query-"));
      window.localStorage.setItem(
        `qb_dashboard_tiles_${storageKey}`,
        JSON.stringify(customToSave),
      );
    } catch {
      // Ignore storage quota errors
    }
  }, [dashboard.tiles, storageKey]);

  const prevResultsRef = useRef<QueryResultData | null | undefined>(options.results);
  const initialTitle = options.initialState?.title;

  useEffect(() => {
    if (options.results === prevResultsRef.current) {
      if (initialTitle) {
        setDashboard((prev) =>
          prev.title === initialTitle
            ? prev
            : { ...prev, title: initialTitle },
        );
      }
      return;
    }
    const hadPreviousResults = Boolean(prevResultsRef.current);
    prevResultsRef.current = options.results;

    if (!options.results) {
      if (hadPreviousResults) {
        setDashboard((prev) => ({
          ...prev,
          title: initialTitle || prev.title,
          tiles: prev.tiles
            .filter((t) => !t.id.startsWith("tile-query-"))
            .map((t) =>
              t.id.startsWith("pinned_") ? t : { ...t, cachedRows: [] },
            ),
          crossFilter: null,
        }));
      }
      return;
    }

    const nextResults = options.results;
    const nextRows = nextResults.rows;
    const inferred = inferDashboardColumns(nextRows, nextResults.columns);

    setDashboard((prev) => {
      const nextAutoTiles = buildDashboardTilesFromResults(nextResults).map(
        (autoTile): DashboardTile => {
          const prevTile = prev.tiles.find((p) => p.id === autoTile.id);
          if (!prevTile) return autoTile;
          const keepCat = inferred.columns.includes(prevTile.categoryCol as string)
            ? prevTile.categoryCol
            : autoTile.categoryCol;
          const keepMet = inferred.columns.includes(prevTile.metricCol as string)
            ? prevTile.metricCol
            : autoTile.metricCol;
          return {
            ...autoTile,
            type: prevTile.type,
            chartType: prevTile.chartType ?? autoTile.chartType,
            categoryCol: keepCat,
            metricCol: keepMet,
            defaultAggregation:
              prevTile.defaultAggregation ?? autoTile.defaultAggregation,
            kpiConfig: autoTile.kpiConfig
              ? {
                  ...autoTile.kpiConfig,
                  valueField: keepMet || autoTile.kpiConfig.valueField,
                }
              : prevTile.kpiConfig,
          };
        },
      );
      const customTiles = prev.tiles
        .filter((t) => !t.id.startsWith("tile-query-"))
        .map((t): DashboardTile => {
          if (t.id.startsWith("pinned_") && t.cachedRows?.length) {
            return t;
          }
          const keepCat = inferred.columns.includes(t.categoryCol as string)
            ? t.categoryCol!
            : inferred.categoryCol;
          const keepMet = inferred.columns.includes(t.metricCol as string)
            ? t.metricCol!
            : inferred.metricCol;
          return {
            ...t,
            cachedRows: nextRows,
            columns: inferred.columns,
            categoryCol: keepCat,
            metricCol: keepMet,
            defaultAggregation: t.defaultAggregation ?? inferred.defaultAggregation,
            kpiConfig: t.kpiConfig
              ? {
                  ...t.kpiConfig,
                  valueField: inferred.hasNonIdMetric ? keepMet : "__count__",
                }
              : undefined,
            pivotConfig: t.pivotConfig
              ? {
                  rowDimensions: [keepCat],
                  columnDimensions: [inferred.secondaryCategoryCol],
                  valueMetrics: [
                    {
                      field: keepMet,
                      agg: inferred.hasNonIdMetric ? "sum" : "count",
                    },
                  ],
                }
              : undefined,
          };
        });
      const includeAutoTiles =
        prev.tiles.length === 0 || prev.tiles.some((t) => t.id.startsWith("tile-query-"));
      return {
        ...prev,
        title: initialTitle || prev.title,
        tiles: includeAutoTiles ? [...nextAutoTiles, ...customTiles] : customTiles,
        crossFilter: null,
      };
    });
  }, [options.results, initialTitle]);

  const addTile = useCallback((tileData: Omit<DashboardTile, "id"> & { id?: string }): string => {
    const id = tileData.id || `tile_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const newTile: DashboardTile = {
      ...tileData,
      id,
      layout: tileData.layout || { w: 2, h: 1 },
    };
    setDashboard((prev) => ({
      ...prev,
      tiles: [...prev.tiles, newTile],
    }));
    return id;
  }, []);

  const updateTile = useCallback((id: string, updates: Partial<DashboardTile>) => {
    setDashboard((prev) => ({
      ...prev,
      tiles: prev.tiles.map((t) => (t.id === id ? { ...t, ...updates } : t)),
    }));
  }, []);

  const removeTile = useCallback((id: string) => {
    setDashboard((prev) => ({
      ...prev,
      tiles: prev.tiles.filter((t) => t.id !== id),
      crossFilter: prev.crossFilter?.sourceTileId === id ? null : prev.crossFilter,
    }));
  }, []);

  const duplicateTile = useCallback(
    (id: string): string => {
      const existing = dashboard.tiles.find((t) => t.id === id);
      if (!existing) return "";

      const newId = `tile_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
      const cloned: DashboardTile = {
        ...existing,
        id: newId,
        title: `${existing.title} (Copy)`,
      };

      setDashboard((prev) => ({
        ...prev,
        tiles: [...prev.tiles, cloned],
      }));
      return newId;
    },
    [dashboard.tiles],
  );

  const moveTile = useCallback((id: string, direction: "up" | "down") => {
    setDashboard((prev) => {
      const idx = prev.tiles.findIndex((t) => t.id === id);
      if (idx === -1) return prev;
      const targetIdx = direction === "up" ? idx - 1 : idx + 1;
      if (targetIdx < 0 || targetIdx >= prev.tiles.length) return prev;

      const nextTiles = [...prev.tiles];
      const [moved] = nextTiles.splice(idx, 1);
      nextTiles.splice(targetIdx, 0, moved);
      return { ...prev, tiles: nextTiles };
    });
  }, []);

  const resizeTile = useCallback((id: string, w: number, h?: number) => {
    setDashboard((prev) => ({
      ...prev,
      tiles: prev.tiles.map((t) => {
        if (t.id !== id) return t;
        const newLayout: DashboardTileLayout = {
          ...t.layout,
          w: Math.max(1, Math.min(4, w)),
          h: h !== undefined ? Math.max(1, Math.min(3, h)) : t.layout.h,
        };
        return { ...t, layout: newLayout };
      }),
    }));
  }, []);

  const setGlobalFilter = useCallback((filter: GlobalFilter) => {
    setDashboard((prev) => {
      const existingIdx = prev.globalFilters.findIndex((f) => f.field === filter.field);
      const nextFilters = [...prev.globalFilters];
      if (existingIdx !== -1) {
        nextFilters[existingIdx] = filter;
      } else {
        nextFilters.push(filter);
      }
      return { ...prev, globalFilters: nextFilters };
    });
  }, []);

  const removeGlobalFilter = useCallback((field: string) => {
    setDashboard((prev) => ({
      ...prev,
      globalFilters: prev.globalFilters.filter((f) => f.field !== field),
    }));
  }, []);

  const clearGlobalFilters = useCallback(() => {
    setDashboard((prev) => ({
      ...prev,
      globalFilters: [],
    }));
  }, []);

  const setCrossFilter = useCallback((sourceTileId: string, field: string, value: unknown) => {
    setDashboard((prev) => {
      // Toggle off if clicking the same value again
      if (
        prev.crossFilter &&
        prev.crossFilter.sourceTileId === sourceTileId &&
        prev.crossFilter.field === field &&
        prev.crossFilter.value === value
      ) {
        return { ...prev, crossFilter: null };
      }
      return {
        ...prev,
        crossFilter: { sourceTileId, field, value },
      };
    });
  }, []);

  const clearCrossFilter = useCallback(() => {
    setDashboard((prev) => ({
      ...prev,
      crossFilter: null,
    }));
  }, []);

  const getFilteredRowsForTile = useCallback(
    (tileId: string): Record<string, unknown>[] => {
      const tile = dashboard.tiles.find((t) => t.id === tileId);
      if (!tile || !tile.cachedRows) return [];

      let rows = [...tile.cachedRows];

      // 1. Apply global parameter filters if row has field (supports exact or table-qualified column match)
      for (const gf of dashboard.globalFilters) {
        rows = rows.filter((r) => {
          const val = resolveRowFieldValue(r, gf.field);
          if (val === undefined) return true; // Pass through if tile table doesn't have this column
          return String(val).toLowerCase() === String(gf.value).toLowerCase();
        });
      }

      // 2. Apply cross filter (unless this tile is the source of the cross filter)
      if (dashboard.crossFilter && dashboard.crossFilter.sourceTileId !== tileId) {
        const { field, value } = dashboard.crossFilter;
        rows = rows.filter((r) => {
          const val = resolveRowFieldValue(r, field);
          if (val === undefined) return true;
          return String(val).toLowerCase() === String(value).toLowerCase();
        });
      }

      return rows;
    },
    [dashboard.tiles, dashboard.globalFilters, dashboard.crossFilter],
  );

  const computeKpi = useCallback(
    (tile: DashboardTile, rows: Record<string, unknown>[]) => {
      const cfg = tile.kpiConfig || {};
      const valField =
        tile.metricCol || cfg.valueField || (rows[0] ? Object.keys(rows[0])[0] : "");
      const agg = (tile.defaultAggregation || "SUM").toUpperCase();

      let total = 0;
      if (valField === "__count__" || agg === "COUNT") {
        total = rows.length;
      } else {
        const nums: number[] = [];
        for (const r of rows) {
          const raw = resolveRowFieldValue(r, valField);
          const num = Number(raw);
          if (!Number.isNaN(num)) nums.push(num);
        }
        if (nums.length === 0) {
          total = 0;
        } else if (agg === "AVG") {
          total = nums.reduce((a, b) => a + b, 0) / nums.length;
        } else if (agg === "MIN") {
          total = Math.min(...nums);
        } else if (agg === "MAX") {
          total = Math.max(...nums);
        } else {
          total = nums.reduce((a, b) => a + b, 0);
        }
      }

      return {
        value: Number.isInteger(total) ? total : Number(total.toFixed(2)),
        title: cfg.title || tile.title,
        subtitle: cfg.subtitle,
        delta: cfg.deltaPercentage,
        color: cfg.statusColor || "#89b4fa",
      };
    },
    [],
  );

  const computePivot = useCallback(
    (tile: DashboardTile, rows: Record<string, unknown>[]) => {
      const cfg = tile.pivotConfig || {
        rowDimensions: [],
        columnDimensions: [],
        valueMetrics: [],
      };

      const rowField =
        tile.categoryCol ||
        cfg.rowDimensions[0] ||
        (rows[0] ? Object.keys(rows[0])[0] : "row");
      const colField =
        cfg.columnDimensions[0] || (rows[0] ? Object.keys(rows[0])[1] || Object.keys(rows[0])[0] : "col");
      const metricField =
        tile.metricCol ||
        cfg.valueMetrics[0]?.field ||
        (rows[0] ? Object.keys(rows[0])[2] || Object.keys(rows[0])[1] || Object.keys(rows[0])[0] : "val");
      const metricAgg = (
        tile.defaultAggregation ||
        cfg.valueMetrics[0]?.agg ||
        "sum"
      ).toLowerCase();

      const rowKeysSet = new Set<string>();
      const colKeysSet = new Set<string>();
      const data: Record<string, Record<string, number>> = {};
      const counts: Record<string, Record<string, number>> = {};

      for (const r of rows) {
        const rk = String(resolveRowFieldValue(r, rowField) ?? "N/A");
        const ck = String(resolveRowFieldValue(r, colField) ?? "N/A");
        const val =
          metricAgg === "count" ? 1 : Number(resolveRowFieldValue(r, metricField)) || 0;

        rowKeysSet.add(rk);
        colKeysSet.add(ck);

        if (!data[rk]) data[rk] = {};
        if (!counts[rk]) counts[rk] = {};
        counts[rk][ck] = (counts[rk][ck] || 0) + 1;

        if (metricAgg === "min") {
          data[rk][ck] =
            data[rk][ck] === undefined ? val : Math.min(data[rk][ck], val);
        } else if (metricAgg === "max") {
          data[rk][ck] =
            data[rk][ck] === undefined ? val : Math.max(data[rk][ck], val);
        } else {
          data[rk][ck] = (data[rk][ck] || 0) + val;
        }
      }

      if (metricAgg === "avg") {
        for (const rk of Object.keys(data)) {
          for (const ck of Object.keys(data[rk])) {
            const cnt = counts[rk]?.[ck] || 1;
            data[rk][ck] = Number((data[rk][ck] / cnt).toFixed(2));
          }
        }
      }

      return {
        rowKeys: Array.from(rowKeysSet),
        colKeys: Array.from(colKeysSet),
        data,
      };
    },
    [],
  );

  return {
    dashboard,
    tiles: dashboard.tiles,
    globalFilters: dashboard.globalFilters,
    crossFilter: dashboard.crossFilter,
    addTile,
    updateTile,
    removeTile,
    duplicateTile,
    moveTile,
    resizeTile,
    setGlobalFilter,
    removeGlobalFilter,
    clearGlobalFilters,
    setCrossFilter,
    clearCrossFilter,
    getFilteredRowsForTile,
    computeKpi,
    computePivot,
  };
}
