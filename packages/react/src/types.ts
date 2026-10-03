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

export interface VisualJoin {
  id: string;
  type: "LEFT JOIN" | "INNER JOIN" | "RIGHT JOIN";
  left_table?: string;
  table: string;
  left_col: string;
  right_col: string;
}

export interface VisualFilter {
  id: string;
  combiner?: "AND" | "OR";
  parenOpen?: string;
  tablePrefix?: string;
  column: string;
  operator:
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
  value: string;
  parenClose?: string;
}

export interface VisualSort {
  id: string;
  tablePrefix?: string;
  column: string;
  direction: "ASC" | "DESC";
}

export interface VisualColumnSelect {
  table: string;
  name: string;
  aggregate?: "" | "COUNT" | "SUM" | "AVG" | "MIN" | "MAX";
  alias?: string;
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
  | "presto";

export interface VisualQueryBuilderProps {
  schema?: SchemaSnapshot | null;
  presets?: SqlPreset[];
  initialTable?: string;
  dialect?: SqlDialect;
  onExecuteQuery?: (sql: string, spec?: Record<string, unknown>) => Promise<QueryResultData> | void;
  onSaveQuery?: (title: string, sql: string, spec: Record<string, unknown>) => void;
  theme?: "dark" | "light" | "auto";
  readOnly?: boolean;
}
