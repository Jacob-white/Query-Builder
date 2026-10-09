import { useMemo } from "react";
import type { SchemaSnapshot, SemanticModel, SqlDialect } from "../../types";
import type { QueryState } from "../../hooks/useQueryState";
import { compileVisualState } from "../../utils/compiler";

/** Compiles the visual query state to SQL and a spec (memoized on the state slices it reads). */
export function useCompiledQuery(
  state: QueryState,
  schema: SchemaSnapshot | null | undefined,
  dialect: SqlDialect,
  customOperators: Parameters<typeof compileVisualState>[11],
  semanticModels: SemanticModel[] | undefined,
) {
  const { primaryTable, selectedColumns, orderedProjectionKeys, joins, filters, sorts } = state;
  const { isDistinct, limit, ctes, windowFunctions } = state;
  const vectorSearch = state.vectorSearch || null;
  const hybridSearch = state.hybridSearch || null;

  return useMemo(
    () =>
      compileVisualState(
        primaryTable,
        selectedColumns,
        orderedProjectionKeys,
        joins,
        filters,
        sorts,
        isDistinct,
        limit,
        schema,
        dialect,
        "AND",
        customOperators,
        vectorSearch,
        hybridSearch,
        ctes,
        windowFunctions,
        semanticModels,
      ),
    [
      primaryTable,
      selectedColumns,
      orderedProjectionKeys,
      joins,
      filters,
      sorts,
      isDistinct,
      limit,
      schema,
      dialect,
      customOperators,
      vectorSearch,
      hybridSearch,
      ctes,
      windowFunctions,
      semanticModels,
    ],
  );
}
