import React from "react";
import type { VisualFilter, TableMeta } from "../types";

export interface TableFiltersEditorProps {
  filters: VisualFilter[];
  activeTables: TableMeta[];
  onChange: (filters: VisualFilter[]) => void;
  unstyled?: boolean;
}

export const TableFiltersEditor: React.FC<TableFiltersEditorProps> = ({
  filters,
  activeTables,
  onChange,
  unstyled = false,
}) => {
  const allColumns = activeTables.flatMap((tbl) =>
    tbl.columns.map((c) => ({
      table: tbl.name,
      column: c.name,
      label: `${tbl.name}.${c.name}`,
    })),
  );

  const handleAddFilter = () => {
    const first = allColumns[0];
    const newFilter: VisualFilter = {
      id: `flt-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
      combiner: "AND",
      tablePrefix: first?.table || "",
      column: first?.column || "",
      operator: "=",
      value: "",
    };
    onChange([...filters, newFilter]);
  };

  const handleUpdate = (id: string, updates: Partial<VisualFilter>) => {
    onChange(
      filters.map((f) => (f.id === id ? { ...f, ...updates } : f)),
    );
  };

  const handleRemove = (id: string) => {
    onChange(filters.filter((f) => f.id !== id));
  };

  return (
    <div
      data-qb="filters-editor"
      style={
        unstyled
          ? undefined
          : {
              background: "rgba(15, 23, 42, 0.6)",
              borderRadius: "8px",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              padding: "12px",
              display: "flex",
              flexDirection: "column",
              gap: "10px",
            }
      }
    >
      <div
        data-qb="filters-header"
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }
        }
      >
        <span
          style={
            unstyled
              ? undefined
              : { fontSize: "0.85rem", fontWeight: 600, color: "#94a3b8" }
          }
        >
          ⚡ Filter Conditions ({filters.length})
        </span>
        <button
          type="button"
          onClick={handleAddFilter}
          data-qb="btn-add-filter"
          style={
            unstyled
              ? undefined
              : {
                  background: "rgba(59, 130, 246, 0.2)",
                  color: "#60a5fa",
                  border: "1px solid rgba(59, 130, 246, 0.4)",
                  borderRadius: "6px",
                  padding: "4px 10px",
                  fontSize: "0.75rem",
                  cursor: "pointer",
                  fontWeight: 600,
                }
          }
        >
          + Add Filter
        </button>
      </div>

      {filters.length === 0 ? (
        <div
          style={
            unstyled
              ? undefined
              : {
                  fontSize: "0.78rem",
                  color: "#64748b",
                  fontStyle: "italic",
                  textAlign: "center",
                  padding: "12px 0",
                }
          }
        >
          No filters applied. Results will include all rows.
        </div>
      ) : (
        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", flexDirection: "column", gap: "8px" }
          }
        >
          {filters.map((f, idx) => (
            <div
              key={f.id}
              data-qb="filter-row"
              data-qb-filter-id={f.id}
              style={
                unstyled
                  ? undefined
                  : {
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      flexWrap: "wrap",
                      background: "rgba(30, 41, 59, 0.5)",
                      padding: "8px 10px",
                      borderRadius: "6px",
                    }
              }
            >
              {idx > 0 && (
                <span
                  data-qb="filter-combiner"
                  style={
                    unstyled
                      ? undefined
                      : {
                          fontSize: "0.7rem",
                          fontWeight: 700,
                          color: "#f59e0b",
                          minWidth: "32px",
                        }
                  }
                >
                  AND
                </span>
              )}

              {/* Column selector */}
              <select
                value={`${f.tablePrefix}.${f.column}`}
                data-qb="filter-column"
                onChange={(e) => {
                  const [t, c] = e.target.value.split(".");
                  handleUpdate(f.id, { tablePrefix: t, column: c });
                }}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "#1e293b",
                        color: "#f8fafc",
                        border: "1px solid #475569",
                        borderRadius: "4px",
                        padding: "4px 8px",
                        fontSize: "0.78rem",
                      }
                }
              >
                {allColumns.map((col) => (
                  <option key={col.label} value={col.label}>
                    {col.label}
                  </option>
                ))}
              </select>

              {/* Operator selector */}
              <select
                value={f.operator}
                data-qb="filter-operator"
                onChange={(e) =>
                  handleUpdate(f.id, {
                    operator: e.target.value as VisualFilter["operator"],
                  })
                }
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "#1e293b",
                        color: "#f8fafc",
                        border: "1px solid #475569",
                        borderRadius: "4px",
                        padding: "4px 8px",
                        fontSize: "0.78rem",
                      }
                }
              >
                <option value="=">=</option>
                <option value="!=">!=</option>
                <option value=">">&gt;</option>
                <option value=">=">&gt;=</option>
                <option value="<">&lt;</option>
                <option value="<=">&lt;=</option>
                <option value="CONTAINS">CONTAINS</option>
                <option value="STARTS_WITH">STARTS WITH</option>
                <option value="ENDS_WITH">ENDS WITH</option>
                <option value="IN">IN</option>
                <option value="NOT IN">NOT IN</option>
                <option value="BETWEEN">BETWEEN</option>
                <option value="IS NULL">IS NULL</option>
                <option value="IS NOT NULL">IS NOT NULL</option>
              </select>

              {/* Value Input */}
              {f.operator !== "IS NULL" && f.operator !== "IS NOT NULL" && (
                <input
                  type="text"
                  placeholder={f.operator === "BETWEEN" ? "10 AND 50" : "Value..."}
                  value={String(f.value ?? "")}
                  data-qb="filter-value"
                  onChange={(e) => handleUpdate(f.id, { value: e.target.value })}
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "#1e293b",
                          color: "#f8fafc",
                          border: "1px solid #475569",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          fontSize: "0.78rem",
                          flex: 1,
                          minWidth: "120px",
                        }
                  }
                />
              )}

              <button
                type="button"
                onClick={() => handleRemove(f.id)}
                data-qb="btn-remove-filter"
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "transparent",
                        border: "none",
                        color: "#ef4444",
                        cursor: "pointer",
                        fontSize: "0.9rem",
                        padding: "2px 6px",
                      }
                }
                title="Remove condition"
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
