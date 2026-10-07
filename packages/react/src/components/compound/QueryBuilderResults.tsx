import React from "react";
import type { QueryBuilderClassNames, QueryResultData } from "../../types";
import { useCompoundQueryBuilder } from "./QueryBuilderContext";
import { QueryResultsTable } from "../QueryResultsTable";
import { cx } from "../../utils/classNames";

export interface QueryBuilderResultsProps {
  /** Optional container class name */
  className?: string;
  /** Granular slot class names mapping */
  classNames?: QueryBuilderClassNames;
  /** Query results override (defaults to root context queryResults) */
  results?: QueryResultData | null;
  /** Loading state override (defaults to root context isRunning) */
  isLoading?: boolean;
  /** Execution error override (defaults to root context error) */
  error?: Error | string | null;
  /** Pagination page size */
  pageSize?: number;
  /** Unstyled mode flag */
  unstyled?: boolean;
}

export const QueryBuilderResults: React.FC<QueryBuilderResultsProps> = ({
  className,
  classNames: propClassNames,
  results: propResults,
  isLoading: propIsLoading,
  error: propError,
  pageSize,
  unstyled: propUnstyled,
}) => {
  const {
    queryResults,
    isRunning,
    error: rootError,
    cellRenderers,
    unstyled: rootUnstyled,
    classNames: rootClassNames,
  } = useCompoundQueryBuilder();

  const unstyled = propUnstyled ?? rootUnstyled;
  const classNames = propClassNames || rootClassNames;
  const effectiveResults = propResults !== undefined ? propResults : queryResults;
  const effectiveIsLoading = propIsLoading !== undefined ? propIsLoading : isRunning;
  const effectiveError = propError !== undefined ? propError : rootError;

  if (effectiveError && !effectiveIsLoading) {
    const errorMsg =
      typeof effectiveError === "string"
        ? effectiveError
        : effectiveError.message || String(effectiveError);
    return (
      <div
        data-qb="results-error"
        className={cx(className, classNames?.results)}
        style={
          unstyled
            ? undefined
            : {
                padding: "16px",
                background: "rgba(239, 68, 68, 0.1)",
                border: "1px solid rgba(239, 68, 68, 0.3)",
                borderRadius: "8px",
                color: "#f87171",
                fontSize: "0.85rem",
              }
        }
      >
        <span>❌ Query Execution Failed: {errorMsg}</span>
      </div>
    );
  }

  return (
    <QueryResultsTable
      results={effectiveResults}
      isLoading={effectiveIsLoading}
      unstyled={unstyled}
      cellRenderers={cellRenderers}
      pageSize={pageSize}
      className={className}
      classNames={classNames}
    />
  );
};
