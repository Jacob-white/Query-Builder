/**
 * Prisma Schema Adapter for React Query Builder.
 * Converts Prisma schema definitions (.prisma text or DMMF objects) into TableSchema[].
 */

import type { ColumnSchema, ForeignKey, TableSchema } from "../types";
import type { AdapterOptions } from "./types";
import { normalizeDataType } from "./utils";

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

export function fromPrisma(
  source: string | Record<string, any>,
  options?: AdapterOptions,
): TableSchema[] {
  const defaultSchema = options?.defaultSchema || "public";

  // Check if source is DMMF object
  if (typeof source === "object" && source !== null) {
    const datamodel = source.datamodel || source;
    const rawEnums = Array.isArray(datamodel.enums) ? datamodel.enums : [];
    const rawModels = Array.isArray(datamodel.models) ? datamodel.models : [];

    const enums: Record<string, string[]> = {};
    for (const e of rawEnums) {
      if (!e || !e.name) continue;
      enums[e.name] = (e.values || []).map((v: any) =>
        typeof v === "object" && v !== null ? v.name : String(v),
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
        if (typeof defaultVal === "object" && defaultVal !== null && defaultVal.name) {
          defaultVal = `${defaultVal.name}()`;
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
  const enumRegex = /enum\s+(\w+)\s*\{([^}]*)\}/g;
  let enumMatch: RegExpExecArray | null;
  while ((enumMatch = enumRegex.exec(text)) !== null) {
    const enumName = enumMatch[1];
    const enumBody = enumMatch[2];
    const values: string[] = [];
    for (const line of enumBody.split("\n")) {
      const clean = line.split("//")[0].trim();
      if (clean) values.push(clean);
    }
    enums[enumName] = values;
  }

  // 2. Map model name to table name
  const modelToTable: Record<string, string> = {};
  const modelRegex = /model\s+(\w+)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}/g;
  const modelsFound: { name: string; body: string }[] = [];
  let modelMatch: RegExpExecArray | null;
  while ((modelMatch = modelRegex.exec(text)) !== null) {
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
