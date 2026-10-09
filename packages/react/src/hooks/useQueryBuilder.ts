import { useState, useMemo, useRef, useEffect, type SetStateAction } from "react";
import type {
  DatabaseSchemaDefinition,
  SchemaSnapshot,
  TableMeta,
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  SqlDialect,
  QueryTemplate,
  SqlSafetyValidation,
  SchemaTableNames,
  SchemaColumnNames,
  SchemaColumnRefs,
  QuerySpec,
  SerializedQuerySpec,
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
import { normalizeCombiner } from "../utils/filterCombiners";
import {
  addTableToState,
  appendItem,
  applyBuilderSpecPatch,
  autoJoinOnState,
  emptyTable,
  isSpecShaped,
  narrowSerializedSpec,
  removeColumnProjectionFromState,
  removeItemById,
  removeTableFromState,
  specToBuilderPatch,
  toggleColumnOnState,
  updateColumnSelectOnState,
  updateItemById,
  type BuilderPatchTarget,
} from "../utils/queryStateTransitions";

export interface UseQueryBuilderOptions<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition> {
  schema?: SchemaSnapshot | Schema | null;
  initialTable?: SchemaTableNames<Schema>;
  dialect?: SqlDialect;
  initialLimit?: number;
  initialDistinct?: boolean;
  initialSql?: string;
  initialSpec?: SerializedQuerySpec | QuerySpec<Schema>;
  initialSelectedColumns?: Record<string, VisualColumnSelect<Schema>>;
  initialOrderedProjectionKeys?: (SchemaColumnRefs<Schema> | string)[];
  initialJoins?: VisualJoin<Schema>[];
  initialFilters?: VisualFilter<Schema>[];
  initialSorts?: VisualSort<Schema>[];
  initialActiveTables?: SchemaTableNames<Schema>[];
  customOperators?: Record<string, CustomFilterOperator>;
  vectorSearch?: VectorSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  ctes?: CteSpec[] | null;
  windowFunctions?: WindowFunctionSpec[] | null;
  semanticModels?: SemanticModel[] | null;
  filterJoin?: "AND" | "OR";
}

export interface QueryBuilderState<Schema = DatabaseSchemaDefinition> {
  primaryTable: SchemaTableNames<Schema>;
  activeTableNames: SchemaTableNames<Schema>[];
  activeTables: TableMeta[];
  selectedColumns: Record<string, VisualColumnSelect<Schema>>;
  orderedProjectionKeys: string[];
  joins: VisualJoin<Schema>[];
  filters: VisualFilter<Schema>[];
  sorts: VisualSort<Schema>[];
  isDistinct: boolean;
  limit: number;
  dialect: SqlDialect;
  rawSql: string;
  isRawMode: boolean;
  isDirty: boolean;
  vectorSearch?: VectorSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  ctes?: CteSpec[] | null;
  windowFunctions?: WindowFunctionSpec[] | null;
  semanticModels?: SemanticModel[] | null;
  filterJoin?: "AND" | "OR";
}

export interface QueryBuilderActions<Schema = DatabaseSchemaDefinition> {
  setPrimaryTable: (table: SchemaTableNames<Schema>) => void;
  addTable: (tableName: SchemaTableNames<Schema>) => void;
  removeTable: (tableName: SchemaTableNames<Schema>) => void;
  toggleColumn: <T extends SchemaTableNames<Schema>>(
    tableName: T,
    colName: SchemaColumnNames<Schema, T> | string,
  ) => void;
  updateColumnSelect: (key: string, updates: Partial<VisualColumnSelect<Schema>>) => void;
  removeColumnProjection: (key: string) => void;
  setJoins: React.Dispatch<React.SetStateAction<VisualJoin<Schema>[]>>;
  addJoin: (join: VisualJoin<Schema>) => void;
  autoJoinTable: (targetTable: SchemaTableNames<Schema> | string) => void;
  updateJoin: (id: string, updates: Partial<VisualJoin<Schema>>) => void;
  removeJoin: (id: string) => void;
  setFilters: React.Dispatch<React.SetStateAction<VisualFilter<Schema>[]>>;
  addFilter: (filter: VisualFilter<Schema>) => void;
  updateFilter: (id: string, updates: Partial<VisualFilter<Schema>>) => void;
  removeFilter: (id: string) => void;
  setSorts: React.Dispatch<React.SetStateAction<VisualSort<Schema>[]>>;
  addSort: (sort: VisualSort<Schema>) => void;
  updateSort: (id: string, updates: Partial<VisualSort<Schema>>) => void;
  removeSort: (id: string) => void;
  setIsDistinct: (distinct: boolean) => void;
  setLimit: (limit: number) => void;
  setDialect: (dialect: SqlDialect) => void;
  setRawSql: (sql: string) => void;
  setIsRawMode: (isRaw: boolean) => void;
  loadTemplate: (template: QueryTemplate) => void;
  loadSpec: (spec: SerializedQuerySpec | QuerySpec<Schema>) => void;
  reset: () => void;
  markClean: () => void;
  setVectorSearch?: (vs: VectorSearchSpec | null) => void;
  setHybridSearch?: (hs: HybridSearchSpec | null) => void;
  setCtes?: (ctes: CteSpec[] | null) => void;
  setWindowFunctions?: (wfs: WindowFunctionSpec[] | null) => void;
  setSemanticModels?: (models: SemanticModel[] | null) => void;
  setFilterJoin?: (join: "AND" | "OR") => void;
}

export interface UseQueryBuilderReturn<Schema = DatabaseSchemaDefinition> {
  state: QueryBuilderState<Schema>;
  compiled: CompiledVisualQuery;
  currentSql: string;
  safety: SqlSafetyValidation;
  actions: QueryBuilderActions<Schema>;
}

/** Everything the builder stores, in one object (`activeTables` holds table NAMES). */
interface BuilderStore<Schema> extends BuilderPatchTarget<Schema> {
  dialect: SqlDialect;
  rawSql: string;
  isRawMode: boolean;
  /** Serialized form of the "clean" baseline that `isDirty` is measured against. */
  cleanSnapshot: string;
}

/** Fields that participate in dirty tracking (compile-only extras like CTEs deliberately do not). */
function computeSnapshot<Schema>(s: BuilderStore<Schema>): string {
  return JSON.stringify({
    primaryTable: s.primaryTable,
    activeTableNames: s.activeTables,
    selectedColumns: s.selectedColumns,
    orderedProjectionKeys: s.orderedProjectionKeys,
    joins: s.joins,
    filters: s.filters,
    sorts: s.sorts,
    isDistinct: s.isDistinct,
    limit: s.limit,
    dialect: s.dialect,
    rawSql: s.rawSql,
    isRawMode: s.isRawMode,
  });
}

function isUpdater<T>(update: SetStateAction<T>): update is (prev: T) => T {
  return typeof update === "function";
}

/** Resolves a `useState`-style argument (value or updater) against the previous value. */
function resolveUpdate<T>(update: SetStateAction<T>, prev: T): T {
  return isUpdater(update) ? update(prev) : update;
}

function buildInitialStore<Schema extends DatabaseSchemaDefinition>(
  options: UseQueryBuilderOptions<Schema>,
  normalizedSchema: SchemaSnapshot | null | undefined,
  init: SerializedQuerySpec,
): BuilderStore<Schema> {
  // A QuerySpec-shaped initialSpec is converted exactly like `actions.loadSpec` would.
  const specInit = isSpecShaped(init) ? specToBuilderPatch<Schema>(init) : undefined;

  const primaryTable: SchemaTableNames<Schema> =
    options.initialTable ||
    (init.primaryTable as SchemaTableNames<Schema> | undefined) ||
    (init.table as SchemaTableNames<Schema> | undefined) ||
    (normalizedSchema?.tables
      ? (Object.keys(normalizedSchema.tables)[0] as SchemaTableNames<Schema>) || emptyTable<Schema>()
      : emptyTable<Schema>());

  const store: BuilderStore<Schema> = {
    primaryTable,
    activeTables:
      options.initialActiveTables ||
      (init.activeTables as SchemaTableNames<Schema>[] | undefined) ||
      specInit?.activeTables?.([]) ||
      (primaryTable ? [primaryTable] : []),
    selectedColumns:
      options.initialSelectedColumns ||
      (init.selectedColumns as Record<string, VisualColumnSelect<Schema>> | undefined) ||
      specInit?.selectedColumns ||
      {},
    orderedProjectionKeys:
      (options.initialOrderedProjectionKeys as string[] | undefined) ||
      init.orderedProjectionKeys ||
      specInit?.orderedProjectionKeys ||
      [],
    joins: options.initialJoins || specInit?.joins || (init.joins as VisualJoin<Schema>[] | undefined) || [],
    filters: options.initialFilters || specInit?.filters || (init.filters as VisualFilter<Schema>[] | undefined) || [],
    sorts: options.initialSorts || specInit?.sorts || (init.sorts as VisualSort<Schema>[] | undefined) || [],
    isDistinct:
      typeof options.initialDistinct === "boolean"
        ? options.initialDistinct
        : Boolean(init.isDistinct ?? init.distinct),
    limit:
      typeof options.initialLimit === "number"
        ? options.initialLimit
        : typeof init.limit === "number"
          ? init.limit
          : 50,
    dialect: options.dialect || "postgres",
    rawSql: options.initialSql || "",
    isRawMode: Boolean(options.initialSql),
    vectorSearch: options.vectorSearch || init.vector_search || init.vectorSearch || null,
    hybridSearch: options.hybridSearch || init.hybrid_search || init.hybridSearch || null,
    ctes: options.ctes || init.ctes || null,
    windowFunctions: options.windowFunctions || init.window_functions || init.windowFunctions || null,
    semanticModels: options.semanticModels || init.semantic_models || init.semanticModels || null,
    filterJoin: normalizeCombiner(options.filterJoin || init.filter_join || init.filterJoin),
    cleanSnapshot: "",
  };
  store.cleanSnapshot = computeSnapshot(store);
  return store;
}

export function useQueryBuilder<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition>(
  options: UseQueryBuilderOptions<Schema> = {},
): UseQueryBuilderReturn<Schema> {
  const normalizedSchema = useMemo(() => normalizeSchema(options.schema), [options.schema]);
  const init = useMemo(() => narrowSerializedSpec(options.initialSpec), [options.initialSpec]);

  const initial = buildInitialStore<Schema>(options, normalizedSchema, init);
  const [store, setStore] = useState<BuilderStore<Schema>>(initial);

  // Latest initial values live in a ref so `reset` keeps a stable identity even when callers pass
  // inline arrays/objects (new references every render). Written post-commit (not during render)
  // so discarded concurrent renders can't leak in.
  const initRef = useRef(initial);
  const schemaRef = useRef(normalizedSchema);
  useEffect(() => {
    initRef.current = initial;
    schemaRef.current = normalizedSchema;
  });

  const {
    primaryTable,
    activeTables: activeTableNames,
    selectedColumns,
    orderedProjectionKeys,
    joins,
    filters,
    sorts,
    isDistinct,
    limit,
    dialect,
    rawSql,
    isRawMode,
    vectorSearch,
    hybridSearch,
    ctes,
    windowFunctions,
    semanticModels,
    filterJoin,
  } = store;
  const { customOperators } = options;

  const activeTables: TableMeta[] = useMemo(
    () =>
      activeTableNames
        .map((name) => normalizedSchema?.tables?.[name as string])
        .filter((t): t is TableMeta => Boolean(t)),
    [activeTableNames, normalizedSchema],
  );

  const compiled = useMemo(
    () =>
      compileVisualState(
        primaryTable as string,
        selectedColumns as Record<string, VisualColumnSelect>,
        orderedProjectionKeys,
        joins as VisualJoin[],
        filters as VisualFilter[],
        sorts as VisualSort[],
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
      normalizedSchema,
      dialect,
      filterJoin,
      customOperators,
      vectorSearch,
      hybridSearch,
      ctes,
      windowFunctions,
      semanticModels,
    ],
  );

  const currentSql = isRawMode ? rawSql : compiled.sql;
  const safety = useMemo(() => validateSqlSafety(currentSql), [currentSql]);
  const isDirty = computeSnapshot(store) !== store.cleanSnapshot;

  const actions = useMemo<QueryBuilderActions<Schema>>(() => {
    const setField =
      <K extends keyof BuilderStore<Schema>>(key: K) =>
      (update: SetStateAction<BuilderStore<Schema>[K]>) =>
        setStore((prev) => ({ ...prev, [key]: resolveUpdate(update, prev[key]) }));
    const update = (fn: (prev: BuilderStore<Schema>) => BuilderStore<Schema>) => setStore(fn);

    const loadSpec = (spec: SerializedQuerySpec | QuerySpec<Schema>) => {
      const patch = specToBuilderPatch<Schema>(narrowSerializedSpec(spec));
      update((prev) => ({ ...applyBuilderSpecPatch(prev, patch), isRawMode: false }));
    };

    return {
      setPrimaryTable: setField("primaryTable"),
      addTable: (table) => update((prev) => addTableToState(prev, table)),
      removeTable: (table) => update((prev) => removeTableFromState(prev, table)),
      toggleColumn: (table, col) => update((prev) => toggleColumnOnState(prev, table, col as string)),
      updateColumnSelect: (key, updates) => update((prev) => updateColumnSelectOnState(prev, key, updates)),
      removeColumnProjection: (key) => update((prev) => removeColumnProjectionFromState(prev, key)),
      setJoins: setField("joins"),
      addJoin: (join) => update((prev) => ({ ...prev, joins: appendItem(prev.joins, join) })),
      autoJoinTable: (target) => {
        if (!target) return;
        update((prev) => autoJoinOnState(prev, target, schemaRef.current));
      },
      updateJoin: (id, updates) => update((prev) => ({ ...prev, joins: updateItemById(prev.joins, id, updates) })),
      removeJoin: (id) => update((prev) => ({ ...prev, joins: removeItemById(prev.joins, id) })),
      setFilters: setField("filters"),
      addFilter: (filter) => update((prev) => ({ ...prev, filters: appendItem(prev.filters, filter) })),
      updateFilter: (id, updates) =>
        update((prev) => ({ ...prev, filters: updateItemById(prev.filters, id, updates) })),
      removeFilter: (id) => update((prev) => ({ ...prev, filters: removeItemById(prev.filters, id) })),
      setSorts: setField("sorts"),
      addSort: (sort) => update((prev) => ({ ...prev, sorts: appendItem(prev.sorts, sort) })),
      updateSort: (id, updates) => update((prev) => ({ ...prev, sorts: updateItemById(prev.sorts, id, updates) })),
      removeSort: (id) => update((prev) => ({ ...prev, sorts: removeItemById(prev.sorts, id) })),
      setIsDistinct: setField("isDistinct"),
      setLimit: setField("limit"),
      setDialect: setField("dialect"),
      setRawSql: setField("rawSql"),
      setIsRawMode: setField("isRawMode"),
      loadTemplate: (template) => {
        if (template.spec && typeof template.spec === "object" && Object.keys(template.spec).length > 0) {
          loadSpec(template.spec);
        } else if (template.sql) {
          update((prev) => ({ ...prev, rawSql: template.sql, isRawMode: true }));
        }
      },
      loadSpec,
      reset: () => {
        // The clean snapshot must describe the values just restored, not the mount-time ones.
        const restored = initRef.current;
        update(() => ({ ...restored, cleanSnapshot: computeSnapshot(restored) }));
      },
      markClean: () => update((prev) => ({ ...prev, cleanSnapshot: computeSnapshot(prev) })),
      setVectorSearch: setField("vectorSearch"),
      setHybridSearch: setField("hybridSearch"),
      setCtes: setField("ctes"),
      setWindowFunctions: setField("windowFunctions"),
      setSemanticModels: setField("semanticModels"),
      setFilterJoin: setField("filterJoin"),
    };
  }, []);

  return {
    state: {
      primaryTable,
      activeTableNames,
      activeTables,
      selectedColumns,
      orderedProjectionKeys,
      joins,
      filters,
      sorts,
      isDistinct,
      limit,
      dialect,
      rawSql,
      isRawMode,
      isDirty,
      vectorSearch,
      hybridSearch,
      ctes,
      windowFunctions,
      semanticModels,
      filterJoin,
    },
    compiled,
    currentSql,
    safety,
    actions,
  };
}

