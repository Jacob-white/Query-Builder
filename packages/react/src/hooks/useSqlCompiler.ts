import { useState, useEffect, useMemo, useRef } from "react";
import type {
  DatabaseSchemaDefinition,
  SchemaSnapshot,
  SqlDialect,
  SqlSafetyValidation,
  QuerySpec,
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  CustomFilterOperator,
  VectorSearchSpec,
  HybridSearchSpec,
  CteSpec,
  WindowFunctionSpec,
  SemanticModel,
} from "../types";
import { compileVisualState, type CompiledVisualQuery } from "../utils/compiler";
import { validateSqlSafety } from "../utils/safety";
import { normalizeSchema } from "../utils/schemaUtils";
import { specToState, type QueryState } from "./useQueryState";
import type { QueryBuilderState } from "./useQueryBuilder";

export interface UseSqlCompilerOptions {
  dialect?: SqlDialect;
  schema?: SchemaSnapshot | DatabaseSchemaDefinition | null;
  debounceMs?: number;
  allowedSchemas?: string[];
  customOperators?: Record<string, CustomFilterOperator>;
}

export interface UseSqlCompilerReturn {
  sql: string;
  params: (string | number | boolean)[];
  countSql: string;
  safety: SqlSafetyValidation;
  isValid: boolean;
  ast: CompiledVisualQuery["spec"] | null;
  error: string | null;
  isCompiling: boolean;
  compileTimeMs: number;
  dialect: SqlDialect;
}

interface CompiledInternal {
  sql: string;
  countSql: string;
  params: (string | number | boolean)[];
  safety: SqlSafetyValidation;
  isValid: boolean;
  ast: CompiledVisualQuery["spec"] | null;
  error: string | null;
  compileTimeMs: number;
  dialect: SqlDialect;
}

function compileInput(
  specOrState:
    | QuerySpec
    | QueryState
    | QueryBuilderState
    | Record<string, unknown>
    | null
    | undefined,
  options?: UseSqlCompilerOptions,
): CompiledInternal {
  const startTime = typeof performance !== "undefined" ? performance.now() : 0;
  const dialect: SqlDialect =
    options?.dialect ||
    ((specOrState as any)?.dialect as SqlDialect) ||
    "postgres";

  if (!specOrState) {
    const safety = validateSqlSafety("");
    return {
      sql: "",
      countSql: "",
      params: [],
      safety,
      isValid: false,
      ast: null,
      error: null,
      compileTimeMs: 0,
      dialect,
    };
  }

  try {
    const normalizedSchema = normalizeSchema(options?.schema);

    let primaryTable = "";
    let selectedColumns: Record<string, VisualColumnSelect> = {};
    let orderedProjectionKeys: string[] = [];
    let joins: VisualJoin[] = [];
    let filters: VisualFilter[] = [];
    let sorts: VisualSort[] = [];
    let isDistinct = false;
    let limit = 50;

    // Check if it's already visual state-like
    if (
      "primaryTable" in specOrState &&
      typeof (specOrState as any).primaryTable === "string" &&
      "selectedColumns" in specOrState
    ) {
      const state = specOrState as QueryState | QueryBuilderState;
      primaryTable = state.primaryTable;
      selectedColumns = state.selectedColumns || {};
      orderedProjectionKeys =
        state.orderedProjectionKeys || Object.keys(selectedColumns);
      joins = state.joins || [];
      filters = state.filters || [];
      sorts = state.sorts || [];
      isDistinct = Boolean(state.isDistinct);
      limit = typeof state.limit === "number" ? state.limit : 50;
    } else {
      const parsed = specToState(specOrState);
      primaryTable = parsed.primaryTable || "";
      selectedColumns = parsed.selectedColumns || {};
      orderedProjectionKeys =
        parsed.orderedProjectionKeys || Object.keys(selectedColumns);
      joins = parsed.joins || [];
      filters = parsed.filters || [];
      sorts = parsed.sorts || [];
      isDistinct = Boolean(parsed.isDistinct);
      limit = typeof parsed.limit === "number" ? parsed.limit : 50;
    }

    const filterJoin = (specOrState as any)?.filter_join || "AND";
    const customOperators =
      options?.customOperators || (specOrState as any)?.customOperators;
    const vectorSearch =
      (specOrState as any)?.vector_search || (specOrState as any)?.vectorSearch || null;
    const hybridSearch =
      (specOrState as any)?.hybrid_search || (specOrState as any)?.hybridSearch || null;
    const ctes = (specOrState as any)?.ctes || null;
    const windowFunctions =
      (specOrState as any)?.window_functions || (specOrState as any)?.windowFunctions || null;
    const semanticModels =
      (specOrState as any)?.semantic_models || (specOrState as any)?.semanticModels || null;

    const compiled = compileVisualState(
      primaryTable,
      selectedColumns,
      orderedProjectionKeys,
      joins,
      filters,
      sorts,
      isDistinct,
      limit,
      normalizedSchema,
      dialect,
      filterJoin,
      customOperators,
      vectorSearch,
      hybridSearch,
      ctes,
      windowFunctions,
      semanticModels,
    );

    const sql = compiled.sql;
    let countSql = "";
    if (sql) {
      let cleanSql = sql.replace(/;+\s*$/, "");
      if (dialect === "mssql") {
        cleanSql = cleanSql.replace(/\s+ORDER\s+BY\s+[^)]+$/i, "");
      }
      countSql = `SELECT COUNT(*) FROM (${cleanSql}) AS count_wrapper;`;
    }

    const safety = validateSqlSafety(sql, options?.allowedSchemas);
    const params = filters.map((f) => f.value);
    const isValid = Boolean(sql) && safety.valid;
    const endTime = typeof performance !== "undefined" ? performance.now() : 0;
    const compileTimeMs = Math.max(0, endTime - startTime);

    return {
      sql,
      countSql,
      params,
      safety,
      isValid,
      ast: compiled.spec,
      error: null,
      compileTimeMs,
      dialect,
    };
  } catch (err) {
    const endTime = typeof performance !== "undefined" ? performance.now() : 0;
    const safety = validateSqlSafety("");
    return {
      sql: "",
      countSql: "",
      params: [],
      safety,
      isValid: false,
      ast: null,
      error: err instanceof Error ? err.message : String(err),
      compileTimeMs: Math.max(0, endTime - startTime),
      dialect,
    };
  }
}

/**
 * Headless SQL compilation and validation hook.
 */
export function useSqlCompiler(
  specOrState:
    | QuerySpec
    | QueryState
    | QueryBuilderState
    | Record<string, unknown>
    | null
    | undefined,
  options?: UseSqlCompilerOptions,
): UseSqlCompilerReturn {
  const debounceMs = options?.debounceMs;
  const isDebounced = typeof debounceMs === "number" && debounceMs > 0;

  const [debouncedResult, setDebouncedResult] = useState<CompiledInternal>(() =>
    compileInput(specOrState, options),
  );
  const [isCompiling, setIsCompiling] = useState<boolean>(false);

  // For immediate synchronous compilation when not debounced
  const syncResult = useMemo(() => {
    if (isDebounced) return null;
    return compileInput(specOrState, options);
  }, [
    specOrState,
    options?.dialect,
    options?.schema,
    options?.allowedSchemas,
    options?.customOperators,
    isDebounced,
  ]);

  // Ref to track latest options/input for debounce
  const latestRef = useRef({ specOrState, options });
  latestRef.current = { specOrState, options };

  useEffect(() => {
    if (!isDebounced) {
      return;
    }

    setIsCompiling(true);
    const timer = setTimeout(() => {
      const res = compileInput(
        latestRef.current.specOrState,
        latestRef.current.options,
      );
      setDebouncedResult(res);
      setIsCompiling(false);
    }, debounceMs);

    return () => {
      clearTimeout(timer);
    };
  }, [
    specOrState,
    options?.dialect,
    options?.schema,
    options?.allowedSchemas,
    options?.customOperators,
    debounceMs,
    isDebounced,
  ]);

  const activeResult = isDebounced ? debouncedResult : syncResult!;

  return {
    sql: activeResult.sql,
    params: activeResult.params,
    countSql: activeResult.countSql,
    safety: activeResult.safety,
    isValid: activeResult.isValid,
    ast: activeResult.ast,
    error: activeResult.error,
    isCompiling: isDebounced ? isCompiling : false,
    compileTimeMs: activeResult.compileTimeMs,
    dialect: activeResult.dialect,
  };
}
