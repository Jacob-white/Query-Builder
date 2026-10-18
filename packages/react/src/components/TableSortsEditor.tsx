import React from "react";
import type {
  VisualSort,
  TableMeta,
  VisualColumnSelect,
  QueryBuilderClassNames,
} from "../types";
import { cx } from "../utils/classNames";

export interface TableSortsEditorProps {
  sorts: VisualSort[];
  activeTables: TableMeta[];
  selectedColumns?: Record<string, VisualColumnSelect>;
  onChange: (sorts: VisualSort[]) => void;
  unstyled?: boolean;
  className?: string;
  classNames?: QueryBuilderClassNames;
}

export const TableSortsEditor: React.FC<TableSortsEditorProps> = ({
  sorts,
  activeTables,
  selectedColumns,
  onChange,
  unstyled = false,
  className,
  classNames,
}) => {
  const baseColumns = activeTables.flatMap((tbl) =>
    tbl.columns.map((c) => ({
      table: tbl.name,
      column: c.name,
      label: `${tbl.name}.${c.name}`,
    })),
  );

  const aliasOptions: { table: string; column: string; label: string }[] = [];
  if (selectedColumns) {
    Object.values(selectedColumns).forEach((item) => {
      if (item.alias) {
        const aliasLabel = item.alias;
        if (
          !baseColumns.some((c) => c.label === aliasLabel || c.column === aliasLabel) &&
          !aliasOptions.some((a) => a.label === aliasLabel)
        ) {
          aliasOptions.push({
            table: "",
            column: item.alias,
            label: aliasLabel,
          });
        }
      }
    });
  }

  const allColumns = [...baseColumns, ...aliasOptions];

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
      data-qb="sorts-editor"
      className={cx(className, classNames?.sorts)}
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
        data-qb="sorts-header"
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
          className={cx(classNames?.title)}
          style={
            unstyled
              ? undefined
              : { fontSize: "0.85rem", fontWeight: 600, color: "#94a3b8" }
          }
        >
          ↕️ Order & Sorts ({sorts.length})
        </span>
        <button
          type="button"
          aria-label="Add sort"
          onClick={handleAddSort}
          data-qb="btn-add-sort"
          className={cx(classNames?.sortAddButton)}
          style={
            unstyled
              ? undefined
              : {
                  background: "rgba(168, 85, 247, 0.2)",
                  color: "#c084fc",
                  border: "1px solid rgba(168, 85, 247, 0.4)",
                  borderRadius: "6px",
                  padding: "4px 10px",
                  fontSize: "0.75rem",
                  cursor: "pointer",
                  fontWeight: 600,
                }
          }
        >
          + Add Sort
        </button>
      </div>

      {sorts.length === 0 ? (
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
          Default database ordering. Add sort columns to order results.
        </div>
      ) : (
        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", flexDirection: "column", gap: "8px" }
          }
        >
          {sorts.map((s) => {
            const resolvedTable =
              s.tablePrefix ||
              activeTables.find((t) => t.columns.some((c) => c.name === s.column))?.name ||
              (aliasOptions.some((a) => a.column === s.column)
                ? ""
                : activeTables[0]?.name || "");
            const selectValue = resolvedTable ? `${resolvedTable}.${s.column}` : s.column;

            return (
              <div
                key={s.id}
                data-qb="sort-row"
                data-qb-sort-id={s.id}
                className={cx(classNames?.sortItem)}
                style={
                  unstyled
                    ? undefined
                    : {
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        background: "rgba(30, 41, 59, 0.5)",
                        padding: "8px 10px",
                        borderRadius: "6px",
                      }
                }
              >
                <select
                  value={selectValue}
                  aria-label="Sort column"
                  data-qb="sort-column"
                  onChange={(e) => {
                    const val = e.target.value;
                    const lastDot = val.lastIndexOf(".");
                    if (lastDot !== -1) {
                      const t = val.substring(0, lastDot);
                      const c = val.substring(lastDot + 1);
                      handleUpdate(s.id, { tablePrefix: t, column: c });
                    } else {
                      handleUpdate(s.id, { tablePrefix: "", column: val });
                    }
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
                          flex: 1,
                        }
                  }
                >
                  {allColumns.map((col) => (
                    <option key={col.label} value={col.label}>
                      {col.label}
                    </option>
                  ))}
                  {!allColumns.some((col) => col.label === selectValue) && selectValue && (
                    <option value={selectValue}>{selectValue}</option>
                  )}
                </select>

                <button
                  type="button"
                  aria-label="Toggle sort direction"
                  data-qb="sort-direction"
                  onClick={() =>
                    handleUpdate(s.id, {
                      direction: s.direction === "ASC" ? "DESC" : "ASC",
                    })
                  }
                  style={
                    unstyled
                      ? undefined
                      : {
                          background:
                            s.direction === "ASC"
                              ? "rgba(34, 197, 94, 0.2)"
                              : "rgba(239, 68, 68, 0.2)",
                          color: s.direction === "ASC" ? "#4ade80" : "#f87171",
                          border: "1px solid #475569",
                          borderRadius: "4px",
                          padding: "4px 10px",
                          fontSize: "0.75rem",
                          fontWeight: 700,
                          cursor: "pointer",
                        }
                  }
                >
                  {s.direction} {s.direction === "ASC" ? "▲" : "▼"}
                </button>

                <button
                  type="button"
                  aria-label="Remove sort"
                  onClick={() => handleRemove(s.id)}
                  data-qb="btn-remove-sort"
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
                  title="Remove sort"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
