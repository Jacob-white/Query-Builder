import React, {
  useState,
  useEffect,
  useMemo,
  useCallback,
  useRef,
  forwardRef,
  useImperativeHandle,
} from "react";
import type {
  DatabaseSchemaDefinition,
  QuerySpec,
  SchemaSnapshot,
  TableMeta,
  SqlDialect,
  QueryResultData,
  QueryBuilderClassNames,
  CustomFilterOperator,
  CustomFieldRenderer,
  TableSchema,
  VisualQueryBuilderRef,
  ExecuteQueryHandler,
} from "../../types";
import type { QueryBuilderClient } from "../../client";
import type { CellRenderer } from "../../theme/QueryBuilderProvider";
import {
  useQueryState,
  createInitialState,
  type QueryStateActions,
} from "../../hooks/useQueryState";
import { compileVisualState } from "../../utils/compiler";
import { normalizeSchema, validateSchema } from "../../utils/schemaUtils";
import { parseSqlToSpec } from "../../utils/sqlParser";
import { cx } from "../../utils/classNames";
import { fastCanonicalSpec } from "../VisualQueryBuilder";
import { useTheme } from "../../theme/ThemeProvider";
import { darkTheme, lightTheme, themeToCssVariables, type QueryBuilderTheme } from "../../theme/tokens";
import {
  QueryBuilderCompoundContext,
  type CompoundQueryBuilderContextValue,
} from "./QueryBuilderContext";

export interface QueryBuilderRootProps<Schema extends DatabaseSchemaDefinition = DatabaseSchemaDefinition> {
  /** Controlled query specification AST */
  value?: QuerySpec<Schema>;
  /** Callback fired whenever the query specification or SQL changes */
  onChange?: (spec: QuerySpec<Schema> | null, sql: string) => void;
  /** Initial query specification for uncontrolled usage */
  initialSpec?: QuerySpec<Schema>;
  /** Initial primary table name */
  initialTable?: string;
  /** Relational database schema snapshot or table schema list */
  schema?: SchemaSnapshot | Schema | TableSchema[] | null;
  /** Official typed API client instance (auto-fetches schema and executes queries) */
  client?: QueryBuilderClient;
  /** SQL dialect target (postgres, mysql, sqlite, duckdb, snowflake, bigquery) */
  dialect?: SqlDialect;
  /** Color theme token override */
  theme?: "dark" | "light" | "auto" | QueryBuilderTheme;
  /** Disable default inline styling to style 100% via Tailwind utility classes */
  unstyled?: boolean;
  /** CSS class name applied to the root element */
  className?: string;
  /** Granular slot class names mapping for Tailwind utility styling */
  classNames?: QueryBuilderClassNames;
  /** Custom filter operator definitions */
  customOperators?: Record<string, CustomFilterOperator>;
  /** Custom field header or label renderers */
  fieldRenderers?: Record<string, CustomFieldRenderer>;
  /** Custom result table cell renderers */
  cellRenderers?: Record<string, CellRenderer>;
  /** Callback to execute SQL or QuerySpec against backend */
  onExecuteQuery?: ExecuteQueryHandler;
  /** Compound component children */
  children?: React.ReactNode;
}

export const QueryBuilderRoot = forwardRef<VisualQueryBuilderRef, QueryBuilderRootProps>(
  function QueryBuilderRoot(
    {
      value,
      onChange,
      initialSpec,
      initialTable,
      schema: propSchema,
      client,
      dialect = "postgres",
      theme: propTheme,
      unstyled = false,
      className,
      classNames,
      customOperators,
      fieldRenderers,
      cellRenderers,
      onExecuteQuery: propExecuteQuery,
      children,
    },
    ref,
  ) {
    const { theme: contextTheme } = useTheme();

    const activeTheme: QueryBuilderTheme = useMemo(() => {
      if (propTheme && typeof propTheme === "object" && "colors" in propTheme) {
        return propTheme as QueryBuilderTheme;
      }
      if (propTheme === "light") return lightTheme;
      if (propTheme === "dark") return darkTheme;
      return contextTheme;
    }, [propTheme, contextTheme]);

    const cssVars = useMemo(
      () => (unstyled ? {} : themeToCssVariables(activeTheme)),
      [activeTheme, unstyled],
    );

    // Auto-wire schema from client if client is provided without schema
    const [clientSchema, setClientSchema] = useState<SchemaSnapshot | null>(null);

    const effectiveSchema = propSchema || clientSchema;
    const normalizedSchema = useMemo(() => normalizeSchema(effectiveSchema), [effectiveSchema]);

    // Central state engine
    const initialQuery = useMemo(() => {
      if (value) return value;
      if (initialSpec) return initialSpec;
      const defaultT =
        initialTable ||
        (propSchema && "tables" in propSchema && propSchema.tables
          ? Object.keys(propSchema.tables)[0]
          : undefined);
      if (defaultT) {
        return { table: defaultT, activeTables: [defaultT] };
      }
      return undefined;
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const { state, actions, history, spec } = useQueryState(initialQuery);

    useEffect(() => {
      if (!propSchema && client && !clientSchema) {
        client
          .getSchema()
          .then((s) => {
            if (s) {
              setClientSchema(s);
              if (initialTable && state.activeTables.length === 0 && s.tables?.[initialTable]) {
                actions.addTable(initialTable);
              }
            }
          })
          .catch((err) => {
            console.warn("[QueryBuilder.Root] Failed to auto-fetch schema from client:", err);
          });
      }
    }, [propSchema, client, clientSchema, initialTable, state.activeTables.length, actions]);

    // Schema diagnostics in development
    useEffect(() => {
      if (normalizedSchema) {
        const result = validateSchema(normalizedSchema);
        if (!result.valid || result.warnings.length > 0) {
          if (
            typeof globalThis !== "undefined" &&
            (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.NODE_ENV !== "production"
          ) {
            result.errors.forEach((e) => {
              console.warn(`[QueryBuilder Schema Error] ${e.code}: ${e.message}`, e.suggestion);
            });
            result.warnings.forEach((w) => {
              console.warn(`[QueryBuilder Schema Warning] ${w.code}: ${w.message}`, w.suggestion);
            });
          }
        }
      }
    }, [normalizedSchema]);

    // Raw SQL editing & bidirectional sync
    const [rawSql, setRawSqlState] = useState<string>("");
    const [isRawMode, setIsRawMode] = useState<boolean>(false);

    // Synchronize controlled `value` prop into useQueryState
    const initialCanonical = useMemo(
      () => (value ? fastCanonicalSpec(createInitialState(value)) : ""),
      [],
    );
    const lastControlledValueRef = useRef<string>(initialCanonical);
    const lastReportedSpecRef = useRef<string>(initialCanonical);
    const isFirstRenderRef = useRef<boolean>(true);

    useEffect(() => {
      if (value !== undefined) {
        const canonical = fastCanonicalSpec(createInitialState(value));
        if (canonical !== lastControlledValueRef.current) {
          lastControlledValueRef.current = canonical;
          lastReportedSpecRef.current = canonical;
          setIsRawMode(false);
          actions.loadSpec(value);
        }
      }
    }, [value, actions]);

    // Compiled SQL
    const compiled = useMemo(() => {
      return compileVisualState(
        state.primaryTable,
        state.selectedColumns,
        state.orderedProjectionKeys,
        state.joins,
        state.filters,
        state.sorts,
        state.isDistinct,
        state.limit,
        normalizedSchema,
        dialect,
        "AND",
        customOperators,
        state.vectorSearch,
        state.hybridSearch,
        state.ctes,
        state.windowFunctions,
      );
    }, [state, normalizedSchema, dialect, customOperators]);

    // Update raw SQL when compiled SQL changes and not in raw mode
    useEffect(() => {
      if (!isRawMode) {
        setRawSqlState(compiled.sql);
      }
    }, [compiled.sql, isRawMode]);

    const currentSql = isRawMode ? rawSql : compiled.sql;
    const lastReportedSqlRef = useRef<string>(currentSql);

    // Propagate state changes to `onChange` callback
    useEffect(() => {
      const canonicalActive = fastCanonicalSpec(createInitialState(spec));

      if (isFirstRenderRef.current) {
        isFirstRenderRef.current = false;
        lastReportedSpecRef.current = canonicalActive;
        lastControlledValueRef.current = canonicalActive;
        lastReportedSqlRef.current = currentSql;
        return;
      }

      if (
        canonicalActive !== lastReportedSpecRef.current ||
        currentSql !== lastReportedSqlRef.current
      ) {
        lastReportedSpecRef.current = canonicalActive;
        lastControlledValueRef.current = canonicalActive;
        lastReportedSqlRef.current = currentSql;
        if (onChange) {
          onChange(spec, currentSql);
        }
      }
    }, [spec, currentSql, onChange]);

    const setRawSql = useCallback(
      (newSql: string) => {
        setRawSqlState(newSql);
        setIsRawMode(true);

        // Attempt continuous bidirectional sync if valid SQL
        const parsedSpec = parseSqlToSpec(newSql, normalizedSchema);
        if (parsedSpec && parsedSpec.table) {
          actions.loadSpec(parsedSpec as QuerySpec);
        }
      },
      [normalizedSchema, actions],
    );

    const syncSqlToCanvas = useCallback(() => {
      const parsedSpec = parseSqlToSpec(rawSql, normalizedSchema);
      if (parsedSpec && parsedSpec.table) {
        actions.loadSpec(parsedSpec as QuerySpec);
        setRawSqlState(compiled.sql);
        setIsRawMode(false);
      }
    }, [rawSql, normalizedSchema, actions, compiled.sql]);

    // Action wrappers that ensure visual interactions reset isRawMode back to false
    const wrappedActions = useMemo<QueryStateActions>(() => {
      const wrap = <A extends unknown[], R>(fn: (...args: A) => R): ((...args: A) => R) => {
        return ((...args: A) => {
          setIsRawMode(false);
          return fn(...args);
        });
      };

      return {
        ...actions,
        toggleColumn: wrap(actions.toggleColumn),
        setOrderedProjectionKeys: wrap(actions.setOrderedProjectionKeys),
        updateColumnSelect: wrap(actions.updateColumnSelect),
        removeColumnProjection: wrap(actions.removeColumnProjection),
        addTable: wrap(actions.addTable),
        removeTable: wrap(actions.removeTable),
        autoJoinTable: wrap(actions.autoJoinTable),
        setJoins: wrap(actions.setJoins),
        setFilters: wrap(actions.setFilters),
        setSorts: wrap(actions.setSorts),
        setDistinct: wrap(actions.setDistinct),
        setLimit: wrap(actions.setLimit),
        setCtes: wrap(actions.setCtes),
        setWindowFunctions: wrap(actions.setWindowFunctions),
        setVectorSearch: wrap(actions.setVectorSearch),
        setHybridSearch: wrap(actions.setHybridSearch),
        reset: wrap(actions.reset),
      };
    }, [actions]);

    // Active table metadata with fallback for headless/dynamic schemas
    const activeTables: TableMeta[] = useMemo(() => {
      return state.activeTables.map((tableName) => {
        if (normalizedSchema?.tables?.[tableName]) {
          return normalizedSchema.tables[tableName];
        }
        return {
          name: tableName,
          columns: Object.keys(state.selectedColumns)
            .filter((k) => k.startsWith(`${tableName}.`))
            .map((k) => ({
              name: k.replace(`${tableName}.`, ""),
              data_type: "text",
              is_nullable: true,
              is_primary: false,
            })),
        };
      });
    }, [normalizedSchema, state.activeTables, state.selectedColumns]);

    // Query Execution state
    const [queryResults, setQueryResults] = useState<QueryResultData | null>(null);
    const [isRunning, setIsRunning] = useState<boolean>(false);
    const [error, setError] = useState<Error | string | null>(null);

    const effectiveOnExecuteQuery =
      propExecuteQuery ??
      (client
        ? async (sql: string, s?: QuerySpec | null) => {
            return client.execute(s ? s : { sql });
          }
        : undefined);

    const executeQuery = useCallback(
      async (
        overrideSql?: string,
        overrideSpec?: QuerySpec | null,
      ): Promise<QueryResultData | void> => {
        const targetSql = overrideSql ?? (isRawMode ? rawSql : compiled.sql);
        const targetSpec = overrideSpec ?? (isRawMode ? undefined : (spec as QuerySpec));

        if (!effectiveOnExecuteQuery) {
          console.warn(
            "[QueryBuilder.Root] executeQuery called but neither `client` nor `onExecuteQuery` prop is provided.",
          );
          return;
        }

        setIsRunning(true);
        setError(null);
        try {
          const res = await effectiveOnExecuteQuery(targetSql, targetSpec);
          if (res) {
            setQueryResults(res);
            return res;
          }
        } catch (err) {
          setError(err as Error);
          throw err;
        } finally {
          setIsRunning(false);
        }
      },
      [effectiveOnExecuteQuery, isRawMode, rawSql, compiled.sql, spec],
    );

    // Track latest state for imperative handle to prevent stale closures
    const latestSpecRef = useRef<QuerySpec>(spec);
    latestSpecRef.current = spec;

    const latestSqlRef = useRef<string>(currentSql);
    latestSqlRef.current = currentSql;

    const latestHistoryRef = useRef(history);
    latestHistoryRef.current = history;

    const latestActionsRef = useRef(actions);
    latestActionsRef.current = actions;

    const latestExecuteQueryRef = useRef(executeQuery);
    latestExecuteQueryRef.current = executeQuery;

    // Expose imperative handle via forwardRef
    useImperativeHandle(
      ref,
      () => ({
        getSpec: () => latestSpecRef.current,
        getSql: () => latestSqlRef.current,
        setSpec: (newSpec: QuerySpec) => {
          setIsRawMode(false);
          latestActionsRef.current.loadSpec(newSpec);
        },
        reset: () => {
          setIsRawMode(false);
          latestActionsRef.current.reset();
        },
        execute: () => latestExecuteQueryRef.current(),
        undo: () => {
          setIsRawMode(false);
          latestActionsRef.current.undo();
        },
        redo: () => {
          setIsRawMode(false);
          latestActionsRef.current.redo();
        },
        canUndo: () => latestHistoryRef.current.canUndo,
        canRedo: () => latestHistoryRef.current.canRedo,
      }),
      [],
    );

    const contextValue = useMemo<CompoundQueryBuilderContextValue>(
      () => ({
        state,
        actions: wrappedActions,
        history,
        spec,
        sql: currentSql,
        rawSql,
        isRawMode,
        setRawSql,
        syncSqlToCanvas,
        schema: effectiveSchema as SchemaSnapshot | null,
        normalizedSchema,
        activeTables,
        primaryTable: state.primaryTable,
        selectedColumns: state.selectedColumns,
        orderedProjectionKeys: state.orderedProjectionKeys,
        joins: state.joins,
        filters: state.filters,
        sorts: state.sorts,
        isDistinct: state.isDistinct,
        limit: state.limit,
        dialect,
        queryResults,
        isRunning,
        error,
        executeQuery,
        setQueryResults,
        client,
        unstyled,
        className,
        classNames,
        customOperators,
        fieldRenderers,
        cellRenderers,
      }),
      [
        state,
        wrappedActions,
        history,
        spec,
        currentSql,
        rawSql,
        isRawMode,
        setRawSql,
        syncSqlToCanvas,
        effectiveSchema,
        normalizedSchema,
        activeTables,
        dialect,
        queryResults,
        isRunning,
        error,
        executeQuery,
        client,
        unstyled,
        className,
        classNames,
        customOperators,
        fieldRenderers,
        cellRenderers,
      ],
    );

    return (
      <QueryBuilderCompoundContext.Provider value={contextValue}>
        <div
          data-qb="root"
          data-qb-compound="root"
          className={cx(className, classNames?.root)}
          style={
            unstyled
              ? undefined
              : {
                  ...cssVars,
                  background: activeTheme.colors.background,
                  color: activeTheme.colors.text,
                  fontFamily: activeTheme.typography.fontFamily,
                  borderRadius: activeTheme.radii.lg,
                  border: `1px solid ${activeTheme.colors.border}`,
                  padding: "16px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "16px",
                }
          }
        >
          {children}
        </div>
      </QueryBuilderCompoundContext.Provider>
    );
  },
);
