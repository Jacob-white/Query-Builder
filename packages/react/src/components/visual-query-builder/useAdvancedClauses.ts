import { useCallback, useMemo } from "react";
import type { ResolvedFeatureMap } from "../../types";
import type { QueryState, QueryStateActions } from "../../hooks/useQueryState";
import { detectActiveAdvancedClauses } from "../../utils/featureUtils";

/**
 * Advanced clauses (CTEs, window functions, vector/hybrid search, expression columns) that keep
 * compiling while the UI is in simple mode, plus a handler that clears them.
 */
export function useAdvancedClauses(
  state: QueryState,
  actions: QueryStateActions,
  isAdvancedMode: boolean,
  resolvedFeatures: ResolvedFeatureMap,
) {
  const { ctes, windowFunctions, selectedColumns } = state;
  const vectorSearch = state.vectorSearch || null;
  const hybridSearch = state.hybridSearch || null;

  const activeAdvancedClauses = useMemo(() => {
    if (isAdvancedMode) return [];
    return detectActiveAdvancedClauses(
      { ctes, windowFunctions, vectorSearch, hybridSearch, selectedColumns },
      resolvedFeatures,
    );
  }, [isAdvancedMode, ctes, windowFunctions, vectorSearch, hybridSearch, selectedColumns, resolvedFeatures]);

  const clearAdvancedClauses = useCallback(() => {
    if (ctes.length > 0) actions.setCtes([]);
    if (windowFunctions.length > 0) actions.setWindowFunctions([]);
    if (vectorSearch) actions.setVectorSearch(null);
    if (hybridSearch) actions.setHybridSearch(null);
    const cleanedCols = { ...selectedColumns };
    let hasCleaned = false;
    for (const [k, v] of Object.entries(cleanedCols)) {
      if (v && (v.rawExpression || (v as { expression?: unknown }).expression)) {
        delete cleanedCols[k];
        hasCleaned = true;
      }
    }
    if (hasCleaned) actions.setSelectedColumns(cleanedCols);
  }, [ctes, windowFunctions, vectorSearch, hybridSearch, selectedColumns, actions]);

  return { activeAdvancedClauses, clearAdvancedClauses };
}
