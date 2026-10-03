import type {
  DatabaseSchemaDefinition,
  SchemaSnapshot,
  TableMeta,
  ColumnMeta,
  TableDefinition,
  ColumnDefinition,
  ForeignKeyMeta,
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
  schema?: DatabaseSchemaDefinition | SchemaSnapshot | null,
): SchemaSnapshot | null {
  if (!schema || typeof schema !== "object" || !schema.tables) {
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
