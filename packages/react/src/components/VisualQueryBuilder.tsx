import React, {
  useState,
  useMemo,
  useRef,
  useEffect,
  useImperativeHandle,
  useCallback,
} from "react";
import type {
  VisualQueryBuilderProps,
  VisualQueryBuilderRef,
  TableMeta,
  ColumnMeta,
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  QueryResultData,
  QueryTemplate,
  DatabaseSchemaDefinition,
  VectorSearchSpec,
  HybridSearchSpec,
  QuerySpec,
  SchemaSnapshot,
  QueryBuilderClassNames,
  FeatureKey,
  FeatureTier,
  FeatureConfig,
  FeaturePreset,
  ResolvedFeatureMap,
} from "../types";
import {
  resolveFeatureConfig,
  isFeatureVisible as checkFeatureVisible,
  detectActiveAdvancedClauses,
  ALL_FEATURE_KEYS,
} from "../utils/featureUtils";
import { QueryCanvas } from "./QueryCanvas";
import { QueryResultsTable } from "./QueryResultsTable";
import { SchemaErdModal } from "./SchemaErdModal";
import { SchemaExplorerModal } from "./SchemaExplorerModal";
import { QueryChartPreview } from "./QueryChartPreview";
import { QueryTemplateManager } from "./QueryTemplateManager";
import { QueryPlanVisualizer } from "./QueryPlanVisualizer";
import { NlqPromptBar } from "./NlqPromptBar";
import { LiveExecutionBar } from "./LiveExecutionBar";
import { PipelineDagCanvas } from "./PipelineDagCanvas";
import { WindowFunctionBuilder } from "./WindowFunctionBuilder";
import { AiAssistantWidget } from "./AiAssistantWidget";
import { useLiveExecution, type LiveExecutionResult } from "../hooks/useLiveExecution";
import { compileVisualState, estimateClientPlan } from "../utils/compiler";
import { validateSqlSafety } from "../utils/safety";
import { normalizeSchema, validateSchema } from "../utils/schemaUtils";
import { parseSqlToSpec } from "../utils/sqlParser";
import { useQueryState, specToState, createInitialState } from "../hooks/useQueryState";
import { findBestJoinCondition } from "../utils/joinUtils";
import { cx } from "../utils/classNames";
import { useTheme } from "../theme/ThemeProvider";
import { darkTheme, lightTheme, themeToCssVariables, type QueryBuilderTheme } from "../theme/tokens";
import { useQueryBuilderContext } from "../theme/QueryBuilderProvider";
import { attachSemanticModelsToTables } from "../adapters/semantic";
import type { QueryPlanNode, CteSpec, WindowFunctionSpec, SemanticModel } from "../types";

export type { VisualQueryBuilderRef };

export type ExtendedVisualQueryBuilderProps<Schema extends DatabaseSchemaDefinition = any> = Omit<
  VisualQueryBuilderProps<Schema>,
  "theme"
> & {
  theme?: "dark" | "light" | "auto" | QueryBuilderTheme;
  unstyled?: boolean;
  queryPlan?: QueryPlanNode;
  showPlanTab?: boolean;
  showNlqBar?: boolean;
  nlqApiUrl?: string;
  nlqDefaultProvider?: any;
  showLiveExecutionBar?: boolean;
  liveExecutionApiUrl?: string;
  liveExecutionConnectionId?: string;
  onLiveExecutionSuccess?: (results: LiveExecutionResult) => void;
  onLiveExecutionError?: (error: Error) => void;
  initialCtes?: CteSpec[];
  initialWindowFunctions?: WindowFunctionSpec[];
  showPipelineTab?: boolean;
  semanticModels?: SemanticModel[];
};

/**
 * Serializes a QuerySpec or object canonically, sorting all keys recursively
 * so equivalent specifications compare identically regardless of key ordering.
 */
export function fastCanonicalSpec(obj: any): string {
  if (obj === null || obj === undefined) return "";
  if (typeof obj !== "object") return JSON.stringify(obj);
  if (Array.isArray(obj)) {
    return "[" + obj.map(fastCanonicalSpec).join(",") + "]";
  }
  const keys = Object.keys(obj).sort().filter((k) => obj[k] !== undefined);
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + fastCanonicalSpec(obj[k])).join(",") + "}";
}

export const VisualQueryBuilder = React.forwardRef<
  VisualQueryBuilderRef,
  ExtendedVisualQueryBuilderProps
>(function VisualQueryBuilder(
  {
    schema: propSchema,
    presets = [],
    initialTable,
    dialect = "postgres",
    value,
    onChange,
    initialSpec,
    client,
    queryPlan,
    showPlanTab = false,
    showNlqBar = false,
    nlqApiUrl,
    nlqDefaultProvider,
    showLiveExecutionBar = false,
    liveExecutionApiUrl,
    liveExecutionConnectionId,
    onLiveExecutionSuccess,
    onLiveExecutionError,
    initialCtes = [],
    initialWindowFunctions = [],
    showPipelineTab = false,
    semanticModels,
    onExecuteQuery: propExecuteQuery,
    onSaveQuery,
    theme: propTheme,
    readOnly = false,
    unstyled: propUnstyled = false,
    mode: propMode,
    className,
    classNames,
    customOperators: propCustomOperators,
    fieldRenderers: propFieldRenderers,
    cellRenderers: propCellRenderers,
    ai,
    features: propFeatures,
    featurePreset: propFeaturePreset,
    allowToggleAdvanced = true,
    advancedMode: propAdvancedMode,
    defaultAdvancedMode = true,
    onAdvancedModeChange,
    storageKey = "qb_advanced_mode",
  },
  ref,
) {
  const { theme: contextTheme } = useTheme();
  const qbContext = useQueryBuilderContext();

  const effectiveMode = propMode ?? qbContext?.mode ?? (propUnstyled ? "unstyled" : "styled");
  const unstyled = propUnstyled || effectiveMode === "unstyled";

  const customOperators = propCustomOperators ?? qbContext?.customOperators;
  const fieldRenderers = propFieldRenderers ?? qbContext?.fieldRenderers;
  const cellRenderers = propCellRenderers ?? qbContext?.cellRenderers;

  // Auto-wire client query execution if client is provided and handler is not
  const effectiveOnExecuteQuery =
    propExecuteQuery ??
    qbContext?.onExecuteQuery ??
    (client
      ? async (sql: string, spec?: Record<string, unknown>) => {
          return client.execute(spec ? (spec as unknown as QuerySpec) : { sql });
        }
      : undefined);

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

  // Auto-wire schema from client if client is provided without schema
  const [clientSchema, setClientSchema] = useState<SchemaSnapshot | null>(null);

  useEffect(() => {
    if (!propSchema && client && !clientSchema) {
      client
        .getSchema()
        .then((s) => {
          if (s) setClientSchema(s);
        })
        .catch((err) => {
          console.warn("[Query-Builder] Failed to auto-fetch schema from client:", err);
        });
    }
  }, [propSchema, client, clientSchema]);

  // Auto-wire engine capabilities from client if client is provided
  const [serverCapabilities, setServerCapabilities] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    if (client && !serverCapabilities && typeof client.getCapabilities === "function") {
      client
        .getCapabilities()
        .then((caps) => {
          if (caps && Object.keys(caps).length > 0) {
            setServerCapabilities(caps);
          }
        })
        .catch((err) => {
          console.warn("[Query-Builder] Failed to auto-fetch capabilities from client:", err);
        });
    }
  }, [client, serverCapabilities]);

  const [featureOverrides, setFeatureOverrides] = useState<Record<string, FeatureTier>>({});
  const [isFeatureSettingsOpen, setIsFeatureSettingsOpen] = useState<boolean>(false);

  const resolvedFeatures: ResolvedFeatureMap = useMemo(() => {
    const base = resolveFeatureConfig(
      propFeatures ?? qbContext?.features,
      propFeaturePreset,
      serverCapabilities,
    );
    return { ...base, ...featureOverrides };
  }, [propFeatures, qbContext?.features, propFeaturePreset, serverCapabilities, featureOverrides]);

  const [internalAdvancedMode, setInternalAdvancedMode] = useState<boolean>(() => {
    if (propAdvancedMode !== undefined) return propAdvancedMode;
    if (storageKey && typeof window !== "undefined") {
      try {
        const stored = localStorage.getItem(storageKey);
        if (stored !== null) return stored === "true";
      } catch {}
    }
    return defaultAdvancedMode;
  });

  const isAdvancedMode =
    propAdvancedMode !== undefined ? propAdvancedMode : internalAdvancedMode;

  const handleToggleAdvanced = useCallback(
    (nextVal?: boolean) => {
      const val = nextVal !== undefined ? nextVal : !isAdvancedMode;
      setInternalAdvancedMode(val);
      if (storageKey && typeof window !== "undefined") {
        try {
          localStorage.setItem(storageKey, String(val));
        } catch {}
      }
      onAdvancedModeChange?.(val);
      qbContext?.setIsAdvancedMode?.(val);
    },
    [isAdvancedMode, storageKey, onAdvancedModeChange, qbContext],
  );

  const isFeatureVisible = useCallback(
    (feat: FeatureKey) => checkFeatureVisible(feat, resolvedFeatures, isAdvancedMode),
    [resolvedFeatures, isAdvancedMode],
  );

  const effectiveSchema = propSchema || clientSchema;
  const normalizedSchema = useMemo(() => normalizeSchema(effectiveSchema), [effectiveSchema]);

  // Schema Diagnostics: Non-blocking developer feedback
  useEffect(() => {
    if (normalizedSchema) {
      const result = validateSchema(normalizedSchema);
      if (!result.valid || result.warnings.length > 0) {
        if (
          typeof globalThis !== "undefined" &&
          (globalThis as any).process?.env?.NODE_ENV !== "production"
        ) {
          result.errors.forEach((e) => {
            console.warn(`[Query-Builder Schema Error] ${e.code}: ${e.message}`, e.suggestion);
          });
          result.warnings.forEach((w) => {
            console.warn(`[Query-Builder Schema Warning] ${w.code}: ${w.message}`, w.suggestion);
          });
        }
      }
    }
  }, [normalizedSchema]);

  // Unified Query State Management (50-step undo/redo & dual controlled/uncontrolled)
  const initialQuery = useMemo(() => {
    if (value) return value;
    if (initialSpec) return initialSpec;
    const base: Record<string, any> = {};
    const defaultT =
      initialTable || (propSchema?.tables ? Object.keys(propSchema.tables)[0] : undefined);
    if (defaultT) {
      base.table = defaultT;
      base.activeTables = [defaultT];
    }
    if (initialCtes.length > 0) base.ctes = initialCtes;
    if (initialWindowFunctions.length > 0) base.window_functions = initialWindowFunctions;
    return Object.keys(base).length > 0 ? base : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const queryState = useQueryState(initialQuery);
  const { state, actions, history } = queryState;

  const [activeStageName, setActiveStageName] = useState<string | null>(null);
  const [isWfBuilderOpen, setIsWfBuilderOpen] = useState<boolean>(false);

  const ctes = state.ctes || [];
  const windowFunctions = state.windowFunctions || [];
  const vectorSearch = state.vectorSearch || null;
  const hybridSearch = state.hybridSearch || null;
  const setCtes = actions.setCtes;
  const setWindowFunctions = actions.setWindowFunctions;
  const setVectorSearch = actions.setVectorSearch;
  const setHybridSearch = actions.setHybridSearch;

  const activeAdvancedClauses = useMemo(() => {
    if (isAdvancedMode) return [];
    return detectActiveAdvancedClauses(
      {
        ctes,
        windowFunctions,
        vectorSearch,
        hybridSearch,
        selectedColumns: state.selectedColumns,
      },
      resolvedFeatures,
    );
  }, [
    isAdvancedMode,
    ctes,
    windowFunctions,
    vectorSearch,
    hybridSearch,
    state.selectedColumns,
    resolvedFeatures,
  ]);

  const handleClearAdvancedClauses = useCallback(() => {
    if (ctes.length > 0) actions.setCtes([]);
    if (windowFunctions.length > 0) actions.setWindowFunctions([]);
    if (vectorSearch) actions.setVectorSearch(null);
    if (hybridSearch) actions.setHybridSearch(null);
    const cleanedCols = { ...state.selectedColumns };
    let hasCleaned = false;
    for (const [k, v] of Object.entries(cleanedCols)) {
      if (v && (v.rawExpression || (v as any).expression)) {
        delete cleanedCols[k];
        hasCleaned = true;
      }
    }
    if (hasCleaned) actions.setSelectedColumns(cleanedCols);
  }, [ctes, windowFunctions, vectorSearch, hybridSearch, state.selectedColumns, actions]);

  // Dynamic Schema Augmentation: expose upstream CTEs as virtual tables & attach semantic models
  const augmentedSchema = useMemo(() => {
    if (!normalizedSchema) return normalizedSchema;
    let copyTables = { ...normalizedSchema.tables };
    if (ctes.length > 0) {
      for (const cte of ctes) {
        if (activeStageName && cte.name === activeStageName) continue;
        const cols: ColumnMeta[] = [];
        if (cte.query?.columns) {
          cte.query.columns.forEach((col: any) => {
            if (typeof col === "string") {
              cols.push({ name: col, data_type: "text", is_nullable: true, is_primary: false });
            } else if (col && typeof col === "object") {
              cols.push({
                name: col.alias || col.column || "col",
                data_type: "text",
                is_nullable: true,
                is_primary: false,
              });
            }
          });
        }
        if (cte.query?.window_functions) {
          cte.query.window_functions.forEach((wf: any) => {
            if (wf.alias)
              cols.push({
                name: wf.alias,
                data_type: "numeric",
                is_nullable: true,
                is_primary: false,
              });
          });
        }
        if (cols.length === 0) {
          cols.push(
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "value", data_type: "text", is_nullable: true, is_primary: false },
          );
        }
        copyTables[cte.name] = {
          name: cte.name,
          columns: cols,
        };
      }
    }
    if (semanticModels && semanticModels.length > 0) {
      copyTables = attachSemanticModelsToTables(copyTables, semanticModels);
    }
    return { ...normalizedSchema, tables: copyTables };
  }, [normalizedSchema, ctes, activeStageName, semanticModels]);

  const allTables = useMemo(
    () => Object.values(augmentedSchema?.tables || {}),
    [augmentedSchema],
  );

  // Auto-select primary table on initial mount if schema was loaded asynchronously (e.g. via client)
  const hasAutoSelectedRef = useRef(false);
  useEffect(() => {
    if (
      !hasAutoSelectedRef.current &&
      !state.primaryTable &&
      state.activeTables.length === 0 &&
      allTables.length > 0 &&
      !value &&
      !initialSpec &&
      !initialTable
    ) {
      hasAutoSelectedRef.current = true;
      actions.setPrimaryTable(allTables[0].name);
    }
  }, [state.primaryTable, state.activeTables.length, allTables, value, initialSpec, initialTable, actions]);

  const primaryTable = state.primaryTable;
  const activeTableNames = state.activeTables;
  const selectedColumns = state.selectedColumns;
  const orderedProjectionKeys = state.orderedProjectionKeys;
  const joins = state.joins;
  const filters = state.filters;
  const sorts = state.sorts;
  const isDistinct = state.isDistinct;
  const limit = state.limit;

  const setLimit = actions.setLimit;
  const setIsDistinct = actions.setDistinct;
  const setSorts = actions.setSorts;
  const setFilters = actions.setFilters;
  const setJoins = actions.setJoins;
  const setPrimaryTable = actions.setPrimaryTable;
  const setActiveTableNames = actions.setTables;
  const setSelectedColumns = actions.setSelectedColumns;
  const setOrderedProjectionKeys = actions.setOrderedProjectionKeys;

  const [activeTab, setActiveTab] = useState<
    "visual" | "sql" | "results" | "chart" | "plan" | "pipeline"
  >("visual");

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
    plan: useRef<HTMLButtonElement | null>(null),
    pipeline: useRef<HTMLButtonElement | null>(null),
  };

  // Keyboard Shortcuts: Escape modal close & Cmd+Z / Cmd+Shift+Z / Cmd+Y Undo/Redo
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (isErdOpen) setIsErdOpen(false);
        if (isSchemaExplorerOpen) setIsSchemaExplorerOpen(false);
        if (isTemplateManagerOpen) setIsTemplateManagerOpen(false);
      }

      const isTargetInput =
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        Boolean((e.target as HTMLElement)?.isContentEditable);

      if (!isTargetInput) {
        const isModifier = e.metaKey || e.ctrlKey;
        if (isModifier && e.key.toLowerCase() === "z") {
          if (e.shiftKey) {
            e.preventDefault();
            if (history.canRedo) actions.redo();
          } else {
            e.preventDefault();
            if (history.canUndo) actions.undo();
          }
        } else if (isModifier && e.key.toLowerCase() === "y") {
          e.preventDefault();
          if (history.canRedo) actions.redo();
        }
      }
    };
    if (typeof window !== "undefined") {
      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }
  }, [
    isErdOpen,
    isSchemaExplorerOpen,
    isTemplateManagerOpen,
    history.canUndo,
    history.canRedo,
    actions,
  ]);

  // Active table metadata
  const activeTables: TableMeta[] = useMemo(() => {
    return activeTableNames
      .map((name) => augmentedSchema?.tables?.[name])
      .filter((t): t is TableMeta => Boolean(t));
  }, [activeTableNames, augmentedSchema]);

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
      augmentedSchema,
      dialect,
      "AND",
      customOperators,
      vectorSearch,
      hybridSearch,
      ctes,
      windowFunctions,
      semanticModels,
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
    augmentedSchema,
    dialect,
    customOperators,
    vectorSearch,
    hybridSearch,
    ctes,
    windowFunctions,
    semanticModels,
  ]);

  const currentSql = isRawMode ? rawSql : compiled.sql;
  const safety = useMemo(() => validateSqlSafety(currentSql), [currentSql]);

  const getActiveSpec = useCallback((): any => {
    const base = isRawMode
      ? (parseSqlToSpec(currentSql, normalizedSchema) as any) || compiled.spec
      : compiled.spec;
    if (!base) return base;
    const merged = { ...base };
    if (ctes.length > 0) merged.ctes = ctes;
    if (windowFunctions.length > 0) merged.window_functions = windowFunctions;
    if (vectorSearch) merged.vector_search = vectorSearch;
    if (hybridSearch) merged.hybrid_search = hybridSearch;
    return merged;
  }, [
    isRawMode,
    currentSql,
    normalizedSchema,
    compiled.spec,
    ctes,
    windowFunctions,
    vectorSearch,
    hybridSearch,
  ]);

  // Synchronize controlled `value` prop into useQueryState
  const initialCanonical = useMemo(
    () => (value ? fastCanonicalSpec(createInitialState(value)) : ""),
    [],
  );
  const lastControlledValueRef = useRef<string>(initialCanonical);
  const lastReportedSpecRef = useRef<string>(initialCanonical);
  const isFirstRenderRef = useRef<boolean>(true);

  useEffect(() => {
    if (value !== undefined) {
      const canonical = fastCanonicalSpec(createInitialState(value));
      if (canonical !== lastControlledValueRef.current) {
        lastControlledValueRef.current = canonical;
        lastReportedSpecRef.current = canonical;
        actions.loadSpec(value);
      }
    }
  }, [value, actions]);

  // Propagate state changes to `onChange` callback
  useEffect(() => {
    const currentActiveSpec = getActiveSpec();
    const canonicalActive = fastCanonicalSpec(createInitialState(currentActiveSpec));

    if (isFirstRenderRef.current) {
      isFirstRenderRef.current = false;
      lastReportedSpecRef.current = canonicalActive;
      lastControlledValueRef.current = canonicalActive;
      return;
    }

    if (canonicalActive !== lastReportedSpecRef.current) {
      lastReportedSpecRef.current = canonicalActive;
      lastControlledValueRef.current = canonicalActive;
      if (onChange) {
        onChange(currentActiveSpec, currentSql);
      }
    }
  }, [onChange, getActiveSpec, currentSql]);

  // Handle column selection toggle
  const handleToggleColumn = (tableName: string, colName: string) => {
    const key = `${tableName}.${colName}`;
    const nextSelected = { ...state.selectedColumns };
    let nextKeys = [...state.orderedProjectionKeys];
    if (nextSelected[key]) {
      delete nextSelected[key];
      nextKeys = nextKeys.filter((k) => k !== key);
    } else {
      const tblMeta = augmentedSchema?.tables?.[tableName];
      const isMetric = tblMeta?.metrics?.find((m: any) => m.name === colName);
      nextSelected[key] = {
        table: tableName,
        name: colName,
        metric: isMetric || undefined,
      };
      if (!nextKeys.includes(key)) {
        nextKeys.push(key);
      }
    }
    actions.setSelectedColumns(nextSelected, nextKeys);
  };

  // Add table to canvas
  const handleAddTableToCanvas = (tableName: string) => {
    if (!tableName) return;
    actions.addTable(tableName);
  };

  // Remove table from canvas
  const handleRemoveTable = (tableName: string) => {
    actions.removeTable(tableName);
  };

  // Synchronize Joins and active table names
  const handleJoinsChange = (newJoins: VisualJoin[]) => {
    actions.setJoins(newJoins);
    const set = new Set(state.activeTables);
    for (const j of newJoins) {
      if (j.table) set.add(j.table);
      if (j.left_table) set.add(j.left_table);
    }
    actions.setTables(Array.from(set));
  };

  const handleAddJoinToTable = (tableName: string) => {
    const allTableNames = normalizedSchema?.tables ? Object.keys(normalizedSchema.tables) : [];
    const candidate = allTableNames.find((t) => t !== tableName && !state.activeTables.includes(t));
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
      handleJoinsChange([...state.joins, newJoin]);
    }
  };

  // Raw SQL input change with bidirectional sync
  const handleRawSqlChange = (newSql: string) => {
    setIsRawMode(true);
    setRawSql(newSql);

    const parsed = parseSqlToSpec(newSql, normalizedSchema);
    if (parsed && parsed.table) {
      actions.loadSpec(parsed);
    }
  };

  const handleSyncWithVisualCanvas = () => {
    const parsed = parseSqlToSpec(rawSql, normalizedSchema);
    if (parsed && parsed.table) {
      actions.loadSpec(parsed);
    }
    setRawSql(compiled.sql);
    setIsRawMode(false);
  };

  const handleApplyNlqSpec = (appliedSpec: any) => {
    if (appliedSpec && appliedSpec.table) {
      actions.loadSpec(appliedSpec);
      setIsRawMode(false);
    }
  };

  const liveExec = useLiveExecution({
    apiUrl: liveExecutionApiUrl,
    connectionId: liveExecutionConnectionId,
    dialect,
    onSuccess: (res) => {
      setQueryResults({
        columns: res.columns,
        rows: res.rows,
        count: res.rowCount,
        durationMs: res.executionTimeMs,
      });
      setActiveTab("results");
      onLiveExecutionSuccess?.(res);
    },
    onError: onLiveExecutionError,
  });

  // Execute current query
  const handleRunQuery = async () => {
    if (!effectiveOnExecuteQuery) return;
    setIsRunning(true);
    setExecutionError(null);
    try {
      const parsedSpec = getActiveSpec();
      const result = await effectiveOnExecuteQuery(currentSql, parsedSpec);
      if (result) {
        setQueryResults(result);
        setActiveTab("results");
      }
      return result;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setExecutionError(msg);
    } finally {
      setIsRunning(false);
    }
  };

  // Expose imperative VisualQueryBuilderRef methods
  useImperativeHandle(
    ref,
    () => ({
      getSpec: () => getActiveSpec(),
      getSql: () => currentSql,
      setSpec: (newSpec: QuerySpec) => {
        actions.loadSpec(newSpec);
      },
      reset: () => {
        actions.reset();
      },
      execute: async () => {
        return handleRunQuery();
      },
      undo: () => {
        actions.undo();
      },
      redo: () => {
        actions.redo();
      },
      canUndo: () => history.canUndo,
      canRedo: () => history.canRedo,
    }),
    [getActiveSpec, currentSql, actions, history.canUndo, history.canRedo],
  );

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
      actions.loadSpec(template.spec);
      setIsRawMode(false);
    } else if (template.sql) {
      setRawSql(template.sql);
      setIsRawMode(true);
      setActiveTab("sql");
    }
    setIsTemplateManagerOpen(false);
  };

  const hasPlanTab = Boolean((queryPlan || showPlanTab) && isFeatureVisible("query_plan"));
  const hasPipelineTab = Boolean((showPipelineTab || ctes.length > 0) && isFeatureVisible("ctes"));
  const hasRawSqlTab = Boolean(isFeatureVisible("raw_sql"));
  const hasVisualChartTab = Boolean(isFeatureVisible("visual_chart"));

  useEffect(() => {
    if (activeTab === "sql" && !hasRawSqlTab) setActiveTab("visual");
    if (activeTab === "pipeline" && !hasPipelineTab) setActiveTab("visual");
    if (activeTab === "plan" && !hasPlanTab) setActiveTab("visual");
    if (activeTab === "chart" && !hasVisualChartTab) setActiveTab("visual");
  }, [activeTab, hasRawSqlTab, hasPipelineTab, hasPlanTab, hasVisualChartTab]);

  const handleTabKeyDown = (
    e: React.KeyboardEvent<HTMLButtonElement>,
    tab: "visual" | "sql" | "results" | "chart" | "plan" | "pipeline",
  ) => {
    const tabs: ("visual" | "sql" | "results" | "chart" | "plan" | "pipeline")[] = ["visual"];
    if (hasRawSqlTab) tabs.push("sql");
    tabs.push("results");
    if (hasVisualChartTab) tabs.push("chart");
    if (hasPipelineTab) tabs.push("pipeline");
    if (hasPlanTab) tabs.push("plan");
    const currentIndex = tabs.indexOf(tab);
    if (currentIndex === -1) return;
    let targetTab: "visual" | "sql" | "results" | "chart" | "plan" | "pipeline" | null = null;

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
      className={cx(className, classNames?.root)}
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
        className={cx(classNames?.header)}
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
            className={cx(classNames?.tabs)}
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
              className={cx(classNames?.tab, activeTab === "visual" && classNames?.tabActive)}
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
            {hasRawSqlTab && (
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
                className={cx(classNames?.tab, activeTab === "sql" && classNames?.tabActive)}
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
            )}
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
              className={cx(classNames?.tab, activeTab === "results" && classNames?.tabActive)}
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
            {hasVisualChartTab && (
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
                className={cx(classNames?.tab, activeTab === "chart" && classNames?.tabActive)}
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
            )}
            {hasPipelineTab && (
              <button
                ref={tabRefs.pipeline}
                role="tab"
                id="tab-pipeline"
                aria-controls="panel-pipeline"
                aria-selected={activeTab === "pipeline"}
                tabIndex={activeTab === "pipeline" ? 0 : -1}
                onKeyDown={(e) => handleTabKeyDown(e, "pipeline")}
                type="button"
                onClick={() => setActiveTab("pipeline")}
                data-qb="tab"
                data-qb-tab="pipeline"
                className={cx(classNames?.tab, activeTab === "pipeline" && classNames?.tabActive)}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: activeTab === "pipeline" ? activeTheme.colors.primary : "transparent",
                        color: activeTab === "pipeline" ? "#fff" : activeTheme.colors.textMuted,
                        border: "none",
                        borderRadius: activeTheme.radii.sm,
                        padding: "6px 12px",
                        fontSize: activeTheme.typography.fontSizeSm,
                        fontWeight: activeTheme.typography.fontWeightSemibold,
                        cursor: "pointer",
                      }
                }
              >
                🔀 Pipeline {ctes.length > 0 ? `(${ctes.length})` : ""}
              </button>
            )}
            {hasPlanTab && (
              <button
                ref={tabRefs.plan}
                role="tab"
                id="tab-plan"
                aria-controls="panel-plan"
                aria-selected={activeTab === "plan"}
                tabIndex={activeTab === "plan" ? 0 : -1}
                onKeyDown={(e) => handleTabKeyDown(e, "plan")}
                type="button"
                onClick={() => setActiveTab("plan")}
                data-qb="tab"
                data-qb-tab="plan"
                className={cx(classNames?.tab, activeTab === "plan" && classNames?.tabActive)}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: activeTab === "plan" ? activeTheme.colors.primary : "transparent",
                        color: activeTab === "plan" ? "#fff" : activeTheme.colors.textMuted,
                        border: "none",
                        borderRadius: activeTheme.radii.sm,
                        padding: "6px 12px",
                        fontSize: activeTheme.typography.fontSizeSm,
                        fontWeight: activeTheme.typography.fontWeightSemibold,
                        cursor: "pointer",
                      }
                }
              >
                ⚡ Query Plan
              </button>
            )}
          </div>

          {/* Window Functions Button */}
          {isFeatureVisible("window_functions") && (
            <button
              type="button"
              onClick={() => setIsWfBuilderOpen(true)}
              aria-label="Open window functions builder"
              data-qb="btn-window-functions"
              data-testid="btn-open-wf-builder"
              style={
                unstyled
                  ? undefined
                  : {
                      background: "rgba(30, 41, 59, 0.5)",
                      color: "#a855f7",
                      border: "1px solid rgba(168, 85, 247, 0.3)",
                      borderRadius: activeTheme.radii.sm,
                      padding: "6px 12px",
                      fontSize: activeTheme.typography.fontSizeSm,
                      fontWeight: activeTheme.typography.fontWeightSemibold,
                      cursor: "pointer",
                    }
              }
            >
              🪟 Window Functions {windowFunctions.length > 0 ? `(${windowFunctions.length})` : ""}
            </button>
          )}

          {/* Schema Explorer Button */}
          {isFeatureVisible("schema_tools") && (
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
          )}

          {/* ERD Button */}
          {isFeatureVisible("schema_tools") && (
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
          )}
        </div>

        {/* Action Controls */}
        <div
          data-qb="actions-bar"
          style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "10px" }}
        >
          {/* Undo / Redo Controls */}
          <button
            type="button"
            onClick={() => actions.undo()}
            disabled={!history.canUndo}
            aria-label="Undo query changes (Cmd+Z)"
            title="Undo (Cmd+Z)"
            data-qb="btn-undo"
            style={
              unstyled
                ? undefined
                : {
                    background: history.canUndo ? activeTheme.colors.surface : "rgba(30, 41, 59, 0.2)",
                    color: history.canUndo ? activeTheme.colors.text : activeTheme.colors.textMuted,
                    border: `1px solid ${history.canUndo ? activeTheme.colors.border : "transparent"}`,
                    borderRadius: activeTheme.radii.sm,
                    padding: "6px 10px",
                    fontSize: activeTheme.typography.fontSizeSm,
                    cursor: history.canUndo ? "pointer" : "not-allowed",
                    opacity: history.canUndo ? 1 : 0.4,
                  }
            }
          >
            ↶ Undo
          </button>
          <button
            type="button"
            onClick={() => actions.redo()}
            disabled={!history.canRedo}
            aria-label="Redo query changes (Cmd+Shift+Z)"
            title="Redo (Cmd+Shift+Z)"
            data-qb="btn-redo"
            style={
              unstyled
                ? undefined
                : {
                    background: history.canRedo ? activeTheme.colors.surface : "rgba(30, 41, 59, 0.2)",
                    color: history.canRedo ? activeTheme.colors.text : activeTheme.colors.textMuted,
                    border: `1px solid ${history.canRedo ? activeTheme.colors.border : "transparent"}`,
                    borderRadius: activeTheme.radii.sm,
                    padding: "6px 10px",
                    fontSize: activeTheme.typography.fontSizeSm,
                    cursor: history.canRedo ? "pointer" : "not-allowed",
                    opacity: history.canRedo ? 1 : 0.4,
                  }
            }
          >
            ↷ Redo
          </button>

          {/* Advanced Mode Toggle Switch */}
          {allowToggleAdvanced && (
            <div
              data-qb="advanced-mode-control"
              style={
                unstyled
                  ? undefined
                  : { display: "flex", alignItems: "center", gap: "4px", position: "relative" }
              }
            >
              <button
                type="button"
                onClick={() => handleToggleAdvanced()}
                aria-pressed={isAdvancedMode}
                data-testid="btn-toggle-advanced"
                data-qb="btn-toggle-advanced"
                title={isAdvancedMode ? "Switch to Simple Mode" : "Switch to Advanced Mode"}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: isAdvancedMode
                          ? "rgba(168, 85, 247, 0.2)"
                          : activeTheme.colors.surface,
                        color: isAdvancedMode ? "#c084fc" : activeTheme.colors.textMuted,
                        border: `1px solid ${isAdvancedMode ? "#a855f7" : activeTheme.colors.border}`,
                        borderRadius: activeTheme.radii.sm,
                        padding: "6px 10px",
                        fontSize: activeTheme.typography.fontSizeSm,
                        fontWeight: activeTheme.typography.fontWeightSemibold,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                      }
                }
              >
                <span>⚡ Advanced</span>
                <span
                  style={
                    unstyled
                      ? undefined
                      : {
                          display: "inline-block",
                          width: "8px",
                          height: "8px",
                          borderRadius: "50%",
                          background: isAdvancedMode ? "#22c55e" : "#64748b",
                        }
                  }
                />
              </button>

              {/* Granular Feature Settings Gear */}
              <button
                type="button"
                onClick={() => setIsFeatureSettingsOpen((prev) => !prev)}
                aria-label="Configure advanced features"
                title="Configure advanced features"
                data-testid="btn-feature-settings"
                style={
                  unstyled
                    ? undefined
                    : {
                        background: isFeatureSettingsOpen
                          ? activeTheme.colors.surfaceHover
                          : "transparent",
                        color: activeTheme.colors.textMuted,
                        border: `1px solid ${isFeatureSettingsOpen ? activeTheme.colors.border : "transparent"}`,
                        borderRadius: activeTheme.radii.sm,
                        padding: "6px 8px",
                        fontSize: activeTheme.typography.fontSizeSm,
                        cursor: "pointer",
                      }
                }
              >
                ⚙️
              </button>

              {/* Settings Dropdown Popover */}
              {isFeatureSettingsOpen && (
                <div
                  data-testid="feature-settings-popover"
                  style={
                    unstyled
                      ? undefined
                      : {
                          position: "absolute",
                          top: "100%",
                          right: 0,
                          marginTop: "6px",
                          width: "260px",
                          background: activeTheme.colors.surface,
                          border: `1px solid ${activeTheme.colors.border}`,
                          borderRadius: activeTheme.radii.md,
                          boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.5)",
                          padding: "12px",
                          zIndex: 1000,
                          fontSize: activeTheme.typography.fontSizeXs,
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
                            marginBottom: "8px",
                            paddingBottom: "6px",
                            borderBottom: `1px solid ${activeTheme.colors.border}`,
                            fontWeight: activeTheme.typography.fontWeightBold,
                          }
                    }
                  >
                    <span>Feature Tiers</span>
                    <button
                      type="button"
                      onClick={() => setIsFeatureSettingsOpen(false)}
                      style={
                        unstyled
                          ? undefined
                          : {
                              background: "none",
                              border: "none",
                              color: activeTheme.colors.textMuted,
                              cursor: "pointer",
                            }
                      }
                    >
                      ✕
                    </button>
                  </div>
                  <div
                    style={
                      unstyled
                        ? undefined
                        : {
                            maxHeight: "220px",
                            overflowY: "auto",
                            display: "flex",
                            flexDirection: "column",
                            gap: "6px",
                          }
                    }
                  >
                    {ALL_FEATURE_KEYS.map((key) => {
                      const currentTier = featureOverrides[key] ?? resolvedFeatures[key];
                      return (
                        <div
                          key={key}
                          style={
                            unstyled
                              ? undefined
                              : {
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "space-between",
                                  gap: "8px",
                                }
                          }
                        >
                          <span
                            style={
                              unstyled
                                ? undefined
                                : { textTransform: "capitalize", color: activeTheme.colors.text }
                            }
                          >
                            {key.replace("_", " ")}
                          </span>
                          <select
                            value={currentTier}
                            onChange={(e) => {
                              const newTier = e.target.value as FeatureTier;
                              setFeatureOverrides((prev) => ({ ...prev, [key]: newTier }));
                            }}
                            data-testid={`feature-select-${key}`}
                            style={
                              unstyled
                                ? undefined
                                : {
                                    background: activeTheme.colors.background,
                                    color: activeTheme.colors.text,
                                    border: `1px solid ${activeTheme.colors.border}`,
                                    borderRadius: activeTheme.radii.xs,
                                    padding: "2px 6px",
                                    fontSize: activeTheme.typography.fontSizeXs,
                                  }
                            }
                          >
                            <option value="standard">Standard</option>
                            <option value="advanced">Advanced</option>
                            <option value="disabled">Disabled</option>
                          </select>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

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

      {/* Non-destructive Advanced Clauses Alert Banner */}
      {!isAdvancedMode && activeAdvancedClauses.length > 0 && (
        <div
          data-testid="active-advanced-clauses-banner"
          data-qb="advanced-clauses-banner"
          style={
            unstyled
              ? undefined
              : {
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "8px 14px",
                  borderRadius: activeTheme.radii.sm,
                  background: "rgba(234, 179, 8, 0.12)",
                  border: "1px solid rgba(234, 179, 8, 0.35)",
                  color: "#eab308",
                  fontSize: activeTheme.typography.fontSizeSm,
                }
          }
        >
          <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px" }}>
            <span>⚠️</span>
            <span>
              <strong>{activeAdvancedClauses.length} hidden advanced clause(s) active</strong> (
              {activeAdvancedClauses.map((c) => c.label).join(", ")}). These clauses continue compiling.
            </span>
          </div>
          <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px" }}>
            <button
              type="button"
              onClick={() => handleToggleAdvanced(true)}
              data-testid="btn-view-advanced-clauses"
              style={
                unstyled
                  ? undefined
                  : {
                      background: "#eab308",
                      color: "#000",
                      border: "none",
                      borderRadius: activeTheme.radii.xs,
                      padding: "3px 8px",
                      fontSize: activeTheme.typography.fontSizeXs,
                      fontWeight: activeTheme.typography.fontWeightBold,
                      cursor: "pointer",
                    }
              }
            >
              View in Advanced Mode
            </button>
            <button
              type="button"
              onClick={handleClearAdvancedClauses}
              data-testid="btn-clear-advanced-clauses"
              style={
                unstyled
                  ? undefined
                  : {
                      background: "transparent",
                      color: activeTheme.colors.textMuted,
                      border: `1px solid ${activeTheme.colors.border}`,
                      borderRadius: activeTheme.radii.xs,
                      padding: "3px 8px",
                      fontSize: activeTheme.typography.fontSizeXs,
                      cursor: "pointer",
                    }
              }
            >
              Clear Clauses
            </button>
          </div>
        </div>
      )}

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

      {showLiveExecutionBar && (
        <LiveExecutionBar
          connectionId={liveExecutionConnectionId}
          connectionStatus={liveExec.connectionStatus}
          connectionLatencyMs={liveExec.connectionLatencyMs}
          isExecuting={liveExec.isExecuting}
          executionTimeMs={liveExec.executionTimeMs}
          rowCount={liveExec.results?.rowCount ?? null}
          error={liveExec.error}
          onDismissError={liveExec.clearResults}
          onTestConnection={() => void liveExec.testConnection()}
          onExecute={() => {
            void liveExec.executeQuery(getActiveSpec());
          }}
          onCancel={() => void liveExec.cancelExecution()}
          unstyled={unstyled}
        />
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
          {showNlqBar && (
            <NlqPromptBar
              schema={normalizedSchema}
              currentSpec={compiled.spec}
              onApplySpec={handleApplyNlqSpec}
              apiUrl={nlqApiUrl}
              defaultProvider={nlqDefaultProvider}
              dialect={dialect}
              unstyled={unstyled}
            />
          )}
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
            onUpdateColumnSelect={actions.updateColumnSelect}
            onRemoveColumnProjection={actions.removeColumnProjection}
            onJoinsChange={handleJoinsChange}
            onAddJoin={handleAddJoinToTable}
            onReorderProjections={setOrderedProjectionKeys}
            onFiltersChange={setFilters}
            onSortsChange={setSorts}
            onDistinctChange={setIsDistinct}
            onLimitChange={setLimit}
            vectorSearch={vectorSearch}
            hybridSearch={hybridSearch}
            onVectorChange={setVectorSearch}
            onHybridChange={setHybridSearch}
            unstyled={unstyled}
            classNames={classNames}
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
          className={cx(classNames?.sqlEditor)}
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
              className={cx(classNames?.title)}
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
              {isRawMode && (
                <span
                  data-qb="sql-sync-badge"
                  className={cx(classNames?.sqlSyncBadge)}
                  style={
                    unstyled
                      ? undefined
                      : {
                          fontSize: "0.75rem",
                          color: parseSqlToSpec(rawSql, normalizedSchema) ? "#34d399" : "#f87171",
                          background: parseSqlToSpec(rawSql, normalizedSchema)
                            ? "rgba(16, 185, 129, 0.15)"
                            : "rgba(239, 68, 68, 0.15)",
                          border: `1px solid ${
                            parseSqlToSpec(rawSql, normalizedSchema)
                              ? "rgba(16, 185, 129, 0.3)"
                              : "rgba(239, 68, 68, 0.3)"
                          }`,
                          padding: "2px 8px",
                          borderRadius: "4px",
                          fontWeight: 600,
                        }
                  }
                >
                  {parseSqlToSpec(rawSql, normalizedSchema)
                    ? "⚡ Synced with Visual Canvas (Continuous Sync)"
                    : "Custom Raw SQL (Visual Canvas Unsynced)"}
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
            className={cx(classNames?.sqlTextarea)}
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
          <QueryResultsTable
            results={queryResults}
            isLoading={isRunning}
            unstyled={unstyled}
            cellRenderers={cellRenderers}
            classNames={classNames}
          />
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

      {hasPlanTab && activeTab === "plan" && (
        <div
          role="tabpanel"
          id="panel-plan"
          aria-labelledby="tab-plan"
          tabIndex={0}
          data-qb="tab-panel"
          data-qb-panel="plan"
        >
          <QueryPlanVisualizer
            plan={queryPlan || estimateClientPlan(compiled.spec)}
            unstyled={unstyled}
          />
        </div>
      )}

      {hasPipelineTab && activeTab === "pipeline" && (
        <div
          role="tabpanel"
          id="panel-pipeline"
          aria-labelledby="tab-pipeline"
          tabIndex={0}
          data-qb="tab-panel"
          data-qb-panel="pipeline"
        >
          <PipelineDagCanvas
            ctes={ctes}
            onCtesChange={setCtes}
            onSelectStage={(stage) => {
              setActiveStageName(stage);
              if (stage) {
                setPrimaryTable(stage);
                if (!activeTableNames.includes(stage)) {
                  actions.addTable(stage);
                }
              }
              setActiveTab("visual");
            }}
            selectedStage={activeStageName}
            unstyled={unstyled}
          />
        </div>
      )}

      {/* Window Function Builder Modal */}
      <WindowFunctionBuilder
        isOpen={isWfBuilderOpen}
        onClose={() => setIsWfBuilderOpen(false)}
        onSave={(wf) => setWindowFunctions([...windowFunctions, wf])}
        availableColumns={Object.values(augmentedSchema?.tables || {}).flatMap((t) =>
          (t.columns || []).map((c) => ({
            table: t.name,
            name: typeof c === "string" ? c : c.name,
          }))
        )}
        unstyled={unstyled}
      />

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

      {/* Bring Your Own AI (BYO-AI) Assistant Widget */}
      {ai && (
        <AiAssistantWidget
          {...ai}
          schema={normalizedSchema}
          currentSpec={compiled.spec}
          dialect={dialect}
          onApplySpec={handleApplyNlqSpec}
          unstyled={unstyled}
        />
      )}
    </div>
  );
}) as <Schema extends DatabaseSchemaDefinition = any>(
  props: ExtendedVisualQueryBuilderProps<Schema> & { ref?: React.Ref<VisualQueryBuilderRef> },
) => React.ReactElement | null;
