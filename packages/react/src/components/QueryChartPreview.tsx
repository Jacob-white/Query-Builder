import React, { useState, useMemo } from "react";
import type {
  QueryChartPreviewProps,
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

export const QueryChartPreview: React.FC<QueryChartPreviewProps> = ({
  results,
  defaultChartType = "bar",
  defaultCategoryCol,
  defaultMetricCol,
  defaultAggregation = "SUM",
  className,
  style,
  unstyled = false,
}) => {
  const [chartType, setChartType] = useState<ChartType>(defaultChartType);
  const [categoryCol, setCategoryCol] = useState<string>("");
  const [metricCol, setMetricCol] = useState<string>("");
  const [aggregation, setAggregation] = useState<AggregationMode>(defaultAggregation);
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
  const step = plotWidth / points.length;

  // Y-axis ticks
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((pct) => {
    const val = minVal + pct * range;
    const y = padding.top + plotHeight - pct * plotHeight;
    return { val, y };
  });

  // Pie chart computations
  const pieCenter = { cx: 200, cy: 160 };
  const rOuter = 110;
  const rInner = 45;
  const pieTotal = points.reduce((acc, p) => acc + Math.max(0, p.value), 0);
  const positivePoints = points.filter((p) => p.value > 0);

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
          style={unstyled ? undefined : { display: "flex", gap: "4px" }}
        >
          <button
            type="button"
            onClick={() => setChartType("bar")}
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
            onClick={() => setChartType("line")}
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
            onClick={() => setChartType("pie")}
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
            🍩 Pie
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

      {/* SVG Canvas Container */}
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

          {/* Grid lines and Y-axis ticks for Bar & Line */}
          {chartType !== "pie" && (
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
                      fill="#3b82f6"
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

          {/* Pie / Donut Chart Rendering */}
          {chartType === "pie" && (
            <g role="group" aria-label="Pie chart series">
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

              {/* Donut Center Badge */}
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
