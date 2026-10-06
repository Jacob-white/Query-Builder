import React from "react";
import type {
  TableMeta,
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  SchemaSnapshot,
  CustomFilterOperator,
  CustomFieldRenderer,
  VectorSearchSpec,
  HybridSearchSpec,
} from "../types";
import { TableCard } from "./TableCard";
import { TableFiltersEditor } from "./TableFiltersEditor";
import { TableJoinEditor } from "./TableJoinEditor";
import { TableSortsEditor } from "./TableSortsEditor";
import { VectorHybridControl } from "./VectorHybridControl";

export interface QueryCanvasProps {
  schema?: SchemaSnapshot | null;
  activeTables: TableMeta[];
  primaryTable: string;
  selectedColumns: Record<string, VisualColumnSelect>;
  orderedProjectionKeys: string[];
  joins: VisualJoin[];
  filters: VisualFilter[];
  sorts: VisualSort[];
  isDistinct: boolean;
  limit: number;
  vectorSearch?: VectorSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  onToggleColumn: (tableName: string, colName: string) => void;
  onRemoveTable: (tableName: string) => void;
  onAddTableToCanvas: (tableName: string) => void;
  onAddJoin?: (tableName: string) => void;
  onReorderProjections?: (keys: string[]) => void;
  onUpdateColumnSelect: (key: string, updates: Partial<VisualColumnSelect>) => void;
  onRemoveColumnProjection: (key: string) => void;
  onJoinsChange: (joins: VisualJoin[]) => void;
  onFiltersChange: (filters: VisualFilter[]) => void;
  onSortsChange: (sorts: VisualSort[]) => void;
  onDistinctChange: (distinct: boolean) => void;
  onLimitChange: (limit: number) => void;
  onVectorChange?: (vs: VectorSearchSpec | null) => void;
  onHybridChange?: (hs: HybridSearchSpec | null) => void;
  unstyled?: boolean;
  customOperators?: Record<string, CustomFilterOperator>;
  fieldRenderers?: Record<string, CustomFieldRenderer>;
}

export const QueryCanvas: React.FC<QueryCanvasProps> = ({
  schema,
  activeTables,
  primaryTable,
  selectedColumns,
  orderedProjectionKeys,
  joins = [],
  filters = [],
  sorts = [],
  isDistinct,
  limit,
  vectorSearch,
  hybridSearch,
  onToggleColumn,
  onRemoveTable,
  onAddTableToCanvas,
  onAddJoin,
  onReorderProjections,
  onUpdateColumnSelect,
  onRemoveColumnProjection,
  onJoinsChange,
  onFiltersChange,
  onSortsChange,
  onDistinctChange,
  onLimitChange,
  onVectorChange,
  onHybridChange,
  unstyled = false,
  customOperators,
  fieldRenderers,
}) => {
  const allTables = Object.values(schema?.tables || {});
  const availableToAdd = allTables.filter(
    (t) => !activeTables.some((a) => a.name === t.name),
  );

  const handleMoveProjection = (index: number, direction: -1 | 1) => {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= orderedProjectionKeys.length) return;
    const newKeys = [...orderedProjectionKeys];
    const temp = newKeys[index];
    newKeys[index] = newKeys[targetIndex];
    newKeys[targetIndex] = temp;
    if (onReorderProjections) {
      onReorderProjections(newKeys);
    }
  };

  return (
    <div
      data-qb="canvas"
      style={
        unstyled
          ? undefined
          : {
              display: "flex",
              flexDirection: "column",
              gap: "16px",
              fontFamily: "system-ui, -apple-system, sans-serif",
            }
      }
    >
      {/* Tables row / workspace */}
      <div
        data-qb="canvas-tables"
        style={unstyled ? undefined : { display: "flex", flexDirection: "column", gap: "10px" }}
      >
        <div
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
                : { fontSize: "0.88rem", fontWeight: 700, color: "#cbd5e1" }
            }
          >
            📋 Active Tables in Query ({activeTables.length})
          </span>
          {availableToAdd.length > 0 && (
            <select
              defaultValue=""
              data-qb="select-add-table"
              onChange={(e) => {
                if (e.target.value) {
                  onAddTableToCanvas(e.target.value);
                  e.target.value = "";
                }
              }}
              style={
                unstyled
                  ? undefined
                  : {
                      background: "#1e293b",
                      color: "#60a5fa",
                      border: "1px solid rgba(59, 130, 246, 0.4)",
                      borderRadius: "6px",
                      padding: "4px 10px",
                      fontSize: "0.78rem",
                      cursor: "pointer",
                      fontWeight: 600,
                    }
              }
            >
              <option value="" disabled>
                + Add Table to Canvas...
              </option>
              {availableToAdd.map((t) => (
                <option key={t.name} value={t.name}>
                  + {t.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {activeTables.length === 0 ? (
          <div
            data-qb="canvas-empty-state"
            style={
              unstyled
                ? undefined
                : {
                    padding: "32px",
                    textAlign: "center",
                    color: "#94a3b8",
                    border: "2px dashed rgba(255, 255, 255, 0.1)",
                    borderRadius: "10px",
                    width: "100%",
                  }
            }
          >
            No tables in query. Select a table to start building.
          </div>
        ) : (
          <div
            data-qb="table-cards-list"
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    gap: "16px",
                    overflowX: "auto",
                    paddingBottom: "8px",
                  }
            }
          >
            {activeTables.map((t) => (
              <TableCard
                key={t.name}
                table={t}
                isSelected={t.name === primaryTable}
                selectedColumns={selectedColumns}
                onToggleColumn={(col) => onToggleColumn(t.name, col)}
                onRemoveTable={() => onRemoveTable(t.name)}
                onAddJoin={() => (onAddJoin ? onAddJoin(t.name) : onAddTableToCanvas(t.name))}
                unstyled={unstyled}
                fieldRenderers={fieldRenderers}
              />
            ))}
          </div>
        )}
      </div>

      {/* Projection fields manager */}
      {orderedProjectionKeys.length > 0 && (
        <div
          data-qb="canvas-projections"
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
              ✨ Selected Columns & Projections ({orderedProjectionKeys.length})
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
                  onChange={(e) => onDistinctChange(e.target.checked)}
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
                  onChange={(e) => onLimitChange(Number(e.target.value))}
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
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "rgba(30, 41, 59, 0.7)",
                          border: "1px solid rgba(255, 255, 255, 0.1)",
                          borderRadius: "6px",
                          padding: "4px 8px",
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          fontSize: "0.78rem",
                        }
                  }
                >
                  {idx > 0 && (
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
                  )}

                  <span
                    style={
                      unstyled
                        ? undefined
                        : { color: "#93c5fd", fontWeight: 600 }
                    }
                  >
                    {item.table}.{item.name}
                  </span>

                  <input
                    type="text"
                    aria-label={`Alias for ${key}`}
                    data-qb="projection-alias-input"
                    placeholder="alias"
                    value={item.alias || ""}
                    onChange={(e) =>
                      onUpdateColumnSelect(key, { alias: e.target.value })
                    }
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

                  <select
                    value={item.aggregate || ""}
                    onChange={(e) =>
                      onUpdateColumnSelect(key, {
                        aggregate: e.target.value as VisualColumnSelect["aggregate"],
                      })
                    }
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

                  {idx < orderedProjectionKeys.length - 1 && (
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
                  )}

                  <button
                    type="button"
                    onClick={() => onRemoveColumnProjection(key)}
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
      )}

      {/* Relational Joins */}
      <TableJoinEditor
        joins={joins}
        activeTables={activeTables}
        allTables={allTables}
        schema={schema}
        onChange={onJoinsChange}
        unstyled={unstyled}
      />

      {/* Filter Conditions */}
      <TableFiltersEditor
        filters={filters}
        activeTables={activeTables}
        onChange={onFiltersChange}
        unstyled={unstyled}
        customOperators={customOperators}
      />

      {/* Sorting */}
      <TableSortsEditor
        sorts={sorts}
        activeTables={activeTables}
        onChange={onSortsChange}
        unstyled={unstyled}
      />

      {/* Semantic Vector & Hybrid Retrieval */}
      {onVectorChange && onHybridChange && (
        <VectorHybridControl
          vectorSearch={vectorSearch}
          hybridSearch={hybridSearch}
          activeTables={activeTables}
          onVectorChange={onVectorChange}
          onHybridChange={onHybridChange}
          unstyled={unstyled}
        />
      )}
    </div>
  );
};
