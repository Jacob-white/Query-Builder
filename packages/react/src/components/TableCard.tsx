import React from "react";
import type { TableMeta, VisualColumnSelect } from "../types";

export interface TableCardProps {
  table: TableMeta;
  isSelected?: boolean;
  selectedColumns: Record<string, VisualColumnSelect>;
  onToggleColumn: (colName: string) => void;
  onRemoveTable?: () => void;
  onAddJoin?: () => void;
}

export const TableCard: React.FC<TableCardProps> = ({
  table,
  isSelected,
  selectedColumns,
  onToggleColumn,
  onRemoveTable,
  onAddJoin,
}) => {
  return (
    <div
      style={{
        background: "rgba(30, 41, 59, 0.8)",
        backdropFilter: "blur(8px)",
        borderRadius: "10px",
        border: isSelected ? "1.5px solid #3b82f6" : "1px solid rgba(255, 255, 255, 0.1)",
        boxShadow: "0 8px 24px rgba(0, 0, 0, 0.3)",
        overflow: "hidden",
        width: "280px",
        display: "flex",
        flexDirection: "column",
        color: "#f8fafc",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "10px 14px",
          background: "rgba(15, 23, 42, 0.9)",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <span style={{ fontSize: "1rem" }}>🗄️</span>
          <span style={{ fontWeight: 600, fontSize: "0.88rem" }} title={table.name}>
            {table.name}
          </span>
        </div>
        <div style={{ display: "flex", gap: "4px" }}>
          {onAddJoin && (
            <button
              type="button"
              onClick={onAddJoin}
              style={{
                background: "transparent",
                border: "none",
                color: "#60a5fa",
                cursor: "pointer",
                padding: "2px 6px",
                borderRadius: "4px",
                fontSize: "0.75rem",
              }}
              title="Add Join to this table"
            >
              🔗
            </button>
          )}
          {onRemoveTable && (
            <button
              type="button"
              onClick={onRemoveTable}
              style={{
                background: "transparent",
                border: "none",
                color: "#ef4444",
                cursor: "pointer",
                padding: "2px 6px",
                borderRadius: "4px",
                fontSize: "0.85rem",
              }}
              title="Remove table"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Columns list */}
      <div
        style={{
          maxHeight: "260px",
          overflowY: "auto",
          padding: "6px 0",
        }}
      >
        {table.columns.map((col) => {
          const key = `${table.name}.${col.name}`;
          const isColChecked = Boolean(selectedColumns[key]);

          return (
            <div
              key={col.name}
              onClick={() => onToggleColumn(col.name)}
              style={{
                padding: "6px 14px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                cursor: "pointer",
                background: isColChecked ? "rgba(59, 130, 246, 0.12)" : "transparent",
                transition: "background 0.15s ease",
                fontSize: "0.8rem",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <input
                  type="checkbox"
                  checked={isColChecked}
                  onChange={() => onToggleColumn(col.name)}
                  style={{ cursor: "pointer" }}
                />
                <span
                  style={{
                    color: isColChecked ? "#93c5fd" : "#cbd5e1",
                    fontWeight: isColChecked ? 600 : 400,
                  }}
                >
                  {col.name}
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                {col.is_primary && (
                  <span
                    style={{
                      background: "rgba(245, 158, 11, 0.2)",
                      color: "#fbbf24",
                      fontSize: "0.65rem",
                      fontWeight: 700,
                      padding: "1px 4px",
                      borderRadius: "4px",
                    }}
                  >
                    PK
                  </span>
                )}
                <span style={{ color: "#64748b", fontSize: "0.7rem" }}>
                  {col.data_type}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
