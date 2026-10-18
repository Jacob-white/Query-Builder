import { expandMetricSql, expandTimeGrainSql } from "../adapters/semantic";
import type {
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  SchemaSnapshot,
  SqlDialect,
  CustomFilterOperator,
  VectorSearchSpec,
  HybridSearchSpec,
  QueryPlanNode,
  CteSpec,
  WindowFunctionSpec,
  MetricDefinition,
  SemanticModel,
  QuerySpec,
  SerializedQuerySpec,
  CaseWhenSpec,
} from "../types";
import { narrowSerializedSpec, specToState } from "./queryStateTransitions";
import { normalizeCombiner, resolveFilterCombiners } from "./filterCombiners";

export interface CompiledVisualQuery {
  sql: string;
  spec: {
    table: string;
    columns: (
      | string
      | {
          column?: string;
          expression?: string;
          case_when?: CaseWhenSpec;
          agg?: string;
          alias?: string;
          time_grain?: string;
          metric?: string | MetricDefinition;
        }
    )[];
    joins: {
      table: string;
      type: string;
      on?: { left: string; right: string }[];
      left_table?: string;
      left_col?: string;
      right_col?: string;
    }[];
    filters: {
      column: string;
      op: string;
      value: string | number | boolean;
      tablePrefix?: string;
      combiner?: "AND" | "OR";
      parenOpen?: string;
      parenClose?: string;
    }[];
    filter_join: "AND" | "OR";
    order_by: { column: string; direction: "ASC" | "DESC"; tablePrefix?: string }[];
    distinct: boolean;
    limit: number;
    vector_search?: VectorSearchSpec;
    hybrid_search?: HybridSearchSpec;
    ctes?: CteSpec[];
    window_functions?: WindowFunctionSpec[];
    semantic_models?: SemanticModel[];
  };
}

const ALLOWED_OPERATORS = new Set([
  "=",
  "!=",
  ">",
  "<",
  ">=",
  "<=",
  "STARTS_WITH",
  "ENDS_WITH",
  "CONTAINS",
  "LIKE",
  "ILIKE",
  "IN",
  "NOT IN",
  "BETWEEN",
  "IS NULL",
  "IS NOT NULL",
  "RAW",
]);

const ALLOWED_AGGREGATES = new Set([
  "COUNT",
  "COUNT_DISTINCT",
  "SUM",
  "AVG",
  "MIN",
  "MAX",
]);

const ALLOWED_TIME_GRAINS = new Set([
  "second",
  "minute",
  "hour",
  "day",
  "week",
  "month",
  "quarter",
  "year",
]);

const IDENT_TOKEN_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const WINDOW_BOUND_RE = /^(UNBOUNDED\s+(PRECEDING|FOLLOWING)|CURRENT\s+ROW|\d+\s+(PRECEDING|FOLLOWING))$/i;
const WINDOW_EXCLUSIONS = new Set(["CURRENT ROW", "GROUP", "TIES", "NO OTHERS"]);

const safeDirection = (d: unknown): "ASC" | "DESC" =>
  typeof d === "string" && d.trim().toUpperCase() === "DESC" ? "DESC" : "ASC";

const sanitizeIdent = (s: string = "") => (s || "").replace(/[\x00-\x1f\x7f]/g, "");

const cleanTableName = (tbl: string) => {
  const clean = sanitizeIdent(tbl);
  const lastDot = clean.lastIndexOf(".");
  return lastDot !== -1 ? clean.substring(lastDot + 1) : clean;
};

export function quoteIdent(ident: string, dialect: SqlDialect = "postgres"): string {
  const clean = ident.replace(/[\x00-\x1f\x7f]/g, "");
  if (
    dialect === "mysql" ||
    dialect === "bigquery" ||
    dialect === "clickhouse" ||
    dialect === "databricks" ||
    dialect === "spanner" ||
    dialect === "tidb" ||
    dialect === "singlestore" ||
    dialect === "memsql" ||
    dialect === "couchbase" ||
    dialect === "n1ql" ||
    dialect === "starrocks" ||
    dialect === "oceanbase" ||
    dialect === "sparksql" ||
    dialect === "spark" ||
    dialect === "spark_sql" ||
    dialect === "pyspark" ||
    dialect === "chdb" ||
    dialect === "tdengine" ||
    dialect === "taos" ||
    dialect === "surrealdb" ||
    dialect === "surreal" ||
    dialect === "arangodb" ||
    dialect === "arango" ||
    dialect === "aql" ||
    dialect === "doris" ||
    dialect === "apache_doris" ||
    dialect === "pydoris" ||
    dialect === "impala" ||
    dialect === "apache_impala" ||
    dialect === "impyla" ||
    dialect === "hive" ||
    dialect === "apache_hive" ||
    dialect === "pyhive" ||
    dialect === "kyuubi" ||
    dialect === "apache_kyuubi" ||
    dialect === "drill" ||
    dialect === "apache_drill" ||
    dialect === "pydrill" ||
    dialect === "opensearch" ||
    dialect === "opensearch_sql" ||
    dialect === "neo4j" ||
    dialect === "cypher" ||
    dialect === "neo4j_sql" ||
    dialect === "clickhouse_native" ||
    dialect === "ch_native" ||
    dialect === "clickhouse_tcp"
  ) {
    return `\`${clean.replace(/`/g, "``")}\``;
  }
  if (
    dialect === "mssql" ||
    dialect === "sqlserver" ||
    dialect === "sybase" ||
    dialect === "sap_ase" ||
    dialect === "ase"
  ) {
    return `[${clean.replace(/\]/g, "]]")}]`;
  }
  return `"${clean.replace(/"/g, '""')}"`;
}

export function quoteAlias(alias: string, dialect: SqlDialect = "postgres"): string {
  return quoteIdent(alias, dialect);
}

export function formatIlike(
  colRef: string,
  valEscaped: string,
  dialect: SqlDialect = "postgres",
): string {
  if (dialect === "sqlite" || dialect === "d1" || dialect === "cloudflare_d1") {
    return `${colRef} LIKE ${valEscaped}`;
  }
  if (dialect === "neo4j" || dialect === "cypher" || dialect === "neo4j_sql") {
    return `toLower(${colRef}) CONTAINS toLower(${valEscaped})`;
  }
  if (dialect === "surrealdb" || dialect === "surreal") {
    return `string::lowercase(${colRef}) CONTAINS string::lowercase(${valEscaped})`;
  }
  if (
    dialect === "arangodb" ||
    dialect === "arango" ||
    dialect === "aql" ||
    dialect === "cosmosdb" ||
    dialect === "azure_cosmos"
  ) {
    return `CONTAINS(LOWER(${colRef}), LOWER(${valEscaped}))`;
  }
  if (
    dialect === "postgres" ||
    dialect === "postgresql" ||
    dialect === "snowflake" ||
    dialect === "duckdb" ||
    dialect === "clickhouse" ||
    dialect === "redshift" ||
    dialect === "polars" ||
    dialect === "questdb" ||
    dialect === "timescaledb" ||
    dialect === "timescale" ||
    dialect === "cockroachdb" ||
    dialect === "cockroach" ||
    dialect === "dremio" ||
    dialect === "firebolt" ||
    dialect === "neon" ||
    dialect === "supabase" ||
    dialect === "materialize" ||
    dialect === "mz" ||
    dialect === "risingwave" ||
    dialect === "rw" ||
    dialect === "cratedb" ||
    dialect === "crate" ||
    dialect === "influxdb" ||
    dialect === "iox" ||
    dialect === "influx" ||
    dialect === "alloydb" ||
    dialect === "vertica" ||
    dialect === "sparksql" ||
    dialect === "spark" ||
    dialect === "spark_sql" ||
    dialect === "pyspark" ||
    dialect === "chdb" ||
    dialect === "greptimedb" ||
    dialect === "greptime" ||
    dialect === "impala" ||
    dialect === "apache_impala" ||
    dialect === "impyla" ||
    dialect === "kyuubi" ||
    dialect === "apache_kyuubi" ||
    dialect === "yugabyte" ||
    dialect === "yugabytedb" ||
    dialect === "starrocks" ||
    dialect === "doris" ||
    dialect === "apache_doris" ||
    dialect === "pydoris" ||
    dialect === "drill" ||
    dialect === "apache_drill" ||
    dialect === "pydrill" ||
    dialect === "clickhouse_native" ||
    dialect === "ch_native" ||
    dialect === "clickhouse_tcp"
  ) {
    return `${colRef} ILIKE ${valEscaped}`;
  }
  return `LOWER(${colRef}) LIKE LOWER(${valEscaped})`;
}

export function formatLimit(limit: number, dialect: SqlDialect = "postgres"): string {
  if (
    dialect === "mssql" ||
    dialect === "sqlserver" ||
    dialect === "oracle" ||
    dialect === "teradata" ||
    dialect === "db2" ||
    dialect === "ibm_db2" ||
    dialect === "derby" ||
    dialect === "apache_derby" ||
    dialect === "sybase" ||
    dialect === "sap_ase" ||
    dialect === "ase"
  ) {
    return `OFFSET 0 ROWS FETCH NEXT ${limit} ROWS ONLY;`;
  }
  if (
    dialect === "trino" ||
    dialect === "presto" ||
    dialect === "prestodb" ||
    dialect === "cosmosdb" ||
    dialect === "azure_cosmos"
  ) {
    return `OFFSET 0 LIMIT ${limit};`;
  }
  if (dialect === "surrealdb" || dialect === "surreal") {
    return `LIMIT ${limit} START 0;`;
  }
  if (dialect === "arangodb" || dialect === "arango" || dialect === "aql") {
    return `LIMIT 0, ${limit};`;
  }
  if (dialect === "neo4j" || dialect === "cypher" || dialect === "neo4j_sql") {
    return `SKIP 0 LIMIT ${limit};`;
  }
  if (dialect === "informix" || dialect === "ibm_informix") {
    return `SKIP 0 FIRST ${limit};`;
  }
  if (dialect === "firebird" || dialect === "firebirdsql") {
    return `ROWS ${limit};`;
  }
  return `LIMIT ${limit};`;
}

function getVectorDistanceOperator(metric?: string): string {
  const m = (metric || "cosine").toLowerCase();
  if (m === "l2" || m === "euclidean") return "<->";
  if (m === "inner_product" || m === "dot_product") return "<#>";
  return "<=>";
}

function compileCaseWhenExpr(
  cw: CaseWhenSpec,
  defaultTable: string,
  dialect: SqlDialect,
): string {
  const branchesSql = (cw.branches || [])
    .map((b) => {
      const bTbl = cleanTableName(b.condition.tablePrefix || defaultTable);
      const bCol = sanitizeIdent(b.condition.column);
      const bColRef = `${quoteIdent(bTbl, dialect)}.${quoteIdent(bCol, dialect)}`;
      const op = (b.condition.op || "=").toUpperCase();
      let condSql = "";
      if (op === "IS NULL" || op === "IS NOT NULL") {
        condSql = `${bColRef} ${op}`;
      } else {
        const rawVal = b.condition.value;
        const valSql =
          typeof rawVal === "number" && Number.isFinite(rawVal)
            ? String(rawVal)
            : rawVal !== null &&
                rawVal !== undefined &&
                !isNaN(Number(rawVal)) &&
                String(rawVal).trim() !== ""
              ? String(Number(rawVal))
              : `'${String(rawVal ?? "").replace(/'/g, "''")}'`;
        condSql = `${bColRef} ${op} ${valSql}`;
      }
      const thenSql = b.then_column
        ? quoteIdent(sanitizeIdent(b.then_column), dialect)
        : typeof b.then_value === "number" && Number.isFinite(b.then_value)
          ? String(b.then_value)
          : `'${String(b.then_value ?? "").replace(/'/g, "''")}'`;
      return `WHEN ${condSql} THEN ${thenSql}`;
    })
    .join(" ");
  let elseSql = "";
  if (cw.else_column) {
    elseSql = ` ELSE ${quoteIdent(sanitizeIdent(cw.else_column), dialect)}`;
  } else if (cw.else_value !== undefined && cw.else_value !== null && cw.else_value !== "") {
    elseSql =
      typeof cw.else_value === "number" && Number.isFinite(cw.else_value)
        ? ` ELSE ${cw.else_value}`
        : ` ELSE '${String(cw.else_value).replace(/'/g, "''")}'`;
  }
  return `CASE ${branchesSql}${elseSql} END`;
}

export function compileVisualState(
  primaryTable: string,
  selectedColumns: Record<string, VisualColumnSelect>,
  orderedProjectionKeys: string[],
  joins: VisualJoin[],
  filters: VisualFilter[],
  sorts: VisualSort[],
  isDistinct: boolean = false,
  limit?: number,
  schemaData?: SchemaSnapshot | null,
  dialect: SqlDialect = "postgres",
  filterJoin: "AND" | "OR" = "AND",
  customOperators?: Record<string, CustomFilterOperator>,
  vectorSearch?: VectorSearchSpec | null,
  hybridSearch?: HybridSearchSpec | null,
  ctes?: CteSpec[] | null,
  windowFunctions?: WindowFunctionSpec[] | null,
  semanticModels?: SemanticModel[] | null,
): CompiledVisualQuery {
  const effectiveLimit = limit ?? vectorSearch?.top_k ?? hybridSearch?.top_k ?? 50;

  if (!primaryTable || typeof primaryTable !== "string") {
    return {
      sql: "",
      spec: {
        table: "",
        columns: [],
        joins: [],
        filters: [],
        filter_join: normalizeCombiner(filterJoin),
        order_by: [],
        distinct: false,
        limit: effectiveLimit,
        vector_search: vectorSearch || undefined,
        hybrid_search: hybridSearch || undefined,
        ctes: ctes && ctes.length > 0 ? ctes : undefined,
        window_functions: windowFunctions && windowFunctions.length > 0 ? windowFunctions : undefined,
        semantic_models: semanticModels && semanticModels.length > 0 ? semanticModels : undefined,
      },
    };
  }

  const cleanPrimary = cleanTableName(primaryTable);
  const safeProjectionKeys = (orderedProjectionKeys || []).slice(0, 100);

  const isItemMetric = (item: VisualColumnSelect): boolean => {
    if (Boolean(item.metric)) return true;
    const tbl = cleanTableName(item.table || cleanPrimary);
    const tblMeta = schemaData?.tables?.[tbl] || schemaData?.tables?.[item.table];
    if (tblMeta?.metrics?.some((m) => m.name === item.name)) return true;
    if (
      semanticModels?.some(
        (sm) =>
          (sm.tableName === tbl || sm.name === tbl || sm.tableName === item.table) &&
          sm.metrics?.some((m) => m.name === item.name),
      )
    ) {
      return true;
    }
    return false;
  };

  const hasAggregates = safeProjectionKeys.some((k) => {
    const it = selectedColumns[k];
    if (!it) return false;
    if (it.aggregate && ALLOWED_AGGREGATES.has(it.aggregate as string)) return true;
    if (isItemMetric(it)) return true;
    return false;
  });

  // Projections
  let selectClause = "*";
  const specColumns: CompiledVisualQuery["spec"]["columns"] = [];
  const usedAliases = new Set<string>();

  if (safeProjectionKeys.length > 0) {
    selectClause = safeProjectionKeys
      .map((compositeKey) => {
        const item = selectedColumns[compositeKey];
        if (!item) return "";
        const tableAlias = cleanTableName(item.table || cleanPrimary);
        const colName = sanitizeIdent(item.name);
        const colRef = `${quoteIdent(tableAlias, dialect)}.${quoteIdent(colName, dialect)}`;

        const aggUpper = (item.aggregate || "").toUpperCase();
        if (aggUpper && ALLOWED_AGGREGATES.has(aggUpper)) {
          let alias = sanitizeIdent(
            item.alias || `${aggUpper.toLowerCase()}_${item.name}`,
          );
          if (usedAliases.has(alias)) {
            let disambiguated = !item.alias
              ? sanitizeIdent(`${aggUpper.toLowerCase()}_${tableAlias}_${colName}`)
              : `${alias}_${tableAlias}`;
            if (usedAliases.has(disambiguated)) {
              let count = 2;
              while (usedAliases.has(`${alias}_${count}`)) {
                count++;
              }
              disambiguated = `${alias}_${count}`;
            }
            alias = disambiguated;
          }
          usedAliases.add(alias);

          specColumns.push({
            column: `${tableAlias}.${colName}`,
            agg: aggUpper.toLowerCase(),
            alias,
          });
          const aggSql =
            aggUpper === "COUNT_DISTINCT"
              ? `COUNT(DISTINCT ${colRef})`
              : `${aggUpper}(${colRef})`;
          return `${aggSql} AS ${quoteAlias(alias, dialect)}`;
        }

        if (item.caseWhen && Array.isArray(item.caseWhen.branches) && item.caseWhen.branches.length > 0) {
          let alias = sanitizeIdent(item.alias || item.caseWhen.alias || item.name || "case_col");
          if (usedAliases.has(alias)) {
            let disambiguated = `${alias}_${tableAlias}`;
            if (usedAliases.has(disambiguated)) {
              let count = 2;
              while (usedAliases.has(`${alias}_${count}`)) {
                count++;
              }
              disambiguated = `${alias}_${count}`;
            }
            alias = disambiguated;
          }
          usedAliases.add(alias);

          const caseExpr = compileCaseWhenExpr(item.caseWhen, tableAlias, dialect);
          specColumns.push({
            case_when: item.caseWhen,
            alias,
          });
          return `${caseExpr} AS ${quoteAlias(alias, dialect)}`;
        }

        if (item.rawExpression) {
          let alias = sanitizeIdent(item.alias || item.name || "expr");
          if (usedAliases.has(alias)) {
            let disambiguated = `${alias}_${tableAlias}`;
            if (usedAliases.has(disambiguated)) {
              let count = 2;
              while (usedAliases.has(`${alias}_${count}`)) {
                count++;
              }
              disambiguated = `${alias}_${count}`;
            }
            alias = disambiguated;
          }
          usedAliases.add(alias);

          specColumns.push({
            expression: item.rawExpression,
            alias,
          });
          return `${item.rawExpression} AS ${quoteAlias(alias, dialect)}`;
        }

        if (item.timeGrain && ALLOWED_TIME_GRAINS.has(String(item.timeGrain).toLowerCase())) {
          let alias = sanitizeIdent(item.alias || `${colName}_${item.timeGrain}`);
          if (usedAliases.has(alias)) {
            let disambiguated = `${alias}_${tableAlias}`;
            if (usedAliases.has(disambiguated)) {
              let count = 2;
              while (usedAliases.has(`${alias}_${count}`)) {
                count++;
              }
              disambiguated = `${alias}_${count}`;
            }
            alias = disambiguated;
          }
          usedAliases.add(alias);

          specColumns.push({
            column: `${tableAlias}.${colName}`,
            time_grain: item.timeGrain,
            alias,
          });
          const tgSql = expandTimeGrainSql(colRef, item.timeGrain, dialect);
          return `${tgSql} AS ${quoteAlias(alias, dialect)}`;
        }

        let metricDef: MetricDefinition | undefined;
        if (typeof item.metric === "object" && item.metric !== null) {
          metricDef = item.metric as MetricDefinition;
        } else {
          const metricName = typeof item.metric === "string" ? item.metric : item.name;
          const isExplicitMetric = Boolean(item.metric);
          const tblMeta = schemaData?.tables?.[tableAlias] || schemaData?.tables?.[item.table];
          const foundInTbl = tblMeta?.metrics?.find((m) => m.name === metricName || m.name === colName);
          if (foundInTbl) {
            metricDef = foundInTbl;
          } else if (semanticModels) {
            for (const sm of semanticModels) {
              if (sm.tableName === tableAlias || sm.name === tableAlias || sm.tableName === item.table) {
                const foundInSm = sm.metrics?.find((m) => m.name === metricName || m.name === colName);
                if (foundInSm) {
                  metricDef = foundInSm;
                  break;
                }
              }
            }
          }
          if (!metricDef && isExplicitMetric) {
            metricDef = {
              name: metricName,
              title: metricName,
              sqlExpression: colRef,
              aggregation: "sum",
            };
          }
        }

        if (metricDef) {
          let alias = sanitizeIdent(item.alias || metricDef.name || colName);
          if (usedAliases.has(alias)) {
            let disambiguated = `${alias}_${tableAlias}`;
            if (usedAliases.has(disambiguated)) {
              let count = 2;
              while (usedAliases.has(`${alias}_${count}`)) {
                count++;
              }
              disambiguated = `${alias}_${count}`;
            }
            alias = disambiguated;
          }
          usedAliases.add(alias);

          specColumns.push({
            column: `${tableAlias}.${colName}`,
            metric: metricDef.name,
            alias,
          });
          const metricSql = expandMetricSql(metricDef, dialect);
          return `${metricSql} AS ${quoteAlias(alias, dialect)}`;
        }

        if (item.alias) {
          let alias = sanitizeIdent(item.alias);
          if (usedAliases.has(alias)) {
            let disambiguated = `${alias}_${tableAlias}`;
            if (usedAliases.has(disambiguated)) {
              let count = 2;
              while (usedAliases.has(`${alias}_${count}`)) {
                count++;
              }
              disambiguated = `${alias}_${count}`;
            }
            alias = disambiguated;
          }
          usedAliases.add(alias);

          specColumns.push({
            column: `${tableAlias}.${colName}`,
            alias,
          });
          return `${colRef} AS ${quoteAlias(alias, dialect)}`;
        }

        specColumns.push(`${tableAlias}.${colName}`);
        return colRef;
      })
      .filter(Boolean)
      .join(", ");
  } else {
    specColumns.push("*");
  }

  if (isDistinct && !hasAggregates) {
    selectClause = `DISTINCT ${selectClause}`;
  }

  const fromClause = `FROM ${quoteIdent(cleanPrimary, dialect)}`;

  // Joins
  const validJoinTypes = new Set([
    "LEFT JOIN",
    "INNER JOIN",
    "RIGHT JOIN",
    "FULL JOIN",
  ]);
  const specJoins: CompiledVisualQuery["spec"]["joins"] = [];
  const safeJoins = (joins || []).slice(0, 20);
  const joinClauses = safeJoins.map((j) => {
    const leftTbl = cleanTableName(j.left_table || cleanPrimary);
    const rightTbl = cleanTableName(j.table);
    const leftCol = sanitizeIdent(j.left_col);
    const rightCol = sanitizeIdent(j.right_col);
    const joinType = validJoinTypes.has(j.type) ? j.type : "LEFT JOIN";

    specJoins.push({
      table: rightTbl,
      type: joinType.replace(" JOIN", ""),
      left_table: leftTbl,
      left_col: leftCol,
      right_col: rightCol,
      on: [
        {
          left: `${leftTbl}.${leftCol}`,
          right: `${rightTbl}.${rightCol}`,
        },
      ],
    });

    return `${joinType} ${quoteIdent(rightTbl, dialect)} ON ${quoteIdent(leftTbl, dialect)}.${quoteIdent(leftCol, dialect)} = ${quoteIdent(rightTbl, dialect)}.${quoteIdent(rightCol, dialect)}`;
  });

  // Filters
  const activeFilters = (filters || [])
    .slice(0, 50)
    .filter(
      (f) =>
        f.column &&
        f.operator &&
        (ALLOWED_OPERATORS.has(f.operator) || Boolean(customOperators?.[f.operator])),
    );
  const specFilters: CompiledVisualQuery["spec"]["filters"] = [];
  let whereClause = "";
  let resolvedFilterJoin: "AND" | "OR" = normalizeCombiner(filterJoin);

  if (activeFilters.length > 0) {
    // Pass 1: build the SQL expression of every active filter.
    const built: { f: (typeof activeFilters)[number]; expr: string }[] = [];
    activeFilters.forEach((f) => {
      const tbl = cleanTableName(f.tablePrefix || cleanPrimary);
      const colName = sanitizeIdent(f.column);
      const colRef = `${quoteIdent(tbl, dialect)}.${quoteIdent(colName, dialect)}`;
      const valStr = String(f.value ?? "");
      let expr = "";

      const customOp = customOperators?.[f.operator];

      if (f.operator === "RAW") {
        expr = f.rawExpression || f.column;
      } else if (customOp?.formatSql) {
        expr = customOp.formatSql(colRef, f.value, dialect);
      } else if (customOp && customOp.hasValue === false) {
        expr = `${colRef} ${customOp.value}`;
      } else if (f.operator === "IS NULL" || f.operator === "IS NOT NULL") {
        expr = `${colRef} ${f.operator}`;
      } else if (f.operator === "STARTS_WITH") {
        const clean = valStr.replace(/'/g, "''");
        expr = formatIlike(colRef, `'${clean}%'`, dialect);
      } else if (f.operator === "ENDS_WITH") {
        const clean = valStr.replace(/'/g, "''");
        expr = formatIlike(colRef, `'%${clean}'`, dialect);
      } else if (f.operator === "CONTAINS") {
        const clean = valStr.replace(/'/g, "''");
        expr = formatIlike(colRef, `'%${clean}%'`, dialect);
      } else if (f.operator === "ILIKE") {
        const clean = valStr.replace(/'/g, "''");
        expr = formatIlike(colRef, `'${clean}'`, dialect);
      } else if (f.operator === "LIKE") {
        const clean = valStr.replace(/'/g, "''");
        if (dialect === "neo4j" || dialect === "cypher" || dialect === "neo4j_sql") {
          expr = `${colRef} CONTAINS '${clean}'`;
        } else {
          expr = `${colRef} LIKE '${clean}'`;
        }
      } else if (f.operator === "IN" || f.operator === "NOT IN") {
        const items = valStr
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
          .slice(0, 500)
          .map((s) =>
            !isNaN(Number(s)) && isFinite(Number(s)) && s !== ""
              ? s
              : `'${s.replace(/'/g, "''")}'`,
          );
        expr = `${colRef} ${f.operator} (${items.join(", ") || "NULL"})`;
      } else if (f.operator === "BETWEEN") {
        const bounds = valStr.includes(" AND ")
          ? valStr.split(" AND ")
          : valStr.split(",");
        if (bounds.length === 2) {
          const b0 = bounds[0].trim();
          const b1 = bounds[1].trim();
          const v0 =
            !isNaN(Number(b0)) && isFinite(Number(b0)) && b0 !== ""
              ? b0
              : `'${b0.replace(/'/g, "''")}'`;
          const v1 =
            !isNaN(Number(b1)) && isFinite(Number(b1)) && b1 !== ""
              ? b1
              : `'${b1.replace(/'/g, "''")}'`;
          expr = `${colRef} BETWEEN ${v0} AND ${v1}`;
        }
      } else {
        const isBool = typeof f.value === "boolean";
        const isNum =
          typeof f.value === "number"
            ? isFinite(f.value)
            : !isNaN(Number(f.value)) &&
              isFinite(Number(f.value)) &&
              valStr.trim() !== "";
        let valEscaped: string;
        if (isBool) {
          valEscaped = f.value ? "TRUE" : "FALSE";
        } else if (isNum) {
          valEscaped = String(f.value);
        } else {
          valEscaped = `'${valStr.replace(/'/g, "''")}'`;
        }
        expr = `${colRef} ${f.operator} ${valEscaped}`;
      }

      if (expr) {
        // Only grouping parentheses are allowed; anything else is dropped (no SQL injection).
        const open = (f.parenOpen || "").replace(/[^(]/g, "");
        const close = (f.parenClose || "").replace(/[^)]/g, "");
        built.push({ f, expr: `${open}${expr}${close}` });
      }
    });

    // Pass 2: resolve combiners ONCE from exactly the filters that are emitted, so the SQL, the
    // per-filter spec combiners and the aggregate `filter_join` always agree.
    const resolved = resolveFilterCombiners(
      built.map((b) => b.f),
      filterJoin,
    );
    resolvedFilterJoin = resolved.filterJoin;
    built.forEach(({ f }, i) => {
      const open = (f.parenOpen || "").replace(/[^(]/g, "");
      const close = (f.parenClose || "").replace(/[^)]/g, "");
      specFilters.push({
        column: sanitizeIdent(f.column),
        op: f.operator.toLowerCase().replace(" ", "_"),
        value: f.value,
        tablePrefix: cleanTableName(f.tablePrefix || cleanPrimary),
        // With any OR present every filter must state its combiner: a backend falling back to
        // `filter_join: "OR"` would otherwise turn explicit ANDs into ORs.
        ...(resolved.hasOr ? { combiner: resolved.combiners[i] } : {}),
        ...(open ? { parenOpen: open } : {}),
        ...(close ? { parenClose: close } : {}),
      });
    });

    if (built.length > 0) {
      let combined = built[0].expr;
      for (let i = 1; i < built.length; i++) {
        combined += ` ${resolved.combiners[i]} ${built[i].expr}`;
      }
      whereClause = `WHERE ${combined}`;
    }
  }

  // Sorts
  const activeSorts = (sorts || []).slice(0, 20).filter((s) => s.column);
  const specSorts: CompiledVisualQuery["spec"]["order_by"] = [];
  let orderClause = "";

  if (activeSorts.length > 0) {
    const aggregateAliases = new Set<string>();
    for (const key of safeProjectionKeys) {
      const item = selectedColumns[key];
      if (!item) continue;
      if (item.aggregate) {
        if (item.alias) {
          aggregateAliases.add(sanitizeIdent(item.alias));
        }
        aggregateAliases.add(
          sanitizeIdent(`${item.aggregate.toLowerCase()}_${item.name}`)
        );
      }
    }

    const sortParts = activeSorts.map((s) => {
      const colName = sanitizeIdent(s.column);
      const direction = s.direction === "DESC" ? "DESC" : "ASC";
      if (aggregateAliases.has(colName)) {
        specSorts.push({ column: colName, direction });
        return `${quoteAlias(colName, dialect)} ${direction}`;
      }
      const tbl = cleanTableName(s.tablePrefix || cleanPrimary);
      specSorts.push({ column: `${tbl}.${colName}`, direction, tablePrefix: tbl });
      return `${quoteIdent(tbl, dialect)}.${quoteIdent(colName, dialect)} ${direction}`;
    });
    orderClause = `ORDER BY ${sortParts.join(", ")}`;
  }

  // Vector Search SQL projection and ordering
  if (
    vectorSearch &&
    Array.isArray(vectorSearch.vector) &&
    vectorSearch.vector.length > 0
  ) {
    const vCol = sanitizeIdent(vectorSearch.column || "embedding");
    const vRef = `${quoteIdent(cleanPrimary, dialect)}.${quoteIdent(vCol, dialect)}`;
    const vecOp = getVectorDistanceOperator(vectorSearch.metric);
    const vecStr = `'[${vectorSearch.vector.map((n) => (Number.isFinite(Number(n)) ? Number(n) : 0)).join(",")}]'`;
    if (vectorSearch.include_distances) {
      const distExpr = `(${vRef} ${vecOp} ${vecStr}) AS "_distance"`;
      selectClause = selectClause === "*" ? `*, ${distExpr}` : `${selectClause}, ${distExpr}`;
    }
    if (!orderClause) {
      orderClause = `ORDER BY ${vRef} ${vecOp} ${vecStr} ASC`;
    }
  }

  // Hybrid Search SQL projection, text filtering, and ordering
  if (hybridSearch) {
    if (Array.isArray(hybridSearch.vector) && hybridSearch.vector.length > 0) {
      const vCol = sanitizeIdent(hybridSearch.vector_column || "embedding");
      const vRef = `${quoteIdent(cleanPrimary, dialect)}.${quoteIdent(vCol, dialect)}`;
      const vecOp = getVectorDistanceOperator(hybridSearch.metric);
      const vecStr = `'[${hybridSearch.vector.map((n) => (Number.isFinite(Number(n)) ? Number(n) : 0)).join(",")}]'`;
      if (hybridSearch.include_scores) {
        const distExpr = `(${vRef} ${vecOp} ${vecStr}) AS "_hybrid_distance"`;
        selectClause = selectClause === "*" ? `*, ${distExpr}` : `${selectClause}, ${distExpr}`;
      }
      if (!orderClause) {
        orderClause = `ORDER BY ${vRef} ${vecOp} ${vecStr} ASC`;
      }
    }
    if (
      hybridSearch.query_text &&
      Array.isArray(hybridSearch.text_columns) &&
      hybridSearch.text_columns.length > 0
    ) {
      const cleanQ = String(hybridSearch.query_text).replace(/'/g, "''");
      const textConds = hybridSearch.text_columns
        .map((tc) => sanitizeIdent(tc))
        .filter(Boolean)
        .map((tc) =>
          formatIlike(
            `${quoteIdent(cleanPrimary, dialect)}.${quoteIdent(tc, dialect)}`,
            `'%${cleanQ}%'`,
            dialect,
          ),
        );
      if (textConds.length > 0) {
        const textFilterSql =
          textConds.length === 1 ? textConds[0] : `(${textConds.join(" OR ")})`;
        whereClause = whereClause
          ? `${whereClause} AND ${textFilterSql}`
          : `WHERE ${textFilterSql}`;
      }
    }
  }

  // Window Functions
  if (windowFunctions && windowFunctions.length > 0) {
    const wfClauses = windowFunctions.map((wf) => {
      const fnName = IDENT_TOKEN_RE.test(wf.function) ? wf.function : "ROW_NUMBER";
      const args = wf.arguments?.length
        ? wf.arguments
            .map((a) =>
              typeof a === "number" && Number.isFinite(a)
                ? String(a)
                : /^[A-Za-z0-9_."*]+$/.test(String(a))
                  ? String(a)
                  : quoteIdent(String(a), dialect),
            )
            .join(", ")
        : wf.function === "COUNT"
          ? "*"
          : "";
      const part = wf.partition_by?.length ? `PARTITION BY ${wf.partition_by.map((c) => sanitizeIdent(c)).join(", ")}` : "";
      const ord = wf.order_by?.length
        ? `ORDER BY ${wf.order_by.map((o) => `${sanitizeIdent(o.column)} ${safeDirection(o.direction)}`).join(", ")}`
        : "";
      let frame = "";
      if (wf.frame) {
        const ft = String(wf.frame.frame_type || "ROWS").toUpperCase();
        const frameType = ft === "RANGE" || ft === "GROUPS" ? ft : "ROWS";
        const start = WINDOW_BOUND_RE.test(wf.frame.start || "") ? (wf.frame.start as string) : "UNBOUNDED PRECEDING";
        const end = WINDOW_BOUND_RE.test(wf.frame.end || "") ? (wf.frame.end as string) : "CURRENT ROW";
        frame = `${frameType} BETWEEN ${start} AND ${end}`;
        const excl = (wf.frame.exclusion || "").trim().toUpperCase().replace(/\s+/g, " ");
        if (WINDOW_EXCLUSIONS.has(excl)) frame += ` EXCLUDE ${excl}`;
      }
      const overTokens = [part, ord, frame].filter(Boolean);
      const overClause = `OVER (${overTokens.join(" ")})`;
      const aliasClause = wf.alias ? ` AS ${quoteIdent(wf.alias, dialect)}` : "";
      return `${fnName}(${args}) ${overClause}${aliasClause}`;
    });
    selectClause = selectClause === "*" ? wfClauses.join(", ") : `${selectClause}, ${wfClauses.join(", ")}`;
  }

  // Group By
  let groupClause = "";
  if (hasAggregates) {
    const nonAggCols = safeProjectionKeys
      .map((k) => selectedColumns[k])
      .filter((item): item is VisualColumnSelect =>
        Boolean(item && !item.aggregate && !isItemMetric(item)),
      )
      .map((item) => {
        const tbl = cleanTableName(item.table || cleanPrimary);
        const colName = sanitizeIdent(item.name);
        const colRef = `${quoteIdent(tbl, dialect)}.${quoteIdent(colName, dialect)}`;
        if (item.caseWhen && Array.isArray(item.caseWhen.branches) && item.caseWhen.branches.length > 0) {
          return compileCaseWhenExpr(item.caseWhen, tbl, dialect);
        }
        if (item.rawExpression) {
          return item.rawExpression;
        }
        if (item.timeGrain && ALLOWED_TIME_GRAINS.has(String(item.timeGrain).toLowerCase())) {
          return expandTimeGrainSql(colRef, item.timeGrain, dialect);
        }
        return colRef;
      });
    if (nonAggCols.length > 0) {
      groupClause = `GROUP BY ${nonAggCols.join(", ")}`;
    }
  }

  const queryParts = [`SELECT ${selectClause}`, fromClause];
  if (joinClauses.length > 0) queryParts.push(...joinClauses);
  if (whereClause) queryParts.push(whereClause);
  if (groupClause) queryParts.push(groupClause);
  if (orderClause) queryParts.push(orderClause);
  queryParts.push(formatLimit(effectiveLimit, dialect));

  let ctePrefix = "";
  if (ctes && ctes.length > 0) {
    const hasRecursive = ctes.some((c) => c.recursive);
    const withKw = hasRecursive ? "WITH RECURSIVE " : "WITH ";
    const compiledCteList = ctes.map((c) => {
      const innerSql = c.query?.sql || `SELECT * FROM ${quoteIdent(c.query?.table || "sub", dialect)}`;
      const cols = c.columns?.length ? ` (${c.columns.map((col) => quoteIdent(col, dialect)).join(", ")})` : "";
      const mat = c.materialized ? "MATERIALIZED " : "";
      return `${quoteIdent(c.name, dialect)}${cols} AS ${mat}(\n${innerSql}\n)`;
    });
    ctePrefix = `${withKw}${compiledCteList.join(", ")}\n`;
  }

  return {
    sql: `${ctePrefix}${queryParts.join("\n")}`,
    spec: {
      table: cleanPrimary,
      columns: specColumns,
      joins: specJoins,
      filters: specFilters,
      filter_join: resolvedFilterJoin,
      order_by: specSorts,
      distinct: isDistinct,
      limit: effectiveLimit,
      vector_search: vectorSearch || undefined,
      hybrid_search: hybridSearch || undefined,
      ctes: ctes && ctes.length > 0 ? ctes : undefined,
      window_functions: windowFunctions && windowFunctions.length > 0 ? windowFunctions : undefined,
      semantic_models: semanticModels && semanticModels.length > 0 ? semanticModels : undefined,
    },
  };
}

/**
 * Estimates a client-side QueryPlanNode hierarchy from a compiled QuerySpec.
 */
export function estimateClientPlan(spec: SerializedQuerySpec | null | undefined): QueryPlanNode {
  const table = spec?.table || "unknown";
  const limit = spec?.limit || 50;
  const joins = spec?.joins || [];
  const filters = spec?.filters || [];
  const isVector = Boolean(spec?.vector_search);
  const isHybrid = Boolean(spec?.hybrid_search);

  let scanNode: QueryPlanNode;
  if (isHybrid) {
    scanNode = {
      node_type: "Hybrid Search Merge",
      table,
      cost_estimate: 320,
      rows_estimated: Math.min(limit, 100),
      cost_percentage: 80,
      children: [
        {
          node_type: "Vector KNN Scan",
          table,
          cost_estimate: 180,
          rows_estimated: 100,
          cost_percentage: 45,
          warnings: [
            "Create an HNSW or IVFFlat vector index to accelerate nearest neighbor retrieval.",
          ],
        },
        {
          node_type: "Full-Text Scan",
          table,
          cost_estimate: 140,
          rows_estimated: 200,
          cost_percentage: 35,
        },
      ],
    };
  } else if (isVector) {
    scanNode = {
      node_type: "KNN Scan",
      table,
      cost_estimate: 280,
      rows_estimated: Math.min(limit, 100),
      cost_percentage: 80,
      warnings: [
        "Create an HNSW or IVFFlat vector index to accelerate nearest neighbor retrieval.",
      ],
    };
  } else if (filters.length > 0) {
    scanNode = {
      node_type: "Seq Scan",
      table,
      cost_estimate: 150,
      rows_estimated: 10000,
      cost_percentage: 75,
      warnings: [
        `Sequential table scan on '${table}' with 10,000 estimated rows. Consider adding an index on relevant filter columns.`,
      ],
    };
  } else {
    scanNode = {
      node_type: "Seq Scan",
      table,
      cost_estimate: 120,
      rows_estimated: 5000,
      cost_percentage: 70,
    };
  }

  let currentNode = scanNode;
  for (const j of joins) {
    const jTable = j?.table || "joined_table";
    currentNode = {
      node_type: `${j?.type || "LEFT"} Join`,
      cost_estimate: currentNode.cost_estimate! + 100,
      rows_estimated: currentNode.rows_estimated,
      cost_percentage: 85,
      children: [
        currentNode,
        {
          node_type: "Seq Scan",
          table: jTable,
          cost_estimate: 60,
          rows_estimated: 2000,
          cost_percentage: 15,
        },
      ],
    };
  }

  return {
    node_type: "Limit",
    cost_estimate: currentNode.cost_estimate! + 25,
    rows_estimated: limit,
    cost_percentage: 100,
    children: [
      {
        node_type: "Sort",
        cost_estimate: currentNode.cost_estimate! + 20,
        rows_estimated: currentNode.rows_estimated,
        cost_percentage: 95,
        children: [currentNode],
      },
    ],
  };
}

/**
 * Compiles a QuerySpec or partial spec directly to SQL string.
 */
export function compileSpecToSql(
  spec: Partial<QuerySpec> | SerializedQuerySpec,
  dialect: SqlDialect = "postgres",
  schemaData?: SchemaSnapshot | null,
): string {
  const looseSpec = narrowSerializedSpec(spec);
  const state = specToState(spec);
  const primaryTable = state.primaryTable || looseSpec.table || "";
  if (!primaryTable) return "";
  const selectedColumns = state.selectedColumns || {};
  const orderedProjectionKeys = state.orderedProjectionKeys || Object.keys(selectedColumns);
  const joins = state.joins || [];
  const filters = state.filters || [];
  const sorts = state.sorts || [];
  const isDistinct = state.isDistinct || false;
  const vectorSearch = state.vectorSearch || looseSpec.vector_search;
  const hybridSearch = state.hybridSearch || looseSpec.hybrid_search;
  const limit =
    typeof state.limit === "number"
      ? state.limit
      : (looseSpec.limit ?? vectorSearch?.top_k ?? hybridSearch?.top_k ?? 50);
  const filterJoin = normalizeCombiner(looseSpec.filter_join);
  const ctes = looseSpec.ctes;
  const windowFunctions = looseSpec.window_functions;
  const semanticModels = looseSpec.semantic_models;

  const compiled = compileVisualState(
    primaryTable,
    selectedColumns,
    orderedProjectionKeys,
    joins,
    filters,
    sorts,
    isDistinct,
    limit,
    schemaData,
    dialect,
    filterJoin,
    undefined,
    vectorSearch,
    hybridSearch,
    ctes,
    windowFunctions,
    semanticModels,
  );
  return compiled.sql;
}
