import type {
  DatabaseSchemaDefinition,
  SchemaSnapshot,
  TableMeta,
  ColumnMeta,
  TableDefinition,
  ColumnDefinition,
  ForeignKeyMeta,
  TableSchema,
} from "../types";

export function isSchemaSnapshot(schema: unknown): schema is SchemaSnapshot {
  if (!schema || typeof schema !== "object" || !("tables" in schema)) {
    return false;
  }
  const tables = (schema as { tables: unknown }).tables;
  if (!tables || typeof tables !== "object") return false;
  const firstTable = Object.values(tables)[0] as TableMeta | TableDefinition | undefined;
  if (firstTable && Array.isArray(firstTable.columns)) {
    return true;
  }
  return false;
}

export function normalizeSchema(
  schema?: DatabaseSchemaDefinition | SchemaSnapshot | TableSchema[] | null,
): SchemaSnapshot | null {
  if (!schema) {
    return null;
  }

  // Handle TableSchema[] directly
  if (Array.isArray(schema)) {
    const normalizedTables: Record<string, TableMeta> = {};
    const foreignKeys: ForeignKeyMeta[] = [];
    const relationships: {
      source_table: string;
      source_column: string;
      target_table: string;
      target_column: string;
    }[] = [];

    for (const table of schema) {
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
        if (foreignTable) {
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
    };
  }

  if (typeof schema !== "object" || !schema.tables) {
    return null;
  }

  if (isSchemaSnapshot(schema)) {
    return schema;
  }

  const normalizedTables: Record<string, TableMeta> = {};
  const foreignKeys: ForeignKeyMeta[] = [];
  const relationships: {
    source_table: string;
    source_column: string;
    target_table: string;
    target_column: string;
  }[] = [];

  for (const [tableName, tableDef] of Object.entries(schema.tables)) {
    if (!tableDef) continue;

    let columns: ColumnMeta[] = [];
    if (Array.isArray(tableDef.columns)) {
      columns = tableDef.columns;
    } else if (tableDef.columns && typeof tableDef.columns === "object") {
      columns = Object.entries(tableDef.columns).map(([colName, colDef]) => {
        if (typeof colDef === "string") {
          return {
            name: colName,
            data_type: colDef,
            is_nullable: true,
            is_primary: false,
          };
        }
        const def = colDef as ColumnDefinition;
        return {
          name: colName,
          data_type: def.dataType || "string",
          is_nullable: Boolean(def.nullable),
          is_primary: Boolean(def.primaryKey),
          comment: def.comment,
        };
      });
    }

    normalizedTables[tableName] = {
      name: tableName,
      columns,
      comment: tableDef.comment,
    };

    if (tableDef.relationships && typeof tableDef.relationships === "object") {
      for (const [_, rel] of Object.entries(tableDef.relationships)) {
        if (!rel || !rel.targetTable) continue;
        const targetCol = rel.targetColumn || "id";
        const sourceCol = rel.sourceColumn || "id";
        foreignKeys.push({
          table: tableName,
          column: sourceCol,
          foreign_table: rel.targetTable,
          foreign_column: targetCol,
        });
        relationships.push({
          source_table: tableName,
          source_column: sourceCol,
          target_table: rel.targetTable,
          target_column: targetCol,
        });
      }
    }
  }

  return {
    tables: normalizedTables,
    foreign_keys: foreignKeys,
    relationships,
  };
}
