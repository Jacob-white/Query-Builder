/**
 * Prisma Schema Adapter for React Query Builder.
 * Converts Prisma schema definitions (.prisma text or DMMF objects) into TableSchema[].
 */

import type { ColumnSchema, ForeignKey, SchemaSnapshot, TableSchema } from "../types";
import type { AdapterOptions, ToPrismaOptions } from "./types";
import {
  extractSnapshotData,
  normalizeDataType,
  toCamelCase,
  toPascalCase,
} from "./utils";


const PRISMA_TYPE_MAP: Record<string, string> = {
  int: "integer",
  bigint: "bigint",
  float: "float",
  decimal: "decimal",
  string: "text",
  boolean: "boolean",
  datetime: "timestamp",
  json: "json",
  bytes: "bytes",
};

/** Minimal structural shapes of the Prisma DMMF read by this adapter. */
interface PrismaDmmfField {
  kind?: string;
  name: string;
  dbName?: string | null;
  type?: string;
  isRequired?: boolean;
  isId?: boolean;
  default?: unknown;
  documentation?: string;
  relationFromFields?: string[];
  relationToFields?: string[];
}

interface PrismaDmmfModel {
  name?: string;
  dbName?: string | null;
  documentation?: string;
  primaryKey?: { fields?: string[] } | null;
  fields?: PrismaDmmfField[];
}

interface PrismaDmmfEnum {
  name?: string;
  values?: unknown[];
}

interface PrismaDatamodel {
  enums?: unknown;
  models?: unknown;
  datamodel?: PrismaDatamodel;
}

/**
 * Linear-time scanner for `enum NAME { ... }` blocks (`enum` + whitespace + identifier +
 * optional whitespace + "{" + body up to the first "}"). It replaces an unanchored regex whose
 * body run backtracked polynomially when the closing brace was missing. Matches never overlap and
 * are reported left to right; the position of the next "}" is cached so a missing terminator is
 * discovered once instead of once per "enum" keyword.
 */
function scanPrismaEnums(text: string): { name: string; body: string }[] {
  const out: { name: string; body: string }[] = [];
  const isSpace = (c: number): boolean =>
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
    c === 0xfeff;
  const isWord = (c: number): boolean =>
    (c >= 48 && c <= 57) || (c >= 65 && c <= 90) || (c >= 97 && c <= 122) || c === 95;
  const skipSpace = (from: number): number => {
    let i = from;
    while (i < text.length && isSpace(text.charCodeAt(i))) i++;
    return i;
  };

  let closeFrom = -1;
  let closeAt = -1;
  const nextClose = (from: number): number => {
    if (closeFrom === -1 || from < closeFrom || (closeAt !== -1 && from > closeAt)) {
      closeFrom = from;
      closeAt = text.indexOf("}", from);
    }
    return closeAt;
  };

  let pos = text.indexOf("enum");
  while (pos !== -1) {
    let i = skipSpace(pos + 4);
    const identStart = i;
    if (i > pos + 4) {
      while (i < text.length && isWord(text.charCodeAt(i))) i++;
      const identEnd = i;
      i = skipSpace(i);
      if (identEnd > identStart && text.charCodeAt(i) === 123) {
        const close = nextClose(i + 1);
        if (close === -1) return out;
        out.push({ name: text.slice(identStart, identEnd), body: text.slice(i + 1, close) });
        pos = text.indexOf("enum", close + 1);
        continue;
      }
    }
    pos = text.indexOf("enum", pos + 1);
  }
  return out;
}

export function fromPrisma(
  source: string | Record<string, unknown>,
  options?: AdapterOptions,
): TableSchema[] {
  const defaultSchema = options?.defaultSchema || "public";

  // Check if source is DMMF object
  if (typeof source === "object" && source !== null) {
    const dmmf = source as PrismaDatamodel;
    const datamodel = dmmf.datamodel || dmmf;
    const rawEnums: PrismaDmmfEnum[] = Array.isArray(datamodel.enums) ? datamodel.enums : [];
    const rawModels: PrismaDmmfModel[] = Array.isArray(datamodel.models) ? datamodel.models : [];

    const enums: Record<string, string[]> = {};
    for (const e of rawEnums) {
      if (!e || !e.name) continue;
      enums[e.name] = (e.values || []).map((v: unknown) =>
        typeof v === "object" && v !== null ? (v as { name: string }).name : String(v),
      );
    }

    const modelToTable: Record<string, string> = {};
    for (const m of rawModels) {
      if (!m || !m.name) continue;
      modelToTable[m.name] = m.dbName || m.name;
    }

    const tables: TableSchema[] = [];

    for (const m of rawModels) {
      if (!m || !m.name) continue;
      const tableName = m.dbName || m.name;
      const columns: ColumnSchema[] = [];
      const foreignKeys: ForeignKey[] = [];
      const primaryKeys: string[] = [];

      if (m.primaryKey && Array.isArray(m.primaryKey.fields)) {
        primaryKeys.push(...m.primaryKey.fields);
      }

      const relationMap: Record<string, [string, string]> = {};
      const fields = Array.isArray(m.fields) ? m.fields : [];

      for (const f of fields) {
        if (f.kind === "object") {
          const fromCols = f.relationFromFields || [];
          const toCols = f.relationToFields || [];
          const targetModel = f.type || "";
          const targetTable = modelToTable[targetModel] || targetModel;
          if (fromCols.length > 0 && toCols.length > 0) {
            relationMap[fromCols[0]] = [targetTable, toCols[0]];
          }
        }
      }

      for (const f of fields) {
        if (f.kind === "object") continue; // Virtual relation

        const colName = f.dbName || f.name || "";
        const rawType = f.type || "String";
        const isNullable = !f.isRequired;
        const isPrimary = Boolean(f.isId);
        if (isPrimary && !primaryKeys.includes(colName)) {
          primaryKeys.push(colName);
        }

        let defaultVal = f.default;
        if (
          typeof defaultVal === "object" &&
          defaultVal !== null &&
          (defaultVal as { name?: string }).name
        ) {
          defaultVal = `${(defaultVal as { name: string }).name}()`;
        }

        let colEnums: string[] | undefined;
        let dataType: string;
        if (f.kind === "enum" || enums[rawType]) {
          dataType = "string";
          colEnums = enums[rawType];
        } else {
          dataType = PRISMA_TYPE_MAP[rawType.toLowerCase()] || normalizeDataType(rawType);
        }

        let fk: ForeignKey | undefined;
        if (relationMap[f.name]) {
          const [tgtTable, tgtCol] = relationMap[f.name];
          fk = {
            table: tableName,
            column: colName,
            foreignTable: tgtTable,
            foreignColumn: tgtCol,
          };
          foreignKeys.push(fk);
        }

        columns.push({
          name: colName,
          dataType,
          data_type: dataType,
          isNullable,
          is_nullable: isNullable,
          isPrimary,
          is_primary: isPrimary,
          default: defaultVal,
          comment: f.documentation,
          enums: colEnums,
          foreignKey: fk,
          foreign_key: fk,
        });
      }

      const tableEnums: Record<string, string[]> = {};
      for (const c of columns) {
        if (c.enums) {
          tableEnums[c.name] = c.enums;
        }
      }

      tables.push({
        name: tableName,
        schema: defaultSchema,
        columns,
        primaryKeys,
        foreignKeys,
        enums: tableEnums,
        comment: m.documentation,
      });
    }

    return tables;
  }

  const text = String(source);

  // 1. Parse Enums
  const enums: Record<string, string[]> = {};
  for (const { name: enumName, body: enumBody } of scanPrismaEnums(text)) {
    const values: string[] = [];
    for (const line of enumBody.split("\n")) {
      const clean = line.split("//")[0].trim();
      if (clean) values.push(clean);
    }
    enums[enumName] = values;
  }

  // 2. Map model name to table name
  const modelToTable: Record<string, string> = {};
  const modelRegex = /model\s+(\w+)\s*\{([^}]*)\}/g;
  const modelsFound: { name: string; body: string }[] = [];
  let modelMatch: RegExpExecArray | null;
  // A model must end with "}", so nothing after the last "}" can match; trimming it keeps
  // unterminated "model X {" runs from being rescanned to the end of the text per header.
  const modelText = text.slice(0, text.lastIndexOf("}") + 1);
  while ((modelMatch = modelRegex.exec(modelText)) !== null) {
    const modelName = modelMatch[1];
    const modelBody = modelMatch[2];
    modelsFound.push({ name: modelName, body: modelBody });
    const mapM = /@@map\(\s*["']([^"']+)["']\s*\)/.exec(modelBody);
    modelToTable[modelName] = mapM ? mapM[1] : modelName;
  }

  const tables: TableSchema[] = [];

  for (const { name: modelName, body: modelBody } of modelsFound) {
    const mapM = /@@map\(\s*["']([^"']+)["']\s*\)/.exec(modelBody);
    const tableName = mapM ? mapM[1] : modelName;

    // Composite primary keys @@id([field1, field2])
    const primaryKeys: string[] = [];
    const pkM = /@@id\(\s*\[([^\]]+)\]\s*\)/.exec(modelBody);
    if (pkM) {
      primaryKeys.push(
        ...pkM[1]
          .split(",")
          .map((f) => f.trim())
          .filter(Boolean),
      );
    }

    // Scan relation directives
    const relationMap: Record<string, [string, string]> = {};
    const relRegex =
      /@relation\([^)]*fields\s*:\s*\[([^\]]+)\][^)]*references\s*:\s*\[([^\]]+)\][^)]*\)/;

    for (const line of modelBody.split("\n")) {
      const clean = line.split("//")[0].trim();
      if (!clean || clean.startsWith("@@")) continue;
      const relM = relRegex.exec(clean);
      if (relM) {
        const parts = clean.split(/\s+/);
        if (parts.length >= 2) {
          const relType = parts[1].replace("?", "").replace("[]", "");
          const targetTable = modelToTable[relType] || relType;
          const fromCols = relM[1].split(",").map((f) => f.trim());
          const toCols = relM[2].split(",").map((f) => f.trim());
          if (fromCols[0] && toCols[0]) {
            relationMap[fromCols[0]] = [targetTable, toCols[0]];
          }
        }
      }
    }

    const columns: ColumnSchema[] = [];
    const foreignKeys: ForeignKey[] = [];

    for (const line of modelBody.split("\n")) {
      let comment: string | undefined;
      if (line.includes("///")) {
        comment = line.split("///")[1].trim();
      }
      const clean = line.split("//")[0].trim();
      if (!clean || clean.startsWith("@@")) continue;

      const parts = clean.split(/\s+/);
      if (parts.length < 2) continue;

      const fieldName = parts[0];
      const rawType = parts[1];
      const baseType = rawType.replace("?", "").replace("[]", "");

      // If relation model reference, skip column creation
      if (modelToTable[baseType]) continue;

      const isNullable = rawType.endsWith("?");
      const colMapM = /@map\(\s*["']([^"']+)["']\s*\)/.exec(clean);
      const colName = colMapM ? colMapM[1] : fieldName;

      const isPrimary = clean.includes("@id") || primaryKeys.includes(fieldName);
      if (isPrimary && !primaryKeys.includes(colName)) {
        primaryKeys.push(colName);
      }

      let defaultVal: unknown = undefined;
      const defIdx = clean.indexOf("@default(");
      if (defIdx !== -1) {
        const start = defIdx + "@default(".length;
        let depth = 1;
        let end = start;
        while (end < clean.length && depth > 0) {
          if (clean[end] === "(") depth++;
          else if (clean[end] === ")") depth--;
          end++;
        }
        if (depth === 0) {
          const rawDef = clean.slice(start, end - 1).trim();
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
      if (enums[baseType]) {
        dataType = "string";
        colEnums = enums[baseType];
      } else {
        dataType = PRISMA_TYPE_MAP[baseType.toLowerCase()] || normalizeDataType(baseType);
      }

      let fk: ForeignKey | undefined;
      if (relationMap[fieldName] || relationMap[colName]) {
        const [tgtTable, tgtCol] = relationMap[fieldName] || relationMap[colName];
        fk = {
          table: tableName,
          column: colName,
          foreignTable: tgtTable,
          foreignColumn: tgtCol,
        };
        foreignKeys.push(fk);
      }

      columns.push({
        name: colName,
        dataType,
        data_type: dataType,
        isNullable,
        is_nullable: isNullable,
        isPrimary,
        is_primary: isPrimary,
        default: defaultVal,
        comment,
        enums: colEnums,
        foreignKey: fk,
        foreign_key: fk,
      });
    }

    const tableEnums: Record<string, string[]> = {};
    for (const c of columns) {
      if (c.enums) {
        tableEnums[c.name] = c.enums;
      }
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

  return tables;
}

export const SUPPORTED_PRISMA_PROVIDERS = new Set([
  "postgresql",
  "mysql",
  "sqlite",
  "sqlserver",
  "cockroachdb",
  "mongodb",
]);

export const PRISMA_PROVIDER_ALIASES: Record<string, string> = {
  postgres: "postgresql",
  mssql: "sqlserver",
};

/**
 * Converts a TableSchema array, SchemaSnapshot, or metadata dictionary to a Prisma schema (.prisma).
 *
 * Generates:
 * - datasource db block with configured provider and url = env("DATABASE_URL")
 * - generator client block
 * - Typed model declarations with @id, @default(autoincrement()), nullability (?)
 * - Bidirectional @relation directives with matching back-relations
 * - Field-level @map and model-level @@map attributes
 */
export function toPrisma(
  snapshot: TableSchema[] | SchemaSnapshot | Record<string, unknown>,
  options?: ToPrismaOptions | string,
): string {
  const rawProvider =
    typeof options === "string"
      ? options
      : options?.provider || "postgresql";
  let cleanProvider = rawProvider.toLowerCase().trim();
  cleanProvider = PRISMA_PROVIDER_ALIASES[cleanProvider] || cleanProvider;

  if (!SUPPORTED_PRISMA_PROVIDERS.has(cleanProvider)) {
    const supported = Array.from(SUPPORTED_PRISMA_PROVIDERS).sort();
    throw new Error(
      `Unsupported Prisma provider '${rawProvider}'. Supported: [${supported.map((s) => `'${s}'`).join(", ")}]`,
    );
  }

  const { tables, foreignKeys } = extractSnapshotData(snapshot);

  const header =
    "datasource db {\n" +
    `  provider = "${cleanProvider}"\n` +
    '  url      = env("DATABASE_URL")\n' +
    "}\n\n" +
    "generator client {\n" +
    '  provider = "prisma-client-js"\n' +
    "}";

  const tableEntries = Object.entries(tables);
  if (tableEntries.length === 0) {
    return header;
  }

  // Index foreign keys
  // outgoing: table -> list of fks
  // incoming: foreign_table -> list of fks
  const outgoingFks: Record<string, typeof foreignKeys> = {};
  const incomingFks: Record<string, typeof foreignKeys> = {};
  const relCounts: Record<string, number> = {};

  for (const tName of Object.keys(tables)) {
    outgoingFks[tName] = [];
    incomingFks[tName] = [];
  }

  for (const fk of foreignKeys) {
    const src = fk.table;
    const tgt = fk.foreign_table;
    if (tables[src] && tables[tgt]) {
      outgoingFks[src].push(fk);
      incomingFks[tgt].push(fk);
      const pair = `${src}->${tgt}`;
      relCounts[pair] = (relCounts[pair] || 0) + 1;
    }
  }

  const modelBlocks: string[] = [];

  for (const [tableName, tableInfo] of tableEntries) {
    const modelName = toPascalCase(tableName);
    const columns = tableInfo.columns;
    const lines: string[] = [];

    const pkColumns = columns.filter((c) => Boolean(c.is_primary));
    const isCompositePk = pkColumns.length > 1;

    // 1. Scalar column definitions
    for (const col of columns) {
      const cName = col.name;
      const cType = col.data_type.toLowerCase();
      const isPk = Boolean(col.is_primary);
      const isNullable = Boolean(col.is_nullable);

      const fieldName = toCamelCase(cName);

      // Map SQL type to Prisma type
      let prismaType = "String";
      if (cType.includes("bigint") || cType.includes("bigserial")) {
        prismaType = "BigInt";
      } else if (["int", "serial", "smallint", "tinyint"].some((t) => cType.includes(t))) {
        prismaType = "Int";
      } else if (["bool", "boolean"].some((t) => cType.includes(t))) {
        prismaType = "Boolean";
      } else if (["float", "double", "real"].some((t) => cType.includes(t))) {
        prismaType = "Float";
      } else if (["decimal", "numeric", "money"].some((t) => cType.includes(t))) {
        prismaType = "Decimal";
      } else if (["datetime", "timestamp", "date", "time"].some((t) => cType.includes(t))) {
        prismaType = "DateTime";
      } else if (["json", "jsonb"].some((t) => cType.includes(t))) {
        prismaType = "Json";
      } else if (["bytea", "blob", "binary", "varbinary"].some((t) => cType.includes(t))) {
        prismaType = "Bytes";
      } else {
        prismaType = "String";
      }

      // Directives
      const directives: string[] = [];
      let typeSuffix = "";
      if (isPk) {
        if (!isCompositePk) {
          directives.push("@id");
          if (prismaType === "Int") {
            directives.push("@default(autoincrement())");
          }
        }
        typeSuffix = "";
      } else {
        typeSuffix = isNullable ? "?" : "";
      }

      if (fieldName !== cName) {
        directives.push(`@map("${cName}")`);
      }

      const directiveStr = directives.length > 0 ? ` ${directives.join(" ")}` : "";
      lines.push(`  ${fieldName} ${prismaType}${typeSuffix}${directiveStr}`);
    }

    // 2. Outgoing relation fields
    for (const fk of outgoingFks[tableName]) {
      const srcCol = fk.column;
      const tgtTbl = fk.foreign_table;
      const tgtCol = fk.foreign_column;
      const targetModel = toPascalCase(tgtTbl);
      const srcField = toCamelCase(srcCol);
      const tgtField = toCamelCase(tgtCol);

      // Determine relation field name
      let baseRel: string;
      if (srcCol.toLowerCase().endsWith("_id")) {
        baseRel = toCamelCase(srcCol.slice(0, -3));
      } else if (srcCol.toLowerCase().endsWith("id") && srcCol.length > 2) {
        baseRel = toCamelCase(srcCol.slice(0, -2));
      } else {
        baseRel = toCamelCase(tgtTbl);
      }

      // If clashes with existing scalar field name, disambiguate
      let relFieldName = baseRel;
      const scalarNames = new Set(columns.map((c) => toCamelCase(c.name)));
      if (scalarNames.has(relFieldName)) {
        relFieldName = `${baseRel}Rel`;
      }

      const colMeta = columns.find((c) => c.name === srcCol);
      const relNullable =
        colMeta && !colMeta.is_primary ? Boolean(colMeta.is_nullable) : false;
      const relSuffix = relNullable ? "?" : "";

      const pairKey = `${tableName}->${tgtTbl}`;
      const isSelf = tableName === tgtTbl;
      const isMulti = relCounts[pairKey] > 1 || isSelf;
      const relNameTag = isMulti ? `"${targetModel}_${srcField}", ` : "";

      lines.push(
        `  ${relFieldName} ${targetModel}${relSuffix} @relation(${relNameTag}fields: [${srcField}], references: [${tgtField}])`,
      );
    }

    // 3. Incoming back-relations
    for (const fk of incomingFks[tableName]) {
      const srcTbl = fk.table;
      const srcCol = fk.column;
      const sourceModel = toPascalCase(srcTbl);
      const srcField = toCamelCase(srcCol);

      const pairKey = `${srcTbl}->${tableName}`;
      const isSelf = srcTbl === tableName;
      const isMulti = relCounts[pairKey] > 1 || isSelf;

      let backField: string;
      let relTag: string;
      if (isMulti) {
        backField = isSelf
          ? toCamelCase(`child_${srcTbl}_by_${srcCol}`)
          : toCamelCase(`${srcTbl}_by_${srcCol}`);
        relTag = ` @relation("${modelName}_${srcField}")`;
      } else {
        const baseBack = toCamelCase(srcTbl);
        backField = !baseBack.endsWith("s") ? `${baseBack}s` : `${baseBack}List`;
        relTag = "";
      }

      // Check collision with existing fields
      const existing = new Set(lines.map((l) => l.trim().split(/\s+/)[0]));
      if (existing.has(backField)) {
        backField = `${backField}Rel`;
      }

      lines.push(`  ${backField} ${sourceModel}[]${relTag}`);
    }

    // 4. Model level attributes (composite @@id and @@map)
    if (isCompositePk) {
      const pkFields = pkColumns.map((c) => toCamelCase(c.name)).join(", ");
      if (lines.length > 0) {
        lines.push("");
      }
      lines.push(`  @@id([${pkFields}])`);
    }

    if (modelName !== tableName) {
      if (lines.length > 0 && !lines[lines.length - 1].startsWith("  @@")) {
        lines.push("");
      }
      lines.push(`  @@map("${tableName}")`);
    }

    const body = lines.join("\n");
    if (body) {
      modelBlocks.push(`model ${modelName} {\n${body}\n}`);
    } else {
      modelBlocks.push(`model ${modelName} {\n}`);
    }
  }

  const modelsContent = modelBlocks.join("\n\n");
  return `${header}\n\n${modelsContent}`;
}

export const toPrismaSchema = toPrisma;

