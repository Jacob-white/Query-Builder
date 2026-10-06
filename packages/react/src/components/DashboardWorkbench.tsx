/**
 * Multi-Tile Interactive Dashboard Workbench Component.
 * =====================================================
 * Turnkey responsive CSS grid canvas supporting KPI cards, interactive charts,
 * pivot tables, raw data grids, global cascading parameter filters, and
 * reactive click-to-filter cross-filtering across tiles.
 */

import React, { useState, useMemo } from "react";
import { useDashboardManager } from "../hooks/useDashboardManager";
import { BiChartVisualizer } from "./BiChartVisualizer";
import type {
  DashboardState,
  DashboardTile,
  DashboardTileType,
  ChartType,
} from "../types";

export interface DashboardWorkbenchProps {
  initialState?: Partial<DashboardState>;
  onStateChange?: (state: DashboardState) => void;
  readOnly?: boolean;
  unstyled?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export const DashboardWorkbench: React.FC<DashboardWorkbenchProps> = ({
  initialState,
  onStateChange,
  readOnly = false,
  unstyled = false,
  className = "",
  style = {},
}) => {
  const {
    dashboard,
    tiles,
    globalFilters,
    crossFilter,
    addTile,
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
  } = useDashboardManager({ initialState });

  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newTileTitle, setNewTileTitle] = useState("");
  const [newTileType, setNewTileType] = useState<DashboardTileType>("chart");
  const [newTileChartType, setNewTileChartType] = useState<ChartType>("bar");

  // Global filter inputs
  const [filterField, setFilterField] = useState("");
  const [filterVal, setFilterVal] = useState("");

  const handleAddTileSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTileTitle.trim()) return;

    const sampleRows = [
      { category: "Hardware", region: "North", sales: 12000, margin: 3400 },
      { category: "Software", region: "North", sales: 25000, margin: 9200 },
      { category: "Hardware", region: "South", sales: 18000, margin: 4800 },
      { category: "Software", region: "South", sales: 31000, margin: 11500 },
      { category: "Services", region: "East", sales: 9500, margin: 2800 },
    ];

    addTile({
      title: newTileTitle.trim(),
      type: newTileType,
      chartType: newTileType === "chart" ? newTileChartType : undefined,
      cachedRows: sampleRows,
      layout: { w: newTileType === "kpi" ? 1 : 2, h: 1 },
      kpiConfig:
        newTileType === "kpi"
          ? { title: newTileTitle.trim(), valueField: "sales", deltaPercentage: 14.5 }
          : undefined,
      pivotConfig:
        newTileType === "pivot"
          ? {
              rowDimensions: ["category"],
              columnDimensions: ["region"],
              valueMetrics: [{ field: "sales", agg: "sum" }],
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
        display: "flex",
        flexDirection: "column",
        gap: "1.25rem",
        backgroundColor: "#181825",
        color: "#cdd6f4",
        padding: "1.5rem",
        borderRadius: "12px",
        border: "1px solid #313244",
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
          <h2 style={{ margin: 0, fontSize: "1.4rem", fontWeight: 700, color: "#cdd6f4" }}>
            {dashboard.title}
          </h2>
          <span style={{ fontSize: "0.85rem", color: "#a6adc8" }}>
            {tiles.length} interactive tile{tiles.length === 1 ? "" : "s"} • Click data points to cross-filter
          </span>
        </div>

        {!readOnly && (
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button
              onClick={() => setIsAddModalOpen(true)}
              style={{
                padding: "0.5rem 1rem",
                backgroundColor: "#89b4fa",
                color: "#11111b",
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
          backgroundColor: "#1e1e2e",
          borderRadius: "8px",
          border: "1px solid #313244",
          flexWrap: "wrap",
        }}
        data-testid="global-filter-bar"
      >
        <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "#89b4fa", textTransform: "uppercase" }}>
          ⚡ Global Filters:
        </span>

        {globalFilters.length === 0 ? (
          <span style={{ fontSize: "0.8rem", color: "#6c7086" }}>None active</span>
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
                backgroundColor: "rgba(137, 180, 250, 0.2)",
                border: "1px solid #89b4fa",
                fontSize: "0.8rem",
                color: "#cdd6f4",
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
                    color: "#f38ba8",
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
              color: "#f38ba8",
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
                backgroundColor: "#181825",
                border: "1px solid #45475a",
                borderRadius: "4px",
                color: "#cdd6f4",
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
                backgroundColor: "#181825",
                border: "1px solid #45475a",
                borderRadius: "4px",
                color: "#cdd6f4",
                fontSize: "0.8rem",
                width: "100px",
              }}
              data-testid="filter-val-input"
            />
            <button
              type="submit"
              style={{
                padding: "0.3rem 0.6rem",
                backgroundColor: "#313244",
                border: "none",
                borderRadius: "4px",
                color: "#cdd6f4",
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
            backgroundColor: "rgba(166, 227, 161, 0.15)",
            border: "1px solid #a6e3a1",
            borderRadius: "6px",
            color: "#a6e3a1",
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
              border: "1px solid #a6e3a1",
              borderRadius: "4px",
              color: "#a6e3a1",
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
              backgroundColor: "#1e1e2e",
              borderRadius: "12px",
              border: "2px dashed #45475a",
            }}
            data-testid="empty-dashboard-state"
          >
            <div style={{ fontSize: "2.5rem", marginBottom: "0.75rem" }}>📊</div>
            <h3 style={{ margin: "0 0 0.5rem 0", color: "#cdd6f4" }}>Dashboard is Empty</h3>
            <p style={{ margin: "0 0 1.5rem 0", color: "#a6adc8", fontSize: "0.9rem" }}>
              Add interactive chart tiles, KPI cards, or pivot tables to visualize your data.
            </p>
            {!readOnly && (
              <button
                onClick={() => setIsAddModalOpen(true)}
                style={{
                  padding: "0.6rem 1.5rem",
                  backgroundColor: "#89b4fa",
                  color: "#11111b",
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
                  backgroundColor: "#1e1e2e",
                  border: "1px solid #313244",
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
                    borderBottom: "1px solid #313244",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    backgroundColor: "rgba(255, 255, 255, 0.02)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <span style={{ fontWeight: 600, fontSize: "0.95rem", color: "#cdd6f4" }}>
                      {tile.title}
                    </span>
                    <span
                      style={{
                        fontSize: "0.65rem",
                        padding: "0.1rem 0.35rem",
                        borderRadius: "3px",
                        backgroundColor: "#313244",
                        color: "#89b4fa",
                        textTransform: "uppercase",
                      }}
                    >
                      {tile.type === "chart" ? `Chart (${tile.chartType})` : tile.type}
                    </span>
                  </div>

                  {!readOnly && (
                    <div style={{ display: "flex", gap: "0.3rem" }}>
                      {/* Resize Width Toggle */}
                      <button
                        onClick={() => resizeTile(tile.id, spanW === 4 ? 1 : spanW + 1)}
                        style={{
                          background: "#313244",
                          border: "none",
                          color: "#cdd6f4",
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
                          background: "#313244",
                          border: "none",
                          color: "#cdd6f4",
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
                          color: "#f38ba8",
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

                {/* Tile Body */}
                <div style={{ padding: "1rem", flex: 1, minHeight: "180px", display: "flex", flexDirection: "column" }}>
                  {tile.type === "kpi" && (
                    <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", height: "100%" }}>
                      {(() => {
                        const kpi = computeKpi(tile, rows);
                        return (
                          <div>
                            <div style={{ fontSize: "2.2rem", fontWeight: 700, color: kpi.color }}>
                              {typeof kpi.value === "number" ? kpi.value.toLocaleString() : kpi.value}
                            </div>
                            <div style={{ fontSize: "0.85rem", color: "#a6adc8", marginTop: "0.25rem" }}>
                              {kpi.title}
                            </div>
                            {kpi.delta !== undefined && (
                              <div
                                style={{
                                  fontSize: "0.8rem",
                                  marginTop: "0.5rem",
                                  color: kpi.delta >= 0 ? "#a6e3a1" : "#f38ba8",
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
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                        <thead>
                          <tr style={{ borderBottom: "1px solid #313244", color: "#a6adc8", textAlign: "left" }}>
                            {rows[0] &&
                              Object.keys(rows[0]).map((col) => (
                                <th key={col} style={{ padding: "0.4rem 0.6rem" }}>
                                  {col}
                                </th>
                              ))}
                          </tr>
                        </thead>
                        <tbody>
                          {rows.slice(0, 5).map((r, rIdx) => (
                            <tr
                              key={rIdx}
                              style={{ borderBottom: "1px solid #28293d", cursor: "pointer" }}
                              onClick={() => {
                                const firstCol = Object.keys(r)[0];
                                if (firstCol) setCrossFilter(tile.id, firstCol, r[firstCol]);
                              }}
                            >
                              {Object.values(r).map((val: any, cIdx) => (
                                <td key={cIdx} style={{ padding: "0.4rem 0.6rem" }}>
                                  {String(val)}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {tile.type === "pivot" && (
                    <div style={{ overflowX: "auto", flex: 1 }}>
                      {(() => {
                        const pivot = computePivot(tile, rows);
                        return (
                          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                            <thead>
                              <tr style={{ borderBottom: "1px solid #313244", color: "#89b4fa" }}>
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
                                <tr key={rk} style={{ borderBottom: "1px solid #28293d" }}>
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
                      <BiChartVisualizer
                        results={{
                          rows,
                          columns: rows[0] ? Object.keys(rows[0]) : [],
                          count: rows.length,
                        }}
                        chartType={tile.chartType || "bar"}
                        defaultCategoryCol={rows[0] ? Object.keys(rows[0])[0] : undefined}
                        defaultMetricCol={rows[0] ? Object.keys(rows[0])[2] || Object.keys(rows[0])[1] : undefined}
                      />
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
              backgroundColor: "#1e1e2e",
              border: "1px solid #313244",
              borderRadius: "10px",
              padding: "1.5rem",
              width: "100%",
              maxWidth: "450px",
              boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: "0 0 1rem 0", color: "#cdd6f4" }}>Add Dashboard Tile</h3>
            <form onSubmit={handleAddTileSubmit}>
              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", color: "#a6adc8", marginBottom: "0.4rem" }}>
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
                    backgroundColor: "#181825",
                    border: "1px solid #45475a",
                    borderRadius: "6px",
                    color: "#cdd6f4",
                    fontSize: "0.9rem",
                    boxSizing: "border-box",
                  }}
                  data-testid="new-tile-title-input"
                />
              </div>

              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", color: "#a6adc8", marginBottom: "0.4rem" }}>
                  Tile Type
                </label>
                <select
                  value={newTileType}
                  onChange={(e) => setNewTileType(e.target.value as DashboardTileType)}
                  style={{
                    width: "100%",
                    padding: "0.5rem",
                    backgroundColor: "#181825",
                    border: "1px solid #45475a",
                    borderRadius: "6px",
                    color: "#cdd6f4",
                    fontSize: "0.9rem",
                    boxSizing: "border-box",
                  }}
                  data-testid="new-tile-type-select"
                >
                  <option value="chart">Chart Visualizer</option>
                  <option value="kpi">Single KPI Card</option>
                  <option value="pivot">Pivot Matrix Table</option>
                  <option value="table">Data Grid Table</option>
                </select>
              </div>

              {newTileType === "chart" && (
                <div style={{ marginBottom: "1.5rem" }}>
                  <label style={{ display: "block", fontSize: "0.85rem", color: "#a6adc8", marginBottom: "0.4rem" }}>
                    Chart Type
                  </label>
                  <select
                    value={newTileChartType}
                    onChange={(e) => setNewTileChartType(e.target.value as ChartType)}
                    style={{
                      width: "100%",
                      padding: "0.5rem",
                      backgroundColor: "#181825",
                      border: "1px solid #45475a",
                      borderRadius: "6px",
                      color: "#cdd6f4",
                      fontSize: "0.9rem",
                      boxSizing: "border-box",
                    }}
                    data-testid="new-tile-chart-select"
                  >
                    <option value="bar">Bar Chart</option>
                    <option value="line">Line Chart</option>
                    <option value="area">Area Chart</option>
                    <option value="pie">Pie Chart</option>
                  </select>
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  style={{
                    padding: "0.5rem 1rem",
                    backgroundColor: "transparent",
                    border: "1px solid #45475a",
                    color: "#cdd6f4",
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
                    backgroundColor: "#89b4fa",
                    color: "#11111b",
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
