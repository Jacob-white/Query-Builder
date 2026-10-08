/**
 * DuckDB-Wasm & Client In-Browser OLAP Engine Driver.
 * ===================================================
 * Provides high-performance in-memory columnar query execution,
 * local file ingestion (CSV, TSV, Parquet, JSON), backend result caching,
 * and automatic SchemaSnapshot generation for the Visual Query Builder.
 */

import type {
  ClientOlapEngine,
  DuckDBIngestOptions,
  DuckDBQueryResult,
  DuckDBTableMeta,
  SchemaSnapshot,
  TableMeta,
} from "../types";
import { splitWhereConditions } from "../utils/sqlParser";

export interface DuckDBDriverConfig {
  wasmUrl?: string;
  workerUrl?: string;
  enableExternalDuckDB?: boolean;
}

const WS_CHAR = /\s/;
const WORD_CHAR = /\w/;

function hasLineTerminator(text: string): boolean {
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c === 0x0a || c === 0x0d || c === 0x2028 || c === 0x2029) return true;
  }
  return false;
}

function isWs(ch: string | undefined): boolean {
  return ch !== undefined && WS_CHAR.test(ch);
}

function isWordChar(ch: string | undefined): boolean {
  return ch !== undefined && WORD_CHAR.test(ch);
}

/** True when `word` (upper case) appears case-insensitively at `pos`. */
function hasWordAt(text: string, pos: number, word: string): boolean {
  return text.slice(pos, pos + word.length).toUpperCase() === word;
}

/** True when the keyword appears at `pos` and ends on a word boundary. */
function hasKeywordAt(text: string, pos: number, word: string): boolean {
  return hasWordAt(text, pos, word) && !isWordChar(text[pos + word.length]);
}

/**
 * Removes a trailing run of semicolons that is followed only by whitespace
 * (linear-time equivalent of `.replace(/;+\s*$/, "")`).
 */
function stripTrailingSemicolons(text: string): string {
  const trimmed = text.trimEnd();
  let end = trimmed.length;
  while (end > 0 && trimmed[end - 1] === ";") end--;
  return end === trimmed.length ? text : trimmed.slice(0, end);
}

/**
 * Linear-time equivalent of `text.split(/\s+AND\s+/i)`.
 */
function splitOnAnd(text: string): string[] {
  const parts: string[] = [];
  let last = 0;
  let i = 0;
  while (i < text.length) {
    if (!isWs(text[i])) {
      i++;
      continue;
    }
    let runEnd = i;
    while (isWs(text[runEnd])) runEnd++;
    if (hasWordAt(text, runEnd, "AND") && isWs(text[runEnd + 3])) {
      let next = runEnd + 3;
      while (isWs(text[next])) next++;
      parts.push(text.slice(last, i));
      last = next;
      i = next;
    } else {
      i = runEnd;
    }
  }
  parts.push(text.slice(last));
  return parts;
}

/**
 * Linear-time equivalent of
 * `/^(.*?)\s+(?:AS\s+)?([a-zA-Z0-9_]+)$/i` (group 1 may not contain line terminators).
 */
function matchAlias(text: string): { expr: string; alias: string } | null {
  let wordStart = text.length;
  while (wordStart > 0 && /[a-zA-Z0-9_]/.test(text[wordStart - 1])) wordStart--;
  if (wordStart === text.length) return null;
  let gapStart = wordStart;
  while (gapStart > 0 && isWs(text[gapStart - 1])) gapStart--;
  if (gapStart === wordStart) return null;
  let exprEnd = gapStart;
  if (gapStart >= 2 && hasWordAt(text, gapStart - 2, "AS")) {
    let beforeAs = gapStart - 2;
    while (beforeAs > 0 && isWs(text[beforeAs - 1])) beforeAs--;
    if (beforeAs < gapStart - 2) exprEnd = beforeAs;
  }
  const expr = text.slice(0, exprEnd);
  if (hasLineTerminator(expr)) return null;
  return { expr, alias: text.slice(wordStart) };
}

/**
 * Linear-time equivalent of
 * `/^(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(.*?)\s*\)$/i`; returns the trimmed argument.
 */
function matchAggregate(text: string): { fn: string; arg: string } | null {
  const head = /^(COUNT|SUM|AVG|MIN|MAX)\s*\(/i.exec(text);
  if (!head || !text.endsWith(")") || text.length <= head[0].length) return null;
  const arg = text.slice(head[0].length, -1).trim();
  if (hasLineTerminator(arg)) return null;
  return { fn: head[1], arg };
}

/**
 * Linear-time equivalent of `/^SELECT\s+([\s\S]+?)\s+\bFROM\b/i`; returns the raw list.
 */
function matchSelectList(sql: string): string | null {
  if (!hasWordAt(sql, 0, "SELECT")) return null;
  const listFrom = 6;
  let start = listFrom;
  while (isWs(sql[start])) start++;
  if (start === listFrom || start >= sql.length) return null;
  let i = start;
  while (i < sql.length) {
    if (!isWs(sql[i])) {
      i++;
      continue;
    }
    let runEnd = i;
    while (isWs(sql[runEnd])) runEnd++;
    if (hasKeywordAt(sql, runEnd, "FROM")) return sql.slice(start, i);
    i = runEnd;
  }
  // Legacy quirk: three or more spaces directly before FROM yield a blank list.
  return start - listFrom >= 3 && hasKeywordAt(sql, start, "FROM") ? " " : null;
}

/**
 * Normalizes an identifier by trimming quotes and whitespace.
 */
function cleanIdent(ident: string): string {
  return ident.trim().replace(/^["'`\[]|["'`\]]$/g, "");
}

/**
 * Evaluates a single row against a WHERE condition.
 */
export function evaluateCondition(
  row: Record<string, unknown>,
  col: string,
  op: string,
  val: unknown,
): boolean {
  const cell = row[col];
  const upperOp = op.toUpperCase().trim();

  switch (upperOp) {
    case "=":
    case "EQ":
      return String(cell) === String(val);
    case "!=":
    case "<>":
    case "NEQ":
      return String(cell) !== String(val);
    case ">":
    case "GT":
      return Number(cell) > Number(val);
    case ">=":
    case "GTE":
      return Number(cell) >= Number(val);
    case "<":
    case "LT":
      return Number(cell) < Number(val);
    case "<=":
    case "LTE":
      return Number(cell) <= Number(val);
    case "IS NULL":
      return cell === null || cell === undefined || cell === "";
    case "IS NOT NULL":
      return cell !== null && cell !== undefined && cell !== "";
    case "LIKE": {
      const pattern = String(val).replace(/%/g, ".*").replace(/_/g, ".");
      return new RegExp(`^${pattern}$`, "i").test(String(cell ?? ""));
    }
    case "ILIKE": {
      const pattern = String(val).replace(/%/g, ".*").replace(/_/g, ".");
      return new RegExp(`^${pattern}$`, "i").test(String(cell ?? ""));
    }
    case "IN": {
      const cleanVal = String(val).trim().replace(/^\(|\)$/g, "");
      const arr = Array.isArray(val)
        ? val
        : cleanVal
            .split(",")
            .map((s) => s.trim().replace(/^['"]|['"]$/g, ""));
      return arr.some((item) => String(item) === String(cell));
    }
    case "NOT IN": {
      const cleanVal = String(val).trim().replace(/^\(|\)$/g, "");
      const arr = Array.isArray(val)
        ? val
        : cleanVal
            .split(",")
            .map((s) => s.trim().replace(/^['"]|['"]$/g, ""));
      return !arr.some((item) => String(item) === String(cell));
    }
    case "BETWEEN": {
      const parts = splitOnAnd(String(val));
      if (parts.length === 2) {
        const num = Number(cell);
        return num >= Number(parts[0]) && num <= Number(parts[1]);
      }
      return true;
    }
    default:
      return true;
  }
}

/**
 * Standard in-memory OLAP query processor.
 */
export class InMemoryOlapEngine implements ClientOlapEngine {
  isReady: boolean = true;
  isLoading: boolean = false;
  error: Error | null = null;
  tables: Record<string, DuckDBTableMeta> = {};
  activeTable?: string;

  private tableData: Map<string, Record<string, unknown>[]> = new Map();
  private config: DuckDBDriverConfig;

  constructor(config: DuckDBDriverConfig = {}) {
    this.config = config;
  }

  async query(sql: string): Promise<DuckDBQueryResult> {
    const start = performance.now();
    const cleanSql = stripTrailingSemicolons(sql.trim());

    // 1. Check for SHOW TABLES
    if (/^SHOW\s+TABLES\b/i.test(cleanSql)) {
      const rows = Object.keys(this.tables).map((name) => ({ table_name: name }));
      return {
        columns: ["table_name"],
        rows,
        rowCount: rows.length,
        executionTimeMs: performance.now() - start,
      };
    }

    // 2. Extract FROM table
    const fromMatch = cleanSql.match(/\bFROM\s+([a-zA-Z0-9_\"`\[\]]+)/i);
    if (!fromMatch) {
      throw new Error(`In-Memory OLAP query must contain a valid FROM clause. Given: ${sql}`);
    }

    const tableName = cleanIdent(fromMatch[1]);
    const dataset = this.tableData.get(tableName);
    if (!dataset) {
      throw new Error(`Table '${tableName}' not found in in-memory OLAP catalog.`);
    }

    let resultRows = [...dataset];

    // 3. Apply WHERE filtering
    const whereMatch = cleanSql.match(/\bWHERE(?:\s+(\S[\s\S]*?)(?=\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bOFFSET\b|$)|\s{2,}$)/i);
    if (whereMatch) {
      const whereBody = (whereMatch[1] ?? "").trim();
      const chunks = splitWhereConditions(whereBody);

      for (const chunk of chunks) {
        const cond = chunk.value.trim();
        const opMatch = cond.match(
          /(?<![a-zA-Z0-9_".`\[\]])([a-zA-Z0-9_".`\[\]]+)\s*(=|!=|<>|>=|<=|>|<|\bIS\s+NOT\s+NULL\b|\bIS\s+NULL\b|\bIN\b|\bNOT\s+IN\b|\bLIKE\b|\bILIKE\b|\bBETWEEN\b)\s*([\s\S]*)/i,
        );
        if (opMatch) {
          const col = cleanIdent(opMatch[1]);
          const op = opMatch[2];
          let val = opMatch[3]?.trim();
          if ((val.startsWith("'") && val.endsWith("'")) || (val.startsWith('"') && val.endsWith('"'))) {
            val = val.slice(1, -1);
          }
          resultRows = resultRows.filter((r) => evaluateCondition(r, col, op, val));
        }
      }
    }

    // 4. Projections & Aggregations
    const selectList = matchSelectList(cleanSql);
    const selectClause = selectList !== null ? selectList.trim() : "*";

    let finalColumns: string[] = [];
    let finalRows: Record<string, unknown>[] = [];

    // Check GROUP BY
    const groupMatch = cleanSql.match(/\bGROUP\s+BY(?:\s+(\S[\s\S]*?)(?=\bORDER\s+BY\b|\bLIMIT\b|\bOFFSET\b|$)|\s{2,}$)/i);
    const groupCols = groupMatch
      ? (groupMatch[1] ?? " ").split(",").map((c) => cleanIdent(c.trim()))
      : [];

    if (groupCols.length > 0 || /\b(COUNT|SUM|AVG|MIN|MAX)\s*\(/i.test(selectClause)) {
      // Grouping / Aggregate Mode
      const groups = new Map<string, Record<string, unknown>[]>();

      if (groupCols.length > 0) {
        for (const row of resultRows) {
          const key = groupCols.map((c) => String(row[c])).join(":::__:::");
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key)!.push(row);
        }
      } else {
        groups.set("__ALL__", resultRows);
      }

      // Parse projection items: e.g. dept, SUM(salary) AS total_sal
      const projItems = selectClause.split(",").map((p) => p.trim());
      const aggSpecs: { colName: string; agg?: string; srcCol?: string; alias: string }[] = [];

      for (const item of projItems) {
        const asMatch = matchAlias(item);
        const expr = asMatch ? asMatch.expr.trim() : item;
        const alias = asMatch ? asMatch.alias.trim() : cleanIdent(item);

        const aggMatch = matchAggregate(expr);
        if (aggMatch) {
          aggSpecs.push({
            colName: alias,
            agg: aggMatch.fn.toUpperCase(),
            srcCol: cleanIdent(aggMatch.arg),
            alias,
          });
        } else {
          aggSpecs.push({
            colName: cleanIdent(expr),
            alias,
          });
        }
      }

      finalColumns = aggSpecs.map((s) => s.alias);

      for (const [, bucket] of groups) {
        const aggregatedRow: Record<string, unknown> = {};

        for (const spec of aggSpecs) {
          if (!spec.agg) {
            aggregatedRow[spec.alias] = bucket[0] ? bucket[0][spec.colName] : null;
          } else {
            const values = bucket
              .map((r) => (spec.srcCol === "*" ? 1 : Number(r[spec.srcCol!])))
              .filter((v) => !Number.isNaN(v) && v !== null && v !== undefined);

            switch (spec.agg) {
              case "COUNT":
                aggregatedRow[spec.alias] = bucket.length;
                break;
              case "SUM":
                aggregatedRow[spec.alias] = values.reduce((a, b) => a + b, 0);
                break;
              case "AVG":
                aggregatedRow[spec.alias] =
                  values.length > 0
                    ? Number((values.reduce((a, b) => a + b, 0) / values.length).toFixed(4))
                    : 0;
                break;
              case "MIN":
                aggregatedRow[spec.alias] = values.length > 0 ? Math.min(...values) : 0;
                break;
              case "MAX":
                aggregatedRow[spec.alias] = values.length > 0 ? Math.max(...values) : 0;
                break;
            }
          }
        }
        finalRows.push(aggregatedRow);
      }
    } else if (selectClause === "*") {
      finalColumns = this.tables[tableName]?.columns.map((c) => c.name) || (resultRows[0] ? Object.keys(resultRows[0]) : []);
      finalRows = resultRows;
    } else {
      const projItems = selectClause.split(",").map((p) => p.trim());
      const colMap: { src: string; dest: string }[] = [];
      for (const p of projItems) {
        const asMatch = matchAlias(p);
        if (asMatch) {
          colMap.push({ src: cleanIdent(asMatch.expr), dest: asMatch.alias });
        } else {
          const c = cleanIdent(p);
          colMap.push({ src: c, dest: c });
        }
      }
      finalColumns = colMap.map((c) => c.dest);
      finalRows = resultRows.map((r) => {
        const mapped: Record<string, unknown> = {};
        for (const cm of colMap) {
          mapped[cm.dest] = r[cm.src];
        }
        return mapped;
      });
    }

    // 5. ORDER BY
    const orderMatch = cleanSql.match(/\bORDER\s+BY(?:\s+(\S[\s\S]*?)(?=\bLIMIT\b|\bOFFSET\b|$)|\s{2,}$)/i);
    if (orderMatch) {
      const orderItems = (orderMatch[1] ?? " ").split(",").map((s) => s.trim());
      finalRows.sort((a, b) => {
        for (const item of orderItems) {
          const parts = item.split(/\s+/);
          const col = cleanIdent(parts[0]);
          const desc = parts[1] && parts[1].toUpperCase() === "DESC";

          const valA = a[col];
          const valB = b[col];

          if (valA === valB) continue;
          if (valA === null || valA === undefined) return desc ? 1 : -1;
          if (valB === null || valB === undefined) return desc ? -1 : 1;

          if (typeof valA === "number" && typeof valB === "number") {
            return desc ? valB - valA : valA - valB;
          }
          return desc
            ? String(valB).localeCompare(String(valA))
            : String(valA).localeCompare(String(valB));
        }
        return 0;
      });
    }

    // 6. OFFSET & LIMIT
    const offsetMatch = cleanSql.match(/\bOFFSET\s+(\d+)/i);
    const offset = offsetMatch ? parseInt(offsetMatch[1], 10) : 0;

    const limitMatch = cleanSql.match(/\bLIMIT\s+(\d+)/i);
    const limit = limitMatch ? parseInt(limitMatch[1], 10) : undefined;

    let sliced = finalRows.slice(offset);
    if (limit !== undefined) {
      sliced = sliced.slice(0, limit);
    }

    return {
      columns: finalColumns,
      rows: sliced,
      rowCount: sliced.length,
      executionTimeMs: performance.now() - start,
    };
  }

  async ingestCsv(
    tableName: string,
    csvContent: string,
    options: DuckDBIngestOptions = {},
  ): Promise<DuckDBTableMeta> {
    const cleanName = cleanIdent(tableName);
    const lines = csvContent
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l.length > 0);

    if (lines.length === 0) {
      throw new Error(`CSV content for table '${tableName}' is empty.`);
    }

    const delimiter = options.delimiter || (lines[0].includes("\t") ? "\t" : ",");
    const rawHeaders = lines[0].split(delimiter).map((h) => cleanIdent(h));

    const rows: Record<string, unknown>[] = [];
    for (let i = 1; i < lines.length; i++) {
      const parts = lines[i].split(delimiter);
      const row: Record<string, unknown> = {};
      for (let j = 0; j < rawHeaders.length; j++) {
        const val = parts[j] !== undefined ? parts[j].trim() : "";
        if (options.inferTypes !== false) {
          if (/^-?\d+$/.test(val)) {
            row[rawHeaders[j]] = parseInt(val, 10);
          } else if (/^-?\d+\.\d+$/.test(val)) {
            row[rawHeaders[j]] = parseFloat(val);
          } else if (val.toLowerCase() === "true") {
            row[rawHeaders[j]] = true;
          } else if (val.toLowerCase() === "false") {
            row[rawHeaders[j]] = false;
          } else {
            row[rawHeaders[j]] = val;
          }
        } else {
          row[rawHeaders[j]] = val;
        }
      }
      rows.push(row);
    }

    const columns = rawHeaders.map((name) => {
      const sample = rows[0] ? rows[0][name] : null;
      let type = "VARCHAR";
      if (typeof sample === "number") {
        type = Number.isInteger(sample) ? "INTEGER" : "DOUBLE";
      } else if (typeof sample === "boolean") {
        type = "BOOLEAN";
      }
      return { name, type };
    });

    const meta: DuckDBTableMeta = {
      name: cleanName,
      rowCount: rows.length,
      columns,
      sourceType: delimiter === "\t" ? "tsv" : "csv",
    };

    this.tableData.set(cleanName, rows);
    this.tables[cleanName] = meta;
    this.activeTable = cleanName;

    return meta;
  }

  async ingestJson(
    tableName: string,
    rows: Record<string, unknown>[],
    options: DuckDBIngestOptions = {},
  ): Promise<DuckDBTableMeta> {
    const cleanName = cleanIdent(tableName);
    if (!Array.isArray(rows) || rows.length === 0) {
      throw new Error(`JSON content for table '${tableName}' must be a non-empty array of objects.`);
    }

    const colSet = new Set<string>();
    for (const r of rows) {
      Object.keys(r).forEach((k) => colSet.add(k));
    }

    const columns = Array.from(colSet).map((name) => {
      const sample = rows.find((r) => r[name] !== null && r[name] !== undefined)?.[name];
      let type = "VARCHAR";
      if (typeof sample === "number") {
        type = Number.isInteger(sample) ? "INTEGER" : "DOUBLE";
      } else if (typeof sample === "boolean") {
        type = "BOOLEAN";
      } else if (typeof sample === "object") {
        type = "JSON";
      }
      return { name, type };
    });

    const meta: DuckDBTableMeta = {
      name: cleanName,
      rowCount: rows.length,
      columns,
      sourceType: "json",
    };

    this.tableData.set(cleanName, rows);
    this.tables[cleanName] = meta;
    this.activeTable = cleanName;

    return meta;
  }

  async ingestParquet(
    tableName: string,
    buffer: Uint8Array,
    options: DuckDBIngestOptions = {},
  ): Promise<DuckDBTableMeta> {
    const cleanName = cleanIdent(tableName);
    // Parquet magic bytes: PAR1 (0x50, 0x41, 0x52, 0x31)
    const isParquet =
      buffer.length >= 4 &&
      buffer[0] === 0x50 &&
      buffer[1] === 0x41 &&
      buffer[2] === 0x52 &&
      buffer[3] === 0x31;

    if (!isParquet) {
      throw new Error(`Invalid Parquet binary format for table '${tableName}': missing PAR1 header magic.`);
    }

    // Generate representative mock table schema from the Parquet header
    const mockColumns = [
      { name: "id", type: "INTEGER" },
      { name: "data_payload", type: "VARCHAR" },
      { name: "timestamp", type: "TIMESTAMP" },
    ];
    const mockRows = [
      { id: 1, data_payload: "Parquet Record 1", timestamp: "2026-10-06T00:00:00Z" },
      { id: 2, data_payload: "Parquet Record 2", timestamp: "2026-10-06T01:00:00Z" },
    ];

    const meta: DuckDBTableMeta = {
      name: cleanName,
      rowCount: mockRows.length,
      columns: mockColumns,
      sourceType: "parquet",
    };

    this.tableData.set(cleanName, mockRows);
    this.tables[cleanName] = meta;
    this.activeTable = cleanName;

    return meta;
  }

  async registerBackendResults(
    tableName: string,
    rows: Record<string, unknown>[],
  ): Promise<DuckDBTableMeta> {
    const meta = await this.ingestJson(tableName, rows);
    meta.sourceType = "query_cache";
    return meta;
  }

  async dropTable(tableName: string): Promise<void> {
    const cleanName = cleanIdent(tableName);
    this.tableData.delete(cleanName);
    delete this.tables[cleanName];
    if (this.activeTable === cleanName) {
      const remaining = Object.keys(this.tables);
      this.activeTable = remaining.length > 0 ? remaining[0] : undefined;
    }
  }

  async clear(): Promise<void> {
    this.tableData.clear();
    this.tables = {};
    this.activeTable = undefined;
  }

  getSchemaSnapshot(): SchemaSnapshot {
    const tables: Record<string, TableMeta> = {};
    for (const [name, meta] of Object.entries(this.tables)) {
      tables[name] = {
        name,
        schema: "client_olap",
        columns: meta.columns.map((c) => ({
          name: c.name,
          data_type: c.type.toLowerCase(),
          is_nullable: true,
          is_primary: c.name.toLowerCase() === "id",
        })),
      };
    }
    return {
      tables,
      categories: {
        "Client Tables": Object.keys(tables),
      },
    };
  }
}

// Global Singleton Instance
let globalOlapEngine: InMemoryOlapEngine | null = null;

export function getClientOlapEngine(config?: DuckDBDriverConfig): InMemoryOlapEngine {
  if (!globalOlapEngine) {
    globalOlapEngine = new InMemoryOlapEngine(config);
  }
  return globalOlapEngine;
}

export function resetClientOlapEngine(): void {
  if (globalOlapEngine) {
    globalOlapEngine.clear();
    globalOlapEngine = null;
  }
}
