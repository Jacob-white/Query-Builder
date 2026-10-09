import { useState, useCallback, useMemo, useRef } from "react";
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
  SerializedQuerySpec,
  VectorSearchSpec,
  HybridSearchSpec,
  CteSpec,
  WindowFunctionSpec,
} from "../types";
import {
  addTableToState,
  appendItem,
  autoJoinOnState,
  emptyTable,
  narrowSerializedSpec,
  removeColumnProjectionFromState,
  removeItemById,
  removeTableFromState,
  setPrimaryTableOnState,
  setTablesOnState,
  specToState,
  stateToSpec,
  toggleColumnOnState,
  updateColumnSelectOnState,
  updateItemById,
  type SpecStatePartial,
} from "../utils/queryStateTransitions";

export { specToState, stateToSpec };

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
  loadSpec: (spec: QuerySpec<Schema> | SerializedQuerySpec) => void;
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

/** Anything `useQueryState` can start from: a (partial) spec, a serialized spec or a partial state. */
export type QueryStateInit<Schema = DatabaseSchemaDefinition> =
  | QuerySpec<Schema>
  | Partial<QuerySpec<Schema>>
  | Partial<QueryState<Schema>>
  | SerializedQuerySpec;

export function createInitialState<Schema>(
  initial?: QueryStateInit<Schema>,
): QueryState<Schema> {
  const defaults: QueryState<Schema> = {
    primaryTable: emptyTable<Schema>(),
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
    primaryTable: parsed.primaryTable || defaults.primaryTable,
    activeTables: parsed.activeTables || [],
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
 * Merges a parsed spec into the current state. A "full" spec (one naming a table) replaces every
 * section it omits with its default; a partial spec only overwrites what it carries.
 */
function mergeParsedSpec<Schema>(
  prev: QueryState<Schema>,
  parsed: SpecStatePartial<Schema>,
  isFullSpec: boolean,
): QueryState<Schema> {
  return {
    ...prev,
    ...parsed,
    primaryTable: parsed.primaryTable || prev.primaryTable,
    activeTables: parsed.activeTables || prev.activeTables,
    selectedColumns: parsed.selectedColumns ?? (isFullSpec ? {} : prev.selectedColumns),
    orderedProjectionKeys: parsed.orderedProjectionKeys ?? (isFullSpec ? [] : prev.orderedProjectionKeys),
    joins: parsed.joins ?? (isFullSpec ? [] : prev.joins),
    filters: parsed.filters ?? (isFullSpec ? [] : prev.filters),
    sorts: parsed.sorts ?? (isFullSpec ? [] : prev.sorts),
    isDistinct: parsed.isDistinct ?? (isFullSpec ? false : prev.isDistinct),
    limit: typeof parsed.limit === "number" ? parsed.limit : isFullSpec ? 50 : prev.limit,
    offset: typeof parsed.offset === "number" ? parsed.offset : isFullSpec ? 0 : prev.offset,
    dialect: parsed.dialect || prev.dialect,
    vectorSearch: parsed.vectorSearch !== undefined ? parsed.vectorSearch : isFullSpec ? null : prev.vectorSearch,
    hybridSearch: parsed.hybridSearch !== undefined ? parsed.hybridSearch : isFullSpec ? null : prev.hybridSearch,
    ctes: parsed.ctes !== undefined ? parsed.ctes : isFullSpec ? [] : prev.ctes,
    windowFunctions:
      parsed.windowFunctions !== undefined ? parsed.windowFunctions : isFullSpec ? [] : prev.windowFunctions,
  };
}

interface HistoryState<Schema> {
  past: QueryState<Schema>[];
  present: QueryState<Schema>;
  future: QueryState<Schema>[];
}

/**
 * Headless state management hook for Query-Builder.
 */
export function useQueryState<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition>(
  initialSpecOrState?: QueryStateInit<Schema>,
): UseQueryStateReturn<Schema> {
  const initialRef = useRef<QueryState<Schema>>(createInitialState<Schema>(initialSpecOrState));
  const [historyState, setHistoryState] = useState<HistoryState<Schema>>(() => ({
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
        nextPast.length > MAX_HISTORY_LENGTH ? nextPast.slice(nextPast.length - MAX_HISTORY_LENGTH) : nextPast;
      return { past: trimmedPast, present: { ...next, isDirty: true }, future: [] };
    });
  }, []);

  const actions = useMemo<QueryStateActions<Schema>>(() => {
    const patch = (fields: Partial<QueryState<Schema>>) => applyUpdate((prev) => ({ ...prev, ...fields }));
    return {
      setTables: (tables) => applyUpdate((prev) => setTablesOnState(prev, tables)),
      setPrimaryTable: (table) => applyUpdate((prev) => setPrimaryTableOnState(prev, table)),
      // Adding an already-active table is a complete no-op here (the primary table is left alone).
      addTable: (table) =>
        applyUpdate((prev) => (prev.activeTables.includes(table) ? prev : addTableToState(prev, table))),
      removeTable: (table) => applyUpdate((prev) => removeTableFromState(prev, table)),
      toggleColumn: (table, col) => applyUpdate((prev) => toggleColumnOnState(prev, table, col as string)),
      updateColumnSelect: (key, updates) => applyUpdate((prev) => updateColumnSelectOnState(prev, key, updates)),
      removeColumnProjection: (key) => applyUpdate((prev) => removeColumnProjectionFromState(prev, key)),
      setSelectedColumns: (selected, orderedKeys) =>
        patch({ selectedColumns: selected, orderedProjectionKeys: orderedKeys ?? Object.keys(selected) }),
      setOrderedProjectionKeys: (keys) => patch({ orderedProjectionKeys: keys }),
      setJoins: (joins) => patch({ joins }),
      addJoin: (join) => applyUpdate((prev) => ({ ...prev, joins: appendItem(prev.joins, join) })),
      autoJoinTable: (targetTable, schema) => {
        if (!targetTable) return;
        applyUpdate((prev) => autoJoinOnState(prev, targetTable, schema));
      },
      updateJoin: (id, updates) =>
        applyUpdate((prev) => ({ ...prev, joins: updateItemById(prev.joins, id, updates) })),
      removeJoin: (id) => applyUpdate((prev) => ({ ...prev, joins: removeItemById(prev.joins, id) })),
      setFilters: (filters) => patch({ filters }),
      addFilter: (filter) => applyUpdate((prev) => ({ ...prev, filters: appendItem(prev.filters, filter) })),
      updateFilter: (id, updates) =>
        applyUpdate((prev) => ({ ...prev, filters: updateItemById(prev.filters, id, updates) })),
      removeFilter: (id) => applyUpdate((prev) => ({ ...prev, filters: removeItemById(prev.filters, id) })),
      setSorts: (sorts) => patch({ sorts }),
      addSort: (sort) => applyUpdate((prev) => ({ ...prev, sorts: appendItem(prev.sorts, sort) })),
      updateSort: (id, updates) =>
        applyUpdate((prev) => ({ ...prev, sorts: updateItemById(prev.sorts, id, updates) })),
      removeSort: (id) => applyUpdate((prev) => ({ ...prev, sorts: removeItemById(prev.sorts, id) })),
      setLimit: (limit) => patch({ limit }),
      setOffset: (offset) => patch({ offset }),
      setDistinct: (distinct) => patch({ isDistinct: distinct }),
      setDialect: (dialect) => patch({ dialect }),
      setVectorSearch: (vs) => patch({ vectorSearch: vs }),
      setHybridSearch: (hs) => patch({ hybridSearch: hs }),
      setCtes: (ctes) => patch({ ctes }),
      setWindowFunctions: (wfs) => patch({ windowFunctions: wfs }),
      loadSpec: (spec) => {
        const narrowed = narrowSerializedSpec(spec);
        const parsed = specToState<Schema>(narrowed);
        const isFullSpec = Boolean(parsed.primaryTable || narrowed.table);
        applyUpdate((prev) => mergeParsedSpec(prev, parsed, isFullSpec));
      },
      reset: () => setHistoryState({ past: [], present: initialRef.current, future: [] }),
      markClean: () => setHistoryState((curr) => ({ ...curr, present: { ...curr.present, isDirty: false } })),
      undo: () =>
        setHistoryState((curr) => {
          if (curr.past.length === 0) return curr;
          return {
            past: curr.past.slice(0, curr.past.length - 1),
            present: curr.past[curr.past.length - 1],
            future: [curr.present, ...curr.future],
          };
        }),
      redo: () =>
        setHistoryState((curr) => {
          if (curr.future.length === 0) return curr;
          return { past: [...curr.past, curr.present], present: curr.future[0], future: curr.future.slice(1) };
        }),
      clearHistory: () => setHistoryState((curr) => ({ ...curr, past: [], future: [] })),
    };
  }, [applyUpdate]);

  const history = useMemo<QueryHistory<Schema>>(
    () => ({ past, future, canUndo: past.length > 0, canRedo: future.length > 0 }),
    [past, future],
  );

  const spec = useMemo<QuerySpec<Schema>>(() => stateToSpec<Schema>(state), [state]);

  return { state, actions, history, spec };
}
