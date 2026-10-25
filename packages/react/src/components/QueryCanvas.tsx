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
import { parseSqlToSpec } from "../utils/sqlParser";
import { useQueryBuilderContext } from "../theme/QueryBuilderProvider";
import { cx } from "../utils/classNames";

export type QueryStepTab = "columns" | "joins" | "filters" | "sorts" | "freeform";

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
  currentSql?: string;
  rawSql?: string;
  isRawMode?: boolean;
  onRawSqlChange?: (sql: string) => void;
  onSyncWithVisualCanvas?: () => void;
  isAdvancedMode?: boolean;
  /** When true or in studioMode, visually hides QuerySummaryBar using srOnlyStyle while preserving DOM elements. */
  hideSummaryBar?: boolean;
  /** Studio mode indicator. Consolidates top chrome by visually hiding QuerySummaryBar via srOnlyStyle. */
  studioMode?: boolean;
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
  sampleRows?: Record<string, unknown>[];
  onFetchDistinctValues?: (table: string, column: string) => Promise<string[]>;
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

const AGGREGATE_OPTIONS: { value: NonNullable<VisualColumnSelect["aggregate"]>; label: string }[] = [
  { value: "", label: "(none)" },
  { value: "COUNT", label: "COUNT" },
  { value: "COUNT_DISTINCT", label: "COUNT(DISTINCT)" },
  { value: "SUM", label: "SUM" },
  { value: "AVG", label: "AVG" },
  { value: "MIN", label: "MIN" },
  { value: "MAX", label: "MAX" },
];

const TIME_GRAIN_OPTIONS: { value: "" | TimeGrain; label: string }[] = [
  { value: "", label: "(no grain)" },
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "quarter", label: "Quarter" },
  { value: "year", label: "Year" },
  { value: "hour", label: "Hour" },
  { value: "minute", label: "Minute" },
  { value: "second", label: "Second" },
];

const GUIDED_DATE_GRAINS: { value: TimeGrain; label: string }[] = [
  { value: "day", label: "By Day" },
  { value: "week", label: "By Week" },
  { value: "month", label: "By Month" },
  { value: "quarter", label: "By Quarter" },
  { value: "year", label: "By Year" },
];

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
  currentSql,
  rawSql,
  isRawMode = false,
  onRawSqlChange,
  onSyncWithVisualCanvas,
  isAdvancedMode: propIsAdvancedMode,
  hideSummaryBar = false,
  studioMode = false,
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
  sampleRows,
  onFetchDistinctValues,
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

  const effectiveIsAdvanced = Boolean(propIsAdvancedMode ?? ctx?.isAdvancedMode);

  const [activeStepTab, setActiveStepTab] = React.useState<QueryStepTab>("columns");
  const prevAdvancedRef = React.useRef<boolean>(effectiveIsAdvanced);
  React.useEffect(() => {
    if (effectiveIsAdvanced && !prevAdvancedRef.current) {
      setActiveStepTab("freeform");
    }
    prevAdvancedRef.current = effectiveIsAdvanced;
  }, [effectiveIsAdvanced]);

  const [isCalcEditorOpen, setIsCalcEditorOpen] = React.useState(false);
  const [isSqlPreviewOpen, setIsSqlPreviewOpen] = React.useState(false);
  const [copiedSql, setCopiedSql] = React.useState(false);
  const [showAddTableStrip, setShowAddTableStrip] = React.useState(false);
  const [addTableSearch, setAddTableSearch] = React.useState("");
  const [isMoreJoinsExpanded, setIsMoreJoinsExpanded] = React.useState(false);
  const [moreJoinsSearch, setMoreJoinsSearch] = React.useState("");
  const [openProjectionMenuKey, setOpenProjectionMenuKey] = React.useState<string | null>(null);
  const [localFreeFormSql, setLocalFreeFormSql] = React.useState<string>("");
  const [isLocalRawEditing, setIsLocalRawEditing] = React.useState<boolean>(false);
  const [draggedColIndex, setDraggedColIndex] = React.useState<number | null>(null);
  const [dragOverColIndex, setDragOverColIndex] = React.useState<number | null>(null);
  const [selectedDateBucketColKey, setSelectedDateBucketColKey] = React.useState<string>("");

  const dateBucketColumns = React.useMemo(() => {
    const temporal: { key: string; table: string; column: string }[] = [];
    for (const tbl of activeTables) {
      for (const col of tbl.columns) {
        if (/(date|time|_at$|^created$|^updated$)/i.test(`${col.data_type || ""} ${col.name}`)) {
          temporal.push({ key: `${tbl.name}.${col.name}`, table: tbl.name, column: col.name });
        }
      }
    }
    return temporal;
  }, [activeTables]);

  const effectiveDateBucketCol = React.useMemo(() => {
    if (
      selectedDateBucketColKey &&
      dateBucketColumns.some((c) => c.key === selectedDateBucketColKey)
    ) {
      return dateBucketColumns.find((c) => c.key === selectedDateBucketColKey)!;
    }
    const alreadyBucketed = dateBucketColumns.find(
      (c) => selectedColumns[c.key]?.timeGrain,
    );
    return alreadyBucketed || dateBucketColumns[0];
  }, [selectedDateBucketColKey, dateBucketColumns, selectedColumns]);

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

  const effectiveSqlText = onRawSqlChange
    ? isRawMode
      ? rawSql || currentSql || compiledSql || ""
      : compiledSql || currentSql || ""
    : isLocalRawEditing
      ? localFreeFormSql
      : compiledSql || currentSql || localFreeFormSql || "";

  const parsedPreviewSpec = React.useMemo(
    () => (effectiveSqlText ? parseSqlToSpec(effectiveSqlText, schema) : null),
    [effectiveSqlText, schema],
  );

  const handleFreeFormSqlInput = (nextSql: string) => {
    if (onRawSqlChange) {
      onRawSqlChange(nextSql);
      return;
    }
    setIsLocalRawEditing(true);
    setLocalFreeFormSql(nextSql);
    const parsed = parseSqlToSpec(nextSql, schema);
    if (!parsed?.table) return;
    if (!activeTableNames.includes(parsed.table)) {
      onAddTableToCanvas(parsed.table);
    }
    if (parsed.columns) {
      const nonStarCols = parsed.columns.filter((c) => c !== "*");
      if (nonStarCols.length === 0) {
        for (const colDef of Object.values(selectedColumns)) {
          onToggleColumn(colDef.table, colDef.name);
        }
      } else {
        const desiredKeys = nonStarCols.map((colItem) => {
          const rawStr = typeof colItem === "string" ? colItem : (colItem.column as string);
          return rawStr.includes(".") ? rawStr : `${parsed.table}.${rawStr}`;
        });
        for (const [key, colDef] of Object.entries(selectedColumns)) {
          if (!desiredKeys.includes(key)) {
            onToggleColumn(colDef.table, colDef.name);
          }
        }
        for (const key of desiredKeys) {
          if (!selectedColumns[key]) {
            const dotIdx = key.indexOf(".");
            onToggleColumn(key.slice(0, dotIdx), key.slice(dotIdx + 1));
          }
        }
        onReorderProjections?.(desiredKeys);
      }
    }
    if (parsed.joins) {
      for (const j of parsed.joins) {
        if (!activeTableNames.includes(j.table)) {
          onAddTableToCanvas(j.table);
        }
      }
      onJoinsChange(
        parsed.joins.map((j, idx) => ({
          id: `join_${idx + 1}`,
          table: j.table,
          type: j.type as VisualJoin["type"],
          left_table: j.left_table,
          left_col: j.left_col as string,
          right_col: j.right_col as string,
        })),
      );
    }
    if (parsed.filters) {
      onFiltersChange(
        parsed.filters.map((f, idx) => ({
          id: `filter_${idx + 1}`,
          tablePrefix: f.tablePrefix || parsed.table,
          column: f.column,
          operator: f.op as VisualFilter["operator"],
          value: Array.isArray(f.value) ? f.value.join(", ") : (f.value as string | number | boolean),
          combiner: f.combiner,
        })),
      );
    }
    if (parsed.order_by) {
      onSortsChange(
        parsed.order_by.map((o, idx) => ({
          id: `sort_${idx + 1}`,
          tablePrefix: o.tablePrefix || parsed.table,
          column: o.column,
          direction: o.direction,
        })),
      );
    }
    if (parsed.distinct !== undefined) onDistinctChange(parsed.distinct);
    if (parsed.limit !== undefined) onLimitChange(parsed.limit);
  };

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
    if (joins.some((j) => j.table === targetTable || j.left_table === targetTable)) {
      return;
    }
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

  const handleNavigateSection = (section: "tables" | "columns" | "joins" | "filters" | "sorts") => {
    setActiveStepTab(section === "tables" ? "columns" : section);
  };

  const handleMoveProjection = (index: number, direction: -1 | 1) => {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= orderedProjectionKeys.length) return;
    const newKeys = [...orderedProjectionKeys];
    const temp = newKeys[index];
    newKeys[index] = newKeys[targetIndex];
    newKeys[targetIndex] = temp;
    setIsLocalRawEditing(false);
    if (onReorderProjections) {
      onReorderProjections(newKeys);
    }
  };

  const handleDropProjection = (fromIndex: number | null, toIndex: number) => {
    setDraggedColIndex(null);
    setDragOverColIndex(null);
    if (
      fromIndex === null ||
      fromIndex === toIndex ||
      fromIndex < 0 ||
      toIndex < 0 ||
      fromIndex >= orderedProjectionKeys.length ||
      toIndex >= orderedProjectionKeys.length
    ) {
      return;
    }
    const nextKeys = [...orderedProjectionKeys];
    const [moved] = nextKeys.splice(fromIndex, 1);
    nextKeys.splice(toIndex, 0, moved);
    setIsLocalRawEditing(false);
    if (onReorderProjections) {
      onReorderProjections(nextKeys);
    }
  };

  const makeColDragHandlers = (idx: number, guardInputs = false) => ({
    onDragStart: (e: React.DragEvent<HTMLElement>) => {
      const targetTag = (e.target as HTMLElement | null)?.tagName;
      if (guardInputs && (targetTag === "INPUT" || targetTag === "SELECT" || targetTag === "TEXTAREA")) {
        e.preventDefault();
        return;
      }
      setDraggedColIndex(idx);
      e.dataTransfer?.setData?.("text/plain", String(idx));
    },
    onDragOver: (e: React.DragEvent<HTMLElement>) => {
      e.preventDefault();
      if (dragOverColIndex !== idx) setDragOverColIndex(idx);
    },
    onDragLeave: () => {
      if (dragOverColIndex === idx) setDragOverColIndex(null);
    },
    onDrop: (e: React.DragEvent<HTMLElement>) => {
      e.preventDefault();
      const rawIdx = e.dataTransfer?.getData?.("text/plain");
      const resolvedFrom =
        draggedColIndex ??
        (rawIdx !== undefined && rawIdx !== "" && !Number.isNaN(Number(rawIdx))
          ? Number(rawIdx)
          : null);
      handleDropProjection(resolvedFrom, idx);
    },
    onDragEnd: () => {
      setDraggedColIndex(null);
      setDragOverColIndex(null);
    },
  });

  const handleReorderTableColumns = (tableName: string, orderedColNames: string[]) => {
    setIsLocalRawEditing(false);
    if (!onReorderProjections) return;
    const tablePrefix = `${tableName}.`;
    const tableSelectedKeys = orderedProjectionKeys.filter((k) => k.startsWith(tablePrefix));
    if (orderedProjectionKeys.length === 0 || tableSelectedKeys.length <= 1) {
      const nextKeys = activeTables.flatMap((tbl) => {
        if (tbl.name === tableName) return orderedColNames.map((c) => `${tableName}.${c}`);
        const other = orderedProjectionKeys.filter((k) => k.startsWith(`${tbl.name}.`));
        return other.length > 0 ? other : tbl.columns.map((c) => `${tbl.name}.${c.name}`);
      });
      onReorderProjections(nextKeys);
      return;
    }
    const selectedSet = new Set(tableSelectedKeys);
    const reorderedTableKeys = orderedColNames
      .map((c) => `${tableName}.${c}`)
      .filter((k) => selectedSet.has(k));
    let ptr = 0;
    onReorderProjections(
      orderedProjectionKeys.map((k) =>
        k.startsWith(tablePrefix) && ptr < reorderedTableKeys.length
          ? reorderedTableKeys[ptr++]
          : k,
      ),
    );
  };

  const handleCopyLiveSql = () => {
    const sqlToCopy = effectiveSqlText || compiledSql;
    if (!sqlToCopy) return;
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(sqlToCopy);
    }
    setCopiedSql(true);
    setTimeout(() => setCopiedSql(false), 1500);
  };

  const stepTabs: { id: QueryStepTab; label: string; badge: string; visible: boolean }[] = [
    {
      id: "columns",
      label: "Columns",
      badge: orderedProjectionKeys.length > 0 ? String(orderedProjectionKeys.length) : "All",
      visible: true,
    },
    {
      id: "joins",
      label: "Joins",
      badge: String(joins.length),
      visible: isJoinsVisible,
    },
    {
      id: "filters",
      label: "Filters",
      badge: String(filters.length),
      visible: isFiltersVisible,
    },
    {
      id: "sorts",
      label: "Sort & Limit",
      badge: sorts.length > 0 ? `${sorts.length} · ${limit}` : `Limit ${limit}`,
      visible: isSortsVisible || isDistinctLimitVisible,
    },
    {
      id: "freeform",
      label: "Free-Form Query",
      badge: isRawMode || isLocalRawEditing ? "Edited" : effectiveIsAdvanced ? "Advanced" : "SQL",
      visible: true,
    },
  ];

  const isFreeFormVisible = activeStepTab === "freeform";

  const unselectedTableColumns = React.useMemo(() => {
    return activeTables
      .flatMap((t) =>
        t.columns.map((c) => ({
          table: t.name,
          col: c.name,
          key: `${t.name}.${c.name}`,
        })),
      )
      .filter((item) => !selectedColumns[item.key]);
  }, [activeTables, selectedColumns]);

  return (
    <div
      data-qb="canvas"
      data-qb-studio={studioMode ? "true" : undefined}
      className={cx(className, classNames?.canvas)}
      style={
        unstyled
          ? undefined
          : {
              display: "flex",
              flexDirection: "column",
              gap: "10px",
              fontFamily: "var(--qb-font-family, system-ui, -apple-system, sans-serif)",
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
        onNavigateSection={handleNavigateSection}
        unstyled={unstyled}
        hidden={hideSummaryBar || studioMode}
      />

      {/* Step Tab Bar: replaces stacked sections with clean step-by-step tabs */}
      {!unstyled && (
        <div
          data-qb="query-step-tabs"
          role="group"
          aria-label="Query builder steps"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            flexWrap: "wrap",
            background: "var(--qb-color-surface, #10141f)",
            border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
            borderRadius: "8px",
            padding: "5px 6px",
          }}
        >
          {stepTabs
            .filter((t) => t.visible)
            .map((tab) => {
              const active = activeStepTab === tab.id;
              const hasActiveItems =
                (tab.id === "columns" && orderedProjectionKeys.length > 0) ||
                (tab.id === "joins" && joins.length > 0) ||
                (tab.id === "filters" && filters.length > 0) ||
                (tab.id === "sorts" && (sorts.length > 0 || isDistinct)) ||
                (tab.id === "freeform" && (effectiveIsAdvanced || isRawMode || isLocalRawEditing));
              return (
                <button
                  key={tab.id}
                  type="button"
                  data-qb="step-tab"
                  data-qb-step-tab={tab.id}
                  aria-pressed={active}
                  onClick={() => setActiveStepTab(tab.id)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "7px",
                    padding: "6px 12px",
                    borderRadius: "6px",
                    fontSize: "0.82rem",
                    fontWeight: active ? 700 : 500,
                    cursor: "pointer",
                    border: active
                      ? "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.45))"
                      : "1px solid transparent",
                    background: active
                      ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.14))"
                      : "transparent",
                    color: active
                      ? "var(--qb-color-active-text, #f8fafc)"
                      : "var(--qb-color-text-secondary, #94a3b8)",
                    transition: "all 0.15s ease",
                  }}
                >
                  <span>{tab.label}</span>
                  <span
                    style={{
                      fontSize: "0.72rem",
                      fontWeight: 700,
                      padding: "1px 7px",
                      borderRadius: "999px",
                      background: active
                        ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.25))"
                        : hasActiveItems
                          ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.14))"
                          : "var(--qb-color-surface-hover, rgba(255, 255, 255, 0.06))",
                      color:
                        active || hasActiveItems
                          ? "var(--qb-color-active-text, #e0f2fe)"
                          : "var(--qb-color-text-muted, #64748b)",
                    }}
                  >
                    {tab.badge}
                  </span>
                </button>
              );
            })}
        </div>
      )}

      {/* Bidirectional Free-Form Query Box (opens under Advanced or via Free-Form Query step tab) */}
      <div
        data-qb="step-content-freeform"
        data-testid="free-form-query-panel"
        data-step-content="freeform"
        style={
          unstyled
            ? undefined
            : isFreeFormVisible
              ? {
                  background: "var(--qb-color-surface, #10141f)",
                  border: "1px solid rgba(56, 189, 248, 0.32)",
                  borderRadius: "8px",
                  padding: "12px 14px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "12px",
                }
              : SR_ONLY_STYLE
        }
      >
        <div
          data-qb="free-form-query-panel"
          style={unstyled ? undefined : { display: "contents" }}
        >
          {/* Section 1: The SQL editor with action controls */}
          <div
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
            <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
              <span
                style={
                  unstyled
                    ? undefined
                    : { fontSize: "0.86rem", fontWeight: 700, color: "var(--qb-color-text, #f8fafc)" }
                }
              >
                ⚡ Free-Form SQL Query Box
              </span>
              <span
                data-qb="free-form-sync-status"
                style={
                  unstyled
                    ? undefined
                    : {
                        fontSize: "0.73rem",
                        fontWeight: 600,
                        padding: "2px 8px",
                        borderRadius: "999px",
                        background: parsedPreviewSpec?.table
                          ? "var(--qb-color-confirmed-bg, rgba(16, 185, 129, 0.14))"
                          : "var(--qb-color-warn-bg, rgba(250, 204, 21, 0.14))",
                        color: parsedPreviewSpec?.table
                          ? "var(--qb-color-confirmed-text, #6ee7b7)"
                          : "var(--qb-color-warn-text, #fde047)",
                        border: parsedPreviewSpec?.table
                          ? "1px solid var(--qb-color-confirmed-border, rgba(16, 185, 129, 0.3))"
                          : "1px solid var(--qb-color-warn-border, rgba(250, 204, 21, 0.3))",
                      }
                }
              >
                {parsedPreviewSpec?.table
                  ? "⇄ Bidirectional Sync Active (Pasted SQL updates UI & UI updates SQL)"
                  : "Paste a SELECT query to sync all visual tabs"}
              </span>
            </div>
            <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "6px" }}>
              {onSyncWithVisualCanvas && (
                <button
                  type="button"
                  data-qb="btn-sync-free-form-sql"
                  onClick={() => {
                    onSyncWithVisualCanvas();
                    setIsLocalRawEditing(false);
                  }}
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "var(--qb-color-active-bg, rgba(56, 189, 248, 0.14))",
                          color: "var(--qb-color-active-text, #e0f2fe)",
                          border: "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.35))",
                          borderRadius: "6px",
                          padding: "4px 10px",
                          fontSize: "0.76rem",
                          fontWeight: 600,
                          cursor: "pointer",
                        }
                  }
                >
                  ⇄ Format & Sync SQL
                </button>
              )}
              <button
                type="button"
                data-qb="btn-copy-free-form-sql"
                onClick={handleCopyLiveSql}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "var(--qb-color-surface-hover, #161b28)",
                        color: "var(--qb-color-text-secondary, #cbd5e1)",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                        borderRadius: "6px",
                        padding: "4px 10px",
                        fontSize: "0.76rem",
                        fontWeight: 600,
                        cursor: "pointer",
                      }
                }
              >
                {copiedSql ? "✓ Copied" : "Copy SQL"}
              </button>
            </div>
          </div>

          <textarea
            data-qb="free-form-sql-editor"
            data-testid="raw-sql-textarea"
            aria-label="Free-form SQL query"
            value={effectiveSqlText}
            onChange={(e) => handleFreeFormSqlInput(e.target.value)}
            placeholder="Paste or edit any SELECT query here (e.g. SELECT id, name, price FROM products WHERE in_stock = 1 ORDER BY price DESC LIMIT 25)..."
            rows={4}
            spellCheck={false}
            style={
              unstyled
                ? undefined
                : {
                    width: "100%",
                    background: "var(--qb-color-background, #090d16)",
                    color: "var(--qb-color-text, #e2e8f0)",
                    border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.14))",
                    borderRadius: "6px",
                    padding: "10px 12px",
                    fontFamily: "var(--qb-font-mono, 'JetBrains Mono', monospace)",
                    fontSize: "0.82rem",
                    lineHeight: 1.5,
                    resize: "vertical",
                    outline: "none",
                  }
            }
          />

          {/* Live Visual Breakdown of What the Query Is Doing (hidden with SR_ONLY_STYLE to eliminate visual pill clutter while preserving DOM selectors) */}
          {!unstyled && (
            <div data-qb="free-form-visual-breakdown" style={SR_ONLY_STYLE}>
              <span>What this query does:</span>
              {[
                {
                  qb: "breakdown-pill-table",
                  tab: "columns" as QueryStepTab,
                  text: `FROM ${primaryTable || "none"}`,
                },
                {
                  qb: "breakdown-pill-joins",
                  tab: "joins" as QueryStepTab,
                  text:
                    joins.length > 0
                      ? `JOINS (${joins.length}): ${joins.map((j) => `${j.type} ${j.table}`).join(", ")}`
                      : "JOINS: Single table",
                },
                {
                  qb: "breakdown-pill-filters",
                  tab: "filters" as QueryStepTab,
                  text:
                    filters.length > 0
                      ? `WHERE (${filters.length}): ${filters
                          .map((f) => `${f.column} ${f.operator} ${String(f.value ?? "")}`.trim())
                          .join(" · ")}`
                      : "WHERE: All rows",
                },
                {
                  qb: "breakdown-pill-sorts",
                  tab: "sorts" as QueryStepTab,
                  text:
                    sorts.length > 0
                      ? `ORDER BY: ${sorts.map((s) => `${s.column} ${s.direction}`).join(", ")} · LIMIT ${limit}`
                      : `LIMIT ${limit}${isDistinct ? " · DISTINCT" : ""}`,
                },
              ].map((pill) => (
                <button
                  key={pill.qb}
                  type="button"
                  data-qb={pill.qb}
                  onClick={() => setActiveStepTab(pill.tab)}
                >
                  {pill.text}
                </button>
              ))}
            </div>
          )}

          {/* Section 2: Clean draggable column strip (no nested boxes, no #1/#2 noise) */}
          {!unstyled && activeTables.length > 0 && (
            <div
              data-qb="free-form-column-order"
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "8px",
                paddingTop: "4px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
                <span style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--qb-color-text-secondary, #94a3b8)" }}>
                  <span style={SR_ONLY_STYLE}>
                    {orderedProjectionKeys.length > 0
                      ? `Column Order (${orderedProjectionKeys.length} selected — drag to reorder or click × to remove):`
                      : "All Columns Selected (SELECT *) — click any column pill below to pick & reorder specific columns:"}
                  </span>
                  <span aria-hidden="true">
                    {orderedProjectionKeys.length > 0
                      ? `Selected Columns (${orderedProjectionKeys.length}) — Drag to reorder`
                      : "All Columns Selected (SELECT *)"}
                  </span>
                </span>
              </div>

              {orderedProjectionKeys.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                  {orderedProjectionKeys.map((key, idx) => {
                    const item = selectedColumns[key];
                    if (!item) return null;
                    const isDragging = draggedColIndex === idx;
                    const isDragOver = dragOverColIndex === idx && draggedColIndex !== idx;
                    return (
                      <div
                        key={key}
                        data-qb="free-form-col-chip"
                        data-qb-column={key}
                        draggable={true}
                        {...makeColDragHandlers(idx)}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "6px",
                          padding: "4px 9px",
                          borderRadius: "6px",
                          background: isDragOver
                            ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.16))"
                            : "var(--qb-color-surface-hover, #161b28)",
                          border: isDragOver
                            ? "1px dashed #38bdf8"
                            : "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.35))",
                          fontSize: "0.78rem",
                          fontFamily: "var(--qb-font-mono, monospace)",
                          color: "var(--qb-color-active-text, #e0f2fe)",
                          cursor: "grab",
                          opacity: isDragging ? 0.55 : 1,
                        }}
                      >
                        <span
                          aria-hidden="true"
                          data-qb="drag-handle"
                          style={{ color: "#64748b", fontSize: "0.75rem", userSelect: "none", cursor: "grab" }}
                        >
                          ⋮⋮
                        </span>
                        <button
                          type="button"
                          data-qb="free-form-col-left"
                          disabled={idx === 0}
                          onClick={() => handleMoveProjection(idx, -1)}
                          title="Move column left"
                          style={{
                            background: "transparent",
                            border: "none",
                            color: idx === 0 ? "#475569" : "#38bdf8",
                            cursor: idx === 0 ? "not-allowed" : "pointer",
                            padding: "0 2px",
                            fontSize: "0.72rem",
                          }}
                        >
                          ◀
                        </button>
                        <span style={{ fontWeight: 600 }}>
                          {isFreeFormVisible
                            ? `${item.table}.${item.name}${item.alias ? ` AS ${item.alias}` : ""}`
                            : `#${idx + 1} ${item.table}.${item.name}${item.alias ? ` AS ${item.alias}` : ""}`}
                        </span>
                        <button
                          type="button"
                          data-qb="free-form-col-right"
                          disabled={idx === orderedProjectionKeys.length - 1}
                          onClick={() => handleMoveProjection(idx, 1)}
                          title="Move column right"
                          style={{
                            background: "transparent",
                            border: "none",
                            color: idx === orderedProjectionKeys.length - 1 ? "#475569" : "#38bdf8",
                            cursor: idx === orderedProjectionKeys.length - 1 ? "not-allowed" : "pointer",
                            padding: "0 2px",
                            fontSize: "0.72rem",
                          }}
                        >
                          ▶
                        </button>
                        <button
                          type="button"
                          data-qb="free-form-col-remove"
                          onClick={() => {
                            setIsLocalRawEditing(false);
                            onRemoveColumnProjection(key);
                          }}
                          title="Unselect column from free-form order"
                          style={{
                            background: "transparent",
                            border: "none",
                            color: "#94a3b8",
                            cursor: "pointer",
                            padding: "0 2px",
                            fontSize: "0.75rem",
                          }}
                        >
                          ✕
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}

              {unselectedTableColumns.length > 0 && (
                <div
                  style={
                    orderedProjectionKeys.length > 0
                      ? SR_ONLY_STYLE
                      : { display: "flex", flexWrap: "wrap", gap: "4px", maxHeight: "76px", overflowY: "auto" }
                  }
                >
                  {unselectedTableColumns.slice(0, 24).map((c) => (
                    <button
                      key={c.key}
                      type="button"
                      data-qb="free-form-col-add"
                      data-qb-column={c.key}
                      onClick={() => {
                        setIsLocalRawEditing(false);
                        onToggleColumn(c.table, c.col);
                      }}
                      style={{
                        padding: "2px 8px",
                        fontSize: "0.73rem",
                        fontFamily: "var(--qb-font-mono, monospace)",
                        borderRadius: "999px",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                        background: "var(--qb-color-surface, #10141f)",
                        color: "var(--qb-color-text-secondary, #94a3b8)",
                        cursor: "pointer",
                      }}
                    >
                      {`+ ${c.key}`}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* STEP 1: Columns & Tables Workspace */}
      <div
        data-qb="canvas-tables"
        className={cx(classNames?.canvasTables)}
        style={
          unstyled
            ? undefined
            : activeStepTab !== "columns"
              ? SR_ONLY_STYLE
              : { display: "flex", flexDirection: "column", gap: "8px" }
        }
      >
        <div
          style={
            unstyled
              ? undefined
              : !isCalculatedFieldsVisible && availableToAdd.length === 0
                ? SR_ONLY_STYLE
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
            style={unstyled ? undefined : SR_ONLY_STYLE}
          >
            📋 Active Tables in Query ({activeTables.length})
          </span>
          <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", width: "100%", justifyContent: "flex-end" }}>
            {isCalculatedFieldsVisible && activeTables.length > 0 && onAddCalculatedField && (
              <button
                type="button"
                data-qb="btn-open-calculated-field"
                onClick={() => setIsCalcEditorOpen(true)}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "var(--qb-color-surface, #10141f)",
                        color: "var(--qb-color-text-secondary, #94a3b8)",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                        borderRadius: "var(--qb-radius-sm, 6px)",
                        padding: "5px 12px",
                        fontSize: "0.82rem",
                        cursor: "pointer",
                        fontWeight: 500,
                      }
                }
              >
                + Calculated Field
              </button>
            )}
            {availableToAdd.length > 0 && (
              <div style={unstyled ? undefined : { display: "inline-flex", alignItems: "center", gap: "6px" }}>
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
                  style={unstyled ? undefined : SR_ONLY_STYLE}
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
                {!unstyled && (
                  <button
                    type="button"
                    data-qb="btn-toggle-add-table-strip"
                    onClick={() => {
                      setShowAddTableStrip((prev) => !prev);
                      setAddTableSearch("");
                    }}
                    style={{
                      background: showAddTableStrip
                        ? "rgba(56, 189, 248, 0.15)"
                        : "var(--qb-color-surface, #10141f)",
                      color: "var(--qb-color-text, #e2e8f0)",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.12))",
                      borderRadius: "var(--qb-radius-sm, 6px)",
                      padding: "5px 12px",
                      fontSize: "0.82rem",
                      cursor: "pointer",
                      fontWeight: 500,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "6px",
                    }}
                  >
                    <span>+ Add Table</span>
                    <span
                      style={{
                        fontSize: "0.74rem",
                        background: "rgba(255, 255, 255, 0.06)",
                        color: "var(--qb-color-text-muted, #94a3b8)",
                        padding: "1px 6px",
                        borderRadius: "4px",
                      }}
                    >
                      {availableToAdd.length}
                    </span>
                  </button>
                )}
              </div>
            )}
          </div>
          {!unstyled && showAddTableStrip && availableToAdd.length > 0 && (
            <div
              data-qb="add-table-pill-strip"
              style={{
                width: "100%",
                background: "var(--qb-color-surface, #10141f)",
                border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                borderRadius: "8px",
                padding: "8px 10px",
                display: "flex",
                flexDirection: "column",
                gap: "6px",
              }}
            >
              {availableToAdd.length > 6 && (
                <input
                  type="text"
                  value={addTableSearch}
                  onChange={(e) => setAddTableSearch(e.target.value)}
                  placeholder="Filter tables to add..."
                  style={{
                    background: "var(--qb-color-background, #090d16)",
                    border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                    borderRadius: "6px",
                    padding: "4px 9px",
                    color: "var(--qb-color-text, #e2e8f0)",
                    fontSize: "0.8rem",
                    outline: "none",
                    maxWidth: "240px",
                  }}
                />
              )}
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", maxHeight: "120px", overflowY: "auto" }}>
                {availableToAdd
                  .filter(
                    (t) =>
                      !addTableSearch.trim() ||
                      t.name.toLowerCase().includes(addTableSearch.trim().toLowerCase()),
                  )
                  .slice(0, 50)
                  .map((t) => (
                    <button
                      key={t.name}
                      type="button"
                      data-qb="add-table-pill"
                      onClick={() => {
                        onAddTableToCanvas(t.name);
                        setShowAddTableStrip(false);
                      }}
                      style={{
                        background: "var(--qb-color-surface-hover, #161b28)",
                        color: "var(--qb-color-text, #e2e8f0)",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                        borderRadius: "999px",
                        padding: "4px 10px",
                        fontSize: "0.78rem",
                        fontWeight: 500,
                        fontFamily: "var(--qb-font-mono, monospace)",
                        cursor: "pointer",
                      }}
                    >
                      {`Add ${t.name}`}
                    </button>
                  ))}
              </div>
            </div>
          )}
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
                    color: "var(--qb-color-text-muted, #64748b)",
                    border: "1px dashed var(--qb-color-border, rgba(255, 255, 255, 0.12))",
                    borderRadius: "var(--qb-radius-md, 8px)",
                    background: "var(--qb-color-surface, #10141f)",
                    width: "100%",
                    fontSize: "0.9rem",
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
                      display: "grid",
                      gridTemplateColumns:
                        activeTables.length === 1
                          ? "1fr"
                          : "repeat(auto-fit, minmax(360px, 1fr))",
                      gap: "12px",
                      alignItems: "start",
                    }
              }
            >
              {activeTables.map((t) => (
                <TableCard
                  key={t.name}
                  table={t}
                  isSelected={false}
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
                  onReorderColumns={handleReorderTableColumns}
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
          </>
        )}
      </div>

      {/* Step Panels & Projections */}
      <div
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                flexDirection: "column",
                gap: "10px",
              }
        }
      >
        {/* 1-click Foreign Key Join Suggestions */}
        {activeTables.length > 0 && suggestedJoins.length > 0 && (
          <div
            data-qb="suggested-joins-bar"
            style={
              unstyled
                ? undefined
                : activeStepTab !== "joins" && activeStepTab !== "columns"
                  ? SR_ONLY_STYLE
                  : {
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "6px",
                      flexWrap: "wrap",
                      background: "transparent",
                      border: "none",
                      fontSize: "0.82rem",
                      position: "relative",
                    }
            }
          >
            <span style={unstyled ? undefined : SR_ONLY_STYLE}>💡 Suggested Joins:</span>
            {!unstyled && (
              <span
                aria-hidden="true"
                style={{
                  fontSize: "0.72rem",
                  fontWeight: 700,
                  color: "var(--qb-color-confirmed-text, #6ee7b7)",
                  background: "var(--qb-color-confirmed-bg, rgba(16, 185, 129, 0.14))",
                  border: "1px solid var(--qb-color-confirmed-border, rgba(16, 185, 129, 0.38))",
                  borderRadius: "999px",
                  padding: "2px 8px",
                  whiteSpace: "nowrap",
                }}
              >
                ✓ Confirmed Joins:
              </span>
            )}
            {suggestedJoins.slice(0, 4).map(({ candidate, edge }, idx) => {
              const hideVisually = suggestedJoins.length > 2 && idx >= 1 && activeStepTab !== "joins";
              return (
                <button
                  key={candidate}
                  type="button"
                  data-testid={`fk-join-suggestion-${candidate}`}
                  data-qb-join-tier="confirmed"
                  onClick={() => handleQuickJoinFk(candidate)}
                  style={
                    unstyled
                      ? undefined
                      : hideVisually
                        ? SR_ONLY_STYLE
                        : {
                            background: "var(--qb-color-surface, #10141f)",
                            color: "var(--qb-color-confirmed-text, #6ee7b7)",
                            border: "1px solid var(--qb-color-confirmed-border, rgba(16, 185, 129, 0.38))",
                            borderRadius: "999px",
                            padding: "4px 10px",
                            fontSize: "0.78rem",
                            cursor: "pointer",
                            fontWeight: 600,
                            whiteSpace: "nowrap",
                          }
                  }
                  title={`Confirmed Join: Join ${candidate} on ${describeLink(edge)}`}
                >
                  + Join {candidate}
                </button>
              );
            })}
            {suggestedJoins.length > 4 && (
              <div style={unstyled ? undefined : { display: "inline-flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                <button
                  type="button"
                  data-qb="btn-more-suggested-joins"
                  onClick={() => {
                    setIsMoreJoinsExpanded((prev) => !prev);
                    setMoreJoinsSearch("");
                  }}
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: isMoreJoinsExpanded
                            ? "var(--qb-color-surface-active, #1c2232)"
                            : "transparent",
                          color: "var(--qb-color-text-muted, #94a3b8)",
                          border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                          borderRadius: "999px",
                          padding: "4px 10px",
                          fontSize: "0.78rem",
                          cursor: "pointer",
                          fontWeight: 500,
                          whiteSpace: "nowrap",
                        }
                  }
                >
                  +{suggestedJoins.length - 4} more FK joins
                </button>
                {isMoreJoinsExpanded && (
                  <div
                    data-qb="more-suggested-joins-popover"
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      gap: "6px",
                      width: "100%",
                      padding: "8px 10px",
                      background: "var(--qb-color-surface, #10141f)",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.12))",
                      borderRadius: "8px",
                    }}
                  >
                    <input
                      type="text"
                      value={moreJoinsSearch}
                      onChange={(e) => setMoreJoinsSearch(e.target.value)}
                      placeholder={`Search ${suggestedJoins.length - 4} more FK tables...`}
                      style={{
                        background: "var(--qb-color-background, #090d16)",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                        borderRadius: "6px",
                        padding: "4px 8px",
                        color: "var(--qb-color-text, #e2e8f0)",
                        fontSize: "0.78rem",
                        outline: "none",
                      }}
                    />
                    {suggestedJoins
                      .slice(4)
                      .filter(
                        ({ candidate, edge }) =>
                          !moreJoinsSearch.trim() ||
                          candidate.toLowerCase().includes(moreJoinsSearch.trim().toLowerCase()) ||
                          describeLink(edge).toLowerCase().includes(moreJoinsSearch.trim().toLowerCase()),
                      )
                      .map(({ candidate, edge }) => (
                        <button
                          key={candidate}
                          type="button"
                          data-testid={`fk-join-suggestion-${candidate}`}
                          onClick={() => {
                            handleQuickJoinFk(candidate);
                            setIsMoreJoinsExpanded(false);
                          }}
                          style={{
                            background: "var(--qb-color-surface-hover, #161b28)",
                            color: "var(--qb-color-text, #e2e8f0)",
                            border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                            borderRadius: "999px",
                            padding: "4px 10px",
                            fontSize: "0.76rem",
                            fontWeight: 500,
                            cursor: "pointer",
                          }}
                          title={`Join ${candidate} on ${describeLink(edge)}`}
                        >
                          + Join {candidate}
                        </button>
                      ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Projection fields & query options manager */}
        {isProjectionsVisible &&
          (activeTables.length > 0 || orderedProjectionKeys.length > 0 || windowFunctions.length > 0) && (
          <div
            data-qb="canvas-projections"
            className={cx(classNames?.columns)}
            style={
              unstyled
                ? undefined
                : activeStepTab !== "columns" && activeStepTab !== "sorts"
                  ? SR_ONLY_STYLE
                  : {
                      background: "var(--qb-color-surface, #10141f)",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                      borderRadius: "var(--qb-radius-md, 8px)",
                      padding: "10px 14px",
                      display: "flex",
                      flexDirection: "column",
                      gap: "10px",
                      width: "100%",
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
                    flexWrap: "wrap",
                    gap: "10px",
                  }
            }
          >
            <span
              className={cx(classNames?.title)}
              style={
                unstyled
                  ? undefined
                  : { fontSize: "0.84rem", fontWeight: 600, color: "var(--qb-color-text, #f8fafc)" }
              }
            >
              {unstyled ? (
                orderedProjectionKeys.length > 0
                  ? `✨ Selected Columns & Projections (${orderedProjectionKeys.length})`
                  : "✨ Projections: All Columns (SELECT *)"
              ) : orderedProjectionKeys.length > 0 ? (
                <>
                  <span style={unstyled ? undefined : SR_ONLY_STYLE}>
                    {`✨ Selected Columns & Projections (${orderedProjectionKeys.length})`}
                  </span>
                  <span aria-hidden="true">
                    {`Selected Columns (${orderedProjectionKeys.length}) — drag to reorder`}
                  </span>
                </>
              ) : (
                <>
                  <span style={SR_ONLY_STYLE}>✨ Projections: All Columns (SELECT *)</span>
                  <span aria-hidden="true">Columns to show: All columns</span>
                </>
              )}
            </span>
            {isDistinctLimitVisible && (
              <div
                style={
                  unstyled
                    ? undefined
                    : { display: "flex", alignItems: "center", gap: "14px", flexWrap: "wrap" }
                }
              >
                <label
                  title="Only include unique rows (SQL DISTINCT)"
                  style={
                    unstyled
                      ? undefined
                      : {
                          fontSize: "0.82rem",
                          color: isDistinct
                            ? "var(--qb-color-active-text, #e0f2fe)"
                            : "var(--qb-color-text-secondary, #94a3b8)",
                          background: isDistinct
                            ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.14))"
                            : "var(--qb-color-background, #090d16)",
                          border: isDistinct
                            ? "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.4))"
                            : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                          borderRadius: "999px",
                          padding: "3px 10px",
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          cursor: "pointer",
                          fontWeight: isDistinct ? 700 : 500,
                        }
                  }
                >
                  <input
                    type="checkbox"
                    data-qb="checkbox-distinct"
                    checked={isDistinct}
                    onChange={(e) => onDistinctChange(e.target.checked)}
                    style={
                      unstyled
                        ? undefined
                        : { accentColor: "var(--qb-color-primary, #3b82f6)", margin: 0, width: "14px", height: "14px" }
                    }
                  />
                  {unstyled ? (
                    "DISTINCT"
                  ) : (
                    <>
                      <span style={SR_ONLY_STYLE}>DISTINCT</span>
                      <span aria-hidden="true">Unique rows only</span>
                    </>
                  )}
                </label>
                <div
                  style={
                    unstyled
                      ? undefined
                      : { display: "flex", alignItems: "center", gap: "8px" }
                  }
                >
                  <span style={unstyled ? undefined : { fontSize: "0.82rem", color: "var(--qb-color-text-muted, #94a3b8)", fontWeight: 500 }}>
                    {unstyled ? (
                      "Limit:"
                    ) : (
                      <>
                        <span style={SR_ONLY_STYLE}>Limit:</span>
                        <span aria-hidden="true">Max rows:</span>
                      </>
                    )}
                  </span>
                  <select
                    value={limit}
                    aria-label="Query row limit"
                    data-qb="input-limit"
                    onChange={(e) => onLimitChange(Number(e.target.value))}
                    style={unstyled ? undefined : SR_ONLY_STYLE}
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
                  {!unstyled && (
                    <div
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "2px",
                        background: "var(--qb-color-background, #090d16)",
                        padding: "3px",
                        borderRadius: "6px",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                      }}
                      role="group"
                      aria-label="Row limit pills"
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
                            data-qb="limit-pill"
                            data-qb-limit={lv}
                            aria-pressed={active}
                            onClick={() => onLimitChange(lv)}
                            style={{
                              padding: "3px 9px",
                              fontSize: "0.8rem",
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
              </div>
            )}
          </div>

          {!unstyled && effectiveDateBucketCol && dateBucketColumns.length > 0 && (
            <div
              data-qb="guided-date-bucketing"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                flexWrap: "wrap",
                padding: "6px 10px",
                borderRadius: "6px",
                background: "var(--qb-color-background, #090d16)",
                border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.07))",
              }}
            >
              <span
                style={{
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  color: "var(--qb-color-logical-text, #e9d5ff)",
                  whiteSpace: "nowrap",
                }}
              >
                📅 Date Bucket:
              </span>
              <select
                data-qb="guided-date-column-select"
                aria-label="Date column for bucketing"
                value={effectiveDateBucketCol.key}
                onChange={(e) => setSelectedDateBucketColKey(e.target.value)}
                style={{
                  background: "var(--qb-color-surface, #10141f)",
                  color: "var(--qb-color-text, #e2e8f0)",
                  border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.12))",
                  borderRadius: "5px",
                  padding: "3px 8px",
                  fontSize: "0.76rem",
                  fontFamily: "var(--qb-font-mono, monospace)",
                  outline: "none",
                }}
              >
                {dateBucketColumns.map((dc) => (
                  <option key={dc.key} value={dc.key}>
                    {`${dc.column} (${dc.table})`}
                  </option>
                ))}
              </select>
              <div style={{ display: "inline-flex", alignItems: "center", gap: "4px", flexWrap: "wrap" }}>
                {GUIDED_DATE_GRAINS.map((g) => {
                  const activeGrain = selectedColumns[effectiveDateBucketCol.key]?.timeGrain;
                  const isActive = activeGrain === g.value;
                  return (
                    <button
                      key={g.value}
                      type="button"
                      data-qb="date-bucket-pill"
                      data-qb-grain={g.value}
                      aria-pressed={isActive}
                      onClick={() => {
                        const target = effectiveDateBucketCol;
                        if (isActive) {
                          onUpdateColumnSelect(target.key, { timeGrain: undefined });
                          return;
                        }
                        if (!selectedColumns[target.key]) {
                          onToggleColumn(target.table, target.column);
                        }
                        onUpdateColumnSelect(target.key, {
                          table: target.table,
                          name: target.column,
                          timeGrain: g.value,
                          aggregate: undefined,
                        });
                      }}
                      style={{
                        padding: "3px 9px",
                        borderRadius: "999px",
                        fontSize: "0.74rem",
                        fontWeight: isActive ? 700 : 500,
                        border: isActive
                          ? "1px solid rgba(168, 85, 247, 0.55)"
                          : "1px solid rgba(255, 255, 255, 0.1)",
                        background: isActive
                          ? "rgba(168, 85, 247, 0.22)"
                          : "var(--qb-color-surface, #10141f)",
                        color: isActive ? "#e9d5ff" : "var(--qb-color-text-secondary, #94a3b8)",
                        cursor: "pointer",
                      }}
                    >
                      {g.label}
                    </button>
                  );
                })}
                {selectedColumns[effectiveDateBucketCol.key]?.timeGrain && (
                  <button
                    type="button"
                    data-qb="date-bucket-clear"
                    onClick={() =>
                      onUpdateColumnSelect(effectiveDateBucketCol.key, {
                        timeGrain: undefined,
                      })
                    }
                    style={{
                      padding: "3px 8px",
                      borderRadius: "999px",
                      fontSize: "0.72rem",
                      border: "1px solid rgba(255, 255, 255, 0.08)",
                      background: "transparent",
                      color: "var(--qb-color-text-muted, #64748b)",
                      cursor: "pointer",
                    }}
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>
          )}

          {(orderedProjectionKeys.length > 0 || windowFunctions.length > 0) && (
            <div
              style={
                unstyled
                  ? undefined
                  : {
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "8px",
                    }
              }
            >
              {orderedProjectionKeys.map((key, idx) => {
                const item = selectedColumns[key];
                if (!item) return null;
                const isCalculated = Boolean(item.rawExpression || item.caseWhen);
                const isDragging = draggedColIndex === idx;
                const isDragOver = dragOverColIndex === idx && draggedColIndex !== idx;

                return (
                  <div
                    key={key}
                    data-qb="projection-item"
                    data-qb-column={key}
                    draggable={true}
                    {...makeColDragHandlers(idx, true)}
                    className={cx(classNames?.projectionItem)}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: isDragOver
                              ? "rgba(56, 189, 248, 0.16)"
                              : "var(--qb-color-surface-hover, #161b28)",
                            border: isDragOver
                              ? "1px dashed #38bdf8"
                              : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                            borderRadius: "6px",
                            padding: "5px 10px",
                            display: "inline-flex",
                            flexWrap: "wrap",
                            alignItems: "center",
                            gap: "6px",
                            fontSize: "0.85rem",
                            cursor: "grab",
                            opacity: isDragging ? 0.55 : 1,
                          }
                    }
                  >
                    {!unstyled && (
                      <span
                        aria-hidden="true"
                        data-qb="drag-handle"
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
                                color: "var(--qb-color-text-muted, #64748b)",
                                cursor: "pointer",
                                padding: "0 2px",
                                fontSize: "0.75rem",
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
                          : { color: "var(--qb-color-text, #e2e8f0)", fontWeight: 500 }
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
                      placeholder="as..."
                      value={item.alias || ""}
                      onChange={(e) =>
                        onUpdateColumnSelect(key, { alias: e.target.value })
                      }
                      className={cx(classNames?.projectionAlias)}
                      style={
                        unstyled
                          ? undefined
                          : {
                              background: "transparent",
                              border: "none",
                              borderBottom: item.alias
                                ? "1px solid var(--qb-color-border-focus, rgba(255, 255, 255, 0.2))"
                                : "1px dashed var(--qb-color-border, rgba(255, 255, 255, 0.12))",
                              padding: "1px 4px",
                              color: "var(--qb-color-text-muted, #94a3b8)",
                              fontSize: "0.8rem",
                              width: item.alias ? "64px" : "42px",
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
                                background: "rgba(255, 255, 255, 0.06)",
                                color: "var(--qb-color-text-secondary, #94a3b8)",
                                fontSize: "0.74rem",
                                fontWeight: 600,
                                padding: "2px 6px",
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
                        style={unstyled ? undefined : SR_ONLY_STYLE}
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
                        style={unstyled ? undefined : SR_ONLY_STYLE}
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

                    {!unstyled && !item.metric && !isCalculated && (
                      <div style={{ display: "inline-flex", alignItems: "center", gap: "4px", flexWrap: "wrap" }}>
                        <button
                          type="button"
                          data-qb="projection-fx-toggle"
                          onClick={() =>
                            setOpenProjectionMenuKey((prev) => (prev === key ? null : key))
                          }
                          title="Toggle inline aggregate & time grain pills"
                          style={{
                            background:
                              item.aggregate || item.timeGrain || openProjectionMenuKey === key
                                ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.16))"
                                : "transparent",
                            color:
                              item.aggregate || item.timeGrain || openProjectionMenuKey === key
                                ? "var(--qb-color-active-text, #e0f2fe)"
                                : "var(--qb-color-text-muted, #64748b)",
                            border: `1px solid ${
                              item.aggregate || item.timeGrain || openProjectionMenuKey === key
                                ? "var(--qb-color-active-border, rgba(56, 189, 248, 0.4))"
                                : "var(--qb-color-border, rgba(255, 255, 255, 0.08))"
                            }`,
                            borderRadius: "4px",
                            padding: "1px 6px",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          {item.aggregate
                            ? `Σ ${item.aggregate === "COUNT_DISTINCT" ? "DISTINCT" : item.aggregate}`
                            : item.timeGrain
                              ? `${item.timeGrain}`
                              : "ƒx"}
                        </button>

                        {openProjectionMenuKey === key && (
                          <div
                            data-qb="projection-inline-pills"
                            style={{
                              display: "inline-flex",
                              flexWrap: "wrap",
                              alignItems: "center",
                              gap: "3px",
                              background: "var(--qb-color-background, #090d16)",
                              padding: "3px 5px",
                              borderRadius: "6px",
                              border: "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.3))",
                            }}
                          >
                            {AGGREGATE_OPTIONS.map((opt) => {
                              const active = (item.aggregate || "") === opt.value && !item.timeGrain;
                              return (
                                <button
                                  key={opt.value || "none"}
                                  type="button"
                                  onClick={() => {
                                    onUpdateColumnSelect(key, {
                                      aggregate: opt.value || undefined,
                                      timeGrain: undefined,
                                    });
                                    setOpenProjectionMenuKey(null);
                                  }}
                                  style={{
                                    padding: "2px 6px",
                                    fontSize: "0.72rem",
                                    fontWeight: active ? 700 : 500,
                                    borderRadius: "4px",
                                    border: "none",
                                    background: active ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.2))" : "transparent",
                                    color: active ? "var(--qb-color-active-text, #e0f2fe)" : "var(--qb-color-text-secondary, #94a3b8)",
                                    cursor: "pointer",
                                  }}
                                >
                                  {opt.label}
                                </button>
                              );
                            })}
                            {TIME_GRAIN_OPTIONS.filter((t) => t.value !== "").map((opt) => {
                              const active = (item.timeGrain || "") === opt.value;
                              return (
                                <button
                                  key={opt.value}
                                  type="button"
                                  onClick={() => {
                                    onUpdateColumnSelect(key, {
                                      timeGrain: (opt.value as TimeGrain) || undefined,
                                      aggregate: opt.value ? undefined : item.aggregate,
                                    });
                                    setOpenProjectionMenuKey(null);
                                  }}
                                  style={{
                                    padding: "2px 6px",
                                    fontSize: "0.72rem",
                                    fontWeight: active ? 700 : 500,
                                    borderRadius: "4px",
                                    border: "none",
                                    background: active ? "var(--qb-color-logical-bg, rgba(168, 85, 247, 0.2))" : "transparent",
                                    color: active ? "var(--qb-color-logical-text, #e9d5ff)" : "var(--qb-color-text-muted, #64748b)",
                                    cursor: "pointer",
                                  }}
                                >
                                  {opt.label}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
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
                                color: "var(--qb-color-text-muted, #64748b)",
                                cursor: "pointer",
                                padding: "0 2px",
                                fontSize: "0.75rem",
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
                              color: "var(--qb-color-text-muted, #64748b)",
                              cursor: "pointer",
                              padding: "0 2px",
                              fontSize: "0.8rem",
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
                          background: "var(--qb-color-surface-hover, #161b28)",
                          border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                          borderRadius: "6px",
                          padding: "5px 10px",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "6px",
                          fontSize: "0.85rem",
                        }
                  }
                >
                  <span style={unstyled ? undefined : { color: "var(--qb-color-text, #e2e8f0)", fontWeight: 500 }}>
                    {unstyled ? (
                      `🪟 ${wf.function}(${wf.column || ""}) AS ${wf.alias}`
                    ) : (
                      <>
                        <span style={SR_ONLY_STYLE}>{`🪟 ${wf.function}(${wf.column || ""}) AS ${wf.alias}`}</span>
                        <span aria-hidden="true">{`${wf.function}(${wf.column || ""}) AS ${wf.alias}`}</span>
                      </>
                    )}
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
                              color: "var(--qb-color-text-muted, #64748b)",
                              cursor: "pointer",
                              fontSize: "0.8rem",
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
          )}
        </div>
        )}

        {/* Clause Editors (Joins, Filters, Sorts): displayed according to activeStepTab while preserving DOM presence */}
        {(isJoinsVisible || isFiltersVisible || isSortsVisible) && (
          <div
            data-qb="clause-editors-grid"
            style={
              unstyled
                ? undefined
                : joins.length === 0 && filters.length === 0 && sorts.length === 0
                  ? {
                      display: "contents",
                      gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
                    }
                  : {
                      display: "contents",
                      gridTemplateColumns: "1fr",
                    }
            }
          >
            {/* STEP 2: Relational Joins */}
            {isJoinsVisible && (
              <div
                data-qb="step-panel-joins"
                style={
                  unstyled
                    ? undefined
                    : activeStepTab !== "joins"
                      ? SR_ONLY_STYLE
                      : { width: "100%" }
                }
              >
                <TableJoinEditor
                  joins={joins}
                  activeTables={activeTables}
                  allTables={allTables}
                  schema={schema}
                  onChange={onJoinsChange}
                  unstyled={unstyled}
                  classNames={classNames}
                />
              </div>
            )}

            {/* STEP 3: Filter Conditions */}
            {isFiltersVisible && (
              <div
                data-qb="step-panel-filters"
                style={
                  unstyled
                    ? undefined
                    : activeStepTab !== "filters"
                      ? SR_ONLY_STYLE
                      : { width: "100%" }
                }
              >
                <TableFiltersEditor
                  filters={filters}
                  activeTables={activeTables}
                  onChange={onFiltersChange}
                  unstyled={unstyled}
                  customOperators={customOperators}
                  fieldRenderers={fieldRenderers}
                  classNames={classNames}
                  sampleRows={sampleRows}
                  onFetchDistinctValues={onFetchDistinctValues}
                />
              </div>
            )}

            {/* STEP 4: Sorting & Limit */}
            {isSortsVisible && (
              <div
                data-qb="step-panel-sorts"
                style={
                  unstyled
                    ? undefined
                    : activeStepTab !== "sorts"
                      ? SR_ONLY_STYLE
                      : { width: "100%" }
                }
              >
                <TableSortsEditor
                  sorts={sorts}
                  activeTables={activeTables}
                  selectedColumns={selectedColumns}
                  limit={limit}
                  onLimitChange={onLimitChange}
                  onChange={onSortsChange}
                  unstyled={unstyled}
                  classNames={classNames}
                />
              </div>
            )}
          </div>
        )}
      </div>

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

      {/* Collapsible Live SQL Preview Bar (visually hidden in styled mode) */}
      {compiledSql && (
        <div
          data-qb="live-sql-preview"
          style={unstyled ? undefined : SR_ONLY_STYLE}
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
            >
              <span>{isSqlPreviewOpen ? "▼" : "▶"}</span>
              <span>Live SQL Preview</span>
              {!isSqlPreviewOpen && (
                <code>{compiledSql.replace(/\s+/g, " ")}</code>
              )}
            </button>
            <button
              type="button"
              data-qb="btn-copy-live-sql"
              onClick={handleCopyLiveSql}
            >
              {copiedSql ? "✓ Copied" : "Copy SQL"}
            </button>
          </div>
          {isSqlPreviewOpen && (
            <pre data-qb="live-sql-preview-code">{compiledSql}</pre>
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
