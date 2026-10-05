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
    ? T extends Record<string, any>
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
    ? C extends Record<string, any>
      ? keyof C & string
      : C extends Array<{ name: infer ColName extends string }>
        ? ColName
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

export interface VisualJoin<Schema = any> {
  id: string;
  type: "LEFT JOIN" | "INNER JOIN" | "RIGHT JOIN" | "FULL JOIN";
  left_table?: SchemaTableNames<Schema>;
  table: SchemaTableNames<Schema>;
  left_col: string;
  right_col: string;
}

export interface VisualFilter<Schema = any> {
  id: string;
  combiner?: "AND" | "OR";
  parenOpen?: string;
  tablePrefix?: SchemaTableNames<Schema>;
  column: SchemaColumnNames<Schema, any> | string;
  operator: FilterOperator;
  value: string | number | boolean;
  parenClose?: string;
}

export interface VisualSort<Schema = any> {
  id: string;
  tablePrefix?: SchemaTableNames<Schema>;
  column: SchemaColumnNames<Schema, any> | string;
  direction: "ASC" | "DESC";
}

export interface VisualColumnSelect<Schema = any> {
  table: SchemaTableNames<Schema>;
  name: SchemaColumnNames<Schema, any> | string;
  aggregate?: "" | "COUNT" | "SUM" | "AVG" | "MIN" | "MAX";
  alias?: string;
}

export interface QuerySpec<Schema = any> {
  table: SchemaTableNames<Schema>;
  columns: (string | { column: string; agg?: string; alias?: string })[];
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
    value: string | number | boolean;
    tablePrefix?: SchemaTableNames<Schema>;
  }[];
  filter_join: "AND" | "OR";
  order_by: {
    column: string;
    direction: "ASC" | "DESC";
    tablePrefix?: SchemaTableNames<Schema>;
  }[];
  distinct: boolean;
  limit: number;
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

export interface VisualQueryBuilderProps<Schema extends DatabaseSchemaDefinition = any> {
  schema?: SchemaSnapshot | Schema | TableSchema[] | null;
  presets?: SqlPreset[];
  initialTable?: SchemaTableNames<Schema>;
  dialect?: SqlDialect;
  onExecuteQuery?: (sql: string, spec?: Record<string, unknown>) => Promise<QueryResultData> | void;
  onSaveQuery?: (title: string, sql: string, spec: Record<string, unknown>) => void;
  theme?: "dark" | "light" | "auto";
  readOnly?: boolean;
  unstyled?: boolean;
  mode?: "styled" | "unstyled";
  customOperators?: Record<string, CustomFilterOperator>;
  fieldRenderers?: Record<string, CustomFieldRenderer>;
  cellRenderers?: Record<string, (value: any, row: any, column: string) => React.ReactNode>;
}

// ==========================================
// Charting Types
// ==========================================

export type ChartType = "bar" | "line" | "pie";

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

export interface QueryPlaygroundProps<Schema extends DatabaseSchemaDefinition = any> {
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
