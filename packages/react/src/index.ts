/**
 * @jacob-white/query-builder-react
 * Standalone Visual SQL Query Builder & Schema Explorer React component library.
 */

export * from "./types";
export * from "./utils/joinUtils";
export * from "./utils/safety";
export * from "./utils/compiler";
export * from "./utils/schemaUtils";
export * from "./utils/sqlParser";
export * from "./utils/vectorUtils";
export * from "./adapters";

export { VisualQueryBuilder } from "./components/VisualQueryBuilder";
export { QueryCanvas } from "./components/QueryCanvas";
export { TableCard } from "./components/TableCard";
export { TableFiltersEditor } from "./components/TableFiltersEditor";
export { TableJoinEditor } from "./components/TableJoinEditor";
export { TableSortsEditor } from "./components/TableSortsEditor";
export {
  NlqPromptBar,
  type NlqPromptBarProps,
} from "./components/NlqPromptBar";
export {
  LiveExecutionBar,
  type LiveExecutionBarProps,
} from "./components/LiveExecutionBar";
export {
  PipelineDagCanvas,
  type PipelineDagCanvasProps,
  detectCteCycles,
} from "./components/PipelineDagCanvas";
export {
  WindowFunctionBuilder,
  type WindowFunctionBuilderProps,
  SUPPORTED_WINDOW_FUNCTIONS,
} from "./components/WindowFunctionBuilder";
export {
  VectorHybridControl,
  type VectorHybridControlProps,
} from "./components/VectorHybridControl";
export {
  QueryPlanVisualizer,
  type QueryPlanVisualizerProps,
} from "./components/QueryPlanVisualizer";
export { SchemaErdModal } from "./components/SchemaErdModal";
export { SchemaExplorer, type SchemaExplorerProps } from "./components/SchemaExplorer";
export {
  SchemaExplorerModal,
  type SchemaExplorerModalProps,
} from "./components/SchemaExplorerModal";
export {
  QueryResultsTable,
  type QueryResultsTableProps,
} from "./components/QueryResultsTable";
export {
  CalculatedFieldEditor,
  type CalculatedFieldEditorProps,
} from "./components/CalculatedFieldEditor";
export { QueryChartPreview } from "./components/QueryChartPreview";
export { BiChartVisualizer } from "./components/BiChartVisualizer";
export { QueryPlayground } from "./components/QueryPlayground";
export { ExportWorkbench, type ExportWorkbenchProps } from "./components/ExportWorkbench";
export { LocalDataModal, type LocalDataModalProps } from "./components/LocalDataModal";
export { DashboardWorkbench, type DashboardWorkbenchProps } from "./components/DashboardWorkbench";
export {
  QueryPerformanceAdvisor,
  type QueryPerformanceAdvisorProps,
} from "./components/QueryPerformanceAdvisor";
export {
  estimateCloudQueryCost,
  recommendIndexes,
  analyzeQueryPerformance,
} from "./utils/performanceAdvisor";
export {
  InMemoryOlapEngine,
  getClientOlapEngine,
  resetClientOlapEngine,
  type DuckDBDriverConfig,
} from "./drivers/duckdbDriver";
export {
  detectFileFormat,
  sanitizeTableName,
  ingestLocalFile,
  type IngestibleFormat,
} from "./utils/localDataIngest";
export {
  QueryTemplateManager,
  SEED_TEMPLATES,
  loadTemplates,
  saveTemplates,
  resetTemplateStorage,
} from "./components/QueryTemplateManager";

// First-Class API Client & Fluent Query Builder
export * from "./client";

// In-Memory OLAP Engine & Local Data Ingestion
export * from "./olap";

// Headless Hooks
export * from "./hooks";

// Theming System
export {
  darkTheme,
  lightTheme,
  mergeTheme,
  themeToCssVariables,
} from "./theme/tokens";
export type {
  DeepPartial,
  QueryBuilderThemeColors,
  QueryBuilderThemeTypography,
  QueryBuilderThemeRadii,
  QueryBuilderThemeShadows,
  QueryBuilderTheme,
} from "./theme/tokens";

export {
  ThemeProvider,
  useTheme,
  ThemeContext,
} from "./theme/ThemeProvider";
export type {
  ThemeProviderProps,
  ThemeContextValue,
} from "./theme/ThemeProvider";

export {
  QueryBuilderProvider,
  useQueryBuilderContext,
  QueryBuilderContext,
} from "./theme/QueryBuilderProvider";
export type {
  QueryBuilderProviderProps,
  QueryBuilderContextValue,
} from "./theme/QueryBuilderProvider";

export { ComponentShowcase } from "./components/ComponentShowcase";
export type {
  ComponentShowcaseProps,
  ShowcaseTab,
} from "./components/ComponentShowcase";

// Bring Your Own AI (BYO-AI) & Agentic Framework
export * from "./ai";

// Composable Compound Components & Slotted Styling Primitives
export * from "./components/compound";
export { cx } from "./utils/classNames";

