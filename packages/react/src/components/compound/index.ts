import { QueryBuilderRoot } from "./QueryBuilderRoot";
import { QueryBuilderCanvas } from "./QueryBuilderCanvas";
import { QueryBuilderColumns } from "./QueryBuilderColumns";
import { QueryBuilderFilters } from "./QueryBuilderFilters";
import { QueryBuilderJoins } from "./QueryBuilderJoins";
import { QueryBuilderSorts } from "./QueryBuilderSorts";
import { QueryBuilderResults } from "./QueryBuilderResults";
import { QueryBuilderSqlEditor } from "./QueryBuilderSqlEditor";

export {
  QueryBuilderRoot,
  QueryBuilderCanvas,
  QueryBuilderColumns,
  QueryBuilderFilters,
  QueryBuilderJoins,
  QueryBuilderSorts,
  QueryBuilderResults,
  QueryBuilderSqlEditor,
};

export {
  QueryBuilderCompoundContext,
  useCompoundQueryBuilder,
  type CompoundQueryBuilderContextValue,
} from "./QueryBuilderContext";

export type { QueryBuilderRootProps } from "./QueryBuilderRoot";
export type { QueryBuilderCanvasProps } from "./QueryBuilderCanvas";
export type { QueryBuilderColumnsProps } from "./QueryBuilderColumns";
export type { QueryBuilderFiltersProps } from "./QueryBuilderFilters";
export type { QueryBuilderJoinsProps } from "./QueryBuilderJoins";
export type { QueryBuilderSortsProps } from "./QueryBuilderSorts";
export type { QueryBuilderResultsProps } from "./QueryBuilderResults";
export type { QueryBuilderSqlEditorProps } from "./QueryBuilderSqlEditor";

/**
 * Composable Compound Components namespace for QueryBuilder.
 *
 * Usage:
 * ```tsx
 * <QueryBuilder.Root value={spec} onChange={setSpec} schema={schema}>
 *   <div className="grid grid-cols-2 gap-4">
 *     <QueryBuilder.Canvas />
 *     <QueryBuilder.Columns />
 *     <QueryBuilder.Filters />
 *     <QueryBuilder.Joins />
 *     <QueryBuilder.Sorts />
 *     <QueryBuilder.SqlEditor />
 *     <QueryBuilder.Results />
 *   </div>
 * </QueryBuilder.Root>
 * ```
 */
export const QueryBuilder = Object.assign(QueryBuilderRoot, {
  Root: QueryBuilderRoot,
  Canvas: QueryBuilderCanvas,
  Columns: QueryBuilderColumns,
  Filters: QueryBuilderFilters,
  Joins: QueryBuilderJoins,
  Sorts: QueryBuilderSorts,
  Results: QueryBuilderResults,
  SqlEditor: QueryBuilderSqlEditor,
});
