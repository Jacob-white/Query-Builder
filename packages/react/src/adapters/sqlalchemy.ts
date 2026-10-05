/**
 * SQLAlchemy Adapter for React Query Builder.
 * Converts SQLAlchemy Python model source code or serialized metadata into TableSchema[].
 */

import type { ColumnSchema, ForeignKey, TableSchema } from "../types";
import type { AdapterOptions } from "./types";
import { normalizeDataType } from "./utils";

const SQLALCHEMY_TYPE_MAP: Record<string, string> = {
  integer: "integer",
  int: "integer",
  smallinteger: "integer",
  biginteger: "bigint",
  string: "text",
  text: "text",
  unicode: "text",
  unicodetext: "text",
  varchar: "text",
  char: "text",
  boolean: "boolean",
  datetime: "timestamp",
  date: "date",
  time: "time",
  timestamp: "timestamp",
  float: "float",
  numeric: "decimal",
  decimal: "decimal",
  json: "json",
  uuid: "uuid",
  largebinary: "bytes",
};

export function fromSqlAlchemy(
  source: string | Record<string, any>,
  options?: AdapterOptions,
): TableSchema[] {
  const defaultSchema = options?.defaultSchema || "public";

  // 1. If source is an object / serialized metadata dict
  if (typeof source === "object" && source !== null) {
    const rawTables = source.tables || source;
    const tables: TableSchema[] = [];

    for (const [tblName, tblDef] of Object.entries(rawTables)) {
      if (!tblDef || typeof tblDef !== "object") continue;
      const columns: ColumnSchema[] = [];
      const primaryKeys: string[] = (tblDef as any).primary_keys || [];
      const foreignKeys: ForeignKey[] = (tblDef as any).foreign_keys || [];

      const rawCols = (tblDef as any).columns;
      if (Array.isArray(rawCols)) {
        for (const c of rawCols) {
          const colName = c.name || "";
          const isPk = Boolean(c.is_primary || c.primary_key || c.isPrimary);
          if (isPk && !primaryKeys.includes(colName)) primaryKeys.push(colName);
          const rawType = c.data_type || c.dataType || c.type || "text";
          const dataType = SQLALCHEMY_TYPE_MAP[String(rawType).toLowerCase()] || normalizeDataType(String(rawType));
          columns.push({
            name: colName,
            dataType,
            data_type: dataType,
            isNullable: c.is_nullable !== undefined ? c.is_nullable : !isPk,
            is_nullable: c.is_nullable !== undefined ? c.is_nullable : !isPk,
            isPrimary: isPk,
            is_primary: isPk,
            default: c.default,
            comment: c.comment,
            enums: c.enums,
          });
        }
      }

      tables.push({
        name: tblName,
        schema: (tblDef as any).schema || defaultSchema,
        columns,
        primaryKeys,
        foreignKeys,
        comment: (tblDef as any).comment,
      });
    }

    if (tables.length > 0) return tables;
  }

  // 2. Parse Python model source code
  const code = String(source);
  const tables: TableSchema[] = [];

  // Split into classes
  const classBlocks = code.split(/\n(?=\s*class\s+\w+)/);

  for (const block of classBlocks) {
    const classMatch = /class\s+(\w+)(?:\([^)]*\))?:/.exec(block);
    if (!classMatch) continue;

    const className = classMatch[1];
    const tableMatch = /__tablename__\s*=\s*['"]([^'"]+)['"]/.exec(block);
    const tableName = tableMatch
      ? tableMatch[1]
      : className.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();

    // Check composite primary keys in __table_args__
    const compositePks: string[] = [];
    const pkConstraintM = /PrimaryKeyConstraint\(([^)]+)\)/.exec(block);
    if (pkConstraintM) {
      compositePks.push(
        ...pkConstraintM[1]
          .split(",")
          .map((c) => c.trim().replace(/^['"]|['"]$/g, ""))
          .filter(Boolean),
      );
    }

    const columns: ColumnSchema[] = [];
    const foreignKeys: ForeignKey[] = [];
    const primaryKeys: string[] = [...compositePks];

    for (const rawLine of block.split("\n")) {
      const line = rawLine.split("#")[0].trim();
      if (!line || (!line.includes("Column(") && !line.includes("mapped_column("))) {
        continue;
      }

      // e.g.: id = Column(Integer, primary_key=True)
      // or user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
      const assignMatch = /^(\w+)(?:\s*:\s*([^=]+))?\s*=\s*(?:Column|mapped_column)\((.*)\)$/.exec(line);
      if (!assignMatch) continue;

      const propName = assignMatch[1];
      const typeAnnotation = (assignMatch[2] || "").trim();
      const callArgs = assignMatch[3] || "";

      let sqlColName = propName;
      // Check if first arg is string literal column name: Column('custom_id', ...)
      const firstArgStrM = /^\s*['"]([^'"]+)['"]\s*(?:,|$)/.exec(callArgs);
      if (firstArgStrM) {
        sqlColName = firstArgStrM[1];
      }

      const isPk = callArgs.includes("primary_key=True") || compositePks.includes(propName) || compositePks.includes(sqlColName);
      if (isPk && !primaryKeys.includes(sqlColName)) {
        primaryKeys.push(sqlColName);
      }

      let isNullable = !isPk;
      if (callArgs.includes("nullable=False")) {
        isNullable = false;
      } else if (callArgs.includes("nullable=True")) {
        isNullable = true;
      }

      // Extract default
      let defaultVal: unknown = undefined;
      const defM = /default\s*=\s*([^,)]+)/.exec(callArgs);
      if (defM) {
        const rawDef = defM[1].trim();
        defaultVal = rawDef.replace(/^['"]|['"]$/g, "");
      }

      // Extract comment
      let comment: string | undefined;
      const comM = /comment\s*=\s*['"]([^'"]+)['"]/.exec(callArgs);
      if (comM) comment = comM[1];

      // Extract Type & Enums
      let dataType = "text";
      let colEnums: string[] | undefined;

      const enumM = /Enum\(([^)]+)\)/.exec(callArgs);
      if (enumM) {
        dataType = "string";
        colEnums = enumM[1]
          .split(",")
          .map((v) => v.trim())
          .filter((v) => !v.includes("=") && (v.startsWith("'") || v.startsWith('"')))
          .map((v) => v.replace(/^['"]|['"]$/g, ""));
      } else {
        const typeTokens = [
          "BigInteger",
          "Integer",
          "SmallInteger",
          "String",
          "Text",
          "Boolean",
          "DateTime",
          "Date",
          "Time",
          "Float",
          "Numeric",
          "JSON",
          "UUID",
        ];
        for (const tok of typeTokens) {
          if (callArgs.includes(tok)) {
            dataType = SQLALCHEMY_TYPE_MAP[tok.toLowerCase()] || "text";
            break;
          }
        }
        if (dataType === "text" && typeAnnotation) {
          const lowerAnn = typeAnnotation.toLowerCase();
          if (lowerAnn.includes("int")) dataType = "integer";
          else if (lowerAnn.includes("bool")) dataType = "boolean";
          else if (lowerAnn.includes("float")) dataType = "float";
          else if (lowerAnn.includes("str")) dataType = "text";
        }
      }

      // Extract ForeignKey
      let fk: ForeignKey | undefined;
      const fkM = /ForeignKey\(\s*['"]([^'"]+)['"]\s*\)/.exec(callArgs);
      if (fkM) {
        const refStr = fkM[1];
        if (refStr.includes(".")) {
          const [refTable, refCol] = refStr.split(".");
          fk = {
            table: tableName,
            column: sqlColName,
            foreignTable: refTable,
            foreignColumn: refCol,
          };
          foreignKeys.push(fk);
        }
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
        comment,
        enums: colEnums,
        foreignKey: fk,
        foreign_key: fk,
      });
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

  return tables;
}
