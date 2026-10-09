import { useEffect, useMemo } from "react";
import type { ColumnMeta, CteSpec, SemanticModel, SchemaSnapshot } from "../../types";
import { normalizeSchema, validateSchema } from "../../utils/schemaUtils";
import { attachSemanticModelsToTables } from "../../adapters/semantic";

/** Normalizes the schema and logs (non-blocking) developer diagnostics outside production. */
export function useNormalizedSchema(effectiveSchema: Parameters<typeof normalizeSchema>[0]) {
  const normalizedSchema = useMemo(() => normalizeSchema(effectiveSchema), [effectiveSchema]);

  useEffect(() => {
    if (normalizedSchema) {
      const result = validateSchema(normalizedSchema);
      if (!result.valid || result.warnings.length > 0) {
        if (
          typeof globalThis !== "undefined" &&
          (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env
            ?.NODE_ENV !== "production"
        ) {
          result.errors.forEach((e) => {
            console.warn(`[Query-Builder Schema Error] ${e.code}: ${e.message}`, e.suggestion);
          });
          result.warnings.forEach((w) => {
            console.warn(`[Query-Builder Schema Warning] ${w.code}: ${w.message}`, w.suggestion);
          });
        }
      }
    }
  }, [normalizedSchema]);

  return normalizedSchema;
}

/** Virtual columns for a CTE, derived from its query (with sensible fallbacks). */
export function cteColumns(cte: CteSpec): ColumnMeta[] {
  const cols: ColumnMeta[] = [];
  if (cte.query?.columns) {
    cte.query.columns.forEach((col) => {
      if (typeof col === "string") {
        cols.push({ name: col, data_type: "text", is_nullable: true, is_primary: false });
      } else if (col && typeof col === "object") {
        cols.push({
          name: col.alias || col.column || "col",
          data_type: "text",
          is_nullable: true,
          is_primary: false,
        });
      }
    });
  }
  if (cte.query?.window_functions) {
    cte.query.window_functions.forEach((wf) => {
      if (wf.alias)
        cols.push({ name: wf.alias, data_type: "numeric", is_nullable: true, is_primary: false });
    });
  }
  if (cols.length === 0) {
    cols.push(
      { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
      { name: "value", data_type: "text", is_nullable: true, is_primary: false },
    );
  }
  return cols;
}

/** Exposes upstream CTEs as virtual tables and attaches semantic models. */
export function useAugmentedSchema(
  normalizedSchema: SchemaSnapshot | null | undefined,
  ctes: CteSpec[],
  activeStageName: string | null,
  semanticModels: SemanticModel[] | undefined,
) {
  return useMemo(() => {
    if (!normalizedSchema) return normalizedSchema;
    let copyTables = { ...normalizedSchema.tables };
    for (const cte of ctes) {
      if (activeStageName && cte.name === activeStageName) continue;
      copyTables[cte.name] = { name: cte.name, columns: cteColumns(cte) };
    }
    if (semanticModels && semanticModels.length > 0) {
      copyTables = attachSemanticModelsToTables(copyTables, semanticModels);
    }
    return { ...normalizedSchema, tables: copyTables };
  }, [normalizedSchema, ctes, activeStageName, semanticModels]);
}
