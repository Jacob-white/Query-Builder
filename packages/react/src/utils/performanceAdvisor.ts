/**
 * Performance Advisor & Cloud Query Cost Estimator.
 * =================================================
 * Provides pre-execution byte scan volume / cloud dollar cost estimation
 * (BigQuery, Snowflake), 1-click index recommendations, and post-execution
 * query plan hotspot detection.
 */

import type {
  CloudCostEstimate,
  IndexRecommendation,
  PerformanceAdvisorInsight,
  QuerySpec,
  SchemaSnapshot,
  SqlDialect,
} from "../types";

// Pricing Constants
const BIGQUERY_PER_TB_DOLLARS = 6.25; // Standard on-demand pricing ($6.25 per TB)
const MIN_BIGQUERY_SCAN_BYTES = 10 * 1024 * 1024; // 10 MB minimum billing quantum
const ESTIMATED_ROW_BYTE_SIZE = 128; // Average bytes per row estimate

/**
 * Estimates byte volume and cloud warehouse cost before execution.
 */
export function estimateCloudQueryCost(
  sql: string,
  dialect: SqlDialect = "postgres",
  tableStats?: Record<string, { rowCount?: number; byteSize?: number }>,
): CloudCostEstimate {
  const clean = sql.toLowerCase();

  // Extract referenced table names
  const fromMatches = clean.matchAll(/\b(?:from|join)\s+([a-zA-Z0-9_".`\[\]]+)/gi);
  const tables: string[] = [];
  for (const m of fromMatches) {
    const raw = m[1].replace(/["'`\[\]]/g, "");
    const parts = raw.split(".");
    tables.push(parts[parts.length - 1]);
  }

  let totalBytes = 0;
  for (const tbl of tables) {
    if (tableStats && tableStats[tbl]?.byteSize) {
      totalBytes += tableStats[tbl].byteSize!;
    } else if (tableStats && tableStats[tbl]?.rowCount) {
      totalBytes += tableStats[tbl].rowCount! * ESTIMATED_ROW_BYTE_SIZE;
    } else {
      // Default heuristics: 25 MB per analytical table reference
      totalBytes += 25 * 1024 * 1024;
    }
  }

  const d = dialect.toLowerCase();
  const isBigQuery = d === "bigquery";
  const isSnowflake = d === "snowflake";

  let dollarCost = 0;
  let creditsEstimated: number | undefined = undefined;
  let pricingTier = "Standard On-Demand";

  if (isBigQuery) {
    const billedBytes = Math.max(MIN_BIGQUERY_SCAN_BYTES, totalBytes);
    const tbScanned = billedBytes / (1024 * 1024 * 1024 * 1024);
    dollarCost = Number((tbScanned * BIGQUERY_PER_TB_DOLLARS).toFixed(5));
    pricingTier = "BigQuery On-Demand ($6.25/TB)";
  } else if (isSnowflake) {
    // Snowflake X-Small warehouse is 1 credit / hr ($3 / credit standard)
    // Estimate query execution time proportional to scanned data
    const secondsEst = Math.max(1, Math.min(60, totalBytes / (50 * 1024 * 1024)));
    creditsEstimated = Number(((secondsEst / 3600) * 1).toFixed(4));
    dollarCost = Number((creditsEstimated * 3.0).toFixed(4));
    pricingTier = "Snowflake X-Small (1 Credit/Hr)";
  } else {
    // Standard SQL engine (Postgres, DuckDB, MySQL) - local or hosted compute
    dollarCost = 0.0;
    pricingTier = "Zero-Cost Local / Provisioned Instance";
  }

  return {
    bytesScannedEstimated: totalBytes,
    dollarCostEstimated: dollarCost,
    creditsEstimated,
    pricingTier,
    isCached: false,
  };
}

/**
 * Recommends optimal database indexes based on QuerySpec filters, joins, and order_by.
 */
export function recommendIndexes(
  spec: Partial<QuerySpec>,
  schema?: SchemaSnapshot | null,
): IndexRecommendation[] {
  const recommendations: IndexRecommendation[] = [];
  const primaryTable = spec.table;
  if (!primaryTable) return recommendations;

  const cleanPrimary = primaryTable.slice(primaryTable.lastIndexOf(".") + 1);
  const aliasMap = new Map<string, string>([
    ["t0", cleanPrimary],
    ["t1", cleanPrimary],
    [cleanPrimary, cleanPrimary],
    [primaryTable, cleanPrimary],
  ]);

  if (spec.joins) {
    const usesOneBasedJoinAliases = Boolean(
      spec.filters?.some((f) => {
        const pref = f.tablePrefix || (f.column?.includes(".") ? f.column.split(".")[0] : "");
        return pref === `t${spec.joins!.length + 1}`;
      }),
    );
    spec.joins.forEach((j, idx) => {
      const cleanJoinTbl = j.table.slice(j.table.lastIndexOf(".") + 1);
      aliasMap.set(`t${idx + 2}`, cleanJoinTbl);
      if (!usesOneBasedJoinAliases) {
        aliasMap.set(`t${idx + 1}`, cleanJoinTbl);
      }
      aliasMap.set(j.table, cleanJoinTbl);
      aliasMap.set(cleanJoinTbl, cleanJoinTbl);
      if (j.alias) {
        aliasMap.set(j.alias, cleanJoinTbl);
      }
    });
  }

  const pkByTable = new Map<string, string[]>();
  if (schema?.tables) {
    for (const [tName, tMeta] of Object.entries(schema.tables)) {
      const cleanT = tName.slice(tName.lastIndexOf(".") + 1).toLowerCase();
      const pks: string[] = [];
      let idExplicitlyNonPk = false;
      for (const c of tMeta.columns) {
        if (c.is_primary) {
          pks.push(c.name.toLowerCase());
        } else if (c.name.toLowerCase() === "id" && c.is_primary === false) {
          idExplicitlyNonPk = true;
        }
      }
      if (pks.length === 0 && !idExplicitlyNonPk) {
        pks.push("id");
      }
      pkByTable.set(cleanT, pks);
    }
  }

  const resolveTable = (rawPrefix?: string): string => {
    if (!rawPrefix) return cleanPrimary;
    const cleaned = rawPrefix.slice(rawPrefix.lastIndexOf(".") + 1);
    return aliasMap.get(cleaned) || cleaned;
  };

  const getCoveredPkCols = (tbl: string, activeCols: Set<string>): Set<string> => {
    const cleanT = tbl.slice(tbl.lastIndexOf(".") + 1).toLowerCase();
    const pks = pkByTable.get(cleanT) ?? ["id"];
    const covered = new Set<string>();
    for (const pkCol of pks) {
      if (activeCols.has(pkCol)) {
        covered.add(pkCol);
      } else {
        break;
      }
    }
    return covered;
  };

  const seenIndexes = new Set<string>();
  const filterColsByTable = new Map<string, Set<string>>();
  const parsedFilters: Array<{ targetTable: string; col: string; op: string }> = [];

  // 1. Check WHERE filter columns
  if (spec.filters && spec.filters.length > 0) {
    for (const f of spec.filters) {
      const rawCol = f.column;
      if (!rawCol || rawCol === "*" || f.op === "RAW") continue;
      const colParts = rawCol.split(".");
      const col = colParts[colParts.length - 1];
      const prefix = f.tablePrefix || (colParts.length > 1 ? colParts[colParts.length - 2] : undefined);
      const targetTable = resolveTable(prefix);
      const tblKey = targetTable.toLowerCase();
      if (!filterColsByTable.has(tblKey)) {
        filterColsByTable.set(tblKey, new Set<string>());
      }
      filterColsByTable.get(tblKey)!.add(col.toLowerCase());
      parsedFilters.push({ targetTable, col, op: f.op });
    }

    for (const { targetTable, col, op } of parsedFilters) {
      const activeCols = filterColsByTable.get(targetTable.toLowerCase()) ?? new Set<string>();
      const coveredPks = getCoveredPkCols(targetTable, activeCols);
      const dedupKey = `${targetTable.toLowerCase()}:${col.toLowerCase()}`;

      if (!coveredPks.has(col.toLowerCase()) && !seenIndexes.has(dedupKey)) {
        seenIndexes.add(dedupKey);
        const idxName = `idx_${targetTable}_${col.toLowerCase()}`;
        recommendations.push({
          id: `idx_rec_${targetTable}_${col}`,
          table: targetTable,
          columns: [col],
          indexName: idxName,
          ddl: `CREATE INDEX ${idxName} ON ${targetTable} (${col});`,
          rationale: `Accelerates filter condition (${col} ${op} ...) from sequential table scan to B-Tree index scan.`,
          estimatedImpact: "high",
        });
      }
    }
  }

  // 2. Check JOIN foreign key columns
  if (spec.joins && spec.joins.length > 0) {
    for (const j of spec.joins) {
      if (j.right_col) {
        const cleanRight = j.right_col.slice(j.right_col.lastIndexOf(".") + 1);
        const cleanJoinTable = resolveTable(j.table);
        const activeJoinCols = new Set<string>(
          filterColsByTable.get(cleanJoinTable.toLowerCase()) ?? [],
        );
        activeJoinCols.add(cleanRight.toLowerCase());
        const coveredJoinPks = getCoveredPkCols(cleanJoinTable, activeJoinCols);
        const dedupKey = `${cleanJoinTable.toLowerCase()}:${cleanRight.toLowerCase()}`;
        if (!coveredJoinPks.has(cleanRight.toLowerCase()) && !seenIndexes.has(dedupKey)) {
          seenIndexes.add(dedupKey);
          const idxName = `idx_${cleanJoinTable}_${cleanRight.toLowerCase()}`;
          recommendations.push({
            id: `idx_join_${cleanJoinTable}_${cleanRight}`,
            table: cleanJoinTable,
            columns: [cleanRight],
            indexName: idxName,
            ddl: `CREATE INDEX ${idxName} ON ${cleanJoinTable} (${cleanRight});`,
            rationale: `Improves ${j.type || "LEFT"} JOIN performance between ${cleanPrimary} and ${cleanJoinTable}.`,
            estimatedImpact: "high",
          });
        }
      }
    }
  }

  // 3. Composite Index on (filter, sort)
  if (spec.filters && spec.filters.length > 0 && spec.order_by && spec.order_by.length > 0) {
    const rawFilterCol = spec.filters[0].column;
    const rawSortCol = spec.order_by[0].column;
    const fParts = rawFilterCol.split(".");
    const sParts = rawSortCol.split(".");
    const filterCol = fParts[fParts.length - 1];
    const sortCol = sParts[sParts.length - 1];
    const filterPrefix =
      spec.filters[0].tablePrefix || (fParts.length > 1 ? fParts[fParts.length - 2] : undefined);
    const sortPrefix = sParts.length > 1 ? sParts[sParts.length - 2] : undefined;
    const filterTable = resolveTable(filterPrefix);
    const sortTable = resolveTable(sortPrefix);
    if (
      filterCol &&
      sortCol &&
      filterCol !== sortCol &&
      spec.filters[0].op !== "RAW" &&
      filterTable.toLowerCase() === sortTable.toLowerCase()
    ) {
      const idxName = `idx_${filterTable}_comp_${filterCol}_${sortCol}`;
      recommendations.push({
        id: `idx_comp_${filterTable}_${filterCol}_${sortCol}`,
        table: filterTable,
        columns: [filterCol, sortCol],
        indexName: idxName,
        ddl: `CREATE INDEX ${idxName} ON ${filterTable} (${filterCol}, ${sortCol});`,
        rationale: `Composite index satisfies both WHERE ${filterCol} and ORDER BY ${sortCol} avoiding file-sort.`,
        estimatedImpact: "medium",
      });
    }
  }

  return recommendations;
}

/**
 * Analyzes query specification and generates holistic performance and cost insights.
 */
export function analyzeQueryPerformance(
  spec: Partial<QuerySpec>,
  sql: string,
  dialect: SqlDialect = "postgres",
  tableStats?: Record<string, { rowCount?: number; byteSize?: number }>,
  schema?: SchemaSnapshot | null,
): PerformanceAdvisorInsight[] {
  const insights: PerformanceAdvisorInsight[] = [];

  // 1. Cloud Cost Estimation Insight
  const cost = estimateCloudQueryCost(sql, dialect, tableStats);
  const costFormatted =
    cost.dollarCostEstimated > 0
      ? `$${cost.dollarCostEstimated.toFixed(4)}`
      : "< $0.0001 (Zero-Cost Local)";
  const scanMb = (cost.bytesScannedEstimated / (1024 * 1024)).toFixed(1);

  insights.push({
    type: "cost",
    severity: cost.dollarCostEstimated > 0.05 ? "warning" : "info",
    title: `Estimated Cost: ${costFormatted}`,
    message: `Estimated scan volume: ~${scanMb} MB using ${cost.pricingTier}.`,
    costEstimate: cost,
  });

  // 2. Unbounded Scan Warning
  const hasWildcard = spec.columns?.includes("*") || /select\s+\*/i.test(sql);
  const hasNoLimit = spec.limit === undefined || spec.limit <= 0 || !/\blimit\s+\d+/i.test(sql);
  if (hasWildcard && hasNoLimit) {
    insights.push({
      type: "warning",
      severity: "warning",
      title: "Unbounded Table Scan Detected",
      message:
        "Query selects all columns ('SELECT *') without an explicit LIMIT clause. Adding a LIMIT or projecting specific columns saves I/O and network bandwidth.",
    });
  }

  // 3. Missing Filter Warning on Table
  if (!spec.filters || spec.filters.length === 0) {
    insights.push({
      type: "optimization",
      severity: "info",
      title: "Full Table Scan",
      message: `Query on table '${spec.table}' has no WHERE filter predicates. Consider filtering to reduce memory consumption.`,
    });
  }

  // 4. Index Recommendations
  const idxRecs = recommendIndexes(spec, schema);
  for (const rec of idxRecs) {
    insights.push({
      type: "index",
      severity: rec.estimatedImpact === "high" ? "warning" : "info",
      title: `Recommended Index: ${rec.indexName}`,
      message: rec.rationale,
      recommendation: rec,
    });
  }

  return insights;
}
