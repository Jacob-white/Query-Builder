/**
 * Headless Hook for Interactive Multi-Tile Dashboard Workbench.
 * =============================================================
 * Manages tiles, responsive grid layouts, cascading global parameter filters,
 * reactive cross-filtering event bus, and KPI/Pivot aggregation compute.
 */

import { useState, useCallback, useMemo } from "react";
import type {
  CrossFilterState,
  DashboardState,
  DashboardTile,
  DashboardTileLayout,
  GlobalFilter,
} from "../types";

export interface UseDashboardManagerOptions {
  initialState?: Partial<DashboardState>;
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
  const [dashboard, setDashboard] = useState<DashboardState>(() => ({
    id: options.initialState?.id || "dashboard_1",
    title: options.initialState?.title || "Operational Analytics",
    tiles: options.initialState?.tiles ? [...options.initialState.tiles] : [],
    globalFilters: options.initialState?.globalFilters ? [...options.initialState.globalFilters] : [],
    crossFilter: options.initialState?.crossFilter || null,
  }));

  const addTile = useCallback((tileData: Omit<DashboardTile, "id">): string => {
    const id = `tile_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const newTile: DashboardTile = {
      id,
      ...tileData,
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

      // 1. Apply global parameter filters if row has field
      for (const gf of dashboard.globalFilters) {
        rows = rows.filter((r) => {
          if (r[gf.field] === undefined) return true; // Pass through if tile table doesn't have this column
          return String(r[gf.field]).toLowerCase() === String(gf.value).toLowerCase();
        });
      }

      // 2. Apply cross filter (unless this tile is the source of the cross filter)
      if (dashboard.crossFilter && dashboard.crossFilter.sourceTileId !== tileId) {
        const { field, value } = dashboard.crossFilter;
        rows = rows.filter((r) => {
          if (r[field] === undefined) return true;
          return String(r[field]).toLowerCase() === String(value).toLowerCase();
        });
      }

      return rows;
    },
    [dashboard.tiles, dashboard.globalFilters, dashboard.crossFilter],
  );

  const computeKpi = useCallback(
    (tile: DashboardTile, rows: Record<string, unknown>[]) => {
      const cfg = tile.kpiConfig || {};
      const valField = cfg.valueField || (rows[0] ? Object.keys(rows[0])[0] : "");

      let total = 0;
      for (const r of rows) {
        const num = Number(r[valField]);
        if (!Number.isNaN(num)) total += num;
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

      const rowField = cfg.rowDimensions[0] || (rows[0] ? Object.keys(rows[0])[0] : "row");
      const colField = cfg.columnDimensions[0] || (rows[0] ? Object.keys(rows[0])[1] : "col");
      const metricField = cfg.valueMetrics[0]?.field || (rows[0] ? Object.keys(rows[0])[2] : "val");

      const rowKeysSet = new Set<string>();
      const colKeysSet = new Set<string>();
      const data: Record<string, Record<string, number>> = {};

      for (const r of rows) {
        const rk = String(r[rowField] ?? "N/A");
        const ck = String(r[colField] ?? "N/A");
        const val = Number(r[metricField]) || 0;

        rowKeysSet.add(rk);
        colKeysSet.add(ck);

        if (!data[rk]) data[rk] = {};
        data[rk][ck] = (data[rk][ck] || 0) + val;
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
