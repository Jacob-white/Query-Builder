import React from "react";
import type {
  VisualFilter,
  TableMeta,
  CustomFilterOperator,
  CustomFieldRenderer,
  QueryBuilderClassNames,
} from "../types";
import { useQueryBuilderContext } from "../theme/QueryBuilderProvider";
import { cx } from "../utils/classNames";

export interface TableFiltersEditorProps {
  filters: VisualFilter[];
  activeTables: TableMeta[];
  onChange: (filters: VisualFilter[]) => void;
  unstyled?: boolean;
  customOperators?: Record<string, CustomFilterOperator>;
  fieldRenderers?: Record<string, CustomFieldRenderer>;
  className?: string;
  classNames?: QueryBuilderClassNames;
}

export const TableFiltersEditor: React.FC<TableFiltersEditorProps> = ({
  filters,
  activeTables,
  onChange,
  unstyled = false,
  customOperators,
  fieldRenderers,
  className,
  classNames,
}) => {
  const ctx = useQueryBuilderContext();
  const effectiveCustomOperators = customOperators ?? ctx?.customOperators;
  const effectiveFieldRenderers = fieldRenderers ?? ctx?.fieldRenderers;
  void effectiveFieldRenderers;

  const allColumns = activeTables.flatMap((tbl) =>
    tbl.columns.map((c) => ({
      table: tbl.name,
      column: c.name,
      label: `${tbl.name}.${c.name}`,
      meta: c,
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
      className={cx(className, classNames?.filters)}
      style={
        unstyled
          ? undefined
          : {
              background: "var(--qb-color-surface, rgba(15, 23, 42, 0.6))",
              borderRadius: "var(--qb-radius-md, 8px)",
              border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
              padding: filters.length === 0 ? "8px 12px" : "12px",
              display: "flex",
              flexDirection: "column",
              gap: filters.length === 0 ? "6px" : "10px",
              color: "var(--qb-color-text, #f8fafc)",
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
                flexWrap: "wrap",
                gap: "8px",
              }
        }
      >
        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }
          }
        >
          <span
            className={cx(classNames?.title)}
            style={
              unstyled
                ? undefined
                : { fontSize: "0.85rem", fontWeight: 600, color: "var(--qb-color-text-muted, #94a3b8)" }
            }
          >
            ⚡ Filter Conditions ({filters.length})
          </span>
          {filters.length === 0 && (
            <span
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: "0.78rem",
                      color: "var(--qb-color-text-muted, #64748b)",
                      fontStyle: "italic",
                    }
              }
            >
              No filters applied. Results will include all rows.
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={handleAddFilter}
          data-qb="btn-add-filter"
          className={cx(classNames?.filterAddButton)}
          style={
            unstyled
              ? undefined
              : {
                  background: "var(--qb-color-primary-light, rgba(59, 130, 246, 0.2))",
                  color: "var(--qb-color-primary, #60a5fa)",
                  border: "1px solid var(--qb-color-primary, rgba(59, 130, 246, 0.4))",
                  borderRadius: "var(--qb-radius-sm, 6px)",
                  padding: "4px 10px",
                  fontSize: "0.75rem",
                  cursor: "pointer",
                  fontWeight: 600,
                  transition: "all 0.15s ease",
                }
          }
        >
          + Add Filter
        </button>
      </div>

      {filters.length > 0 && (
        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", flexDirection: "column", gap: "8px" }
          }
        >
          {filters.map((f, idx) => {
            const resolvedTable =
              f.tablePrefix ||
              activeTables.find((t) => t.columns.some((c) => c.name === f.column))?.name ||
              activeTables[0]?.name ||
              "";
            const selectValue = resolvedTable ? `${resolvedTable}.${f.column}` : f.column;
            const targetColMeta = allColumns.find(
              (c) => c.table === resolvedTable && c.column === f.column,
            )?.meta;
            const enumOptions = targetColMeta?.enums;

            return (
              <div
                key={f.id}
                data-qb="filter-row"
                data-qb-filter-id={f.id}
                className={cx(classNames?.filterItem)}
                style={
                  unstyled
                    ? undefined
                    : {
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        flexWrap: "wrap",
                        background: "var(--qb-color-surface-hover, rgba(30, 41, 59, 0.5))",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.04))",
                        padding: "8px 10px",
                        borderRadius: "var(--qb-radius-sm, 6px)",
                      }
                }
              >
                {idx > 0 && (
                  <button
                    type="button"
                    aria-label={`Toggle combiner for filter ${idx}`}
                    data-qb="filter-combiner"
                    data-qb-combiner-toggle="true"
                    onClick={() =>
                      handleUpdate(f.id, {
                        combiner: f.combiner === "OR" ? "AND" : "OR",
                      })
                    }
                    style={
                      unstyled
                        ? undefined
                        : {
                            fontSize: "0.7rem",
                            fontWeight: 700,
                            color: f.combiner === "OR" ? "#ec4899" : "#f59e0b",
                            background: f.combiner === "OR" ? "rgba(236, 72, 153, 0.15)" : "rgba(245, 158, 11, 0.15)",
                            border: `1px solid ${f.combiner === "OR" ? "rgba(236, 72, 153, 0.35)" : "rgba(245, 158, 11, 0.35)"}`,
                            borderRadius: "4px",
                            padding: "2px 7px",
                            cursor: "pointer",
                            minWidth: "38px",
                            transition: "all 0.15s ease",
                          }
                    }
                  >
                    {f.combiner || "AND"}
                  </button>
                )}

                {/* Open Parenthesis Toggle */}
                <button
                  type="button"
                  aria-label={`Toggle open parenthesis for filter ${idx + 1}`}
                  data-qb="filter-paren-open"
                  onClick={() =>
                    handleUpdate(f.id, {
                      parenOpen: f.parenOpen ? undefined : "(",
                    })
                  }
                  style={
                    unstyled
                      ? undefined
                      : {
                          fontSize: "0.72rem",
                          fontWeight: 700,
                          color: f.parenOpen ? "#38bdf8" : "var(--qb-color-text-muted, #64748b)",
                          background: f.parenOpen
                            ? "rgba(56, 189, 248, 0.18)"
                            : "var(--qb-color-surface, rgba(255, 255, 255, 0.03))",
                          border: f.parenOpen
                            ? "1px solid rgba(56, 189, 248, 0.45)"
                            : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                          borderRadius: "4px",
                          padding: "2px 6px",
                          cursor: "pointer",
                        }
                  }
                  title="Toggle opening parenthesis ("
                >
                  {f.parenOpen || "("}
                </button>

                {/* Column selector */}
                <select
                  value={selectValue}
                  data-qb="filter-column"
                  onChange={(e) => {
                    const val = e.target.value;
                    const lastDot = val.lastIndexOf(".");
                    if (lastDot !== -1) {
                      const t = val.substring(0, lastDot);
                      const c = val.substring(lastDot + 1);
                      handleUpdate(f.id, { tablePrefix: t, column: c });
                    }
                  }}
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "var(--qb-color-background, #1e293b)",
                          color: "var(--qb-color-text, #f8fafc)",
                          border: "1px solid var(--qb-color-border, #475569)",
                          borderRadius: "var(--qb-radius-sm, 4px)",
                          padding: "4px 8px",
                          fontSize: "0.78rem",
                          outline: "none",
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
                          background: "var(--qb-color-background, #1e293b)",
                          color: "var(--qb-color-text, #f8fafc)",
                          border: "1px solid var(--qb-color-border, #475569)",
                          borderRadius: "var(--qb-radius-sm, 4px)",
                          padding: "4px 8px",
                          fontSize: "0.78rem",
                          outline: "none",
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
                  <option value="LIKE">LIKE</option>
                  <option value="ILIKE">ILIKE</option>
                  <option value="IN">IN</option>
                  <option value="NOT IN">NOT IN</option>
                  <option value="BETWEEN">BETWEEN</option>
                  <option value="IS NULL">IS NULL</option>
                  <option value="IS NOT NULL">IS NOT NULL</option>
                  {effectiveCustomOperators &&
                    Object.values(effectiveCustomOperators).map((cop) => (
                      <option key={cop.value} value={cop.value}>
                        {cop.label || cop.value}
                      </option>
                    ))}
                </select>

                {/* Value Input */}
                {(() => {
                  const customOp = effectiveCustomOperators?.[f.operator];
                  const isUnary =
                    f.operator === "IS NULL" ||
                    f.operator === "IS NOT NULL" ||
                    customOp?.hasValue === false;

                  if (isUnary) return null;

                  const placeholder =
                    customOp?.placeholder ??
                    (f.operator === "BETWEEN" ? "10 AND 50" : "Value...");

                  const listId =
                    enumOptions && enumOptions.length > 0
                      ? `filter-enums-${f.id}`
                      : undefined;

                  return (
                    <>
                      <input
                        type="text"
                        placeholder={placeholder}
                        value={String(f.value ?? "")}
                        list={listId}
                        data-qb="filter-value"
                        onChange={(e) => handleUpdate(f.id, { value: e.target.value })}
                        style={
                          unstyled
                            ? undefined
                            : {
                                background: "var(--qb-color-background, #1e293b)",
                                color: "var(--qb-color-text, #f8fafc)",
                                border: "1px solid var(--qb-color-border, #475569)",
                                borderRadius: "var(--qb-radius-sm, 4px)",
                                padding: "4px 8px",
                                fontSize: "0.78rem",
                                flex: 1,
                                minWidth: "120px",
                                outline: "none",
                              }
                        }
                      />
                      {listId && enumOptions && (
                        <datalist id={listId}>
                          {enumOptions.map((ev) => (
                            <option key={ev} value={ev} />
                          ))}
                        </datalist>
                      )}
                    </>
                  );
                })()}

                {/* Close Parenthesis Toggle */}
                <button
                  type="button"
                  aria-label={`Toggle close parenthesis for filter ${idx + 1}`}
                  data-qb="filter-paren-close"
                  onClick={() =>
                    handleUpdate(f.id, {
                      parenClose: f.parenClose ? undefined : ")",
                    })
                  }
                  style={
                    unstyled
                      ? undefined
                      : {
                          fontSize: "0.72rem",
                          fontWeight: 700,
                          color: f.parenClose ? "#38bdf8" : "var(--qb-color-text-muted, #64748b)",
                          background: f.parenClose
                            ? "rgba(56, 189, 248, 0.18)"
                            : "var(--qb-color-surface, rgba(255, 255, 255, 0.03))",
                          border: f.parenClose
                            ? "1px solid rgba(56, 189, 248, 0.45)"
                            : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                          borderRadius: "4px",
                          padding: "2px 6px",
                          cursor: "pointer",
                        }
                  }
                  title="Toggle closing parenthesis )"
                >
                  {f.parenClose || ")"}
                </button>

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
                          color: "var(--qb-color-error, #ef4444)",
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
            );
          })}
        </div>
      )}
    </div>
  );
};
