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

export type SchemaDiagnosticSeverity = "error" | "warning" | "info";

export interface SchemaDiagnostic {
  severity: SchemaDiagnosticSeverity;
  code: string;
  table?: string;
  column?: string;
  message: string;
  suggestion?: string;
}

export interface SchemaValidationResult {
  valid: boolean;
  diagnostics: SchemaDiagnostic[];
  errors: SchemaDiagnostic[];
  warnings: SchemaDiagnostic[];
  infos: SchemaDiagnostic[];
}

/**
 * Validates a schema definition, snapshot, or table array and returns actionable diagnostics.
 * Detects missing tables, broken foreign keys, missing data types, missing primary keys,
 * and duplicate columns with descriptive developer suggestions.
 */
export function validateSchema(
  rawSchema?: DatabaseSchemaDefinition | SchemaSnapshot | TableSchema[] | null,
): SchemaValidationResult {
  const diagnostics: SchemaDiagnostic[] = [];

  if (!rawSchema) {
    diagnostics.push({
      severity: "error",
      code: "SCHEMA_EMPTY",
      message: "Schema is null, undefined, or empty.",
      suggestion: "Provide a valid SchemaSnapshot, TableSchema[] array, or DatabaseSchemaDefinition.",
    });
    return {
      valid: false,
      diagnostics,
      errors: diagnostics.filter((d) => d.severity === "error"),
      warnings: [],
      infos: [],
    };
  }

  const normalized = normalizeSchema(rawSchema);
  if (!normalized || !normalized.tables || Object.keys(normalized.tables).length === 0) {
    diagnostics.push({
      severity: "error",
      code: "SCHEMA_NO_TABLES",
      message: "Schema contains no tables or could not be parsed.",
      suggestion: "Check that tables are defined with at least one column.",
    });
    return {
      valid: false,
      diagnostics,
      errors: diagnostics.filter((d) => d.severity === "error"),
      warnings: [],
      infos: [],
    };
  }

  const tableNames = new Set(Object.keys(normalized.tables));

  // 1. Validate each table
  for (const [tableName, table] of Object.entries(normalized.tables)) {
    if (!table.columns || table.columns.length === 0) {
      diagnostics.push({
        severity: "warning",
        code: "TABLE_NO_COLUMNS",
        table: tableName,
        message: `Table "${tableName}" has no columns defined.`,
        suggestion: "Add column metadata to enable querying this table.",
      });
      continue;
    }

    const seenCols = new Set<string>();
    let hasPk = false;

    for (const rawCol of table.columns) {
      const col: ColumnMeta = typeof rawCol === "string" ? { name: rawCol, data_type: "text", is_nullable: true, is_primary: false } : rawCol;
      // Duplicate column check
      if (seenCols.has(col.name)) {
        diagnostics.push({
          severity: "error",
          code: "DUPLICATE_COLUMN",
          table: tableName,
          column: col.name,
          message: `Table "${tableName}" has duplicate column "${col.name}".`,
          suggestion: `Ensure column names are unique within table "${tableName}".`,
        });
      }
      seenCols.add(col.name);

      // Missing or empty data_type check
      if (!col.data_type || col.data_type.trim() === "") {
        diagnostics.push({
          severity: "warning",
          code: "COLUMN_MISSING_DATA_TYPE",
          table: tableName,
          column: col.name,
          message: `Column "${tableName}.${col.name}" is missing a data type. Defaulting to text.`,
          suggestion: 'Specify a data type such as "integer", "varchar", "boolean", or "timestamp".',
        });
      }

      if (col.is_primary || col.name.toLowerCase() === "id") {
        hasPk = true;
      }
    }

    // Missing primary key check
    if (!hasPk) {
      diagnostics.push({
        severity: "info",
        code: "TABLE_NO_PRIMARY_KEY",
        table: tableName,
        message: `Table "${tableName}" has no primary key designated.`,
        suggestion: "Designating a primary key column helps the query builder recommend optimal joins.",
      });
    }
  }

  // 2. Validate Foreign Keys & Relationships
  const allFks = [...(normalized.foreign_keys || [])];
  if (normalized.relationships) {
    for (const rel of normalized.relationships) {
      const alreadyPresent = allFks.some(
        (fk) =>
          fk.table === rel.source_table &&
          fk.column === rel.source_column &&
          fk.foreign_table === rel.target_table &&
          fk.foreign_column === rel.target_column,
      );
      if (!alreadyPresent) {
        allFks.push({
          table: rel.source_table,
          column: rel.source_column,
          foreign_table: rel.target_table,
          foreign_column: rel.target_column,
        });
      }
    }
  }

  for (const fk of allFks) {
    // Check source table
    if (!tableNames.has(fk.table)) {
      diagnostics.push({
        severity: "error",
        code: "FK_SOURCE_TABLE_MISSING",
        table: fk.table,
        message: `Foreign key references missing source table "${fk.table}".`,
        suggestion: `Define table "${fk.table}" in the schema snapshot.`,
      });
      continue;
    }

    const sourceTable = normalized.tables[fk.table];
    const sourceColExists = sourceTable.columns.some((c) => c.name === fk.column);
    if (!sourceColExists) {
      diagnostics.push({
        severity: "error",
        code: "FK_SOURCE_COLUMN_MISSING",
        table: fk.table,
        column: fk.column,
        message: `Foreign key column "${fk.column}" does not exist in source table "${fk.table}".`,
        suggestion: `Add column "${fk.column}" to table "${fk.table}" or fix foreign key definition.`,
      });
    }

    // Check target table
    if (!tableNames.has(fk.foreign_table)) {
      diagnostics.push({
        severity: "error",
        code: "FK_TARGET_TABLE_MISSING",
        table: fk.table,
        message: `Foreign key in table "${fk.table}" references non-existent target table "${fk.foreign_table}".`,
        suggestion: `Include table "${fk.foreign_table}" in schema snapshot or remove broken foreign key.`,
      });
    } else {
      // Check target column
      const targetTable = normalized.tables[fk.foreign_table];
      const targetColExists = targetTable.columns.some((c) => c.name === fk.foreign_column);
      if (!targetColExists) {
        diagnostics.push({
          severity: "error",
          code: "FK_TARGET_COLUMN_MISSING",
          table: fk.foreign_table,
          column: fk.foreign_column,
          message: `Foreign key in table "${fk.table}" references column "${fk.foreign_table}.${fk.foreign_column}" which does not exist.`,
          suggestion: `Ensure column "${fk.foreign_column}" exists in target table "${fk.foreign_table}".`,
        });
      }
    }
  }

  const errors = diagnostics.filter((d) => d.severity === "error");
  const warnings = diagnostics.filter((d) => d.severity === "warning");
  const infos = diagnostics.filter((d) => d.severity === "info");

  return {
    valid: errors.length === 0,
    diagnostics,
    errors,
    warnings,
    infos,
  };
}

/**
 * Table names from any accepted schema shape: `TableSchema[]` (adapter output),
 * `{ tables: Record<string, ...> }` (`DatabaseSchemaDefinition` / `SchemaSnapshot`) or null.
 */
export function getSchemaTableNames(schema: unknown): string[] {
  if (Array.isArray(schema)) {
    return schema
      .map((t: unknown) =>
        typeof t === "object" && t !== null && typeof (t as { name?: unknown }).name === "string"
          ? (t as { name: string }).name
          : "",
      )
      .filter(Boolean);
  }
  if (typeof schema === "object" && schema !== null) {
    const tables = (schema as { tables?: unknown }).tables;
    if (typeof tables === "object" && tables !== null) return Object.keys(tables);
  }
  return [];
}
