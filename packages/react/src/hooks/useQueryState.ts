import { useState, useCallback, useMemo, useRef } from "react";
import { normalizeCombiner, resolveFilterCombiners } from "../utils/filterCombiners";
import type {
  DatabaseSchemaDefinition,
  SchemaTableNames,
  SchemaColumnNames,
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  SqlDialect,
  QuerySpec,
  SchemaSnapshot,
  VectorSearchSpec,
  HybridSearchSpec,
  CteSpec,
  WindowFunctionSpec,
  LooseQuerySpec,
  TimeGrain,
} from "../types";
import { findJoinPath, findBestJoinCondition } from "../utils/joinUtils";

export interface QueryState<Schema = DatabaseSchemaDefinition> {
  primaryTable: SchemaTableNames<Schema>;
  activeTables: SchemaTableNames<Schema>[];
  selectedColumns: Record<string, VisualColumnSelect<Schema>>;
  orderedProjectionKeys: string[];
  joins: VisualJoin<Schema>[];
  filters: VisualFilter<Schema>[];
  sorts: VisualSort<Schema>[];
  isDistinct: boolean;
  limit: number;
  offset: number;
  dialect: SqlDialect;
  isDirty: boolean;
  vectorSearch?: VectorSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  ctes: CteSpec[];
  windowFunctions: WindowFunctionSpec[];
}

export interface QueryHistory<Schema = DatabaseSchemaDefinition> {
  past: QueryState<Schema>[];
  future: QueryState<Schema>[];
  canUndo: boolean;
  canRedo: boolean;
}

export interface QueryStateActions<Schema = DatabaseSchemaDefinition> {
  setTables: (tables: SchemaTableNames<Schema>[]) => void;
  setPrimaryTable: (table: SchemaTableNames<Schema>) => void;
  addTable: (table: SchemaTableNames<Schema>) => void;
  removeTable: (table: SchemaTableNames<Schema>) => void;
  toggleColumn: (
    table: SchemaTableNames<Schema>,
    col: SchemaColumnNames<Schema, string> | string,
  ) => void;
  updateColumnSelect: (key: string, updates: Partial<VisualColumnSelect<Schema>>) => void;
  removeColumnProjection: (key: string) => void;
  setSelectedColumns: (
    selected: Record<string, VisualColumnSelect<Schema>>,
    orderedKeys?: string[],
  ) => void;
  setOrderedProjectionKeys: (keys: string[]) => void;
  setJoins: (joins: VisualJoin<Schema>[]) => void;
  addJoin: (join: VisualJoin<Schema>) => void;
  autoJoinTable: (
    targetTable: SchemaTableNames<Schema> | string,
    schema?: SchemaSnapshot | null,
  ) => void;
  updateJoin: (id: string, updates: Partial<VisualJoin<Schema>>) => void;
  removeJoin: (id: string) => void;
  setFilters: (filters: VisualFilter<Schema>[]) => void;
  addFilter: (filter: VisualFilter<Schema>) => void;
  updateFilter: (id: string, updates: Partial<VisualFilter<Schema>>) => void;
  removeFilter: (id: string) => void;
  setSorts: (sorts: VisualSort<Schema>[]) => void;
  addSort: (sort: VisualSort<Schema>) => void;
  updateSort: (id: string, updates: Partial<VisualSort<Schema>>) => void;
  removeSort: (id: string) => void;
  setLimit: (limit: number) => void;
  setOffset: (offset: number) => void;
  setDistinct: (distinct: boolean) => void;
  setDialect: (dialect: SqlDialect) => void;
  setVectorSearch: (vs: VectorSearchSpec | null) => void;
  setHybridSearch: (hs: HybridSearchSpec | null) => void;
  setCtes: (ctes: CteSpec[]) => void;
  setWindowFunctions: (wfs: WindowFunctionSpec[]) => void;
  loadSpec: (spec: QuerySpec<Schema> | Record<string, unknown>) => void;
  reset: () => void;
  markClean: () => void;
  undo: () => void;
  redo: () => void;
  clearHistory: () => void;
}

export interface UseQueryStateReturn<Schema = DatabaseSchemaDefinition> {
  state: QueryState<Schema>;
  actions: QueryStateActions<Schema>;
  history: QueryHistory<Schema>;
  spec: QuerySpec<Schema>;
}

export const MAX_HISTORY_LENGTH = 50;

/**
 * Converts internal QueryState to a serializable QuerySpec.
 */
export function stateToSpec<Schema = DatabaseSchemaDefinition>(state: QueryState<Schema>): QuerySpec<Schema> {
  const columns: (string | { column: string; agg?: string; alias?: string })[] = [];
  const keys =
    state.orderedProjectionKeys.length > 0
      ? state.orderedProjectionKeys
      : Object.keys(state.selectedColumns);

  for (const k of keys) {
    const col = state.selectedColumns[k];
    if (col) {
      if (col.aggregate || col.alias) {
        columns.push({
          column: `${col.table}.${col.name}`,
          agg: col.aggregate || undefined,
          alias: col.alias || undefined,
        });
      } else {
        columns.push(`${col.table}.${col.name}`);
      }
    }
  }

  const joins = (state.joins || []).map((j) => {
    const leftTable = j.left_table || state.primaryTable;
    return {
      table: j.table,
      type: j.type,
      left_table: leftTable,
      left_col: j.left_col,
      right_col: j.right_col,
      on: [{ left: `${leftTable}.${j.left_col}`, right: `${j.table}.${j.right_col}` }],
    };
  });

  // Resolve combiners ONCE so per-filter combiners and the aggregate filter_join always agree.
  const resolvedCombiners = resolveFilterCombiners(state.filters || []);
  const hasOrFilter = resolvedCombiners.hasOr;
  const filters = (state.filters || []).map((f, i) => ({
    column: f.column,
    op: f.operator,
    value: f.value,
    tablePrefix: f.tablePrefix,
    // With any OR present every filter states its combiner (see compileVisualState); AND-only
    // specs carry none, which keeps their round-trip exact.
    ...(hasOrFilter ? { combiner: resolvedCombiners.combiners[i] } : {}),
  }));

  const order_by = (state.sorts || []).map((s) => ({
    column: s.tablePrefix ? `${s.tablePrefix}.${s.column}` : s.column,
    direction: s.direction,
  }));

  const spec: QuerySpec<Schema> = {
    table: state.primaryTable,
    columns,
    joins,
    filters,
    // Per-filter combiners are authoritative; the aggregate flag only mirrors them.
    filter_join: resolvedCombiners.filterJoin,
    order_by,
    distinct: state.isDistinct,
    limit: state.limit,
  };

  if (state.offset !== undefined && state.offset !== 0) {
    spec.offset = state.offset;
  }
  if (state.vectorSearch) {
    spec.vector_search = state.vectorSearch;
  }
  if (state.hybridSearch) {
    spec.hybrid_search = state.hybridSearch;
  }
  if (state.ctes && state.ctes.length > 0) {
    spec.ctes = state.ctes;
  }
  if (state.windowFunctions && state.windowFunctions.length > 0) {
    spec.window_functions = state.windowFunctions;
  }

  return spec;
}

/**
 * Converts a QuerySpec or raw spec object to a partial QueryState.
 */
export function specToState<Schema = DatabaseSchemaDefinition>(
  spec: Partial<QuerySpec<Schema>> | Partial<QueryState<Schema>> | LooseQuerySpec | Record<string, unknown>,
): Partial<QueryState<Schema>> {
  const partial: Partial<QueryState<Schema>> = {};
  const s = spec as LooseQuerySpec;

  const primary = (s.table as string) || (s.primaryTable as string) || "";
  if (primary) {
    partial.primaryTable = primary as SchemaTableNames<Schema>;
  }

  if (Array.isArray(s.activeTables)) {
    partial.activeTables = s.activeTables as SchemaTableNames<Schema>[];
  } else if (primary) {
    partial.activeTables = [primary as SchemaTableNames<Schema>];
  }

  if (s.selectedColumns && typeof s.selectedColumns === "object") {
    partial.selectedColumns = s.selectedColumns as Record<string, VisualColumnSelect<Schema>>;
    partial.orderedProjectionKeys = Array.isArray(s.orderedProjectionKeys)
      ? (s.orderedProjectionKeys as string[])
      : Object.keys(s.selectedColumns);
  } else if (Array.isArray(s.columns)) {
    const selected: Record<string, VisualColumnSelect<Schema>> = {};
    const keys: string[] = [];

    for (const c of s.columns) {
      if (typeof c === "string") {
        const parts = c.split(".");
        const table = parts.length > 1 ? parts[0] : primary;
        const col = parts.length > 1 ? parts.slice(1).join(".") : parts[0];
        const key = `${table}.${col}`;
        selected[key] = { table: table as SchemaTableNames<Schema>, name: col };
        keys.push(key);
      } else if (c && typeof c === "object" && typeof c.column === "string") {
        const parts = c.column.split(".");
        const table = parts.length > 1 ? parts[0] : primary;
        const col = parts.length > 1 ? parts.slice(1).join(".") : parts[0];
        const rawExpr = c.raw_expression || c.rawExpression;
        const key = rawExpr ? `raw_${keys.length + 1}` : `${table}.${col}`;
        selected[key] = {
          table: table as SchemaTableNames<Schema>,
          name: col,
          aggregate: (c.agg as VisualColumnSelect["aggregate"]) || undefined,
          alias: c.alias,
          timeGrain: (c.time_grain || c.timeGrain) as TimeGrain | undefined,
          metric: c.metric,
          rawExpression: rawExpr,
        };
        keys.push(key);
      }
    }
    partial.selectedColumns = selected;
    partial.orderedProjectionKeys = keys;
  }

  if (Array.isArray(s.joins)) {
    partial.joins = s.joins.map((j, idx): VisualJoin<Schema> => {
      let leftCol = j.left_col || "id";
      let rightCol = j.right_col || "id";
      let leftTable = j.left_table;

      if (Array.isArray(j.on) && j.on.length > 0) {
        const firstOn = j.on[0];
        if (firstOn.left) {
          const lparts = firstOn.left.split(".");
          if (lparts.length > 1) {
            leftTable = lparts[0];
            leftCol = lparts.slice(1).join(".");
          } else {
            leftCol = lparts[0];
          }
        }
        if (firstOn.right) {
          const rparts = firstOn.right.split(".");
          if (rparts.length > 1) {
            rightCol = rparts.slice(1).join(".");
          } else {
            rightCol = rparts[0];
          }
        }
      }

      return {
        id: j.id || `join_${idx + 1}`,
        type: (j.type || "LEFT JOIN") as VisualJoin<Schema>["type"],
        left_table: leftTable as SchemaTableNames<Schema> | undefined,
        table: j.table as SchemaTableNames<Schema>,
        left_col: leftCol,
        right_col: rightCol,
      };
    });
  }

  // Spec-level `filter_join` is the default combiner for filters without their own.
  const specFilterJoin = normalizeCombiner(s.filter_join ?? s.filterJoin);

  if (Array.isArray(s.filters)) {
    partial.filters = s.filters.map((f, idx): VisualFilter<Schema> => {
      let col = f.column || "";
      let prefix = f.tablePrefix;
      if (!prefix && col.includes(".")) {
        const parts = col.split(".");
        prefix = parts[0];
        col = parts.slice(1).join(".");
      }
      return {
        id: f.id || `filter_${idx + 1}`,
        combiner: normalizeCombiner(f.combiner, specFilterJoin),
        tablePrefix: prefix as SchemaTableNames<Schema> | undefined,
        column: col,
        operator: (f.operator || f.op || "=").toUpperCase() === "RAW" ? "RAW" : (f.operator || f.op || "="),
        value: f.value ?? "",
        rawExpression: f.raw_expression || f.rawExpression,
      };
    });
  }

  if (Array.isArray(s.order_by)) {
    partial.sorts = s.order_by.map((sortItem, idx): VisualSort<Schema> => {
      let col = sortItem.column || "";
      let prefix = sortItem.tablePrefix;
      if (!prefix && col.includes(".")) {
        const parts = col.split(".");
        prefix = parts[0];
        col = parts.slice(1).join(".");
      }
      return {
        id: sortItem.id || `sort_${idx + 1}`,
        tablePrefix: prefix as SchemaTableNames<Schema> | undefined,
        column: col,
        direction: sortItem.direction || "ASC",
      };
    });
  } else if (Array.isArray(s.sorts)) {
    partial.sorts = s.sorts as VisualSort<Schema>[];
  }

  if (typeof s.distinct === "boolean") {
    partial.isDistinct = s.distinct;
  } else if (typeof s.isDistinct === "boolean") {
    partial.isDistinct = s.isDistinct;
  }

  if (typeof s.limit === "number") {
    partial.limit = s.limit;
  }

  if (typeof s.offset === "number") {
    partial.offset = s.offset;
  }

  if (typeof s.dialect === "string") {
    partial.dialect = s.dialect as SqlDialect;
  }

  if (s.vector_search || s.vectorSearch) {
    partial.vectorSearch = s.vector_search || s.vectorSearch;
  }

  if (s.hybrid_search || s.hybridSearch) {
    partial.hybridSearch = s.hybrid_search || s.hybridSearch;
  }

  if (Array.isArray(s.ctes)) {
    partial.ctes = s.ctes;
  }

  if (Array.isArray(s.window_functions) || Array.isArray(s.windowFunctions)) {
    partial.windowFunctions = (s.window_functions || s.windowFunctions) as WindowFunctionSpec[];
  }

  return partial;
}

export function createInitialState<Schema>(
  initial?: QuerySpec<Schema> | Partial<QueryState<Schema>> | Record<string, unknown>,
): QueryState<Schema> {
  const defaults: QueryState<Schema> = {
    primaryTable: "" as SchemaTableNames<Schema>,
    activeTables: [],
    selectedColumns: {},
    orderedProjectionKeys: [],
    joins: [],
    filters: [],
    sorts: [],
    isDistinct: false,
    limit: 50,
    offset: 0,
    dialect: "postgres",
    isDirty: false,
    vectorSearch: null,
    hybridSearch: null,
    ctes: [],
    windowFunctions: [],
  };

  if (!initial) {
    return defaults;
  }

  const parsed = specToState<Schema>(initial);
  return {
    ...defaults,
    ...parsed,
    primaryTable: (parsed.primaryTable || defaults.primaryTable) as SchemaTableNames<Schema>,
    activeTables: (parsed.activeTables || []) as SchemaTableNames<Schema>[],
    selectedColumns: parsed.selectedColumns || defaults.selectedColumns,
    orderedProjectionKeys: parsed.orderedProjectionKeys || defaults.orderedProjectionKeys,
    joins: parsed.joins || defaults.joins,
    filters: parsed.filters || defaults.filters,
    sorts: parsed.sorts || defaults.sorts,
    isDistinct: parsed.isDistinct ?? defaults.isDistinct,
    limit: typeof parsed.limit === "number" ? parsed.limit : defaults.limit,
    offset: typeof parsed.offset === "number" ? parsed.offset : defaults.offset,
    dialect: parsed.dialect || defaults.dialect,
    vectorSearch: parsed.vectorSearch !== undefined ? parsed.vectorSearch : defaults.vectorSearch,
    hybridSearch: parsed.hybridSearch !== undefined ? parsed.hybridSearch : defaults.hybridSearch,
    ctes: parsed.ctes ?? defaults.ctes,
    windowFunctions: parsed.windowFunctions ?? defaults.windowFunctions,
    isDirty: false,
  };
}

/**
 * Headless state management hook for Query-Builder.
 */
export function useQueryState<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition>(
  initialSpecOrState?: QuerySpec<Schema> | Partial<QueryState<Schema>> | Record<string, unknown>,
): UseQueryStateReturn<Schema> {
  const initialRef = useRef<QueryState<Schema>>(createInitialState<Schema>(initialSpecOrState));
  const [historyState, setHistoryState] = useState<{
    past: QueryState<Schema>[];
    present: QueryState<Schema>;
    future: QueryState<Schema>[];
  }>(() => ({
    past: [],
    present: initialRef.current,
    future: [],
  }));

  const state = historyState.present;
  const past = historyState.past;
  const future = historyState.future;

  const applyUpdate = useCallback((updater: (prev: QueryState<Schema>) => QueryState<Schema>) => {
    setHistoryState((curr) => {
      const next = updater(curr.present);
      const nextPast = [...curr.past, curr.present];
      const trimmedPast =
        nextPast.length > MAX_HISTORY_LENGTH
          ? nextPast.slice(nextPast.length - MAX_HISTORY_LENGTH)
          : nextPast;
      return {
        past: trimmedPast,
        present: { ...next, isDirty: true },
        future: [],
      };
    });
  }, []);

  const setTables = useCallback((tables: SchemaTableNames<Schema>[]) => {
    applyUpdate((prev) => ({
      ...prev,
      activeTables: tables,
      primaryTable: tables.includes(prev.primaryTable) ? prev.primaryTable : tables[0] || ("" as SchemaTableNames<Schema>),
    }));
  }, [applyUpdate]);

  const setPrimaryTable = useCallback((table: SchemaTableNames<Schema>) => {
    applyUpdate((prev) => ({
      ...prev,
      primaryTable: table,
      activeTables: prev.activeTables.includes(table)
        ? prev.activeTables
        : [...prev.activeTables, table],
    }));
  }, [applyUpdate]);

  const addTable = useCallback((table: SchemaTableNames<Schema>) => {
    applyUpdate((prev) => {
      if (prev.activeTables.includes(table)) return prev;
      return {
        ...prev,
        activeTables: [...prev.activeTables, table],
        primaryTable: prev.primaryTable || table,
      };
    });
  }, [applyUpdate]);

  const removeTable = useCallback((table: SchemaTableNames<Schema>) => {
    applyUpdate((prev) => {
      const nextActive = prev.activeTables.filter((t) => t !== table);
      const nextPrimary =
        prev.primaryTable === table ? (nextActive[0] || ("" as SchemaTableNames<Schema>)) : prev.primaryTable;
      const nextJoins = prev.joins.filter((j) => j.table !== table && j.left_table !== table);
      const nextSelected: Record<string, VisualColumnSelect<Schema>> = {};
      for (const [k, col] of Object.entries(prev.selectedColumns)) {
        if (col.table !== table) {
          nextSelected[k] = col;
        }
      }
      const nextOrderedKeys = prev.orderedProjectionKeys.filter(
        (k) => !k.startsWith(`${table}.`),
      );
      return {
        ...prev,
        activeTables: nextActive,
        primaryTable: nextPrimary,
        joins: nextJoins,
        selectedColumns: nextSelected,
        orderedProjectionKeys: nextOrderedKeys,
      };
    });
  }, [applyUpdate]);

  const toggleColumn = useCallback(
    (table: SchemaTableNames<Schema>, col: SchemaColumnNames<Schema, string> | string) => {
      applyUpdate((prev) => {
        const key = `${table}.${col}`;
        const nextSelected = { ...prev.selectedColumns };
        let nextKeys = [...prev.orderedProjectionKeys];

        if (nextSelected[key]) {
          delete nextSelected[key];
          nextKeys = nextKeys.filter((k) => k !== key);
        } else {
          nextSelected[key] = { table, name: col };
          if (!nextKeys.includes(key)) {
            nextKeys.push(key);
          }
        }

        return {
          ...prev,
          selectedColumns: nextSelected,
          orderedProjectionKeys: nextKeys,
        };
      });
    },
    [applyUpdate],
  );

  const updateColumnSelect = useCallback(
    (key: string, updates: Partial<VisualColumnSelect<Schema>>) => {
      applyUpdate((prev) => {
        if (!prev.selectedColumns[key]) return prev;
        return {
          ...prev,
          selectedColumns: {
            ...prev.selectedColumns,
            [key]: { ...prev.selectedColumns[key], ...updates },
          },
        };
      });
    },
    [applyUpdate],
  );

  const removeColumnProjection = useCallback(
    (key: string) => {
      applyUpdate((prev) => {
        const nextSelected = { ...prev.selectedColumns };
        delete nextSelected[key];
        return {
          ...prev,
          selectedColumns: nextSelected,
          orderedProjectionKeys: prev.orderedProjectionKeys.filter((k) => k !== key),
        };
      });
    },
    [applyUpdate],
  );

  const setSelectedColumns = useCallback(
    (
      selected: Record<string, VisualColumnSelect<Schema>>,
      orderedKeys?: string[],
    ) => {
      applyUpdate((prev) => ({
        ...prev,
        selectedColumns: selected,
        orderedProjectionKeys: orderedKeys ?? Object.keys(selected),
      }));
    },
    [applyUpdate],
  );

  const setOrderedProjectionKeys = useCallback(
    (keys: string[]) => {
      applyUpdate((prev) => ({
        ...prev,
        orderedProjectionKeys: keys,
      }));
    },
    [applyUpdate],
  );

  const setJoins = useCallback(
    (joins: VisualJoin<Schema>[]) => {
      applyUpdate((prev) => ({
        ...prev,
        joins,
      }));
    },
    [applyUpdate],
  );

  const addJoin = useCallback(
    (join: VisualJoin<Schema>) => {
      applyUpdate((prev) => ({
        ...prev,
        joins: [...prev.joins, join],
      }));
    },
    [applyUpdate],
  );

  const autoJoinTable = useCallback(
    (
      targetTable: SchemaTableNames<Schema> | string,
      schema?: SchemaSnapshot | null,
    ) => {
      if (!targetTable) return;
      applyUpdate((prev) => {
        const active =
          prev.activeTables.length > 0
            ? prev.activeTables
            : prev.primaryTable
              ? [prev.primaryTable]
              : [];
        const pathJoins = findJoinPath(active as string[], targetTable as string, schema);

        if (pathJoins.length > 0) {
          const newActive = new Set(prev.activeTables as string[]);
          for (const pj of pathJoins) {
            if (pj.table) newActive.add(pj.table);
            if (pj.left_table) newActive.add(pj.left_table);
          }
          newActive.add(targetTable as string);

          return {
            ...prev,
            joins: [...prev.joins, ...(pathJoins as VisualJoin<Schema>[])],
            activeTables: Array.from(newActive) as SchemaTableNames<Schema>[],
          };
        } else {
          const base = (prev.primaryTable || active[0] || "table") as string;
          const cond = findBestJoinCondition(base, targetTable as string, schema);
          const fallbackJoin: VisualJoin<Schema> = {
            id: `join-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
            type: "LEFT JOIN",
            left_table: cond.leftTable as SchemaTableNames<Schema>,
            left_col: cond.leftCol,
            table: cond.rightTable as SchemaTableNames<Schema>,
            right_col: cond.rightCol,
          };
          const newActive = new Set(prev.activeTables as string[]);
          newActive.add(cond.rightTable);

          return {
            ...prev,
            joins: [...prev.joins, fallbackJoin],
            activeTables: Array.from(newActive) as SchemaTableNames<Schema>[],
          };
        }
      });
    },
    [applyUpdate],
  );

  const updateJoin = useCallback(
    (id: string, updates: Partial<VisualJoin<Schema>>) => {
      applyUpdate((prev) => ({
        ...prev,
        joins: prev.joins.map((j) => (j.id === id ? { ...j, ...updates } : j)),
      }));
    },
    [applyUpdate],
  );

  const removeJoin = useCallback(
    (id: string) => {
      applyUpdate((prev) => ({
        ...prev,
        joins: prev.joins.filter((j) => j.id !== id),
      }));
    },
    [applyUpdate],
  );

  const setFilters = useCallback(
    (filters: VisualFilter<Schema>[]) => {
      applyUpdate((prev) => ({
        ...prev,
        filters,
      }));
    },
    [applyUpdate],
  );

  const addFilter = useCallback(
    (filter: VisualFilter<Schema>) => {
      applyUpdate((prev) => ({
        ...prev,
        filters: [...prev.filters, filter],
      }));
    },
    [applyUpdate],
  );

  const updateFilter = useCallback(
    (id: string, updates: Partial<VisualFilter<Schema>>) => {
      applyUpdate((prev) => ({
        ...prev,
        filters: prev.filters.map((f) => (f.id === id ? { ...f, ...updates } : f)),
      }));
    },
    [applyUpdate],
  );

  const removeFilter = useCallback(
    (id: string) => {
      applyUpdate((prev) => ({
        ...prev,
        filters: prev.filters.filter((f) => f.id !== id),
      }));
    },
    [applyUpdate],
  );

  const setSorts = useCallback(
    (sorts: VisualSort<Schema>[]) => {
      applyUpdate((prev) => ({
        ...prev,
        sorts,
      }));
    },
    [applyUpdate],
  );

  const addSort = useCallback(
    (sort: VisualSort<Schema>) => {
      applyUpdate((prev) => ({
        ...prev,
        sorts: [...prev.sorts, sort],
      }));
    },
    [applyUpdate],
  );

  const updateSort = useCallback(
    (id: string, updates: Partial<VisualSort<Schema>>) => {
      applyUpdate((prev) => ({
        ...prev,
        sorts: prev.sorts.map((s) => (s.id === id ? { ...s, ...updates } : s)),
      }));
    },
    [applyUpdate],
  );

  const removeSort = useCallback(
    (id: string) => {
      applyUpdate((prev) => ({
        ...prev,
        sorts: prev.sorts.filter((s) => s.id !== id),
      }));
    },
    [applyUpdate],
  );

  const setLimit = useCallback(
    (limit: number) => {
      applyUpdate((prev) => ({ ...prev, limit }));
    },
    [applyUpdate],
  );

  const setOffset = useCallback(
    (offset: number) => {
      applyUpdate((prev) => ({ ...prev, offset }));
    },
    [applyUpdate],
  );

  const setDistinct = useCallback(
    (distinct: boolean) => {
      applyUpdate((prev) => ({ ...prev, isDistinct: distinct }));
    },
    [applyUpdate],
  );

  const setDialect = useCallback(
    (dialect: SqlDialect) => {
      applyUpdate((prev) => ({ ...prev, dialect }));
    },
    [applyUpdate],
  );

  const setVectorSearch = useCallback(
    (vs: VectorSearchSpec | null) => {
      applyUpdate((prev) => ({ ...prev, vectorSearch: vs }));
    },
    [applyUpdate],
  );

  const setHybridSearch = useCallback(
    (hs: HybridSearchSpec | null) => {
      applyUpdate((prev) => ({ ...prev, hybridSearch: hs }));
    },
    [applyUpdate],
  );

  const setCtes = useCallback(
    (ctes: CteSpec[]) => {
      applyUpdate((prev) => ({ ...prev, ctes }));
    },
    [applyUpdate],
  );

  const setWindowFunctions = useCallback(
    (wfs: WindowFunctionSpec[]) => {
      applyUpdate((prev) => ({ ...prev, windowFunctions: wfs }));
    },
    [applyUpdate],
  );

  const loadSpec = useCallback(
    (spec: QuerySpec<Schema> | Record<string, unknown>) => {
      const parsed = specToState<Schema>(spec);
      const isFullSpec = Boolean(parsed.primaryTable || (spec as LooseQuerySpec).table);
      applyUpdate((prev) => {
        const activeTables = parsed.activeTables || prev.activeTables;

        return {
          ...prev,
          ...parsed,
          primaryTable: (parsed.primaryTable || prev.primaryTable) as SchemaTableNames<Schema>,
          activeTables,
          selectedColumns: parsed.selectedColumns ?? (isFullSpec ? {} : prev.selectedColumns),
          orderedProjectionKeys:
            parsed.orderedProjectionKeys ?? (isFullSpec ? [] : prev.orderedProjectionKeys),
          joins: parsed.joins ?? (isFullSpec ? [] : prev.joins),
          filters: parsed.filters ?? (isFullSpec ? [] : prev.filters),
          sorts: parsed.sorts ?? (isFullSpec ? [] : prev.sorts),
          isDistinct: parsed.isDistinct ?? (isFullSpec ? false : prev.isDistinct),
          limit: typeof parsed.limit === "number" ? parsed.limit : (isFullSpec ? 50 : prev.limit),
          offset: typeof parsed.offset === "number" ? parsed.offset : (isFullSpec ? 0 : prev.offset),
          dialect: parsed.dialect || prev.dialect,
          vectorSearch:
            parsed.vectorSearch !== undefined ? parsed.vectorSearch : (isFullSpec ? null : prev.vectorSearch),
          hybridSearch:
            parsed.hybridSearch !== undefined ? parsed.hybridSearch : (isFullSpec ? null : prev.hybridSearch),
          ctes: parsed.ctes !== undefined ? parsed.ctes : (isFullSpec ? [] : prev.ctes),
          windowFunctions:
            parsed.windowFunctions !== undefined
              ? parsed.windowFunctions
              : (isFullSpec ? [] : prev.windowFunctions),
        };
      });
    },
    [applyUpdate],
  );

  const undo = useCallback(() => {
    setHistoryState((curr) => {
      if (curr.past.length === 0) return curr;
      const previous = curr.past[curr.past.length - 1];
      const remaining = curr.past.slice(0, curr.past.length - 1);
      return {
        past: remaining,
        present: previous,
        future: [curr.present, ...curr.future],
      };
    });
  }, []);

  const redo = useCallback(() => {
    setHistoryState((curr) => {
      if (curr.future.length === 0) return curr;
      const next = curr.future[0];
      const remaining = curr.future.slice(1);
      return {
        past: [...curr.past, curr.present],
        present: next,
        future: remaining,
      };
    });
  }, []);

  const clearHistory = useCallback(() => {
    setHistoryState((curr) => ({
      ...curr,
      past: [],
      future: [],
    }));
  }, []);

  const reset = useCallback(() => {
    setHistoryState({
      past: [],
      present: initialRef.current,
      future: [],
    });
  }, []);

  const markClean = useCallback(() => {
    setHistoryState((curr) => ({
      ...curr,
      present: { ...curr.present, isDirty: false },
    }));
  }, []);

  const history = useMemo<QueryHistory<Schema>>(
    () => ({
      past,
      future,
      canUndo: past.length > 0,
      canRedo: future.length > 0,
    }),
    [past, future],
  );

  const spec = useMemo<QuerySpec<Schema>>(() => stateToSpec<Schema>(state), [state]);

  const actions = useMemo<QueryStateActions<Schema>>(
    () => ({
      setTables,
      setPrimaryTable,
      addTable,
      removeTable,
      toggleColumn,
      updateColumnSelect,
      removeColumnProjection,
      setSelectedColumns,
      setOrderedProjectionKeys,
      setJoins,
      addJoin,
      autoJoinTable,
      updateJoin,
      removeJoin,
      setFilters,
      addFilter,
      updateFilter,
      removeFilter,
      setSorts,
      addSort,
      updateSort,
      removeSort,
      setLimit,
      setOffset,
      setDistinct,
      setDialect,
      setVectorSearch,
      setHybridSearch,
      setCtes,
      setWindowFunctions,
      loadSpec,
      reset,
      markClean,
      undo,
      redo,
      clearHistory,
    }),
    [
      setTables,
      setPrimaryTable,
      addTable,
      removeTable,
      toggleColumn,
      updateColumnSelect,
      removeColumnProjection,
      setSelectedColumns,
      setOrderedProjectionKeys,
      setJoins,
      addJoin,
      autoJoinTable,
      updateJoin,
      removeJoin,
      setFilters,
      addFilter,
      updateFilter,
      removeFilter,
      setSorts,
      addSort,
      updateSort,
      removeSort,
      setLimit,
      setOffset,
      setDistinct,
      setDialect,
      setVectorSearch,
      setHybridSearch,
      setCtes,
      setWindowFunctions,
      loadSpec,
      reset,
      markClean,
      undo,
      redo,
      clearHistory,
    ],
  );

  return {
    state,
    actions,
    history,
    spec,
  };
}
