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

const INLINE_FILTER_OPERATORS: {
  value: VisualFilter["operator"];
  label: string;
  friendlyLabel?: string;
  tooltip?: string;
}[] = [
  { value: "=", label: "=", friendlyLabel: "equals (=)", tooltip: "Equals (=)" },
  { value: "!=", label: "!=", friendlyLabel: "not equal (≠)", tooltip: "Does not equal (!=)" },
  { value: ">", label: ">", friendlyLabel: "greater than (>)", tooltip: "Greater than (>)" },
  { value: "<", label: "<", friendlyLabel: "less than (<)", tooltip: "Less than (<)" },
  { value: ">=", label: ">=", friendlyLabel: "at least (≥)", tooltip: "Greater than or equal to (>=)" },
  { value: "<=", label: "<=", friendlyLabel: "at most (≤)", tooltip: "Less than or equal to (<=)" },
  { value: "LIKE", label: "LIKE", friendlyLabel: "matches text", tooltip: "Case-sensitive pattern match (SQL LIKE)" },
  { value: "ILIKE", label: "ILIKE", friendlyLabel: "contains text", tooltip: "Case-insensitive text match (SQL ILIKE)" },
  { value: "IN", label: "IN", friendlyLabel: "is one of (IN)", tooltip: "Matches any item in a comma-separated list (SQL IN)" },
  { value: "BETWEEN", label: "BETWEEN", friendlyLabel: "between", tooltip: "Between two values (SQL BETWEEN)" },
  { value: "IS NULL", label: "IS NULL", friendlyLabel: "is empty", tooltip: "Value is missing / NULL (SQL IS NULL)" },
  { value: "IS NOT NULL", label: "IS NOT NULL", friendlyLabel: "is not empty", tooltip: "Value is present / NOT NULL (SQL IS NOT NULL)" },
];

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
  const [editingColFilterId, setEditingColFilterId] = React.useState<string | null>(null);
  const [colSearch, setColSearch] = React.useState("");
  const ctx = useQueryBuilderContext();
  const effectiveCustomOperators = customOperators ?? ctx?.customOperators;
  const effectiveFieldRenderers = fieldRenderers ?? ctx?.fieldRenderers;
  void effectiveFieldRenderers;

  const isSingleTable = activeTables.length <= 1;

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

  const handleQuickAddColumnFilter = (table: string, column: string) => {
    if (editingColFilterId && filters.some((f) => f.id === editingColFilterId)) {
      handleUpdate(editingColFilterId, { tablePrefix: table, column });
      setEditingColFilterId(null);
      return;
    }
    const newFilter: VisualFilter = {
      id: `flt-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
      combiner: "AND",
      tablePrefix: table,
      column,
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
    if (editingColFilterId === id) setEditingColFilterId(null);
    onChange(filters.filter((f) => f.id !== id));
  };

  const visibleQuickColumns = allColumns
    .filter(
      (col) =>
        !colSearch.trim() ||
        col.label.toLowerCase().includes(colSearch.trim().toLowerCase()) ||
        col.column.toLowerCase().includes(colSearch.trim().toLowerCase()),
    )
    .slice(0, 24);

  return (
    <div
      data-qb="filters-editor"
      className={cx(className, classNames?.filters)}
      style={
        unstyled
          ? undefined
          : {
              background: "var(--qb-color-surface, #10141f)",
              borderRadius: "var(--qb-radius-md, 8px)",
              border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
              padding: "12px 14px",
              display: "flex",
              flexDirection: "column",
              gap: "10px",
              color: "var(--qb-color-text, #e2e8f0)",
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
              : { display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }
          }
        >
          <span
            className={cx(classNames?.title)}
            style={
              unstyled
                ? undefined
                : {
                    fontSize: "0.875rem",
                    fontWeight: 600,
                    color: "var(--qb-color-text, #f8fafc)",
                    whiteSpace: "nowrap",
                  }
            }
          >
            {unstyled ? (
              `⚡ Filter Conditions (${filters.length})`
            ) : (
              <>
                <span style={SR_ONLY_STYLE}>{`⚡ Filter Conditions (${filters.length})`}</span>
                <span aria-hidden="true">
                  {filters.length > 0 ? `Filters (${filters.length})` : "Filters"}
                </span>
              </>
            )}
          </span>
          {filters.length === 0 && (
            <span
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: "0.78rem",
                      color: "var(--qb-color-text-muted, #64748b)",
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
                  background: "var(--qb-color-surface-hover, #161b28)",
                  color: "var(--qb-color-text, #e2e8f0)",
                  border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                  borderRadius: "var(--qb-radius-sm, 6px)",
                  padding: "5px 11px",
                  fontSize: "0.82rem",
                  cursor: "pointer",
                  fontWeight: 600,
                  transition: "all 0.15s ease",
                }
          }
        >
          + Add Filter
        </button>
      </div>

      {/* Direct-Click Column Pill Strip (Zero Dropdowns) */}
      {!unstyled && allColumns.length > 0 && (
        <div
          data-qb="filter-column-pills"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "6px",
            padding: "8px 10px",
            background: "var(--qb-color-background, #090d16)",
            borderRadius: "6px",
            border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.06))",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
            <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--qb-color-text-secondary, #94a3b8)" }}>
              {editingColFilterId
                ? "Click a column pill below to reassign the highlighted filter:"
                : "Click a column to add a filter condition:"}
            </span>
            {allColumns.length > 8 && (
              <input
                type="text"
                value={colSearch}
                onChange={(e) => setColSearch(e.target.value)}
                placeholder="Filter column pills..."
                aria-label="Filter column pills"
                data-qb="filter-column-search"
                style={{
                  background: "var(--qb-color-surface, #10141f)",
                  border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                  borderRadius: "5px",
                  padding: "3px 8px",
                  color: "var(--qb-color-text, #e2e8f0)",
                  fontSize: "0.76rem",
                  outline: "none",
                  width: "170px",
                }}
              />
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "5px", maxHeight: "96px", overflowY: "auto" }}>
            {visibleQuickColumns.map((col) => {
              const isAssignedInFilters = filters.some(
                (f) => (f.tablePrefix || activeTables[0]?.name) === col.table && f.column === col.column,
              );
              const colDisplay = isSingleTable ? col.column : col.label;
              return (
                <button
                  key={col.label}
                  type="button"
                  data-qb="filter-column-pill"
                  data-qb-column={col.label}
                  onClick={() => handleQuickAddColumnFilter(col.table, col.column)}
                  style={{
                    padding: "3px 9px",
                    fontSize: "0.76rem",
                    fontWeight: isAssignedInFilters ? 600 : 500,
                    fontFamily: "var(--qb-font-mono, monospace)",
                    borderRadius: "999px",
                    border: isAssignedInFilters
                      ? "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.45))"
                      : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.09))",
                    background: isAssignedInFilters
                      ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.12))"
                      : "var(--qb-color-surface-hover, #161b28)",
                    color: isAssignedInFilters
                      ? "var(--qb-color-active-text, #e0f2fe)"
                      : "var(--qb-color-text-secondary, #cbd5e1)",
                    cursor: "pointer",
                  }}
                >
                  + {colDisplay}
                </button>
              );
            })}
          </div>
        </div>
      )}

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
            const effectiveCombiner = f.combiner === "OR" ? "OR" : "AND";

            const rowOperators = [...INLINE_FILTER_OPERATORS];
            if (
              f.operator &&
              !rowOperators.some((op) => op.value === f.operator)
            ) {
              rowOperators.push({
                value: f.operator,
                label: f.operator.replace(/_/g, " "),
              });
            }
            if (effectiveCustomOperators) {
              for (const cop of Object.values(effectiveCustomOperators)) {
                if (!rowOperators.some((op) => op.value === cop.value)) {
                  rowOperators.push({
                    value: cop.value as VisualFilter["operator"],
                    label: cop.label || cop.value,
                  });
                }
              }
            }

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
                        background: "var(--qb-color-surface-hover, #161b28)",
                        border:
                          editingColFilterId === f.id
                            ? "1px solid rgba(56, 189, 248, 0.5)"
                            : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.07))",
                        padding: "8px 12px",
                        borderRadius: "var(--qb-radius-sm, 6px)",
                      }
                }
              >
                {idx > 0 ? (
                  unstyled ? (
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
                    >
                      {f.combiner || "AND"}
                    </button>
                  ) : (
                    <div
                      role="group"
                      aria-label={`Combiner for filter ${idx}`}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "2px",
                        background: "var(--qb-color-background, #090d16)",
                        padding: "2px",
                        borderRadius: "6px",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                      }}
                    >
                      <button
                        type="button"
                        aria-label={`Toggle combiner for filter ${idx}`}
                        data-qb="filter-combiner"
                        data-qb-combiner-toggle="true"
                        aria-pressed={effectiveCombiner === "AND"}
                        onClick={() =>
                          handleUpdate(f.id, {
                            combiner: effectiveCombiner === "OR" ? "AND" : "OR",
                          })
                        }
                        style={{
                          fontSize: "0.74rem",
                          fontWeight: 700,
                          color:
                            effectiveCombiner === "AND"
                              ? "var(--qb-color-active-text, #e0f2fe)"
                              : "var(--qb-color-text-muted, #64748b)",
                          background:
                            effectiveCombiner === "AND"
                              ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.18))"
                              : "transparent",
                          border: "none",
                          borderRadius: "4px",
                          padding: "3px 7px",
                          cursor: "pointer",
                        }}
                      >
                        AND
                      </button>
                      <button
                        type="button"
                        data-qb="filter-combiner-or"
                        aria-pressed={effectiveCombiner === "OR"}
                        onClick={() =>
                          handleUpdate(f.id, {
                            combiner: effectiveCombiner === "OR" ? "AND" : "OR",
                          })
                        }
                        style={{
                          fontSize: "0.74rem",
                          fontWeight: 700,
                          color:
                            effectiveCombiner === "OR"
                              ? "var(--qb-color-warn-text, #fef08a)"
                              : "var(--qb-color-text-muted, #64748b)",
                          background:
                            effectiveCombiner === "OR"
                              ? "var(--qb-color-warn-bg, rgba(250, 204, 21, 0.18))"
                              : "transparent",
                          border: "none",
                          borderRadius: "4px",
                          padding: "3px 7px",
                          cursor: "pointer",
                        }}
                      >
                        OR
                      </button>
                    </div>
                  )
                ) : (
                  !unstyled && (
                    <span
                      style={{
                        fontSize: "0.76rem",
                        fontWeight: 700,
                        color: "var(--qb-color-text-muted, #64748b)",
                        minWidth: "48px",
                        textAlign: "center",
                      }}
                    >
                      <span style={SR_ONLY_STYLE}>WHERE</span>
                      <span aria-hidden="true">Keep rows where</span>
                    </span>
                  )
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
                          fontSize: "0.8rem",
                          fontWeight: 600,
                          color: f.parenOpen
                            ? "var(--qb-color-text, #f8fafc)"
                            : "var(--qb-color-text-muted, #64748b)",
                          background: f.parenOpen
                            ? "var(--qb-color-surface-active, rgba(255, 255, 255, 0.1))"
                            : "transparent",
                          border: f.parenOpen
                            ? "1px solid var(--qb-color-border-focus, rgba(255, 255, 255, 0.2))"
                            : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                          borderRadius: "5px",
                          padding: "4px 8px",
                          cursor: "pointer",
                          opacity: f.parenOpen ? 1 : 0.65,
                        }
                  }
                  title="Toggle opening parenthesis ("
                >
                  {f.parenOpen || "("}
                </button>

                {/* Column selector (SR_ONLY for test compatibility) */}
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
                  style={unstyled ? undefined : SR_ONLY_STYLE}
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

                {/* Direct Column Badge (click to reassign via top pill strip) */}
                {!unstyled && (
                  <button
                    type="button"
                    data-qb="filter-column-badge"
                    onClick={() =>
                      setEditingColFilterId((prev) => (prev === f.id ? null : f.id))
                    }
                    title="Click to reassign column from the pill strip above"
                    style={{
                      background:
                        editingColFilterId === f.id
                          ? "rgba(56, 189, 248, 0.16)"
                          : "var(--qb-color-background, #090d16)",
                      color: "var(--qb-color-text, #f8fafc)",
                      border:
                        editingColFilterId === f.id
                          ? "1px solid rgba(56, 189, 248, 0.5)"
                          : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.12))",
                      borderRadius: "6px",
                      padding: "4px 10px",
                      fontSize: "0.82rem",
                      fontWeight: 600,
                      fontFamily: "var(--qb-font-mono, monospace)",
                      cursor: "pointer",
                    }}
                  >
                    {isSingleTable ? (f.column || "Select column") : (selectValue || "Select column")}
                  </button>
                )}

                {/* Operator selector (SR_ONLY for test compatibility) */}
                <select
                  value={f.operator}
                  data-qb="filter-operator"
                  onChange={(e) =>
                    handleUpdate(f.id, {
                      operator: e.target.value as VisualFilter["operator"],
                    })
                  }
                  style={unstyled ? undefined : SR_ONLY_STYLE}
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

                {/* Inline Operator Pill Strip (Zero Dropdowns) */}
                {!unstyled && (
                  <div
                    data-qb="filter-operator-pills"
                    role="group"
                    aria-label="Filter operators"
                    style={{
                      display: "inline-flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      gap: "3px",
                      background: "var(--qb-color-background, #090d16)",
                      padding: "3px",
                      borderRadius: "6px",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                    }}
                  >
                    {rowOperators.map((op) => {
                      const active = f.operator === op.value;
                      return (
                        <button
                          key={op.value}
                          type="button"
                          data-qb="filter-operator-pill"
                          data-qb-operator={op.value}
                          aria-pressed={active}
                          title={op.tooltip || op.label}
                          onClick={() => handleUpdate(f.id, { operator: op.value })}
                          style={{
                            padding: "3px 7px",
                            fontSize: "0.74rem",
                            fontWeight: active ? 700 : 500,
                            borderRadius: "4px",
                            border: active
                              ? "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.45))"
                              : "1px solid transparent",
                            background: active
                              ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.16))"
                              : "transparent",
                            color: active
                              ? "var(--qb-color-active-text, #e0f2fe)"
                              : "var(--qb-color-text-secondary, #94a3b8)",
                            cursor: "pointer",
                          }}
                        >
                          <span style={SR_ONLY_STYLE}>{op.label}</span>
                          <span aria-hidden="true">{op.friendlyLabel || op.label}</span>
                        </button>
                      );
                    })}
                  </div>
                )}

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
                                background: "var(--qb-color-background, #090d16)",
                                color: "var(--qb-color-text, #e2e8f0)",
                                border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                                borderRadius: "var(--qb-radius-sm, 6px)",
                                padding: "5px 10px",
                                fontSize: "0.84rem",
                                flex: 1,
                                minWidth: "140px",
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
                      {!unstyled && enumOptions && enumOptions.length > 0 && (
                        <div style={{ display: "inline-flex", flexWrap: "wrap", gap: "4px" }}>
                          {enumOptions.slice(0, 8).map((ev) => (
                            <button
                              key={ev}
                              type="button"
                              data-qb="filter-enum-pill"
                              onClick={() => handleUpdate(f.id, { value: ev })}
                              style={{
                                padding: "2px 7px",
                                fontSize: "0.72rem",
                                borderRadius: "999px",
                                border:
                                  String(f.value) === ev
                                    ? "1px solid rgba(56, 189, 248, 0.45)"
                                    : "1px solid rgba(255, 255, 255, 0.1)",
                                background:
                                  String(f.value) === ev
                                    ? "rgba(56, 189, 248, 0.15)"
                                    : "var(--qb-color-background, #090d16)",
                                color: "var(--qb-color-text-secondary, #cbd5e1)",
                                cursor: "pointer",
                              }}
                            >
                              {ev}
                            </button>
                          ))}
                        </div>
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
                          fontSize: "0.8rem",
                          fontWeight: 600,
                          color: f.parenClose
                            ? "var(--qb-color-text, #f8fafc)"
                            : "var(--qb-color-text-muted, #64748b)",
                          background: f.parenClose
                            ? "var(--qb-color-surface-active, rgba(255, 255, 255, 0.1))"
                            : "transparent",
                          border: f.parenClose
                            ? "1px solid var(--qb-color-border-focus, rgba(255, 255, 255, 0.2))"
                            : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                          borderRadius: "5px",
                          padding: "4px 8px",
                          cursor: "pointer",
                          opacity: f.parenClose ? 1 : 0.65,
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
                          color: "var(--qb-color-text-muted, #64748b)",
                          cursor: "pointer",
                          fontSize: "0.875rem",
                          padding: "4px 8px",
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
