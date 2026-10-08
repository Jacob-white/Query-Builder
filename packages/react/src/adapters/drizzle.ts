/**
 * Drizzle ORM Adapter for React Query Builder.
 * Converts Drizzle runtime table objects or TypeScript source code into TableSchema[].
 */

import type { ColumnSchema, ForeignKey, SchemaSnapshot, TableSchema } from "../types";
import type { AdapterOptions, ToDrizzleOptions } from "./types";
import {
  extractSnapshotData,
  normalizeDataType,
  toCamelCase,
} from "./utils";


const DRIZZLE_TYPE_MAP: Record<string, string> = {
  serial: "integer",
  bigserial: "bigint",
  smallserial: "integer",
  int: "integer",
  integer: "integer",
  smallint: "integer",
  bigint: "bigint",
  tinyint: "integer",
  mediumint: "integer",
  text: "text",
  varchar: "text",
  char: "text",
  boolean: "boolean",
  bool: "boolean",
  timestamp: "timestamp",
  date: "date",
  datetime: "timestamp",
  time: "time",
  float: "float",
  double: "float",
  real: "float",
  doubleprecision: "float",
  decimal: "decimal",
  numeric: "decimal",
  json: "json",
  jsonb: "json",
  uuid: "uuid",
  bytes: "bytes",
};

/** Minimal structural shape of a Drizzle runtime column. */
interface DrizzleColumnLike {
  name?: string;
  primary?: boolean;
  isPrimaryKey?: boolean;
  notNull?: boolean;
  dataType?: string;
  columnType?: string;
  enumValues?: string[];
  references?: () => DrizzleRefTarget | null | undefined;
  default?: unknown;
}

interface DrizzleTableRef {
  [key: symbol]: unknown;
  _?: { name?: string };
  name?: string;
}

interface DrizzleRefTarget {
  table?: DrizzleTableRef;
  name?: string;
  column?: { name?: string };
}

/** Minimal structural shape of a Drizzle runtime table. */
interface DrizzleTableLike {
  [key: symbol]: unknown;
  _?: { name?: string; columns?: Record<string, unknown> };
  name?: string;
}

function parseRuntimeDrizzleTable(
  nameOrKey: string,
  tableObj: unknown,
  defaultSchema: string,
): TableSchema | null {
  if (!tableObj || typeof tableObj !== "object") return null;
  const table = tableObj as DrizzleTableLike;

  // Resolve table name
  const nameSymbol = Symbol.for("drizzle:Name");
  const tableName = (table[nameSymbol] ||
    table._?.name ||
    table.name ||
    nameOrKey) as string;

  // Resolve columns
  const colsSymbol = Symbol.for("drizzle:Columns");
  const rawCols = (table[colsSymbol] || table._?.columns || table) as Record<string, unknown>;

  const columns: ColumnSchema[] = [];
  const foreignKeys: ForeignKey[] = [];
  const primaryKeys: string[] = [];

  for (const [key, col] of Object.entries(rawCols)) {
    if (!col || typeof col !== "object" || key.startsWith("_") || key.startsWith("$")) {
      continue;
    }
    const colObj = col as DrizzleColumnLike;
    const colName = colObj.name || key;
    const isPk = Boolean(colObj.primary || colObj.isPrimaryKey);
    if (isPk) primaryKeys.push(colName);

    const isNotNull = Boolean(colObj.notNull || isPk);
    const isNullable = !isNotNull;

    const rawType = colObj.dataType || colObj.columnType || "text";
    const enumValues = colObj.enumValues;

    let dataType: string;
    let enums: string[] | undefined;
    if (Array.isArray(enumValues) && enumValues.length > 0) {
      dataType = "string";
      enums = enumValues;
    } else {
      dataType = DRIZZLE_TYPE_MAP[String(rawType).toLowerCase()] || normalizeDataType(String(rawType));
    }

    let fk: ForeignKey | undefined;
    if (typeof colObj.references === "function") {
      try {
        const refTarget = colObj.references();
        if (refTarget && typeof refTarget === "object") {
          const targetTable = (refTarget.table?.[nameSymbol] || refTarget.table?._?.name || refTarget.table?.name || "unknown") as string;
          const targetCol = refTarget.name || refTarget.column?.name || "id";
          fk = {
            table: tableName,
            column: colName,
            foreignTable: targetTable,
            foreignColumn: targetCol,
          };
          foreignKeys.push(fk);
        }
      } catch {
        // References may not resolve without context
      }
    }

    columns.push({
      name: colName,
      dataType,
      data_type: dataType,
      isNullable,
      is_nullable: isNullable,
      isPrimary: isPk,
      is_primary: isPk,
      default: colObj.default,
      enums,
      foreignKey: fk,
      foreign_key: fk,
    });
  }

  if (columns.length === 0) return null;

  const tableEnums: Record<string, string[]> = {};
  for (const c of columns) {
    if (c.enums) tableEnums[c.name] = c.enums;
  }

  return {
    name: tableName,
    schema: defaultSchema,
    columns,
    primaryKeys,
    foreignKeys,
    enums: tableEnums,
  };
}

type DrizzleScanMode = "enum" | "varTable" | "table";

interface DrizzleCall {
  /** `const NAME` the call is assigned to ("" when there is none; only possible in "table" mode). */
  varName: string;
  /** Quoted first argument: the DB enum / table name. */
  name: string;
  /** Index of the "(" that opens the call's argument list. */
  parenIdx: number;
  /** Index where the match starts: the `const` of its head, or the keyword when there is none. */
  start: number;
  /** Raw text between "[" and "]" for enum calls. */
  enumBody?: string;
}

// Same character classes as the regex escapes \s and \w.
function isRegexSpace(c: number): boolean {
  return (
    (c >= 9 && c <= 13) ||
    c === 32 ||
    c === 160 ||
    c === 0x1680 ||
    (c >= 0x2000 && c <= 0x200a) ||
    c === 0x2028 ||
    c === 0x2029 ||
    c === 0x202f ||
    c === 0x205f ||
    c === 0x3000 ||
    c === 0xfeff
  );
}

function isWordChar(c: number): boolean {
  return (c >= 48 && c <= 57) || (c >= 65 && c <= 90) || (c >= 97 && c <= 122) || c === 95;
}

function isQuoteChar(c: number): boolean {
  return c === 34 || c === 39 || c === 96;
}

/**
 * Wraps a "next index at or after `from`" search with a one-entry cache: a miss ("nothing after
 * from") and a hit that is still ahead of the next query are both reused, so repeated queries
 * from increasing start positions scan each character of the input at most once overall.
 */
function cachedFinder(find: (from: number) => number): (from: number) => number {
  let lastFrom = -1;
  let lastRes = -1;
  return (from) => {
    if (lastFrom !== -1 && from >= lastFrom && (lastRes === -1 || from <= lastRes)) return lastRes;
    lastFrom = from;
    lastRes = find(from);
    return lastRes;
  };
}

/**
 * Linear-time scanner for drizzle `pgTable("name", ...)` / `pgEnum("name", [...])` calls (and the
 * mysql / sqlite variants), optionally preceded by `[export] const NAME [: Type] =`.
 *
 * It replaces three unanchored regexes whose `[^=]+` / `\s*` runs followed by a terminator that
 * may be missing backtracked polynomially. Here every keyword occurrence is located with a
 * quantifier-free regex, the call is parsed with charCodeAt / cached indexOf, and the optional
 * `const` head is recovered by looking backwards from the keyword.
 *
 * - "enum":     `KwEnum(` directly followed by a quoted name, `,` and a non-empty `[...]`; head required.
 * - "varTable": `KwTable(` directly followed by a quoted name; head required.
 * - "table":    `KwTable` + optional whitespace + `(` + quoted name; head optional.
 *
 * Like the global regexes they replace, matches never overlap and are reported left to right.
 */
function scanDrizzleCalls(code: string, mode: DrizzleScanMode): DrizzleCall[] {
  const out: DrizzleCall[] = [];
  const wantEnum = mode === "enum";
  const nextQuote = cachedFinder((from) => {
    for (let i = from; i < code.length; i++) {
      if (isQuoteChar(code.charCodeAt(i))) return i;
    }
    return -1;
  });
  const nextClose = cachedFinder((from) => code.indexOf("]", from));
  const nextConst = cachedFinder((from) => code.indexOf("const", from));

  const skipSpace = (from: number): number => {
    let i = from;
    while (i < code.length && isRegexSpace(code.charCodeAt(i))) i++;
    return i;
  };

  // Recover `const NAME [: Type] =` ending right before the keyword at `kwIdx`. Only the
  // whitespace-then-"=" immediately before the keyword can end a head, and its type annotation
  // cannot contain another "=", so the candidates are the "const" tokens between the previous
  // "=" and this one; the leftmost valid one wins.
  const findHead = (kwIdx: number, lo: number): { name: string; start: number } | null => {
    let eq = kwIdx - 1;
    while (eq >= lo && isRegexSpace(code.charCodeAt(eq))) eq--;
    if (eq < lo || eq === 0 || code.charCodeAt(eq) !== 61) return null;
    const regionStart = Math.max(lo, code.lastIndexOf("=", eq - 1) + 1);
    for (let p = nextConst(regionStart); p !== -1 && p < eq; p = nextConst(p + 1)) {
      let i = p + 5;
      const afterConst = i;
      i = skipSpace(i);
      if (i === afterConst) continue;
      const identStart = i;
      while (i < eq && isWordChar(code.charCodeAt(i))) i++;
      if (i === identStart) continue;
      const identEnd = i;
      i = skipSpace(i);
      if (i === eq || (code.charCodeAt(i) === 58 && i + 1 < eq)) {
        return { name: code.slice(identStart, identEnd), start: p };
      }
    }
    return null;
  };

  const kwRe = /(?:pg|mysql|sqlite)(Enum|Table)/g;
  let lo = 0;
  let m: RegExpExecArray | null;
  while ((m = kwRe.exec(code)) !== null) {
    const k = m.index;
    if (k < lo || (m[1] === "Enum") !== wantEnum) continue;

    let i = k + m[0].length;
    if (mode === "table") i = skipSpace(i);
    if (code.charCodeAt(i) !== 40) continue;
    const parenIdx = i;
    i = skipSpace(i + 1);
    if (!isQuoteChar(code.charCodeAt(i))) continue;
    const nameStart = i + 1;
    const nameEnd = nextQuote(nameStart);
    if (nameEnd <= nameStart) continue;
    let end = nameEnd + 1;

    let enumBody: string | undefined;
    if (wantEnum) {
      i = skipSpace(end);
      if (code.charCodeAt(i) !== 44) continue;
      i = skipSpace(i + 1);
      if (code.charCodeAt(i) !== 91) continue;
      const bodyStart = i + 1;
      const close = nextClose(bodyStart);
      if (close <= bodyStart) continue;
      enumBody = code.slice(bodyStart, close);
      end = close + 1;
    }

    const head = findHead(k, lo);
    if (head === null && mode !== "table") continue;
    out.push({
      varName: head?.name ?? "",
      name: code.slice(nameStart, nameEnd),
      parenIdx,
      start: head?.start ?? k,
      enumBody,
    });
    lo = end;
  }
  return out;
}

/**
 * Open call scans that share one quote state, kept as a binary min-heap ordered by depth.
 * Every scan in a group sees the same "(" / ")" characters, so their depths all move together:
 * a scan is stored as `depth - offset` and the group's `offset` is the shared running delta.
 */
class OpenScans {
  readonly keys: number[] = [];
  readonly starts: number[] = [];
  offset = 0;

  push(key: number, start: number): void {
    let i = this.keys.length;
    this.keys.push(key);
    this.starts.push(start);
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (this.keys[parent] <= key) break;
      this.keys[i] = this.keys[parent];
      this.starts[i] = this.starts[parent];
      i = parent;
    }
    this.keys[i] = key;
    this.starts[i] = start;
  }

  /** Removes the scan at the top of the heap and returns its start index. */
  pop(): number {
    const top = this.starts[0];
    const key = this.keys.pop() ?? 0;
    const start = this.starts.pop() ?? 0;
    const n = this.keys.length;
    if (n > 0) {
      let i = 0;
      for (;;) {
        let child = 2 * i + 1;
        if (child >= n) break;
        if (child + 1 < n && this.keys[child + 1] < this.keys[child]) child++;
        if (this.keys[child] >= key) break;
        this.keys[i] = this.keys[child];
        this.starts[i] = this.starts[child];
        i = child;
      }
      this.keys[i] = key;
      this.starts[i] = start;
    }
    return top;
  }

  /** Merges two groups by moving the smaller heap into the larger one. */
  absorb(other: OpenScans): OpenScans {
    const [big, small] = this.keys.length >= other.keys.length ? [this, other] : [other, this];
    for (let i = 0; i < small.keys.length; i++) {
      big.push(small.keys[i] + small.offset - big.offset, small.starts[i]);
    }
    return big;
  }
}

/**
 * Index of the ")" closing the call whose "(" is at each start (-1 when it never closes).
 *
 * Equivalent to scanning forward from every start with a depth counter and a quote state (a quote
 * closes only on the same character not preceded by a backslash; an opening quote is never
 * checked for a preceding backslash). The quote state evolves independently of the depth, so all
 * scans in the same quote state share one pass: a single left-to-right sweep keeps four groups
 * (no quote, ' , " and backtick) of open scans in depth-ordered heaps, instead of rescanning to
 * the end of the input for every start. Mirrors `_balanced_call_ends` in the Python adapter.
 */
function balancedCallEnds(code: string, starts: readonly number[]): Map<number, number> {
  const ends = new Map<number, number>();
  const pending = [...new Set(starts)].sort((a, b) => a - b);
  if (pending.length === 0) return ends;
  let outside = new OpenScans();
  const inside = new Map<string, OpenScans>([
    ["'", new OpenScans()],
    ['"', new OpenScans()],
    ["`", new OpenScans()],
  ]);
  let active = 0;
  let nextStart = 0;
  let index = pending[0];
  while (index < code.length) {
    if (nextStart < pending.length && pending[nextStart] === index) {
      outside.push(-outside.offset, index);
      active++;
      nextStart++;
    } else if (active === 0) {
      if (nextStart >= pending.length) break;
      index = pending[nextStart];
      continue;
    }
    const ch = code[index];
    const quoted = inside.get(ch);
    if (quoted) {
      if (code[index - 1] === "\\") {
        // Escaped: scans inside this quote stay in it; the others open it as well.
        inside.set(ch, outside.absorb(quoted));
        outside = new OpenScans();
      } else {
        inside.set(ch, outside);
        outside = quoted;
      }
    } else if (ch === "(") {
      outside.offset++;
    } else if (ch === ")") {
      outside.offset--;
      while (outside.keys.length > 0 && outside.keys[0] + outside.offset === 0) {
        ends.set(outside.pop(), index);
        active--;
      }
    }
    index++;
  }
  for (const start of pending) if (!ends.has(start)) ends.set(start, -1);
  return ends;
}

export function fromDrizzle(
  source: string | Record<string, unknown> | unknown[],
  options?: AdapterOptions,
): TableSchema[] {
  const defaultSchema = options?.defaultSchema || "public";

  // 1. Runtime table objects
  if (typeof source === "object" && source !== null) {
    const tables: TableSchema[] = [];
    if (Array.isArray(source)) {
      for (let i = 0; i < source.length; i++) {
        const parsed = parseRuntimeDrizzleTable(`table_${i}`, source[i], defaultSchema);
        if (parsed) tables.push(parsed);
      }
    } else if ((source as DrizzleTableLike)[Symbol.for("drizzle:Name")] || (source as DrizzleTableLike)._?.name) {
      // Single table
      const parsed = parseRuntimeDrizzleTable("table", source, defaultSchema);
      if (parsed) tables.push(parsed);
    } else {
      // Map of tables { users: ..., orders: ... }
      for (const [key, val] of Object.entries(source)) {
        const parsed = parseRuntimeDrizzleTable(key, val, defaultSchema);
        if (parsed) tables.push(parsed);
      }
    }
    if (tables.length > 0) return tables;
  }

  // 2. Parse TypeScript source string
  const code = String(source);

  // Extract Enums
  const enums: Record<string, string[]> = {};
  for (const call of scanDrizzleCalls(code, "enum")) {
    const vals = (call.enumBody ?? "")
      .split(",")
      .map((v) => v.trim().replace(/^['"`]|['"`]$/g, ""))
      .filter(Boolean);
    enums[call.varName] = vals;
    enums[call.name] = vals;
  }

  // Map variable names to table names
  const tableVarToName: Record<string, string> = {};
  for (const call of scanDrizzleCalls(code, "varTable")) {
    tableVarToName[call.varName] = call.name;
  }

  const tables: TableSchema[] = [];

  const headers = scanDrizzleCalls(code, "table");
  const callEnds = balancedCallEnds(
    code,
    headers.map((h) => h.parenIdx),
  );

  // A pgTable header inside the argument list of a call that was already parsed is not a new
  // table (tables are never nested in valid code). Skipping it parses every argument list once,
  // which keeps the whole pass linear. Mirrors `consumed_end` in the Python adapter.
  let consumedEnd = 0;
  for (const header of headers) {
    if (header.start < consumedEnd) continue;
    const varName = header.varName;
    const tableName = header.name;
    const callStartIdx = header.parenIdx;

    // Balanced parentheses of the full call (all headers resolved in one sweep)
    const callEndIdx = callEnds.get(callStartIdx) ?? -1;
    if (callEndIdx === -1) continue;
    consumedEnd = callEndIdx + 1;

    const argsContent = code.slice(callStartIdx + 1, callEndIdx);
    const args: string[] = [];
    let argDepth = 0;
    let argQuote: string | null = null;
    let currArg: string[] = [];
    for (let i = 0; i < argsContent.length; i++) {
      const ch = argsContent[i];
      if (argQuote) {
        if (ch === argQuote && argsContent[i - 1] !== "\\") argQuote = null;
        currArg.push(ch);
      } else if (ch === "'" || ch === '"' || ch === "`") {
        argQuote = ch;
        currArg.push(ch);
      } else if (ch === "(" || ch === "{" || ch === "[") {
        argDepth++;
        currArg.push(ch);
      } else if (ch === ")" || ch === "}" || ch === "]") {
        argDepth--;
        currArg.push(ch);
      } else if (ch === "," && argDepth === 0) {
        args.push(currArg.join("").trim());
        currArg = [];
      } else {
        currArg.push(ch);
      }
    }
    if (currArg.length > 0) args.push(currArg.join("").trim());

    const columnsBlock = args[1] ? args[1].replace(/^\s*\{|\}\s*$/g, "") : "";
    const extraBlock = args[2] || "";

    if (varName) {
      tableVarToName[varName] = tableName;
    }

    const columns: ColumnSchema[] = [];
    const foreignKeys: ForeignKey[] = [];
    let primaryKeys: string[] = [];
    const colPropToName: Record<string, string> = {};

    // Split columns by comma or newline with parenthesis balancing
    const colLines: string[] = [];
    let current: string[] = [];
    let colDepth = 0;
    for (const char of columnsBlock) {
      if (char === "(" || char === "{" || char === "[") colDepth++;
      else if (char === ")" || char === "}" || char === "]") colDepth--;
      if ((char === "," || char === "\n") && colDepth === 0) {
        const chunk = current.join("").trim();
        if (chunk) colLines.push(chunk);
        current = [];
      } else {
        current.push(char);
      }
    }
    if (current.length > 0) {
      const chunk = current.join("").trim();
      if (chunk) colLines.push(chunk);
    }

    for (const rawLine of colLines) {
      const colDef = rawLine.split("//")[0].trim();
      if (!colDef || !colDef.includes(":")) continue;

      const [propNameRaw, exprRaw] = colDef.split(/:(.+)/);
      const propName = propNameRaw.trim();
      const expr = (exprRaw || "").trim();

      const callM = /(?<!\w)(\w+)\s*\(\s*(?:['"`]([^'"`]*)['"`])?/.exec(expr);
      if (!callM) continue;

      const rawType = callM[1];
      const sqlColName = callM[2] || propName;
      colPropToName[propName] = sqlColName;

      const isPk = expr.includes(".primaryKey(") || rawType.toLowerCase() === "serial";
      if (isPk && !primaryKeys.includes(sqlColName)) {
        primaryKeys.push(sqlColName);
      }

      const isNotNull = expr.includes(".notNull(") || isPk;
      const isNullable = !isNotNull;

      let defaultVal: unknown = undefined;
      if (expr.includes(".defaultNow(")) {
        defaultVal = "now()";
      } else {
        const defM = /\.default\(([^)]+)\)/.exec(expr);
        if (defM) {
          const rawDef = defM[1].trim();
          if (
            (rawDef.startsWith('"') && rawDef.endsWith('"')) ||
            (rawDef.startsWith("'") && rawDef.endsWith("'"))
          ) {
            defaultVal = rawDef.slice(1, -1);
          } else if (rawDef.toLowerCase() === "true" || rawDef.toLowerCase() === "false") {
            defaultVal = rawDef.toLowerCase() === "true";
          } else if (/^\d+$/.test(rawDef)) {
            defaultVal = parseInt(rawDef, 10);
          } else {
            defaultVal = rawDef;
          }
        }
      }

      let colEnums: string[] | undefined;
      let dataType: string;
      if (enums[rawType]) {
        dataType = "string";
        colEnums = enums[rawType];
      } else {
        dataType = DRIZZLE_TYPE_MAP[rawType.toLowerCase()] || normalizeDataType(rawType);
      }

      let fk: ForeignKey | undefined;
      const refM = /\.references\(\s*\(\)\s*=>\s*(\w+)\.(\w+)/.exec(expr);
      if (refM) {
        const tgtVar = refM[1];
        const tgtColProp = refM[2];
        const tgtTable = tableVarToName[tgtVar] || tgtVar;
        fk = {
          table: tableName,
          column: sqlColName,
          foreignTable: tgtTable,
          foreignColumn: tgtColProp,
        };
        foreignKeys.push(fk);
      }

      columns.push({
        name: sqlColName,
        dataType,
        data_type: dataType,
        isNullable,
        is_nullable: isNullable,
        isPrimary: isPk,
        is_primary: isPk,
        default: defaultVal,
        enums: colEnums,
        foreignKey: fk,
        foreign_key: fk,
      });
    }

    // Check composite primary keys in extra block
    if (extraBlock && extraBlock.includes("primaryKey(")) {
      let rawCols = "";
      const colListM = /columns\s*:\s*\[([^\]]+)\]/.exec(extraBlock);
      if (colListM) {
        rawCols = colListM[1];
      } else {
        const pkPosM = /primaryKey\(([^)]+)\)/.exec(extraBlock);
        if (pkPosM) rawCols = pkPosM[1];
      }
      if (rawCols) {
        const extraPks = rawCols
          .split(",")
          .map((c) => {
            const clean = c.replace(/[^a-zA-Z0-9_.]/g, "").split(".").pop()?.trim() || "";
            return colPropToName[clean] || clean;
          })
          .filter(Boolean);
        if (extraPks.length > 0) {
          primaryKeys = extraPks;
          for (const col of columns) {
            if (primaryKeys.includes(col.name)) {
              col.isPrimary = true;
              col.is_primary = true;
            }
          }
        }
      }
    }

    const tableEnums: Record<string, string[]> = {};
    for (const c of columns) {
      if (c.enums) tableEnums[c.name] = c.enums;
    }

    tables.push({
      name: tableName,
      schema: defaultSchema,
      columns,
      primaryKeys,
      foreignKeys,
      enums: tableEnums,
    });
  }

  // Post-process foreign keys
  for (const tbl of tables) {
    const fks = tbl.foreignKeys!;
    for (const fk of fks) {
      const targetTable = tables.find((t) => t.name === fk.foreignTable);
      if (targetTable) {
        const fCol = fk.foreignColumn;
        const matched = targetTable.columns.find((c) => c.name === fCol);
        if (!matched) {
          const caseMatched = targetTable.columns.find((c) => c.name.toLowerCase() === fCol?.toLowerCase());
          if (caseMatched) {
            fk.foreignColumn = caseMatched.name;
            fk.foreign_column = caseMatched.name;
          }
        }
      }
    }
  }

  return tables;
}

export const SUPPORTED_DRIZZLE_DIALECTS = new Set(["postgres", "mysql", "sqlite"]);

export const DRIZZLE_DIALECT_ALIASES: Record<string, string> = {
  postgresql: "postgres",
};

/**
 * Converts a TableSchema array, SchemaSnapshot, or metadata dictionary to Drizzle ORM TypeScript definitions.
 *
 * Generates:
 * - Dialect-specific core imports (drizzle-orm/pg-core, mysql-core, sqlite-core)
 * - Typed table declarations (pgTable, mysqlTable, sqliteTable)
 * - Column creators, serial/autoincrement primary keys
 * - Foreign key constraints via .references(() => targetTable.col)
 * - .notNull() chained modifiers
 */
export function toDrizzle(
  snapshot: TableSchema[] | SchemaSnapshot | Record<string, unknown>,
  options?: ToDrizzleOptions | string,
): string {
  const rawDialect =
    typeof options === "string"
      ? options
      : options?.dialect || "postgres";
  let cleanDialect = rawDialect.toLowerCase().trim();
  cleanDialect = DRIZZLE_DIALECT_ALIASES[cleanDialect] || cleanDialect;

  if (!SUPPORTED_DRIZZLE_DIALECTS.has(cleanDialect)) {
    throw new Error(
      `Unsupported Drizzle dialect '${rawDialect}'. Supported: ('postgres', 'mysql', 'sqlite')`,
    );
  }

  const { tables, foreignKeys } = extractSnapshotData(snapshot);

  let importStmt: string;
  let tableCreator: string;

  if (cleanDialect === "postgres") {
    importStmt =
      "import { bigint, boolean, doublePrecision, integer, jsonb, numeric, " +
      'pgTable, primaryKey, serial, text, timestamp, varchar } from "drizzle-orm/pg-core";';
    tableCreator = "pgTable";
  } else if (cleanDialect === "mysql") {
    importStmt =
      "import { bigint, boolean, decimal, double, int, json, " +
      'mysqlTable, primaryKey, serial, text, timestamp, varchar } from "drizzle-orm/mysql-core";';
    tableCreator = "mysqlTable";
  } else {
    // sqlite
    importStmt =
      'import { blob, integer, primaryKey, real, sqliteTable, text } from "drizzle-orm/sqlite-core";';
    tableCreator = "sqliteTable";
  }

  const tableEntries = Object.entries(tables);
  if (tableEntries.length === 0) {
    return importStmt;
  }

  // Build FK index: `${table}.${column}` -> [foreign_table, foreign_column]
  const fkLookup: Record<string, [string, string]> = {};
  for (const fk of foreignKeys) {
    if (tables[fk.table] && tables[fk.foreign_table]) {
      fkLookup[`${fk.table}.${fk.column}`] = [fk.foreign_table, fk.foreign_column];
    }
  }

  const tableBlocks: string[] = [];

  for (const [tableName, tableInfo] of tableEntries) {
    const tableVar = toCamelCase(tableName);
    const columns = tableInfo.columns;

    const pkColumns = columns.filter((c) => Boolean(c.is_primary));
    const isCompositePk = pkColumns.length > 1;

    const colLines: string[] = [];
    for (const col of columns) {
      const cName = col.name;
      const cType = col.data_type.toLowerCase();
      const isPk = Boolean(col.is_primary);
      const isNullable = Boolean(col.is_nullable);
      const colVar = toCamelCase(cName);

      const isInt = ["int", "serial", "smallint", "tinyint"].some((t) => cType.includes(t));
      const isBigint = ["bigint", "bigserial"].some((t) => cType.includes(t));

      let expr: string;

      if (cleanDialect === "postgres") {
        if (isPk && !isCompositePk && isInt) {
          expr = `serial("${cName}").primaryKey()`;
        } else if (isPk && !isCompositePk) {
          expr = `text("${cName}").primaryKey()`;
        } else if (isBigint) {
          expr = `bigint("${cName}", { mode: "number" })`;
        } else if (isInt) {
          expr = `integer("${cName}")`;
        } else if (["bool", "boolean"].some((t) => cType.includes(t))) {
          expr = `boolean("${cName}")`;
        } else if (["float", "double", "real"].some((t) => cType.includes(t))) {
          expr = `doublePrecision("${cName}")`;
        } else if (["decimal", "numeric", "money"].some((t) => cType.includes(t))) {
          expr = `numeric("${cName}")`;
        } else if (["datetime", "timestamp", "date", "time"].some((t) => cType.includes(t))) {
          expr = `timestamp("${cName}")`;
        } else if (["json", "jsonb"].some((t) => cType.includes(t))) {
          expr = `jsonb("${cName}")`;
        } else if (cType.includes("varchar")) {
          expr = `varchar("${cName}", { length: 255 })`;
        } else {
          expr = `text("${cName}")`;
        }
      } else if (cleanDialect === "mysql") {
        if (isPk && !isCompositePk && isInt) {
          expr = `serial("${cName}").primaryKey()`;
        } else if (isPk && !isCompositePk) {
          expr = `varchar("${cName}", { length: 255 }).primaryKey()`;
        } else if (isBigint) {
          expr = `bigint("${cName}", { mode: "number" })`;
        } else if (isInt) {
          expr = `int("${cName}")`;
        } else if (["bool", "boolean"].some((t) => cType.includes(t))) {
          expr = `boolean("${cName}")`;
        } else if (["float", "double", "real"].some((t) => cType.includes(t))) {
          expr = `double("${cName}")`;
        } else if (["decimal", "numeric", "money"].some((t) => cType.includes(t))) {
          expr = `decimal("${cName}", { precision: 10, scale: 2 })`;
        } else if (["datetime", "timestamp", "date", "time"].some((t) => cType.includes(t))) {
          expr = `timestamp("${cName}")`;
        } else if (["json", "jsonb"].some((t) => cType.includes(t))) {
          expr = `json("${cName}")`;
        } else {
          expr = `varchar("${cName}", { length: 255 })`;
        }
      } else {
        // sqlite
        if (isPk && !isCompositePk && isInt) {
          expr = `integer("${cName}").primaryKey({ autoIncrement: true })`;
        } else if (isPk && !isCompositePk) {
          expr = `text("${cName}").primaryKey()`;
        } else if (isInt || isBigint) {
          expr = `integer("${cName}")`;
        } else if (["bool", "boolean"].some((t) => cType.includes(t))) {
          expr = `integer("${cName}", { mode: "boolean" })`;
        } else if (["float", "double", "real", "decimal", "numeric"].some((t) => cType.includes(t))) {
          expr = `real("${cName}")`;
        } else if (["blob", "bytea", "binary"].some((t) => cType.includes(t))) {
          expr = `blob("${cName}")`;
        } else {
          expr = `text("${cName}")`;
        }
      }

      // Foreign key chaining
      const fkKey = `${tableName}.${cName}`;
      if (fkLookup[fkKey]) {
        const [tgtTbl, tgtCol] = fkLookup[fkKey];
        if (tables[tgtTbl]) {
          const tgtTblVar = toCamelCase(tgtTbl);
          const tgtColVar = toCamelCase(tgtCol);
          expr += `.references(() => ${tgtTblVar}.${tgtColVar})`;
        }
      }

      // Not-null chaining
      if (!isNullable && !isPk) {
        expr += ".notNull()";
      }

      colLines.push(`  ${colVar}: ${expr},`);
    }

    const body = colLines.join("\n");
    if (body) {
      if (isCompositePk) {
        const pkRefs = pkColumns.map((c) => `table.${toCamelCase(c.name)}`).join(", ");
        tableBlocks.push(
          `export const ${tableVar} = ${tableCreator}("${tableName}", {\n${body}\n}, (table) => ({\n  pk: primaryKey({ columns: [${pkRefs}] }),\n}));`,
        );
      } else {
        tableBlocks.push(
          `export const ${tableVar} = ${tableCreator}("${tableName}", {\n${body}\n});`,
        );
      }
    } else {
      tableBlocks.push(
        `export const ${tableVar} = ${tableCreator}("${tableName}", {});\n`,
      );
    }
  }

  const tablesContent = tableBlocks.join("\n\n");
  return `${importStmt}\n\n${tablesContent}`;
}

export const toDrizzleSchema = toDrizzle;

