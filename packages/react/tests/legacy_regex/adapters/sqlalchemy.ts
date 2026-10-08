/**
 * SQLAlchemy Adapter for React Query Builder.
 * Converts SQLAlchemy Python model source code or serialized metadata into TableSchema[].
 */

import type { ColumnSchema, ForeignKey, SchemaSnapshot, TableSchema } from "../../../src/types";
import type { AdapterOptions } from "../../../src/adapters/types";
import {
  extractSnapshotData,
  normalizeDataType,
  toPascalCase,
  toSnakeCase,
} from "./utils";


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

/** Minimal structural shapes of serialized SQLAlchemy metadata. */
interface SqlAlchemyColumnDef {
  name?: string;
  is_primary?: boolean;
  primary_key?: boolean;
  isPrimary?: boolean;
  data_type?: string;
  dataType?: string;
  type?: string;
  is_nullable?: boolean;
  default?: unknown;
  comment?: string;
  enums?: string[];
}

interface SqlAlchemyTableDef {
  primary_keys?: string[];
  foreign_keys?: ForeignKey[];
  columns?: unknown;
  schema?: string;
  comment?: string;
}

export function fromSqlAlchemy(
  source: string | Record<string, unknown>,
  options?: AdapterOptions,
): TableSchema[] {
  const defaultSchema = options?.defaultSchema || "public";

  // 1. If source is an object / serialized metadata dict
  if (typeof source === "object" && source !== null) {
    const rawTables = (source.tables || source) as Record<string, unknown>;
    const tables: TableSchema[] = [];

    for (const [tblName, rawTblDef] of Object.entries(rawTables)) {
      if (!rawTblDef || typeof rawTblDef !== "object") continue;
      const tblDef = rawTblDef as SqlAlchemyTableDef;
      const columns: ColumnSchema[] = [];
      const primaryKeys: string[] = tblDef.primary_keys || [];
      const foreignKeys: ForeignKey[] = tblDef.foreign_keys || [];

      const rawCols = tblDef.columns;
      if (Array.isArray(rawCols)) {
        for (const c of rawCols as SqlAlchemyColumnDef[]) {
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
        schema: tblDef.schema || defaultSchema,
        columns,
        primaryKeys,
        foreignKeys,
        comment: tblDef.comment,
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
            dataType = SQLALCHEMY_TYPE_MAP[tok.toLowerCase()];
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

/**
 * Converts a TableSchema array, SchemaSnapshot, or metadata dictionary to SQLAlchemy Declarative Base models (.py).
 *
 * Generates:
 * - Base = declarative_base() definition
 * - Model classes inheriting from Base with __tablename__
 * - Column declarations with standard SQLAlchemy types
 * - ForeignKey constraints and relationship() definitions
 */
export function toSqlAlchemy(
  snapshot: TableSchema[] | SchemaSnapshot | Record<string, unknown>,
): string {
  const { tables, foreignKeys } = extractSnapshotData(snapshot);

  const header =
    "from __future__ import annotations\n\n" +
    "from sqlalchemy import (\n" +
    "    Boolean,\n" +
    "    Column,\n" +
    "    DateTime,\n" +
    "    Float,\n" +
    "    ForeignKey,\n" +
    "    Integer,\n" +
    "    Numeric,\n" +
    "    String,\n" +
    "    Text,\n" +
    ")\n" +
    "from sqlalchemy.orm import declarative_base, relationship\n\n" +
    "Base = declarative_base()";

  const tableEntries = Object.entries(tables);
  if (tableEntries.length === 0) {
    return header;
  }

  // Build FK index: table -> list of fks
  const fksByTable: Record<string, typeof foreignKeys> = {};
  for (const tName of Object.keys(tables)) {
    fksByTable[tName] = [];
  }
  for (const fk of foreignKeys) {
    if (tables[fk.table]) {
      fksByTable[fk.table].push(fk);
    }
  }

  const modelBlocks: string[] = [];

  for (const [tableName, tableInfo] of tableEntries) {
    const modelName = toPascalCase(tableName);
    const columns = tableInfo.columns;
    const tableComment = tableInfo.comment;

    const docstring = tableComment
      ? tableComment
      : `Declarative model for table '${tableName}'.`;

    const lines: string[] = [
      `class ${modelName}(Base):`,
      `    """${docstring}"""`,
      `    __tablename__ = "${tableName}"`,
    ];

    if (!columns || columns.length === 0) {
      lines.push("    pass");
      modelBlocks.push(lines.join("\n"));
      continue;
    }

    // Map FK columns for this table
    const fkMap: Record<string, (typeof foreignKeys)[0]> = {};
    for (const fk of fksByTable[tableName]) {
      fkMap[fk.column] = fk;
    }

const PYTHON_KEYWORDS = new Set([
  "False", "None", "True", "and", "as", "assert", "async", "await", "break",
  "class", "continue", "def", "del", "elif", "else", "except", "finally",
  "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
  "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
]);

    const colVarNames = new Set<string>();

    for (const col of columns) {
      const cName = col.name;
      const cType = col.data_type.toLowerCase();
      const isPk = Boolean(col.is_primary);
      const isNullable = Boolean(col.is_nullable);

      const baseVar = toSnakeCase(cName);
      const isKeyword = PYTHON_KEYWORDS.has(baseVar);
      const colVar = isKeyword ? `${baseVar}_` : baseVar;
      colVarNames.add(colVar);

      // Map to SQLAlchemy type
      let saType = "String";
      if (
        ["bigint", "bigserial", "int", "serial", "smallint", "tinyint"].some((t) =>
          cType.includes(t),
        )
      ) {
        saType = "Integer";
      } else if (["bool", "boolean"].some((t) => cType.includes(t))) {
        saType = "Boolean";
      } else if (["float", "double", "real"].some((t) => cType.includes(t))) {
        saType = "Float";
      } else if (["decimal", "numeric", "money"].some((t) => cType.includes(t))) {
        saType = "Numeric";
      } else if (["datetime", "timestamp", "date", "time"].some((t) => cType.includes(t))) {
        saType = "DateTime";
      } else if (["text", "clob", "json", "jsonb"].some((t) => cType.includes(t))) {
        saType = "Text";
      } else {
        saType = "String";
      }

      // Check for FK
      let fkClause = "";
      if (fkMap[cName]) {
        const fk = fkMap[cName];
        fkClause = `ForeignKey("${fk.foreign_table}.${fk.foreign_column}"), `;
      }

      const colNameArg = isKeyword || colVar !== cName ? `"${cName}", ` : "";
      lines.push(
        `    ${colVar} = Column(${colNameArg}${saType}, ${fkClause}primary_key=${isPk ? "True" : "False"}, nullable=${isNullable ? "True" : "False"})`,
      );
    }

    // Generate relationships for outgoing FKs where target table is present in snapshot
    for (const fk of fksByTable[tableName]) {
      if (!tables[fk.foreign_table]) continue;

      const srcCol = fk.column;
      const tgtTbl = fk.foreign_table;
      const baseSrc = toSnakeCase(srcCol);
      const srcVar = PYTHON_KEYWORDS.has(baseSrc) ? `${baseSrc}_` : baseSrc;
      const targetModel = toPascalCase(tgtTbl);

      let relName: string;
      if (baseSrc.endsWith("_id")) {
        relName = baseSrc.slice(0, -3);
      } else if (baseSrc.endsWith("id") && baseSrc.length > 2) {
        relName = baseSrc.slice(0, -2);
      } else {
        relName = toSnakeCase(tgtTbl);
      }

      if (PYTHON_KEYWORDS.has(relName)) {
        relName = `${relName}_rel`;
      } else if (colVarNames.has(relName)) {
        relName = `${relName}_rel`;
      }

      lines.push(
        `    ${relName} = relationship("${targetModel}", foreign_keys=[${srcVar}])`,
      );
    }

    modelBlocks.push(lines.join("\n"));
  }

  const modelsContent = modelBlocks.join("\n\n\n");
  return `${header}\n\n\n${modelsContent}`;
}

export const toSqlAlchemyModels = toSqlAlchemy;

