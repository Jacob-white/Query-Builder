/**
 * Semantic Metrics & Modeling Layer Adapter for React SDK.
 * ========================================================
 * Provides declarative parsing, validation, and SQL expansion for metrics,
 * virtual dimensions, and time-grain temporal bucketing.
 */

import type {
  DimensionDefinition,
  MetricDefinition,
  MetricFilter,
  SemanticModel,
  TableMeta,
  TimeGrain,
} from "../types";

export const SUPPORTED_TIME_GRAINS: TimeGrain[] = [
  "second",
  "minute",
  "hour",
  "day",
  "week",
  "month",
  "quarter",
  "year",
];

export const SUPPORTED_AGGREGATIONS = [
  "sum",
  "avg",
  "count",
  "count_distinct",
  "min",
  "max",
  "custom",
] as const;

export function formatMetricFilterSql(filter: MetricFilter, _dialect: string = "postgres"): string {
  const field = filter.field;
  const op = (filter.operator || "eq").toLowerCase();
  const val = filter.value;

  if (op === "eq" || op === "=") {
    if (val === null || val === undefined) return `${field} IS NULL`;
    const valStr = typeof val === "string" ? `'${val}'` : String(val);
    return `${field} = ${valStr}`;
  } else if (op === "neq" || op === "!=" || op === "<>") {
    if (val === null || val === undefined) return `${field} IS NOT NULL`;
    const valStr = typeof val === "string" ? `'${val}'` : String(val);
    return `${field} <> ${valStr}`;
  } else if (op === "gt" || op === ">") {
    return `${field} > ${val}`;
  } else if (op === "gte" || op === ">=") {
    return `${field} >= ${val}`;
  } else if (op === "lt" || op === "<") {
    return `${field} < ${val}`;
  } else if (op === "lte" || op === "<=") {
    return `${field} <= ${val}`;
  } else if (op === "in") {
    if (Array.isArray(val)) {
      const items = val.map((v) => (typeof v === "string" ? `'${v}'` : String(v))).join(", ");
      return `${field} IN (${items})`;
    }
    return `${field} IN (${val})`;
  } else if (op === "not_in" || op === "not in") {
    if (Array.isArray(val)) {
      const items = val.map((v) => (typeof v === "string" ? `'${v}'` : String(v))).join(", ");
      return `${field} NOT IN (${items})`;
    }
    return `${field} NOT IN (${val})`;
  } else if (op === "is_null") {
    return `${field} IS NULL`;
  } else if (op === "is_not_null") {
    return `${field} IS NOT NULL`;
  }
  const valStr = typeof val === "string" ? `'${val}'` : String(val);
  return `${field} = ${valStr}`;
}

export function expandMetricSql(metric: MetricDefinition, dialect: string = "postgres"): string {
  const expr = (metric.sqlExpression || "").trim();
  const agg = (metric.aggregation || "sum").toLowerCase();
  const d = (dialect || "postgres").toLowerCase();

  const filterSqls = (metric.filters || []).map((f) => formatMetricFilterSql(f, d));
  const combinedFilter = filterSqls.length > 0 ? filterSqls.join(" AND ") : null;

  if (agg === "custom") {
    if (combinedFilter) {
      return `CASE WHEN ${combinedFilter} THEN (${expr}) ELSE NULL END`;
    }
    return `(${expr})`;
  }

  const supportsFilterClause = ["postgres", "postgresql", "duckdb", "sqlite", "cockroach", "cockroachdb"].includes(d);

  if (agg === "count_distinct") {
    if (combinedFilter) {
      if (supportsFilterClause) {
        return `COUNT(DISTINCT ${expr}) FILTER (WHERE ${combinedFilter})`;
      }
      return `COUNT(DISTINCT CASE WHEN ${combinedFilter} THEN ${expr} ELSE NULL END)`;
    }
    return `COUNT(DISTINCT ${expr})`;
  }

  const func = agg === "avg" ? "AVG" : agg.toUpperCase();

  if (combinedFilter) {
    if (supportsFilterClause) {
      return `${func}(${expr}) FILTER (WHERE ${combinedFilter})`;
    }
    return `${func}(CASE WHEN ${combinedFilter} THEN ${expr} ELSE NULL END)`;
  }

  return `${func}(${expr})`;
}

export function expandTimeGrainSql(
  columnOrExpr: string,
  grain: TimeGrain,
  dialect: string = "postgres"
): string {
  const g = grain.toLowerCase();
  const expr = (columnOrExpr || "").trim();
  const d = (dialect || "postgres").toLowerCase();

  if (["postgres", "postgresql", "duckdb", "redshift", "snowflake"].includes(d)) {
    return `DATE_TRUNC('${g}', ${expr})`;
  } else if (d === "bigquery") {
    return `DATE_TRUNC(${expr}, ${g.toUpperCase()})`;
  } else if (d === "sqlite") {
    const sqliteMap: Record<string, string> = {
      second: "%Y-%m-%d %H:%M:%S",
      minute: "%Y-%m-%d %H:%M:00",
      hour: "%Y-%m-%d %H:00:00",
      day: "%Y-%m-%d",
      week: "%Y-%W",
      month: "%Y-%m-01",
      quarter: "%Y-m",
      year: "%Y-01-01",
    };
    const fmt = sqliteMap[g] || "%Y-%m-%d";
    return `STRFTIME('${fmt}', ${expr})`;
  } else if (d === "mysql" || d === "mariadb") {
    const mysqlMap: Record<string, string> = {
      second: "%Y-%m-%d %H:%i:%s",
      minute: "%Y-%m-%d %H:%i:00",
      hour: "%Y-%m-%d %H:00:00",
      day: "%Y-%m-%d",
      week: "%Y-%u",
      month: "%Y-%m-01",
      quarter: "%Y-%q",
      year: "%Y-01-01",
    };
    const fmt = mysqlMap[g] || "%Y-%m-%d";
    return `DATE_FORMAT(${expr}, '${fmt}')`;
  } else if (d === "mssql" || d === "sqlserver") {
    return `DATETRUNC(${g}, ${expr})`;
  } else if (d === "oracle") {
    const oracleMap: Record<string, string> = {
      day: "DD",
      week: "IW",
      month: "MM",
      quarter: "Q",
      year: "YYYY",
      hour: "HH",
      minute: "MI",
      second: "SS",
    };
    const fmt = oracleMap[g] || "DD";
    return `TRUNC(${expr}, '${fmt}')`;
  }
  return `DATE_TRUNC('${g}', ${expr})`;
}

/** Loose raw JSON shapes accepted by parseSemanticModelsJson (camelCase / snake_case aliases). */
interface RawSemanticFilter {
  field?: string;
  column?: string;
  operator?: string;
  op?: string;
  value?: unknown;
}

interface RawSemanticDimension {
  name: string;
  title?: string;
  description?: string;
  sqlExpression?: string;
  sql_expression?: string;
  sql?: string;
  dataType?: string;
  data_type?: string;
  type?: string;
  timeGrains?: TimeGrain[];
  time_grains?: TimeGrain[];
  table?: string;
}

interface RawSemanticMetric {
  name: string;
  title?: string;
  description?: string;
  sqlExpression?: string;
  sql_expression?: string;
  sql?: string;
  aggregation?: MetricDefinition["aggregation"];
  type?: MetricDefinition["aggregation"];
  format?: MetricDefinition["format"];
  filters?: RawSemanticFilter[];
  table?: string;
}

interface RawSemanticModel {
  name?: string;
  model?: string;
  tableName?: string;
  table_name?: string;
  table?: string;
  description?: string;
  primaryKey?: string;
  primary_key?: string;
  pk?: string;
  defaultTimeDimension?: string;
  default_time_dimension?: string;
  dimensions?: RawSemanticDimension[];
  metrics?: RawSemanticMetric[];
  models?: RawSemanticModel[];
  semantic_models?: RawSemanticModel[];
}

export function parseSemanticModelsJson(jsonContent: string): SemanticModel[] {
  const parsed: RawSemanticModel | RawSemanticModel[] = JSON.parse(jsonContent);
  const items: RawSemanticModel[] = Array.isArray(parsed)
    ? parsed
    : parsed.models || parsed.semantic_models || [parsed];

  return items.map((m): SemanticModel => ({
    name: m.name || m.model || "unnamed_model",
    tableName: (m.tableName || m.table_name || m.table || m.name) as string,
    description: m.description,
    primaryKey: m.primaryKey || m.primary_key || m.pk,
    defaultTimeDimension: m.defaultTimeDimension || m.default_time_dimension,
    dimensions: (m.dimensions || []).map((d): DimensionDefinition => ({
      name: d.name,
      title: d.title || d.name,
      description: d.description,
      sqlExpression: d.sqlExpression || d.sql_expression || d.sql || d.name,
      dataType: d.dataType || d.data_type || d.type || "string",
      timeGrains: d.timeGrains || d.time_grains || [],
      table: d.table,
    })),
    metrics: (m.metrics || []).map((metric): MetricDefinition => ({
      name: metric.name,
      title: metric.title || metric.name,
      description: metric.description,
      sqlExpression: (metric.sqlExpression || metric.sql_expression || metric.sql) as string,
      aggregation: metric.aggregation || metric.type || "sum",
      format: metric.format || "number",
      filters: (metric.filters || []).map((f): MetricFilter => ({
        field: (f.field || f.column) as string,
        operator: f.operator || f.op || "eq",
        value: f.value,
      })),
      table: metric.table,
    })),
  }));
}

export function attachSemanticModelsToTables(
  tables: Record<string, TableMeta>,
  models: SemanticModel[]
): Record<string, TableMeta> {
  const updated = { ...tables };
  for (const model of models) {
    const targetKey = Object.keys(updated).find(
      (k) => k === model.tableName || k.endsWith(`.${model.tableName}`)
    );
    if (targetKey && updated[targetKey]) {
      updated[targetKey] = {
        ...updated[targetKey],
        metrics: model.metrics,
        dimensions: model.dimensions,
      };
    }
  }
  return updated;
}
