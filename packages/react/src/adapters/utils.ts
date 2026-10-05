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
