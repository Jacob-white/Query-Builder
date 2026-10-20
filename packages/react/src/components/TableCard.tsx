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

  const selectedCount = table.columns.filter(
    (c) => Boolean(selectedColumns[`${table.name}.${c.name}`]),
  ).length;

  const filteredColumns = columnSearch.trim()
    ? table.columns.filter((c) =>
        c.name.toLowerCase().includes(columnSearch.trim().toLowerCase()),
      )
    : table.columns;

  const handleSelectAll = () => {
    table.columns.forEach((col) => {
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
              background: "var(--qb-color-surface, rgba(30, 41, 59, 0.85))",
              backdropFilter: "blur(12px)",
              WebkitBackdropFilter: "blur(12px)",
              borderRadius: "var(--qb-radius-lg, 10px)",
              border: isSelected
                ? "1.5px solid #3b82f6"
                : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
              boxShadow: isSelected
                ? "0 0 0 2px rgba(59, 130, 246, 0.25), var(--qb-shadow-lg, 0 10px 24px rgba(0, 0, 0, 0.3))"
                : "var(--qb-shadow-md, 0 4px 16px rgba(0, 0, 0, 0.18))",
              overflow: "hidden",
              width: "290px",
              display: "flex",
              flexDirection: "column",
              color: "var(--qb-color-text, #f8fafc)",
              fontFamily: "var(--qb-font-family, system-ui, -apple-system, sans-serif)",
              transition: "border-color 0.15s ease, box-shadow 0.15s ease",
            }
      }
    >
      {/* Header */}
      <div
        data-qb="table-card-header"
        className={cx(classNames?.tableCardHeader)}
        style={
          unstyled
            ? undefined
            : {
                padding: "10px 14px",
                background: "var(--qb-color-surface-hover, rgba(15, 23, 42, 0.9))",
                borderBottom: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }
        }
      >
        <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "6px" }}>
          <span style={unstyled ? undefined : { fontSize: "1rem" }}>🗄️</span>
          <span
            data-qb="table-card-title"
            className={cx(classNames?.tableCardTitle)}
            style={unstyled ? undefined : { fontWeight: 600, fontSize: "0.88rem" }}
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
                      fontSize: "0.68rem",
                      padding: "1px 6px",
                      borderRadius: "10px",
                      background: "var(--qb-color-primary-light, rgba(59, 130, 246, 0.15))",
                      color: "var(--qb-color-primary, #60a5fa)",
                      fontWeight: 600,
                    }
              }
              title={`${selectedCount} of ${table.columns.length} columns selected`}
            >
              {selectedCount}/{table.columns.length}
            </span>
          )}
        </div>
        <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "4px" }}>
          <button
            type="button"
            onClick={handleSelectAll}
            aria-label={`Select all columns in ${table.name}`}
            data-qb="table-card-btn-select-all"
            style={
              unstyled
                ? undefined
                : {
                    background: "var(--qb-color-primary-light, rgba(59, 130, 246, 0.12))",
                    border: "1px solid var(--qb-color-primary, rgba(59, 130, 246, 0.3))",
                    color: "var(--qb-color-primary, #93c5fd)",
                    cursor: "pointer",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    fontSize: "0.68rem",
                    fontWeight: 600,
                    transition: "all 0.15s ease",
                  }
            }
            title="Select all columns"
          >
            All
          </button>
          <button
            type="button"
            onClick={handleClearAll}
            aria-label={`Clear all columns in ${table.name}`}
            data-qb="table-card-btn-clear-all"
            style={
              unstyled
                ? undefined
                : {
                    background: "var(--qb-color-surface-active, rgba(148, 163, 184, 0.1))",
                    border: "1px solid var(--qb-color-border, rgba(148, 163, 184, 0.25))",
                    color: "var(--qb-color-text-muted, #94a3b8)",
                    cursor: "pointer",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    fontSize: "0.68rem",
                    fontWeight: 600,
                    transition: "all 0.15s ease",
                  }
            }
            title="Clear all columns"
          >
            Clear
          </button>
          {onAddJoin && (
            <button
              type="button"
              onClick={onAddJoin}
              aria-label={`Add join for table ${table.name}`}
              data-qb="table-card-btn-join"
              style={
                unstyled
                  ? undefined
                : {
                    background: "transparent",
                    border: "none",
                    color: "var(--qb-color-primary, #60a5fa)",
                    cursor: "pointer",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    fontSize: "0.75rem",
                  }
              }
              title="Add Join to this table"
            >
              🔗
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
                      color: "var(--qb-color-error, #ef4444)",
                      cursor: "pointer",
                      padding: "2px 6px",
                      borderRadius: "4px",
                      fontSize: "0.85rem",
                    }
              }
              title="Remove table"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Column filter search input when > 6 columns */}
      {table.columns.length > 6 && (
        <div
          style={
            unstyled
              ? undefined
              : {
                  padding: "6px 12px",
                  borderBottom: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.06))",
                  background: "var(--qb-color-surface, rgba(15, 23, 42, 0.5))",
                  position: "relative",
                  display: "flex",
                  alignItems: "center",
                }
          }
        >
          <input
            type="text"
            value={columnSearch}
            onChange={(e) => setColumnSearch(e.target.value)}
            placeholder="Filter columns..."
            aria-label={`Filter columns in ${table.name}`}
            data-qb="table-card-column-search"
            style={
              unstyled
                ? undefined
                : {
                    width: "100%",
                    boxSizing: "border-box",
                    background: "var(--qb-color-background, #0f172a)",
                    color: "var(--qb-color-text, #f8fafc)",
                    border: "1px solid var(--qb-color-border, #334155)",
                    borderRadius: "6px",
                    padding: columnSearch ? "4px 24px 4px 8px" : "4px 8px",
                    fontSize: "0.75rem",
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
                right: "18px",
                background: "transparent",
                border: "none",
                color: "var(--qb-color-text-muted, #94a3b8)",
                cursor: "pointer",
                padding: "2px 4px",
                fontSize: "0.75rem",
              }}
            >
              ✕
            </button>
          )}
        </div>
      )}

      {/* Columns list */}
      <div
        data-qb="table-card-columns-list"
        className={cx(classNames?.columnList)}
        style={
          unstyled
            ? undefined
            : {
                maxHeight: "260px",
                overflowY: "auto",
                padding: "6px 0",
              }
        }
      >
        {filteredColumns.map((col) => {
          const key = `${table.name}.${col.name}`;
          const isColChecked = Boolean(selectedColumns[key]);
          const isFk = Boolean(col.is_foreign_key || col.foreign_key);
          const fkMatch = foreignKeys?.find(
            (fk) =>
              (fk.table === table.name && fk.column === col.name) ||
              (fk.foreign_table === table.name && fk.foreign_column === col.name),
          );
          const targetFkTable = fkMatch
            ? fkMatch.table === table.name
              ? fkMatch.foreign_table
              : fkMatch.table
            : undefined;
          const isFiltered = activeFilterColumns?.has(col.name);
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

          return (
            <div
              key={col.name}
              data-qb="table-card-column-row"
              data-qb-column={col.name}
              data-qb-selected={isColChecked ? "true" : "false"}
              onClick={() => onToggleColumn(col.name)}
              className={cx(classNames?.columnItem)}
              style={
                unstyled
                  ? undefined
                  : {
                      padding: "6px 14px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      cursor: "pointer",
                      background: isColChecked
                        ? "var(--qb-color-primary-light, rgba(59, 130, 246, 0.12))"
                        : "transparent",
                      transition: "background 0.15s ease",
                      fontSize: "0.8rem",
                      borderBottom: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.03))",
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
                  data-qb="table-card-column-checkbox"
                  checked={isColChecked}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => onToggleColumn(col.name)}
                  aria-label={`Select column ${table.name}.${col.name}`}
                  className={cx(classNames?.columnCheckbox)}
                  style={unstyled ? undefined : { cursor: "pointer", accentColor: "var(--qb-color-primary, #3b82f6)" }}
                />
                <span
                  data-qb="table-card-column-name"
                  className={cx(classNames?.columnName)}
                  style={
                    unstyled
                      ? undefined
                      : {
                          color: isColChecked
                            ? "var(--qb-color-primary, #93c5fd)"
                            : "var(--qb-color-text-secondary, #cbd5e1)",
                          fontWeight: isColChecked ? 600 : 400,
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
                    : { display: "flex", alignItems: "center", gap: "4px" }
                }
              >
                {/* Column quick-action buttons */}
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
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: isFiltered ? "rgba(245, 158, 11, 0.2)" : "transparent",
                            color: isFiltered ? "#fbbf24" : "var(--qb-color-text-muted, #94a3b8)",
                            border: isFiltered ? "1px solid rgba(245, 158, 11, 0.4)" : "none",
                            borderRadius: "4px",
                            padding: "1px 4px",
                            fontSize: "0.72rem",
                            cursor: "pointer",
                            lineHeight: 1,
                          }
                    }
                  >
                    🔍
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
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: sortDirection ? "rgba(59, 130, 246, 0.2)" : "transparent",
                            color:
                              sortDirection === "ASC"
                                ? "#60a5fa"
                                : sortDirection === "DESC"
                                  ? "#f472b6"
                                  : "var(--qb-color-text-muted, #94a3b8)",
                            border: sortDirection ? "1px solid rgba(59, 130, 246, 0.4)" : "none",
                            borderRadius: "4px",
                            padding: "1px 4px",
                            fontSize: "0.72rem",
                            cursor: "pointer",
                            lineHeight: 1,
                          }
                    }
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
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: currentAgg ? "rgba(16, 185, 129, 0.2)" : "transparent",
                            color: currentAgg ? "#34d399" : "var(--qb-color-text-muted, #94a3b8)",
                            border: currentAgg ? "1px solid rgba(16, 185, 129, 0.4)" : "none",
                            borderRadius: "4px",
                            padding: "1px 4px",
                            fontSize: "0.72rem",
                            cursor: "pointer",
                            lineHeight: 1,
                          }
                    }
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
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "rgba(56, 189, 248, 0.15)",
                            color: "#38bdf8",
                            border: "1px solid rgba(56, 189, 248, 0.35)",
                            borderRadius: "4px",
                            padding: "1px 5px",
                            fontSize: "0.68rem",
                            cursor: "pointer",
                            fontWeight: 600,
                            lineHeight: 1,
                          }
                    }
                  >
                    🔗 {targetFkTable}
                  </button>
                )}

                {col.is_primary && (
                  <span
                    data-qb="table-card-badge-pk"
                    className={cx(classNames?.tableCardBadge)}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "rgba(245, 158, 11, 0.2)",
                            color: "var(--qb-color-warning, #fbbf24)",
                            border: "1px solid rgba(245, 158, 11, 0.4)",
                            fontSize: "0.65rem",
                            fontWeight: 700,
                            padding: "1px 5px",
                            borderRadius: "4px",
                          }
                    }
                  >
                    PK
                  </span>
                )}
                {isFk && !targetFkTable && (
                  <span
                    data-qb="table-card-badge-fk"
                    className={cx(classNames?.tableCardBadge)}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "rgba(56, 189, 248, 0.18)",
                            color: "#38bdf8",
                            border: "1px solid rgba(56, 189, 248, 0.4)",
                            fontSize: "0.65rem",
                            fontWeight: 700,
                            padding: "1px 5px",
                            borderRadius: "4px",
                          }
                    }
                  >
                    FK
                  </span>
                )}
                <span
                  data-qb="table-card-column-type"
                  className={cx(classNames?.columnType)}
                  style={
                    unstyled
                      ? undefined
                      : {
                          color: "var(--qb-color-text-muted, #64748b)",
                          fontSize: "0.7rem",
                          fontFamily: "var(--qb-font-mono, monospace)",
                        }
                  }
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
                  borderTop: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                  padding: "6px 0",
                  background: "var(--qb-color-surface, rgba(15, 23, 42, 0.4))",
                }
          }
        >
          <div
            style={
              unstyled
                ? undefined
                : {
                    padding: "4px 14px",
                    fontSize: "0.68rem",
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    color: "var(--qb-color-text-muted, #94a3b8)",
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                  }
            }
          >
            <span>📈 Metrics ({table.metrics.length})</span>
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
                        padding: "5px 14px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        cursor: "pointer",
                        background: isMetricChecked
                          ? "var(--qb-color-success-light, rgba(16, 185, 129, 0.15))"
                          : "transparent",
                        transition: "background 0.15s ease",
                        fontSize: "0.8rem",
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
                    style={unstyled ? undefined : { cursor: "pointer" }}
                  />
                  <span
                    data-qb="table-card-metric-name"
                    style={
                      unstyled
                        ? undefined
                        : {
                            color: isMetricChecked ? "#6ee7b7" : "#cbd5e1",
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
                          background: "rgba(16, 185, 129, 0.2)",
                          color: "#34d399",
                          fontSize: "0.65rem",
                          fontWeight: 700,
                          padding: "1px 5px",
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
