import React, { useState } from "react";
import type { QueryResultData } from "../types";

export interface QueryResultsTableProps {
  results: QueryResultData | null;
  isLoading?: boolean;
}

export const QueryResultsTable: React.FC<QueryResultsTableProps> = ({
  results,
  isLoading,
}) => {
  const [searchTerm, setSearchTerm] = useState("");

  if (isLoading) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "200px",
          color: "#94a3b8",
          fontSize: "0.9rem",
        }}
      >
        <span>⏳ Executing read-only query...</span>
      </div>
    );
  }

  if (!results) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "180px",
          color: "#64748b",
          fontStyle: "italic",
          fontSize: "0.85rem",
        }}
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

  const handleExportCsv = () => {
    if (rows.length === 0) return;
    const header = columns.join(",");
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
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "10px",
        height: "100%",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Action Bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "0.82rem", color: "#94a3b8" }}>
            Showing <strong>{filteredRows.length}</strong> of <strong>{results.count}</strong> rows
          </span>
          {results.latency_ms !== undefined && (
            <span
              style={{
                fontSize: "0.75rem",
                color: "#10b981",
                background: "rgba(16, 185, 129, 0.1)",
                padding: "2px 8px",
                borderRadius: "12px",
                fontWeight: 600,
              }}
            >
              ⚡ {results.latency_ms} ms
            </span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <input
            type="text"
            placeholder="Search results..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              background: "#1e293b",
              color: "#f8fafc",
              border: "1px solid #475569",
              borderRadius: "6px",
              padding: "4px 10px",
              fontSize: "0.78rem",
              width: "160px",
            }}
          />
          <button
            type="button"
            onClick={handleExportCsv}
            style={{
              background: "rgba(59, 130, 246, 0.15)",
              color: "#60a5fa",
              border: "1px solid rgba(59, 130, 246, 0.3)",
              borderRadius: "6px",
              padding: "4px 12px",
              fontSize: "0.78rem",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            📥 Export CSV
          </button>
        </div>
      </div>

      {/* Table container */}
      <div
        style={{
          overflowX: "auto",
          overflowY: "auto",
          maxHeight: "360px",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          borderRadius: "8px",
          background: "rgba(15, 23, 42, 0.6)",
        }}
      >
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: "0.78rem",
            color: "#e2e8f0",
            textAlign: "left",
          }}
        >
          <thead>
            <tr style={{ background: "rgba(30, 41, 59, 0.9)", position: "sticky", top: 0 }}>
              {columns.map((c) => (
                <th
                  key={c}
                  style={{
                    padding: "8px 12px",
                    fontWeight: 600,
                    borderBottom: "1px solid #334155",
                    whiteSpace: "nowrap",
                    color: "#93c5fd",
                  }}
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((r, idx) => (
              <tr
                key={idx}
                style={{
                  background: idx % 2 === 0 ? "rgba(15, 23, 42, 0.4)" : "rgba(30, 41, 59, 0.3)",
                  borderBottom: "1px solid rgba(255, 255, 255, 0.04)",
                }}
              >
                {columns.map((c) => (
                  <td
                    key={c}
                    style={{
                      padding: "6px 12px",
                      whiteSpace: "nowrap",
                      maxWidth: "240px",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {r[c] !== null && r[c] !== undefined ? String(r[c]) : <span style={{ color: "#64748b" }}>null</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
