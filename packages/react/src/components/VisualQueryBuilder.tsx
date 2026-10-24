import React, {
  useState,
  useMemo,
  useRef,
  useEffect,
  useImperativeHandle,
  useCallback,
} from "react";
import type {
  VisualQueryBuilderRef,
  TableMeta,
  QueryTemplate,
  DatabaseSchemaDefinition,
  QuerySpec,
  FeatureKey,
  FeatureTier,
  ResolvedFeatureMap,
} from "../types";
import {
  resolveFeatureConfig,
  isFeatureVisible as checkFeatureVisible,
} from "../utils/featureUtils";
import type { ExtendedVisualQueryBuilderProps } from "./visual-query-builder/props";
import { useAdvancedClauses } from "./visual-query-builder/useAdvancedClauses";
import { useCompiledQuery } from "./visual-query-builder/useCompiledQuery";
import { SchemaErdModal } from "./SchemaErdModal";
import { SchemaExplorerModal } from "./SchemaExplorerModal";
import { QueryTemplateManager } from "./QueryTemplateManager";
import { LiveExecutionBar } from "./LiveExecutionBar";
import { WindowFunctionBuilder } from "./WindowFunctionBuilder";
import { AiAssistantWidget } from "./AiAssistantWidget";
import { estimateClientPlan } from "../utils/compiler";
import { validateSqlSafety } from "../utils/safety";
import { parseSqlToSpec } from "../utils/sqlParser";
import { useQueryState } from "../hooks/useQueryState";
import { cx } from "../utils/classNames";
import {
   QueryBuilderContext,
  useQueryBuilderContext,
  type QueryBuilderContextValue,
} from "../theme/QueryBuilderProvider";
import { fastCanonicalSpec } from "../utils/canonicalSpec";
import { useBuilderTheme, rootStyle } from "./visual-query-builder/useBuilderTheme";
import { useClientBootstrap } from "./visual-query-builder/useClientBootstrap";
import { useAdvancedMode } from "./visual-query-builder/useAdvancedMode";
import {
  useNormalizedSchema,
  useAugmentedSchema,
} from "./visual-query-builder/useAugmentedSchema";
import { useRawSqlMode } from "./visual-query-builder/useRawSqlMode";
import { useCanvasHandlers } from "./visual-query-builder/useCanvasHandlers";
import { useTabState, visibleTabs } from "./visual-query-builder/useTabState";
import { useQueryRunner } from "./visual-query-builder/useQueryRunner";
import { useControlledSpecSync } from "./visual-query-builder/useControlledSpecSync";
import { useKeyboardShortcuts } from "./visual-query-builder/useKeyboardShortcuts";
import { TabBar } from "./visual-query-builder/TabBar";
import { ToolButtons } from "./visual-query-builder/ToolButtons";
import { ToolbarActions } from "./visual-query-builder/ToolbarActions";
import {
  AdvancedClausesBanner,
  ExecutionErrorBanner,
  SafetyBadge,
} from "./visual-query-builder/StatusBanners";
import { VisualPanel } from "./visual-query-builder/VisualPanel";
import { SqlPanel } from "./visual-query-builder/SqlPanel";
import {
  ChartPanel,
  PipelinePanel,
  PlanPanel,
  ResultsPanel,
} from "./visual-query-builder/TabPanels";

export type { VisualQueryBuilderRef, ExtendedVisualQueryBuilderProps };
export { fastCanonicalSpec };

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
    hideNlqBar = false,
    compactHeader = false,
    hideInnerToolbar = false,
    hideSummaryBar = false,
    studioMode = false,
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
  const qbContext = useQueryBuilderContext();

  const effectiveMode = propMode ?? qbContext?.mode ?? (propUnstyled ? "unstyled" : "styled");
  const unstyled = propUnstyled || effectiveMode === "unstyled";

  const customOperators = propCustomOperators ?? qbContext?.customOperators;
  const fieldRenderers = propFieldRenderers ?? qbContext?.fieldRenderers;
  const cellRenderers = propCellRenderers ?? qbContext?.cellRenderers;

  const { activeTheme, cssVars } = useBuilderTheme(propTheme, unstyled);
  const { clientSchema, serverCapabilities } = useClientBootstrap(client, propSchema);

  const [featureOverrides, setFeatureOverrides] = useState<Record<string, FeatureTier>>({});

  const resolvedFeatures: ResolvedFeatureMap = useMemo(() => {
    const base = resolveFeatureConfig(
      propFeatures ?? qbContext?.features,
      propFeaturePreset,
      serverCapabilities,
    );
    return { ...base, ...featureOverrides };
  }, [propFeatures, qbContext?.features, propFeaturePreset, serverCapabilities, featureOverrides]);

  const { isAdvancedMode, toggleAdvanced } = useAdvancedMode({
    advancedMode: propAdvancedMode,
    defaultAdvancedMode,
    storageKey,
    onAdvancedModeChange,
    onContextChange: qbContext?.setIsAdvancedMode,
  });

  const isFeatureVisible = useCallback(
    (feat: FeatureKey) => checkFeatureVisible(feat, resolvedFeatures, isAdvancedMode),
    [resolvedFeatures, isAdvancedMode],
  );

  const contextValue = useMemo<QueryBuilderContextValue>(
    () => ({
      mode: effectiveMode,
      customOperators,
      fieldRenderers,
      cellRenderers,
      onExecuteQuery: propExecuteQuery ?? qbContext?.onExecuteQuery,
      isAdvancedMode,
      setIsAdvancedMode: (val: boolean) => toggleAdvanced(val),
      features: resolvedFeatures,
      isFeatureVisible,
      readOnly,
      dialect,
    }),
    [
      effectiveMode,
      customOperators,
      fieldRenderers,
      cellRenderers,
      propExecuteQuery,
      qbContext?.onExecuteQuery,
      isAdvancedMode,
      toggleAdvanced,
      resolvedFeatures,
      isFeatureVisible,
      readOnly,
      dialect,
    ],
  );

  const effectiveSchema = propSchema || clientSchema;
  const normalizedSchema = useNormalizedSchema(effectiveSchema);

  // Unified Query State Management (50-step undo/redo & dual controlled/uncontrolled).
  // Only the first render's inputs seed the state; later changes flow through `value`.
  const [initialQuery] = useState(() => {
    if (value) return value;
    if (initialSpec) return initialSpec;
    const base: Record<string, unknown> = {};
    const defaultT =
      initialTable ||
      (propSchema && !Array.isArray(propSchema) && propSchema.tables
        ? Object.keys(propSchema.tables)[0]
        : undefined);
    if (defaultT) {
      base.table = defaultT;
      base.activeTables = [defaultT];
    }
    if (initialCtes.length > 0) base.ctes = initialCtes;
    if (initialWindowFunctions.length > 0) base.window_functions = initialWindowFunctions;
    return Object.keys(base).length > 0 ? base : undefined;
  });

  const { state, actions, history } = useQueryState(initialQuery);

  const [activeStageName, setActiveStageName] = useState<string | null>(null);
  const [isWfBuilderOpen, setIsWfBuilderOpen] = useState<boolean>(false);

  const { ctes, windowFunctions } = state;
  const vectorSearch = state.vectorSearch || null;
  const hybridSearch = state.hybridSearch || null;

  const { activeAdvancedClauses, clearAdvancedClauses } = useAdvancedClauses(
    state,
    actions,
    isAdvancedMode,
    resolvedFeatures,
  );

  const augmentedSchema = useAugmentedSchema(normalizedSchema, ctes, activeStageName, semanticModels);

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

  const { primaryTable, activeTables: activeTableNames } = state;

  const activeTables: TableMeta[] = useMemo(() => {
    return activeTableNames
      .map((name) => augmentedSchema?.tables?.[name])
      .filter((t): t is TableMeta => Boolean(t));
  }, [activeTableNames, augmentedSchema]);

  const compiled = useCompiledQuery(state, augmentedSchema, dialect, customOperators, semanticModels);

  const raw = useRawSqlMode({
    compiled,
    dialect,
    compileSchema: augmentedSchema,
    parseSchema: augmentedSchema || normalizedSchema,
    loadSpec: actions.loadSpec,
  });
  const { currentSql, getActiveSpec, leaveRawMode } = raw;
  const safety = useMemo(() => validateSqlSafety(currentSql), [currentSql]);

  const canvasHandlers = useCanvasHandlers({
    state,
    actions,
    leaveRawMode,
    augmentedSchema,
    normalizedSchema,
  });

  const hasPlanTab = Boolean((queryPlan || showPlanTab) && isFeatureVisible("query_plan"));
  const hasPipelineTab = Boolean((showPipelineTab || ctes.length > 0) && isFeatureVisible("ctes"));
  const hasRawSqlTab = Boolean(isFeatureVisible("raw_sql"));
  const hasVisualChartTab = Boolean(isFeatureVisible("visual_chart"));
  const [activeTab, setActiveTab] = useTabState({
    hasPlanTab,
    hasPipelineTab,
    hasRawSqlTab,
    hasVisualChartTab,
  });

  const [isErdOpen, setIsErdOpen] = useState<boolean>(false);
  const [isSchemaExplorerOpen, setIsSchemaExplorerOpen] = useState<boolean>(false);
  const [isTemplateManagerOpen, setIsTemplateManagerOpen] = useState<boolean>(false);
  const [templateManagerMode, setTemplateManagerMode] = useState<"library" | "save">("library");

  const {
    queryResults,
    isRunning,
    executionError,
    liveExec,
    handleRunQuery,
    isDockOpen,
    setIsDockOpen,
    dockTab,
    setDockTab,
  } = useQueryRunner({
    propExecuteQuery,
    contextExecuteQuery: qbContext?.onExecuteQuery,
    client,
    getActiveSpec,
    currentSql,
    activeTab,
    setActiveTab,
    dialect,
    schema: augmentedSchema,
    liveExecutionApiUrl,
    liveExecutionConnectionId,
    onLiveExecutionSuccess,
    onLiveExecutionError,
  });

  const modals = useMemo(
    () => [
      { isOpen: isErdOpen, close: () => setIsErdOpen(false) },
      { isOpen: isSchemaExplorerOpen, close: () => setIsSchemaExplorerOpen(false) },
      { isOpen: isTemplateManagerOpen, close: () => setIsTemplateManagerOpen(false) },
    ],
    [isErdOpen, isSchemaExplorerOpen, isTemplateManagerOpen],
  );
  useKeyboardShortcuts({
    modals,
    canUndo: history.canUndo,
    canRedo: history.canRedo,
    undo: () => {
      leaveRawMode();
      actions.undo();
    },
    redo: () => {
      leaveRawMode();
      actions.redo();
    },
  });

  useControlledSpecSync({ value, onChange, loadSpec: actions.loadSpec, getActiveSpec, currentSql });

  const handleApplyNlqSpec = (appliedSpec: QuerySpec) => {
    if (appliedSpec && appliedSpec.table) {
      let cleanedColumns = Array.isArray(appliedSpec.columns)
        ? appliedSpec.columns.filter((col) => {
            if (typeof col === "string") {
              const trimmed = col.trim();
              return trimmed !== "*" && !trimmed.endsWith(".*");
            }
            if (col && typeof col === "object" && "column" in col) {
              const cName = String(col.column || "").trim();
              const hasAgg = Boolean(col.agg || (col as Record<string, unknown>).aggregate);
              if (!hasAgg && (cName === "*" || cName.endsWith(".*"))) {
                return false;
              }
            }
            return true;
          })
        : [];
      const baseMeta = augmentedSchema?.tables?.[appliedSpec.table];
      if (
        baseMeta &&
        baseMeta.columns.length > 4 &&
        cleanedColumns.length >= baseMeta.columns.length &&
        cleanedColumns.every(
          (c) =>
            typeof c === "string" ||
            (c &&
              typeof c === "object" &&
              !c.agg &&
              !(c as Record<string, unknown>).aggregate &&
              !c.alias &&
              !c.expression &&
              !(c as Record<string, unknown>).dimension &&
              !c.metric),
        )
      ) {
        cleanedColumns = [];
      }
      const cleanedFilters = Array.isArray(appliedSpec.filters)
        ? appliedSpec.filters.map((f) => {
            if (f && typeof f.column === "string" && !f.tablePrefix && f.column.includes(".")) {
              const lastDot = f.column.lastIndexOf(".");
              return {
                ...f,
                tablePrefix: f.column.substring(0, lastDot),
                column: f.column.substring(lastDot + 1),
              };
            }
            return f;
          })
        : appliedSpec.filters;
      const nextSpec: QuerySpec = {
        ...appliedSpec,
        columns: cleanedColumns,
        ...(cleanedFilters ? { filters: cleanedFilters } : {}),
      };
      actions.loadSpec(nextSpec);
      leaveRawMode();
      void handleRunQuery(nextSpec);
    }
  };

  const nlqSuggestions = useMemo<string[] | undefined>(() => {
    const namedTables = allTables.filter((t) => Boolean(t && typeof t.name === "string"));
    if (!namedTables.length) return undefined;
    const hasDemoTables = namedTables.some((t) =>
      ["customers", "orders", "users"].includes(t.name.toLowerCase()),
    );
    if (hasDemoTables) return undefined;
    const userTables = namedTables.filter(
      (t) => !t.name.startsWith("django_") && !t.name.startsWith("auth_permission"),
    );
    const primary =
      userTables.find((t) => t.name === primaryTable) || userTables[0] || namedTables[0];
    const secondary =
      userTables.find((t) => t.name !== primary.name) || primary;
    const cols = primary.columns || [];
    const sortCol =
      cols.find((c) => /aum|amount|total|score|count|date|created|id/i.test(c?.name || ""))?.name ||
      cols[0]?.name ||
      "id";
    const groupCol =
      cols.find((c) => /status|type|state|category|tier|role/i.test(c?.name || ""))?.name ||
      cols[1]?.name ||
      cols[0]?.name ||
      "id";
    return [
      `Top 10 ${primary.name} sorted by ${sortCol} descending`,
      `Count ${primary.name} grouped by ${groupCol}`,
      `Show ${secondary.name} limit 25`,
    ];
  }, [allTables, primaryTable]);

  // Expose imperative VisualQueryBuilderRef methods
  useImperativeHandle(
    ref,
    () => ({
      getSpec: () => getActiveSpec(),
      getSql: () => currentSql,
      setSpec: (newSpec: QuerySpec) => {
        leaveRawMode();
        actions.loadSpec(newSpec);
      },
      reset: () => {
        leaveRawMode();
        actions.reset();
      },
      execute: async (overrideSpec?: QuerySpec) => {
        return handleRunQuery(overrideSpec);
      },
      undo: () => {
        leaveRawMode();
        actions.undo();
      },
      redo: () => {
        leaveRawMode();
        actions.redo();
      },
      canUndo: () => history.canUndo,
      canRedo: () => history.canRedo,
    }),
    [getActiveSpec, currentSql, actions, history.canUndo, history.canRedo, leaveRawMode, handleRunQuery],
  );

  const handleSaveTemplate = (template: QueryTemplate) => {
    if (onSaveQuery) {
      const parsedSpec = raw.isRawMode
        ? parseSqlToSpec(template.sql, normalizedSchema) || template.spec || compiled.spec
        : template.spec || compiled.spec;
      onSaveQuery(template.title, template.sql, parsedSpec);
    }
    setIsTemplateManagerOpen(false);
  };

  const handleLoadTemplate = (template: QueryTemplate) => {
    if (template.spec && Object.keys(template.spec).length > 0) {
      actions.loadSpec(template.spec);
      leaveRawMode();
    } else if (template.sql) {
      raw.enterRawSql(template.sql);
      setActiveTab("sql");
    }
    setIsTemplateManagerOpen(false);
  };

  const handleSelectTab = (tab: typeof activeTab) => {
    if (tab === "sql") raw.seedFromCompiled();
    setActiveTab(tab);
  };

  const handleReorderResultColumns = useCallback(
    (newCols: string[]) => {
      if (newCols.length <= 1) return;
      if (state.orderedProjectionKeys.length === 0) {
        if (activeTables.length === 0) return;
        const orderedTables = [
          ...activeTables.filter((t) => t.name === primaryTable),
          ...activeTables.filter((t) => t.name !== primaryTable),
        ];
        const usedKeys = new Set<string>();
        const nextSelected: typeof state.selectedColumns = {};
        const nextKeys: string[] = [];
        for (const col of newCols) {
          if (col.includes(".")) {
            const dotIdx = col.indexOf(".");
            const tbl = col.slice(0, dotIdx);
            const colName = col.slice(dotIdx + 1);
            const key = `${tbl}.${colName}`;
            if (!usedKeys.has(key)) {
              usedKeys.add(key);
              nextSelected[key] = { table: tbl as typeof primaryTable, name: colName };
              nextKeys.push(key);
              continue;
            }
          }
          const matchedTable = orderedTables.find((t) =>
            t.columns.some((c) => c.name === col && !usedKeys.has(`${t.name}.${c.name}`)),
          );
          if (matchedTable) {
            const key = `${matchedTable.name}.${col}`;
            usedKeys.add(key);
            nextSelected[key] = { table: matchedTable.name as typeof primaryTable, name: col };
            nextKeys.push(key);
          }
        }
        if (nextKeys.length > 1) {
          leaveRawMode();
          actions.setSelectedColumns(nextSelected, nextKeys);
        }
        return;
      }
      if (state.orderedProjectionKeys.length <= 1) return;
      const remaining = [...state.orderedProjectionKeys];
      const reordered: string[] = [];
      for (const col of newCols) {
        // Priority 1: exact alias match (when aliased) or exact table.col key match
        let matchIdx = remaining.findIndex((key) => {
          const sel = state.selectedColumns[key];
          const effectiveAlias = sel?.alias?.trim();
          return effectiveAlias ? effectiveAlias === col : key === col;
        });
        // Priority 2: unaliased column name match
        if (matchIdx === -1) {
          matchIdx = remaining.findIndex((key) => {
            const sel = state.selectedColumns[key];
            const effectiveAlias = sel?.alias?.trim();
            if (effectiveAlias) return false;
            return key.endsWith(`.${col}`) || sel?.name === col;
          });
        }
        // Priority 3: fallback to raw name/suffix match
        if (matchIdx === -1) {
          matchIdx = remaining.findIndex((key) => {
            const sel = state.selectedColumns[key];
            return key === col || key.endsWith(`.${col}`) || sel?.alias === col || sel?.name === col;
          });
        }
        if (matchIdx !== -1) {
          reordered.push(remaining[matchIdx]);
          remaining.splice(matchIdx, 1);
        }
      }
      reordered.push(...remaining);
      leaveRawMode();
      actions.setOrderedProjectionKeys(reordered);
    },
    [state, activeTables, primaryTable, leaveRawMode, actions],
  );

  const shouldHideInnerToolbar = hideInnerToolbar || studioMode;
  const shouldHideSummaryBar = hideSummaryBar || studioMode;

  return (
    <QueryBuilderContext.Provider value={contextValue}>
      <div
        data-qb="root"
        data-qb-mode={activeTab}
        data-qb-unstyled={unstyled ? "true" : undefined}
        data-qb-studio={studioMode ? "true" : undefined}
        className={cx(className, classNames?.root)}
        style={rootStyle(activeTheme, cssVars, unstyled)}
      >
        {/* Top Controls Bar */}
        <div
          data-qb="top-bar"
          data-qb-hidden={shouldHideInnerToolbar ? "true" : undefined}
          className={cx(classNames?.header, shouldHideInnerToolbar ? "qb-sr-only" : undefined)}
          style={
            shouldHideInnerToolbar
              ? SR_ONLY_STYLE
              : unstyled
                ? undefined
                : {
                    display: "flex",
                    flexDirection: "column",
                    gap: compactHeader ? "6px" : "10px",
                    paddingBottom: compactHeader ? "8px" : "12px",
                    borderBottom: `1px solid ${activeTheme.colors.border}`,
                  }
          }
        >
          {/* Tier 1: Primary Mode Tabs & Execution CTA */}
          <div
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: compactHeader ? "6px" : "10px",
                  }
            }
          >
            <TabBar
              activeTab={activeTab}
              tabs={visibleTabs({ hasRawSqlTab, hasVisualChartTab, hasPipelineTab, hasPlanTab })}
              resultCount={queryResults ? queryResults.count : null}
              cteCount={ctes.length}
              onSelectTab={handleSelectTab}
              unstyled={unstyled}
              theme={activeTheme}
              classNames={classNames}
            />

            <ToolbarActions
              canUndo={history.canUndo}
              canRedo={history.canRedo}
              onUndo={() => {
                leaveRawMode();
                actions.undo();
              }}
              onRedo={() => {
                leaveRawMode();
                actions.redo();
              }}
              allowToggleAdvanced={allowToggleAdvanced}
              isAdvancedMode={isAdvancedMode}
              onToggleAdvanced={() => toggleAdvanced()}
              resolvedFeatures={resolvedFeatures}
              featureOverrides={featureOverrides}
              onFeatureOverride={(key, tier) => setFeatureOverrides((prev) => ({ ...prev, [key]: tier }))}
              dialect={dialect}
              onOpenTemplates={(mode) => {
                setTemplateManagerMode(mode);
                setIsTemplateManagerOpen(true);
              }}
              presets={presets}
              onSelectPreset={(preset) => {
                if (preset.spec && Object.keys(preset.spec).length > 0) {
                  actions.loadSpec(preset.spec);
                  leaveRawMode();
                  setActiveTab("visual");
                } else if (preset.sql) {
                  raw.enterRawSql(preset.sql);
                  setActiveTab("sql");
                }
              }}
              readOnly={readOnly}
              isRunning={isRunning}
              isSafe={safety.valid}
              onRun={handleRunQuery}
              unstyled={unstyled}
              theme={activeTheme}
            />
          </div>

          {/* Tier 2: Secondary Schema & Tools Ribbon + Compact Safety Badge */}
          <div
            data-qb="secondary-tools-ribbon"
            style={
              unstyled
                ? undefined
                : {
                    display:
                      compactHeader &&
                      safety.valid &&
                      !isFeatureVisible("window_functions") &&
                      !isFeatureVisible("schema_tools")
                        ? "none"
                        : "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "8px",
                    flexWrap: "wrap",
                    paddingTop: compactHeader ? "0px" : "2px",
                  }
            }
          >
            <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
              <ToolButtons
                unstyled={unstyled}
                theme={activeTheme}
                showWindowFunctions={isFeatureVisible("window_functions")}
                windowFunctionCount={windowFunctions.length}
                onOpenWindowFunctions={() => setIsWfBuilderOpen(true)}
                showSchemaTools={isFeatureVisible("schema_tools")}
                onOpenSchemaExplorer={() => setIsSchemaExplorerOpen(true)}
                onOpenErd={() => setIsErdOpen(true)}
              />
            </div>
            <SafetyBadge
              valid={safety.valid}
              message={safety.message}
              dialect={dialect}
              unstyled={unstyled}
              theme={activeTheme}
            />
          </div>
        </div>

        {!isAdvancedMode && activeAdvancedClauses.length > 0 && (
          <AdvancedClausesBanner
            labels={activeAdvancedClauses.map((c) => c.label)}
            onViewAdvanced={() => toggleAdvanced(true)}
            onClear={() => {
              leaveRawMode();
              clearAdvancedClauses();
            }}
            unstyled={unstyled}
            theme={activeTheme}
          />
        )}

        {executionError && (
          <ExecutionErrorBanner message={executionError} unstyled={unstyled} theme={activeTheme} />
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
              const activeSpec = getActiveSpec();
              if (activeSpec) void liveExec.executeQuery(activeSpec);
            }}
            onCancel={() => void liveExec.cancelExecution()}
            unstyled={unstyled}
          />
        )}

        {/* Tab Panels */}
        {activeTab === "visual" && (
          <VisualPanel
            nlq={
              showNlqBar && !hideNlqBar
                ? {
                    schema: augmentedSchema,
                    currentSpec: compiled.spec,
                    onApplySpec: handleApplyNlqSpec,
                    apiUrl: nlqApiUrl,
                    defaultProvider: nlqDefaultProvider,
                    dialect,
                    suggestions: nlqSuggestions,
                    showSchemaPills: false,
                    unstyled,
                  }
                : undefined
            }
            canvas={{
              schema: augmentedSchema,
              activeTables,
              primaryTable,
              selectedColumns: state.selectedColumns,
              orderedProjectionKeys: state.orderedProjectionKeys,
              joins: state.joins,
              filters: state.filters,
              sorts: state.sorts,
              isDistinct: state.isDistinct,
              limit: state.limit,
              windowFunctions,
              compiledSql: compiled.sql,
              currentSql,
              rawSql: raw.rawSql,
              isRawMode: raw.isRawMode,
              onRawSqlChange: raw.handleRawSqlChange,
              onSyncWithVisualCanvas: raw.handleSyncWithVisualCanvas,
              isAdvancedMode,
              hideSummaryBar: shouldHideSummaryBar,
              studioMode,
              onToggleColumn: canvasHandlers.handleToggleColumn,
              onRemoveTable: canvasHandlers.handleRemoveTable,
              onAddTableToCanvas: canvasHandlers.handleAddTableToCanvas,
              onUpdateColumnSelect: (key, updates) => {
                leaveRawMode();
                actions.updateColumnSelect(key, updates);
              },
              onRemoveColumnProjection: (key) => {
                leaveRawMode();
                actions.removeColumnProjection(key);
              },
              onAddCalculatedField: canvasHandlers.handleAddCalculatedField,
              onRemoveWindowFunction: (idx) => {
                leaveRawMode();
                actions.setWindowFunctions(windowFunctions.filter((_, i) => i !== idx));
              },
              onOpenWindowFunctions: () => setIsWfBuilderOpen(true),
              onJoinsChange: canvasHandlers.handleJoinsChange,
              onAddJoin: canvasHandlers.handleAddJoinToTable,
              onReorderProjections: (keys) => {
                leaveRawMode();
                if (keys.some((k) => !state.selectedColumns[k])) {
                  const nextSelected = { ...state.selectedColumns };
                  for (const k of keys) {
                    if (!nextSelected[k]) {
                      const dotIdx = k.indexOf(".");
                      if (dotIdx !== -1) {
                        nextSelected[k] = {
                          table: k.slice(0, dotIdx) as typeof primaryTable,
                          name: k.slice(dotIdx + 1),
                        };
                      }
                    }
                  }
                  actions.setSelectedColumns(nextSelected, keys);
                } else {
                  actions.setOrderedProjectionKeys(keys);
                }
              },
              onFiltersChange: canvasHandlers.setFilters,
              onSortsChange: canvasHandlers.setSorts,
              onDistinctChange: (distinct) => {
                leaveRawMode();
                actions.setDistinct(distinct);
              },
              onLimitChange: (limit) => {
                leaveRawMode();
                actions.setLimit(limit);
              },
              vectorSearch,
              hybridSearch,
              onVectorChange: (vs) => {
                leaveRawMode();
                actions.setVectorSearch(vs);
              },
              onHybridChange: (hs) => {
                leaveRawMode();
                actions.setHybridSearch(hs);
              },
              unstyled,
              classNames,
              customOperators,
              fieldRenderers,
            }}
            dock={{
              results: queryResults,
              isLoading: isRunning,
              currentSql,
              isOpen: isDockOpen,
              onToggleOpen: () => setIsDockOpen((prev) => !prev),
              dockTab,
              onSelectDockTab: (t) => setDockTab(t),
              onExpandFullTab: (t) => setActiveTab(t),
              onReorderColumns: handleReorderResultColumns,
              cellRenderers,
              classNames,
              unstyled,
              theme: activeTheme,
            }}
          />
        )}

        {activeTab === "sql" && (
          <SqlPanel
            currentSql={currentSql}
            rawSql={raw.rawSql}
            isRawMode={raw.isRawMode}
            schema={augmentedSchema}
            discardedRawSql={raw.discardedRawSql}
            onRawSqlChange={raw.handleRawSqlChange}
            onDismissDiscarded={() => raw.setDiscardedRawSql(null)}
            onSyncWithVisualCanvas={raw.handleSyncWithVisualCanvas}
            unstyled={unstyled}
            theme={activeTheme}
            classNames={classNames}
          />
        )}

        {activeTab === "results" && (
          <ResultsPanel
            results={queryResults}
            isLoading={isRunning}
            unstyled={unstyled}
            onReorderColumns={handleReorderResultColumns}
            cellRenderers={cellRenderers}
            classNames={classNames}
          />
        )}

        {activeTab === "chart" && <ChartPanel results={queryResults} unstyled={unstyled} />}

        {hasPlanTab && activeTab === "plan" && (
          <PlanPanel
            plan={queryPlan || estimateClientPlan(compiled.spec)}
            spec={compiled.spec}
            sql={currentSql}
            dialect={dialect}
            schema={augmentedSchema}
            unstyled={unstyled}
          />
        )}

        {hasPipelineTab && activeTab === "pipeline" && (
          <PipelinePanel
            ctes={ctes}
            onCtesChange={(newCtes) => {
              leaveRawMode();
              actions.setCtes(newCtes);
            }}
            onSelectStage={(stage) => {
              leaveRawMode();
              setActiveStageName(stage);
              if (stage) {
                actions.setPrimaryTable(stage);
                if (!activeTableNames.includes(stage)) {
                  actions.addTable(stage);
                }
              }
              setActiveTab("visual");
            }}
            selectedStage={activeStageName}
            unstyled={unstyled}
          />
        )}

        {/* Window Function Builder Modal */}
        <WindowFunctionBuilder
          isOpen={isWfBuilderOpen}
          onClose={() => setIsWfBuilderOpen(false)}
          onSave={(wf) => {
            leaveRawMode();
            actions.setWindowFunctions([...windowFunctions, wf]);
          }}
          availableColumns={allTables.flatMap((t) =>
            t.columns.map((c) => ({ table: t.name, name: c.name })),
          )}
          unstyled={unstyled}
        />

        {/* Schema ERD Modal */}
        <SchemaErdModal
          isOpen={isErdOpen}
          onClose={() => setIsErdOpen(false)}
          schema={augmentedSchema}
          onSelectTable={(tbl) => canvasHandlers.handleAddTableToCanvas(tbl)}
          onAddJoins={(newJoins) => canvasHandlers.handleJoinsChange([...state.joins, ...newJoins])}
        />

        {/* Schema Explorer Modal */}
        <SchemaExplorerModal
          isOpen={isSchemaExplorerOpen}
          onClose={() => setIsSchemaExplorerOpen(false)}
          schema={augmentedSchema}
          selectedTable={primaryTable}
          onSelectTable={(tbl) => {
            leaveRawMode();
            actions.setPrimaryTable(tbl);
          }}
          onAddToCanvas={(tbl) => {
            canvasHandlers.handleAddTableToCanvas(tbl);
            setIsSchemaExplorerOpen(false);
          }}
          onOpenErd={() => {
            setIsSchemaExplorerOpen(false);
            setIsErdOpen(true);
          }}
          onQuickQuery={(tbl) => {
            canvasHandlers.handleAddTableToCanvas(tbl);
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
            schema={augmentedSchema}
            currentSpec={compiled.spec}
            dialect={dialect}
            onApplySpec={handleApplyNlqSpec}
            unstyled={unstyled}
          />
        )}
      </div>
    </QueryBuilderContext.Provider>
  );
}) as <Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition>(
  props: ExtendedVisualQueryBuilderProps<Schema> & { ref?: React.Ref<VisualQueryBuilderRef> },
) => React.ReactElement | null;
