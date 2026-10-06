import React, { useState, useMemo } from "react";
import type {
  BiChartVisualizerProps,
  ChartType,
  AggregationMode,
  ChartDataPoint,
} from "../types";

const PALETTE = [
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#ec4899",
  "#8b5cf6",
  "#06b6d4",
  "#f97316",
  "#14b8a6",
  "#6366f1",
  "#84cc16",
];

function isNumericValue(val: unknown): boolean {
  if (val === null || val === undefined) return false;
  if (typeof val === "number") return !isNaN(val);
  if (typeof val === "string") {
    const trimmed = val.trim();
    return trimmed !== "" && !isNaN(Number(trimmed));
  }
  return false;
}

function parseMetricValue(raw: unknown): number {
  if (raw === null || raw === undefined) return 0;
  if (typeof raw === "number") return isNaN(raw) ? 0 : raw;
  const str = String(raw).trim();
  if (str === "") return 0;
  const num = Number(str);
  return isNaN(num) ? 0 : num;
}

function truncate(str: string, maxLen: number): string {
  if (!str) return "";
  return str.length > maxLen ? `${str.slice(0, maxLen - 1)}…` : str;
}

function formatNumber(val: number): string {
  if (Number.isInteger(val)) return val.toLocaleString();
  return Number(val.toFixed(2)).toLocaleString();
}

export const BiChartVisualizer: React.FC<BiChartVisualizerProps> = ({
  results,
  defaultChartType = "bar",
  chartType: propChartType,
  onChartTypeChange,
  defaultCategoryCol,
  defaultMetricCol,
  defaultAggregation = "SUM",
  stacked: propStacked,
  onStackedChange,
  adapter = "builtin",
  kpiTitle,
  kpiSubtitle,
  className,
  style,
  unstyled = false,
}) => {
  const [internalChartType, setInternalChartType] = useState<ChartType>(defaultChartType);
  const chartType = propChartType !== undefined ? propChartType : internalChartType;

  const [categoryCol, setCategoryCol] = useState<string>("");
  const [metricCol, setMetricCol] = useState<string>("");
  const [aggregation, setAggregation] = useState<AggregationMode>(defaultAggregation);
  const [internalStacked, setInternalStacked] = useState<boolean>(false);
  const isStacked = propStacked !== undefined ? propStacked : internalStacked;

  const [activeTooltip, setActiveTooltip] = useState<{
    category: string;
    metric: string;
    value: number;
    formatted: string;
    percentage?: string;
    x: number;
    y: number;
  } | null>(null);

  const columns = useMemo(() => results?.columns || [], [results]);
  const rows = useMemo(() => results?.rows || [], [results]);

  // Resolve effective category column
  const effectiveCategory = useMemo(() => {
    if (categoryCol && columns.includes(categoryCol)) return categoryCol;
    if (defaultCategoryCol && columns.includes(defaultCategoryCol)) return defaultCategoryCol;
    return columns[0] || "";
  }, [categoryCol, defaultCategoryCol, columns]);

  // Resolve effective metric column
  const effectiveMetric = useMemo(() => {
    if (metricCol && columns.includes(metricCol)) return metricCol;
    if (defaultMetricCol && columns.includes(defaultMetricCol)) return defaultMetricCol;
    const detected = columns.find((col) =>
      rows.slice(0, 5).some((r) => isNumericValue(r[col])),
    );
    return detected || columns[1] || columns[0] || "";
  }, [metricCol, defaultMetricCol, columns, rows]);

  // Transform and aggregate data points
  const points: ChartDataPoint[] = useMemo(() => {
    if (rows.length === 0 || !effectiveCategory || !effectiveMetric) return [];

    if (aggregation === "NONE") {
      return rows.slice(0, 50).map((r, idx) => {
        const rawCat = r[effectiveCategory];
        const cat =
          rawCat !== null && rawCat !== undefined ? String(rawCat) : `Row ${idx + 1}`;
        const val = parseMetricValue(r[effectiveMetric]);
        return {
          category: cat,
          value: val,
          count: 1,
          rawRows: [r],
        };
      });
    }

    // Aggregated mode
    const groupMap = new Map<string, { values: number[]; rows: Record<string, unknown>[] }>();
    for (const r of rows) {
      const rawCat = r[effectiveCategory];
      const cat = rawCat !== null && rawCat !== undefined ? String(rawCat) : "(null)";
      const val = parseMetricValue(r[effectiveMetric]);
      let entry = groupMap.get(cat);
      if (!entry) {
        entry = { values: [], rows: [] };
        groupMap.set(cat, entry);
      }
      entry.values.push(val);
      entry.rows.push(r);
    }

    const aggregated: ChartDataPoint[] = [];
    groupMap.forEach((entry, cat) => {
      let val = 0;
      const count = entry.values.length;
      switch (aggregation) {
        case "SUM":
          val = entry.values.reduce((sum, v) => sum + v, 0);
          break;
        case "COUNT":
          val = count;
          break;
        case "AVG":
          val = entry.values.reduce((sum, v) => sum + v, 0) / count;
          break;
        case "MIN":
          val = Math.min(...entry.values);
          break;
        case "MAX":
          val = Math.max(...entry.values);
          break;
      }
      aggregated.push({
        category: cat,
        value: val,
        count,
        rawRows: entry.rows,
      });
    });

    return aggregated.slice(0, 25);
  }, [rows, effectiveCategory, effectiveMetric, aggregation]);

  const handleChartTypeChange = (newType: ChartType) => {
    setInternalChartType(newType);
    onChartTypeChange?.(newType);
  };

  const handleToggleStacked = () => {
    const next = !isStacked;
    setInternalStacked(next);
    onStackedChange?.(next);
  };

  // Pluggable adapter handling
  if (typeof adapter === "function") {
    return (
      <div
        data-qb="chart-preview-root"
        data-testid="bi-chart-visualizer"
        className={className}
        style={style}
      >
        {adapter({
          results,
          chartType,
          effectiveCategory,
          effectiveMetric,
          points,
          stacked: isStacked,
        })}
      </div>
    );
  }

  if (adapter === "echarts") {
    return (
      <div
        data-qb="chart-preview-root"
        data-testid="echarts-container"
        className={className}
        style={unstyled ? style : { padding: "16px", background: "rgba(15, 23, 42, 0.6)", borderRadius: "8px", ...style }}
      >
        <div style={{ color: "#94a3b8", fontSize: "0.85rem", marginBottom: "8px" }}>
          [Apache ECharts Adapter Canvas]
        </div>
        <div data-testid="echarts-surface" style={{ height: "300px", border: "1px dashed #334155" }} />
      </div>
    );
  }

  if (adapter === "vega-lite") {
    return (
      <div
        data-qb="chart-preview-root"
        data-testid="vega-lite-container"
        className={className}
        style={unstyled ? style : { padding: "16px", background: "rgba(15, 23, 42, 0.6)", borderRadius: "8px", ...style }}
      >
        <div style={{ color: "#94a3b8", fontSize: "0.85rem", marginBottom: "8px" }}>
          [Vega-Lite Adapter Canvas]
        </div>
        <div data-testid="vega-lite-surface" style={{ height: "300px", border: "1px dashed #334155" }} />
      </div>
    );
  }

  // If no results or empty data
  if (!results || columns.length === 0 || rows.length === 0) {
    return (
      <div
        role="region"
        aria-label="Visual Chart Preview"
        className={className}
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          height: "260px",
          color: "#64748b",
          fontStyle: "italic",
          fontSize: "0.85rem",
          background: "rgba(15, 23, 42, 0.5)",
          borderRadius: "8px",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          padding: "16px",
          ...style,
        }}
      >
        <span>No data available to chart. Run a query to preview charts.</span>
      </div>
    );
  }

  // Dimensions & Coordinates
  const width = 600;
  const height = 320;
  const padding = { top: 24, right: 24, bottom: 56, left: 64 };
  const plotWidth = width - padding.left - padding.right; // 512
  const plotHeight = height - padding.top - padding.bottom; // 240

  const minVal = Math.min(0, ...points.map((p) => p.value));
  const maxVal = Math.max(0, ...points.map((p) => p.value));
  const range = maxVal - minVal || 1;
  const yZero = padding.top + plotHeight - ((0 - minVal) / range) * plotHeight;
  const step = points.length > 0 ? plotWidth / points.length : plotWidth;

  // Y-axis ticks
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((pct) => {
    const val = minVal + pct * range;
    const y = padding.top + plotHeight - pct * plotHeight;
    return { val, y };
  });

  // Pie & Donut chart computations
  const pieCenter = { cx: 200, cy: 160 };
  const rOuter = 110;
  const rInner = chartType === "donut" ? 60 : 45;
  const pieTotal = points.reduce((acc, p) => acc + Math.max(0, p.value), 0);
  const positivePoints = points.filter((p) => p.value > 0);

  // Total summary for KPI / Donut
  const totalMetric = points.reduce((acc, p) => acc + p.value, 0);
  const avgMetric = points.length > 0 ? totalMetric / points.length : 0;

  // Tooltip handlers
  const handleShowTooltip = (
    cat: string,
    val: number,
    clientX: number,
    clientY: number,
    pct?: string,
  ) => {
    setActiveTooltip({
      category: cat,
      metric: effectiveMetric,
      value: val,
      formatted: formatNumber(val),
      percentage: pct,
      x: clientX,
      y: clientY,
    });
  };

  return (
    <div
      role="region"
      aria-label="Visual Chart Preview"
      className={className}
      data-qb="chart-preview-root"
      style={
        unstyled
          ? style
          : {
              display: "flex",
              flexDirection: "column",
              gap: "12px",
              position: "relative",
              background: "rgba(15, 23, 42, 0.6)",
              borderRadius: "8px",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              padding: "14px",
              fontFamily: "system-ui, -apple-system, sans-serif",
              ...style,
            }
      }
    >
      {/* Controls Bar */}
      <div
        data-qb="chart-controls"
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "10px",
                paddingBottom: "10px",
                borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
              }
        }
      >
        {/* Chart Type Toggle Buttons */}
        <div
          data-qb="select-chart-type"
          style={unstyled ? undefined : { display: "flex", gap: "4px", flexWrap: "wrap" }}
        >
          <button
            type="button"
            onClick={() => handleChartTypeChange("bar")}
            aria-label="Bar Chart"
            style={
              unstyled
                ? undefined
                : {
                    background: chartType === "bar" ? "#3b82f6" : "rgba(30, 41, 59, 0.6)",
                    color: chartType === "bar" ? "#ffffff" : "#94a3b8",
                    border: "1px solid rgba(255, 255, 255, 0.1)",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            📊 Bar
          </button>
          <button
            type="button"
            onClick={() => handleChartTypeChange("line")}
            aria-label="Line Chart"
            style={
              unstyled
                ? undefined
                : {
                    background: chartType === "line" ? "#3b82f6" : "rgba(30, 41, 59, 0.6)",
                    color: chartType === "line" ? "#ffffff" : "#94a3b8",
                    border: "1px solid rgba(255, 255, 255, 0.1)",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            📈 Line
          </button>
          <button
            type="button"
            onClick={() => handleChartTypeChange("area")}
            aria-label="Area Chart"
            style={
              unstyled
                ? undefined
                : {
                    background: chartType === "area" ? "#3b82f6" : "rgba(30, 41, 59, 0.6)",
                    color: chartType === "area" ? "#ffffff" : "#94a3b8",
                    border: "1px solid rgba(255, 255, 255, 0.1)",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            📉 Area
          </button>
          <button
            type="button"
            onClick={() => handleChartTypeChange("scatter")}
            aria-label="Scatter Plot"
            style={
              unstyled
                ? undefined
                : {
                    background: chartType === "scatter" ? "#3b82f6" : "rgba(30, 41, 59, 0.6)",
                    color: chartType === "scatter" ? "#ffffff" : "#94a3b8",
                    border: "1px solid rgba(255, 255, 255, 0.1)",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            ⁖ Scatter
          </button>
          <button
            type="button"
            onClick={() => handleChartTypeChange("pie")}
            aria-label="Pie Chart"
            style={
              unstyled
                ? undefined
                : {
                    background: chartType === "pie" ? "#3b82f6" : "rgba(30, 41, 59, 0.6)",
                    color: chartType === "pie" ? "#ffffff" : "#94a3b8",
                    border: "1px solid rgba(255, 255, 255, 0.1)",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            🥧 Pie
          </button>
          <button
            type="button"
            onClick={() => handleChartTypeChange("donut")}
            aria-label="Donut Chart"
            style={
              unstyled
                ? undefined
                : {
                    background: chartType === "donut" ? "#3b82f6" : "rgba(30, 41, 59, 0.6)",
                    color: chartType === "donut" ? "#ffffff" : "#94a3b8",
                    border: "1px solid rgba(255, 255, 255, 0.1)",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            🍩 Donut
          </button>
          <button
            type="button"
            onClick={() => handleChartTypeChange("kpi")}
            aria-label="KPI Card"
            style={
              unstyled
                ? undefined
                : {
                    background: chartType === "kpi" ? "#3b82f6" : "rgba(30, 41, 59, 0.6)",
                    color: chartType === "kpi" ? "#ffffff" : "#94a3b8",
                    border: "1px solid rgba(255, 255, 255, 0.1)",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            🎯 KPI
          </button>
        </div>

        {/* Field Mappings & Aggregation Dropdowns */}
        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", alignItems: "center", flexWrap: "wrap", gap: "8px" }
          }
        >
          {(chartType === "bar" || chartType === "area") && (
            <button
              type="button"
              aria-label="Toggle stacked layout"
              aria-pressed={isStacked}
              onClick={handleToggleStacked}
              style={
                unstyled
                  ? undefined
                  : {
                      background: isStacked ? "#2563eb" : "#1e293b",
                      color: isStacked ? "#ffffff" : "#94a3b8",
                      border: "1px solid #475569",
                      borderRadius: "6px",
                      padding: "3px 8px",
                      fontSize: "0.75rem",
                      cursor: "pointer",
                      fontWeight: 600,
                    }
              }
            >
              {isStacked ? "Stacked: On" : "Stacked: Off"}
            </button>
          )}

          {/* Category Dropdown */}
          <label
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                    fontSize: "0.78rem",
                    color: "#94a3b8",
                  }
            }
          >
            <span>Category:</span>
            <select
              aria-label="Select Category column"
              value={effectiveCategory}
              onChange={(e) => setCategoryCol(e.target.value)}
              style={
                unstyled
                  ? undefined
                  : {
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #475569",
                      borderRadius: "6px",
                      padding: "3px 8px",
                      fontSize: "0.78rem",
                    }
              }
            >
              {columns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>

          {/* Metric Dropdown */}
          <label
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                    fontSize: "0.78rem",
                    color: "#94a3b8",
                  }
            }
          >
            <span>Metric:</span>
            <select
              aria-label="Select Metric column"
              value={effectiveMetric}
              onChange={(e) => setMetricCol(e.target.value)}
              style={
                unstyled
                  ? undefined
                  : {
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #475569",
                      borderRadius: "6px",
                      padding: "3px 8px",
                      fontSize: "0.78rem",
                    }
              }
            >
              {columns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>

          {/* Aggregation Dropdown */}
          <label
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                    fontSize: "0.78rem",
                    color: "#94a3b8",
                  }
            }
          >
            <span>Agg:</span>
            <select
              aria-label="Select Aggregation"
              value={aggregation}
              onChange={(e) => setAggregation(e.target.value as AggregationMode)}
              style={
                unstyled
                  ? undefined
                  : {
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #475569",
                      borderRadius: "6px",
                      padding: "3px 8px",
                      fontSize: "0.78rem",
                    }
              }
            >
              <option value="SUM">SUM</option>
              <option value="COUNT">COUNT</option>
              <option value="AVG">AVG</option>
              <option value="MIN">MIN</option>
              <option value="MAX">MAX</option>
              <option value="NONE">NONE (Raw)</option>
            </select>
          </label>
        </div>
      </div>

      {/* SVG Canvas Container or KPI Card */}
      <div
        data-qb="chart-display-container"
        style={
          unstyled
            ? undefined
            : {
                width: "100%",
                overflowX: "auto",
                display: "flex",
                justifyContent: "center",
              }
        }
      >
        {chartType === "kpi" ? (
          <div
            data-testid="kpi-card"
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "2rem",
                    background: "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)",
                    border: "1px solid #334155",
                    borderRadius: "12px",
                    width: "100%",
                    maxWidth: "520px",
                  }
            }
          >
            <div style={unstyled ? undefined : { fontSize: "0.9rem", color: "#94a3b8", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {kpiTitle || `${aggregation} of ${effectiveMetric}`}
            </div>
            <div
              data-testid="kpi-value"
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: "3.25rem",
                      fontWeight: 800,
                      color: "#38bdf8",
                      margin: "0.5rem 0",
                      fontVariantNumeric: "tabular-nums",
                    }
              }
            >
              {formatNumber(aggregation === "AVG" ? avgMetric : totalMetric)}
            </div>
            <div
              data-testid="kpi-badge"
              style={
                unstyled
                  ? undefined
                  : {
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "4px",
                      padding: "0.25rem 0.65rem",
                      borderRadius: "9999px",
                      background: totalMetric >= 0 ? "rgba(16, 185, 129, 0.2)" : "rgba(239, 68, 68, 0.2)",
                      color: totalMetric >= 0 ? "#34d399" : "#f87171",
                      fontSize: "0.8rem",
                      fontWeight: 600,
                      marginBottom: "1rem",
                    }
              }
            >
              {totalMetric >= 0 ? "▲ Positive" : "▼ Negative"} ({points.length} categories)
            </div>

            {/* Sparkline */}
            <svg
              width="240"
              height="40"
              viewBox="0 0 240 40"
              data-testid="kpi-sparkline"
              style={{ overflow: "visible" }}
            >
              {points.length > 1 && (
                <polyline
                  fill="none"
                  stroke="#38bdf8"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  points={points
                    .map((p, idx) => {
                      const sx = (idx / (points.length - 1)) * 240;
                      const sy = 36 - ((p.value - minVal) / range) * 32;
                      return `${sx},${sy}`;
                    })
                    .join(" ")}
                />
              )}
            </svg>

            <div style={unstyled ? undefined : { fontSize: "0.75rem", color: "#64748b", marginTop: "0.75rem" }}>
              {kpiSubtitle || `Grouped by ${effectiveCategory}`}
            </div>
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label={`${chartType.toUpperCase()} chart of ${effectiveMetric} by ${effectiveCategory}`}
            style={{
              width: "100%",
              maxWidth: "720px",
              height: "auto",
              userSelect: "none",
            }}
          >
            <defs>
              <linearGradient id="qbLineGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.4" />
                <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.0" />
              </linearGradient>
            </defs>

            {/* Grid lines and Y-axis ticks for Cartesian charts */}
            {(chartType === "bar" || chartType === "line" || chartType === "area" || chartType === "scatter") && (
              <g aria-hidden="true">
                {ticks.map((t, idx) => (
                  <g key={idx}>
                    <line
                      x1={padding.left}
                      y1={t.y}
                      x2={padding.left + plotWidth}
                      y2={t.y}
                      stroke="rgba(255, 255, 255, 0.08)"
                      strokeDasharray="2,2"
                    />
                    <text
                      x={padding.left - 8}
                      y={t.y + 4}
                      textAnchor="end"
                      fontSize="10"
                      fill="#64748b"
                    >
                      {formatNumber(t.val)}
                    </text>
                  </g>
                ))}
                {/* Baseline zero line if 0 is within range */}
                <line
                  x1={padding.left}
                  y1={yZero}
                  x2={padding.left + plotWidth}
                  y2={yZero}
                  stroke="#475569"
                  strokeWidth={1}
                />
              </g>
            )}

            {/* Bar Chart Rendering */}
            {chartType === "bar" && (
              <g role="group" aria-label="Bar chart series">
                {points.map((p, idx) => {
                  const barWidth = Math.max(8, Math.min(48, step * 0.7));
                  const x = padding.left + idx * step + (step - barWidth) / 2;
                  const yVal = padding.top + plotHeight - ((p.value - minVal) / range) * plotHeight;
                  const isPositive = p.value >= 0;
                  const barY = isPositive ? yVal : yZero;
                  const barH = isPositive ? Math.max(2, yZero - yVal) : Math.max(2, yVal - yZero);

                  return (
                    <g key={idx}>
                      <rect
                        x={x}
                        y={barY}
                        width={barWidth}
                        height={barH}
                        rx={4}
                        fill={isStacked ? PALETTE[idx % PALETTE.length] : "#3b82f6"}
                        role="graphics-symbol"
                        tabIndex={0}
                        aria-label={`${p.category}: ${p.value}`}
                        style={{ cursor: "pointer", transition: "fill 0.15s ease" }}
                        onMouseEnter={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          handleShowTooltip(p.category, p.value, rect.left + barWidth / 2, rect.top);
                        }}
                        onMouseLeave={() => setActiveTooltip(null)}
                        onFocus={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          handleShowTooltip(p.category, p.value, rect.left + barWidth / 2, rect.top);
                        }}
                        onBlur={() => setActiveTooltip(null)}
                      />
                      {/* Category Label */}
                      <text
                        x={x + barWidth / 2}
                        y={padding.top + plotHeight + 18}
                        textAnchor="middle"
                        fontSize="10"
                        fill="#94a3b8"
                      >
                        {truncate(p.category, 12)}
                      </text>
                    </g>
                  );
                })}
              </g>
            )}

            {/* Line Chart Rendering */}
            {chartType === "line" && (
              <g role="group" aria-label="Line chart series">
                {points.length > 0 && (() => {
                  const coords = points.map((p, idx) => {
                    const cx = padding.left + (idx + 0.5) * step;
                    const cy = padding.top + plotHeight - ((p.value - minVal) / range) * plotHeight;
                    return { cx, cy, p };
                  });
                  const lineD = coords
                    .map((c, i) => `${i === 0 ? "M" : "L"} ${c.cx} ${c.cy}`)
                    .join(" ");
                  const first = coords[0];
                  const last = coords[coords.length - 1];
                  const areaD = `${lineD} L ${last.cx} ${yZero} L ${first.cx} ${yZero} Z`;

                  return (
                    <>
                      {/* Shaded Area under Curve */}
                      <path d={areaD} fill="url(#qbLineGradient)" />
                      {/* Trend Line */}
                      <path
                        d={lineD}
                        fill="none"
                        stroke="#3b82f6"
                        strokeWidth={3}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                      {/* Data Points */}
                      {coords.map((c, idx) => (
                        <g key={idx}>
                          <circle
                            cx={c.cx}
                            cy={c.cy}
                            r={4}
                            fill="#3b82f6"
                            stroke="#ffffff"
                            strokeWidth={2}
                            role="graphics-symbol"
                            tabIndex={0}
                            aria-label={`${c.p.category}: ${c.p.value}`}
                            style={{ cursor: "pointer", transition: "r 0.15s ease" }}
                            onMouseEnter={(e) => {
                              const rect = e.currentTarget.getBoundingClientRect();
                              handleShowTooltip(c.p.category, c.p.value, rect.left, rect.top);
                            }}
                            onMouseLeave={() => setActiveTooltip(null)}
                            onFocus={(e) => {
                              const rect = e.currentTarget.getBoundingClientRect();
                              handleShowTooltip(c.p.category, c.p.value, rect.left, rect.top);
                            }}
                            onBlur={() => setActiveTooltip(null)}
                          />
                          {/* X-axis Label */}
                          <text
                            x={c.cx}
                            y={padding.top + plotHeight + 18}
                            textAnchor="middle"
                            fontSize="10"
                            fill="#94a3b8"
                          >
                            {truncate(c.p.category, 12)}
                          </text>
                        </g>
                      ))}
                    </>
                  );
                })()}
              </g>
            )}

            {/* Area Chart Rendering */}
            {chartType === "area" && (
              <g role="group" aria-label="Area chart series">
                {points.length > 0 && (() => {
                  const coords = points.map((p, idx) => {
                    const cx = padding.left + (idx + 0.5) * step;
                    const cy = padding.top + plotHeight - ((p.value - minVal) / range) * plotHeight;
                    return { cx, cy, p };
                  });
                  const lineD = coords
                    .map((c, i) => `${i === 0 ? "M" : "L"} ${c.cx} ${c.cy}`)
                    .join(" ");
                  const first = coords[0];
                  const last = coords[coords.length - 1];
                  const areaD = `${lineD} L ${last.cx} ${yZero} L ${first.cx} ${yZero} Z`;

                  return (
                    <>
                      <path d={areaD} fill="url(#qbLineGradient)" />
                      <path
                        d={lineD}
                        fill="none"
                        stroke="#38bdf8"
                        strokeWidth={2.5}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                      {coords.map((c, idx) => (
                        <g key={idx}>
                          <circle
                            cx={c.cx}
                            cy={c.cy}
                            r={4.5}
                            fill="#38bdf8"
                            stroke="#ffffff"
                            strokeWidth={2}
                            role="graphics-symbol"
                            tabIndex={0}
                            aria-label={`${c.p.category}: ${c.p.value}`}
                            onMouseEnter={(e) => {
                              const rect = e.currentTarget.getBoundingClientRect();
                              handleShowTooltip(c.p.category, c.p.value, rect.left, rect.top);
                            }}
                            onMouseLeave={() => setActiveTooltip(null)}
                            onFocus={(e) => {
                              const rect = e.currentTarget.getBoundingClientRect();
                              handleShowTooltip(c.p.category, c.p.value, rect.left, rect.top);
                            }}
                            onBlur={() => setActiveTooltip(null)}
                          />
                          <text
                            x={c.cx}
                            y={padding.top + plotHeight + 18}
                            textAnchor="middle"
                            fontSize="10"
                            fill="#94a3b8"
                          >
                            {truncate(c.p.category, 12)}
                          </text>
                        </g>
                      ))}
                    </>
                  );
                })()}
              </g>
            )}

            {/* Scatter Plot Rendering */}
            {chartType === "scatter" && (
              <g role="group" aria-label="Scatter plot series">
                {points.map((p, idx) => {
                  const cx = padding.left + (idx + 0.5) * step;
                  const cy = padding.top + plotHeight - ((p.value - minVal) / range) * plotHeight;
                  const color = PALETTE[idx % PALETTE.length];

                  return (
                    <g key={idx}>
                      <circle
                        cx={cx}
                        cy={cy}
                        r={6}
                        fill={color}
                        stroke="#ffffff"
                        strokeWidth={1.5}
                        role="graphics-symbol"
                        tabIndex={0}
                        aria-label={`${p.category}: ${p.value}`}
                        onMouseEnter={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          handleShowTooltip(p.category, p.value, rect.left, rect.top);
                        }}
                        onMouseLeave={() => setActiveTooltip(null)}
                        onFocus={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          handleShowTooltip(p.category, p.value, rect.left, rect.top);
                        }}
                        onBlur={() => setActiveTooltip(null)}
                      />
                      <text
                        x={cx}
                        y={padding.top + plotHeight + 18}
                        textAnchor="middle"
                        fontSize="10"
                        fill="#94a3b8"
                      >
                        {truncate(p.category, 12)}
                      </text>
                    </g>
                  );
                })}
              </g>
            )}

            {/* Pie & Donut Chart Rendering */}
            {(chartType === "pie" || chartType === "donut") && (
              <g role="group" aria-label={`${chartType === "donut" ? "Donut" : "Pie"} chart series`}>
                {pieTotal === 0 ? (
                  <text
                    x={pieCenter.cx}
                    y={pieCenter.cy}
                    textAnchor="middle"
                    fill="#94a3b8"
                    fontSize="14"
                  >
                    Total is 0
                  </text>
                ) : positivePoints.length === 1 ? (
                  (() => {
                    const p = positivePoints[0];
                    return (
                      <g>
                        <circle
                          cx={pieCenter.cx}
                          cy={pieCenter.cy}
                          r={rOuter}
                          fill={PALETTE[0]}
                          role="graphics-symbol"
                          tabIndex={0}
                          aria-label={`${p.category}: ${p.value} (100.0%)`}
                          onMouseEnter={(e) => {
                            const rect = e.currentTarget.getBoundingClientRect();
                            handleShowTooltip(p.category, p.value, rect.left + rOuter, rect.top, "100.0%");
                          }}
                          onMouseLeave={() => setActiveTooltip(null)}
                          onFocus={(e) => {
                            const rect = e.currentTarget.getBoundingClientRect();
                            handleShowTooltip(p.category, p.value, rect.left + rOuter, rect.top, "100.0%");
                          }}
                          onBlur={() => setActiveTooltip(null)}
                        />
                        <circle cx={pieCenter.cx} cy={pieCenter.cy} r={rInner} fill="#090d16" />
                      </g>
                    );
                  })()
                ) : (
                  (() => {
                    let currentAngle = -Math.PI / 2;
                    return positivePoints.map((p, idx) => {
                      const sweep = (p.value / pieTotal) * 2 * Math.PI;
                      const startAngle = currentAngle;
                      const endAngle = currentAngle + sweep;
                      currentAngle = endAngle;

                      const x1 = pieCenter.cx + rOuter * Math.cos(startAngle);
                      const y1 = pieCenter.cy + rOuter * Math.sin(startAngle);
                      const x2 = pieCenter.cx + rOuter * Math.cos(endAngle);
                      const y2 = pieCenter.cy + rOuter * Math.sin(endAngle);
                      const x3 = pieCenter.cx + rInner * Math.cos(endAngle);
                      const y3 = pieCenter.cy + rInner * Math.sin(endAngle);
                      const x4 = pieCenter.cx + rInner * Math.cos(startAngle);
                      const y4 = pieCenter.cy + rInner * Math.sin(startAngle);
                      const largeArc = sweep > Math.PI ? 1 : 0;
                      const d = `M ${x1} ${y1} A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${x2} ${y2} L ${x3} ${y3} A ${rInner} ${rInner} 0 ${largeArc} 0 ${x4} ${y4} Z`;
                      const color = PALETTE[idx % PALETTE.length];
                      const pctStr = `${((p.value / pieTotal) * 100).toFixed(1)}%`;

                      return (
                        <path
                          key={idx}
                          d={d}
                          fill={color}
                          stroke="#090d16"
                          strokeWidth={2}
                          role="graphics-symbol"
                          tabIndex={0}
                          aria-label={`${p.category}: ${p.value} (${pctStr})`}
                          style={{ cursor: "pointer", transition: "opacity 0.15s ease" }}
                          onMouseEnter={(e) => {
                            const rect = e.currentTarget.getBoundingClientRect();
                            handleShowTooltip(p.category, p.value, rect.left + 20, rect.top, pctStr);
                          }}
                          onMouseLeave={() => setActiveTooltip(null)}
                          onFocus={(e) => {
                            const rect = e.currentTarget.getBoundingClientRect();
                            handleShowTooltip(p.category, p.value, rect.left + 20, rect.top, pctStr);
                          }}
                          onBlur={() => setActiveTooltip(null)}
                        />
                      );
                    });
                  })()
                )}

                {/* Donut / Pie Center Badge */}
                {pieTotal > 0 && (
                  <g pointerEvents="none">
                    <text
                      x={pieCenter.cx}
                      y={pieCenter.cy - 4}
                      textAnchor="middle"
                      fill="#f8fafc"
                      fontSize="16"
                      fontWeight="700"
                    >
                      {formatNumber(pieTotal)}
                    </text>
                    <text
                      x={pieCenter.cx}
                      y={pieCenter.cy + 14}
                      textAnchor="middle"
                      fill="#64748b"
                      fontSize="10"
                      fontWeight="600"
                    >
                      TOTAL
                    </text>
                  </g>
                )}

                {/* Pie Legend on Right */}
                {pieTotal > 0 && (
                  <g role="list" aria-label="Chart legend">
                    {positivePoints.slice(0, 10).map((p, idx) => {
                      const y = 50 + idx * 22;
                      const color = PALETTE[idx % PALETTE.length];
                      const pctStr = `${((p.value / pieTotal) * 100).toFixed(1)}%`;
                      return (
                        <g key={idx} role="listitem">
                          <rect x={350} y={y - 10} width={10} height={10} rx={2} fill={color} />
                          <text x={368} y={y - 1} fill="#e2e8f0" fontSize="11">
                            {truncate(p.category, 14)}
                            <tspan fill="#94a3b8"> ({pctStr})</tspan>
                          </text>
                        </g>
                      );
                    })}
                  </g>
                )}
              </g>
            )}
          </svg>
        )}
      </div>

      {/* Floating Tooltip */}
      {activeTooltip && (
        <div
          role="tooltip"
          data-testid="chart-tooltip"
          style={{
            position: "absolute",
            left: "50%",
            top: "20px",
            transform: "translateX(-50%)",
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: "6px",
            padding: "6px 12px",
            fontSize: "0.75rem",
            color: "#f8fafc",
            pointerEvents: "none",
            boxShadow: "0 4px 12px rgba(0, 0, 0, 0.4)",
            zIndex: 10,
          }}
        >
          <div style={{ fontWeight: 600, color: "#93c5fd" }}>{activeTooltip.category}</div>
          <div style={{ color: "#e2e8f0" }}>
            {activeTooltip.metric}: <strong>{activeTooltip.formatted}</strong>
            {activeTooltip.percentage ? ` (${activeTooltip.percentage})` : ""}
          </div>
        </div>
      )}
    </div>
  );
};

export default BiChartVisualizer;
