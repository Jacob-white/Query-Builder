import { useState, useMemo, useCallback } from "react";
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
} from "../types";
import { compileVisualState, type CompiledVisualQuery } from "../utils/compiler";
import { validateSqlSafety } from "../utils/safety";
import { normalizeSchema } from "../utils/schemaUtils";

export interface UseQueryBuilderOptions<Schema extends DatabaseSchemaDefinition = any> {
  schema?: SchemaSnapshot | Schema | null;
  initialTable?: SchemaTableNames<Schema>;
  dialect?: SqlDialect;
  initialLimit?: number;
  initialDistinct?: boolean;
  initialSql?: string;
  initialSpec?: Record<string, unknown> | QuerySpec<Schema>;
  initialSelectedColumns?: Record<string, VisualColumnSelect<Schema>>;
  initialOrderedProjectionKeys?: (SchemaColumnRefs<Schema> | string)[];
  initialJoins?: VisualJoin<Schema>[];
  initialFilters?: VisualFilter<Schema>[];
  initialSorts?: VisualSort<Schema>[];
  initialActiveTables?: SchemaTableNames<Schema>[];
}

export interface QueryBuilderState<Schema = any> {
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
}

export interface QueryBuilderActions<Schema = any> {
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
  loadSpec: (spec: Record<string, unknown> | QuerySpec<Schema>) => void;
  reset: () => void;
  markClean: () => void;
}

export interface UseQueryBuilderReturn<Schema = any> {
  state: QueryBuilderState<Schema>;
  compiled: CompiledVisualQuery;
  currentSql: string;
  safety: SqlSafetyValidation;
  actions: QueryBuilderActions<Schema>;
}

function computeSnapshot(data: {
  primaryTable: string;
  activeTableNames: string[];
  selectedColumns: Record<string, VisualColumnSelect>;
  orderedProjectionKeys: string[];
  joins: VisualJoin[];
  filters: VisualFilter[];
  sorts: VisualSort[];
  isDistinct: boolean;
  limit: number;
  dialect: SqlDialect;
  rawSql: string;
  isRawMode: boolean;
}): string {
  return JSON.stringify(data);
}

export function useQueryBuilder<Schema extends DatabaseSchemaDefinition = any>(
  options: UseQueryBuilderOptions<Schema> = {},
): UseQueryBuilderReturn<Schema> {
  const {
    schema,
    initialTable,
    dialect: optDialect,
    initialLimit,
    initialDistinct,
    initialSql,
    initialSpec,
    initialSelectedColumns,
    initialOrderedProjectionKeys,
    initialJoins,
    initialFilters,
    initialSorts,
    initialActiveTables,
  } = options;

  const normalizedSchema = useMemo(() => normalizeSchema(schema), [schema]);

  const defaultTable =
    initialTable ||
    ((initialSpec as any)?.primaryTable as SchemaTableNames<Schema>) ||
    ((initialSpec as any)?.table as SchemaTableNames<Schema>) ||
    (normalizedSchema?.tables
      ? (Object.keys(normalizedSchema.tables)[0] as SchemaTableNames<Schema>) || ("" as any)
      : ("" as any));

  const initPrimaryTable = defaultTable;
  const initActiveTableNames: SchemaTableNames<Schema>[] =
    initialActiveTables ||
    ((initialSpec as any)?.activeTables as SchemaTableNames<Schema>[]) ||
    (initPrimaryTable ? [initPrimaryTable] : []);
  const initSelectedColumns: Record<string, VisualColumnSelect<Schema>> =
    initialSelectedColumns ||
    ((initialSpec as any)?.selectedColumns as Record<string, VisualColumnSelect<Schema>>) ||
    {};
  const initOrderedProjectionKeys: string[] =
    (initialOrderedProjectionKeys as string[]) ||
    ((initialSpec as any)?.orderedProjectionKeys as string[]) ||
    [];
  const initJoins: VisualJoin<Schema>[] =
    initialJoins || ((initialSpec as any)?.joins as VisualJoin<Schema>[]) || [];
  const initFilters: VisualFilter<Schema>[] =
    initialFilters || ((initialSpec as any)?.filters as VisualFilter<Schema>[]) || [];
  const initSorts: VisualSort<Schema>[] =
    initialSorts || ((initialSpec as any)?.sorts as VisualSort<Schema>[]) || [];
  const initIsDistinct =
    typeof initialDistinct === "boolean"
      ? initialDistinct
      : Boolean((initialSpec as any)?.isDistinct ?? (initialSpec as any)?.distinct);
  const initLimit =
    typeof initialLimit === "number"
      ? initialLimit
      : typeof (initialSpec as any)?.limit === "number"
        ? ((initialSpec as any).limit as number)
        : 50;
  const initDialect = optDialect || "postgres";
  const initRawSql = initialSql || "";
  const initIsRawMode = Boolean(initialSql);

  const initialSnapshot = useMemo(
    () =>
      computeSnapshot({
        primaryTable: initPrimaryTable as string,
        activeTableNames: initActiveTableNames as string[],
        selectedColumns: initSelectedColumns as Record<string, VisualColumnSelect>,
        orderedProjectionKeys: initOrderedProjectionKeys,
        joins: initJoins as VisualJoin[],
        filters: initFilters as VisualFilter[],
        sorts: initSorts as VisualSort[],
        isDistinct: initIsDistinct,
        limit: initLimit,
        dialect: initDialect,
        rawSql: initRawSql,
        isRawMode: initIsRawMode,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const [primaryTable, setPrimaryTable] = useState<SchemaTableNames<Schema>>(initPrimaryTable);
  const [activeTableNames, setActiveTableNames] =
    useState<SchemaTableNames<Schema>[]>(initActiveTableNames);
  const [selectedColumns, setSelectedColumns] =
    useState<Record<string, VisualColumnSelect<Schema>>>(initSelectedColumns);
  const [orderedProjectionKeys, setOrderedProjectionKeys] = useState<string[]>(
    initOrderedProjectionKeys,
  );
  const [joins, setJoins] = useState<VisualJoin<Schema>[]>(initJoins);
  const [filters, setFilters] = useState<VisualFilter<Schema>[]>(initFilters);
  const [sorts, setSorts] = useState<VisualSort<Schema>[]>(initSorts);
  const [isDistinct, setIsDistinct] = useState<boolean>(initIsDistinct);
  const [limit, setLimit] = useState<number>(initLimit);
  const [dialect, setDialect] = useState<SqlDialect>(initDialect);
  const [rawSql, setRawSql] = useState<string>(initRawSql);
  const [isRawMode, setIsRawMode] = useState<boolean>(initIsRawMode);
  const [cleanSnapshot, setCleanSnapshot] = useState<string>(initialSnapshot);

  // Active table metadata
  const activeTables: TableMeta[] = useMemo(() => {
    return activeTableNames
      .map((name) => normalizedSchema?.tables?.[name as string])
      .filter((t): t is TableMeta => Boolean(t));
  }, [activeTableNames, normalizedSchema]);

  // Compiled visual query
  const compiled = useMemo(() => {
    return compileVisualState(
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
    );
  }, [
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
  ]);

  const currentSql = isRawMode ? rawSql : compiled.sql;
  const safety = useMemo(() => validateSqlSafety(currentSql), [currentSql]);

  const currentSnapshot = computeSnapshot({
    primaryTable: primaryTable as string,
    activeTableNames: activeTableNames as string[],
    selectedColumns: selectedColumns as Record<string, VisualColumnSelect>,
    orderedProjectionKeys,
    joins: joins as VisualJoin[],
    filters: filters as VisualFilter[],
    sorts: sorts as VisualSort[],
    isDistinct,
    limit,
    dialect,
    rawSql,
    isRawMode,
  });

  const isDirty = currentSnapshot !== cleanSnapshot;

  const markClean = useCallback(() => {
    setCleanSnapshot(currentSnapshot);
  }, [currentSnapshot]);

  const reset = useCallback(() => {
    setPrimaryTable(initPrimaryTable);
    setActiveTableNames(initActiveTableNames);
    setSelectedColumns(initSelectedColumns);
    setOrderedProjectionKeys(initOrderedProjectionKeys);
    setJoins(initJoins);
    setFilters(initFilters);
    setSorts(initSorts);
    setIsDistinct(initIsDistinct);
    setLimit(initLimit);
    setDialect(initDialect);
    setRawSql(initRawSql);
    setIsRawMode(initIsRawMode);
    setCleanSnapshot(initialSnapshot);
  }, [
    initPrimaryTable,
    initActiveTableNames,
    initSelectedColumns,
    initOrderedProjectionKeys,
    initJoins,
    initFilters,
    initSorts,
    initIsDistinct,
    initLimit,
    initDialect,
    initRawSql,
    initIsRawMode,
    initialSnapshot,
  ]);

  const addTable = useCallback((tableName: SchemaTableNames<Schema>) => {
    setActiveTableNames((prev) => {
      if (prev.includes(tableName)) return prev;
      return [...prev, tableName];
    });
    setPrimaryTable((prev) => (prev ? prev : tableName));
  }, []);

  const removeTable = useCallback((tableName: SchemaTableNames<Schema>) => {
    setActiveTableNames((prev) => {
      const remaining = prev.filter((t) => t !== tableName);
      setPrimaryTable((curPrimary) => {
        if (curPrimary === tableName) {
          return remaining[0] || ("" as any);
        }
        return curPrimary;
      });
      return remaining;
    });
    setJoins((prev) => prev.filter((j) => j.table !== tableName && j.left_table !== tableName));
    setSelectedColumns((prev) => {
      const next = { ...prev };
      Object.keys(next).forEach((k) => {
        if (next[k].table === tableName) delete next[k];
      });
      return next;
    });
    setOrderedProjectionKeys((prev) =>
      prev.filter((k) => !k.startsWith(`${tableName as string}.`)),
    );
  }, []);

  const toggleColumn = useCallback(
    <T extends SchemaTableNames<Schema>>(
      tableName: T,
      colName: SchemaColumnNames<Schema, T> | string,
    ) => {
      const key = `${tableName as string}.${colName as string}`;
      setSelectedColumns((prev) => {
        const next = { ...prev };
        if (next[key]) {
          delete next[key];
          setOrderedProjectionKeys((keys) => keys.filter((k) => k !== key));
        } else {
          next[key] = { table: tableName, name: colName };
          setOrderedProjectionKeys((keys) => [...keys, key]);
        }
        return next;
      });
    },
    [],
  );

  const updateColumnSelect = useCallback(
    (key: string, updates: Partial<VisualColumnSelect<Schema>>) => {
      setSelectedColumns((prev) => {
        if (!prev[key]) return prev;
        return {
          ...prev,
          [key]: { ...prev[key], ...updates },
        };
      });
    },
    [],
  );

  const removeColumnProjection = useCallback((key: string) => {
    setSelectedColumns((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setOrderedProjectionKeys((prev) => prev.filter((k) => k !== key));
  }, []);

  const addJoin = useCallback((join: VisualJoin<Schema>) => {
    setJoins((prev) => [...prev, join]);
  }, []);

  const updateJoin = useCallback((id: string, updates: Partial<VisualJoin<Schema>>) => {
    setJoins((prev) => prev.map((j) => (j.id === id ? { ...j, ...updates } : j)));
  }, []);

  const removeJoin = useCallback((id: string) => {
    setJoins((prev) => prev.filter((j) => j.id !== id));
  }, []);

  const addFilter = useCallback((filter: VisualFilter<Schema>) => {
    setFilters((prev) => [...prev, filter]);
  }, []);

  const updateFilter = useCallback((id: string, updates: Partial<VisualFilter<Schema>>) => {
    setFilters((prev) => prev.map((f) => (f.id === id ? { ...f, ...updates } : f)));
  }, []);

  const removeFilter = useCallback((id: string) => {
    setFilters((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const addSort = useCallback((sort: VisualSort<Schema>) => {
    setSorts((prev) => [...prev, sort]);
  }, []);

  const updateSort = useCallback((id: string, updates: Partial<VisualSort<Schema>>) => {
    setSorts((prev) => prev.map((s) => (s.id === id ? { ...s, ...updates } : s)));
  }, []);

  const removeSort = useCallback((id: string) => {
    setSorts((prev) => prev.filter((s) => s.id !== id));
  }, []);

  const loadSpec = useCallback((spec: Record<string, unknown> | QuerySpec<Schema>) => {
    const s = spec as any;
    if (typeof s.table === "string" && s.table) {
      setPrimaryTable(s.table as SchemaTableNames<Schema>);
      setActiveTableNames((prev) =>
        prev.includes(s.table as any) ? prev : [...prev, s.table as SchemaTableNames<Schema>],
      );
    } else if (typeof s.primaryTable === "string") {
      setPrimaryTable(s.primaryTable as SchemaTableNames<Schema>);
    }

    if (Array.isArray(s.activeTables)) {
      setActiveTableNames(s.activeTables as SchemaTableNames<Schema>[]);
    } else if (typeof s.primaryTable === "string") {
      setActiveTableNames([s.primaryTable as SchemaTableNames<Schema>]);
    }

    if (s.selectedColumns && typeof s.selectedColumns === "object") {
      setSelectedColumns(s.selectedColumns as Record<string, VisualColumnSelect<Schema>>);
    }
    if (Array.isArray(s.orderedProjectionKeys)) {
      setOrderedProjectionKeys(s.orderedProjectionKeys as string[]);
    }
    if (Array.isArray(s.joins)) {
      setJoins(s.joins as VisualJoin<Schema>[]);
    }
    if (Array.isArray(s.filters)) {
      setFilters(s.filters as VisualFilter<Schema>[]);
    }
    if (Array.isArray(s.sorts)) {
      setSorts(s.sorts as VisualSort<Schema>[]);
    } else if (Array.isArray(s.order_by)) {
      const mappedSorts: VisualSort<Schema>[] = s.order_by.map(
        (s: any, idx: number) => {
          let col = s.column || "";
          let prefix = s.tablePrefix;
          if (!prefix && col.includes(".")) {
            const parts = col.split(".");
            prefix = parts[0];
            col = parts.slice(1).join(".");
          }
          return {
            id: `sort_${idx + 1}`,
            tablePrefix: prefix,
            column: col,
            direction: s.direction || "ASC",
          };
        },
      );
      setSorts(mappedSorts);
    }
    if (typeof (spec as any).isDistinct === "boolean") {
      setIsDistinct((spec as any).isDistinct);
    } else if (typeof (spec as any).distinct === "boolean") {
      setIsDistinct((spec as any).distinct);
    }
    if (typeof spec.limit === "number") {
      setLimit(spec.limit);
    }
    setIsRawMode(false);
  }, []);

  const loadTemplate = useCallback(
    (template: QueryTemplate) => {
      if (
        template.spec &&
        typeof template.spec === "object" &&
        Object.keys(template.spec).length > 0
      ) {
        loadSpec(template.spec as Record<string, unknown>);
        setIsRawMode(false);
      } else if (template.sql) {
        setRawSql(template.sql);
        setIsRawMode(true);
      }
    },
    [loadSpec],
  );

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
    },
    compiled,
    currentSql,
    safety,
    actions: {
      setPrimaryTable,
      addTable,
      removeTable,
      toggleColumn,
      updateColumnSelect,
      removeColumnProjection,
      setJoins,
      addJoin,
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
      setIsDistinct,
      setLimit,
      setDialect,
      setRawSql,
      setIsRawMode,
      loadTemplate,
      loadSpec,
      reset,
      markClean,
    },
  };
}
