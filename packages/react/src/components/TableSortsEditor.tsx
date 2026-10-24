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
  limit?: number;
  onLimitChange?: (limit: number) => void;
  onChange: (sorts: VisualSort[]) => void;
  unstyled?: boolean;
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

export const TableSortsEditor: React.FC<TableSortsEditorProps> = ({
  sorts,
  activeTables,
  selectedColumns,
  limit,
  onLimitChange,
  onChange,
  unstyled = false,
  className,
  classNames,
}) => {
  const [editingSortId, setEditingSortId] = React.useState<string | null>(null);
  const [sortSearch, setSortSearch] = React.useState("");
  const [draggedSortIdx, setDraggedSortIdx] = React.useState<number | null>(null);
  const [dragOverSortIdx, setDragOverSortIdx] = React.useState<number | null>(null);
  const isSingleTable = activeTables.length <= 1;
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

  const handleQuickColumnSort = (table: string, column: string) => {
    if (editingSortId && sorts.some((s) => s.id === editingSortId)) {
      handleUpdate(editingSortId, { tablePrefix: table, column });
      setEditingSortId(null);
      return;
    }
    const existing = sorts.find(
      (s) => (s.tablePrefix || activeTables[0]?.name || "") === table && s.column === column,
    );
    if (existing) {
      handleUpdate(existing.id, {
        direction: existing.direction === "ASC" ? "DESC" : "ASC",
      });
      return;
    }
    const newSort: VisualSort = {
      id: `sort-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
      tablePrefix: table,
      column,
      direction: "ASC",
    };
    onChange([...sorts, newSort]);
  };

  const handleUpdate = (id: string, updates: Partial<VisualSort>) => {
    onChange(sorts.map((s) => (s.id === id ? { ...s, ...updates } : s)));
  };

  const handleMoveSort = (index: number, delta: -1 | 1) => {
    const targetIdx = index + delta;
    if (targetIdx < 0 || targetIdx >= sorts.length) return;
    const next = [...sorts];
    const [moved] = next.splice(index, 1);
    next.splice(targetIdx, 0, moved);
    onChange(next);
  };

  const handleDropSort = (fromIdx: number | null, toIdx: number) => {
    setDraggedSortIdx(null);
    setDragOverSortIdx(null);
    if (
      fromIdx === null ||
      fromIdx === toIdx ||
      fromIdx < 0 ||
      toIdx < 0 ||
      fromIdx >= sorts.length ||
      toIdx >= sorts.length
    ) {
      return;
    }
    const next = [...sorts];
    const [moved] = next.splice(fromIdx, 1);
    next.splice(toIdx, 0, moved);
    onChange(next);
  };

  const handleRemove = (id: string) => {
    if (editingSortId === id) setEditingSortId(null);
    onChange(sorts.filter((s) => s.id !== id));
  };

  const visibleQuickColumns = allColumns
    .filter(
      (col) =>
        !sortSearch.trim() ||
        col.label.toLowerCase().includes(sortSearch.trim().toLowerCase()) ||
        col.column.toLowerCase().includes(sortSearch.trim().toLowerCase()),
    )
    .slice(0, 24);

  return (
    <div
      data-qb="sorts-editor"
      className={cx(className, classNames?.sorts)}
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
        data-qb="sorts-header"
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
              `↕️ Order & Sorts (${sorts.length})`
            ) : (
              <>
                <span style={SR_ONLY_STYLE}>{`↕️ Order & Sorts (${sorts.length})`}</span>
                <span aria-hidden="true">
                  {sorts.length > 0 ? `Sort (${sorts.length})` : "Sort"}
                </span>
              </>
            )}
          </span>
          {sorts.length === 0 && (
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
              Default database ordering. Add sort columns to order results.
            </span>
          )}
        </div>
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
          + Add Sort
        </button>
      </div>

      {/* Direct-Click Sort Column Pill Strip (Zero Dropdowns) */}
      {!unstyled && allColumns.length > 0 && (
        <div
          data-qb="sort-column-pills"
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
              {editingSortId
                ? "Click a column pill below to reassign the highlighted sort:"
                : "Click a column to sort (click again to flip ASC/DESC):"}
            </span>
            {allColumns.length > 8 && (
              <input
                type="text"
                value={sortSearch}
                onChange={(e) => setSortSearch(e.target.value)}
                placeholder="Filter sort pills..."
                aria-label="Filter sort column pills"
                data-qb="sort-column-search"
                style={{
                  background: "var(--qb-color-surface, #10141f)",
                  border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                  borderRadius: "5px",
                  padding: "3px 8px",
                  color: "var(--qb-color-text, #e2e8f0)",
                  fontSize: "0.76rem",
                  outline: "none",
                  width: "160px",
                }}
              />
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "5px", maxHeight: "96px", overflowY: "auto" }}>
            {visibleQuickColumns.map((col) => {
              const activeSort = sorts.find(
                (s) =>
                  (s.tablePrefix || activeTables[0]?.name || "") === col.table &&
                  s.column === col.column,
              );
              const colDisplay = isSingleTable ? col.column : col.label;
              return (
                <button
                  key={col.label}
                  type="button"
                  data-qb="sort-column-pill"
                  data-qb-column={col.label}
                  onClick={() => handleQuickColumnSort(col.table, col.column)}
                  style={{
                    padding: "3px 9px",
                    fontSize: "0.76rem",
                    fontWeight: activeSort ? 700 : 500,
                    fontFamily: "var(--qb-font-mono, monospace)",
                    borderRadius: "999px",
                    border: activeSort
                      ? "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.45))"
                      : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.09))",
                    background: activeSort
                      ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.14))"
                      : "var(--qb-color-surface-hover, #161b28)",
                    color: activeSort
                      ? "var(--qb-color-active-text, #e0f2fe)"
                      : "var(--qb-color-text-secondary, #cbd5e1)",
                    cursor: "pointer",
                  }}
                >
                  {`↕ ${colDisplay}${activeSort ? ` (${activeSort.direction})` : ""}`}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {sorts.length > 0 && (
        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", flexDirection: "column", gap: "8px" }
          }
        >
          {sorts.map((s, idx) => {
            const resolvedTable =
              s.tablePrefix ||
              activeTables.find((t) => t.columns.some((c) => c.name === s.column))?.name ||
              (aliasOptions.some((a) => a.column === s.column)
                ? ""
                : activeTables[0]?.name || "");
            const selectValue = resolvedTable ? `${resolvedTable}.${s.column}` : s.column;
            const isDragging = draggedSortIdx === idx;
            const isDragOver = dragOverSortIdx === idx && draggedSortIdx !== idx;

            return (
              <div
                key={s.id}
                data-qb="sort-row"
                data-qb-sort-id={s.id}
                draggable={!unstyled}
                onDragStart={(e) => {
                  const targetTag = (e.target as HTMLElement | null)?.tagName;
                  if (targetTag === "INPUT" || targetTag === "SELECT" || targetTag === "TEXTAREA") {
                    e.preventDefault();
                    return;
                  }
                  setDraggedSortIdx(idx);
                  if (e.dataTransfer) {
                    e.dataTransfer.effectAllowed = "move";
                    try {
                      e.dataTransfer.setData("text/plain", String(idx));
                    } catch {
                      // Ignore in synthetic test environments
                    }
                  }
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
                  if (dragOverSortIdx !== idx) setDragOverSortIdx(idx);
                }}
                onDragEnter={(e) => {
                  e.preventDefault();
                  setDragOverSortIdx(idx);
                }}
                onDragLeave={(e) => {
                  if (
                    e.relatedTarget instanceof Node &&
                    e.currentTarget.contains(e.relatedTarget)
                  ) {
                    return;
                  }
                  if (dragOverSortIdx === idx) setDragOverSortIdx(null);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  const rawIdx = e.dataTransfer?.getData?.("text/plain");
                  const resolvedFrom =
                    draggedSortIdx ??
                    (rawIdx !== undefined && rawIdx !== "" && !Number.isNaN(Number(rawIdx))
                      ? Number(rawIdx)
                      : null);
                  handleDropSort(resolvedFrom, idx);
                }}
                onDragEnd={() => {
                  setDraggedSortIdx(null);
                  setDragOverSortIdx(null);
                }}
                className={cx(classNames?.sortItem)}
                style={
                  unstyled
                    ? undefined
                    : {
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                        flexWrap: "wrap",
                        background: isDragOver
                          ? "rgba(56, 189, 248, 0.14)"
                          : "var(--qb-color-surface-hover, #161b28)",
                        border: isDragOver
                          ? "1px dashed #38bdf8"
                          : editingSortId === s.id
                            ? "1px solid rgba(56, 189, 248, 0.5)"
                            : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.07))",
                        padding: "8px 12px",
                        borderRadius: "var(--qb-radius-sm, 6px)",
                        cursor: "grab",
                        opacity: isDragging ? 0.55 : 1,
                      }
                }
              >
                {!unstyled && (
                  <span
                    aria-hidden="true"
                    data-qb="sort-drag-handle"
                    style={{
                      color: "var(--qb-color-text-muted, #64748b)",
                      fontSize: "0.78rem",
                      userSelect: "none",
                      cursor: "grab",
                    }}
                  >
                    ⋮⋮
                  </span>
                )}
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

                {!unstyled && (
                  <button
                    type="button"
                    data-qb="sort-column-badge"
                    onClick={() =>
                      setEditingSortId((prev) => (prev === s.id ? null : s.id))
                    }
                    title="Click to reassign sort column from the pill strip above"
                    style={{
                      background:
                        editingSortId === s.id
                          ? "rgba(56, 189, 248, 0.16)"
                          : "var(--qb-color-background, #090d16)",
                      color: "var(--qb-color-text, #f8fafc)",
                      border:
                        editingSortId === s.id
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
                    {isSingleTable ? (s.column || "Select sort column") : (selectValue || "Select sort column")}
                  </button>
                )}

                {/* SR_ONLY direction toggle button preserved for test compatibility */}
                <button
                  type="button"
                  aria-label="Toggle sort direction"
                  data-qb="sort-direction"
                  onClick={() =>
                    handleUpdate(s.id, {
                      direction: s.direction === "ASC" ? "DESC" : "ASC",
                    })
                  }
                  style={unstyled ? undefined : SR_ONLY_STYLE}
                >
                  {s.direction} {s.direction === "ASC" ? "▲" : "▼"}
                </button>

                {/* Direct Segmented [ASC ↑ | DESC ↓] Pills */}
                {!unstyled && (
                  <div
                    role="group"
                    aria-label="Sort direction pills"
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
                      data-qb="sort-dir-asc"
                      aria-pressed={s.direction === "ASC"}
                      title="Sort ascending (A→Z / lowest to highest)"
                      onClick={() => handleUpdate(s.id, { direction: "ASC" })}
                      style={{
                        padding: "3px 9px",
                        fontSize: "0.75rem",
                        fontWeight: s.direction === "ASC" ? 700 : 500,
                        borderRadius: "4px",
                        border: "none",
                        background:
                          s.direction === "ASC"
                            ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.18))"
                            : "transparent",
                        color:
                          s.direction === "ASC"
                            ? "var(--qb-color-active-text, #e0f2fe)"
                            : "var(--qb-color-text-muted, #64748b)",
                        cursor: "pointer",
                      }}
                    >
                      <span style={SR_ONLY_STYLE}>ASC ↑</span>
                      <span aria-hidden="true">Ascending ↑</span>
                    </button>
                    <button
                      type="button"
                      data-qb="sort-dir-desc"
                      aria-pressed={s.direction === "DESC"}
                      title="Sort descending (Z→A / highest to lowest)"
                      onClick={() => handleUpdate(s.id, { direction: "DESC" })}
                      style={{
                        padding: "3px 9px",
                        fontSize: "0.75rem",
                        fontWeight: s.direction === "DESC" ? 700 : 500,
                        borderRadius: "4px",
                        border: "none",
                        background:
                          s.direction === "DESC"
                            ? "var(--qb-color-warn-bg, rgba(250, 204, 21, 0.18))"
                            : "transparent",
                        color:
                          s.direction === "DESC"
                            ? "var(--qb-color-warn-text, #fef08a)"
                            : "var(--qb-color-text-muted, #64748b)",
                        cursor: "pointer",
                      }}
                    >
                      <span style={SR_ONLY_STYLE}>DESC ↓</span>
                      <span aria-hidden="true">Descending ↓</span>
                    </button>
                  </div>
                )}

                {!unstyled && sorts.length > 1 && (
                  <div style={{ display: "inline-flex", alignItems: "center", gap: "3px" }}>
                    <button
                      type="button"
                      data-qb="sort-move-up"
                      disabled={idx === 0}
                      onClick={() => handleMoveSort(idx, -1)}
                      title="Move sort priority up"
                      style={{
                        background: "var(--qb-color-background, #090d16)",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                        borderRadius: "4px",
                        color: "var(--qb-color-text-secondary, #94a3b8)",
                        fontSize: "0.72rem",
                        padding: "2px 6px",
                        cursor: idx === 0 ? "not-allowed" : "pointer",
                        opacity: idx === 0 ? 0.4 : 1,
                      }}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      data-qb="sort-move-down"
                      disabled={idx === sorts.length - 1}
                      onClick={() => handleMoveSort(idx, 1)}
                      title="Move sort priority down"
                      style={{
                        background: "var(--qb-color-background, #090d16)",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                        borderRadius: "4px",
                        color: "var(--qb-color-text-secondary, #94a3b8)",
                        fontSize: "0.72rem",
                        padding: "2px 6px",
                        cursor: idx === sorts.length - 1 ? "not-allowed" : "pointer",
                        opacity: idx === sorts.length - 1 ? 0.4 : 1,
                      }}
                    >
                      ↓
                    </button>
                  </div>
                )}

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
                          color: "var(--qb-color-text-muted, #64748b)",
                          cursor: "pointer",
                          fontSize: "0.875rem",
                          padding: "4px 8px",
                          marginLeft: "auto",
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

      {limit !== undefined && onLimitChange && (
        <div
          data-qb="sorts-limit-row"
          style={
            unstyled
              ? undefined
              : {
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "8px",
                  padding: "8px 10px",
                  background: "var(--qb-color-background, #090d16)",
                  borderRadius: "6px",
                  border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.06))",
                }
          }
        >
          <span
            style={
              unstyled
                ? undefined
                : {
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    color: "var(--qb-color-text-secondary, #94a3b8)",
                  }
            }
          >
            Row limit:
          </span>
          <select
            value={limit}
            aria-label="Sorts query limit"
            data-qb="sort-input-limit"
            onChange={(e) => onLimitChange(Number(e.target.value))}
            style={unstyled ? undefined : SR_ONLY_STYLE}
          >
            {[10, 25, 50, 100, 500].map((lv) => (
              <option key={lv} value={lv}>
                {lv}
              </option>
            ))}
            {![10, 25, 50, 100, 500].includes(limit) && (
              <option value={limit}>{limit}</option>
            )}
          </select>
          {!unstyled && (
            <div
              role="group"
              aria-label="Sort row limit pills"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "2px",
                background: "var(--qb-color-surface, #10141f)",
                padding: "2px",
                borderRadius: "6px",
                border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
              }}
            >
              {(![10, 25, 50, 100, 500].includes(limit)
                ? [limit, 10, 25, 50, 100, 500]
                : [10, 25, 50, 100, 500]
              ).map((lv) => {
                const active = limit === lv;
                return (
                  <button
                    key={lv}
                    type="button"
                    data-qb="sort-limit-pill"
                    data-qb-limit={lv}
                    aria-pressed={active}
                    onClick={() => onLimitChange(lv)}
                    style={{
                      padding: "2px 8px",
                      fontSize: "0.74rem",
                      fontWeight: active ? 700 : 500,
                      borderRadius: "4px",
                      border: "none",
                      background: active
                        ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.18))"
                        : "transparent",
                      color: active
                        ? "var(--qb-color-active-text, #e0f2fe)"
                        : "var(--qb-color-text-muted, #64748b)",
                      cursor: "pointer",
                    }}
                  >
                    {lv}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
