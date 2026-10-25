import React, { useState } from "react";
import type { QueryResultData, QueryBuilderClassNames, SchemaSnapshot } from "../types";
import { useQueryBuilderContext, type CellRenderer } from "../theme/QueryBuilderProvider";
import { csvCellText } from "../utils/csvSafe";
import { cx } from "../utils/classNames";

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

export interface ColumnMicroStats {
  total: number;
  nullCount: number;
  nullPct: number;
  distinctCount: number;
  isNumeric: boolean;
  min?: string;
  max?: string;
  avg?: string;
  topValue?: string;
}

export function resolveForeignKeyTarget(
  col: string,
  schema?: SchemaSnapshot | null,
): { targetTable: string; targetColumn: string } | null {
  const shortCol = col.includes(".") ? col.slice(col.lastIndexOf(".") + 1) : col;
  const colPrefix = col.includes(".") ? col.slice(0, col.lastIndexOf(".")) : null;

  for (const fk of schema?.foreign_keys || []) {
    if (fk.column === shortCol && (!colPrefix || fk.table === colPrefix)) {
      return { targetTable: fk.foreign_table, targetColumn: fk.foreign_column };
    }
  }

  for (const rel of schema?.relationships || []) {
    if (rel.source_column === shortCol && (!colPrefix || rel.source_table === colPrefix)) {
      return { targetTable: rel.target_table, targetColumn: rel.target_column };
    }
  }

  if (shortCol.toLowerCase().endsWith("_id") && shortCol.length > 3) {
    const stem = shortCol.slice(0, -3).toLowerCase();
    const defaultPlural = stem.endsWith("y")
      ? `${stem.slice(0, -1)}ies`
      : stem.endsWith("s")
        ? `${stem}es`
        : `${stem}s`;
    const candidates = [stem, defaultPlural, `${stem}es`];
    const tableNames = Object.keys(schema?.tables || {});
    for (const cand of candidates) {
      const matched = tableNames.find((t) => t.toLowerCase() === cand);
      if (matched) {
        return { targetTable: matched, targetColumn: "id" };
      }
    }
    if (tableNames.length === 0) {
      return { targetTable: defaultPlural, targetColumn: "id" };
    }
  }

  return null;
}

export interface QueryResultsTableProps {
  results: QueryResultData | null;
  isLoading?: boolean;
  unstyled?: boolean;
  cellRenderers?: Record<string, CellRenderer>;
  pageSize?: number;
  onReorderColumns?: (newColumns: string[]) => void;
  schema?: SchemaSnapshot | null;
  onFilterByCell?: (
    column: string,
    value: unknown,
    operator: "=" | "!=" | "IS NULL" | "IS NOT NULL",
  ) => void;
  onDrillDownForeignKey?: (
    column: string,
    value: unknown,
    targetTable?: string,
    targetColumn?: string,
  ) => void;
  onPinToDashboard?: () => void;
  className?: string;
  classNames?: QueryBuilderClassNames;
}

export const QueryResultsTable: React.FC<QueryResultsTableProps> = ({
  results,
  isLoading,
  unstyled = false,
  cellRenderers,
  pageSize = 100,
  onReorderColumns,
  schema,
  onFilterByCell,
  onDrillDownForeignKey,
  onPinToDashboard,
  className,
  classNames,
}) => {
  const ctx = useQueryBuilderContext();
  const effectiveCellRenderers = cellRenderers ?? ctx?.cellRenderers;
  const [searchTerm, setSearchTerm] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [rowsPerPage, setRowsPerPage] = useState(pageSize);
  const [orderedColumns, setOrderedColumns] = useState<string[]>(results?.columns || []);
  const [draggedColIdx, setDraggedColIdx] = useState<number | null>(null);
  const [dragOverColIdx, setDragOverColIdx] = useState<number | null>(null);
  const [showColumnStats, setShowColumnStats] = useState(false);
  const [selectedCell, setSelectedCell] = useState<{
    rowIdx: number;
    column: string;
    value: unknown;
  } | null>(null);

  React.useEffect(() => {
    setCurrentPage(1);
    setOrderedColumns(results?.columns || []);
    setSelectedCell(null);
  }, [results]);

  React.useEffect(() => {
    setRowsPerPage(pageSize);
  }, [pageSize]);

  if (isLoading) {
    return (
      <div
        data-qb="results-table-root"
        className={cx(className, classNames?.results, classNames?.resultsLoading)}
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                height: "200px",
                color: "#94a3b8",
                fontSize: "0.9rem",
              }
        }
      >
        <span>⏳ Executing read-only query...</span>
      </div>
    );
  }

  if (!results) {
    return (
      <div
        data-qb="results-table-root"
        className={cx(className, classNames?.results, classNames?.resultsEmpty)}
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                height: "180px",
                color: "#64748b",
                fontStyle: "italic",
                fontSize: "0.85rem",
              }
        }
      >
        No query executed yet. Click "Run Query" to preview results.
      </div>
    );
  }

  const rawColumns = results.columns || [];
  const columns =
    orderedColumns.length === rawColumns.length &&
    orderedColumns.every((c) => rawColumns.includes(c))
      ? orderedColumns
      : rawColumns;
  const rows = results.rows || [];
  const durationMs = results.durationMs ?? results.latency_ms;

  const handleDropColumn = (fromIndex: number | null, toIndex: number) => {
    setDraggedColIdx(null);
    setDragOverColIdx(null);
    if (
      fromIndex === null ||
      fromIndex === toIndex ||
      fromIndex < 0 ||
      toIndex < 0 ||
      fromIndex >= columns.length ||
      toIndex >= columns.length
    ) {
      return;
    }
    const nextCols = [...columns];
    const [moved] = nextCols.splice(fromIndex, 1);
    nextCols.splice(toIndex, 0, moved);
    setOrderedColumns(nextCols);
    if (onReorderColumns) {
      onReorderColumns(nextCols);
    }
  };

  const filteredRows = rows.filter((r) => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return Object.values(r).some((v) =>
      String(v ?? "").toLowerCase().includes(term),
    );
  });

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / rowsPerPage));
  const effectivePage = Math.min(currentPage, totalPages);
  const displayedRows =
    filteredRows.length > rowsPerPage
      ? filteredRows.slice(
          (effectivePage - 1) * rowsPerPage,
          effectivePage * rowsPerPage,
        )
      : filteredRows;

  const columnStatsMap: Record<string, ColumnMicroStats> = {};
  if (showColumnStats) {
    const total = filteredRows.length;
    for (const col of columns) {
      let nullCount = 0;
      const nonNullStrings: string[] = [];
      const numericVals: number[] = [];
      let allNumeric = true;
      const freq: Record<string, number> = {};

      for (const row of filteredRows) {
        const val = row[col];
        if (val === null || val === undefined) {
          nullCount += 1;
          continue;
        }
        const s = typeof val === "object" ? JSON.stringify(val) : String(val);
        nonNullStrings.push(s);
        freq[s] = (freq[s] || 0) + 1;
        if (allNumeric) {
          if (typeof val === "number" && Number.isFinite(val)) {
            numericVals.push(val);
          } else if (
            typeof val === "string" &&
            val.trim() !== "" &&
            Number.isFinite(Number(val))
          ) {
            numericVals.push(Number(val));
          } else {
            allNumeric = false;
          }
        }
      }

      const nullPct = total > 0 ? Math.round((nullCount / total) * 100) : 0;
      const distinctCount = new Set(nonNullStrings).size;
      const isNumeric = allNumeric && numericVals.length > 0;
      if (isNumeric) {
        const minVal = Math.min(...numericVals);
        const maxVal = Math.max(...numericVals);
        const avgVal =
          numericVals.reduce((acc, v) => acc + v, 0) / numericVals.length;
        const fmtNum = (n: number) =>
          Number.isInteger(n) ? String(n) : n.toFixed(2);
        columnStatsMap[col] = {
          total,
          nullCount,
          nullPct,
          distinctCount,
          isNumeric: true,
          min: fmtNum(minVal),
          max: fmtNum(maxVal),
          avg: fmtNum(avgVal),
        };
      } else {
        let topValue: string | undefined;
        let topCount = 0;
        for (const [k, cnt] of Object.entries(freq)) {
          if (cnt > topCount) {
            topCount = cnt;
            topValue = k.length > 18 ? `${k.slice(0, 18)}…` : k;
          }
        }
        columnStatsMap[col] = {
          total,
          nullCount,
          nullPct,
          distinctCount,
          isNumeric: false,
          topValue,
        };
      }
    }
  }

  const handleExportCsv = () => {
    if (typeof document === "undefined") return;
    if (rows.length === 0) return;
    const header = columns.map((c) => `"${csvCellText(c).replace(/"/g, '""')}"`).join(",");
    const body = rows
      .map((r) =>
        columns
          .map((c) => {
            const v = csvCellText(r[c]).replace(/"/g, '""');
            return `"${v}"`;
          })
          .join(","),
      )
      .join("\n");
    const blob = new Blob([`${header}\n${body}`], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `query_export_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleExportJson = () => {
    if (typeof document === "undefined") return;
    if (rows.length === 0) return;
    const orderedRows = rows.map((r) => {
      const nextRow: Record<string, unknown> = {};
      for (const c of columns) {
        if (c in r) nextRow[c] = r[c];
      }
      for (const [k, v] of Object.entries(r)) {
        if (!(k in nextRow)) nextRow[k] = v;
      }
      return nextRow;
    });
    const jsonContent = JSON.stringify(orderedRows, null, 2);
    const blob = new Blob([jsonContent], { type: "application/json;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `query_export_${Date.now()}.json`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const selectedCellFk = selectedCell
    ? resolveForeignKeyTarget(selectedCell.column, schema)
    : null;
  const selectedCellIsNull =
    selectedCell !== null &&
    (selectedCell.value === null || selectedCell.value === undefined);

  return (
    <div
      data-qb="results-table-root"
      className={cx(className, classNames?.results)}
      style={
        unstyled
          ? undefined
          : {
              display: "flex",
              flexDirection: "column",
              gap: "10px",
              height: "100%",
              fontFamily: "system-ui, -apple-system, sans-serif",
            }
      }
    >
      {/* Action Bar */}
      <div
        data-qb="results-toolbar"
        className={cx(classNames?.resultsHeader)}
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "8px",
              }
        }
      >
        <div
          data-qb="results-pagination"
          style={
            unstyled
              ? undefined
              : { display: "flex", alignItems: "center", gap: "10px" }
          }
        >
          <span style={unstyled ? undefined : { fontSize: "0.875rem", color: "var(--qb-color-text-secondary, #cbd5e1)" }}>
            Showing <strong>{filteredRows.length}</strong> of <strong>{results.count}</strong> rows
          </span>
          {durationMs !== undefined && (
            <span
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: "0.8rem",
                      color: "var(--qb-color-text-secondary, #94a3b8)",
                      background: "var(--qb-color-surface-active, rgba(255, 255, 255, 0.05))",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                      padding: "3px 8px",
                      borderRadius: "5px",
                      fontWeight: 500,
                      fontFamily: "var(--qb-font-mono, monospace)",
                    }
              }
            >
              {unstyled ? (
                `⚡ ${durationMs} ms`
              ) : (
                <>
                  <span style={SR_ONLY_STYLE}>{`⚡ ${durationMs} ms`}</span>
                  <span aria-hidden="true">{`${durationMs} ms`}</span>
                </>
              )}
            </span>
          )}
        </div>

        <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <select
            aria-label="Rows per page"
            data-qb="select-page-size"
            value={rowsPerPage}
            onChange={(e) => {
              setRowsPerPage(Number(e.target.value));
              setCurrentPage(1);
            }}
            style={unstyled ? undefined : SR_ONLY_STYLE}
          >
            <option value={10}>10 / page</option>
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
            {![10, 25, 50, 100].includes(rowsPerPage) && (
              <option value={rowsPerPage}>{rowsPerPage} / page</option>
            )}
          </select>
          {!unstyled && rows.length > 25 && (
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "2px",
                background: "var(--qb-color-surface, #10141f)",
                border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                borderRadius: "6px",
                padding: "3px",
              }}
              title="Rows per page"
            >
              {[10, 25, 50, 100].map((sz) => {
                const isSelected = rowsPerPage === sz;
                return (
                  <button
                    key={sz}
                    type="button"
                    onClick={() => {
                      setRowsPerPage(sz);
                      setCurrentPage(1);
                    }}
                    style={{
                      background: isSelected
                        ? "var(--qb-color-surface-active, rgba(255, 255, 255, 0.1))"
                        : "transparent",
                      color: isSelected
                        ? "var(--qb-color-text, #f8fafc)"
                        : "var(--qb-color-text-muted, #64748b)",
                      border: "none",
                      borderRadius: "4px",
                      padding: "3px 9px",
                      fontSize: "0.82rem",
                      fontWeight: isSelected ? 600 : 500,
                      cursor: "pointer",
                    }}
                  >
                    {sz}
                  </button>
                );
              })}
            </div>
          )}
          <input
            type="text"
            placeholder="Search results..."
            aria-label="Search query results"
            value={searchTerm}
            onChange={(e) => {
              setSearchTerm(e.target.value);
              setCurrentPage(1);
            }}
            style={
              unstyled
                ? undefined
                : rows.length === 0 && !searchTerm
                  ? SR_ONLY_STYLE
                  : {
                      background: "var(--qb-color-surface, #10141f)",
                      color: "var(--qb-color-text, #f8fafc)",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                      borderRadius: "6px",
                      padding: "6px 12px",
                      fontSize: "0.85rem",
                      width: "185px",
                      outline: "none",
                    }
            }
          />
          {columns.length > 0 && (
            <button
              type="button"
              onClick={() => setShowColumnStats((prev) => !prev)}
              aria-label="Toggle column statistics"
              aria-pressed={showColumnStats}
              data-qb="btn-toggle-column-stats"
              title="Toggle column micro-stats (Null %, Distinct count, Min/Max/Avg)"
              style={{
                background: showColumnStats
                  ? "rgba(56, 189, 248, 0.16)"
                  : "var(--qb-color-surface, #10141f)",
                color: showColumnStats
                  ? "#38bdf8"
                  : "var(--qb-color-text-secondary, #cbd5e1)",
                border: showColumnStats
                  ? "1px solid rgba(56, 189, 248, 0.45)"
                  : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                borderRadius: "6px",
                padding: "6px 11px",
                fontSize: "0.84rem",
                cursor: "pointer",
                fontWeight: showColumnStats ? 600 : 500,
                transition: "all 0.15s ease",
              }}
            >
              📊 Stats
            </button>
          )}
          {onPinToDashboard && (
            <button
              type="button"
              onClick={onPinToDashboard}
              aria-label="Pin results to BI Dashboard"
              data-qb="btn-pin-to-dashboard"
              title="Pin current query and results as a custom tile on the BI Dashboard"
              style={{
                background: "rgba(16, 185, 129, 0.15)",
                color: "#34d399",
                border: "1px solid rgba(16, 185, 129, 0.4)",
                borderRadius: "6px",
                padding: "6px 12px",
                fontSize: "0.84rem",
                cursor: "pointer",
                fontWeight: 600,
                transition: "all 0.15s ease",
              }}
            >
              📌 Pin to BI Dashboard
            </button>
          )}
          <button
            type="button"
            onClick={handleExportCsv}
            aria-label="Export results as CSV"
            data-qb="btn-export-csv"
            style={
              unstyled
                ? undefined
                : rows.length === 0
                  ? SR_ONLY_STYLE
                  : {
                      background: "var(--qb-color-surface, #10141f)",
                      color: "var(--qb-color-text-secondary, #cbd5e1)",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                      borderRadius: "6px",
                      padding: "6px 12px",
                      fontSize: "0.84rem",
                      cursor: "pointer",
                      fontWeight: 500,
                      transition: "all 0.15s ease",
                    }
            }
          >
            {unstyled ? (
              "📥 Export CSV"
            ) : (
              <>
                <span style={SR_ONLY_STYLE}>📥 Export CSV</span>
                <span aria-hidden="true">Export CSV</span>
              </>
            )}
          </button>
          <button
            type="button"
            onClick={handleExportJson}
            aria-label="Export results as JSON"
            data-qb="btn-export-json"
            style={
              unstyled
                ? undefined
                : rows.length === 0
                  ? SR_ONLY_STYLE
                  : {
                      background: "var(--qb-color-surface, #10141f)",
                      color: "var(--qb-color-text-secondary, #cbd5e1)",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                      borderRadius: "6px",
                      padding: "6px 12px",
                      fontSize: "0.84rem",
                      cursor: "pointer",
                      fontWeight: 500,
                      transition: "all 0.15s ease",
                    }
            }
          >
            {unstyled ? (
              "📥 Export JSON"
            ) : (
              <>
                <span style={SR_ONLY_STYLE}>📥 Export JSON</span>
                <span aria-hidden="true">Export JSON</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Interactive Cell Power Action Bar */}
      {selectedCell && (
        <div
          data-qb="results-cell-action-bar"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "8px",
            padding: "7px 12px",
            borderRadius: "7px",
            background: "rgba(56, 189, 248, 0.08)",
            border: "1px solid rgba(56, 189, 248, 0.3)",
            fontSize: "0.82rem",
            color: "var(--qb-color-text, #e2e8f0)",
          }}
        >
          <span
            data-qb="cell-action-summary"
            style={{ fontWeight: 600, fontFamily: "var(--qb-font-mono, monospace)" }}
          >
            {selectedCell.column} ={" "}
            {selectedCellIsNull ? "NULL" : String(selectedCell.value)}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
            <button
              type="button"
              data-qb="btn-cell-filter-eq"
              onClick={() => {
                if (onFilterByCell) {
                  onFilterByCell(
                    selectedCell.column,
                    selectedCellIsNull ? null : selectedCell.value,
                    selectedCellIsNull ? "IS NULL" : "=",
                  );
                } else if (!selectedCellIsNull) {
                  setSearchTerm(String(selectedCell.value));
                  setCurrentPage(1);
                }
                setSelectedCell(null);
              }}
              style={{
                background: "rgba(56, 189, 248, 0.18)",
                color: "#38bdf8",
                border: "1px solid rgba(56, 189, 248, 0.4)",
                borderRadius: "5px",
                padding: "3px 9px",
                fontSize: "0.78rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {selectedCellIsNull
                ? `Filter ${selectedCell.column} IS NULL`
                : `Filter = ${String(selectedCell.value)}`}
            </button>
            <button
              type="button"
              data-qb="btn-cell-filter-neq"
              onClick={() => {
                if (onFilterByCell) {
                  onFilterByCell(
                    selectedCell.column,
                    selectedCellIsNull ? null : selectedCell.value,
                    selectedCellIsNull ? "IS NOT NULL" : "!=",
                  );
                }
                setSelectedCell(null);
              }}
              style={{
                background: "rgba(248, 113, 113, 0.14)",
                color: "#fca5a5",
                border: "1px solid rgba(248, 113, 113, 0.35)",
                borderRadius: "5px",
                padding: "3px 9px",
                fontSize: "0.78rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {selectedCellIsNull
                ? `Filter ${selectedCell.column} IS NOT NULL`
                : `Filter != ${String(selectedCell.value)}`}
            </button>
            {selectedCellFk && !selectedCellIsNull && (
              <button
                type="button"
                data-qb="btn-cell-fk-drilldown"
                data-qb-fk-target={selectedCellFk.targetTable}
                onClick={() => {
                  onDrillDownForeignKey?.(
                    selectedCell.column,
                    selectedCell.value,
                    selectedCellFk.targetTable,
                    selectedCellFk.targetColumn,
                  );
                  setSelectedCell(null);
                }}
                style={{
                  background: "rgba(16, 185, 129, 0.16)",
                  color: "#34d399",
                  border: "1px solid rgba(16, 185, 129, 0.4)",
                  borderRadius: "5px",
                  padding: "3px 9px",
                  fontSize: "0.78rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                🔗 Drill down: {selectedCellFk.targetTable}.{selectedCellFk.targetColumn} ={" "}
                {String(selectedCell.value)}
              </button>
            )}
            <button
              type="button"
              data-qb="btn-cell-action-close"
              aria-label="Close cell actions"
              onClick={() => setSelectedCell(null)}
              style={{
                background: "transparent",
                color: "var(--qb-color-text-muted, #94a3b8)",
                border: "none",
                padding: "2px 6px",
                fontSize: "0.82rem",
                cursor: "pointer",
              }}
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Table container */}
      <div
        style={
          unstyled
            ? undefined
            : {
                overflowX: rows.length === 0 ? "hidden" : "auto",
                overflowY: "auto",
                maxHeight: "420px",
                border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                borderRadius: "var(--qb-radius-md, 8px)",
                background: "var(--qb-color-surface, #10141f)",
              }
        }
      >
        <table
          role="table"
          aria-label="Query results"
          data-qb="results-table"
          className={cx(classNames?.resultsTable)}
          style={
            unstyled
              ? undefined
              : {
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: "0.875rem",
                  color: "var(--qb-color-text, #e2e8f0)",
                  textAlign: "left",
                }
          }
        >
          <thead>
            <tr
              role="row"
              style={
                unstyled
                  ? undefined
                  : {
                      background: "var(--qb-color-surface-hover, #161b28)",
                      position: "sticky",
                      top: 0,
                      zIndex: 1,
                    }
              }
            >
              {columns.length > 0 && (
                <th
                  aria-hidden="true"
                  data-qb="results-th-index"
                  style={
                    unstyled
                      ? undefined
                      : {
                          width: "48px",
                          minWidth: "48px",
                          maxWidth: "52px",
                          padding: "10px 10px",
                          fontSize: "0.78rem",
                          fontWeight: 600,
                          textAlign: "right",
                          fontVariantNumeric: "tabular-nums",
                          borderBottom: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                          borderRight: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                          whiteSpace: "nowrap",
                          color: "var(--qb-color-text-muted, #64748b)",
                          userSelect: "none",
                        }
                  }
                >
                  #
                </th>
              )}
              {columns.map((c, colIdx) => {
                const isDragging = draggedColIdx === colIdx;
                const isDragOver = dragOverColIdx === colIdx && draggedColIdx !== colIdx;
                return (
                  <th
                    key={`${c}-${colIdx}`}
                    role="columnheader"
                    data-qb="results-th"
                    data-qb-column={c}
                    draggable={!unstyled}
                    onDragStart={(e) => {
                      setDraggedColIdx(colIdx);
                      e.dataTransfer?.setData?.("text/plain", String(colIdx));
                    }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      if (dragOverColIdx !== colIdx) setDragOverColIdx(colIdx);
                    }}
                    onDragLeave={() => {
                      if (dragOverColIdx === colIdx) setDragOverColIdx(null);
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      const rawIdx = e.dataTransfer?.getData?.("text/plain");
                      const resolvedFrom =
                        draggedColIdx ??
                        (rawIdx !== undefined && rawIdx !== "" && !Number.isNaN(Number(rawIdx))
                          ? Number(rawIdx)
                          : null);
                      handleDropColumn(resolvedFrom, colIdx);
                    }}
                    onDragEnd={() => {
                      setDraggedColIdx(null);
                      setDragOverColIdx(null);
                    }}
                    title={unstyled ? undefined : "Drag column header to reorder"}
                    style={
                      unstyled
                        ? undefined
                        : {
                            padding: "10px 14px",
                            fontSize: "0.84rem",
                            fontWeight: 600,
                            borderBottom: isDragOver
                              ? "2px solid #38bdf8"
                              : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                            background: isDragOver ? "rgba(56, 189, 248, 0.14)" : undefined,
                            whiteSpace: "nowrap",
                            color: "var(--qb-color-text-secondary, #cbd5e1)",
                            cursor: "grab",
                            opacity: isDragging ? 0.55 : 1,
                            userSelect: "none",
                          }
                    }
                  >
                    {unstyled ? (
                      c
                    ) : (
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                        <span
                          aria-hidden="true"
                          data-qb="col-drag-grip"
                          style={{ opacity: 0.45, fontSize: "0.75rem" }}
                        >
                          ⋮⋮
                        </span>
                        <span>{c}</span>
                      </span>
                    )}
                  </th>
                );
              })}
            </tr>
            {showColumnStats && columns.length > 0 && (
              <tr
                role="presentation"
                data-qb="results-stats-row"
                style={{
                  background: "rgba(15, 23, 42, 0.85)",
                  borderBottom: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                }}
              >
                <th
                  role="presentation"
                  aria-hidden="true"
                  style={{
                    padding: "6px 10px",
                    fontSize: "0.7rem",
                    fontWeight: 600,
                    textAlign: "right",
                    color: "#38bdf8",
                    borderRight: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                    whiteSpace: "nowrap",
                  }}
                >
                  Σ
                </th>
                {columns.map((c) => {
                  const st = columnStatsMap[c];
                  return (
                    <th
                      key={`stats-${c}`}
                      role="presentation"
                      data-qb="column-stat-cell"
                      data-qb-column={c}
                      style={{
                        padding: "6px 14px",
                        fontSize: "0.72rem",
                        fontWeight: 500,
                        color: "var(--qb-color-text-muted, #94a3b8)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {st && (
                        <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                          <span>
                            Distinct: <strong>{st.distinctCount}</strong> • Null:{" "}
                            <strong>{st.nullPct}%</strong>
                          </span>
                          <span>
                            {st.isNumeric
                              ? `Min: ${st.min} · Max: ${st.max} · Avg: ${st.avg}`
                              : st.topValue !== undefined
                                ? `Top: ${st.topValue}`
                                : "All null"}
                          </span>
                        </div>
                      )}
                    </th>
                  );
                })}
              </tr>
            )}
          </thead>
          <tbody>
            {displayedRows.map((r, idx) => (
              <tr
                key={idx}
                role="row"
                className={cx(classNames?.resultsRow)}
                style={
                  unstyled
                    ? undefined
                    : {
                        background:
                          idx % 2 === 0
                            ? "var(--qb-color-background, rgba(15, 23, 42, 0.4))"
                            : "var(--qb-color-surface, rgba(30, 41, 59, 0.3))",
                        borderBottom: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.05))",
                      }
                }
              >
                {columns.length > 0 && (
                  <td
                    aria-hidden="true"
                    data-qb="results-td-index"
                    style={
                      unstyled
                        ? undefined
                        : {
                            width: "48px",
                            minWidth: "48px",
                            maxWidth: "52px",
                            padding: "10px 10px",
                            fontSize: "0.8rem",
                            lineHeight: 1.4,
                            textAlign: "right",
                            fontVariantNumeric: "tabular-nums",
                            fontFamily: "var(--qb-font-mono, monospace)",
                            color: "var(--qb-color-text-muted, #64748b)",
                            borderRight: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                            whiteSpace: "nowrap",
                            userSelect: "none",
                          }
                    }
                  >
                    {(effectivePage - 1) * rowsPerPage + idx + 1}
                  </td>
                )}
                {columns.map((c, colIdx) => {
                  const shortCol = c.includes(".") ? c.slice(c.lastIndexOf(".") + 1) : c;
                  const cellRenderer =
                    effectiveCellRenderers?.[c] ?? effectiveCellRenderers?.[shortCol];
                  const fkInfo = resolveForeignKeyTarget(c, schema);
                  const hasFkValue = Boolean(fkInfo && r[c] !== null && r[c] !== undefined);
                  const isCellSelected =
                    selectedCell?.rowIdx === idx && selectedCell?.column === c;
                  return (
                    <td
                      key={`${c}-${colIdx}`}
                      role="cell"
                      data-qb="results-td"
                      data-qb-column={c}
                      data-qb-fk-target={fkInfo ? fkInfo.targetTable : undefined}
                      className={cx(classNames?.resultsCell)}
                      onClick={() => {
                        setSelectedCell((prev) =>
                          prev && prev.rowIdx === idx && prev.column === c
                            ? null
                            : { rowIdx: idx, column: c, value: r[c] },
                        );
                      }}
                      title={
                        unstyled
                          ? undefined
                          : hasFkValue
                            ? `Click to filter or drill down to ${fkInfo!.targetTable}.${fkInfo!.targetColumn} = ${String(r[c])}`
                            : "Click cell to filter query by this value"
                      }
                      style={
                        unstyled
                          ? undefined
                          : {
                              padding: "10px 14px",
                              fontSize: "0.875rem",
                              lineHeight: 1.4,
                              whiteSpace: "nowrap",
                              maxWidth: "280px",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              cursor: "pointer",
                              background: isCellSelected
                                ? "rgba(56, 189, 248, 0.14)"
                                : undefined,
                              textDecoration: hasFkValue
                                ? "underline dotted rgba(52, 211, 153, 0.65)"
                                : undefined,
                            }
                      }
                    >
                      {cellRenderer ? (
                        cellRenderer(r[c], r, c)
                      ) : r[c] !== null && r[c] !== undefined ? (
                        String(r[c])
                      ) : (
                        <span style={unstyled ? undefined : { color: "var(--qb-color-text-muted, #64748b)" }}>null</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination Controls */}
      {totalPages > 1 && (
        <div
          data-qb="results-pagination-controls"
          style={
            unstyled
              ? undefined
              : {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "6px 2px",
                  fontSize: "0.85rem",
                  color: "var(--qb-color-text-muted, #94a3b8)",
                }
          }
        >
          <span>
            Page <strong>{effectivePage}</strong> of <strong>{totalPages}</strong>
          </span>
          <div style={unstyled ? undefined : { display: "flex", gap: "8px" }}>
            <button
              type="button"
              data-qb="btn-prev-page"
              aria-label="Previous page"
              disabled={effectivePage <= 1}
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              style={
                unstyled
                  ? undefined
                  : {
                      background:
                        effectivePage <= 1
                          ? "var(--qb-color-surface, rgba(255, 255, 255, 0.05))"
                          : "var(--qb-color-surface-hover, rgba(255, 255, 255, 0.1))",
                      color: effectivePage <= 1 ? "var(--qb-color-text-muted, #64748b)" : "var(--qb-color-text, #f8fafc)",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.15))",
                      borderRadius: "var(--qb-radius-sm, 6px)",
                      padding: "5px 12px",
                      cursor: effectivePage <= 1 ? "not-allowed" : "pointer",
                      fontSize: "0.84rem",
                      transition: "all 0.15s ease",
                    }
              }
            >
              Previous
            </button>
            <button
              type="button"
              data-qb="btn-next-page"
              aria-label="Next page"
              disabled={effectivePage >= totalPages}
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              style={
                unstyled
                  ? undefined
                  : {
                      background:
                        effectivePage >= totalPages
                          ? "var(--qb-color-surface, rgba(255, 255, 255, 0.05))"
                          : "var(--qb-color-surface-hover, rgba(255, 255, 255, 0.1))",
                      color: effectivePage >= totalPages ? "var(--qb-color-text-muted, #64748b)" : "var(--qb-color-text, #f8fafc)",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.15))",
                      borderRadius: "var(--qb-radius-sm, 6px)",
                      padding: "5px 12px",
                      cursor: effectivePage >= totalPages ? "not-allowed" : "pointer",
                      fontSize: "0.84rem",
                      transition: "all 0.15s ease",
                    }
              }
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
