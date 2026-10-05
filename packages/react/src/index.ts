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
export * from "./adapters";

export { VisualQueryBuilder } from "./components/VisualQueryBuilder";
export { QueryCanvas } from "./components/QueryCanvas";
export { TableCard } from "./components/TableCard";
export { TableFiltersEditor } from "./components/TableFiltersEditor";
export { TableJoinEditor } from "./components/TableJoinEditor";
export { TableSortsEditor } from "./components/TableSortsEditor";
export { SchemaErdModal } from "./components/SchemaErdModal";
export { SchemaExplorer, type SchemaExplorerProps } from "./components/SchemaExplorer";
export {
  SchemaExplorerModal,
  type SchemaExplorerModalProps,
} from "./components/SchemaExplorerModal";
export { QueryResultsTable } from "./components/QueryResultsTable";
export { QueryChartPreview } from "./components/QueryChartPreview";
export { QueryPlayground } from "./components/QueryPlayground";
export { ExportWorkbench, type ExportWorkbenchProps } from "./components/ExportWorkbench";
export {
  QueryTemplateManager,
  SEED_TEMPLATES,
  loadTemplates,
  saveTemplates,
  resetTemplateStorage,
} from "./components/QueryTemplateManager";

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

// Component Showcase
export { ComponentShowcase } from "./components/ComponentShowcase";
export type {
  ComponentShowcaseProps,
  ShowcaseTab,
} from "./components/ComponentShowcase";
