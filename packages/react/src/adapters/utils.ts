/**
 * Shared Utilities for ORM & Schema Adapters in React.
 */

import type { SchemaSnapshot, TableMeta, ColumnMeta, ForeignKeyMeta, TableSchema } from "../types";

export const PRIMITIVE_DATA_TYPE_MAP: Record<string, string> = {
  int: "integer",
  integer: "integer",
  int2: "integer",
  int4: "integer",
  int8: "bigint",
  bigint: "bigint",
  smallint: "integer",
  tinyint: "integer",
  serial: "integer",
  bigserial: "bigint",
  string: "text",
  str: "text",
  text: "text",
  varchar: "text",
  char: "text",
  bool: "boolean",
  boolean: "boolean",
  float: "float",
  double: "float",
  real: "float",
  decimal: "decimal",
  numeric: "decimal",
  date: "date",
  datetime: "timestamp",
  timestamp: "timestamp",
  time: "time",
  json: "json",
  jsonb: "json",
  uuid: "uuid",
  bytes: "bytes",
};

export function normalizeDataType(rawType: string): string {
  const cleaned = rawType.trim().toLowerCase().split("(")[0].trim();
  return PRIMITIVE_DATA_TYPE_MAP[cleaned] || cleaned || "text";
}

export function toSchemaSnapshot(tables: TableSchema[]): SchemaSnapshot {
  const normalizedTables: Record<string, TableMeta> = {};
  const foreignKeys: ForeignKeyMeta[] = [];
  const relationships: {
    source_table: string;
    source_column: string;
    target_table: string;
    target_column: string;
  }[] = [];
  const seenFks = new Set<string>();

  for (const table of tables) {
    if (!table || !table.name) continue;

    const columns: ColumnMeta[] = (table.columns || []).map((col) => {
      const isNullable =
        col.isNullable !== undefined
          ? col.isNullable
          : col.is_nullable !== undefined
            ? col.is_nullable
            : true;
      const isPrimary = Boolean(col.isPrimary ?? col.is_primary ?? false);
      return {
        name: col.name,
        data_type: col.dataType || col.data_type || "text",
        is_nullable: isNullable,
        is_primary: isPrimary,
        comment: col.comment,
      };
    });

    normalizedTables[table.name] = {
      name: table.name,
      schema: table.schema || "public",
      columns,
      comment: table.comment,
      has_user_id: columns.some((c) => c.name === "user_id"),
    };

    const fks = table.foreignKeys || table.foreign_keys || [];
    for (const fk of fks) {
      const foreignTable = fk.foreignTable || fk.foreign_table || "";
      const foreignColumn = fk.foreignColumn || fk.foreign_column || "id";
      const key = `${table.name}.${fk.column}->${foreignTable}.${foreignColumn}`;
      if (foreignTable && !seenFks.has(key)) {
        seenFks.add(key);
        foreignKeys.push({
          table: table.name,
          column: fk.column,
          foreign_table: foreignTable,
          foreign_column: foreignColumn,
        });
        relationships.push({
          source_table: table.name,
          source_column: fk.column,
          target_table: foreignTable,
          target_column: foreignColumn,
        });
      }
    }
  }

  return {
    tables: normalizedTables,
    foreign_keys: foreignKeys,
    relationships,
    categories: {},
  };
}

export function toPascalCase(name: string): string {
  const cleaned = name.replace(/[^a-zA-Z0-9]+/g, " ").trim();
  if (!cleaned) return "Model";
  const words = cleaned.split(/\s+/);
  let result = words.map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join("");
  if (result && /^[0-9]/.test(result)) {
    result = `Model${result}`;
  }
  return result;
}

export function toCamelCase(name: string): string {
  const cleaned = name.replace(/[^a-zA-Z0-9]+/g, " ").trim();
  if (!cleaned) return "field";
  const words = cleaned.split(/\s+/);
  const first = words[0].toLowerCase();
  const rest = words.slice(1).map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join("");
  let result = `${first}${rest}`;
  if (result && /^[0-9]/.test(result)) {
    result = `col${result}`;
  }
  return result;
}

export function toSnakeCase(name: string): string {
  const s1 = name.replace(/(.)([A-Z][a-z]+)/g, "$1_$2");
  const s2 = s1.replace(/([a-z0-9])([A-Z])/g, "$1_$2");
  let s3 = s2.replace(/[^a-zA-Z0-9]+/g, "_").toLowerCase().replace(/^_+|_+$/g, "");
  if (!s3) return "col";
  if (/^[0-9]/.test(s3)) {
    s3 = `col_${s3}`;
  }
  return s3;
}

export interface ExtractedColumn {
  name: string;
  data_type: string;
  is_nullable: boolean;
  is_primary: boolean;
  comment?: string | null;
}

export interface ExtractedTable {
  name: string;
  columns: ExtractedColumn[];
  comment?: string | null;
}

export interface ExtractedForeignKey {
  table: string;
  column: string;
  foreign_table: string;
  foreign_column: string;
}

export function extractSnapshotData(
  snapshot: TableSchema[] | SchemaSnapshot | Record<string, any>,
): {
  tables: Record<string, ExtractedTable>;
  foreignKeys: ExtractedForeignKey[];
} {
  let rawTables: Record<string, any> = {};
  const rawFks: any[] = [];
  const rawRels: any[] = [];

  if (Array.isArray(snapshot)) {
    for (const t of snapshot) {
      if (t && t.name) {
        rawTables[t.name] = t;
        const fks = t.foreignKeys || t.foreign_keys || [];
        rawFks.push(...fks);
      }
    }
  } else if (typeof snapshot === "object" && snapshot !== null) {
    if ("tables" in snapshot && typeof snapshot.tables === "object" && snapshot.tables !== null) {
      rawTables = snapshot.tables;
      const snapAny = snapshot as any;
      if (Array.isArray(snapAny.foreign_keys)) rawFks.push(...snapAny.foreign_keys);
      if (Array.isArray(snapAny.foreignKeys)) rawFks.push(...snapAny.foreignKeys);
      if (Array.isArray(snapAny.relationships)) rawRels.push(...snapAny.relationships);

    } else {
      rawTables = snapshot;
    }
  }

  const tables: Record<string, ExtractedTable> = {};
  for (const [tblName, tblInfo] of Object.entries(rawTables)) {
    if (!tblInfo || typeof tblInfo !== "object") continue;
    const tName = tblInfo.name || tblName;
    const tComment = tblInfo.comment || null;
    const colsSource = Array.isArray(tblInfo.columns) ? tblInfo.columns : [];

    if (Array.isArray(tblInfo.foreignKeys)) {
      rawFks.push(...tblInfo.foreignKeys);
    } else if (Array.isArray(tblInfo.foreign_keys)) {
      rawFks.push(...tblInfo.foreign_keys);
    }

    const columns: ExtractedColumn[] = [];
    for (const col of colsSource) {
      if (typeof col === "string") {
        columns.push({
          name: col,
          data_type: "text",
          is_nullable: true,
          is_primary: col === "id",
          comment: null,
        });
      } else if (col && typeof col === "object") {
        columns.push({
          name: col.name || "",
          data_type: col.dataType || col.data_type || "text",
          is_nullable:
            col.isNullable !== undefined
              ? Boolean(col.isNullable)
              : col.is_nullable !== undefined
                ? Boolean(col.is_nullable)
                : true,
          is_primary: Boolean(col.isPrimary ?? col.is_primary ?? false),
          comment: col.comment || null,
        });
      }
    }

    tables[tName] = {
      name: tName,
      columns,
      comment: tComment,
    };
  }

  const seenFks = new Set<string>();
  const foreignKeys: ExtractedForeignKey[] = [];

  for (const fk of rawFks) {
    if (!fk || typeof fk !== "object") continue;
    const srcTbl = fk.table || "";
    const srcCol = fk.column || "";
    const tgtTbl = fk.foreignTable || fk.foreign_table || "";
    const tgtCol = fk.foreignColumn || fk.foreign_column || "id";
    const key = `${srcTbl}.${srcCol}->${tgtTbl}.${tgtCol}`;
    if (srcTbl && srcCol && tgtTbl && tgtCol && !seenFks.has(key)) {
      seenFks.add(key);
      foreignKeys.push({
        table: srcTbl,
        column: srcCol,
        foreign_table: tgtTbl,
        foreign_column: tgtCol,
      });
    }
  }

  for (const rel of rawRels) {
    if (!rel || typeof rel !== "object") continue;
    const srcTbl = rel.source_table || rel.sourceTable || "";
    const srcCol = rel.source_column || rel.sourceColumn || "";
    const tgtTbl = rel.target_table || rel.targetTable || "";
    const tgtCol = rel.target_column || rel.targetColumn || "id";
    const key = `${srcTbl}.${srcCol}->${tgtTbl}.${tgtCol}`;
    if (srcTbl && srcCol && tgtTbl && tgtCol && !seenFks.has(key)) {
      seenFks.add(key);
      foreignKeys.push({
        table: srcTbl,
        column: srcCol,
        foreign_table: tgtTbl,
        foreign_column: tgtCol,
      });
    }
  }

  return { tables, foreignKeys };
}
