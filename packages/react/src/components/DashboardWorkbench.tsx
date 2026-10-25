/**
 * Multi-Tile Interactive Dashboard Workbench Component.
 * =====================================================
 * Turnkey responsive CSS grid canvas supporting KPI cards, interactive charts,
 * pivot tables, raw data grids, global cascading parameter filters, and
 * reactive click-to-filter cross-filtering across tiles.
 */

import React, { useState, useEffect } from "react";
import { useDashboardManager, inferDashboardColumns } from "../hooks/useDashboardManager";
import { BiChartVisualizer } from "./BiChartVisualizer";
import { useTheme } from "../theme/ThemeProvider";
import type {
  AggregationMode,
  DashboardState,
  DashboardTileType,
  ChartType,
  QueryResultData,
  QuerySpec,
} from "../types";

const SR_ONLY_STYLE: React.CSSProperties = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

export interface DashboardWorkbenchProps {
  initialState?: Partial<DashboardState>;
  results?: QueryResultData | null;
  querySpec?: QuerySpec | null;
  sql?: string;
  storageKey?: string;
  onStateChange?: (state: DashboardState) => void;
  readOnly?: boolean;
  unstyled?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export const DashboardWorkbench: React.FC<DashboardWorkbenchProps> = ({
  initialState,
  results,
  querySpec,
  sql,
  storageKey,
  onStateChange,
  readOnly = false,
  unstyled = false,
  className = "",
  style = {},
}) => {
  const { cssVariables } = useTheme();
  const {
    dashboard,
    tiles,
    globalFilters,
    crossFilter,
    addTile,
    updateTile,
    removeTile,
    duplicateTile,
    resizeTile,
    setGlobalFilter,
    removeGlobalFilter,
    clearGlobalFilters,
    setCrossFilter,
    clearCrossFilter,
    getFilteredRowsForTile,
    computeKpi,
    computePivot,
  } = useDashboardManager({ initialState, results, storageKey });

  useEffect(() => {
    onStateChange?.(dashboard);
  }, [dashboard, onStateChange]);

  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newTileTitle, setNewTileTitle] = useState("");
  const [newTileType, setNewTileType] = useState<DashboardTileType>("chart");
  const [newTileChartType, setNewTileChartType] = useState<ChartType>("bar");
  const [configuringTileId, setConfiguringTileId] = useState<string | null>(null);

  // Global filter inputs
  const [filterField, setFilterField] = useState("");
  const [filterVal, setFilterVal] = useState("");

  const handleAddTileSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTileTitle.trim()) return;

    const existingTile = tiles.find((t) => t.cachedRows?.length || t.columns?.length);
    const hasQueryResults = results !== undefined && results !== null;
    const activeRows = hasQueryResults
      ? results.rows
      : existingTile?.cachedRows || [];
    const activeCols = hasQueryResults
      ? results.columns
      : existingTile?.columns;

    const inferred = inferDashboardColumns(activeRows, activeCols);

    addTile({
      title: newTileTitle.trim(),
      type: newTileType,
      chartType: newTileType === "chart" ? newTileChartType : undefined,
      columns: inferred.columns,
      categoryCol: newTileType === "chart" ? inferred.categoryCol : undefined,
      metricCol: newTileType === "chart" ? inferred.metricCol : undefined,
      defaultAggregation: newTileType === "chart" ? inferred.defaultAggregation : undefined,
      querySpec: querySpec ?? undefined,
      sql,
      cachedRows: activeRows,
      layout: { w: newTileType === "kpi" ? 1 : 2, h: 1 },
      kpiConfig:
        newTileType === "kpi"
          ? {
              title: newTileTitle.trim(),
              valueField: inferred.hasNonIdMetric ? inferred.metricCol : "__count__",
            }
          : undefined,
      pivotConfig:
        newTileType === "pivot"
          ? {
              rowDimensions: [inferred.categoryCol],
              columnDimensions: [inferred.secondaryCategoryCol],
              valueMetrics: [
                {
                  field: inferred.metricCol,
                  agg: inferred.hasNonIdMetric ? "sum" : "count",
                },
              ],
            }
          : undefined,
    });

    setNewTileTitle("");
    setIsAddModalOpen(false);
  };

  const handleAddGlobalFilter = (e: React.FormEvent) => {
    e.preventDefault();
    if (!filterField.trim() || !filterVal.trim()) return;
    setGlobalFilter({
      field: filterField.trim(),
      operator: "=",
      value: filterVal.trim(),
    });
    setFilterField("");
    setFilterVal("");
  };

  const containerStyle: React.CSSProperties = unstyled
    ? {}
    : {
        ...(cssVariables as React.CSSProperties),
        display: "flex",
        flexDirection: "column",
        gap: "1.25rem",
        backgroundColor: "var(--qb-color-background, #181825)",
        color: "var(--qb-color-text, #cdd6f4)",
        padding: "1.5rem",
        borderRadius: "12px",
        border: "1px solid var(--qb-color-border, #313244)",
        fontFamily: "system-ui, -apple-system, sans-serif",
        ...style,
      };

  return (
    <div className={`qb-dashboard-workbench ${className}`} style={containerStyle} data-testid="dashboard-workbench">
      {/* Top Header & Actions */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "1rem",
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: "1.4rem", fontWeight: 700, color: "var(--qb-color-text, #cdd6f4)" }}>
            {dashboard.title}
          </h2>
          <span style={{ fontSize: "0.85rem", color: "var(--qb-color-text-muted, #a6adc8)" }}>
            {tiles.length} interactive tile{tiles.length === 1 ? "" : "s"} • Click data points to cross-filter
          </span>
        </div>

        {!readOnly && (
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button
              onClick={() => setIsAddModalOpen(true)}
              style={{
                padding: "0.5rem 1rem",
                backgroundColor: "var(--qb-color-primary, #89b4fa)",
                color: "#ffffff",
                border: "none",
                borderRadius: "6px",
                fontWeight: 600,
                fontSize: "0.85rem",
                cursor: "pointer",
              }}
              data-testid="add-tile-btn"
            >
              + Add Tile
            </button>
          </div>
        )}
      </div>

      {/* Global Filter Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.75rem",
          padding: "0.75rem 1rem",
          backgroundColor: "var(--qb-color-surface, #1e1e2e)",
          borderRadius: "8px",
          border: "1px solid var(--qb-color-border, #313244)",
          flexWrap: "wrap",
        }}
        data-testid="global-filter-bar"
      >
        <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--qb-color-primary, #89b4fa)", textTransform: "uppercase" }}>
          ⚡ Global Filters:
        </span>

        {globalFilters.length === 0 ? (
          <span style={{ fontSize: "0.8rem", color: "var(--qb-color-text-muted, #6c7086)" }}>None active</span>
        ) : (
          globalFilters.map((gf) => (
            <span
              key={gf.field}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "0.2rem 0.6rem",
                borderRadius: "16px",
                backgroundColor: "rgba(59, 130, 246, 0.14)",
                border: "1px solid var(--qb-color-primary, #89b4fa)",
                fontSize: "0.8rem",
                color: "var(--qb-color-text, #cdd6f4)",
              }}
              data-testid={`global-filter-pill-${gf.field}`}
            >
              <strong>{gf.field}</strong> = {String(gf.value)}
              {!readOnly && (
                <button
                  onClick={() => removeGlobalFilter(gf.field)}
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "var(--qb-color-error, #f38ba8)",
                    cursor: "pointer",
                    padding: 0,
                    lineHeight: 1,
                  }}
                  data-testid={`remove-global-filter-${gf.field}`}
                >
                  &times;
                </button>
              )}
            </span>
          ))
        )}

        {globalFilters.length > 0 && !readOnly && (
          <button
            onClick={clearGlobalFilters}
            style={{
              background: "transparent",
              border: "none",
              color: "var(--qb-color-error, #f38ba8)",
              fontSize: "0.75rem",
              cursor: "pointer",
              textDecoration: "underline",
            }}
            data-testid="clear-global-filters-btn"
          >
            Clear all
          </button>
        )}

        {!readOnly && (
          <form
            onSubmit={handleAddGlobalFilter}
            style={{ display: "flex", gap: "0.4rem", marginLeft: "auto", alignItems: "center" }}
            data-testid="add-filter-form"
          >
            <input
              type="text"
              placeholder="Field (e.g. region)"
              value={filterField}
              onChange={(e) => setFilterField(e.target.value)}
              style={{
                padding: "0.3rem 0.5rem",
                backgroundColor: "var(--qb-color-background, #181825)",
                border: "1px solid var(--qb-color-border, #45475a)",
                borderRadius: "4px",
                color: "var(--qb-color-text, #cdd6f4)",
                fontSize: "0.8rem",
                width: "120px",
              }}
              data-testid="filter-field-input"
            />
            <input
              type="text"
              placeholder="Value"
              value={filterVal}
              onChange={(e) => setFilterVal(e.target.value)}
              style={{
                padding: "0.3rem 0.5rem",
                backgroundColor: "var(--qb-color-background, #181825)",
                border: "1px solid var(--qb-color-border, #45475a)",
                borderRadius: "4px",
                color: "var(--qb-color-text, #cdd6f4)",
                fontSize: "0.8rem",
                width: "100px",
              }}
              data-testid="filter-val-input"
            />
            <button
              type="submit"
              style={{
                padding: "0.3rem 0.6rem",
                backgroundColor: "var(--qb-color-border, #313244)",
                border: "none",
                borderRadius: "4px",
                color: "var(--qb-color-text, #cdd6f4)",
                fontSize: "0.8rem",
                cursor: "pointer",
              }}
              data-testid="add-filter-submit-btn"
            >
              Add
            </button>
          </form>
        )}
      </div>

      {/* Reactive Cross-Filter Active Banner */}
      {crossFilter && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "0.6rem 1rem",
            backgroundColor: "rgba(16, 185, 129, 0.14)",
            border: "1px solid var(--qb-color-success, #a6e3a1)",
            borderRadius: "6px",
            color: "var(--qb-color-success, #a6e3a1)",
            fontSize: "0.85rem",
          }}
          data-testid="cross-filter-banner"
        >
          <span>
            🔍 <strong>Cross-Filter Active:</strong> {crossFilter.field} = "{String(crossFilter.value)}" (propagating across tiles)
          </span>
          <button
            onClick={clearCrossFilter}
            style={{
              background: "transparent",
              border: "1px solid var(--qb-color-success, #a6e3a1)",
              borderRadius: "4px",
              color: "var(--qb-color-success, #a6e3a1)",
              fontSize: "0.75rem",
              padding: "0.2rem 0.5rem",
              cursor: "pointer",
            }}
            data-testid="clear-cross-filter-btn"
          >
            Reset Cross-Filter
          </button>
        </div>
      )}

      {/* Responsive Grid Canvas */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: "1.25rem",
        }}
        data-testid="dashboard-grid-canvas"
      >
        {tiles.length === 0 ? (
          <div
            style={{
              gridColumn: "span 4",
              textAlign: "center",
              padding: "4rem 2rem",
              backgroundColor: "var(--qb-color-surface, #1e1e2e)",
              borderRadius: "12px",
              border: "2px dashed var(--qb-color-border, #45475a)",
            }}
            data-testid="empty-dashboard-state"
          >
            <div style={{ fontSize: "2.5rem", marginBottom: "0.75rem" }}>📊</div>
            <h3 style={{ margin: "0 0 0.5rem 0", color: "var(--qb-color-text, #cdd6f4)" }}>Dashboard is Empty</h3>
            <p style={{ margin: "0 0 1.5rem 0", color: "var(--qb-color-text-muted, #a6adc8)", fontSize: "0.9rem" }}>
              Add interactive chart tiles, KPI cards, or pivot tables to visualize your data.
            </p>
            {!readOnly && (
              <button
                onClick={() => setIsAddModalOpen(true)}
                style={{
                  padding: "0.6rem 1.5rem",
                  backgroundColor: "var(--qb-color-primary, #89b4fa)",
                  color: "#ffffff",
                  border: "none",
                  borderRadius: "6px",
                  fontWeight: 600,
                  fontSize: "0.9rem",
                  cursor: "pointer",
                }}
              >
                Create First Tile
              </button>
            )}
          </div>
        ) : (
          tiles.map((tile) => {
            const rows = getFilteredRowsForTile(tile.id);
            const spanW = tile.layout?.w || 2;

            return (
              <div
                key={tile.id}
                style={{
                  gridColumn: `span ${Math.min(4, Math.max(1, spanW))}`,
                  backgroundColor: "var(--qb-color-surface, #1e1e2e)",
                  border: "1px solid var(--qb-color-border, #313244)",
                  borderRadius: "10px",
                  display: "flex",
                  flexDirection: "column",
                  overflow: "hidden",
                }}
                data-testid={`dashboard-tile-${tile.id}`}
              >
                {/* Tile Header */}
                <div
                  style={{
                    padding: "0.75rem 1rem",
                    borderBottom: "1px solid var(--qb-color-border, #313244)",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    backgroundColor: "rgba(148, 163, 184, 0.05)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <span style={{ fontWeight: 600, fontSize: "0.95rem", color: "var(--qb-color-text, #cdd6f4)" }}>
                      {tile.title}
                    </span>
                    <span
                      style={{
                        fontSize: "0.65rem",
                        padding: "0.1rem 0.35rem",
                        borderRadius: "3px",
                        backgroundColor: "var(--qb-color-border, #313244)",
                        color: "var(--qb-color-primary, #89b4fa)",
                        textTransform: "uppercase",
                      }}
                    >
                      {tile.type === "chart" ? `Chart (${tile.chartType})` : tile.type}
                    </span>
                  </div>

                  {!readOnly && (
                    <div style={{ display: "flex", gap: "0.3rem" }}>
                      {/* Configure Tile Axis & Chart Type */}
                      <button
                        type="button"
                        onClick={() =>
                          setConfiguringTileId((prev) =>
                            prev === tile.id ? null : tile.id,
                          )
                        }
                        style={{
                          background:
                            configuringTileId === tile.id
                              ? "var(--qb-color-primary, #89b4fa)"
                              : "var(--qb-color-border, #313244)",
                          border: "none",
                          color:
                            configuringTileId === tile.id
                              ? "#11111b"
                              : "var(--qb-color-text, #cdd6f4)",
                          fontSize: "0.75rem",
                          borderRadius: "3px",
                          padding: "0.2rem 0.45rem",
                          cursor: "pointer",
                          fontWeight: 600,
                        }}
                        title="Configure Chart Type, Axes & Aggregation"
                        aria-label={`Configure ${tile.title}`}
                        data-testid={`configure-tile-${tile.id}`}
                        data-qb="btn-configure-tile"
                      >
                        ⚙
                      </button>
                      {/* Resize Width Toggle */}
                      <button
                        onClick={() => resizeTile(tile.id, spanW === 4 ? 1 : spanW + 1)}
                        style={{
                          background: "var(--qb-color-border, #313244)",
                          border: "none",
                          color: "var(--qb-color-text, #cdd6f4)",
                          fontSize: "0.75rem",
                          borderRadius: "3px",
                          padding: "0.2rem 0.4rem",
                          cursor: "pointer",
                        }}
                        title={`Span: ${spanW} cols`}
                        data-testid={`resize-tile-${tile.id}`}
                      >
                        {spanW}x
                      </button>
                      {/* Duplicate */}
                      <button
                        onClick={() => duplicateTile(tile.id)}
                        style={{
                          background: "var(--qb-color-border, #313244)",
                          border: "none",
                          color: "var(--qb-color-text, #cdd6f4)",
                          fontSize: "0.75rem",
                          borderRadius: "3px",
                          padding: "0.2rem 0.4rem",
                          cursor: "pointer",
                        }}
                        title="Duplicate"
                        data-testid={`duplicate-tile-${tile.id}`}
                      >
                        📑
                      </button>
                      {/* Delete */}
                      <button
                        onClick={() => removeTile(tile.id)}
                        style={{
                          background: "transparent",
                          border: "none",
                          color: "var(--qb-color-error, #f38ba8)",
                          fontSize: "0.9rem",
                          borderRadius: "3px",
                          padding: "0.1rem 0.3rem",
                          cursor: "pointer",
                        }}
                        title="Remove"
                        data-testid={`remove-tile-${tile.id}`}
                      >
                        🗑
                      </button>
                    </div>
                  )}
                </div>

                {/* Per-Tile Chart / Axis / Aggregation Configuration Bar */}
                {!readOnly && configuringTileId === tile.id && (() => {
                  const availCols = rows[0]
                    ? Object.keys(rows[0])
                    : tile.columns || results?.columns || [];
                  const inferredCfg = inferDashboardColumns(rows, availCols);
                  const currentViz =
                    tile.type === "chart"
                      ? tile.chartType || "bar"
                      : tile.type;
                  const currentCat = tile.categoryCol || inferredCfg.categoryCol;
                  const currentMet = tile.metricCol || inferredCfg.metricCol;
                  const currentAgg = tile.defaultAggregation || inferredCfg.defaultAggregation;

                  return (
                    <div
                      data-testid={`tile-config-panel-${tile.id}`}
                      data-qb="tile-config-panel"
                      style={{
                        padding: "0.55rem 0.9rem",
                        borderBottom: "1px solid var(--qb-color-border, #313244)",
                        backgroundColor: "rgba(30, 41, 59, 0.55)",
                        display: "flex",
                        flexWrap: "wrap",
                        gap: "0.6rem",
                        alignItems: "center",
                        fontSize: "0.78rem",
                      }}
                    >
                      <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", color: "var(--qb-color-text-muted, #a6adc8)" }}>
                        <span>Type:</span>
                        <select
                          aria-label="Visualization Type"
                          data-testid={`tile-viz-select-${tile.id}`}
                          value={currentViz}
                          onChange={(e) => {
                            const val = e.target.value;
                            if (val === "kpi" || val === "pivot" || val === "table") {
                              updateTile(tile.id, { type: val });
                            } else {
                              updateTile(tile.id, {
                                type: "chart",
                                chartType: val as ChartType,
                              });
                            }
                          }}
                          style={{
                            padding: "2px 6px",
                            borderRadius: "4px",
                            border: "1px solid var(--qb-color-border, #45475a)",
                            backgroundColor: "var(--qb-color-background, #181825)",
                            color: "var(--qb-color-text, #cdd6f4)",
                            fontSize: "0.75rem",
                          }}
                        >
                          <option value="bar">Bar Chart</option>
                          <option value="line">Line Chart</option>
                          <option value="area">Area Chart</option>
                          <option value="donut">Donut Chart</option>
                          <option value="pie">Pie Chart</option>
                          <option value="scatter">Scatter Plot</option>
                          <option value="kpi">KPI Card</option>
                          <option value="pivot">Pivot Matrix</option>
                          <option value="table">Data Table</option>
                        </select>
                      </label>

                      <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", color: "var(--qb-color-text-muted, #a6adc8)" }}>
                        <span>X-Axis / Group:</span>
                        <select
                          aria-label="Category / X-Axis"
                          data-testid={`tile-category-select-${tile.id}`}
                          value={currentCat}
                          onChange={(e) =>
                            updateTile(tile.id, { categoryCol: e.target.value })
                          }
                          style={{
                            padding: "2px 6px",
                            borderRadius: "4px",
                            border: "1px solid var(--qb-color-border, #45475a)",
                            backgroundColor: "var(--qb-color-background, #181825)",
                            color: "var(--qb-color-text, #cdd6f4)",
                            fontSize: "0.75rem",
                          }}
                        >
                          {availCols.map((col) => (
                            <option key={col} value={col}>
                              {col}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", color: "var(--qb-color-text-muted, #a6adc8)" }}>
                        <span>Y-Axis / Metric:</span>
                        <select
                          aria-label="Metric / Y-Axis"
                          data-testid={`tile-metric-select-${tile.id}`}
                          value={currentMet}
                          onChange={(e) =>
                            updateTile(tile.id, {
                              metricCol: e.target.value,
                              ...(tile.kpiConfig
                                ? {
                                    kpiConfig: {
                                      ...tile.kpiConfig,
                                      valueField: e.target.value,
                                    },
                                  }
                                : {}),
                            })
                          }
                          style={{
                            padding: "2px 6px",
                            borderRadius: "4px",
                            border: "1px solid var(--qb-color-border, #45475a)",
                            backgroundColor: "var(--qb-color-background, #181825)",
                            color: "var(--qb-color-text, #cdd6f4)",
                            fontSize: "0.75rem",
                          }}
                        >
                          {availCols.map((col) => (
                            <option key={col} value={col}>
                              {col}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", color: "var(--qb-color-text-muted, #a6adc8)" }}>
                        <span>Agg:</span>
                        <select
                          aria-label="Aggregation"
                          data-testid={`tile-agg-select-${tile.id}`}
                          value={currentAgg}
                          onChange={(e) =>
                            updateTile(tile.id, {
                              defaultAggregation: e.target.value as AggregationMode,
                            })
                          }
                          style={{
                            padding: "2px 6px",
                            borderRadius: "4px",
                            border: "1px solid var(--qb-color-border, #45475a)",
                            backgroundColor: "var(--qb-color-background, #181825)",
                            color: "var(--qb-color-text, #cdd6f4)",
                            fontSize: "0.75rem",
                          }}
                        >
                          <option value="SUM">SUM</option>
                          <option value="AVG">AVG</option>
                          <option value="COUNT">COUNT</option>
                          <option value="MIN">MIN</option>
                          <option value="MAX">MAX</option>
                        </select>
                      </label>
                    </div>
                  );
                })()}

                {/* Tile Body */}
                <div style={{ padding: "1rem", flex: 1, minHeight: "180px", display: "flex", flexDirection: "column" }}>
                  {tile.type === "kpi" && (
                    <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", height: "100%" }}>
                      {(() => {
                        const kpi = computeKpi(tile, rows);
                        return (
                          <div>
                            <div style={{ fontSize: "2.2rem", fontWeight: 700, color: kpi.color }}>
                              {kpi.value.toLocaleString()}
                            </div>
                            <div style={{ fontSize: "0.85rem", color: "var(--qb-color-text-muted, #a6adc8)", marginTop: "0.25rem" }}>
                              {kpi.title}
                            </div>
                            {kpi.delta !== undefined && (
                              <div
                                style={{
                                  fontSize: "0.8rem",
                                  marginTop: "0.5rem",
                                  color: kpi.delta >= 0 ? "var(--qb-color-success, #a6e3a1)" : "var(--qb-color-error, #f38ba8)",
                                  fontWeight: 600,
                                }}
                              >
                                {kpi.delta >= 0 ? "▲ +" : "▼ "}
                                {kpi.delta}% vs previous period
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    </div>
                  )}

                  {tile.type === "table" && (
                    <div style={{ overflowX: "auto", flex: 1 }}>
                      {(() => {
                        const tableCols = rows[0]
                          ? Object.keys(rows[0])
                          : tile.columns?.length
                            ? tile.columns
                            : results?.columns || [];
                        return (
                          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                            <thead>
                              <tr style={{ borderBottom: "1px solid var(--qb-color-border, #313244)", color: "var(--qb-color-text-muted, #a6adc8)", textAlign: "left" }}>
                                {tableCols.map((col) => (
                                  <th key={col} style={{ padding: "0.4rem 0.6rem" }}>
                                    {col}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {rows.length === 0 ? (
                                <tr>
                                  <td
                                    colSpan={Math.max(1, tableCols.length)}
                                    style={{
                                      padding: "1.25rem",
                                      textAlign: "center",
                                      color: "var(--qb-color-text-muted, #6c7086)",
                                      fontStyle: "italic",
                                    }}
                                    data-testid={`empty-table-tile-${tile.id}`}
                                  >
                                    No matching records
                                  </td>
                                </tr>
                              ) : (
                                rows.slice(0, 25).map((r, rIdx) => (
                                  <tr
                                    key={rIdx}
                                    style={{ borderBottom: "1px solid var(--qb-color-border, #28293d)", cursor: "pointer" }}
                                    onClick={() => {
                                      const firstCol = Object.keys(r)[0];
                                      if (firstCol) setCrossFilter(tile.id, firstCol, r[firstCol]);
                                    }}
                                  >
                                    {Object.values(r).map((val, cIdx) => (
                                      <td key={cIdx} style={{ padding: "0.4rem 0.6rem" }}>
                                        {String(val)}
                                      </td>
                                    ))}
                                  </tr>
                                ))
                              )}
                            </tbody>
                          </table>
                        );
                      })()}
                    </div>
                  )}

                  {tile.type === "pivot" && (
                    <div style={{ overflowX: "auto", flex: 1 }}>
                      {(() => {
                        const pivot = computePivot(tile, rows);
                        return (
                          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                            <thead>
                              <tr style={{ borderBottom: "1px solid var(--qb-color-border, #313244)", color: "var(--qb-color-primary, #89b4fa)" }}>
                                <th style={{ padding: "0.4rem 0.6rem", textAlign: "left" }}>Dimension</th>
                                {pivot.colKeys.map((ck) => (
                                  <th key={ck} style={{ padding: "0.4rem 0.6rem", textAlign: "right" }}>
                                    {ck}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {pivot.rowKeys.map((rk) => (
                                <tr key={rk} style={{ borderBottom: "1px solid var(--qb-color-border, #28293d)" }}>
                                  <td style={{ padding: "0.4rem 0.6rem", fontWeight: 600 }}>{rk}</td>
                                  {pivot.colKeys.map((ck) => (
                                    <td key={ck} style={{ padding: "0.4rem 0.6rem", textAlign: "right" }}>
                                      {pivot.data[rk]?.[ck]?.toLocaleString() || 0}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        );
                      })()}
                    </div>
                  )}

                  {tile.type === "chart" && (
                    <div style={{ flex: 1, minHeight: "160px" }}>
                      {(() => {
                        const tileCols = rows[0]
                          ? Object.keys(rows[0])
                          : tile.columns?.length
                            ? tile.columns
                            : results?.columns || [];
                        const tileInferred = inferDashboardColumns(rows, tileCols);
                        return (
                          <BiChartVisualizer
                            results={{
                              rows,
                              columns: tileCols,
                              count: rows.length,
                            }}
                            chartType={tile.chartType || "bar"}
                            onChartTypeChange={(ct) => updateTile(tile.id, { chartType: ct })}
                            defaultCategoryCol={tile.categoryCol || tileInferred.categoryCol}
                            defaultMetricCol={tile.metricCol || tileInferred.metricCol}
                            defaultAggregation={tile.defaultAggregation || tileInferred.defaultAggregation}
                            onDataPointClick={(cat, _val, field) => setCrossFilter(tile.id, field, cat)}
                          />
                        );
                      })()}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Add Tile Modal */}
      {isAddModalOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.6)",
            backdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 9999,
          }}
          onClick={() => setIsAddModalOpen(false)}
          data-testid="add-tile-modal-overlay"
        >
          <div
            style={{
              backgroundColor: "var(--qb-color-surface, #1e1e2e)",
              border: "1px solid var(--qb-color-border, #313244)",
              borderRadius: "10px",
              padding: "1.5rem",
              width: "100%",
              maxWidth: "450px",
              boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: "0 0 1rem 0", color: "var(--qb-color-text, #cdd6f4)" }}>Add Dashboard Tile</h3>
            <form onSubmit={handleAddTileSubmit}>
              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", color: "var(--qb-color-text-muted, #a6adc8)", marginBottom: "0.4rem" }}>
                  Tile Title
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Regional Revenue"
                  value={newTileTitle}
                  onChange={(e) => setNewTileTitle(e.target.value)}
                  style={{
                    width: "100%",
                    padding: "0.5rem",
                    backgroundColor: "var(--qb-color-background, #181825)",
                    border: "1px solid var(--qb-color-border, #45475a)",
                    borderRadius: "6px",
                    color: "var(--qb-color-text, #cdd6f4)",
                    fontSize: "0.9rem",
                    boxSizing: "border-box",
                  }}
                  data-testid="new-tile-title-input"
                />
              </div>

              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", color: "var(--qb-color-text-muted, #a6adc8)", marginBottom: "0.4rem" }}>
                  Tile Type
                </label>
                <select
                  value={newTileType}
                  onChange={(e) => setNewTileType(e.target.value as DashboardTileType)}
                  style={unstyled ? undefined : SR_ONLY_STYLE}
                  data-testid="new-tile-type-select"
                >
                  <option value="chart">Chart Visualizer</option>
                  <option value="kpi">Single KPI Card</option>
                  <option value="pivot">Pivot Matrix Table</option>
                  <option value="table">Data Grid Table</option>
                </select>
                {!unstyled && (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px" }}>
                    {(
                      [
                        { v: "chart", l: "📊 Chart Visualizer" },
                        { v: "kpi", l: "🎯 Single KPI Card" },
                        { v: "pivot", l: "🔢 Pivot Matrix Table" },
                        { v: "table", l: "📋 Data Grid Table" },
                      ] as const
                    ).map((opt) => {
                      const isSelected = newTileType === opt.v;
                      return (
                        <button
                          key={opt.v}
                          type="button"
                          onClick={() => setNewTileType(opt.v)}
                          style={{
                            padding: "8px 10px",
                            borderRadius: "6px",
                            fontSize: "0.8rem",
                            fontWeight: isSelected ? 700 : 500,
                            cursor: "pointer",
                            border: isSelected ? "1px solid var(--qb-color-primary, #89b4fa)" : "1px solid var(--qb-color-border, #45475a)",
                            backgroundColor: isSelected ? "rgba(59, 130, 246, 0.16)" : "var(--qb-color-background, #181825)",
                            color: isSelected ? "var(--qb-color-primary, #89b4fa)" : "var(--qb-color-text, #cdd6f4)",
                            textAlign: "left",
                          }}
                        >
                          {opt.l}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {newTileType === "chart" && (
                <div style={{ marginBottom: "1.5rem" }}>
                  <label style={{ display: "block", fontSize: "0.85rem", color: "var(--qb-color-text-muted, #a6adc8)", marginBottom: "0.4rem" }}>
                    Chart Type
                  </label>
                  <select
                    value={newTileChartType}
                    onChange={(e) => setNewTileChartType(e.target.value as ChartType)}
                    style={unstyled ? undefined : SR_ONLY_STYLE}
                    data-testid="new-tile-chart-select"
                  >
                    <option value="bar">Bar Chart</option>
                    <option value="line">Line Chart</option>
                    <option value="area">Area Chart</option>
                    <option value="pie">Pie Chart</option>
                  </select>
                  {!unstyled && (
                    <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                      {(
                        [
                          { v: "bar", l: "📊 Bar" },
                          { v: "line", l: "📈 Line" },
                          { v: "area", l: "📉 Area" },
                          { v: "pie", l: "🥧 Pie" },
                        ] as const
                      ).map((opt) => {
                        const isSelected = newTileChartType === opt.v;
                        return (
                          <button
                            key={opt.v}
                            type="button"
                            onClick={() => setNewTileChartType(opt.v)}
                            style={{
                              padding: "6px 12px",
                              borderRadius: "6px",
                              fontSize: "0.8rem",
                              fontWeight: isSelected ? 700 : 500,
                              cursor: "pointer",
                              border: isSelected ? "1px solid var(--qb-color-primary, #89b4fa)" : "1px solid var(--qb-color-border, #45475a)",
                              backgroundColor: isSelected ? "rgba(59, 130, 246, 0.16)" : "var(--qb-color-background, #181825)",
                              color: isSelected ? "var(--qb-color-primary, #89b4fa)" : "var(--qb-color-text, #cdd6f4)",
                            }}
                          >
                            {opt.l}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  style={{
                    padding: "0.5rem 1rem",
                    backgroundColor: "transparent",
                    border: "1px solid var(--qb-color-border, #45475a)",
                    color: "var(--qb-color-text, #cdd6f4)",
                    borderRadius: "6px",
                    cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  style={{
                    padding: "0.5rem 1.25rem",
                    backgroundColor: "var(--qb-color-primary, #89b4fa)",
                    color: "#ffffff",
                    border: "none",
                    borderRadius: "6px",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                  data-testid="confirm-add-tile-btn"
                >
                  Add Tile
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
