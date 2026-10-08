import { useState, useMemo, useCallback, useRef, useEffect } from "react";
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
  LooseQuerySpec,
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
import { findJoinPath, findBestJoinCondition } from "../utils/joinUtils";

export interface UseQueryBuilderOptions<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition> {
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

export interface UseQueryBuilderReturn<Schema = DatabaseSchemaDefinition> {
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

/** Result of converting a spec (or state-shaped object) into builder state; absent keys = leave as is. */
interface SpecPatch<Schema extends DatabaseSchemaDefinition> {
  primaryTable?: SchemaTableNames<Schema>;
  activeTableNames?: (prev: SchemaTableNames<Schema>[]) => SchemaTableNames<Schema>[];
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
 * Pure conversion shared by `loadSpec` and `initialSpec`, so a QuerySpec-shaped `initialSpec`
 * produces exactly the same builder state (and SQL) as `actions.loadSpec(sameSpec)`.
 */
function convertSpecToPatch<Schema extends DatabaseSchemaDefinition>(s: LooseQuerySpec): SpecPatch<Schema> {
  const patch: SpecPatch<Schema> = {};
  const pTable = (s.table || s.primaryTable || "") as SchemaTableNames<Schema>;
  let baseActive: SchemaTableNames<Schema>[] | undefined;
  if (pTable) patch.primaryTable = pTable;
  if (Array.isArray(s.activeTables)) {
    baseActive = s.activeTables as SchemaTableNames<Schema>[];
  } else if (pTable) {
    baseActive = [pTable];
  }
  let joinTables: SchemaTableNames<Schema>[] = [];
  // Mirrors the previous setState sequence: replace with the base list (if any), then union join tables.
  const activeUpdater = (prev: SchemaTableNames<Schema>[]) =>
    Array.from(new Set([...(baseActive ?? prev), ...joinTables]));
  if (baseActive) patch.activeTableNames = activeUpdater;

  if (s.selectedColumns && typeof s.selectedColumns === "object") {
    patch.selectedColumns = s.selectedColumns as Record<string, VisualColumnSelect<Schema>>;
    if (Array.isArray(s.orderedProjectionKeys)) {
      patch.orderedProjectionKeys = s.orderedProjectionKeys as string[];
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
        newSelected[key] = {
          table: tbl as SchemaTableNames<Schema>,
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
    patch.activeTableNames = activeUpdater;
  }

  // Spec-level `filter_join` is the default combiner for filters without their own.
  const specFilterJoin = normalizeCombiner(s.filter_join ?? s.filterJoin);
  if (Array.isArray(s.filters)) {
    patch.filters = s.filters.map((f, idx): VisualFilter<Schema> => {
      let op = f.operator || f.op || "=";
      op = op.toUpperCase().replace(/_/g, " ");
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
  if (typeof s.limit === "number") {
    patch.limit = s.limit;
  }
  if ("vector_search" in s || "vectorSearch" in s) {
    patch.vectorSearch = s.vector_search || s.vectorSearch || null;
  }
  if ("hybrid_search" in s || "hybridSearch" in s) {
    patch.hybridSearch = s.hybrid_search || s.hybridSearch || null;
  }
  if ("ctes" in s) {
    patch.ctes = s.ctes || null;
  }
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

/**
 * True when `initialSpec` is a serialized QuerySpec (snake_case, `op`, `order_by`, ...) rather than
 * the hook's own state shape; such specs must go through the same conversion as `loadSpec`.
 */
function isSpecShaped(s: LooseQuerySpec): boolean {
  if (
    s.selectedColumns ||
    s.orderedProjectionKeys ||
    s.activeTables ||
    s.sorts ||
    s.primaryTable
  ) {
    return false;
  }
  return (
    Array.isArray(s.columns) ||
    Array.isArray(s.order_by) ||
    "filter_join" in s ||
    (Array.isArray(s.filters) && s.filters.some((f) => f && "op" in f)) ||
    (Array.isArray(s.joins) && s.joins.some((j) => j && (Boolean(j.on) || (j.type !== undefined && !/JOIN$/i.test(j.type)))))
  );
}

export function useQueryBuilder<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition>(
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

  const looseInit = initialSpec as LooseQuerySpec | undefined;
  // A QuerySpec-shaped initialSpec is converted exactly like `actions.loadSpec` would.
  const specInit = useMemo(
    () => (looseInit && isSpecShaped(looseInit) ? convertSpecToPatch<Schema>(looseInit) : undefined),
    [looseInit],
  );

  const defaultTable =
    initialTable ||
    (looseInit?.primaryTable as SchemaTableNames<Schema>) ||
    (looseInit?.table as SchemaTableNames<Schema>) ||
    (normalizedSchema?.tables
      ? (Object.keys(normalizedSchema.tables)[0] as SchemaTableNames<Schema>) || ("" as SchemaTableNames<Schema>)
      : ("" as SchemaTableNames<Schema>));

  const initPrimaryTable = defaultTable;
  const initActiveTableNames: SchemaTableNames<Schema>[] =
    initialActiveTables ||
    (looseInit?.activeTables as SchemaTableNames<Schema>[]) ||
    specInit?.activeTableNames?.([]) ||
    (initPrimaryTable ? [initPrimaryTable] : []);
  const initSelectedColumns: Record<string, VisualColumnSelect<Schema>> =
    initialSelectedColumns ||
    (looseInit?.selectedColumns as Record<string, VisualColumnSelect<Schema>>) ||
    specInit?.selectedColumns ||
    {};
  const initOrderedProjectionKeys: string[] =
    (initialOrderedProjectionKeys as string[]) ||
    (looseInit?.orderedProjectionKeys as string[]) ||
    specInit?.orderedProjectionKeys ||
    [];
  const initJoins: VisualJoin<Schema>[] =
    initialJoins || specInit?.joins || (looseInit?.joins as VisualJoin<Schema>[]) || [];
  const initFilters: VisualFilter<Schema>[] =
    initialFilters || specInit?.filters || (looseInit?.filters as VisualFilter<Schema>[]) || [];
  const initSorts: VisualSort<Schema>[] =
    initialSorts || specInit?.sorts || (looseInit?.sorts as VisualSort<Schema>[]) || [];
  const initIsDistinct =
    typeof initialDistinct === "boolean"
      ? initialDistinct
      : Boolean(looseInit?.isDistinct ?? looseInit?.distinct);
  const initLimit =
    typeof initialLimit === "number"
      ? initialLimit
      : typeof looseInit?.limit === "number"
        ? looseInit.limit
        : 50;
  const initDialect = optDialect || "postgres";
  const initRawSql = initialSql || "";
  const initIsRawMode = Boolean(initialSql);
  const initVectorSearch =
    options.vectorSearch ||
    looseInit?.vector_search ||
    looseInit?.vectorSearch ||
    null;
  const initHybridSearch =
    options.hybridSearch ||
    looseInit?.hybrid_search ||
    looseInit?.hybridSearch ||
    null;
  const initCtes =
    options.ctes ||
    looseInit?.ctes ||
    null;
  const initWindowFunctions =
    options.windowFunctions ||
    looseInit?.window_functions ||
    looseInit?.windowFunctions ||
    null;
  const initSemanticModels =
    options.semanticModels ||
    looseInit?.semantic_models ||
    looseInit?.semanticModels ||
    null;
  const initFilterJoin = normalizeCombiner(
    options.filterJoin || looseInit?.filter_join || looseInit?.filterJoin,
  );

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

  // Latest initial values live in a ref so `reset` keeps a stable identity even when
  // callers pass inline arrays/objects (new references every render).
  const initRef = useRef({
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
  });
  // Written post-commit (not during render) so discarded concurrent renders can't leak in.
  useEffect(() => {
    initRef.current = {
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
    };
  });

  const reset = useCallback(() => {
    const init = initRef.current;
    setPrimaryTable(init.initPrimaryTable);
    setActiveTableNames(init.initActiveTableNames);
    setSelectedColumns(init.initSelectedColumns);
    setOrderedProjectionKeys(init.initOrderedProjectionKeys);
    setJoins(init.initJoins);
    setFilters(init.initFilters);
    setSorts(init.initSorts);
    setIsDistinct(init.initIsDistinct);
    setLimit(init.initLimit);
    setDialect(init.initDialect);
    setRawSql(init.initRawSql);
    setIsRawMode(init.initIsRawMode);
    setVectorSearch(init.initVectorSearch);
    setHybridSearch(init.initHybridSearch);
    setCtes(init.initCtes);
    setWindowFunctions(init.initWindowFunctions);
    setSemanticModels(init.initSemanticModels);
    setFilterJoin(init.initFilterJoin);
    // Clean snapshot must describe the values just restored, not the mount-time ones.
    setCleanSnapshot(
      computeSnapshot({
        primaryTable: init.initPrimaryTable as string,
        activeTableNames: init.initActiveTableNames as string[],
        selectedColumns: init.initSelectedColumns as Record<string, VisualColumnSelect>,
        orderedProjectionKeys: init.initOrderedProjectionKeys,
        joins: init.initJoins as VisualJoin[],
        filters: init.initFilters as VisualFilter[],
        sorts: init.initSorts as VisualSort[],
        isDistinct: init.initIsDistinct,
        limit: init.initLimit,
        dialect: init.initDialect,
        rawSql: init.initRawSql,
        isRawMode: init.initIsRawMode,
      }),
    );
  }, []);

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
          return remaining[0] || ("" as SchemaTableNames<Schema>);
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
    const patch = convertSpecToPatch<Schema>(spec as LooseQuerySpec);
    if (patch.primaryTable !== undefined) setPrimaryTable(patch.primaryTable);
    if (patch.activeTableNames) setActiveTableNames(patch.activeTableNames);
    if (patch.selectedColumns) setSelectedColumns(patch.selectedColumns);
    if (patch.orderedProjectionKeys) setOrderedProjectionKeys(patch.orderedProjectionKeys);
    if (patch.joins) setJoins(patch.joins);
    if (patch.filters) setFilters(patch.filters);
    if (patch.sorts) setSorts(patch.sorts);
    if (patch.isDistinct !== undefined) setIsDistinct(patch.isDistinct);
    if (patch.limit !== undefined) setLimit(patch.limit);
    if (patch.vectorSearch !== undefined) setVectorSearch(patch.vectorSearch);
    if (patch.hybridSearch !== undefined) setHybridSearch(patch.hybridSearch);
    if (patch.ctes !== undefined) setCtes(patch.ctes);
    if (patch.windowFunctions !== undefined) setWindowFunctions(patch.windowFunctions);
    if (patch.semanticModels !== undefined) setSemanticModels(patch.semanticModels);
    if (patch.filterJoin !== undefined) setFilterJoin(patch.filterJoin);
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
