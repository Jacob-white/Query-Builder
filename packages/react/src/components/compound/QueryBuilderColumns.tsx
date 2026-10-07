import React from "react";
import type { QueryBuilderClassNames, VisualColumnSelect } from "../../types";
import { useCompoundQueryBuilder } from "./QueryBuilderContext";
import { cx } from "../../utils/classNames";

export interface QueryBuilderColumnsProps {
  /** Optional container class name */
  className?: string;
  /** Granular slot class names mapping */
  classNames?: QueryBuilderClassNames;
  /** Unstyled mode flag */
  unstyled?: boolean;
}

export const QueryBuilderColumns: React.FC<QueryBuilderColumnsProps> = ({
  className,
  classNames: propClassNames,
  unstyled: propUnstyled,
}) => {
  const {
    selectedColumns,
    orderedProjectionKeys,
    isDistinct,
    limit,
    actions,
    unstyled: rootUnstyled,
    classNames: rootClassNames,
  } = useCompoundQueryBuilder();

  const unstyled = propUnstyled ?? rootUnstyled;
  const classNames = propClassNames || rootClassNames;

  const handleMoveProjection = (index: number, direction: -1 | 1) => {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= orderedProjectionKeys.length) return;
    const newKeys = [...orderedProjectionKeys];
    const temp = newKeys[index];
    newKeys[index] = newKeys[targetIndex];
    newKeys[targetIndex] = temp;
    actions.setOrderedProjectionKeys(newKeys);
  };

  if (orderedProjectionKeys.length === 0) {
    return (
      <div
        data-qb="canvas-projections"
        className={cx(className, classNames?.columns)}
        style={
          unstyled
            ? undefined
            : {
                background: "rgba(15, 23, 42, 0.6)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "8px",
                padding: "12px",
                display: "flex",
                flexDirection: "column",
                gap: "10px",
              }
        }
      >
        <span
          style={
            unstyled
              ? undefined
              : { fontSize: "0.82rem", color: "#64748b", fontStyle: "italic" }
          }
        >
          No columns selected. Check columns on table cards above to add projections.
        </span>
      </div>
    );
  }

  return (
    <div
      data-qb="canvas-projections"
      className={cx(className, classNames?.columns)}
      style={
        unstyled
          ? undefined
          : {
              background: "rgba(15, 23, 42, 0.6)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "8px",
              padding: "12px",
              display: "flex",
              flexDirection: "column",
              gap: "10px",
            }
      }
    >
      <div
        data-qb="canvas-options"
        className={cx(classNames?.columnsHeader)}
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
          {`✨ Selected Columns & Projections (${orderedProjectionKeys.length})`}
        </span>
        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", alignItems: "center", gap: "10px" }
          }
        >
          <label
            style={
              unstyled
                ? undefined
                : {
                    fontSize: "0.78rem",
                    color: "#cbd5e1",
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    cursor: "pointer",
                  }
            }
          >
            <input
              type="checkbox"
              data-qb="checkbox-distinct"
              checked={isDistinct}
              onChange={(e) => actions.setDistinct(e.target.checked)}
            />
            DISTINCT
          </label>
          <div
            style={
              unstyled
                ? undefined
                : { display: "flex", alignItems: "center", gap: "6px" }
            }
          >
            <span style={unstyled ? undefined : { fontSize: "0.75rem", color: "#64748b" }}>
              Limit:
            </span>
            <select
              value={limit}
              data-qb="input-limit"
              aria-label="Query result limit"
              onChange={(e) => actions.setLimit(Number(e.target.value))}
              style={
                unstyled
                  ? undefined
                  : {
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #475569",
                      borderRadius: "4px",
                      padding: "2px 6px",
                      fontSize: "0.75rem",
                    }
              }
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={500}>500</option>
              {![10, 25, 50, 100, 500].includes(limit) && (
                <option value={limit}>{limit}</option>
              )}
            </select>
          </div>
        </div>
      </div>

      <div
        style={
          unstyled
            ? undefined
            : { display: "flex", flexWrap: "wrap", gap: "8px" }
        }
      >
        {orderedProjectionKeys.map((key, idx) => {
          const item = selectedColumns[key];
          if (!item) return null;

          return (
            <div
              key={key}
              data-qb="projection-item"
              data-qb-column={key}
              className={cx(classNames?.projectionItem)}
              style={
                unstyled
                  ? undefined
                  : {
                      background: "rgba(30, 41, 59, 0.7)",
                      border: "1px solid rgba(59, 130, 246, 0.3)",
                      borderRadius: "6px",
                      padding: "4px 8px",
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      fontSize: "0.78rem",
                      color: "#e2e8f0",
                    }
              }
            >
              <button
                type="button"
                aria-label={`Move ${key} left`}
                data-qb="projection-move-left"
                onClick={() => handleMoveProjection(idx, -1)}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "transparent",
                        border: "none",
                        color: "#94a3b8",
                        cursor: "pointer",
                        padding: "1px 3px",
                        fontSize: "0.7rem",
                      }
                }
                title="Move left"
              >
                ◀
              </button>

              <span style={{ fontWeight: 600 }}>
                {item.table}.{item.name}
              </span>

              <input
                type="text"
                aria-label={`Alias for ${key}`}
                data-qb="projection-alias-input"
                placeholder="alias"
                value={item.alias || ""}
                onChange={(e) =>
                  actions.updateColumnSelect(key, { alias: e.target.value })
                }
                className={cx(classNames?.projectionAlias)}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "#0f172a",
                        border: "1px solid #334155",
                        borderRadius: "4px",
                        padding: "1px 6px",
                        color: "#38bdf8",
                        fontSize: "0.7rem",
                        width: "60px",
                      }
                }
              />

              {item.metric && (
                <span
                  data-qb="projection-metric-badge"
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
                        }
                  }
                >
                  Σ Metric
                </span>
              )}

              {!item.metric && (
                <select
                  value={item.timeGrain || ""}
                  data-qb="projection-timegrain-select"
                  aria-label={`Time grain for ${key}`}
                  onChange={(e) =>
                    actions.updateColumnSelect(key, {
                      timeGrain: (e.target.value as any) || undefined,
                    })
                  }
                  className={cx(classNames?.projectionSelect)}
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "#0f172a",
                          color: item.timeGrain ? "#a78bfa" : "#64748b",
                          border: "1px solid #334155",
                          borderRadius: "4px",
                          padding: "1px 4px",
                          fontSize: "0.7rem",
                        }
                  }
                >
                  <option value="">(no grain)</option>
                  <option value="day">Day</option>
                  <option value="week">Week</option>
                  <option value="month">Month</option>
                  <option value="quarter">Quarter</option>
                  <option value="year">Year</option>
                  <option value="hour">Hour</option>
                  <option value="minute">Minute</option>
                  <option value="second">Second</option>
                </select>
              )}

              {!item.metric && !item.timeGrain && (
                <select
                  value={item.aggregate || ""}
                  aria-label={`Aggregate for ${key}`}
                  onChange={(e) =>
                    actions.updateColumnSelect(key, {
                      aggregate: e.target.value as VisualColumnSelect["aggregate"],
                    })
                  }
                  className={cx(classNames?.projectionSelect)}
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "#0f172a",
                          color: item.aggregate ? "#f59e0b" : "#64748b",
                          border: "1px solid #334155",
                          borderRadius: "4px",
                          padding: "1px 4px",
                          fontSize: "0.7rem",
                        }
                  }
                >
                  <option value="">(none)</option>
                  <option value="COUNT">COUNT</option>
                  <option value="SUM">SUM</option>
                  <option value="AVG">AVG</option>
                  <option value="MIN">MIN</option>
                  <option value="MAX">MAX</option>
                </select>
              )}

              <button
                type="button"
                aria-label={`Move ${key} right`}
                data-qb="projection-move-right"
                onClick={() => handleMoveProjection(idx, 1)}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "transparent",
                        border: "none",
                        color: "#94a3b8",
                        cursor: "pointer",
                        padding: "1px 3px",
                        fontSize: "0.7rem",
                      }
                }
                title="Move right"
              >
                ▶
              </button>

              <button
                type="button"
                onClick={() => actions.removeColumnProjection(key)}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "transparent",
                        border: "none",
                        color: "#94a3b8",
                        cursor: "pointer",
                        fontSize: "0.75rem",
                      }
                }
                title="Remove column"
              >
                ✕
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};
