/**
 * Type specifications for React Query Builder UI.
 */

export interface ColumnMeta {
  name: string;
  data_type: string;
  is_nullable: boolean;
  is_primary: boolean;
  comment?: string;
}

export interface TableMeta {
  name: string;
  schema?: string;
  comment?: string;
  columns: ColumnMeta[];
  has_user_id?: boolean;
  metrics?: MetricDefinition[];
  dimensions?: DimensionDefinition[];
}

export interface ForeignKeyMeta {
  table: string;
  column: string;
  foreign_table: string;
  foreign_column: string;
}

export interface ForeignKey {
  table: string;
  column: string;
  foreignTable: string;
  foreign_table?: string;
  foreignColumn: string;
  foreign_column?: string;
}

export interface ColumnSchema {
  name: string;
  dataType: string;
  data_type?: string;
  isNullable?: boolean;
  is_nullable?: boolean;
  isPrimary?: boolean;
  is_primary?: boolean;
  default?: unknown;
  comment?: string;
  enums?: string[];
  foreignKey?: ForeignKey;
  foreign_key?: ForeignKey;
}

export interface TableSchema {
  name: string;
  schema?: string;
  comment?: string;
  columns: ColumnSchema[];
  foreignKeys?: ForeignKey[];
  foreign_keys?: ForeignKey[];
  primaryKeys?: string[];
  primary_keys?: string[];
  enums?: Record<string, string[]>;
}

export interface SchemaSnapshot {
  tables: Record<string, TableMeta>;
  categories?: Record<string, string[]>;
  foreign_keys?: ForeignKeyMeta[];
  relationships?: {
    source_table: string;
    source_column: string;
    target_table: string;
    target_column: string;
  }[];
}

// ==========================================
// Generic Database Schema Definitions
// ==========================================

export type SchemaDataType =
  | "string"
  | "number"
  | "boolean"
  | "date"
  | "timestamp"
  | "json"
  | "uuid"
  | "decimal"
  | "integer"
  | string;

export interface ColumnDefinition {
  dataType: SchemaDataType;
  nullable?: boolean;
  primaryKey?: boolean;
  comment?: string;
}

export interface RelationshipDefinition {
  targetTable: string;
  targetColumn?: string;
  sourceColumn?: string;
  type?: "one-to-one" | "one-to-many" | "many-to-one" | "many-to-many";
}

export interface TableDefinition {
  columns: Record<string, ColumnDefinition | string> | ColumnMeta[];
  relationships?: Record<string, RelationshipDefinition>;
  comment?: string;
}

export interface DatabaseSchemaDefinition {
  tables: Record<string, TableDefinition>;
}

// ==========================================
// Schema Generic Utility Helpers
// ==========================================

export type SchemaTableNames<Schema> =
  Schema extends { tables: infer T }
    ? T extends object
      ? keyof T & string
      : string
    : string;

export type SchemaColumnNames<Schema, Table extends string> =
  Schema extends {
    tables: {
      [K in Table]: {
        columns: infer C;
      };
    };
  }
    ? C extends Array<{ name: infer ColName extends string }>
      ? ColName
      : C extends object
        ? keyof C & string
        : string
    : string;

export type SchemaColumnRefs<Schema> =
  SchemaTableNames<Schema> extends infer T extends string
    ? [T] extends [never]
      ? string
      : { [K in T]: `${K}.${SchemaColumnNames<Schema, K>}` }[T]
    : string;

export type SchemaJoinTargetTables<Schema, SourceTable extends string> =
  Schema extends {
    tables: {
      [K in SourceTable]: {
        relationships?: infer R;
      };
    };
  }
    ? R extends Record<string, { targetTable: infer TT extends string }>
      ? TT
      : SchemaTableNames<Schema>
    : SchemaTableNames<Schema>;

export type SchemaColumnType<Schema, Table extends string, Col extends string> =
  Schema extends {
    tables: {
      [T in Table]: {
        columns: {
          [C in Col]: { dataType: infer DT } | infer DirectDT;
        };
      };
    };
  }
    ? DT extends string
      ? DT
      : DirectDT extends string
        ? DirectDT
        : unknown
    : unknown;

// ==========================================
// Filter and Visual AST Types
// ==========================================

export type BuiltInFilterOperator =
  | "="
  | "!="
  | ">"
  | "<"
  | ">="
  | "<="
  | "STARTS_WITH"
  | "ENDS_WITH"
  | "CONTAINS"
  | "LIKE"
  | "ILIKE"
  | "IN"
  | "NOT IN"
  | "BETWEEN"
  | "IS NULL"
  | "IS NOT NULL";

export type FilterOperator = BuiltInFilterOperator | (string & {});

export interface CustomFilterOperator {
  label: string;
  value: string;
  hasValue?: boolean;
  placeholder?: string;
  formatSql?: (colRef: string, val: string | number | boolean, dialect: string) => string;
}

export interface FieldRendererProps {
  column: ColumnMeta;
  table: TableMeta;
  isSelected: boolean;
  onToggle: () => void;
  unstyled?: boolean;
}

export type CustomFieldRenderer = (props: FieldRendererProps) => React.ReactNode;

export type TimeGrain =
  | "second"
  | "minute"
  | "hour"
  | "day"
  | "week"
  | "month"
  | "quarter"
  | "year";

/**
 * Value accepted by a filter: scalars, `null` (for `IS` / `IS NOT`) or a list (for `IN` / `BETWEEN`).
 */
export type FilterValue =
  | string
  | number
  | boolean
  | null
  | ReadonlyArray<string | number | boolean | null>;

/**
 * Cell renderer callback. Declared with the method-bivariance pattern so consumer callbacks with a
 * narrower parameter type (for example `(v: number) => ...`) stay assignable.
 */
export type CellRenderer = {
  bivarianceHack(value: unknown, row: Record<string, unknown>, column: string): React.ReactNode;
}["bivarianceHack"];

/**
 * Query execution callback. `spec` is `null` when raw-SQL mode holds SQL that cannot be mapped to a
 * QuerySpec. Method-bivariant so handlers declared with a narrower `spec` type remain assignable.
 */
export type ExecuteQueryHandler = {
  bivarianceHack(sql: string, spec?: QuerySpec | null): Promise<QueryResultData> | void;
}["bivarianceHack"];

export interface MetricFilter {
  field: string;
  operator: string;
  value: unknown;
}

export interface MetricDefinition {
  name: string;
  title: string;
  description?: string;
  sqlExpression: string;
  aggregation: "sum" | "avg" | "count" | "count_distinct" | "min" | "max" | "custom";
  filters?: MetricFilter[];
  format?: "currency" | "percentage" | "number" | "decimal" | "integer" | "duration" | "raw";
  table?: string;
}

export interface DimensionDefinition {
  name: string;
  title: string;
  description?: string;
  sqlExpression: string;
  dataType?: string;
  timeGrains?: TimeGrain[];
  table?: string;
}

export interface SemanticModel {
  name: string;
  tableName: string;
  description?: string;
  primaryKey?: string;
  defaultTimeDimension?: string;
  dimensions?: DimensionDefinition[];
  metrics?: MetricDefinition[];
}

export interface VisualJoin<Schema = DatabaseSchemaDefinition> {
  id: string;
  type: "LEFT JOIN" | "INNER JOIN" | "RIGHT JOIN" | "FULL JOIN";
  left_table?: SchemaTableNames<Schema>;
  table: SchemaTableNames<Schema>;
  left_col: string;
  right_col: string;
}

export interface VisualFilter<Schema = DatabaseSchemaDefinition> {
  id: string;
  combiner?: "AND" | "OR";
  parenOpen?: string;
  tablePrefix?: SchemaTableNames<Schema>;
  column: SchemaColumnNames<Schema, string> | string;
  operator: FilterOperator;
  value: string | number | boolean;
  parenClose?: string;
  rawExpression?: string;
}

export interface VisualSort<Schema = DatabaseSchemaDefinition> {
  id: string;
  tablePrefix?: SchemaTableNames<Schema>;
  column: SchemaColumnNames<Schema, string> | string;
  direction: "ASC" | "DESC";
}

export interface VisualColumnSelect<Schema = DatabaseSchemaDefinition> {
  table: SchemaTableNames<Schema>;
  name: SchemaColumnNames<Schema, string> | string;
  aggregate?: "" | "COUNT" | "SUM" | "AVG" | "MIN" | "MAX";
  alias?: string;
  timeGrain?: TimeGrain;
  metric?: boolean | string | MetricDefinition;
  format?: string;
  rawExpression?: string;
}

export interface VectorSearchSpec {
  vector: number[];
  column?: string;
  top_k?: number;
  metric?: "cosine" | "euclidean" | "l2" | "dot_product" | "inner_product";
  include_distances?: boolean;
  min_score?: number;
}

export interface HybridSearchSpec {
  vector: number[];
  vector_column?: string;
  query_text: string;
  text_columns: string[];
  alpha?: number; // 0.0 = pure text, 1.0 = pure vector
  fusion?: "rrf" | "linear";
  rrf_k?: number;
  top_k?: number;
  metric?: "cosine" | "euclidean" | "l2" | "dot_product" | "inner_product";
  include_scores?: boolean;
}

export interface QueryPlanNode {
  node_type: string;
  table?: string;
  cost_estimate?: number;
  actual_time_ms?: number;
  rows_estimated?: number;
  rows_actual?: number;
  filter_predicate?: string;
  index_name?: string;
  cost_percentage?: number;
  warnings?: string[];
  children?: QueryPlanNode[];
}

export interface StreamingQueryState {
  rows: Record<string, unknown>[];
  columns: string[];
  isStreaming: boolean;
  progress: {
    rowsReceived: number;
    totalEstimated?: number;
    elapsedMs: number;
  };
  error: string | null;
}

export interface CaseWhenBranch {
  condition: {
    column: string;
    op: string;
    value?: string | number | null;
    tablePrefix?: string;
  };
  then_value?: string | number | null;
  then_column?: string;
}

export interface CaseWhenSpec {
  branches: CaseWhenBranch[];
  else_value?: string | number | null;
  else_column?: string;
  alias?: string;
}

export interface SetOperationSpec<Schema = DatabaseSchemaDefinition> {
  operation: "UNION" | "UNION ALL" | "INTERSECT" | "EXCEPT" | "MINUS";
  query: QuerySpec<Schema>;
}

export interface CalculatedFieldSpec {
  id: string;
  name: string;
  alias: string;
  type: "case_when" | "expression";
  case_when?: CaseWhenSpec;
  expression?: string;
  dataType?: string;
}

export interface QuerySpec<Schema = DatabaseSchemaDefinition> {
  table: SchemaTableNames<Schema>;
  columns: (
    | string
    | {
        column?: string;
        agg?: string;
        alias?: string;
        case_when?: CaseWhenSpec;
        expression?: string;
      }
  )[];
  joins: {
    table: SchemaTableNames<Schema>;
    type: string;
    on?: { left: string; right: string }[];
    left_table?: SchemaTableNames<Schema>;
    left_col?: string;
    right_col?: string;
  }[];
  filters: {
    column: string;
    op: string;
    value: FilterValue;
    tablePrefix?: SchemaTableNames<Schema>;
    combiner?: "AND" | "OR";
    rawExpression?: string;
  }[];
  filter_join: "AND" | "OR";
  order_by: {
    column: string;
    direction: "ASC" | "DESC";
    tablePrefix?: SchemaTableNames<Schema>;
  }[];
  distinct: boolean;
  limit: number;
  offset?: number;
  vector_search?: VectorSearchSpec;
  hybrid_search?: HybridSearchSpec;
  ctes?: CteSpec[];
  window_functions?: WindowFunctionSpec[];
  set_operations?: SetOperationSpec<Schema>[];
  group_by?: string[];
  having?: { column: string; op: string; value: unknown }[];
  grouping_type?: "standard" | "rollup" | "cube" | "grouping_sets";
  grouping_sets?: string[][];
}

/**
 * Loosely-typed view over the many spec shapes accepted at runtime
 * (QuerySpec, QueryState, saved presets). Accepts snake_case and camelCase aliases.
 */
export interface LooseSpecColumn {
  column?: string;
  agg?: string;
  alias?: string;
  raw_expression?: string;
  rawExpression?: string;
  time_grain?: string;
  timeGrain?: string;
  metric?: boolean | string | MetricDefinition;
}

export interface LooseSpecJoin {
  id?: string;
  table: string;
  type?: string;
  left_table?: string;
  left_col?: string;
  right_col?: string;
  on?: { left?: string; right?: string }[];
}

export interface LooseSpecFilter {
  id?: string;
  combiner?: "AND" | "OR";
  tablePrefix?: string;
  table?: string;
  column?: string;
  operator?: string;
  op?: string;
  value?: string | number | boolean | null;
  raw_expression?: string;
  rawExpression?: string;
}

export interface LooseSpecSort {
  id?: string;
  tablePrefix?: string;
  column?: string;
  direction?: "ASC" | "DESC";
}

export interface LooseQuerySpec {
  table?: string;
  primaryTable?: string;
  activeTables?: (string | TableMeta)[];
  selectedColumns?: Record<string, VisualColumnSelect>;
  orderedProjectionKeys?: string[];
  columns?: (string | LooseSpecColumn | null)[];
  joins?: LooseSpecJoin[];
  filters?: LooseSpecFilter[];
  sorts?: VisualSort[];
  order_by?: LooseSpecSort[];
  filter_join?: "AND" | "OR";
  filterJoin?: "AND" | "OR";
  distinct?: boolean;
  isDistinct?: boolean;
  limit?: number;
  offset?: number;
  dialect?: string;
  vector_search?: VectorSearchSpec | null;
  vectorSearch?: VectorSearchSpec | null;
  hybrid_search?: HybridSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  ctes?: CteSpec[] | null;
  window_functions?: WindowFunctionSpec[] | null;
  windowFunctions?: WindowFunctionSpec[] | null;
  semantic_models?: SemanticModel[] | null;
  semanticModels?: SemanticModel[] | null;
}

export interface WindowFrameSpec {
  frame_type?: "ROWS" | "RANGE" | "GROUPS";
  start?: string;
  end?: string;
  exclusion?: string;
}

export interface WindowFunctionSpec {
  function: string;
  arguments?: (string | number)[];
  partition_by?: string[];
  order_by?: {
    column: string;
    direction?: "ASC" | "DESC";
    tablePrefix?: string;
  }[];
  frame?: WindowFrameSpec;
  alias?: string;
}

export interface CteSpec {
  name: string;
  query: Partial<QuerySpec> & { sql?: string };
  columns?: string[];
  recursive?: boolean;
  materialized?: boolean;
}

export interface SqlPreset {
  id: string;
  title: string;
  description: string;
  category?: string;
  sql?: string;
  spec?: Record<string, unknown>;
}

export interface SqlSafetyValidation {
  valid: boolean;
  isEmpty: boolean;
  statementType: string;
  isReadOnly: boolean;
  violations: string[];
  injectionRisk: "NONE" | "HIGH" | "CRITICAL";
  message: string;
}

export interface QueryResultData {
  columns: string[];
  rows: Record<string, unknown>[];
  count: number;
  latency_ms?: number;
  durationMs?: number;
}

export type SqlDialect =
  | "postgres"
  | "snowflake"
  | "mssql"
  | "sqlite"
  | "mysql"
  | "duckdb"
  | "bigquery"
  | "clickhouse"
  | "oracle"
  | "redshift"
  | "trino"
  | "presto"
  | "databricks"
  | "athena"
  | "polars"
  | "datafusion"
  | "timescaledb"
  | "cockroachdb"
  | "spanner"
  | "questdb"
  | "elasticsearch"
  | "dynamodb"
  | "dremio"
  | "firebolt"
  | "tidb"
  | "singlestore"
  | "memsql"
  | "teradata"
  | "couchbase"
  | "n1ql"
  | "d1"
  | "cloudflare_d1"
  | "mongodb"
  | "mongo"
  | "atlas_sql"
  | "neon"
  | "supabase"
  | "prestodb"
  | "druid"
  | "apache_druid"
  | "pinot"
  | "apache_pinot"
  | "starrocks"
  | "materialize"
  | "mz"
  | "risingwave"
  | "rw"
  | "cratedb"
  | "crate"
  | "influxdb"
  | "iox"
  | "influx"
  | "alloydb"
  | "vertica"
  | "saphana"
  | "hana"
  | "sap_hana"
  | "oceanbase"
  | "scylladb"
  | "scylla"
  | "cassandra"
  | "cql"
  | "sparksql"
  | "spark"
  | "chdb"
  | "greptimedb"
  | "greptime"
  | "tdengine"
  | "taos"
  | "surrealdb"
  | "surreal"
  | "arangodb"
  | "arango"
  | "aql"
  | "exasol"
  | "db2"
  | "ibm_db2"
  | "cosmosdb"
  | "azure_cosmos"
  | "doris"
  | "apache_doris"
  | "pydoris"
  | "impala"
  | "apache_impala"
  | "impyla"
  | "hive"
  | "apache_hive"
  | "pyhive"
  | "kyuubi"
  | "apache_kyuubi"
  | "drill"
  | "apache_drill"
  | "pydrill"
  | "yugabyte"
  | "yugabytedb"
  | "opensearch"
  | "opensearch_sql"
  | "neo4j"
  | "cypher"
  | "neo4j_sql"
  | "kdb"
  | "kdb+"
  | "pykx"
  | "q"
  | "clickhouse_native"
  | "ch_native"
  | "clickhouse_tcp"
  | "postgresql"
  | "sqlserver"
  | "timescale"
  | "cockroach"
  | "partiql"
  | "apache_cassandra"
  | "spark_sql"
  | "pyspark"
  | "firebird"
  | "firebirdsql"
  | "monetdb"
  | "monet"
  | "h2"
  | "h2db"
  | "derby"
  | "apache_derby"
  | "sybase"
  | "sap_ase"
  | "ase"
  | "informix"
  | "ibm_informix";

export interface VisualQueryBuilderRef {
  /** Gets the active serialized QuerySpec AST */
  /** Current spec, or `null` while raw-SQL mode holds SQL that cannot be mapped to a spec. */
  getSpec(): QuerySpec | null;
  /** Gets the current compiled or raw SQL string */
  getSql(): string;
  /** Sets and synchronizes a new QuerySpec AST into the visual state */
  setSpec(spec: QuerySpec): void;
  /** Resets visual canvas back to initial state */
  reset(): void;
  /** Imperatively triggers query execution */
  execute(): Promise<QueryResultData | void>;
  /** Undoes last state change */
  undo(): void;
  /** Redoes previously undone state change */
  redo(): void;
  /** Whether an undo action is available */
  canUndo(): boolean;
  /** Whether a redo action is available */
  canRedo(): boolean;
}

// ==========================================
// Slotted Styling & Compound Component Types
// ==========================================

export type QueryBuilderSlot =
  | "root"
  | "header"
  | "title"
  | "tabs"
  | "tab"
  | "tabActive"
  | "canvas"
  | "canvasTables"
  | "canvasEmpty"
  | "tableCard"
  | "tableCardHeader"
  | "tableCardTitle"
  | "tableCardBadge"
  | "columnList"
  | "columnItem"
  | "columnCheckbox"
  | "columnName"
  | "columnType"
  | "columns"
  | "columnsHeader"
  | "projectionItem"
  | "projectionSelect"
  | "projectionAlias"
  | "joins"
  | "joinItem"
  | "filters"
  | "filterItem"
  | "filterAddButton"
  | "sorts"
  | "sortItem"
  | "sortAddButton"
  | "sqlEditor"
  | "sqlTextarea"
  | "sqlSyncBadge"
  | "results"
  | "resultsHeader"
  | "resultsTable"
  | "resultsRow"
  | "resultsCell"
  | "resultsEmpty"
  | "resultsLoading";

export type QueryBuilderClassNames = Partial<Record<QueryBuilderSlot, string>>;

// ==========================================
// Feature Flags & Engine Capabilities Types
// ==========================================

export type FeatureTier = "standard" | "advanced" | "disabled";

export type FeatureKey =
  | "projections"
  | "filters"
  | "sorts"
  | "joins"
  | "distinct_limit"
  | "visual_chart"
  | "ctes"
  | "window_functions"
  | "analytical_grouping"
  | "vector_search"
  | "raw_sql"
  | "query_plan"
  | "calculated_fields"
  | "schema_tools";

export type FeatureConfig = Partial<Record<FeatureKey, FeatureTier | boolean>>;

export type FeaturePreset = "simple" | "standard" | "power_user" | "all";

export type ResolvedFeatureMap = Record<FeatureKey, FeatureTier>;

export interface VisualQueryBuilderProps<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition> {
  schema?: SchemaSnapshot | Schema | TableSchema[] | null;
  presets?: SqlPreset[];
  initialTable?: SchemaTableNames<Schema>;
  dialect?: SqlDialect;
  value?: QuerySpec<Schema>;
  /** `spec` is `null` when raw-SQL mode holds SQL that cannot be mapped to a QuerySpec. */
  onChange?: (spec: QuerySpec<Schema> | null, sql: string) => void;
  initialSpec?: QuerySpec<Schema>;
  client?: import("./client").QueryBuilderClient;
  onExecuteQuery?: ExecuteQueryHandler;
  onSaveQuery?: {
    bivarianceHack(title: string, sql: string, spec: QuerySpec | Record<string, unknown>): void;
  }["bivarianceHack"];
  theme?: "dark" | "light" | "auto";
  readOnly?: boolean;
  unstyled?: boolean;
  mode?: "styled" | "unstyled";
  className?: string;
  classNames?: QueryBuilderClassNames;
  customOperators?: Record<string, CustomFilterOperator>;
  fieldRenderers?: Record<string, CustomFieldRenderer>;
  cellRenderers?: Record<string, CellRenderer>;
  ai?: import("./ai/types").ByoAiConfig;

  // Advanced Feature Controls
  features?: FeatureConfig;
  featurePreset?: FeaturePreset;
  allowToggleAdvanced?: boolean;
  advancedMode?: boolean;
  defaultAdvancedMode?: boolean;
  onAdvancedModeChange?: (isAdvanced: boolean) => void;
  storageKey?: string | null;
}

// ==========================================
// Charting & BI Visualizer Types
// ==========================================

export type ChartType = "bar" | "line" | "pie" | "area" | "scatter" | "donut" | "kpi";

export type AggregationMode = "SUM" | "COUNT" | "AVG" | "MIN" | "MAX" | "NONE";

export interface QueryChartPreviewProps {
  results: QueryResultData | null;
  defaultChartType?: ChartType;
  defaultCategoryCol?: string;
  defaultMetricCol?: string;
  defaultAggregation?: AggregationMode;
  className?: string;
  style?: React.CSSProperties;
  unstyled?: boolean;
}

export interface ChartDataPoint {
  category: string;
  value: number;
  count: number;
  rawRows?: Record<string, unknown>[];
}

export interface BiChartAdapterContext {
  results: QueryResultData | null;
  chartType: ChartType;
  effectiveCategory: string;
  effectiveMetric: string;
  points: ChartDataPoint[];
  stacked?: boolean;
}

export interface BiChartVisualizerProps extends QueryChartPreviewProps {
  chartType?: ChartType;
  onChartTypeChange?: (type: ChartType) => void;
  stacked?: boolean;
  onStackedChange?: (stacked: boolean) => void;
  adapter?: "builtin" | "echarts" | "vega-lite" | ((context: BiChartAdapterContext) => React.ReactNode);
  kpiTitle?: string;
  kpiSubtitle?: string;
}

export type ExportFormat = "csv" | "json" | "parquet" | "excel" | "xlsx" | "arrow" | "jsonl" | "ndjson";

// ==========================================
// Template Management Types
// ==========================================

export interface QueryTemplate {
  id: string;
  title: string;
  description?: string;
  category?: string;
  sql: string;
  spec?: Record<string, unknown>;
  createdAt: string;
  updatedAt?: string;
  isDefault?: boolean;
}

export interface QueryTemplateManagerProps {
  isOpen: boolean;
  onClose: () => void;
  currentSql?: string;
  currentSpec?: Record<string, unknown>;
  onLoadTemplate: (template: QueryTemplate) => void;
  onSaveTemplate?: (template: QueryTemplate) => void;
  onDeleteTemplate?: (templateId: string) => void;
  initialTemplates?: QueryTemplate[];
  defaultMode?: "library" | "save";
  unstyled?: boolean;
}

// ==========================================
// Playground Types
// ==========================================

export interface QueryPlaygroundProps<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition> {
  schema?: SchemaSnapshot | Schema | TableSchema[] | null;
  initialSpec?: QuerySpec<Schema> | Record<string, unknown>;
  initialTable?: string;
  dialect?: SqlDialect;
  unstyled?: boolean;
  className?: string;
  style?: React.CSSProperties;
  onSpecChange?: (spec: QuerySpec<Schema>) => void;
  onSqlChange?: (sql: string) => void;
  readOnly?: boolean;
}

// ==========================================
// DuckDB-Wasm Client OLAP & Local Ingest Types
// ==========================================

export interface DuckDBTableMeta {
  name: string;
  rowCount: number;
  columns: { name: string; type: string }[];
  fileSource?: string;
  sourceType: "csv" | "tsv" | "parquet" | "json" | "query_cache";
}

export interface DuckDBQueryResult {
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
  executionTimeMs: number;
}

export interface DuckDBIngestOptions {
  delimiter?: string;
  header?: boolean;
  inferTypes?: boolean;
  sampleRows?: number;
}

export interface ClientOlapEngine {
  isReady: boolean;
  isLoading: boolean;
  error: Error | null;
  tables: Record<string, DuckDBTableMeta>;
  activeTable?: string;
  query(sql: string): Promise<DuckDBQueryResult>;
  ingestCsv(tableName: string, csvContent: string, options?: DuckDBIngestOptions): Promise<DuckDBTableMeta>;
  ingestJson(tableName: string, rows: Record<string, unknown>[], options?: DuckDBIngestOptions): Promise<DuckDBTableMeta>;
  ingestParquet(tableName: string, buffer: Uint8Array, options?: DuckDBIngestOptions): Promise<DuckDBTableMeta>;
  registerBackendResults(tableName: string, rows: Record<string, unknown>[]): Promise<DuckDBTableMeta>;
  dropTable(tableName: string): Promise<void>;
  clear(): Promise<void>;
  getSchemaSnapshot(): SchemaSnapshot;
}

// ==========================================
// Phase 4: Multi-Tile Dashboard Workbench Types
// ==========================================

export type DashboardTileType = "chart" | "kpi" | "pivot" | "table";

export interface DashboardTileLayout {
  x?: number;
  y?: number;
  w: number; // Column span (1..4)
  h: number; // Row span (1..2)
}

export interface KpiConfig {
  title?: string;
  subtitle?: string;
  valueField?: string;
  deltaPercentage?: number;
  statusColor?: string;
}

export interface PivotConfig {
  rowDimensions: string[];
  columnDimensions: string[];
  valueMetrics: { field: string; agg: "sum" | "avg" | "count" | "min" | "max" }[];
}

export interface GlobalFilter {
  field: string;
  operator: string;
  value: unknown;
}

export interface CrossFilterState {
  sourceTileId: string;
  field: string;
  value: unknown;
}

export interface DashboardTile {
  id: string;
  title: string;
  description?: string;
  type: DashboardTileType;
  querySpec?: QuerySpec;
  sql?: string;
  cachedRows?: Record<string, unknown>[];
  layout: DashboardTileLayout;
  chartType?: ChartType;
  kpiConfig?: KpiConfig;
  pivotConfig?: PivotConfig;
}

export interface DashboardState {
  id: string;
  title: string;
  tiles: DashboardTile[];
  globalFilters: GlobalFilter[];
  crossFilter: CrossFilterState | null;
}

// ==========================================
// Phase 5: AI Cost & Performance Advisor Types
// ==========================================

export interface CloudCostEstimate {
  bytesScannedEstimated: number;
  dollarCostEstimated: number;
  creditsEstimated?: number;
  pricingTier: string;
  isCached?: boolean;
}

export interface IndexRecommendation {
  id: string;
  table: string;
  columns: string[];
  indexName: string;
  ddl: string;
  rationale: string;
  estimatedImpact: "high" | "medium" | "low";
}

export interface PerformanceAdvisorInsight {
  type: "cost" | "warning" | "index" | "optimization";
  severity: "info" | "warning" | "critical";
  title: string;
  message: string;
  recommendation?: IndexRecommendation;
  costEstimate?: CloudCostEstimate;
}


