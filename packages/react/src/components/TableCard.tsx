import React, { useState } from "react";
import type { TableMeta, VisualColumnSelect, CustomFieldRenderer, QueryBuilderClassNames } from "../types";
import { useQueryBuilderContext } from "../theme/QueryBuilderProvider";
import { cx } from "../utils/classNames";

export interface TableCardProps {
  table: TableMeta;
  isSelected?: boolean;
  selectedColumns: Record<string, VisualColumnSelect>;
  onToggleColumn: (colName: string) => void;
  onRemoveTable?: () => void;
  onAddJoin?: () => void;
  onQuickFilterColumn?: (tableName: string, colName: string, dataType: string) => void;
  onQuickSortColumn?: (tableName: string, colName: string) => void;
  onQuickAggregateColumn?: (tableName: string, colName: string, currentAgg?: string) => void;
  onQuickJoinForeignKey?: (foreignTable: string) => void;
  onReorderColumns?: (tableName: string, orderedColumnNames: string[]) => void;
  activeFilterColumns?: Set<string>;
  activeSortMap?: Record<string, "ASC" | "DESC">;
  foreignKeys?: { table: string; column: string; foreign_table: string; foreign_column: string }[];
  unstyled?: boolean;
  fieldRenderers?: Record<string, CustomFieldRenderer>;
  className?: string;
  classNames?: QueryBuilderClassNames;
}

export const TableCard: React.FC<TableCardProps> = ({
  table,
  isSelected,
  selectedColumns,
  onToggleColumn,
  onRemoveTable,
  onAddJoin,
  onQuickFilterColumn,
  onQuickSortColumn,
  onQuickAggregateColumn,
  onQuickJoinForeignKey,
  onReorderColumns,
  activeFilterColumns,
  activeSortMap,
  foreignKeys,
  unstyled = false,
  fieldRenderers,
  className,
  classNames,
}) => {
  const ctx = useQueryBuilderContext();
  const effectiveFieldRenderers = fieldRenderers ?? ctx?.fieldRenderers;
  const [columnSearch, setColumnSearch] = useState("");
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);
  const [isColumnsCollapsed, setIsColumnsCollapsed] = useState(false);
  const [hoveredCol, setHoveredCol] = useState<string | null>(null);
  const [focusedCol, setFocusedCol] = useState<string | null>(null);
  const [orderedColNames, setOrderedColNames] = useState<string[]>(() =>
    table.columns.map((c) => c.name),
  );
  const [draggedColName, setDraggedColName] = useState<string | null>(null);
  const [dragOverColName, setDragOverColName] = useState<string | null>(null);

  React.useEffect(() => {
    setOrderedColNames(table.columns.map((c) => c.name));
  }, [table.name, table.columns]);

  const formatShortType = (rawType?: string): string => {
    if (!rawType) return "";
    const t = rawType.toLowerCase();
    if (t.includes("uuid")) return "uid";
    if (t.includes("bool")) return "bool";
    if (t.includes("json")) return "json";
    if (t.includes("time") || t.includes("date")) return "time";
    if (
      t.includes("int") ||
      t.includes("num") ||
      t.includes("dec") ||
      t.includes("float") ||
      t.includes("double") ||
      t.includes("real") ||
      t.includes("serial")
    ) {
      return "num";
    }
    if (t.includes("char") || t.includes("text") || t.includes("citext")) return "str";
    if (t.includes("user-defined") || t.includes("enum")) return "enum";
    if (t.includes("array")) return "arr";
    return t.slice(0, 4);
  };

  const formatFriendlyType = (rawType?: string): string => {
    if (!rawType) return "";
    const t = rawType.toLowerCase();
    if (t.includes("uuid")) return "ID";
    if (t.includes("bool")) return "Yes/No";
    if (t.includes("json")) return "Data";
    if (t.includes("time") || t.includes("date")) return "Date";
    if (
      t.includes("int") ||
      t.includes("num") ||
      t.includes("dec") ||
      t.includes("float") ||
      t.includes("double") ||
      t.includes("real") ||
      t.includes("serial")
    ) {
      return "Number";
    }
    if (t.includes("char") || t.includes("text") || t.includes("citext")) return "Text";
    if (t.includes("user-defined") || t.includes("enum")) return "Option";
    if (t.includes("array")) return "List";
    return "Field";
  };

  const selectedCount = table.columns.filter(
    (c) => Boolean(selectedColumns[`${table.name}.${c.name}`]),
  ).length;

  React.useEffect(() => {
    if (showSelectedOnly && selectedCount === 0) {
      setShowSelectedOnly(false);
    }
  }, [showSelectedOnly, selectedCount]);

  const orderedColumns = React.useMemo(() => {
    const colMap = new Map(table.columns.map((c) => [c.name, c]));
    if (
      orderedColNames.length === table.columns.length &&
      orderedColNames.every((n) => colMap.has(n))
    ) {
      return orderedColNames.map((n) => colMap.get(n)!);
    }
    return table.columns;
  }, [table.columns, orderedColNames]);

  const handleDropTableColumn = (fromCol: string | null, toCol: string) => {
    setDraggedColName(null);
    setDragOverColName(null);
    if (!fromCol || fromCol === toCol) return;
    const currentNames = orderedColumns.map((c) => c.name);
    const fromIdx = currentNames.indexOf(fromCol);
    const toIdx = currentNames.indexOf(toCol);
    if (fromIdx === -1 || toIdx === -1) return;
    const nextNames = [...currentNames];
    const [moved] = nextNames.splice(fromIdx, 1);
    nextNames.splice(toIdx, 0, moved);
    setOrderedColNames(nextNames);
    if (onReorderColumns) {
      onReorderColumns(table.name, nextNames);
    }
  };

  const filteredColumns = orderedColumns.filter((c) => {
    if (showSelectedOnly && selectedCount > 0 && !selectedColumns[`${table.name}.${c.name}`]) {
      return false;
    }
    if (columnSearch.trim()) {
      return c.name.toLowerCase().includes(columnSearch.trim().toLowerCase());
    }
    return true;
  });

  const handleSelectAll = () => {
    orderedColumns.forEach((col) => {
      const key = `${table.name}.${col.name}`;
      if (!selectedColumns[key]) {
        onToggleColumn(col.name);
      }
    });
  };

  const handleClearAll = () => {
    table.columns.forEach((col) => {
      const key = `${table.name}.${col.name}`;
      if (selectedColumns[key]) {
        onToggleColumn(col.name);
      }
    });
  };

  const srOnlyStyle: React.CSSProperties = {
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

  return (
    <div
      role="region"
      aria-label={`Table ${table.name}`}
      data-qb="table-card"
      data-qb-table={table.name}
      data-qb-selected={isSelected ? "true" : "false"}
      className={cx(className, classNames?.tableCard)}
      style={
        unstyled
          ? undefined
          : {
              background: "var(--qb-color-surface, #10141f)",
              borderRadius: "var(--qb-radius-md, 8px)",
              border: isSelected
                ? "1px solid #3b82f6"
                : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
              boxShadow: "var(--qb-shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.25))",
              overflow: "hidden",
              minWidth: "320px",
              flex: "1 1 360px",
              display: "flex",
              flexDirection: "column",
              color: "var(--qb-color-text, #e2e8f0)",
              fontFamily: "var(--qb-font-family, system-ui, -apple-system, sans-serif)",
              transition: "border-color 0.15s ease",
            }
      }
    >
      {/* Consolidated Single Header Bar */}
      <div
        data-qb="table-card-header"
        className={cx(classNames?.tableCardHeader)}
        style={
          unstyled
            ? undefined
            : {
                padding: "10px 14px",
                background: "var(--qb-color-surface-hover, #161b28)",
                borderBottom: isColumnsCollapsed
                  ? "none"
                  : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.07))",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "10px",
              }
        }
      >
        <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "10px", minWidth: 0, flex: "1 1 auto" }}>
          <span
            data-qb="table-card-title"
            className={cx(classNames?.tableCardTitle)}
            style={
              unstyled
                ? undefined
                : {
                    fontWeight: 600,
                    fontSize: "1rem",
                    color: "var(--qb-color-text, #f8fafc)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    letterSpacing: "-0.01em",
                  }
            }
            title={table.name}
          >
            {table.name}
          </span>
          {table.columns.length > 0 && (
            <span
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: "0.82rem",
                      padding: "2px 8px",
                      borderRadius: "5px",
                      background: "var(--qb-color-surface-active, rgba(255, 255, 255, 0.06))",
                      color:
                        selectedCount > 0
                          ? "var(--qb-color-text, #e2e8f0)"
                          : "var(--qb-color-text-muted, #94a3b8)",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.07))",
                      fontWeight: 500,
                      flexShrink: 0,
                    }
              }
              title={`${selectedCount} of ${table.columns.length} columns selected`}
            >
              {unstyled ? (
                `${selectedCount}/${table.columns.length}`
              ) : (
                <>
                  <span style={srOnlyStyle}>{`${selectedCount}/${table.columns.length}`}</span>
                  <span aria-hidden="true">
                    {selectedCount === 0
                      ? `All ${table.columns.length} columns`
                      : `${selectedCount} of ${table.columns.length} selected`}
                  </span>
                </>
              )}
            </span>
          )}
        </div>

        <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap", flexShrink: 0 }}>
          {/* Inline column search and Selected filter when > 6 columns */}
          {table.columns.length > 6 && (
            <>
              <div
                style={
                  unstyled
                    ? undefined
                    : isColumnsCollapsed
                      ? srOnlyStyle
                      : { position: "relative", display: "flex", alignItems: "center" }
                }
              >
                <input
                  type="text"
                  value={columnSearch}
                  onChange={(e) => {
                    setColumnSearch(e.target.value);
                    if (isColumnsCollapsed) setIsColumnsCollapsed(false);
                  }}
                  placeholder="Filter columns..."
                  aria-label={`Filter columns in ${table.name}`}
                  data-qb="table-card-column-search"
                  style={
                    unstyled
                      ? undefined
                      : {
                          width: "175px",
                          boxSizing: "border-box",
                          background: "var(--qb-color-background, #090d16)",
                          color: "var(--qb-color-text, #e2e8f0)",
                          border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                          borderRadius: "6px",
                          padding: columnSearch ? "5px 26px 5px 10px" : "5px 10px",
                          fontSize: "0.84rem",
                          outline: "none",
                        }
                  }
                />
                {columnSearch && (
                  <button
                    type="button"
                    onClick={() => setColumnSearch("")}
                    aria-label="Clear filter search"
                    style={{
                      position: "absolute",
                      right: "6px",
                      background: "transparent",
                      border: "none",
                      color: "var(--qb-color-text-muted, #64748b)",
                      cursor: "pointer",
                      padding: "2px 4px",
                      fontSize: "0.8rem",
                    }}
                  >
                    ✕
                  </button>
                )}
              </div>
              {!unstyled && (
                <button
                  type="button"
                  data-qb="table-card-filter-selected"
                  onClick={() => setShowSelectedOnly((prev) => !prev)}
                  title={
                    showSelectedOnly
                      ? `Showing ${selectedCount} selected columns — click to show all ${table.columns.length}`
                      : `Filter to only ${selectedCount} checked columns`
                  }
                  style={srOnlyStyle}
                >
                  {showSelectedOnly
                    ? `All (${table.columns.length}) | ✓ Selected (${selectedCount})`
                    : `All (${table.columns.length}) | Selected (${selectedCount})`}
                </button>
              )}
            </>
          )}

          <button
            type="button"
            onClick={handleSelectAll}
            aria-label={`Select all columns in ${table.name}`}
            data-qb="table-card-btn-select-all"
            style={
              unstyled
                ? undefined
                : isColumnsCollapsed || table.columns.length === 0 || selectedCount > 0
                  ? srOnlyStyle
                  : {
                      background: "transparent",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                      color: "var(--qb-color-text-secondary, #94a3b8)",
                      cursor: "pointer",
                      padding: "5px 10px",
                      borderRadius: "6px",
                      fontSize: "0.84rem",
                      fontWeight: 500,
                      transition: "all 0.15s ease",
                    }
            }
            title="Select all columns"
          >
            {unstyled ? (
              "All"
            ) : (
              <>
                <span style={srOnlyStyle}>All</span>
                <span aria-hidden="true">Select all</span>
              </>
            )}
          </button>
          <button
            type="button"
            onClick={handleClearAll}
            aria-label={`Clear all columns in ${table.name}`}
            data-qb="table-card-btn-clear-all"
            style={
              unstyled
                ? undefined
                : isColumnsCollapsed || selectedCount === 0
                  ? srOnlyStyle
                  : {
                      background: "transparent",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                      color: "var(--qb-color-text-secondary, #94a3b8)",
                      cursor: "pointer",
                      padding: "5px 10px",
                      borderRadius: "6px",
                      fontSize: "0.84rem",
                      fontWeight: 500,
                      transition: "all 0.15s ease",
                    }
            }
            title="Clear all columns"
          >
            {unstyled ? (
              "Clear"
            ) : (
              <>
                <span style={srOnlyStyle}>Clear</span>
                <span aria-hidden="true">{`Clear (${selectedCount})`}</span>
              </>
            )}
          </button>
          {!unstyled && table.columns.length > 0 && (
            <button
              type="button"
              data-qb="table-card-btn-collapse-columns"
              onClick={() => setIsColumnsCollapsed((prev) => !prev)}
              style={{
                background: "transparent",
                border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                color: "var(--qb-color-text-secondary, #94a3b8)",
                cursor: "pointer",
                padding: "5px 10px",
                borderRadius: "6px",
                fontSize: "0.84rem",
                fontWeight: 500,
              }}
              title={isColumnsCollapsed ? "Expand column selector grid" : "Collapse column selector grid"}
            >
              {isColumnsCollapsed ? `Columns (${table.columns.length}) ▾` : "Hide columns ▴"}
            </button>
          )}
          {onAddJoin && (
            <button
              type="button"
              onClick={onAddJoin}
              aria-label={`Add join for table ${table.name}`}
              data-qb="table-card-btn-join"
              style={
                unstyled
                  ? undefined
                  : srOnlyStyle
              }
              title="Add Join to this table"
            >
              Join
            </button>
          )}
          {onRemoveTable && (
            <button
              type="button"
              onClick={onRemoveTable}
              aria-label={`Remove table ${table.name}`}
              data-qb="table-card-btn-remove"
              style={
                unstyled
                  ? undefined
                  : {
                      background: "transparent",
                      border: "none",
                      color: "var(--qb-color-text-muted, #64748b)",
                      cursor: "pointer",
                      padding: "4px 8px",
                      borderRadius: "6px",
                      fontSize: "0.9rem",
                    }
              }
              title="Remove table"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Columns list — clean 3-column grid (minmax(240px, 1fr)) with 14px labels and 8px 12px padding */}
      <div
        data-qb="table-card-columns-list"
        className={cx(classNames?.columnList)}
        style={
          unstyled
            ? undefined
            : isColumnsCollapsed
              ? srOnlyStyle
              : {
                  display: "grid",
                  gridTemplateColumns: "repeat(3, minmax(240px, 1fr))",
                  gap: "4px 12px",
                  maxHeight: "208px",
                  overflowY: "auto",
                  padding: "10px 12px",
                }
        }
      >
        {!unstyled && table.columns.length > 0 && filteredColumns.length === 0 && (
          <div
            style={{
              gridColumn: "1 / -1",
              padding: "12px",
              textAlign: "center",
              color: "var(--qb-color-text-muted, #64748b)",
              fontSize: "0.84rem",
            }}
          >
            No columns matching “{columnSearch.trim()}”
          </div>
        )}
        {filteredColumns.map((col) => {
          const key = `${table.name}.${col.name}`;
          const isColChecked = Boolean(selectedColumns[key]);
          const isFk = Boolean(col.is_foreign_key || col.foreign_key);
          const fkMatch = foreignKeys?.find(
            (fk) => fk.table === table.name && fk.column === col.name && fk.foreign_table !== table.name,
          );
          const targetFkTable = fkMatch ? fkMatch.foreign_table : undefined;
          const isFiltered = Boolean(activeFilterColumns?.has(col.name));
          const sortDirection = activeSortMap?.[col.name];
          const currentAgg = selectedColumns[key]?.aggregate;

          const customRenderer =
            effectiveFieldRenderers?.[col.name] ??
            effectiveFieldRenderers?.[`${table.name}.${col.name}`] ??
            effectiveFieldRenderers?.[col.data_type];

          if (customRenderer) {
            return (
              <div
                key={col.name}
                data-qb="table-card-column-row"
                data-qb-column={col.name}
                data-qb-selected={isColChecked ? "true" : "false"}
                className={cx(classNames?.columnItem)}
              >
                {customRenderer({
                  column: col,
                  table,
                  isSelected: isColChecked,
                  onToggle: () => onToggleColumn(col.name),
                  unstyled,
                })}
              </div>
            );
          }

          const isRowHovered = hoveredCol === col.name;
          const isRowFocused = focusedCol === col.name;
          const shortType = formatShortType(col.data_type);
          const isDragging = draggedColName === col.name;
          const isDragOver = dragOverColName === col.name && draggedColName !== col.name;

          return (
            <div
              key={col.name}
              data-qb="table-card-column-row"
              data-qb-column={col.name}
              data-qb-selected={isColChecked ? "true" : "false"}
              draggable={!unstyled}
              tabIndex={unstyled ? undefined : 0}
              onFocus={() => setFocusedCol(col.name)}
              onBlur={() => setFocusedCol((prev) => (prev === col.name ? null : prev))}
              onKeyDown={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  e.preventDefault();
                  onToggleColumn(col.name);
                }
              }}
              onDragStart={(e) => {
                setDraggedColName(col.name);
                if (e.dataTransfer) {
                  e.dataTransfer.effectAllowed = "move";
                  try {
                    e.dataTransfer.setData("text/plain", col.name);
                  } catch {
                    // Ignore in synthetic test environments
                  }
                }
              }}
              onDragOver={(e) => {
                e.preventDefault();
                if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
                if (dragOverColName !== col.name) setDragOverColName(col.name);
              }}
              onDragEnter={(e) => {
                e.preventDefault();
                setDragOverColName(col.name);
              }}
              onDragLeave={(e) => {
                if (
                  e.relatedTarget instanceof Node &&
                  e.currentTarget.contains(e.relatedTarget)
                ) {
                  return;
                }
                if (dragOverColName === col.name) setDragOverColName(null);
              }}
              onDrop={(e) => {
                e.preventDefault();
                const rawFrom = e.dataTransfer?.getData?.("text/plain");
                const resolvedFrom = draggedColName || rawFrom || null;
                handleDropTableColumn(resolvedFrom, col.name);
              }}
              onDragEnd={() => {
                setDraggedColName(null);
                setDragOverColName(null);
              }}
              onClick={() => onToggleColumn(col.name)}
              onMouseEnter={() => setHoveredCol(col.name)}
              onMouseLeave={() => setHoveredCol((prev) => (prev === col.name ? null : prev))}
              className={cx(classNames?.columnItem)}
              style={
                unstyled
                  ? undefined
                  : {
                      padding: "8px 12px",
                      borderRadius: "6px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: "8px",
                      cursor: "grab",
                      border: isDragOver
                        ? "1px dashed #38bdf8"
                        : undefined,
                      outline: isRowFocused ? "2px solid #38bdf8" : undefined,
                      outlineOffset: "-1px",
                      background: isDragOver
                        ? "rgba(56, 189, 248, 0.16)"
                        : isColChecked
                          ? "var(--qb-color-primary-light, rgba(59, 130, 246, 0.12))"
                          : isRowHovered || isRowFocused
                            ? "var(--qb-color-surface-hover, rgba(255, 255, 255, 0.04))"
                            : "transparent",
                      opacity: isDragging ? 0.55 : 1,
                      transition: "background 0.12s ease",
                      fontSize: "0.875rem",
                      minWidth: 0,
                    }
              }
            >
              <div
                style={
                  unstyled
                    ? undefined
                    : { display: "flex", alignItems: "center", gap: "8px", minWidth: 0, flex: 1 }
                }
              >
                <input
                  type="checkbox"
                  data-qb="table-card-column-checkbox"
                  checked={isColChecked}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => onToggleColumn(col.name)}
                  aria-label={`Select column ${table.name}.${col.name}`}
                  className={cx(classNames?.columnCheckbox)}
                  style={
                    unstyled
                      ? undefined
                      : {
                           cursor: "pointer",
                           accentColor: "var(--qb-color-primary, #3b82f6)",
                           margin: 0,
                           width: "15px",
                           height: "15px",
                           flexShrink: 0,
                         }
                  }
                />
                <span
                  data-qb="table-card-column-name"
                  className={cx(classNames?.columnName)}
                  title={`${col.name} (${col.data_type})`}
                  style={
                    unstyled
                      ? undefined
                      : {
                          color: isColChecked
                            ? "var(--qb-color-text, #f8fafc)"
                            : "var(--qb-color-text-secondary, #cbd5e1)",
                          fontWeight: isColChecked ? 600 : 400,
                          fontSize: "0.875rem",
                          lineHeight: 1.35,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }
                  }
                >
                  {col.name}
                </span>
              </div>
              <div
                style={
                  unstyled
                    ? undefined
                    : { display: "flex", alignItems: "center", gap: "4px", flexShrink: 0 }
                }
              >
                {/* Per-column quick-action buttons kept in DOM via srOnlyStyle for programmatic/test triggers */}
                {onQuickFilterColumn && (
                  <button
                    type="button"
                    aria-label={`Filter by ${col.name}`}
                    data-qb="col-btn-filter"
                    title={isFiltered ? `Filtered by ${col.name}` : `Filter by ${col.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onQuickFilterColumn(table.name, col.name, col.data_type);
                    }}
                    style={unstyled ? undefined : srOnlyStyle}
                  >
                    Filter
                  </button>
                )}

                {onQuickSortColumn && (
                  <button
                    type="button"
                    aria-label={`Sort by ${col.name}`}
                    data-qb="col-btn-sort"
                    title={sortDirection ? `Sorted ${sortDirection}` : `Sort by ${col.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onQuickSortColumn(table.name, col.name);
                    }}
                    style={unstyled ? undefined : srOnlyStyle}
                  >
                    {sortDirection === "ASC" ? "↑" : sortDirection === "DESC" ? "↓" : "⇅"}
                  </button>
                )}

                {onQuickAggregateColumn && (
                  <button
                    type="button"
                    aria-label={`Aggregate ${col.name}`}
                    data-qb="col-btn-aggregate"
                    title={currentAgg ? `Aggregate: ${currentAgg}` : `Cycle aggregate for ${col.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onQuickAggregateColumn(table.name, col.name, currentAgg);
                    }}
                    style={unstyled ? undefined : srOnlyStyle}
                  >
                    {currentAgg ? currentAgg : "Σ"}
                  </button>
                )}

                {targetFkTable && onQuickJoinForeignKey && (
                  <button
                    type="button"
                    aria-label={`Join table ${targetFkTable}`}
                    data-qb="col-btn-fk-join"
                    title={`Join ${targetFkTable}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onQuickJoinForeignKey(targetFkTable);
                    }}
                    style={unstyled ? undefined : srOnlyStyle}
                  >
                    {`🔗 ${targetFkTable}`}
                  </button>
                )}

                {col.is_primary && (
                  <span
                    data-qb="table-card-badge-pk"
                    className={cx(classNames?.tableCardBadge)}
                    title="Primary Key (Unique ID)"
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "var(--qb-color-surface-active, rgba(255, 255, 255, 0.05))",
                            color: "var(--qb-color-text-muted, #94a3b8)",
                            border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                            fontSize: "0.7rem",
                            fontWeight: 600,
                            padding: "1px 5px",
                            borderRadius: "4px",
                          }
                    }
                  >
                    {unstyled ? (
                      "PK"
                    ) : (
                      <>
                        <span style={srOnlyStyle}>PK</span>
                        <span aria-hidden="true">ID</span>
                      </>
                    )}
                  </span>
                )}
                {isFk && !targetFkTable && (
                  <span
                    data-qb="table-card-badge-fk"
                    className={cx(classNames?.tableCardBadge)}
                    style={unstyled ? undefined : srOnlyStyle}
                  >
                    FK
                  </span>
                )}
                {!unstyled && !col.is_primary && shortType && (
                  <>
                    <span style={srOnlyStyle}>{shortType}</span>
                    {(isRowHovered || isRowFocused) && (
                      <span
                        aria-hidden="true"
                        title={col.data_type}
                        style={{
                          fontSize: "0.72rem",
                          color: "var(--qb-color-text-muted, #64748b)",
                          opacity: 0.85,
                        }}
                      >
                        {formatFriendlyType(col.data_type)}
                      </span>
                    )}
                  </>
                )}
                <span
                  data-qb="table-card-column-type"
                  className={cx(classNames?.columnType)}
                  title={col.data_type}
                  style={unstyled ? undefined : srOnlyStyle}
                >
                  {col.data_type}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Metrics list */}
      {table.metrics && table.metrics.length > 0 && (
        <div
          data-qb="table-card-metrics-section"
          style={
            unstyled
              ? undefined
              : {
                  borderTop: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.07))",
                  padding: "8px 0",
                  background: "var(--qb-color-surface, #10141f)",
                }
          }
        >
          <div
            style={
              unstyled
                ? undefined
                : {
                    padding: "4px 14px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    color: "var(--qb-color-text-muted, #64748b)",
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                  }
            }
          >
            {unstyled ? (
              <span>📈 Metrics ({table.metrics.length})</span>
            ) : (
              <span>
                <span style={srOnlyStyle}>📈 </span>
                {`Metrics (${table.metrics.length})`}
              </span>
            )}
          </div>
          {table.metrics.map((metric) => {
            const key = `${table.name}.${metric.name}`;
            const isMetricChecked = Boolean(selectedColumns[key]);
            return (
              <div
                key={metric.name}
                data-qb="table-card-metric-row"
                data-qb-metric={metric.name}
                data-qb-selected={isMetricChecked ? "true" : "false"}
                onClick={() => onToggleColumn(metric.name)}
                title={metric.description || `${metric.title} (${metric.aggregation})`}
                style={
                  unstyled
                    ? undefined
                    : {
                        padding: "6px 14px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        cursor: "pointer",
                        background: isMetricChecked
                          ? "var(--qb-color-primary-light, rgba(59, 130, 246, 0.12))"
                          : "transparent",
                        transition: "background 0.15s ease",
                        fontSize: "0.875rem",
                      }
                }
              >
                <div
                  style={
                    unstyled
                      ? undefined
                      : { display: "flex", alignItems: "center", gap: "8px" }
                  }
                >
                  <input
                    type="checkbox"
                    data-qb="table-card-metric-checkbox"
                    checked={isMetricChecked}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => onToggleColumn(metric.name)}
                    aria-label={`Select metric ${table.name}.${metric.name}`}
                    style={unstyled ? undefined : { cursor: "pointer", width: "15px", height: "15px" }}
                  />
                  <span
                    data-qb="table-card-metric-name"
                    style={
                      unstyled
                        ? undefined
                        : {
                            color: isMetricChecked
                              ? "var(--qb-color-text, #f8fafc)"
                              : "var(--qb-color-text-secondary, #cbd5e1)",
                            fontWeight: isMetricChecked ? 600 : 400,
                          }
                    }
                  >
                    {metric.title || metric.name}
                  </span>
                </div>
                <span
                  data-qb="table-card-metric-badge"
                  className={cx(classNames?.tableCardBadge)}
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "rgba(255, 255, 255, 0.05)",
                          color: "var(--qb-color-text-muted, #94a3b8)",
                          fontSize: "0.72rem",
                          fontWeight: 600,
                          padding: "2px 6px",
                          borderRadius: "4px",
                          textTransform: "uppercase",
                        }
                  }
                >
                  {metric.aggregation || "metric"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
