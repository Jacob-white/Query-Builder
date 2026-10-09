/**
 * Pure query-state transitions shared by `useQueryBuilder` and `useQueryState`.
 *
 * Both hooks keep their own storage strategy (a flat state object for the builder, a history stack
 * for the headless hook) but every state change goes through the functions in this module, so the
 * table / column / join / filter / sort / auto-join rules live in exactly one place. Spec
 * conversion (`specToState`, `stateToSpec`, `specToBuilderPatch`) lives here too.
 *
 * Everything here is free of React and of side effects, which keeps it directly unit-testable.
 */
import type {
  DatabaseSchemaDefinition,
  LooseQuerySpec,
  QuerySpec,
  SchemaSnapshot,
  SchemaTableNames,
  SemanticModel,
  SerializedQuerySpec,
  SqlDialect,
  TimeGrain,
  VectorSearchSpec,
  HybridSearchSpec,
  CteSpec,
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  WindowFunctionSpec,
} from "../types";
import { normalizeCombiner, resolveFilterCombiners } from "./filterCombiners";
import { findBestJoinCondition, findJoinPath } from "./joinUtils";

// ---------------------------------------------------------------------------
// Core state shape shared by both hooks
// ---------------------------------------------------------------------------

/** The slice of query state that both hooks manipulate with identical rules. */
export interface QueryCoreState<Schema = DatabaseSchemaDefinition> {
  primaryTable: SchemaTableNames<Schema>;
  /** Names of the tables taking part in the query (the builder exposes this as `activeTableNames`). */
  activeTables: SchemaTableNames<Schema>[];
  selectedColumns: Record<string, VisualColumnSelect<Schema>>;
  orderedProjectionKeys: string[];
  joins: VisualJoin<Schema>[];
  filters: VisualFilter<Schema>[];
  sorts: VisualSort<Schema>[];
}

export function emptyTable<Schema>(): SchemaTableNames<Schema> {
  return "" as SchemaTableNames<Schema>;
}

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/**
 * Adds a table to the active list (no duplicates) and adopts it as primary when none is set.
 * The primary fallback applies even when the table was already active.
 */
export function addTableToState<Schema, S extends QueryCoreState<Schema>>(
  state: S,
  table: SchemaTableNames<Schema>,
): S {
  return {
    ...state,
    activeTables: state.activeTables.includes(table) ? state.activeTables : [...state.activeTables, table],
    primaryTable: state.primaryTable || table,
  };
}

export function setPrimaryTableOnState<Schema, S extends QueryCoreState<Schema>>(
  state: S,
  table: SchemaTableNames<Schema>,
): S {
  return {
    ...state,
    primaryTable: table,
    activeTables: state.activeTables.includes(table) ? state.activeTables : [...state.activeTables, table],
  };
}

export function setTablesOnState<Schema, S extends QueryCoreState<Schema>>(
  state: S,
  tables: SchemaTableNames<Schema>[],
): S {
  return {
    ...state,
    activeTables: tables,
    primaryTable: tables.includes(state.primaryTable) ? state.primaryTable : tables[0] || emptyTable<Schema>(),
  };
}

/** Removes a table together with every join, column and projection key that referenced it. */
export function removeTableFromState<Schema, S extends QueryCoreState<Schema>>(
  state: S,
  table: SchemaTableNames<Schema>,
): S {
  const activeTables = state.activeTables.filter((t) => t !== table);
  const selectedColumns: Record<string, VisualColumnSelect<Schema>> = {};
  for (const [key, col] of Object.entries(state.selectedColumns)) {
    if (col.table !== table) selectedColumns[key] = col;
  }
  return {
    ...state,
    activeTables,
    primaryTable: state.primaryTable === table ? activeTables[0] || emptyTable<Schema>() : state.primaryTable,
    joins: state.joins.filter((j) => j.table !== table && j.left_table !== table),
    selectedColumns,
    orderedProjectionKeys: state.orderedProjectionKeys.filter((k) => !k.startsWith(`${table}.`)),
  };
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

export function toggleColumnOnState<Schema, S extends QueryCoreState<Schema>>(
  state: S,
  table: SchemaTableNames<Schema>,
  column: string,
): S {
  const key = `${table}.${column}`;
  const selectedColumns = { ...state.selectedColumns };
  if (selectedColumns[key]) {
    delete selectedColumns[key];
    return {
      ...state,
      selectedColumns,
      orderedProjectionKeys: state.orderedProjectionKeys.filter((k) => k !== key),
    };
  }
  selectedColumns[key] = { table, name: column };
  return {
    ...state,
    selectedColumns,
    orderedProjectionKeys: state.orderedProjectionKeys.includes(key)
      ? state.orderedProjectionKeys
      : [...state.orderedProjectionKeys, key],
  };
}

export function updateColumnSelectOnState<Schema, S extends QueryCoreState<Schema>>(
  state: S,
  key: string,
  updates: Partial<VisualColumnSelect<Schema>>,
): S {
  const existing = state.selectedColumns[key];
  if (!existing) return state;
  return { ...state, selectedColumns: { ...state.selectedColumns, [key]: { ...existing, ...updates } } };
}

export function removeColumnProjectionFromState<Schema, S extends QueryCoreState<Schema>>(
  state: S,
  key: string,
): S {
  const selectedColumns = { ...state.selectedColumns };
  delete selectedColumns[key];
  return {
    ...state,
    selectedColumns,
    orderedProjectionKeys: state.orderedProjectionKeys.filter((k) => k !== key),
  };
}

// ---------------------------------------------------------------------------
// Id-keyed lists (joins, filters, sorts)
// ---------------------------------------------------------------------------

export function appendItem<T>(list: readonly T[], item: T): T[] {
  return [...list, item];
}

export function updateItemById<T extends { id: string }>(list: readonly T[], id: string, updates: Partial<T>): T[] {
  return list.map((item) => (item.id === id ? { ...item, ...updates } : item));
}

export function removeItemById<T extends { id: string }>(list: readonly T[], id: string): T[] {
  return list.filter((item) => item.id !== id);
}

// ---------------------------------------------------------------------------
// Auto-join
// ---------------------------------------------------------------------------

/**
 * Joins `targetTable` into the query: follows the FK path from the active tables when one exists,
 * otherwise falls back to the best single-hop condition. No-ops for an empty target.
 */
export function autoJoinOnState<Schema, S extends QueryCoreState<Schema>>(
  state: S,
  targetTable: SchemaTableNames<Schema> | string,
  schema?: SchemaSnapshot | null,
): S {
  if (!targetTable) return state;
  const active: SchemaTableNames<Schema>[] =
    state.activeTables.length > 0 ? state.activeTables : state.primaryTable ? [state.primaryTable] : [];
  const pathJoins = findJoinPath(active as string[], targetTable as string, schema);

  if (pathJoins.length > 0) {
    const names = new Set(state.activeTables as string[]);
    for (const pj of pathJoins) {
      if (pj.table) names.add(pj.table);
      if (pj.left_table) names.add(pj.left_table);
    }
    names.add(targetTable as string);
    return {
      ...state,
      joins: [...state.joins, ...(pathJoins as VisualJoin<Schema>[])],
      activeTables: Array.from(names) as SchemaTableNames<Schema>[],
    };
  }

  const base = (state.primaryTable || active[0] || "table") as string;
  const cond = findBestJoinCondition(base, targetTable as string, schema);
  const fallbackJoin: VisualJoin<Schema> = {
    id: `join-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
    type: "LEFT JOIN",
    left_table: cond.leftTable as SchemaTableNames<Schema>,
    left_col: cond.leftCol,
    table: cond.rightTable as SchemaTableNames<Schema>,
    right_col: cond.rightCol,
  };
  const names = new Set(state.activeTables as string[]);
  names.add(cond.rightTable);
  return {
    ...state,
    joins: [...state.joins, fallbackJoin],
    activeTables: Array.from(names) as SchemaTableNames<Schema>[],
  };
}

// ---------------------------------------------------------------------------
// Spec <-> state conversion
// ---------------------------------------------------------------------------

/** Subset of a hook state that `stateToSpec` reads. */
export interface SpecSourceState<Schema = DatabaseSchemaDefinition> {
  primaryTable: SchemaTableNames<Schema>;
  selectedColumns: Record<string, VisualColumnSelect<Schema>>;
  orderedProjectionKeys: string[];
  joins: VisualJoin<Schema>[];
  filters: VisualFilter<Schema>[];
  sorts: VisualSort<Schema>[];
  isDistinct: boolean;
  limit: number;
  offset?: number;
  vectorSearch?: VectorSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  ctes?: CteSpec[] | null;
  windowFunctions?: WindowFunctionSpec[] | null;
}

/** Converts internal query state to a serializable QuerySpec. */
export function stateToSpec<Schema = DatabaseSchemaDefinition>(state: SpecSourceState<Schema>): QuerySpec<Schema> {
  const columns: (string | { column: string; agg?: string; alias?: string })[] = [];
  const keys =
    state.orderedProjectionKeys.length > 0 ? state.orderedProjectionKeys : Object.keys(state.selectedColumns);

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

  if (state.offset !== undefined && state.offset !== 0) spec.offset = state.offset;
  if (state.vectorSearch) spec.vector_search = state.vectorSearch;
  if (state.hybridSearch) spec.hybrid_search = state.hybridSearch;
  if (state.ctes && state.ctes.length > 0) spec.ctes = state.ctes;
  if (state.windowFunctions && state.windowFunctions.length > 0) spec.window_functions = state.windowFunctions;

  return spec;
}

/** Partial hook state produced by `specToState` (the headless hook's flavour of spec loading). */
export interface SpecStatePartial<Schema = DatabaseSchemaDefinition> {
  primaryTable?: SchemaTableNames<Schema>;
  activeTables?: SchemaTableNames<Schema>[];
  selectedColumns?: Record<string, VisualColumnSelect<Schema>>;
  orderedProjectionKeys?: string[];
  joins?: VisualJoin<Schema>[];
  filters?: VisualFilter<Schema>[];
  sorts?: VisualSort<Schema>[];
  isDistinct?: boolean;
  limit?: number;
  offset?: number;
  dialect?: SqlDialect;
  vectorSearch?: VectorSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  ctes?: CteSpec[];
  windowFunctions?: WindowFunctionSpec[];
}

/** Everything the spec converters accept: a serialized spec, a typed spec, or a state-shaped object. */
export type SpecInput<Schema = DatabaseSchemaDefinition> =
  | SerializedQuerySpec
  | Partial<QuerySpec<Schema>>
  | SpecStatePartial<Schema>;

/**
 * Converts a serialized spec (snake_case QuerySpec, camelCase state shape or saved preset) into a
 * partial headless-hook state. Keys absent from the input stay absent.
 */
export function specToState<Schema = DatabaseSchemaDefinition>(
  input: SpecInput<Schema>,
): SpecStatePartial<Schema> {
  const partial: SpecStatePartial<Schema> = {};
  const s = narrowSerializedSpec(input);

  const primary = s.table || s.primaryTable || "";
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
      ? s.orderedProjectionKeys
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
          rightCol = rparts.length > 1 ? rparts.slice(1).join(".") : rparts[0];
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
        operator: (f.operator || f.op || "=").toUpperCase() === "RAW" ? "RAW" : f.operator || f.op || "=",
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

  if (typeof s.limit === "number") partial.limit = s.limit;
  if (typeof s.offset === "number") partial.offset = s.offset;
  if (typeof s.dialect === "string") partial.dialect = s.dialect as SqlDialect;

  const vector = s.vector_search || s.vectorSearch;
  if (vector) partial.vectorSearch = vector;
  const hybrid = s.hybrid_search || s.hybridSearch;
  if (hybrid) partial.hybridSearch = hybrid;

  if (Array.isArray(s.ctes)) partial.ctes = s.ctes;

  if (Array.isArray(s.window_functions) || Array.isArray(s.windowFunctions)) {
    partial.windowFunctions = (s.window_functions || s.windowFunctions) as WindowFunctionSpec[];
  }

  return partial;
}

/** Result of converting a spec into builder state; absent keys mean "leave as is". */
export interface BuilderSpecPatch<Schema = DatabaseSchemaDefinition> {
  primaryTable?: SchemaTableNames<Schema>;
  /** Computes the next active-table list from the previous one (joined tables are unioned in). */
  activeTables?: (prev: SchemaTableNames<Schema>[]) => SchemaTableNames<Schema>[];
  selectedColumns?: Record<string, VisualColumnSelect<Schema>>;
  orderedProjectionKeys?: string[];
  joins?: VisualJoin<Schema>[];
  filters?: VisualFilter<Schema>[];
  sorts?: VisualSort<Schema>[];
  isDistinct?: boolean;
  limit?: number;
  vectorSearch?: VectorSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  ctes?: CteSpec[] | null;
  windowFunctions?: WindowFunctionSpec[] | null;
  semanticModels?: SemanticModel[] | null;
  filterJoin?: "AND" | "OR";
}

/**
 * Pure conversion used by the builder for both `loadSpec` and a spec-shaped `initialSpec`, so the
 * two always produce the same builder state (and SQL).
 */
export function specToBuilderPatch<Schema = DatabaseSchemaDefinition>(
  input: SpecInput<Schema>,
): BuilderSpecPatch<Schema> {
  const s = narrowSerializedSpec(input);
  const patch: BuilderSpecPatch<Schema> = {};
  const pTable = (s.table || s.primaryTable || "") as SchemaTableNames<Schema>;
  let baseActive: SchemaTableNames<Schema>[] | undefined;
  if (pTable) patch.primaryTable = pTable;
  if (Array.isArray(s.activeTables)) {
    baseActive = s.activeTables as SchemaTableNames<Schema>[];
  } else if (pTable) {
    baseActive = [pTable];
  }
  let joinTables: SchemaTableNames<Schema>[] = [];
  const activeUpdater = (prev: SchemaTableNames<Schema>[]) =>
    Array.from(new Set([...(baseActive ?? prev), ...joinTables]));
  if (baseActive) patch.activeTables = activeUpdater;

  if (s.selectedColumns && typeof s.selectedColumns === "object") {
    patch.selectedColumns = s.selectedColumns as Record<string, VisualColumnSelect<Schema>>;
    if (Array.isArray(s.orderedProjectionKeys)) {
      patch.orderedProjectionKeys = s.orderedProjectionKeys;
    }
  } else if (Array.isArray(s.columns)) {
    const newSelected: Record<string, VisualColumnSelect<Schema>> = {};
    const newKeys: string[] = [];
    s.columns.forEach((colItem) => {
      if (!colItem || colItem === "*") return;
      if (typeof colItem === "string") {
        let tbl = pTable as string;
        let col = colItem;
        if (colItem.includes(".")) {
          const lastDot = colItem.lastIndexOf(".");
          tbl = colItem.substring(0, lastDot);
          col = colItem.substring(lastDot + 1);
        }
        const key = `${tbl}.${col}`;
        newSelected[key] = { table: tbl as SchemaTableNames<Schema>, name: col };
        newKeys.push(key);
      } else if (typeof colItem === "object" && colItem.column) {
        let tbl = pTable as string;
        let col = colItem.column;
        if (col.includes(".")) {
          const lastDot = col.lastIndexOf(".");
          tbl = col.substring(0, lastDot);
          col = col.substring(lastDot + 1);
        }
        const key = `${tbl}.${col}`;
        newSelected[key] = {
          table: tbl as SchemaTableNames<Schema>,
          name: col,
          aggregate: colItem.agg ? (colItem.agg.toUpperCase() as VisualColumnSelect<Schema>["aggregate"]) : undefined,
          alias: colItem.alias,
        };
        newKeys.push(key);
      }
    });
    patch.selectedColumns = newSelected;
    patch.orderedProjectionKeys = newKeys;
  }

  if (Array.isArray(s.joins)) {
    const mappedJoins: VisualJoin<Schema>[] = s.joins.map((j, idx): VisualJoin<Schema> => {
      const jType = (j.type || "LEFT").toUpperCase();
      const fullType = jType.endsWith(" JOIN") ? jType : `${jType} JOIN`;
      let leftTbl = j.left_table;
      let leftC = j.left_col;
      if (!leftC && j.on?.[0]?.left) {
        const lStr = j.on[0].left;
        if (lStr.includes(".")) {
          const lastDot = lStr.lastIndexOf(".");
          if (!leftTbl) leftTbl = lStr.substring(0, lastDot);
          leftC = lStr.substring(lastDot + 1);
        } else {
          leftC = lStr;
        }
      }
      let rightC = j.right_col;
      if (!rightC && j.on?.[0]?.right) {
        const rStr = j.on[0].right;
        rightC = rStr.includes(".") ? rStr.substring(rStr.lastIndexOf(".") + 1) : rStr;
      }
      return {
        id: j.id || `join_${idx + 1}`,
        table: j.table as SchemaTableNames<Schema>,
        type: fullType as VisualJoin<Schema>["type"],
        left_table: leftTbl as SchemaTableNames<Schema> | undefined,
        left_col: leftC || "id",
        right_col: rightC || "id",
      };
    });
    patch.joins = mappedJoins;
    joinTables = mappedJoins.map((j) => j.table);
    patch.activeTables = activeUpdater;
  }

  // Spec-level `filter_join` is the default combiner for filters without their own.
  const specFilterJoin = normalizeCombiner(s.filter_join ?? s.filterJoin);
  if (Array.isArray(s.filters)) {
    patch.filters = s.filters.map((f, idx): VisualFilter<Schema> => {
      const op = (f.operator || f.op || "=").toUpperCase().replace(/_/g, " ");
      return {
        id: f.id || `filter_${idx + 1}`,
        tablePrefix: (f.tablePrefix || f.table || pTable) as SchemaTableNames<Schema>,
        column: f.column || "",
        operator: op,
        value: f.value ?? "",
        combiner: normalizeCombiner(f.combiner, specFilterJoin),
      };
    });
  }

  if (Array.isArray(s.sorts)) {
    patch.sorts = s.sorts as VisualSort<Schema>[];
  } else if (Array.isArray(s.order_by)) {
    patch.sorts = s.order_by.map((ord, idx): VisualSort<Schema> => {
      let col = ord.column || "";
      let prefix = ord.tablePrefix;
      if (!prefix && col.includes(".")) {
        const lastDot = col.lastIndexOf(".");
        prefix = col.substring(0, lastDot);
        col = col.substring(lastDot + 1);
      }
      return {
        id: `sort_${idx + 1}`,
        tablePrefix: (prefix || pTable) as SchemaTableNames<Schema>,
        column: col,
        direction: ord.direction || "ASC",
      };
    });
  }
  if (typeof s.isDistinct === "boolean") {
    patch.isDistinct = s.isDistinct;
  } else if (typeof s.distinct === "boolean") {
    patch.isDistinct = s.distinct;
  }
  if (typeof s.limit === "number") patch.limit = s.limit;
  if ("vector_search" in s || "vectorSearch" in s) patch.vectorSearch = s.vector_search || s.vectorSearch || null;
  if ("hybrid_search" in s || "hybridSearch" in s) patch.hybridSearch = s.hybrid_search || s.hybridSearch || null;
  if ("ctes" in s) patch.ctes = s.ctes || null;
  if ("window_functions" in s || "windowFunctions" in s) {
    patch.windowFunctions = s.window_functions || s.windowFunctions || null;
  }
  if ("semantic_models" in s || "semanticModels" in s) {
    patch.semanticModels = s.semantic_models || s.semanticModels || null;
  }
  if ("filter_join" in s || "filterJoin" in s) {
    patch.filterJoin = specFilterJoin;
  } else if (Array.isArray(s.filters)) {
    // A spec that carries filters but no join is all-AND; do not keep a stale OR from a prior load.
    patch.filterJoin = "AND";
  }
  return patch;
}

/** The builder-state fields a {@link BuilderSpecPatch} can overwrite. */
export interface BuilderPatchTarget<Schema = DatabaseSchemaDefinition> extends QueryCoreState<Schema> {
  isDistinct: boolean;
  limit: number;
  vectorSearch: VectorSearchSpec | null;
  hybridSearch: HybridSearchSpec | null;
  ctes: CteSpec[] | null;
  windowFunctions: WindowFunctionSpec[] | null;
  semanticModels: SemanticModel[] | null;
  filterJoin: "AND" | "OR";
}

/** Applies a spec patch to builder state; keys the patch does not carry are left untouched. */
export function applyBuilderSpecPatch<Schema, S extends BuilderPatchTarget<Schema>>(
  state: S,
  patch: BuilderSpecPatch<Schema>,
): S {
  const next: S = { ...state };
  if (patch.primaryTable !== undefined) next.primaryTable = patch.primaryTable;
  if (patch.activeTables) next.activeTables = patch.activeTables(state.activeTables);
  if (patch.selectedColumns) next.selectedColumns = patch.selectedColumns;
  if (patch.orderedProjectionKeys) next.orderedProjectionKeys = patch.orderedProjectionKeys;
  if (patch.joins) next.joins = patch.joins;
  if (patch.filters) next.filters = patch.filters;
  if (patch.sorts) next.sorts = patch.sorts;
  if (patch.isDistinct !== undefined) next.isDistinct = patch.isDistinct;
  if (patch.limit !== undefined) next.limit = patch.limit;
  if (patch.vectorSearch !== undefined) next.vectorSearch = patch.vectorSearch;
  if (patch.hybridSearch !== undefined) next.hybridSearch = patch.hybridSearch;
  if (patch.ctes !== undefined) next.ctes = patch.ctes;
  if (patch.windowFunctions !== undefined) next.windowFunctions = patch.windowFunctions;
  if (patch.semanticModels !== undefined) next.semanticModels = patch.semanticModels;
  if (patch.filterJoin !== undefined) next.filterJoin = patch.filterJoin;
  return next;
}

/**
 * True when a builder `initialSpec` is a serialized QuerySpec (snake_case, `op`, `order_by`, ...)
 * rather than the hook's own state shape; such specs must go through `specToBuilderPatch`.
 */
export function isSpecShaped(input: SerializedQuerySpec): boolean {
  const s = input;
  if (s.selectedColumns || s.orderedProjectionKeys || s.activeTables || s.sorts || s.primaryTable) {
    return false;
  }
  return (
    Array.isArray(s.columns) ||
    Array.isArray(s.order_by) ||
    "filter_join" in s ||
    (Array.isArray(s.filters) && s.filters.some((f) => f && "op" in f)) ||
    (Array.isArray(s.joins) &&
      s.joins.some((j) => j && (Boolean(j.on) || (j.type !== undefined && !/JOIN$/i.test(j.type)))))
  );
}

// ---------------------------------------------------------------------------
// Boundary validation
// ---------------------------------------------------------------------------

const ARRAY_KEYS = ["activeTables", "orderedProjectionKeys", "columns", "joins", "filters", "sorts", "order_by"] as const;
/** Lists that an explicit `null` legitimately clears (key presence is meaningful to the builder). */
const NULLABLE_ARRAY_KEYS = ["ctes", "window_functions", "windowFunctions", "semantic_models", "semanticModels"] as const;
const STRING_KEYS = ["table", "primaryTable", "dialect"] as const;
const NUMBER_KEYS = ["limit", "offset"] as const;
const BOOLEAN_KEYS = ["distinct", "isDistinct"] as const;
const OBJECT_KEYS = ["selectedColumns", "vector_search", "vectorSearch", "hybrid_search", "hybridSearch"] as const;

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Narrows untrusted input (a saved preset, parsed JSON, a prop from plain JS) to a
 * `SerializedQuerySpec`: anything that is not a plain object becomes `{}`, and every known key
 * whose value has the wrong top-level type (for example `limit: "5"` or `joins: {}`) is dropped,
 * so the converters only ever see well-typed top-level fields. Unknown keys are preserved.
 */
export function narrowSerializedSpec(input: unknown): SerializedQuerySpec {
  if (!isPlainRecord(input)) return {};
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) {
    if ((ARRAY_KEYS as readonly string[]).includes(key)) {
      if (Array.isArray(value)) out[key] = value;
    } else if ((NULLABLE_ARRAY_KEYS as readonly string[]).includes(key)) {
      if (value === null || Array.isArray(value)) out[key] = value;
    } else if ((STRING_KEYS as readonly string[]).includes(key)) {
      if (typeof value === "string") out[key] = value;
    } else if ((NUMBER_KEYS as readonly string[]).includes(key)) {
      if (typeof value === "number") out[key] = value;
    } else if ((BOOLEAN_KEYS as readonly string[]).includes(key)) {
      if (typeof value === "boolean") out[key] = value;
    } else if ((OBJECT_KEYS as readonly string[]).includes(key)) {
      if (value === null || typeof value === "object") out[key] = value;
    } else {
      out[key] = value;
    }
  }
  return out as LooseQuerySpec;
}
