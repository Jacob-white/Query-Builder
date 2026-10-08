/**
 * JSON Schema and OpenAPI 3.x Adapter for React Query Builder.
 * Converts JSON Schema (Draft 4/7/2020-12) or OpenAPI 3.x specifications into TableSchema[].
 */

import type { ColumnSchema, ForeignKey, TableSchema } from "../types";
import type { AdapterOptions } from "./types";
import { normalizeDataType } from "./utils";

const JSON_SCHEMA_TYPE_MAP: Record<string, string> = {
  string: "text",
  integer: "integer",
  number: "decimal",
  boolean: "boolean",
  object: "json",
  array: "json",
  null: "text",
};

/** Minimal structural shape of a JSON Schema / OpenAPI schema node (only what is read). */
interface JsonSchemaNode {
  type?: string | string[];
  format?: string;
  nullable?: boolean;
  $ref?: string;
  enum?: unknown[];
  default?: unknown;
  description?: string;
  title?: string;
  name?: string;
  required?: unknown;
  properties?: Record<string, unknown>;
  primary_keys?: unknown;
  primaryKey?: unknown;
  is_primary?: unknown;
  foreign_key?: unknown;
  components?: { schemas?: Record<string, unknown> };
  definitions?: Record<string, unknown>;
  $defs?: Record<string, unknown>;
  [key: string]: unknown;
}

function parseSingleJsonTable(
  tableName: string,
  schemaDef: JsonSchemaNode,
  defaultSchema: string,
): TableSchema {
  const properties = schemaDef.properties || {};
  const requiredCols = new Set<string>(
    Array.isArray(schemaDef.required) ? (schemaDef.required as string[]) : [],
  );

  const primaryKeys: string[] = [];
  if (Array.isArray(schemaDef["x-primary-keys"])) {
    primaryKeys.push(...(schemaDef["x-primary-keys"] as string[]));
  } else if (Array.isArray(schemaDef.primary_keys)) {
    primaryKeys.push(...(schemaDef.primary_keys as string[]));
  }

  const columns: ColumnSchema[] = [];
  const foreignKeys: ForeignKey[] = [];

  for (const [propName, propDefRaw] of Object.entries(properties)) {
    const propDef: JsonSchemaNode =
      typeof propDefRaw === "object" && propDefRaw !== null
        ? (propDefRaw as JsonSchemaNode)
        : { type: String(propDefRaw) };

    // Handle $ref
    let refFk: ForeignKey | undefined;
    if (propDef.$ref) {
      const refPath = String(propDef.$ref);
      const targetTable = refPath.split("/").pop() || "unknown";
      refFk = {
        table: tableName,
        column: propName,
        foreignTable: targetTable,
        foreignColumn: "id",
      };
      foreignKeys.push(refFk);
    }

    // Type resolution
    let rawType: string | string[] = propDef.type || "string";
    let hasNullType = false;
    if (Array.isArray(rawType)) {
      hasNullType = rawType.includes("null");
      const nonNull = rawType.filter((t: string) => t !== "null");
      rawType = nonNull[0] || "string";
    }

    const fmt = String(propDef.format || "").toLowerCase();
    let dataType: string;
    if (fmt === "date-time" || fmt === "datetime") dataType = "timestamp";
    else if (fmt === "date") dataType = "date";
    else if (fmt === "uuid") dataType = "uuid";
    else if (fmt === "int32") dataType = "integer";
    else if (fmt === "int64") dataType = "bigint";
    else if (fmt === "float" || fmt === "double") dataType = "float";
    else {
      dataType =
        JSON_SCHEMA_TYPE_MAP[String(rawType).toLowerCase()] ||
        normalizeDataType(String(rawType));
    }

    // Nullability
    const isRequired = requiredCols.has(propName);
    const isNullable =
      !isRequired || hasNullType || Boolean(propDef.nullable);

    // Primary key
    const isPk =
      primaryKeys.includes(propName) ||
      Boolean(propDef["x-primary-key"]) ||
      Boolean(propDef.primaryKey) ||
      Boolean(propDef.is_primary);

    if (isPk && !primaryKeys.includes(propName)) {
      primaryKeys.push(propName);
    }

    // Enums
    let colEnums: string[] | undefined;
    if (Array.isArray(propDef.enum)) {
      colEnums = propDef.enum.map(String);
      dataType = "string";
    }

    // Explicit foreign key
    let fk: ForeignKey | undefined = refFk;
    const fkRaw: unknown =
      propDef["x-foreign-key"] || propDef["x-references"] || propDef.foreign_key;
    if (fkRaw) {
      if (typeof fkRaw === "string" && fkRaw.includes(".")) {
        const [fTbl, fCol] = fkRaw.split(".");
        fk = {
          table: tableName,
          column: propName,
          foreignTable: fTbl,
          foreignColumn: fCol,
        };
        foreignKeys.push(fk);
      } else if (typeof fkRaw === "object" && fkRaw !== null) {
        fk = {
          table: tableName,
          column: propName,
          foreignTable: (fkRaw as { table?: string }).table || "",
          foreignColumn: (fkRaw as { column?: string }).column || "id",
        };
        foreignKeys.push(fk);
      }
    }

    columns.push({
      name: propName,
      dataType,
      data_type: dataType,
      isNullable,
      is_nullable: isNullable,
      isPrimary: isPk,
      is_primary: isPk,
      default: propDef.default,
      comment: propDef.description,
      enums: colEnums,
      foreignKey: fk,
      foreign_key: fk,
    });
  }

  // Fallback to 'id' primary key if none specified
  if (primaryKeys.length === 0 && columns.some((c) => c.name === "id")) {
    for (const c of columns) {
      if (c.name === "id") {
        c.isPrimary = true;
        c.is_primary = true;
        primaryKeys.push("id");
        break;
      }
    }
  }

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
    comment: schemaDef.description,
  };
}

export function fromJsonSchema(
  source: string | Record<string, unknown>,
  options?: AdapterOptions,
): TableSchema[] {
  const defaultSchema = options?.defaultSchema || "public";

  let rawData: JsonSchemaNode;
  if (typeof source === "string") {
    try {
      rawData = JSON.parse(source);
    } catch {
      rawData = { type: "object", properties: {} };
    }
  } else {
    rawData = (source || {}) as JsonSchemaNode;
  }

  const tables: TableSchema[] = [];

  // 1. OpenAPI 3.x components.schemas
  if (
    rawData.components &&
    typeof rawData.components === "object" &&
    rawData.components.schemas &&
    typeof rawData.components.schemas === "object"
  ) {
    for (const [name, def] of Object.entries(rawData.components.schemas)) {
      if (typeof def === "object" && def !== null) {
        tables.push(parseSingleJsonTable(name, def as JsonSchemaNode, defaultSchema));
      }
    }
    return tables;
  }

  // 2. JSON Schema $defs or definitions
  const defs = rawData.definitions || rawData.$defs;
  if (defs && typeof defs === "object") {
    for (const [name, def] of Object.entries(defs)) {
      if (typeof def === "object" && def !== null) {
        tables.push(parseSingleJsonTable(name, def as JsonSchemaNode, defaultSchema));
      }
    }
    return tables;
  }

  // 3. Dictionary of tables: { users: { properties: ... }, orders: { ... } }
  if (!rawData.properties && !rawData.type) {
    for (const [name, def] of Object.entries(rawData)) {
      if (typeof def === "object" && def !== null) {
        tables.push(parseSingleJsonTable(name, def as JsonSchemaNode, defaultSchema));
      }
    }
    return tables;
  }

  // 4. Single schema object
  const name = (rawData.title || rawData.name || "main") as string;
  tables.push(parseSingleJsonTable(name, rawData, defaultSchema));

  return tables;
}
