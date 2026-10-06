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
} from "../types";

export interface CompiledVisualQuery {
  sql: string;
  spec: {
    table: string;
    columns: (string | { column: string; agg?: string; alias?: string })[];
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
    }[];
    filter_join: "AND" | "OR";
    order_by: { column: string; direction: "ASC" | "DESC"; tablePrefix?: string }[];
    distinct: boolean;
    limit: number;
    vector_search?: VectorSearchSpec;
    hybrid_search?: HybridSearchSpec;
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
]);

const ALLOWED_AGGREGATES = new Set(["COUNT", "SUM", "AVG", "MIN", "MAX"]);

const sanitizeIdent = (s: string) => s.replace(/[\x00-\x1f\x7f]/g, "");

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
    dialect === "starrocks" ||
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
    dialect === "doris" ||
    dialect === "apache_doris" ||
    dialect === "pydoris" ||
    dialect === "impala" ||
    dialect === "apache_impala" ||
    dialect === "impyla" ||
    dialect === "kyuubi" ||
    dialect === "apache_kyuubi" ||
    dialect === "drill" ||
    dialect === "apache_drill" ||
    dialect === "pydrill" ||
    dialect === "yugabyte" ||
    dialect === "yugabytedb" ||
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

export function compileVisualState(
  primaryTable: string,
  selectedColumns: Record<string, VisualColumnSelect>,
  orderedProjectionKeys: string[],
  joins: VisualJoin[],
  filters: VisualFilter[],
  sorts: VisualSort[],
  isDistinct: boolean = false,
  limit: number = 50,
  schemaData?: SchemaSnapshot | null,
  dialect: SqlDialect = "postgres",
  filterJoin: "AND" | "OR" = "AND",
  customOperators?: Record<string, CustomFilterOperator>,
  vectorSearch?: VectorSearchSpec | null,
  hybridSearch?: HybridSearchSpec | null,
): CompiledVisualQuery {
  if (!primaryTable || typeof primaryTable !== "string") {
    return {
      sql: "",
      spec: {
        table: "",
        columns: [],
        joins: [],
        filters: [],
        filter_join: filterJoin || "AND",
        order_by: [],
        distinct: false,
        limit,
        vector_search: vectorSearch || undefined,
        hybrid_search: hybridSearch || undefined,
      },
    };
  }

  const cleanPrimary = cleanTableName(primaryTable);
  const safeProjectionKeys = (orderedProjectionKeys || []).slice(0, 100);
  const hasAggregates = safeProjectionKeys.some(
    (k) =>
      Boolean(
        selectedColumns[k]?.aggregate &&
          ALLOWED_AGGREGATES.has(selectedColumns[k]?.aggregate as string),
      ),
  );

  // Projections
  let selectClause = "*";
  const specColumns: (
    | string
    | { column: string; agg?: string; alias?: string }
  )[] = [];
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
          return `${aggUpper}(${colRef}) AS ${quoteAlias(alias, dialect)}`;
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

  if (activeFilters.length > 0) {
    const parts: { expr: string; combiner: "AND" | "OR" }[] = [];
    activeFilters.forEach((f) => {
      const tbl = cleanTableName(f.tablePrefix || cleanPrimary);
      const colName = sanitizeIdent(f.column);
      const colRef = `${quoteIdent(tbl, dialect)}.${quoteIdent(colName, dialect)}`;
      const valStr = String(f.value ?? "");
      let expr = "";

      specFilters.push({
        column: colName,
        op: f.operator.toLowerCase().replace(" ", "_"),
        value: f.value,
        tablePrefix: tbl,
      });

      const customOp = customOperators?.[f.operator];

      if (customOp?.formatSql) {
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
        if (f.parenOpen) expr = `${f.parenOpen}${expr}`;
        if (f.parenClose) expr = `${expr}${f.parenClose}`;
        parts.push({ expr, combiner: f.combiner || filterJoin || "AND" });
      }
    });

    if (parts.length > 0) {
      let combined = parts[0].expr;
      for (let i = 1; i < parts.length; i++) {
        combined += ` ${parts[i].combiner} ${parts[i].expr}`;
      }
      whereClause = `WHERE ${combined}`;
    }
  }

  // Sorts
  const activeSorts = (sorts || []).slice(0, 20).filter((s) => s.column);
  const specSorts: CompiledVisualQuery["spec"]["order_by"] = [];
  let orderClause = "";

  if (activeSorts.length > 0) {
    const sortParts = activeSorts.map((s) => {
      const tbl = cleanTableName(s.tablePrefix || cleanPrimary);
      const colName = sanitizeIdent(s.column);
      const direction = s.direction === "DESC" ? "DESC" : "ASC";
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
    const vecStr = `'[${vectorSearch.vector.join(",")}]'`;
    if (vectorSearch.include_distances) {
      const distExpr = `(${vRef} <=> ${vecStr}) AS "_distance"`;
      selectClause = selectClause === "*" ? `*, ${distExpr}` : `${selectClause}, ${distExpr}`;
    }
    if (!orderClause) {
      orderClause = `ORDER BY ${vRef} <=> ${vecStr} ASC`;
    }
  }

  // Group By
  let groupClause = "";
  if (hasAggregates) {
    const nonAggCols = safeProjectionKeys
      .map((k) => selectedColumns[k])
      .filter((item): item is VisualColumnSelect =>
        Boolean(item && !item.aggregate),
      )
      .map((item) => {
        const tbl = cleanTableName(item.table || cleanPrimary);
        const colName = sanitizeIdent(item.name);
        return `${quoteIdent(tbl, dialect)}.${quoteIdent(colName, dialect)}`;
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
  queryParts.push(formatLimit(limit, dialect));

  return {
    sql: queryParts.join("\n"),
    spec: {
      table: cleanPrimary,
      columns: specColumns,
      joins: specJoins,
      filters: specFilters,
      filter_join:
        (filters || []).some((f) => f.combiner === "OR") || filterJoin === "OR"
          ? "OR"
          : "AND",
      order_by: specSorts,
      distinct: isDistinct,
      limit,
      vector_search: vectorSearch || undefined,
      hybrid_search: hybridSearch || undefined,
    },
  };
}

/**
 * Estimates a client-side QueryPlanNode hierarchy from a compiled QuerySpec.
 */
export function estimateClientPlan(spec: any): QueryPlanNode {
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
