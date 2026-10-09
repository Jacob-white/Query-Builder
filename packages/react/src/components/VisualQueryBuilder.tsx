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
  detectActiveAdvancedClauses,
} from "../utils/featureUtils";
import { SchemaErdModal } from "./SchemaErdModal";
import { SchemaExplorerModal } from "./SchemaExplorerModal";
import { QueryTemplateManager } from "./QueryTemplateManager";
import { LiveExecutionBar } from "./LiveExecutionBar";
import { WindowFunctionBuilder } from "./WindowFunctionBuilder";
import { AiAssistantWidget } from "./AiAssistantWidget";
import type { LiveExecutionResult } from "../hooks/useLiveExecution";
import { estimateClientPlan, compileVisualState } from "../utils/compiler";
import { validateSqlSafety } from "../utils/safety";
import { parseSqlToSpec } from "../utils/sqlParser";
import { useQueryState } from "../hooks/useQueryState";
import { cx } from "../utils/classNames";
import { useQueryBuilderContext } from "../theme/QueryBuilderProvider";
import type { QueryBuilderTheme } from "../theme/tokens";
import type { NlqProviderName } from "../hooks/useNlqQuery";
import type { QueryPlanNode, CteSpec, WindowFunctionSpec, SemanticModel } from "../types";
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

export type { VisualQueryBuilderRef };
export { fastCanonicalSpec };

export type ExtendedVisualQueryBuilderProps<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition> = Omit<
  VisualQueryBuilderProps<Schema>,
  "theme"
> & {
  theme?: "dark" | "light" | "auto" | QueryBuilderTheme;
  unstyled?: boolean;
  queryPlan?: QueryPlanNode;
  showPlanTab?: boolean;
  showNlqBar?: boolean;
  nlqApiUrl?: string;
  nlqDefaultProvider?: NlqProviderName;
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

  const activeAdvancedClauses = useMemo(() => {
    if (isAdvancedMode) return [];
    return detectActiveAdvancedClauses(
      { ctes, windowFunctions, vectorSearch, hybridSearch, selectedColumns: state.selectedColumns },
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
      if (v && (v.rawExpression || (v as { expression?: unknown }).expression)) {
        delete cleanedCols[k];
        hasCleaned = true;
      }
    }
    if (hasCleaned) actions.setSelectedColumns(cleanedCols);
  }, [ctes, windowFunctions, vectorSearch, hybridSearch, state.selectedColumns, actions]);

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

  // Compiled visual query
  const compiled = useMemo(() => {
    return compileVisualState(
      primaryTable,
      state.selectedColumns,
      state.orderedProjectionKeys,
      state.joins,
      state.filters,
      state.sorts,
      state.isDistinct,
      state.limit,
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
    state.selectedColumns,
    state.orderedProjectionKeys,
    state.joins,
    state.filters,
    state.sorts,
    state.isDistinct,
    state.limit,
    augmentedSchema,
    dialect,
    customOperators,
    vectorSearch,
    hybridSearch,
    ctes,
    windowFunctions,
    semanticModels,
  ]);

  const raw = useRawSqlMode({
    compiled,
    dialect,
    compileSchema: augmentedSchema,
    parseSchema: normalizedSchema,
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

  const { queryResults, isRunning, executionError, liveExec, handleRunQuery } = useQueryRunner({
    propExecuteQuery,
    contextExecuteQuery: qbContext?.onExecuteQuery,
    client,
    getActiveSpec,
    currentSql,
    setActiveTab,
    dialect,
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
    undo: actions.undo,
    redo: actions.redo,
  });

  useControlledSpecSync({ value, onChange, loadSpec: actions.loadSpec, getActiveSpec, currentSql });

  const handleApplyNlqSpec = (appliedSpec: QuerySpec) => {
    if (appliedSpec && appliedSpec.table) {
      actions.loadSpec(appliedSpec);
      leaveRawMode();
    }
  };

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
      execute: async () => {
        return handleRunQuery();
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

  return (
    <div
      data-qb="root"
      data-qb-mode={activeTab}
      data-qb-unstyled={unstyled ? "true" : undefined}
      className={cx(className, classNames?.root)}
      style={rootStyle(activeTheme, cssVars, unstyled)}
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

        <ToolbarActions
          canUndo={history.canUndo}
          canRedo={history.canRedo}
          onUndo={() => actions.undo()}
          onRedo={() => actions.redo()}
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
          onSelectPreset={(sql) => {
            raw.enterRawSql(sql);
            setActiveTab("sql");
          }}
          readOnly={readOnly}
          isRunning={isRunning}
          isSafe={safety.valid}
          onRun={handleRunQuery}
          unstyled={unstyled}
          theme={activeTheme}
        />
      </div>

      {!isAdvancedMode && activeAdvancedClauses.length > 0 && (
        <AdvancedClausesBanner
          labels={activeAdvancedClauses.map((c) => c.label)}
          onViewAdvanced={() => toggleAdvanced(true)}
          onClear={handleClearAdvancedClauses}
          unstyled={unstyled}
          theme={activeTheme}
        />
      )}

      <SafetyBadge
        valid={safety.valid}
        message={safety.message}
        unstyled={unstyled}
        theme={activeTheme}
      />

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
            showNlqBar
              ? {
                  schema: normalizedSchema,
                  currentSpec: compiled.spec,
                  onApplySpec: handleApplyNlqSpec,
                  apiUrl: nlqApiUrl,
                  defaultProvider: nlqDefaultProvider,
                  dialect,
                  unstyled,
                }
              : undefined
          }
          canvas={{
            schema: normalizedSchema,
            activeTables,
            primaryTable,
            selectedColumns: state.selectedColumns,
            orderedProjectionKeys: state.orderedProjectionKeys,
            joins: state.joins,
            filters: state.filters,
            sorts: state.sorts,
            isDistinct: state.isDistinct,
            limit: state.limit,
            onToggleColumn: canvasHandlers.handleToggleColumn,
            onRemoveTable: canvasHandlers.handleRemoveTable,
            onAddTableToCanvas: canvasHandlers.handleAddTableToCanvas,
            onUpdateColumnSelect: actions.updateColumnSelect,
            onRemoveColumnProjection: actions.removeColumnProjection,
            onJoinsChange: canvasHandlers.handleJoinsChange,
            onAddJoin: canvasHandlers.handleAddJoinToTable,
            onReorderProjections: actions.setOrderedProjectionKeys,
            onFiltersChange: canvasHandlers.setFilters,
            onSortsChange: canvasHandlers.setSorts,
            onDistinctChange: actions.setDistinct,
            onLimitChange: actions.setLimit,
            vectorSearch,
            hybridSearch,
            onVectorChange: actions.setVectorSearch,
            onHybridChange: actions.setHybridSearch,
            unstyled,
            classNames,
            customOperators,
            fieldRenderers,
          }}
        />
      )}

      {activeTab === "sql" && (
        <SqlPanel
          currentSql={currentSql}
          rawSql={raw.rawSql}
          isRawMode={raw.isRawMode}
          schema={normalizedSchema}
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
          cellRenderers={cellRenderers}
          classNames={classNames}
        />
      )}

      {activeTab === "chart" && <ChartPanel results={queryResults} unstyled={unstyled} />}

      {hasPlanTab && activeTab === "plan" && (
        <PlanPanel plan={queryPlan || estimateClientPlan(compiled.spec)} unstyled={unstyled} />
      )}

      {hasPipelineTab && activeTab === "pipeline" && (
        <PipelinePanel
          ctes={ctes}
          onCtesChange={actions.setCtes}
          onSelectStage={(stage) => {
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
        onSave={(wf) => actions.setWindowFunctions([...windowFunctions, wf])}
        availableColumns={allTables.flatMap((t) =>
          t.columns.map((c) => ({ table: t.name, name: c.name })),
        )}
        unstyled={unstyled}
      />

      {/* Schema ERD Modal */}
      <SchemaErdModal
        isOpen={isErdOpen}
        onClose={() => setIsErdOpen(false)}
        schema={normalizedSchema}
        onSelectTable={(tbl) => canvasHandlers.handleAddTableToCanvas(tbl)}
        onAddJoins={(newJoins) => canvasHandlers.handleJoinsChange([...state.joins, ...newJoins])}
      />

      {/* Schema Explorer Modal */}
      <SchemaExplorerModal
        isOpen={isSchemaExplorerOpen}
        onClose={() => setIsSchemaExplorerOpen(false)}
        schema={normalizedSchema}
        selectedTable={primaryTable}
        onSelectTable={(tbl) => actions.setPrimaryTable(tbl)}
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
          schema={normalizedSchema}
          currentSpec={compiled.spec}
          dialect={dialect}
          onApplySpec={handleApplyNlqSpec}
          unstyled={unstyled}
        />
      )}
    </div>
  );
}) as <Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition>(
  props: ExtendedVisualQueryBuilderProps<Schema> & { ref?: React.Ref<VisualQueryBuilderRef> },
) => React.ReactElement | null;
