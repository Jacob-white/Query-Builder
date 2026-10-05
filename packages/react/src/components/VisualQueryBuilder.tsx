import React, { useState, useMemo, useRef, useEffect } from "react";
import type {
  VisualQueryBuilderProps,
  TableMeta,
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  QueryResultData,
  QueryTemplate,
  DatabaseSchemaDefinition,
} from "../types";
import { QueryCanvas } from "./QueryCanvas";
import { QueryResultsTable } from "./QueryResultsTable";
import { SchemaErdModal } from "./SchemaErdModal";
import { SchemaExplorerModal } from "./SchemaExplorerModal";
import { QueryChartPreview } from "./QueryChartPreview";
import { QueryTemplateManager } from "./QueryTemplateManager";
import { compileVisualState } from "../utils/compiler";
import { validateSqlSafety } from "../utils/safety";
import { normalizeSchema } from "../utils/schemaUtils";
import { parseSqlToSpec } from "../utils/sqlParser";
import { specToState } from "../hooks/useQueryState";
import { findBestJoinCondition } from "../utils/joinUtils";
import { useTheme } from "../theme/ThemeProvider";
import { darkTheme, lightTheme, themeToCssVariables, type QueryBuilderTheme } from "../theme/tokens";
import { useQueryBuilderContext } from "../theme/QueryBuilderProvider";

export type ExtendedVisualQueryBuilderProps<Schema extends DatabaseSchemaDefinition = any> = Omit<
  VisualQueryBuilderProps<Schema>,
  "theme"
> & {
  theme?: "dark" | "light" | "auto" | QueryBuilderTheme;
  unstyled?: boolean;
};

export const VisualQueryBuilder: React.FC<ExtendedVisualQueryBuilderProps> = ({
  schema,
  presets = [],
  initialTable,
  dialect = "postgres",
  onExecuteQuery: propExecuteQuery,
  onSaveQuery,
  theme: propTheme,
  readOnly = false,
  unstyled: propUnstyled = false,
  mode: propMode,
  customOperators: propCustomOperators,
  fieldRenderers: propFieldRenderers,
  cellRenderers: propCellRenderers,
}) => {
  const { theme: contextTheme } = useTheme();
  const qbContext = useQueryBuilderContext();

  const effectiveMode = propMode ?? qbContext?.mode ?? (propUnstyled ? "unstyled" : "styled");
  const unstyled = propUnstyled || effectiveMode === "unstyled";

  const customOperators = propCustomOperators ?? qbContext?.customOperators;
  const fieldRenderers = propFieldRenderers ?? qbContext?.fieldRenderers;
  const cellRenderers = propCellRenderers ?? qbContext?.cellRenderers;
  const onExecuteQuery = propExecuteQuery ?? qbContext?.onExecuteQuery;

  const activeTheme: QueryBuilderTheme = useMemo(() => {
    if (propTheme && typeof propTheme === "object" && "colors" in propTheme) {
      return propTheme as QueryBuilderTheme;
    }
    if (propTheme === "light") {
      return lightTheme;
    }
    if (propTheme === "dark") {
      return darkTheme;
    }
    return contextTheme;
  }, [propTheme, contextTheme]);

  const cssVars = useMemo(
    () => (unstyled ? {} : themeToCssVariables(activeTheme)),
    [activeTheme, unstyled],
  );

  const normalizedSchema = useMemo(() => normalizeSchema(schema), [schema]);
  const allTables = useMemo(() => Object.values(normalizedSchema?.tables || {}), [normalizedSchema]);
  const defaultTable = initialTable || allTables[0]?.name || "";

  const [activeTab, setActiveTab] = useState<"visual" | "sql" | "results" | "chart">("visual");
  const [primaryTable, setPrimaryTable] = useState<string>(defaultTable);
  const [activeTableNames, setActiveTableNames] = useState<string[]>(
    defaultTable ? [defaultTable] : [],
  );

  const [selectedColumns, setSelectedColumns] = useState<
    Record<string, VisualColumnSelect>
  >({});
  const [orderedProjectionKeys, setOrderedProjectionKeys] = useState<string[]>([]);
  const [joins, setJoins] = useState<VisualJoin[]>([]);
  const [filters, setFilters] = useState<VisualFilter[]>([]);
  const [sorts, setSorts] = useState<VisualSort[]>([]);
  const [isDistinct, setIsDistinct] = useState<boolean>(false);
  const [limit, setLimit] = useState<number>(50);

  const [rawSql, setRawSql] = useState<string>("");
  const [isRawMode, setIsRawMode] = useState<boolean>(false);
  const [isErdOpen, setIsErdOpen] = useState<boolean>(false);
  const [isSchemaExplorerOpen, setIsSchemaExplorerOpen] = useState<boolean>(false);
  const [isTemplateManagerOpen, setIsTemplateManagerOpen] = useState<boolean>(false);
  const [templateManagerMode, setTemplateManagerMode] = useState<"library" | "save">("library");

  const [queryResults, setQueryResults] = useState<QueryResultData | null>(null);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [executionError, setExecutionError] = useState<string | null>(null);

  const tabRefs = {
    visual: useRef<HTMLButtonElement | null>(null),
    sql: useRef<HTMLButtonElement | null>(null),
    results: useRef<HTMLButtonElement | null>(null),
    chart: useRef<HTMLButtonElement | null>(null),
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (isErdOpen) setIsErdOpen(false);
        if (isSchemaExplorerOpen) setIsSchemaExplorerOpen(false);
        if (isTemplateManagerOpen) setIsTemplateManagerOpen(false);
      }
    };
    if (typeof window !== "undefined") {
      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }
  }, [isErdOpen, isSchemaExplorerOpen, isTemplateManagerOpen]);

  // Active table metadata
  const activeTables: TableMeta[] = useMemo(() => {
    return activeTableNames
      .map((name) => normalizedSchema?.tables?.[name])
      .filter((t): t is TableMeta => Boolean(t));
  }, [activeTableNames, normalizedSchema]);

  // Compiled visual query
  const compiled = useMemo(() => {
    return compileVisualState(
      primaryTable,
      selectedColumns,
      orderedProjectionKeys,
      joins,
      filters,
      sorts,
      isDistinct,
      limit,
      normalizedSchema,
      dialect,
      "AND",
      customOperators,
    );
  }, [
    primaryTable,
    selectedColumns,
    orderedProjectionKeys,
    joins,
    filters,
    sorts,
    isDistinct,
    limit,
    normalizedSchema,
    dialect,
    customOperators,
  ]);

  const currentSql = isRawMode ? rawSql : compiled.sql;
  const safety = useMemo(() => validateSqlSafety(currentSql), [currentSql]);

  // Handle column selection toggle
  const handleToggleColumn = (tableName: string, colName: string) => {
    const key = `${tableName}.${colName}`;
    setSelectedColumns((prev) => {
      const next = { ...prev };
      if (next[key]) {
        delete next[key];
        setOrderedProjectionKeys((keys) => keys.filter((k) => k !== key));
      } else {
        next[key] = { table: tableName, name: colName };
        setOrderedProjectionKeys((keys) => [...keys, key]);
      }
      return next;
    });
  };

  // Add table to canvas
  const handleAddTableToCanvas = (tableName: string) => {
    if (!tableName) return;
    if (!activeTableNames.includes(tableName)) {
      setActiveTableNames((prev) => [...prev, tableName]);
    }
    if (!primaryTable) {
      setPrimaryTable(tableName);
    }
  };

  // Remove table from canvas
  const handleRemoveTable = (tableName: string) => {
    setActiveTableNames((prev) => {
      const next = prev.filter((t) => t !== tableName);
      if (primaryTable === tableName) {
        setPrimaryTable(next[0] || "");
      }
      return next;
    });
    setJoins((prev) => prev.filter((j) => j.table !== tableName && j.left_table !== tableName));
    setSelectedColumns((prev) => {
      const next = { ...prev };
      Object.keys(next).forEach((k) => {
        if (next[k].table === tableName) delete next[k];
      });
      return next;
    });
    setOrderedProjectionKeys((prev) => prev.filter((k) => !k.startsWith(`${tableName}.`)));
  };

  // Synchronize Joins and active table names
  const handleJoinsChange = (newJoins: VisualJoin[]) => {
    setJoins(newJoins);
    setActiveTableNames((prev) => {
      const set = new Set(prev);
      for (const j of newJoins) {
        if (j.table) set.add(j.table);
        if (j.left_table) set.add(j.left_table);
      }
      return Array.from(set);
    });
  };

  const handleAddJoinToTable = (tableName: string) => {
    const allTableNames = normalizedSchema?.tables ? Object.keys(normalizedSchema.tables) : [];
    const candidate = allTableNames.find((t) => t !== tableName && !activeTableNames.includes(t));
    if (candidate) {
      const cond = findBestJoinCondition(tableName, candidate, normalizedSchema);
      const newJoin: VisualJoin = {
        id: `join-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
        type: "LEFT JOIN",
        left_table: cond.leftTable,
        left_col: cond.leftCol,
        table: cond.rightTable,
        right_col: cond.rightCol,
      };
      handleJoinsChange([...joins, newJoin]);
    }
  };

  // Raw SQL input change with bidirectional sync
  const handleRawSqlChange = (newSql: string) => {
    setIsRawMode(true);
    setRawSql(newSql);

    const parsed = parseSqlToSpec(newSql, normalizedSchema);
    if (parsed && parsed.table) {
      const converted = specToState(parsed);
      if (converted.primaryTable) setPrimaryTable(converted.primaryTable);
      if (converted.activeTables && converted.activeTables.length > 0) {
        setActiveTableNames(converted.activeTables);
      }
      if (converted.selectedColumns) setSelectedColumns(converted.selectedColumns);
      if (converted.orderedProjectionKeys) setOrderedProjectionKeys(converted.orderedProjectionKeys);
      if (converted.joins) setJoins(converted.joins);
      if (converted.filters) setFilters(converted.filters);
      if (converted.sorts) setSorts(converted.sorts);
      if (converted.isDistinct !== undefined) setIsDistinct(converted.isDistinct);
      if (converted.limit !== undefined) setLimit(converted.limit);
    }
  };

  const handleSyncWithVisualCanvas = () => {
    const parsed = parseSqlToSpec(rawSql, normalizedSchema);
    if (parsed && parsed.table) {
      const converted = specToState(parsed);
      if (converted.primaryTable) setPrimaryTable(converted.primaryTable);
      if (converted.activeTables && converted.activeTables.length > 0) {
        setActiveTableNames(converted.activeTables);
      }
      if (converted.selectedColumns) setSelectedColumns(converted.selectedColumns);
      if (converted.orderedProjectionKeys) setOrderedProjectionKeys(converted.orderedProjectionKeys);
      if (converted.joins) setJoins(converted.joins);
      if (converted.filters) setFilters(converted.filters);
      if (converted.sorts) setSorts(converted.sorts);
      if (converted.isDistinct !== undefined) setIsDistinct(converted.isDistinct);
      if (converted.limit !== undefined) setLimit(converted.limit);
    }
    setRawSql(compiled.sql);
    setIsRawMode(false);
  };

  // Execute current query
  const handleRunQuery = async () => {
    if (!onExecuteQuery) return;
    setIsRunning(true);
    setExecutionError(null);
    try {
      const parsedSpec = isRawMode
        ? (parseSqlToSpec(currentSql, normalizedSchema) as any) || compiled.spec
        : compiled.spec;
      const result = await onExecuteQuery(currentSql, parsedSpec);
      if (result) {
        setQueryResults(result);
        setActiveTab("results");
      }
    } catch (err: unknown) {
      setExecutionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsRunning(false);
    }
  };

  // Save template handler
  const handleSaveTemplate = (template: QueryTemplate) => {
    if (onSaveQuery) {
      const parsedSpec = isRawMode
        ? (parseSqlToSpec(template.sql, normalizedSchema) as any) || template.spec || compiled.spec
        : template.spec || compiled.spec;
      onSaveQuery(template.title, template.sql, parsedSpec);
    }
    setIsTemplateManagerOpen(false);
  };

  // Load template handler
  const handleLoadTemplate = (template: QueryTemplate) => {
    if (template.spec && Object.keys(template.spec).length > 0) {
      const s = template.spec as any;
      const pTable = s.table || s.primaryTable || "";
      if (pTable) {
        setPrimaryTable(pTable);
      }
      if (Array.isArray(s.activeTables)) {
        setActiveTableNames(s.activeTables);
      } else if (pTable) {
        setActiveTableNames([pTable]);
      }

      if (s.selectedColumns && typeof s.selectedColumns === "object") {
        setSelectedColumns(s.selectedColumns);
        if (Array.isArray(s.orderedProjectionKeys)) {
          setOrderedProjectionKeys(s.orderedProjectionKeys);
        }
      } else if (Array.isArray(s.columns)) {
        const newSelected: Record<string, VisualColumnSelect> = {};
        const newKeys: string[] = [];
        s.columns.forEach((colItem: any) => {
          if (!colItem || colItem === "*") return;
          if (typeof colItem === "string") {
            let tbl = pTable;
            let col = colItem;
            if (colItem.includes(".")) {
              const lastDot = colItem.lastIndexOf(".");
              tbl = colItem.substring(0, lastDot);
              col = colItem.substring(lastDot + 1);
            }
            const key = `${tbl}.${col}`;
            newSelected[key] = { table: tbl, name: col };
            newKeys.push(key);
          } else if (typeof colItem === "object" && colItem.column) {
            let tbl = pTable;
            let col = colItem.column;
            if (col.includes(".")) {
              const lastDot = col.lastIndexOf(".");
              tbl = col.substring(0, lastDot);
              col = col.substring(lastDot + 1);
            }
            const key = `${tbl}.${col}`;
            newSelected[key] = {
              table: tbl,
              name: col,
              aggregate: colItem.agg ? colItem.agg.toUpperCase() : undefined,
              alias: colItem.alias,
            };
            newKeys.push(key);
          }
        });
        setSelectedColumns(newSelected);
        setOrderedProjectionKeys(newKeys);
      }

      if (Array.isArray(s.joins)) {
        const mappedJoins: VisualJoin[] = s.joins.map((j: any, idx: number) => {
          const jType = (j.type || "LEFT").toUpperCase();
          const fullType = jType.endsWith(" JOIN") ? jType : `${jType} JOIN`;
          let leftTbl = j.left_table;
          let leftC = j.left_col;
          if (!leftC && j.on?.[0]?.left) {
            const lStr = j.on[0].left;
            if (lStr.includes(".")) {
              const lastDot = lStr.lastIndexOf(".");
              if (!leftTbl) leftTbl = lStr.substring(0, lastDot);
              leftC = lStr.substring(lastDot + 1);
            } else {
              leftC = lStr;
            }
          }
          let rightC = j.right_col;
          if (!rightC && j.on?.[0]?.right) {
            const rStr = j.on[0].right;
            rightC = rStr.includes(".") ? rStr.substring(rStr.lastIndexOf(".") + 1) : rStr;
          }
          return {
            id: j.id || `join_${idx + 1}`,
            table: j.table,
            type: fullType as any,
            left_table: leftTbl,
            left_col: leftC || "id",
            right_col: rightC || "id",
          };
        });
        setJoins(mappedJoins);
        setActiveTableNames((prev) => {
          const joinTables = mappedJoins.map((j) => j.table);
          return Array.from(new Set([...prev, ...joinTables]));
        });
      }

      if (Array.isArray(s.filters)) {
        const mappedFilters: VisualFilter[] = s.filters.map((f: any, idx: number) => {
          let op = f.operator || f.op || "=";
          op = op.toUpperCase().replace(/_/g, " ");
          return {
            id: f.id || `filter_${idx + 1}`,
            tablePrefix: f.tablePrefix || f.table || pTable,
            column: f.column || "",
            operator: op as any,
            value: f.value ?? "",
            combiner: f.combiner || "AND",
          };
        });
        setFilters(mappedFilters);
      }

      if (Array.isArray(s.sorts)) {
        setSorts(s.sorts);
      } else if (Array.isArray(s.order_by)) {
        const mappedSorts: VisualSort[] = s.order_by.map((ord: any, idx: number) => {
          let col = ord.column || "";
          let prefix = ord.tablePrefix;
          if (!prefix && col.includes(".")) {
            const lastDot = col.lastIndexOf(".");
            prefix = col.substring(0, lastDot);
            col = col.substring(lastDot + 1);
          }
          return {
            id: `sort_${idx + 1}`,
            tablePrefix: prefix || pTable,
            column: col,
            direction: ord.direction || "ASC",
          };
        });
        setSorts(mappedSorts);
      }

      if (typeof s.distinct === "boolean") setIsDistinct(s.distinct);
      else if (typeof s.isDistinct === "boolean") setIsDistinct(s.isDistinct);

      if (typeof s.limit === "number") setLimit(s.limit);
      setIsRawMode(false);
    } else if (template.sql) {
      setRawSql(template.sql);
      setIsRawMode(true);
      setActiveTab("sql");
    }
    setIsTemplateManagerOpen(false);
  };

  const handleTabKeyDown = (
    e: React.KeyboardEvent<HTMLButtonElement>,
    tab: "visual" | "sql" | "results" | "chart",
  ) => {
    const tabs: ("visual" | "sql" | "results" | "chart")[] = ["visual", "sql", "results", "chart"];
    const currentIndex = tabs.indexOf(tab);
    let targetTab: "visual" | "sql" | "results" | "chart" | null = null;

    if (e.key === "ArrowRight") {
      e.preventDefault();
      targetTab = tabs[(currentIndex + 1) % tabs.length];
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      targetTab = tabs[(currentIndex - 1 + tabs.length) % tabs.length];
    } else if (e.key === "Home") {
      e.preventDefault();
      targetTab = tabs[0];
    } else if (e.key === "End") {
      e.preventDefault();
      targetTab = tabs[tabs.length - 1];
    }

    if (targetTab) {
      if (targetTab === "sql" && !isRawMode) {
        setRawSql(compiled.sql);
      }
      setActiveTab(targetTab);
      tabRefs[targetTab].current?.focus();
    }
  };

  return (
    <div
      data-qb="root"
      data-qb-mode={activeTab}
      data-qb-unstyled={unstyled ? "true" : undefined}
      style={
        unstyled
          ? undefined
          : {
              ...(cssVars as unknown as React.CSSProperties),
              display: "flex",
              flexDirection: "column",
              gap: "14px",
              background: activeTheme.colors.background,
              color: activeTheme.colors.text,
              borderRadius: activeTheme.radii.xl,
              border: `1px solid ${activeTheme.colors.border}`,
              padding: "16px",
              fontFamily: activeTheme.typography.fontFamily,
            }
      }
    >
      {/* Top Controls Bar */}
      <div
        data-qb="top-bar"
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "10px",
                paddingBottom: "12px",
                borderBottom: `1px solid ${activeTheme.colors.border}`,
              }
        }
      >
        <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px" }}>
          {/* Tabs */}
          <div
            role="tablist"
            aria-label="Query builder tabs"
            data-qb="tab-list"
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    background: activeTheme.colors.surface,
                    borderRadius: activeTheme.radii.md,
                    padding: "2px",
                    border: `1px solid ${activeTheme.colors.border}`,
                  }
            }
          >
            <button
              ref={tabRefs.visual}
              role="tab"
              id="tab-visual"
              aria-controls="panel-visual"
              aria-selected={activeTab === "visual"}
              tabIndex={activeTab === "visual" ? 0 : -1}
              onKeyDown={(e) => handleTabKeyDown(e, "visual")}
              type="button"
              onClick={() => setActiveTab("visual")}
              data-qb="tab"
              data-qb-tab="visual"
              style={
                unstyled
                  ? undefined
                  : {
                      background: activeTab === "visual" ? activeTheme.colors.primary : "transparent",
                      color: activeTab === "visual" ? "#fff" : activeTheme.colors.textMuted,
                      border: "none",
                      borderRadius: activeTheme.radii.sm,
                      padding: "6px 12px",
                      fontSize: activeTheme.typography.fontSizeSm,
                      fontWeight: activeTheme.typography.fontWeightSemibold,
                      cursor: "pointer",
                    }
              }
            >
              🎨 Visual Builder
            </button>
            <button
              ref={tabRefs.sql}
              role="tab"
              id="tab-sql"
              aria-controls="panel-sql"
              aria-selected={activeTab === "sql"}
              tabIndex={activeTab === "sql" ? 0 : -1}
              onKeyDown={(e) => handleTabKeyDown(e, "sql")}
              type="button"
              onClick={() => {
                if (!isRawMode) setRawSql(compiled.sql);
                setActiveTab("sql");
              }}
              data-qb="tab"
              data-qb-tab="sql"
              style={
                unstyled
                  ? undefined
                  : {
                      background: activeTab === "sql" ? activeTheme.colors.primary : "transparent",
                      color: activeTab === "sql" ? "#fff" : activeTheme.colors.textMuted,
                      border: "none",
                      borderRadius: activeTheme.radii.sm,
                      padding: "6px 12px",
                      fontSize: activeTheme.typography.fontSizeSm,
                      fontWeight: activeTheme.typography.fontWeightSemibold,
                      cursor: "pointer",
                    }
              }
            >
              📝 Raw SQL
            </button>
            <button
              ref={tabRefs.results}
              role="tab"
              id="tab-results"
              aria-controls="panel-results"
              aria-selected={activeTab === "results"}
              tabIndex={activeTab === "results" ? 0 : -1}
              onKeyDown={(e) => handleTabKeyDown(e, "results")}
              type="button"
              onClick={() => setActiveTab("results")}
              data-qb="tab"
              data-qb-tab="results"
              style={
                unstyled
                  ? undefined
                  : {
                      background: activeTab === "results" ? activeTheme.colors.primary : "transparent",
                      color: activeTab === "results" ? "#fff" : activeTheme.colors.textMuted,
                      border: "none",
                      borderRadius: activeTheme.radii.sm,
                      padding: "6px 12px",
                      fontSize: activeTheme.typography.fontSizeSm,
                      fontWeight: activeTheme.typography.fontWeightSemibold,
                      cursor: "pointer",
                    }
              }
            >
              📊 Results {queryResults ? `(${queryResults.count})` : ""}
            </button>
            <button
              ref={tabRefs.chart}
              role="tab"
              id="tab-chart"
              aria-controls="panel-chart"
              aria-selected={activeTab === "chart"}
              tabIndex={activeTab === "chart" ? 0 : -1}
              onKeyDown={(e) => handleTabKeyDown(e, "chart")}
              type="button"
              onClick={() => setActiveTab("chart")}
              data-qb="tab"
              data-qb-tab="chart"
              style={
                unstyled
                  ? undefined
                  : {
                      background: activeTab === "chart" ? activeTheme.colors.primary : "transparent",
                      color: activeTab === "chart" ? "#fff" : activeTheme.colors.textMuted,
                      border: "none",
                      borderRadius: activeTheme.radii.sm,
                      padding: "6px 12px",
                      fontSize: activeTheme.typography.fontSizeSm,
                      fontWeight: activeTheme.typography.fontWeightSemibold,
                      cursor: "pointer",
                    }
              }
            >
              📈 Visual Chart
            </button>
          </div>

          {/* Schema Explorer Button */}
          <button
            type="button"
            onClick={() => setIsSchemaExplorerOpen(true)}
            aria-label="Open schema explorer"
            data-qb="btn-schema-explorer"
            style={
              unstyled
                ? undefined
                : {
                    background: "rgba(30, 41, 59, 0.5)",
                    color: "#38bdf8",
                    border: "1px solid rgba(56, 189, 248, 0.3)",
                    borderRadius: activeTheme.radii.sm,
                    padding: "6px 12px",
                    fontSize: activeTheme.typography.fontSizeSm,
                    fontWeight: activeTheme.typography.fontWeightSemibold,
                    cursor: "pointer",
                  }
            }
          >
            🗄️ Schema Explorer
          </button>

          {/* ERD Button */}
          <button
            type="button"
            onClick={() => setIsErdOpen(true)}
            aria-label="Open schema ERD modal"
            data-qb="btn-erd"
            style={
              unstyled
                ? undefined
                : {
                    background: "rgba(30, 41, 59, 0.5)",
                    color: "#38bdf8",
                    border: "1px solid rgba(56, 189, 248, 0.3)",
                    borderRadius: activeTheme.radii.sm,
                    padding: "6px 12px",
                    fontSize: activeTheme.typography.fontSizeSm,
                    fontWeight: activeTheme.typography.fontWeightSemibold,
                    cursor: "pointer",
                  }
            }
          >
            🗺️ Schema ERD
          </button>
        </div>

        {/* Action Controls */}
        <div
          data-qb="actions-bar"
          style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "10px" }}
        >
          <span
            data-testid="dialect-badge"
            style={
              unstyled
                ? undefined
                : {
                    padding: "4px 8px",
                    background: activeTheme.colors.surface,
                    border: `1px solid ${activeTheme.colors.border}`,
                    borderRadius: activeTheme.radii.xs,
                    fontSize: activeTheme.typography.fontSizeXs,
                    fontFamily: activeTheme.typography.fontMono,
                    color: activeTheme.colors.textMuted,
                    textTransform: "uppercase",
                  }
            }
          >
            {dialect}
          </span>
          <button
            type="button"
            onClick={() => {
              setTemplateManagerMode("save");
              setIsTemplateManagerOpen(true);
            }}
            aria-label="Save query as template"
            data-qb="btn-templates"
            style={
              unstyled
                ? undefined
                : {
                    background: activeTheme.colors.successLight,
                    color: activeTheme.colors.success,
                    border: `1px solid ${activeTheme.colors.success}`,
                    borderRadius: activeTheme.radii.sm,
                    padding: "6px 12px",
                    fontSize: activeTheme.typography.fontSizeSm,
                    fontWeight: activeTheme.typography.fontWeightSemibold,
                    cursor: "pointer",
                  }
            }
          >
            💾 Save Template
          </button>
          <button
            type="button"
            onClick={() => {
              setTemplateManagerMode("library");
              setIsTemplateManagerOpen(true);
            }}
            aria-label="Open template library"
            data-qb="btn-templates"
            style={
              unstyled
                ? undefined
                : {
                    background: "rgba(99, 102, 241, 0.15)",
                    color: "#818cf8",
                    border: "1px solid rgba(99, 102, 241, 0.3)",
                    borderRadius: activeTheme.radii.sm,
                    padding: "6px 12px",
                    fontSize: activeTheme.typography.fontSizeSm,
                    fontWeight: activeTheme.typography.fontWeightSemibold,
                    cursor: "pointer",
                  }
            }
          >
            📚 Template Library
          </button>
          {/* Preset templates */}
          {presets.length > 0 && (
            <select
              aria-label="Starter query presets"
              defaultValue=""
              onChange={(e) => {
                const preset = presets.find((p) => p.id === e.target.value);
                if (preset?.sql) {
                  setRawSql(preset.sql);
                  setIsRawMode(true);
                  setActiveTab("sql");
                }
              }}
              style={
                unstyled
                  ? undefined
                  : {
                      background: activeTheme.colors.surface,
                      color: activeTheme.colors.textSecondary,
                      border: `1px solid ${activeTheme.colors.border}`,
                      borderRadius: activeTheme.radii.sm,
                      padding: "6px 10px",
                      fontSize: activeTheme.typography.fontSizeSm,
                    }
              }
            >
              <option value="" disabled>
                ⚡ Starters & Presets...
              </option>
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
          )}

          {/* Run Query Button */}
          {!readOnly && (
            <button
              type="button"
              onClick={handleRunQuery}
              disabled={isRunning || !safety.valid}
              aria-label="Run query"
              data-qb="btn-run"
              data-qb-running={isRunning ? "true" : "false"}
              style={
                unstyled
                  ? undefined
                  : {
                      background: safety.valid
                        ? activeTheme.colors.success
                        : activeTheme.colors.surfaceHover,
                      color: "#ffffff",
                      border: "none",
                      borderRadius: activeTheme.radii.sm,
                      padding: "6px 16px",
                      fontSize: activeTheme.typography.fontSizeBase,
                      fontWeight: activeTheme.typography.fontWeightBold,
                      cursor: safety.valid && !isRunning ? "pointer" : "not-allowed",
                      boxShadow: safety.valid ? "0 4px 12px rgba(16, 185, 129, 0.3)" : "none",
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                    }
              }
            >
              {isRunning ? "⏳ Running..." : "▶ Run Query"}
            </button>
          )}
        </div>
      </div>

      {/* Safety & AST Status banner */}
      <div
        role="status"
        aria-live="polite"
        data-qb="safety-badge"
        data-qb-safety={safety.valid ? "valid" : "invalid"}
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                fontSize: activeTheme.typography.fontSizeXs,
                padding: "6px 12px",
                borderRadius: activeTheme.radii.sm,
                background: safety.valid
                  ? activeTheme.colors.successLight
                  : activeTheme.colors.errorLight,
                border: safety.valid
                  ? `1px solid ${activeTheme.colors.success}`
                  : `1px solid ${activeTheme.colors.error}`,
                color: safety.valid ? activeTheme.colors.success : activeTheme.colors.error,
              }
        }
      >
        <span>
          {safety.valid
            ? "🛡️ Read-Only Protected (AST Verified)"
            : `⚠️ Security Notice: ${safety.message}`}
        </span>
        <span style={unstyled ? undefined : { color: activeTheme.colors.textMuted }}>
          Dialect: ANSI / PostgreSQL
        </span>
      </div>

      {/* Error message banner */}
      {executionError && (
        <div
          role="alert"
          aria-live="assertive"
          style={
            unstyled
              ? undefined
              : {
                  padding: "8px 12px",
                  borderRadius: activeTheme.radii.sm,
                  background: activeTheme.colors.errorLight,
                  border: `1px solid ${activeTheme.colors.error}`,
                  color: activeTheme.colors.error,
                  fontSize: activeTheme.typography.fontSizeSm,
                }
          }
        >
          ❌ {executionError}
        </div>
      )}

      {/* Tab Panels */}
      {activeTab === "visual" && (
        <div
          role="tabpanel"
          id="panel-visual"
          aria-labelledby="tab-visual"
          tabIndex={0}
          data-qb="tab-panel"
          data-qb-panel="visual"
        >
          <QueryCanvas
            schema={normalizedSchema}
            activeTables={activeTables}
            primaryTable={primaryTable}
            selectedColumns={selectedColumns}
            orderedProjectionKeys={orderedProjectionKeys}
            joins={joins}
            filters={filters}
            sorts={sorts}
            isDistinct={isDistinct}
            limit={limit}
            onToggleColumn={handleToggleColumn}
            onRemoveTable={handleRemoveTable}
            onAddTableToCanvas={handleAddTableToCanvas}
            onUpdateColumnSelect={(key, updates) =>
              setSelectedColumns((prev) => ({
                ...prev,
                [key]: { ...prev[key], ...updates },
              }))
            }
            onRemoveColumnProjection={(key) => {
              setSelectedColumns((prev) => {
                const next = { ...prev };
                delete next[key];
                return next;
              });
              setOrderedProjectionKeys((keys) => keys.filter((k) => k !== key));
            }}
            onJoinsChange={handleJoinsChange}
            onAddJoin={handleAddJoinToTable}
            onReorderProjections={setOrderedProjectionKeys}
            onFiltersChange={setFilters}
            onSortsChange={setSorts}
            onDistinctChange={setIsDistinct}
            onLimitChange={setLimit}
            unstyled={unstyled}
            customOperators={customOperators}
            fieldRenderers={fieldRenderers}
          />
        </div>
      )}

      {activeTab === "sql" && (
        <div
          role="tabpanel"
          id="panel-sql"
          aria-labelledby="tab-sql"
          tabIndex={0}
          data-qb="tab-panel"
          data-qb-panel="sql"
          style={
            unstyled
              ? undefined
              : { display: "flex", flexDirection: "column", gap: "8px" }
          }
        >
          <div
            style={
              unstyled
                ? undefined
                : { display: "flex", justifyContent: "space-between", alignItems: "center" }
            }
          >
            <span
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: activeTheme.typography.fontSizeBase,
                      color: activeTheme.colors.textMuted,
                      fontWeight: 600,
                    }
              }
            >
              Live SQL Code Editor
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              {isRawMode && !parseSqlToSpec(rawSql, normalizedSchema) && (
                <span
                  data-qb="sql-sync-badge"
                  style={
                    unstyled
                      ? undefined
                      : {
                          fontSize: "0.75rem",
                          color: "#f87171",
                          background: "rgba(239, 68, 68, 0.15)",
                          border: "1px solid rgba(239, 68, 68, 0.3)",
                          padding: "2px 8px",
                          borderRadius: "4px",
                          fontWeight: 600,
                        }
                  }
                >
                  Custom Raw SQL (Visual Canvas Unsynced)
                </span>
              )}
              <button
                type="button"
                aria-label="Sync with visual canvas"
                onClick={handleSyncWithVisualCanvas}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "transparent",
                        border: "none",
                        color: activeTheme.colors.primary,
                        cursor: "pointer",
                        fontSize: activeTheme.typography.fontSizeXs,
                      }
                }
              >
                🔄 Sync with Visual Canvas
              </button>
            </div>
          </div>
          <textarea
            aria-label="Raw SQL code"
            data-qb="sql-editor"
            value={currentSql}
            onChange={(e) => handleRawSqlChange(e.target.value)}
            rows={12}
            style={
              unstyled
                ? undefined
                : {
                    width: "100%",
                    background: activeTheme.colors.background,
                    color: "#38bdf8",
                    fontFamily: activeTheme.typography.fontMono,
                    fontSize: activeTheme.typography.fontSizeSm,
                    border: `1px solid ${activeTheme.colors.border}`,
                    borderRadius: activeTheme.radii.md,
                    padding: "12px",
                    lineHeight: 1.5,
                    resize: "vertical",
                    outline: "none",
                    boxSizing: "border-box",
                  }
            }
          />
        </div>
      )}

      {activeTab === "results" && (
        <div
          role="tabpanel"
          id="panel-results"
          aria-labelledby="tab-results"
          tabIndex={0}
          data-qb="tab-panel"
          data-qb-panel="results"
        >
          <QueryResultsTable results={queryResults} isLoading={isRunning} unstyled={unstyled} cellRenderers={cellRenderers} />
        </div>
      )}

      {activeTab === "chart" && (
        <div
          role="tabpanel"
          id="panel-chart"
          aria-labelledby="tab-chart"
          tabIndex={0}
          data-qb="tab-panel"
          data-qb-panel="chart"
        >
          <QueryChartPreview results={queryResults} unstyled={unstyled} />
        </div>
      )}

      {/* Schema ERD Modal */}
      <SchemaErdModal
        isOpen={isErdOpen}
        onClose={() => setIsErdOpen(false)}
        schema={normalizedSchema}
        onSelectTable={(tbl) => handleAddTableToCanvas(tbl)}
      />

      {/* Schema Explorer Modal */}
      <SchemaExplorerModal
        isOpen={isSchemaExplorerOpen}
        onClose={() => setIsSchemaExplorerOpen(false)}
        schema={normalizedSchema}
        selectedTable={primaryTable}
        onSelectTable={(tbl) => setPrimaryTable(tbl)}
        onAddToCanvas={(tbl) => {
          handleAddTableToCanvas(tbl);
          setIsSchemaExplorerOpen(false);
        }}
        onOpenErd={() => {
          setIsSchemaExplorerOpen(false);
          setIsErdOpen(true);
        }}
        onQuickQuery={(tbl) => {
          handleAddTableToCanvas(tbl);
          setIsSchemaExplorerOpen(false);
        }}
        theme={activeTheme}
        unstyled={unstyled}
      />

      {/* Query Template Manager Modal */}
      <QueryTemplateManager
        isOpen={isTemplateManagerOpen}
        onClose={() => setIsTemplateManagerOpen(false)}
        currentSql={currentSql}
        currentSpec={compiled.spec}
        onLoadTemplate={handleLoadTemplate}
        onSaveTemplate={handleSaveTemplate}
        defaultMode={templateManagerMode}
        unstyled={unstyled}
      />
    </div>
  );
};
