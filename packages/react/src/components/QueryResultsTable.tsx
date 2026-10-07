import React, { useState } from "react";
import type { QueryResultData, QueryBuilderClassNames } from "../types";
import { cx } from "../utils/classNames";

export interface QueryResultsTableProps {
  results: QueryResultData | null;
  isLoading?: boolean;
  unstyled?: boolean;
  cellRenderers?: Record<string, (value: any, row: any, column: string) => React.ReactNode>;
  pageSize?: number;
  className?: string;
  classNames?: QueryBuilderClassNames;
}

export const QueryResultsTable: React.FC<QueryResultsTableProps> = ({
  results,
  isLoading,
  unstyled = false,
  cellRenderers,
  pageSize = 100,
  className,
  classNames,
}) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [rowsPerPage, setRowsPerPage] = useState(pageSize);

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

  const columns = results.columns || [];
  const rows = results.rows || [];

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

  const handleExportCsv = () => {
    if (typeof document === "undefined") return;
    if (rows.length === 0) return;
    const header = columns.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",");
    const body = rows
      .map((r) =>
        columns
          .map((c) => {
            const v = String(r[c] ?? "").replace(/"/g, '""');
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
    const jsonContent = JSON.stringify(rows, null, 2);
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
          <span style={unstyled ? undefined : { fontSize: "0.82rem", color: "#94a3b8" }}>
            Showing <strong>{filteredRows.length}</strong> of <strong>{results.count}</strong> rows
          </span>
          {results.latency_ms !== undefined && (
            <span
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: "0.75rem",
                      color: "#10b981",
                      background: "rgba(16, 185, 129, 0.1)",
                      padding: "2px 8px",
                      borderRadius: "12px",
                      fontWeight: 600,
                    }
              }
            >
              ⚡ {results.latency_ms} ms
            </span>
          )}
        </div>

        <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px" }}>
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
                : {
                    background: "#1e293b",
                    color: "#f8fafc",
                    border: "1px solid #475569",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    fontSize: "0.78rem",
                    width: "160px",
                  }
            }
          />
          <button
            type="button"
            onClick={handleExportCsv}
            aria-label="Export results as CSV"
            data-qb="btn-export-csv"
            style={
              unstyled
                ? undefined
                : {
                    background: "rgba(59, 130, 246, 0.15)",
                    color: "#60a5fa",
                    border: "1px solid rgba(59, 130, 246, 0.3)",
                    borderRadius: "6px",
                    padding: "4px 12px",
                    fontSize: "0.78rem",
                    cursor: "pointer",
                    fontWeight: 600,
                  }
            }
          >
            📥 Export CSV
          </button>
          <button
            type="button"
            onClick={handleExportJson}
            aria-label="Export results as JSON"
            data-qb="btn-export-json"
            style={
              unstyled
                ? undefined
                : {
                    background: "rgba(16, 185, 129, 0.15)",
                    color: "#34d399",
                    border: "1px solid rgba(16, 185, 129, 0.3)",
                    borderRadius: "6px",
                    padding: "4px 12px",
                    fontSize: "0.78rem",
                    cursor: "pointer",
                    fontWeight: 600,
                  }
            }
          >
            📥 Export JSON
          </button>
        </div>
      </div>

      {/* Table container */}
      <div
        style={
          unstyled
            ? undefined
            : {
                overflowX: "auto",
                overflowY: "auto",
                maxHeight: "360px",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "8px",
                background: "rgba(15, 23, 42, 0.6)",
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
                  fontSize: "0.78rem",
                  color: "#e2e8f0",
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
                      background: "rgba(30, 41, 59, 0.9)",
                      position: "sticky",
                      top: 0,
                    }
              }
            >
              {columns.map((c) => (
                <th
                  key={c}
                  role="columnheader"
                  data-qb="results-th"
                  style={
                    unstyled
                      ? undefined
                      : {
                          padding: "8px 12px",
                          fontWeight: 600,
                          borderBottom: "1px solid #334155",
                          whiteSpace: "nowrap",
                          color: "#93c5fd",
                        }
                  }
                >
                  {c}
                </th>
              ))}
            </tr>
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
                            ? "rgba(15, 23, 42, 0.4)"
                            : "rgba(30, 41, 59, 0.3)",
                        borderBottom: "1px solid rgba(255, 255, 255, 0.04)",
                      }
                }
              >
                {columns.map((c) => (
                  <td
                    key={c}
                    role="cell"
                    data-qb="results-td"
                    className={cx(classNames?.resultsCell)}
                    style={
                      unstyled
                        ? undefined
                        : {
                            padding: "6px 12px",
                            whiteSpace: "nowrap",
                            maxWidth: "240px",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }
                    }
                  >
                    {cellRenderers && cellRenderers[c] ? (
                      cellRenderers[c](r[c], r, c)
                    ) : r[c] !== null && r[c] !== undefined ? (
                      String(r[c])
                    ) : (
                      <span style={unstyled ? undefined : { color: "#64748b" }}>null</span>
                    )}
                  </td>
                ))}
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
                  fontSize: "0.8rem",
                  color: "#94a3b8",
                }
          }
        >
          <span>
            Page <strong>{effectivePage}</strong> of <strong>{totalPages}</strong>
          </span>
          <div style={unstyled ? undefined : { display: "flex", gap: "6px" }}>
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
                      background: effectivePage <= 1 ? "rgba(255, 255, 255, 0.05)" : "rgba(255, 255, 255, 0.1)",
                      color: effectivePage <= 1 ? "#64748b" : "#f8fafc",
                      border: "1px solid rgba(255, 255, 255, 0.15)",
                      borderRadius: "4px",
                      padding: "3px 10px",
                      cursor: effectivePage <= 1 ? "not-allowed" : "pointer",
                      fontSize: "0.78rem",
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
                      background: effectivePage >= totalPages ? "rgba(255, 255, 255, 0.05)" : "rgba(255, 255, 255, 0.1)",
                      color: effectivePage >= totalPages ? "#64748b" : "#f8fafc",
                      border: "1px solid rgba(255, 255, 255, 0.15)",
                      borderRadius: "4px",
                      padding: "3px 10px",
                      cursor: effectivePage >= totalPages ? "not-allowed" : "pointer",
                      fontSize: "0.78rem",
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
