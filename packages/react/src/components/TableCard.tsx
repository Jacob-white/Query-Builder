import React from "react";
import type { TableMeta, VisualColumnSelect, CustomFieldRenderer, QueryBuilderClassNames } from "../types";
import { cx } from "../utils/classNames";

export interface TableCardProps {
  table: TableMeta;
  isSelected?: boolean;
  selectedColumns: Record<string, VisualColumnSelect>;
  onToggleColumn: (colName: string) => void;
  onRemoveTable?: () => void;
  onAddJoin?: () => void;
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
  unstyled = false,
  fieldRenderers,
  className,
  classNames,
}) => {
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
                background: "rgba(15, 23, 42, 0.9)",
                borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
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
        </div>
        <div style={unstyled ? undefined : { display: "flex", gap: "4px" }}>
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
                      color: "#60a5fa",
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
                      color: "#ef4444",
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
        {table.columns.map((col) => {
          const key = `${table.name}.${col.name}`;
          const isColChecked = Boolean(selectedColumns[key]);

          const customRenderer =
            fieldRenderers?.[col.name] ??
            fieldRenderers?.[`${table.name}.${col.name}`] ??
            fieldRenderers?.[col.data_type];

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
                      background: isColChecked ? "rgba(59, 130, 246, 0.12)" : "transparent",
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
                  data-qb="table-card-column-checkbox"
                  checked={isColChecked}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => onToggleColumn(col.name)}
                  aria-label={`Select column ${table.name}.${col.name}`}
                  className={cx(classNames?.columnCheckbox)}
                  style={unstyled ? undefined : { cursor: "pointer" }}
                />
                <span
                  data-qb="table-card-column-name"
                  className={cx(classNames?.columnName)}
                  style={
                    unstyled
                      ? undefined
                      : {
                          color: isColChecked ? "#93c5fd" : "#cbd5e1",
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
                {col.is_primary && (
                  <span
                    data-qb="table-card-badge-pk"
                    className={cx(classNames?.tableCardBadge)}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "rgba(245, 158, 11, 0.2)",
                            color: "#fbbf24",
                            fontSize: "0.65rem",
                            fontWeight: 700,
                            padding: "1px 4px",
                            borderRadius: "4px",
                          }
                    }
                  >
                    PK
                  </span>
                )}
                <span
                  data-qb="table-card-column-type"
                  className={cx(classNames?.columnType)}
                  style={
                    unstyled
                      ? undefined
                      : { color: "#64748b", fontSize: "0.7rem" }
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
                  borderTop: "1px solid rgba(255, 255, 255, 0.08)",
                  padding: "6px 0",
                  background: "rgba(15, 23, 42, 0.4)",
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
                    color: "#94a3b8",
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
                          ? "rgba(16, 185, 129, 0.15)"
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
