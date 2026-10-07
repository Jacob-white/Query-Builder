import { createContext, useContext } from "react";
import type {
  QueryState,
  QueryStateActions,
  QueryHistory,
} from "../../hooks/useQueryState";
import type {
  QuerySpec,
  SchemaSnapshot,
  TableMeta,
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  SqlDialect,
  QueryResultData,
  QueryBuilderClassNames,
  CustomFilterOperator,
  CustomFieldRenderer,
} from "../../types";
import type { QueryBuilderClient } from "../../client";

export interface CompoundQueryBuilderContextValue {
  state: QueryState;
  actions: QueryStateActions;
  history: QueryHistory;
  spec: QuerySpec;
  sql: string;
  rawSql: string;
  isRawMode: boolean;
  setRawSql: (sql: string) => void;
  syncSqlToCanvas: () => void;
  schema: SchemaSnapshot | null;
  normalizedSchema: SchemaSnapshot | null;
  activeTables: TableMeta[];
  primaryTable: string;
  selectedColumns: Record<string, VisualColumnSelect>;
  orderedProjectionKeys: string[];
  joins: VisualJoin[];
  filters: VisualFilter[];
  sorts: VisualSort[];
  isDistinct: boolean;
  limit: number;
  dialect: SqlDialect;
  queryResults: QueryResultData | null;
  isRunning: boolean;
  error: Error | string | null;
  executeQuery: (sql?: string, spec?: Record<string, unknown>) => Promise<QueryResultData | void>;
  setQueryResults: (results: QueryResultData | null) => void;
  client?: QueryBuilderClient;
  unstyled: boolean;
  className?: string;
  classNames?: QueryBuilderClassNames;
  customOperators?: Record<string, CustomFilterOperator>;
  fieldRenderers?: Record<string, CustomFieldRenderer>;
  cellRenderers?: Record<string, (value: any, row: any, column: string) => React.ReactNode>;
}

export const QueryBuilderCompoundContext =
  createContext<CompoundQueryBuilderContextValue | null>(null);

/**
 * Hook to access the compound QueryBuilder state, actions, and compilation context.
 */
export function useCompoundQueryBuilder(): CompoundQueryBuilderContextValue {
  const ctx = useContext(QueryBuilderCompoundContext);
  if (!ctx) {
    throw new Error(
      "QueryBuilder compound components (<QueryBuilder.Canvas>, <QueryBuilder.Columns>, <QueryBuilder.Filters>, <QueryBuilder.Joins>, <QueryBuilder.Sorts>, <QueryBuilder.Results>, <QueryBuilder.SqlEditor>) must be used within a <QueryBuilder.Root> provider.",
    );
  }
  return ctx;
}
