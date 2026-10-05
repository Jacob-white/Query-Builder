/**
 * Drizzle ORM Adapter for React Query Builder.
 * Converts Drizzle runtime table objects or TypeScript source code into TableSchema[].
 */

import type { ColumnSchema, ForeignKey, TableSchema } from "../types";
import type { AdapterOptions } from "./types";
import { normalizeDataType } from "./utils";

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

function parseRuntimeDrizzleTable(
  nameOrKey: string,
  tableObj: any,
  defaultSchema: string,
): TableSchema | null {
  if (!tableObj || typeof tableObj !== "object") return null;

  // Resolve table name
  const nameSymbol = Symbol.for("drizzle:Name");
  const tableName =
    tableObj[nameSymbol] ||
    tableObj._?.name ||
    tableObj.name ||
    nameOrKey;

  // Resolve columns
  const colsSymbol = Symbol.for("drizzle:Columns");
  const rawCols = tableObj[colsSymbol] || tableObj._?.columns || tableObj;

  const columns: ColumnSchema[] = [];
  const foreignKeys: ForeignKey[] = [];
  const primaryKeys: string[] = [];

  for (const [key, col] of Object.entries(rawCols)) {
    if (!col || typeof col !== "object" || key.startsWith("_") || key.startsWith("$")) {
      continue;
    }
    const colName = (col as any).name || key;
    const isPk = Boolean((col as any).primary || (col as any).isPrimaryKey);
    if (isPk) primaryKeys.push(colName);

    const isNotNull = Boolean((col as any).notNull || isPk);
    const isNullable = !isNotNull;

    const rawType = (col as any).dataType || (col as any).columnType || "text";
    const enumValues = (col as any).enumValues as string[] | undefined;

    let dataType: string;
    let enums: string[] | undefined;
    if (Array.isArray(enumValues) && enumValues.length > 0) {
      dataType = "string";
      enums = enumValues;
    } else {
      dataType = DRIZZLE_TYPE_MAP[String(rawType).toLowerCase()] || normalizeDataType(String(rawType));
    }

    let fk: ForeignKey | undefined;
    if (typeof (col as any).references === "function") {
      try {
        const refTarget = (col as any).references();
        if (refTarget && typeof refTarget === "object") {
          const targetTable = refTarget.table?.[nameSymbol] || refTarget.table?._?.name || refTarget.table?.name || "unknown";
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
      default: (col as any).default,
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

export function fromDrizzle(
  source: string | Record<string, any> | any[],
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
    } else if ((source as any)[Symbol.for("drizzle:Name")] || (source as any)._?.name) {
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
  const enumRegex = /(?:export\s+)?const\s+(\w+)\s*=\s*(?:pgEnum|mysqlEnum|sqliteEnum)\(\s*['"`]([^'"`]+)['"`]\s*,\s*\[([^\]]+)\]/g;
  let enumM: RegExpExecArray | null;
  while ((enumM = enumRegex.exec(code)) !== null) {
    const varName = enumM[1];
    const enumDbName = enumM[2];
    const vals = enumM[3]
      .split(",")
      .map((v) => v.trim().replace(/^['"`]|['"`]$/g, ""))
      .filter(Boolean);
    enums[varName] = vals;
    enums[enumDbName] = vals;
  }

  // Map variable names to table names
  const tableVarToName: Record<string, string> = {};
  const varTableRegex = /(?:export\s+)?const\s+(\w+)\s*(?::\s*[^=]+)?=\s*(?:pgTable|mysqlTable|sqliteTable)\(\s*['"`]([^'"`]+)['"`]/g;
  let varM: RegExpExecArray | null;
  while ((varM = varTableRegex.exec(code)) !== null) {
    tableVarToName[varM[1]] = varM[2];
  }

  const tables: TableSchema[] = [];
  const tableHeaderRegex = /(?:(?:export\s+)?const\s+(\w+)\s*(?::\s*[^=]+)?=\s*)?(?:pgTable|mysqlTable|sqliteTable)\s*\(\s*['"`]([^'"`]+)['"`]/g;

  let headerMatch: RegExpExecArray | null;
  while ((headerMatch = tableHeaderRegex.exec(code)) !== null) {
    const varName = headerMatch[1] || "";
    const tableName = headerMatch[2];
    const callStartIdx = code.indexOf("(", headerMatch.index);
    if (callStartIdx === -1) continue;

    // Balance parentheses to find full call
    let depth = 0;
    let inQuote: string | null = null;
    let callEndIdx = -1;
    for (let i = callStartIdx; i < code.length; i++) {
      const ch = code[i];
      if (inQuote) {
        if (ch === inQuote && code[i - 1] !== "\\") {
          inQuote = null;
        }
      } else if (ch === "'" || ch === '"' || ch === "`") {
        inQuote = ch;
      } else if (ch === "(") {
        depth++;
      } else if (ch === ")") {
        depth--;
        if (depth === 0) {
          callEndIdx = i;
          break;
        }
      }
    }
    if (callEndIdx === -1) continue;

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

      const callM = /(\w+)\s*\(\s*(?:['"`]([^'"`]*)['"`])?/.exec(expr);
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
    const fks = tbl.foreignKeys || tbl.foreign_keys || [];
    for (const fk of fks) {
      const targetTable = tables.find((t) => t.name === (fk.foreignTable || fk.foreign_table));
      if (targetTable) {
        const fCol = fk.foreignColumn || fk.foreign_column;
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
