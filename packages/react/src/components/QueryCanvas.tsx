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
  QueryBuilderClassNames,
  TimeGrain,
  CalculatedFieldSpec,
  WindowFunctionSpec,
} from "../types";
import { TableCard } from "./TableCard";
import { TableFiltersEditor } from "./TableFiltersEditor";
import { TableJoinEditor } from "./TableJoinEditor";
import { TableSortsEditor } from "./TableSortsEditor";
import { VectorHybridControl } from "./VectorHybridControl";
import { CalculatedFieldEditor } from "./CalculatedFieldEditor";
import { QuerySummaryBar } from "./QuerySummaryBar";
import { directLinks, describeLink } from "../utils/queryHelpers/joinLinks";
import { useQueryBuilderContext } from "../theme/QueryBuilderProvider";
import { cx } from "../utils/classNames";

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
  windowFunctions?: WindowFunctionSpec[];
  compiledSql?: string;
  onToggleColumn: (tableName: string, colName: string) => void;
  onRemoveTable: (tableName: string) => void;
  onAddTableToCanvas: (tableName: string) => void;
  onAddJoin?: (tableName: string) => void;
  onReorderProjections?: (keys: string[]) => void;
  onUpdateColumnSelect: (key: string, updates: Partial<VisualColumnSelect>) => void;
  onRemoveColumnProjection: (key: string) => void;
  onAddCalculatedField?: (field: CalculatedFieldSpec) => void;
  onRemoveWindowFunction?: (index: number) => void;
  onOpenWindowFunctions?: () => void;
  onJoinsChange: (joins: VisualJoin[]) => void;
  onFiltersChange: (filters: VisualFilter[]) => void;
  onSortsChange: (sorts: VisualSort[]) => void;
  onDistinctChange: (distinct: boolean) => void;
  onLimitChange: (limit: number) => void;
  onVectorChange?: (vs: VectorSearchSpec | null) => void;
  onHybridChange?: (hs: HybridSearchSpec | null) => void;
  unstyled?: boolean;
  className?: string;
  classNames?: QueryBuilderClassNames;
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
  windowFunctions = [],
  compiledSql,
  onToggleColumn,
  onRemoveTable,
  onAddTableToCanvas,
  onAddJoin,
  onReorderProjections,
  onUpdateColumnSelect,
  onRemoveColumnProjection,
  onAddCalculatedField,
  onRemoveWindowFunction,
  onJoinsChange,
  onFiltersChange,
  onSortsChange,
  onDistinctChange,
  onLimitChange,
  onVectorChange,
  onHybridChange,
  unstyled = false,
  className,
  classNames,
  customOperators,
  fieldRenderers,
}) => {
  const ctx = useQueryBuilderContext();
  const isProjectionsVisible = ctx?.isFeatureVisible ? ctx.isFeatureVisible("projections") : true;
  const isCalculatedFieldsVisible = ctx?.isFeatureVisible
    ? ctx.isFeatureVisible("calculated_fields")
    : true;
  const isVectorSearchVisible = ctx?.isFeatureVisible ? ctx.isFeatureVisible("vector_search") : true;
  const isJoinsVisible = ctx?.isFeatureVisible ? ctx.isFeatureVisible("joins") : true;
  const isFiltersVisible = ctx?.isFeatureVisible ? ctx.isFeatureVisible("filters") : true;
  const isSortsVisible = ctx?.isFeatureVisible ? ctx.isFeatureVisible("sorts") : true;
  const isDistinctLimitVisible = ctx?.isFeatureVisible ? ctx.isFeatureVisible("distinct_limit") : true;

  const [isCalcEditorOpen, setIsCalcEditorOpen] = React.useState(false);
  const [isSqlPreviewOpen, setIsSqlPreviewOpen] = React.useState(false);
  const [copiedSql, setCopiedSql] = React.useState(false);

  const allTables = React.useMemo(() => Object.values(schema?.tables || {}), [schema?.tables]);
  const availableToAdd = React.useMemo(
    () => allTables.filter((t) => !activeTables.some((a) => a.name === t.name)),
    [allTables, activeTables],
  );

  const activeTableNames = React.useMemo(() => activeTables.map((t) => t.name), [activeTables]);
  const foreignKeys = React.useMemo(() => schema?.foreign_keys || [], [schema?.foreign_keys]);

  // Compute 1-click FK join suggestions for tables in schema not yet on the canvas
  const suggestedJoins = React.useMemo(() => {
    if (activeTableNames.length === 0 || foreignKeys.length === 0) return [];
    const suggestions: { candidate: string; edge: (typeof foreignKeys)[0] }[] = [];
    for (const cand of availableToAdd) {
      const links = directLinks(cand.name, activeTableNames, foreignKeys);
      if (links.length > 0) {
        suggestions.push({ candidate: cand.name, edge: links[0] });
      }
    }
    return suggestions;
  }, [activeTableNames, foreignKeys, availableToAdd]);

  const handleQuickFilter = (tableName: string, colName: string, _dataType: string) => {
    const newFilter: VisualFilter = {
      id: `filter-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
      tablePrefix: tableName,
      column: colName,
      operator: "=",
      value: "",
    };
    onFiltersChange([...filters, newFilter]);
  };

  const handleQuickSort = (tableName: string, colName: string) => {
    const existingIdx = sorts.findIndex(
      (s) => (s.tablePrefix === tableName || !s.tablePrefix) && s.column === colName,
    );
    if (existingIdx >= 0) {
      const existing = sorts[existingIdx];
      if (existing.direction === "ASC") {
        const next = [...sorts];
        next[existingIdx] = { ...existing, direction: "DESC" };
        onSortsChange(next);
      } else {
        onSortsChange(sorts.filter((_, idx) => idx !== existingIdx));
      }
    } else {
      const newSort: VisualSort = {
        id: `sort-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
        tablePrefix: tableName,
        column: colName,
        direction: "ASC",
      };
      onSortsChange([...sorts, newSort]);
    }
  };

  const handleQuickAggregate = (tableName: string, colName: string, currentAgg?: string) => {
    const key = `${tableName}.${colName}`;
    if (!selectedColumns[key]) {
      onToggleColumn(tableName, colName);
    }
    const cycle: ("" | "COUNT" | "SUM" | "AVG" | "MIN" | "MAX")[] = ["COUNT", "SUM", "AVG", "MIN", "MAX", ""];
    const nextAgg = cycle[(cycle.indexOf((currentAgg as "" | "COUNT" | "SUM" | "AVG" | "MIN" | "MAX") || "") + 1) % cycle.length] || undefined;
    onUpdateColumnSelect(key, { aggregate: nextAgg });
  };

  const handleQuickJoinFk = (targetTable: string) => {
    if (onAddJoin) {
      onAddJoin(targetTable);
    } else {
      onAddTableToCanvas(targetTable);
    }
  };

  const handleClearAllClauses = () => {
    onJoinsChange([]);
    onFiltersChange([]);
    onSortsChange([]);
  };

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

  const handleCopyLiveSql = () => {
    if (!compiledSql) return;
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(compiledSql);
    }
    setCopiedSql(true);
    setTimeout(() => setCopiedSql(false), 1500);
  };

  return (
    <div
      data-qb="canvas"
      className={cx(className, classNames?.canvas)}
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
      {/* Plain-English query breadcrumb & clause summary bar */}
      <QuerySummaryBar
        primaryTable={primaryTable}
        activeTables={activeTableNames}
        selectedColumns={selectedColumns}
        orderedProjectionKeys={orderedProjectionKeys}
        joins={joins}
        filters={filters}
        sorts={sorts}
        limit={limit}
        isDistinct={isDistinct}
        windowFunctions={windowFunctions}
        onClearClauses={handleClearAllClauses}
        unstyled={unstyled}
      />
      {/* Tables row / workspace */}
      <div
        data-qb="canvas-tables"
        className={cx(classNames?.canvasTables)}
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
                  gap: "8px",
                  flexWrap: "wrap",
                }
          }
        >
          <span
            className={cx(classNames?.title)}
            style={
              unstyled
                ? undefined
                : { fontSize: "0.88rem", fontWeight: 700, color: "var(--qb-color-text-secondary, #cbd5e1)" }
            }
          >
            📋 Active Tables in Query ({activeTables.length})
          </span>
          <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px" }}>
            {isCalculatedFieldsVisible && activeTables.length > 0 && onAddCalculatedField && (
              <button
                type="button"
                data-qb="btn-open-calculated-field"
                onClick={() => setIsCalcEditorOpen(true)}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "var(--qb-color-accent, rgba(139, 92, 246, 0.15))",
                        color: "#c4b5fd",
                        border: "1px solid rgba(139, 92, 246, 0.4)",
                        borderRadius: "var(--qb-radius-sm, 6px)",
                        padding: "4px 10px",
                        fontSize: "0.78rem",
                        cursor: "pointer",
                        fontWeight: 600,
                        transition: "all 0.15s ease",
                      }
                }
              >
                + Calculated Field
              </button>
            )}
            {availableToAdd.length > 0 && (
              <select
                defaultValue=""
                aria-label="Add table to canvas"
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
                        background: "var(--qb-color-surface, #1e293b)",
                        color: "var(--qb-color-primary, #60a5fa)",
                        border: "1px solid var(--qb-color-primary, rgba(59, 130, 246, 0.4))",
                        borderRadius: "var(--qb-radius-sm, 6px)",
                        padding: "4px 10px",
                        fontSize: "0.78rem",
                        cursor: "pointer",
                        fontWeight: 600,
                        outline: "none",
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
        </div>

        {activeTables.length === 0 ? (
          <div
            data-qb="canvas-empty-state"
            className={cx(classNames?.canvasEmpty)}
            style={
              unstyled
                ? undefined
                : {
                    padding: "36px",
                    textAlign: "center",
                    color: "var(--qb-color-text-muted, #94a3b8)",
                    border: "2px dashed var(--qb-color-border, rgba(255, 255, 255, 0.15))",
                    borderRadius: "var(--qb-radius-lg, 10px)",
                    background: "var(--qb-color-surface, rgba(15, 23, 42, 0.4))",
                    width: "100%",
                  }
            }
          >
            No tables in query. Select a table to start building.
          </div>
        ) : (
          <>
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
                  onAddJoin={
                    isJoinsVisible
                      ? () => (onAddJoin ? onAddJoin(t.name) : onAddTableToCanvas(t.name))
                      : undefined
                  }
                  onQuickFilterColumn={handleQuickFilter}
                  onQuickSortColumn={handleQuickSort}
                  onQuickAggregateColumn={handleQuickAggregate}
                  onQuickJoinForeignKey={handleQuickJoinFk}
                  activeFilterColumns={
                    new Set(
                      filters
                        .filter(
                          (f) =>
                            f.tablePrefix === t.name || (!f.tablePrefix && t.name === primaryTable),
                        )
                        .map((f) => f.column),
                    )
                  }
                  activeSortMap={Object.fromEntries(
                    sorts
                      .filter(
                        (s) =>
                          s.tablePrefix === t.name || (!s.tablePrefix && t.name === primaryTable),
                      )
                      .map((s) => [s.column, s.direction as "ASC" | "DESC"]),
                  )}
                  foreignKeys={foreignKeys}
                  unstyled={unstyled}
                  fieldRenderers={fieldRenderers}
                  classNames={classNames}
                />
              ))}
            </div>

            {/* Smart 1-click Foreign Key Join Suggestions */}
            {suggestedJoins.length > 0 && (
              <div
                data-qb="suggested-joins-bar"
                style={
                  unstyled
                    ? undefined
                    : {
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        flexWrap: "wrap",
                        padding: "6px 12px",
                        background: "rgba(56, 189, 248, 0.08)",
                        border: "1px dashed rgba(56, 189, 248, 0.3)",
                        borderRadius: "6px",
                        fontSize: "0.78rem",
                      }
                }
              >
                <span style={unstyled ? undefined : { color: "#38bdf8", fontWeight: 600 }}>💡 Suggested Joins:</span>
                {suggestedJoins.map(({ candidate, edge }) => (
                  <button
                    key={candidate}
                    type="button"
                    data-testid={`fk-join-suggestion-${candidate}`}
                    onClick={() => handleQuickJoinFk(candidate)}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "rgba(56, 189, 248, 0.16)",
                            color: "#38bdf8",
                            border: "1px solid rgba(56, 189, 248, 0.35)",
                            borderRadius: "4px",
                            padding: "3px 8px",
                            fontSize: "0.74rem",
                            cursor: "pointer",
                            fontWeight: 600,
                            transition: "all 0.15s ease",
                          }
                    }
                    title={`Join ${candidate} on ${describeLink(edge)}`}
                  >
                    + Join {candidate} ({describeLink(edge)})
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Projection fields manager */}
      {isProjectionsVisible && (orderedProjectionKeys.length > 0 || windowFunctions.length > 0) && (
        <div
          data-qb="canvas-projections"
          className={cx(classNames?.columns)}
          style={
            unstyled
              ? undefined
              : {
                  background: "var(--qb-color-surface, rgba(15, 23, 42, 0.6))",
                  border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                  borderRadius: "var(--qb-radius-md, 8px)",
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
                  : { fontSize: "0.85rem", fontWeight: 600, color: "var(--qb-color-text-muted, #94a3b8)" }
              }
            >
              ✨ Selected Columns & Projections ({orderedProjectionKeys.length})
            </span>
            {isDistinctLimitVisible && (
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
                          color: "var(--qb-color-text-secondary, #cbd5e1)",
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
                    style={{ accentColor: "var(--qb-color-primary, #3b82f6)" }}
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
                  <span style={unstyled ? undefined : { fontSize: "0.75rem", color: "var(--qb-color-text-muted, #64748b)" }}>
                    Limit:
                  </span>
                  <select
                    value={limit}
                    aria-label="Query row limit"
                    data-qb="input-limit"
                    onChange={(e) => onLimitChange(Number(e.target.value))}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "var(--qb-color-background, #1e293b)",
                            color: "var(--qb-color-text, #f8fafc)",
                            border: "1px solid var(--qb-color-border, #475569)",
                            borderRadius: "var(--qb-radius-sm, 4px)",
                            padding: "2px 6px",
                            fontSize: "0.75rem",
                            outline: "none",
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
            )}
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
              const isCalculated = Boolean(item.rawExpression || item.caseWhen);

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
                          background: "var(--qb-color-surface-hover, rgba(30, 41, 59, 0.7))",
                          border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                          borderRadius: "var(--qb-radius-sm, 6px)",
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
                              color: "var(--qb-color-text-muted, #94a3b8)",
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
                        : { color: isCalculated ? "#c4b5fd" : "var(--qb-color-primary, #93c5fd)", fontWeight: 600 }
                    }
                  >
                    {isCalculated
                      ? `fx ${item.name || item.alias || key}`
                      : `${item.table}.${item.name}`}
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
                    className={cx(classNames?.projectionAlias)}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "var(--qb-color-background, #0f172a)",
                            border: "1px solid var(--qb-color-border, #334155)",
                            borderRadius: "4px",
                            padding: "1px 6px",
                            color: "var(--qb-color-primary, #38bdf8)",
                            fontSize: "0.7rem",
                            width: "60px",
                            outline: "none",
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

                  {!item.metric && !isCalculated && (
                    <select
                      value={item.timeGrain || ""}
                      data-qb="projection-timegrain-select"
                      aria-label={`Time grain for ${key}`}
                      onChange={(e) =>
                        onUpdateColumnSelect(key, {
                          timeGrain: (e.target.value as TimeGrain) || undefined,
                        })
                      }
                      className={cx(classNames?.projectionSelect)}
                      style={
                        unstyled
                          ? undefined
                          : {
                              background: "var(--qb-color-background, #0f172a)",
                              color: item.timeGrain ? "#a78bfa" : "var(--qb-color-text-muted, #64748b)",
                              border: "1px solid var(--qb-color-border, #334155)",
                              borderRadius: "4px",
                              padding: "1px 4px",
                              fontSize: "0.7rem",
                              outline: "none",
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

                  {!item.metric && !item.timeGrain && !isCalculated && (
                    <select
                      value={item.aggregate || ""}
                      data-qb="projection-aggregate-select"
                      aria-label={`Aggregate function for ${key}`}
                      onChange={(e) =>
                        onUpdateColumnSelect(key, {
                          aggregate: e.target.value as VisualColumnSelect["aggregate"],
                        })
                      }
                      className={cx(classNames?.projectionSelect)}
                      style={
                        unstyled
                          ? undefined
                          : {
                              background: "var(--qb-color-background, #0f172a)",
                              color: item.aggregate ? "var(--qb-color-warning, #f59e0b)" : "var(--qb-color-text-muted, #64748b)",
                              border: "1px solid var(--qb-color-border, #334155)",
                              borderRadius: "4px",
                              padding: "1px 4px",
                              fontSize: "0.7rem",
                              outline: "none",
                            }
                      }
                    >
                      <option value="">(none)</option>
                      <option value="COUNT">COUNT</option>
                      <option value="COUNT_DISTINCT">COUNT(DISTINCT)</option>
                      <option value="SUM">SUM</option>
                      <option value="AVG">AVG</option>
                      <option value="MIN">MIN</option>
                      <option value="MAX">MAX</option>
                    </select>
                  )}

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
                    aria-label={`Remove projection ${key}`}
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

            {windowFunctions.map((wf, idx) => (
              <div
                key={`wf_${wf.alias || idx}`}
                data-qb="window-function-chip"
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "rgba(88, 28, 135, 0.35)",
                        border: "1px solid rgba(168, 85, 247, 0.4)",
                        borderRadius: "6px",
                        padding: "4px 8px",
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                        fontSize: "0.78rem",
                      }
                }
              >
                <span style={unstyled ? undefined : { color: "#d8b4fe", fontWeight: 600 }}>
                  🪟 {wf.function}({wf.column || ""}) AS {wf.alias}
                </span>
                {onRemoveWindowFunction && (
                  <button
                    type="button"
                    aria-label={`Remove window function ${wf.alias}`}
                    onClick={() => onRemoveWindowFunction(idx)}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "transparent",
                            border: "none",
                            color: "#cbd5e1",
                            cursor: "pointer",
                            fontSize: "0.75rem",
                          }
                    }
                    title="Remove window function"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Relational Joins */}
      {isJoinsVisible && (
        <TableJoinEditor
          joins={joins}
          activeTables={activeTables}
          allTables={allTables}
          schema={schema}
          onChange={onJoinsChange}
          unstyled={unstyled}
          classNames={classNames}
        />
      )}

      {/* Filter Conditions */}
      {isFiltersVisible && (
        <TableFiltersEditor
          filters={filters}
          activeTables={activeTables}
          onChange={onFiltersChange}
          unstyled={unstyled}
          customOperators={customOperators}
          fieldRenderers={fieldRenderers}
          classNames={classNames}
        />
      )}

      {/* Sorting */}
      {isSortsVisible && (
        <TableSortsEditor
          sorts={sorts}
          activeTables={activeTables}
          selectedColumns={selectedColumns}
          onChange={onSortsChange}
          unstyled={unstyled}
          classNames={classNames}
        />
      )}

      {/* Semantic Vector & Hybrid Retrieval */}
      {isVectorSearchVisible && onVectorChange && onHybridChange && (
        <VectorHybridControl
          vectorSearch={vectorSearch}
          hybridSearch={hybridSearch}
          activeTables={activeTables}
          onVectorChange={onVectorChange}
          onHybridChange={onHybridChange}
          unstyled={unstyled}
        />
      )}

      {/* Collapsible Live SQL Preview Bar */}
      {compiledSql && (
        <div
          data-qb="live-sql-preview"
          style={
            unstyled
              ? undefined
              : {
                  background: "var(--qb-color-surface, rgba(15, 23, 42, 0.75))",
                  border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                  borderRadius: "var(--qb-radius-md, 8px)",
                  padding: "8px 12px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "8px",
                }
          }
        >
          <div
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "8px",
                  }
            }
          >
            <button
              type="button"
              data-qb="btn-toggle-live-sql"
              onClick={() => setIsSqlPreviewOpen((prev) => !prev)}
              style={
                unstyled
                  ? undefined
                  : {
                      background: "transparent",
                      border: "none",
                      color: "var(--qb-color-text-muted, #94a3b8)",
                      fontSize: "0.78rem",
                      fontWeight: 600,
                      cursor: "pointer",
                      padding: 0,
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                    }
              }
            >
              <span>{isSqlPreviewOpen ? "▼" : "▶"}</span>
              <span>Live SQL Preview</span>
              {!isSqlPreviewOpen && (
                <code
                  style={
                    unstyled
                      ? undefined
                      : {
                          color: "var(--qb-color-primary, #38bdf8)",
                          fontSize: "0.74rem",
                          maxWidth: "480px",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          display: "inline-block",
                          verticalAlign: "bottom",
                        }
                  }
                >
                  {compiledSql.replace(/\s+/g, " ")}
                </code>
              )}
            </button>
            <button
              type="button"
              data-qb="btn-copy-live-sql"
              onClick={handleCopyLiveSql}
              style={
                unstyled
                  ? undefined
                  : {
                      background: "var(--qb-color-primary-light, rgba(59, 130, 246, 0.15))",
                      color: "var(--qb-color-primary, #60a5fa)",
                      border: "1px solid var(--qb-color-primary, rgba(59, 130, 246, 0.35))",
                      borderRadius: "var(--qb-radius-sm, 4px)",
                      padding: "2px 8px",
                      fontSize: "0.72rem",
                      cursor: "pointer",
                      fontWeight: 600,
                      transition: "all 0.15s ease",
                    }
              }
            >
              {copiedSql ? "✓ Copied" : "Copy SQL"}
            </button>
          </div>
          {isSqlPreviewOpen && (
            <pre
              data-qb="live-sql-preview-code"
              style={
                unstyled
                  ? undefined
                  : {
                      margin: 0,
                      padding: "10px 12px",
                      background: "var(--qb-color-background, #0f172a)",
                      color: "var(--qb-color-primary, #38bdf8)",
                      border: "1px solid var(--qb-color-border, #1e293b)",
                      borderRadius: "var(--qb-radius-sm, 6px)",
                      fontSize: "0.78rem",
                      fontFamily: "var(--qb-font-mono, monospace)",
                      overflowX: "auto",
                      whiteSpace: "pre-wrap",
                    }
              }
            >
              {compiledSql}
            </pre>
          )}
        </div>
      )}

      {onAddCalculatedField && (
        <CalculatedFieldEditor
          isOpen={isCalcEditorOpen}
          onClose={() => setIsCalcEditorOpen(false)}
          onSave={(field) => {
            onAddCalculatedField(field);
            setIsCalcEditorOpen(false);
          }}
          tables={activeTables}
          unstyled={unstyled}
        />
      )}
    </div>
  );
};
