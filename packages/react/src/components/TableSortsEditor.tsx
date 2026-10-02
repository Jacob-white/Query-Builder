import React from "react";
import type { VisualSort, TableMeta } from "../types";

export interface TableSortsEditorProps {
  sorts: VisualSort[];
  activeTables: TableMeta[];
  onChange: (sorts: VisualSort[]) => void;
}

export const TableSortsEditor: React.FC<TableSortsEditorProps> = ({
  sorts,
  activeTables,
  onChange,
}) => {
  const allColumns = activeTables.flatMap((tbl) =>
    tbl.columns.map((c) => ({
      table: tbl.name,
      column: c.name,
      label: `${tbl.name}.${c.name}`,
    })),
  );

  const handleAddSort = () => {
    const first = allColumns[0];
    const newSort: VisualSort = {
      id: `sort-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
      tablePrefix: first?.table || "",
      column: first?.column || "",
      direction: "ASC",
    };
    onChange([...sorts, newSort]);
  };

  const handleUpdate = (id: string, updates: Partial<VisualSort>) => {
    onChange(sorts.map((s) => (s.id === id ? { ...s, ...updates } : s)));
  };

  const handleRemove = (id: string) => {
    onChange(sorts.filter((s) => s.id !== id));
  };

  return (
    <div
      style={{
        background: "rgba(15, 23, 42, 0.6)",
        borderRadius: "8px",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        padding: "12px",
        display: "flex",
        flexDirection: "column",
        gap: "10px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "#94a3b8" }}>
          ↕️ Order & Sorts ({sorts.length})
        </span>
        <button
          type="button"
          onClick={handleAddSort}
          style={{
            background: "rgba(168, 85, 247, 0.2)",
            color: "#c084fc",
            border: "1px solid rgba(168, 85, 247, 0.4)",
            borderRadius: "6px",
            padding: "4px 10px",
            fontSize: "0.75rem",
            cursor: "pointer",
            fontWeight: 600,
          }}
        >
          + Add Sort
        </button>
      </div>

      {sorts.length === 0 ? (
        <div style={{ fontSize: "0.78rem", color: "#64748b", fontStyle: "italic", textAlign: "center", padding: "12px 0" }}>
          Default database ordering. Add sort columns to order results.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {sorts.map((s) => (
            <div
              key={s.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                background: "rgba(30, 41, 59, 0.5)",
                padding: "8px 10px",
                borderRadius: "6px",
              }}
            >
              <select
                value={`${s.tablePrefix}.${s.column}`}
                onChange={(e) => {
                  const [t, c] = e.target.value.split(".");
                  handleUpdate(s.id, { tablePrefix: t, column: c });
                }}
                style={{
                  background: "#1e293b",
                  color: "#f8fafc",
                  border: "1px solid #475569",
                  borderRadius: "4px",
                  padding: "4px 8px",
                  fontSize: "0.78rem",
                  flex: 1,
                }}
              >
                {allColumns.map((col) => (
                  <option key={col.label} value={col.label}>
                    {col.label}
                  </option>
                ))}
              </select>

              <button
                type="button"
                onClick={() =>
                  handleUpdate(s.id, {
                    direction: s.direction === "ASC" ? "DESC" : "ASC",
                  })
                }
                style={{
                  background: s.direction === "ASC" ? "rgba(34, 197, 94, 0.2)" : "rgba(239, 68, 68, 0.2)",
                  color: s.direction === "ASC" ? "#4ade80" : "#f87171",
                  border: "1px solid #475569",
                  borderRadius: "4px",
                  padding: "4px 10px",
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                {s.direction} {s.direction === "ASC" ? "▲" : "▼"}
              </button>

              <button
                type="button"
                onClick={() => handleRemove(s.id)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#ef4444",
                  cursor: "pointer",
                  fontSize: "0.9rem",
                  padding: "2px 6px",
                }}
                title="Remove sort"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
