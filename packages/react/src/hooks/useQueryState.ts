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
} from "../types";
import { findJoinPath, findBestJoinCondition } from "../utils/joinUtils";

export interface QueryState<Schema = any> {
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
}

export interface QueryHistory<Schema = any> {
  past: QueryState<Schema>[];
  future: QueryState<Schema>[];
  canUndo: boolean;
  canRedo: boolean;
}

export interface QueryStateActions<Schema = any> {
  setTables: (tables: SchemaTableNames<Schema>[]) => void;
  setPrimaryTable: (table: SchemaTableNames<Schema>) => void;
  addTable: (table: SchemaTableNames<Schema>) => void;
  removeTable: (table: SchemaTableNames<Schema>) => void;
  toggleColumn: (
    table: SchemaTableNames<Schema>,
    col: SchemaColumnNames<Schema, any> | string,
  ) => void;
  updateColumnSelect: (key: string, updates: Partial<VisualColumnSelect<Schema>>) => void;
  removeColumnProjection: (key: string) => void;
  addJoin: (join: VisualJoin<Schema>) => void;
  autoJoinTable: (
    targetTable: SchemaTableNames<Schema> | string,
    schema?: SchemaSnapshot | null,
  ) => void;
  updateJoin: (id: string, updates: Partial<VisualJoin<Schema>>) => void;
  removeJoin: (id: string) => void;
  addFilter: (filter: VisualFilter<Schema>) => void;
  updateFilter: (id: string, updates: Partial<VisualFilter<Schema>>) => void;
  removeFilter: (id: string) => void;
  addSort: (sort: VisualSort<Schema>) => void;
  updateSort: (id: string, updates: Partial<VisualSort<Schema>>) => void;
  removeSort: (id: string) => void;
  setLimit: (limit: number) => void;
  setOffset: (offset: number) => void;
  setDistinct: (distinct: boolean) => void;
  setDialect: (dialect: SqlDialect) => void;
  loadSpec: (spec: QuerySpec<Schema> | Record<string, unknown>) => void;
  reset: () => void;
  markClean: () => void;
  undo: () => void;
  redo: () => void;
  clearHistory: () => void;
}

export interface UseQueryStateReturn<Schema = any> {
  state: QueryState<Schema>;
  actions: QueryStateActions<Schema>;
  history: QueryHistory<Schema>;
  spec: QuerySpec<Schema>;
}

export const MAX_HISTORY_LENGTH = 50;

/**
 * Converts internal QueryState to a serializable QuerySpec.
 */
export function stateToSpec<Schema = any>(state: QueryState<Schema>): QuerySpec<Schema> {
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

  const filters = (state.filters || []).map((f) => ({
    column: f.column,
    op: f.operator,
    value: f.value,
    tablePrefix: f.tablePrefix,
  }));

  const order_by = (state.sorts || []).map((s) => ({
    column: s.tablePrefix ? `${s.tablePrefix}.${s.column}` : s.column,
    direction: s.direction,
  }));

  return {
    table: state.primaryTable,
    columns,
    joins,
    filters,
    filter_join: "AND",
    order_by,
    distinct: state.isDistinct,
    limit: state.limit,
  };
}

/**
 * Converts a QuerySpec or raw spec object to a partial QueryState.
 */
export function specToState<Schema = any>(
  spec: Partial<QuerySpec<Schema>> | Partial<QueryState<Schema>> | Record<string, any>,
): Partial<QueryState<Schema>> {
  const partial: Partial<QueryState<Schema>> = {};
  const s = spec as any;

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
          aggregate: (c.agg as any) || undefined,
          alias: c.alias,
          timeGrain: c.time_grain || c.timeGrain,
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
    partial.joins = s.joins.map((j: any, idx: number) => {
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
        type: j.type || "LEFT JOIN",
        left_table: leftTable,
        table: j.table,
        left_col: leftCol,
        right_col: rightCol,
      };
    });
  }

  if (Array.isArray(s.filters)) {
    partial.filters = s.filters.map((f: any, idx: number) => {
      let col = f.column || "";
      let prefix = f.tablePrefix;
      if (!prefix && col.includes(".")) {
        const parts = col.split(".");
        prefix = parts[0];
        col = parts.slice(1).join(".");
      }
      return {
        id: f.id || `filter_${idx + 1}`,
        combiner: f.combiner || "AND",
        tablePrefix: prefix,
        column: col,
        operator: (f.operator || f.op || "=").toUpperCase() === "RAW" ? "RAW" : (f.operator || f.op || "="),
        value: f.value ?? "",
        rawExpression: f.raw_expression || f.rawExpression,
      };
    });
  }

  if (Array.isArray(s.order_by)) {
    partial.sorts = s.order_by.map((sortItem: any, idx: number) => {
      let col = sortItem.column || "";
      let prefix = sortItem.tablePrefix;
      if (!prefix && col.includes(".")) {
        const parts = col.split(".");
        prefix = parts[0];
        col = parts.slice(1).join(".");
      }
      return {
        id: sortItem.id || `sort_${idx + 1}`,
        tablePrefix: prefix,
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
    partial.dialect = s.dialect;
  }

  return partial;
}

function createInitialState<Schema>(
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
    isDirty: false,
  };
}

/**
 * Headless state management hook for Query-Builder.
 */
export function useQueryState<Schema extends DatabaseSchemaDefinition = any>(
  initialSpecOrState?: QuerySpec<Schema> | Partial<QueryState<Schema>> | Record<string, unknown>,
): UseQueryStateReturn<Schema> {
  const initialRef = useRef<QueryState<Schema>>(createInitialState<Schema>(initialSpecOrState));
  const [state, setState] = useState<QueryState<Schema>>(initialRef.current);

  const [past, setPast] = useState<QueryState<Schema>[]>([]);
  const [future, setFuture] = useState<QueryState<Schema>[]>([]);

  const applyUpdate = useCallback((updater: (prev: QueryState<Schema>) => QueryState<Schema>) => {
    setState((prev) => {
      const next = updater(prev);
      setPast((p) => {
        const nextPast = [...p, prev];
        return nextPast.length > MAX_HISTORY_LENGTH
          ? nextPast.slice(nextPast.length - MAX_HISTORY_LENGTH)
          : nextPast;
      });
      setFuture([]);
      return { ...next, isDirty: true };
    });
  }, []);

  const setTables = useCallback((tables: SchemaTableNames<Schema>[]) => {
    applyUpdate((prev) => ({
      ...prev,
      activeTables: tables,
      primaryTable: tables.includes(prev.primaryTable) ? prev.primaryTable : tables[0] || ("" as any),
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
        prev.primaryTable === table ? (nextActive[0] || ("" as any)) : prev.primaryTable;
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
    (table: SchemaTableNames<Schema>, col: SchemaColumnNames<Schema, any> | string) => {
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

  const loadSpec = useCallback(
    (spec: QuerySpec<Schema> | Record<string, unknown>) => {
      const parsed = specToState<Schema>(spec);
      applyUpdate((prev) => ({
        ...prev,
        ...parsed,
        primaryTable: (parsed.primaryTable || prev.primaryTable) as SchemaTableNames<Schema>,
        activeTables: (parsed.activeTables ||
          (parsed.primaryTable ? [parsed.primaryTable] : prev.activeTables)) as SchemaTableNames<Schema>[],
        selectedColumns: parsed.selectedColumns || prev.selectedColumns,
        orderedProjectionKeys: parsed.orderedProjectionKeys || prev.orderedProjectionKeys,
        joins: parsed.joins || prev.joins,
        filters: parsed.filters || prev.filters,
        sorts: parsed.sorts || prev.sorts,
        isDistinct: parsed.isDistinct ?? prev.isDistinct,
        limit: typeof parsed.limit === "number" ? parsed.limit : prev.limit,
        offset: typeof parsed.offset === "number" ? parsed.offset : prev.offset,
        dialect: parsed.dialect || prev.dialect,
      }));
    },
    [applyUpdate],
  );

  const undo = useCallback(() => {
    setPast((p) => {
      if (p.length === 0) return p;
      const previous = p[p.length - 1];
      const remaining = p.slice(0, p.length - 1);
      setFuture((f) => [state, ...f]);
      setState(previous);
      return remaining;
    });
  }, [state]);

  const redo = useCallback(() => {
    setFuture((f) => {
      if (f.length === 0) return f;
      const next = f[0];
      const remaining = f.slice(1);
      setPast((p) => [...p, state]);
      setState(next);
      return remaining;
    });
  }, [state]);

  const clearHistory = useCallback(() => {
    setPast([]);
    setFuture([]);
  }, []);

  const reset = useCallback(() => {
    setState(initialRef.current);
    setPast([]);
    setFuture([]);
  }, []);

  const markClean = useCallback(() => {
    setState((prev) => ({ ...prev, isDirty: false }));
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
      addJoin,
      autoJoinTable,
      updateJoin,
      removeJoin,
      addFilter,
      updateFilter,
      removeFilter,
      addSort,
      updateSort,
      removeSort,
      setLimit,
      setOffset,
      setDistinct,
      setDialect,
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
      addJoin,
      autoJoinTable,
      updateJoin,
      removeJoin,
      addFilter,
      updateFilter,
      removeFilter,
      addSort,
      updateSort,
      removeSort,
      setLimit,
      setOffset,
      setDistinct,
      setDialect,
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
