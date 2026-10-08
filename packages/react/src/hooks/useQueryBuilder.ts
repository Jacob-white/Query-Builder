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
import { findJoinPath, findBestJoinCondition } from "../utils/joinUtils";

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
  customOperators?: Record<string, CustomFilterOperator>;
  vectorSearch?: VectorSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  ctes?: CteSpec[] | null;
  windowFunctions?: WindowFunctionSpec[] | null;
  semanticModels?: SemanticModel[] | null;
  filterJoin?: "AND" | "OR";
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
  vectorSearch?: VectorSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  ctes?: CteSpec[] | null;
  windowFunctions?: WindowFunctionSpec[] | null;
  semanticModels?: SemanticModel[] | null;
  filterJoin?: "AND" | "OR";
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
  loadSpec: (spec: Record<string, unknown> | QuerySpec<Schema>) => void;
  reset: () => void;
  markClean: () => void;
  setVectorSearch?: (vs: VectorSearchSpec | null) => void;
  setHybridSearch?: (hs: HybridSearchSpec | null) => void;
  setCtes?: (ctes: CteSpec[] | null) => void;
  setWindowFunctions?: (wfs: WindowFunctionSpec[] | null) => void;
  setSemanticModels?: (models: SemanticModel[] | null) => void;
  setFilterJoin?: (join: "AND" | "OR") => void;
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
  const initVectorSearch =
    options.vectorSearch ||
    (options.initialSpec as any)?.vector_search ||
    (options.initialSpec as any)?.vectorSearch ||
    null;
  const initHybridSearch =
    options.hybridSearch ||
    (options.initialSpec as any)?.hybrid_search ||
    (options.initialSpec as any)?.hybridSearch ||
    null;
  const initCtes =
    options.ctes ||
    (options.initialSpec as any)?.ctes ||
    null;
  const initWindowFunctions =
    options.windowFunctions ||
    (options.initialSpec as any)?.window_functions ||
    (options.initialSpec as any)?.windowFunctions ||
    null;
  const initSemanticModels =
    options.semanticModels ||
    (options.initialSpec as any)?.semantic_models ||
    (options.initialSpec as any)?.semanticModels ||
    null;
  const initFilterJoin =
    options.filterJoin ||
    (options.initialSpec as any)?.filter_join ||
    (options.initialSpec as any)?.filterJoin ||
    "AND";

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
  const [vectorSearch, setVectorSearch] = useState<VectorSearchSpec | null>(initVectorSearch);
  const [hybridSearch, setHybridSearch] = useState<HybridSearchSpec | null>(initHybridSearch);
  const [ctes, setCtes] = useState<CteSpec[] | null>(initCtes);
  const [windowFunctions, setWindowFunctions] = useState<WindowFunctionSpec[] | null>(initWindowFunctions);
  const [semanticModels, setSemanticModels] = useState<SemanticModel[] | null>(initSemanticModels);
  const [filterJoin, setFilterJoin] = useState<"AND" | "OR">(initFilterJoin);

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
      filterJoin,
      options.customOperators,
      vectorSearch,
      hybridSearch,
      ctes,
      windowFunctions,
      semanticModels,
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
    filterJoin,
    options.customOperators,
    vectorSearch,
    hybridSearch,
    ctes,
    windowFunctions,
    semanticModels,
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
    setVectorSearch(initVectorSearch);
    setHybridSearch(initHybridSearch);
    setCtes(initCtes);
    setWindowFunctions(initWindowFunctions);
    setSemanticModels(initSemanticModels);
    setFilterJoin(initFilterJoin);
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
    initVectorSearch,
    initHybridSearch,
    initCtes,
    initWindowFunctions,
    initSemanticModels,
    initFilterJoin,
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

  const autoJoinTable = useCallback(
    (targetTable: SchemaTableNames<Schema> | string) => {
      if (!targetTable) return;
      const currentActive =
        activeTableNames.length > 0
          ? activeTableNames
          : primaryTable
            ? [primaryTable]
            : [];
      const pathJoins = findJoinPath(
        currentActive as string[],
        targetTable as string,
        normalizedSchema,
      );
      if (pathJoins.length > 0) {
        setJoins((prev) => [...prev, ...(pathJoins as VisualJoin<Schema>[])]);
        setActiveTableNames((prev) => {
          const s = new Set(prev as string[]);
          for (const pj of pathJoins) {
            if (pj.table) s.add(pj.table);
            if (pj.left_table) s.add(pj.left_table);
          }
          s.add(targetTable as string);
          return Array.from(s) as SchemaTableNames<Schema>[];
        });
      } else {
        const base = (primaryTable || currentActive[0] || "table") as string;
        const cond = findBestJoinCondition(base, targetTable as string, normalizedSchema);
        const fallbackJoin: VisualJoin<Schema> = {
          id: `join-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
          type: "LEFT JOIN",
          left_table: cond.leftTable as SchemaTableNames<Schema>,
          left_col: cond.leftCol,
          table: cond.rightTable as SchemaTableNames<Schema>,
          right_col: cond.rightCol,
        };
        setJoins((prev) => [...prev, fallbackJoin]);
        setActiveTableNames((prev) =>
          Array.from(new Set([...(prev as string[]), cond.rightTable])) as SchemaTableNames<Schema>[],
        );
      }
    },
    [activeTableNames, primaryTable, normalizedSchema],
  );

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
    const pTable = (s.table || s.primaryTable || "") as SchemaTableNames<Schema>;
    if (pTable) {
      setPrimaryTable(pTable);
      setActiveTableNames((prev) =>
        prev.includes(pTable as any) ? prev : [...prev, pTable],
      );
    }

    if (Array.isArray(s.activeTables)) {
      setActiveTableNames(s.activeTables as SchemaTableNames<Schema>[]);
    } else if (pTable) {
      setActiveTableNames([pTable]);
    }

    if (s.selectedColumns && typeof s.selectedColumns === "object") {
      setSelectedColumns(s.selectedColumns as Record<string, VisualColumnSelect<Schema>>);
      if (Array.isArray(s.orderedProjectionKeys)) {
        setOrderedProjectionKeys(s.orderedProjectionKeys as string[]);
      }
    } else if (Array.isArray(s.columns)) {
      const newSelected: Record<string, VisualColumnSelect<Schema>> = {};
      const newKeys: string[] = [];
      s.columns.forEach((colItem: any) => {
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
          newSelected[key] = {
            table: tbl as any,
            name: col,
          };
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
            table: tbl as any,
            name: col,
            aggregate: colItem.agg ? colItem.agg.toUpperCase() : undefined,
            alias: colItem.alias,
          };
          newKeys.push(key);
        }
      });
      setSelectedColumns(newSelected);
      setOrderedProjectionKeys(newKeys);
    }

    if (Array.isArray(s.joins)) {
      const mappedJoins: VisualJoin<Schema>[] = s.joins.map((j: any, idx: number) => {
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
          table: j.table,
          type: fullType as any,
          left_table: leftTbl,
          left_col: leftC || "id",
          right_col: rightC || "id",
        };
      });
      setJoins(mappedJoins);
      setActiveTableNames((prev) => {
        const joinTables = mappedJoins.map((j) => j.table);
        return Array.from(new Set([...prev, ...joinTables])) as SchemaTableNames<Schema>[];
      });
    }
    if (Array.isArray(s.filters)) {
      const mappedFilters: VisualFilter<Schema>[] = s.filters.map((f: any, idx: number) => {
        let op = f.operator || f.op || "=";
        op = op.toUpperCase().replace(/_/g, " ");
        return {
          id: f.id || `filter_${idx + 1}`,
          tablePrefix: (f.tablePrefix || f.table || pTable) as SchemaTableNames<Schema>,
          column: f.column || "",
          operator: op as any,
          value: f.value ?? "",
          combiner: f.combiner || "AND",
        };
      });
      setFilters(mappedFilters);
    }
    if (Array.isArray(s.sorts)) {
      setSorts(s.sorts as VisualSort<Schema>[]);
    } else if (Array.isArray(s.order_by)) {
      const mappedSorts: VisualSort<Schema>[] = s.order_by.map(
        (ord: any, idx: number) => {
          let col = ord.column || "";
          let prefix = ord.tablePrefix;
          if (!prefix && col.includes(".")) {
            const lastDot = col.lastIndexOf(".");
            prefix = col.substring(0, lastDot);
            col = col.substring(lastDot + 1);
          }
          return {
            id: `sort_${idx + 1}`,
            tablePrefix: prefix || pTable,
            column: col,
            direction: ord.direction || "ASC",
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
    if ("vector_search" in s || "vectorSearch" in s) {
      setVectorSearch(s.vector_search || s.vectorSearch || null);
    }
    if ("hybrid_search" in s || "hybridSearch" in s) {
      setHybridSearch(s.hybrid_search || s.hybridSearch || null);
    }
    if ("ctes" in s) {
      setCtes(s.ctes || null);
    }
    if ("window_functions" in s || "windowFunctions" in s) {
      setWindowFunctions(s.window_functions || s.windowFunctions || null);
    }
    if ("semantic_models" in s || "semanticModels" in s) {
      setSemanticModels(s.semantic_models || s.semanticModels || null);
    }
    if ("filter_join" in s || "filterJoin" in s) {
      setFilterJoin(s.filter_join || s.filterJoin || "AND");
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
    actions: {
      setPrimaryTable,
      addTable,
      removeTable,
      toggleColumn,
      updateColumnSelect,
      removeColumnProjection,
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
      setIsDistinct,
      setLimit,
      setDialect,
      setRawSql,
      setIsRawMode,
      loadTemplate,
      loadSpec,
      reset,
      markClean,
      setVectorSearch,
      setHybridSearch,
      setCtes,
      setWindowFunctions,
      setSemanticModels,
      setFilterJoin,
    },
  };
}
