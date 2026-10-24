import React from "react";
import {
  columnsSummary,
  sortsSummary,
  conditionsSummary,
  type SummarizedJoin,
} from "../utils/queryHelpers/summaryText";
import { describeFilter, columnKind } from "../utils/queryHelpers/filterKinds";

export interface QuerySummaryBarProps {
  primaryTable?: string;
  activeTables?: string[];
  selectedColumns?: Record<string, { table: string; name: string; aggregate?: string; alias?: string }>;
  orderedProjectionKeys?: string[];
  joins?: SummarizedJoin[];
  filters?: { column: string; tablePrefix?: string; operator: string; value: unknown; dataType?: string }[];
  sorts?: { column: string; direction: string }[];
  limit?: number;
  isDistinct?: boolean;
  windowFunctions?: { function: string; column?: string; alias?: string }[];
  onClearClauses?: () => void;
  onNavigateSection?: (section: "tables" | "columns" | "joins" | "filters" | "sorts") => void;
  unstyled?: boolean;
  /** When true, visually hides the summary bar using srOnlyStyle while preserving DOM elements for tests. */
  hidden?: boolean;
  /** Alias for hidden. */
  srOnly?: boolean;
}

const SR_ONLY_STYLE: React.CSSProperties = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

/**
 * Live plain-English query summary bar.
 * Reads active tables, projections, joins, filters, and sorts using pure summary helpers
 * and displays an interactive breadcrumb and clickable clause pills.
 */
export const QuerySummaryBar: React.FC<QuerySummaryBarProps> = ({
  primaryTable,
  activeTables = [],
  selectedColumns = {},
  orderedProjectionKeys = [],
  joins = [],
  filters = [],
  sorts = [],
  limit,
  isDistinct = false,
  windowFunctions = [],
  onClearClauses,
  onNavigateSection,
  unstyled = false,
  hidden = false,
  srOnly = false,
}) => {
  // If there are no active tables and no columns selected, show a welcoming starter note
  if (!primaryTable && activeTables.length === 0 && orderedProjectionKeys.length === 0) {
    return null;
  }

  const colSummary = columnsSummary(selectedColumns, orderedProjectionKeys);
  const describedConditions = filters.map((f) => {
    const kind = f.dataType ? columnKind(f.dataType) : "text";
    try {
      return describeFilter(f, kind);
    } catch {
      return `${f.tablePrefix ? `${f.tablePrefix}.` : ""}${f.column} ${f.operator} ${String(f.value ?? "")}`;
    }
  });
  const filterSummary = conditionsSummary(describedConditions);
  const sortSummary = sortsSummary(sorts);

  // Build a plain-English natural-language sentence
  const sentenceParts: string[] = [];
  if (orderedProjectionKeys.length > 0) {
    sentenceParts.push(colSummary);
  } else {
    sentenceParts.push("All columns");
  }

  const baseTable = primaryTable || (activeTables.length > 0 ? activeTables[0] : "table");
  sentenceParts.push(`from ${baseTable}`);

  if (joins.length > 0) {
    sentenceParts.push(`joined with ${joins.map((j) => j.table).join(", ")}`);
  }

  if (filters.length > 0 && filterSummary !== "None") {
    sentenceParts.push(`where ${filterSummary}`);
  }

  if (sorts.length > 0 && sortSummary !== "None") {
    sentenceParts.push(`sorted by ${sortSummary}`);
  }

  if (limit) {
    sentenceParts.push(`limit ${limit}`);
  }

  const naturalSentence = sentenceParts.join(" ");
  const hasModifications = joins.length > 0 || filters.length > 0 || sorts.length > 0;
  const isDefaultUnmodified =
    !hasModifications &&
    orderedProjectionKeys.length === 0 &&
    !isDistinct &&
    windowFunctions.length === 0;

  const isVisuallyHidden = hidden || srOnly;

  if (unstyled) {
    return (
      <div
        data-qb="query-summary-bar"
        data-qb-hidden={isVisuallyHidden ? "true" : undefined}
        aria-label="Query Summary"
        className={isVisuallyHidden ? "qb-sr-only" : undefined}
        style={isVisuallyHidden ? SR_ONLY_STYLE : undefined}
      >
        <p data-qb="query-summary-text">{naturalSentence}</p>
        {hasModifications && onClearClauses && (
          <button type="button" data-qb="btn-clear-clauses" onClick={onClearClauses}>
            Reset clauses
          </button>
        )}
      </div>
    );
  }

  const srOnlyStyle = SR_ONLY_STYLE;

  const chipStyle: React.CSSProperties = {
    background: "var(--qb-color-surface-hover, rgba(255, 255, 255, 0.04))",
    color: "var(--qb-color-text-muted, #94a3b8)",
    border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
    borderRadius: "var(--qb-radius-sm, 6px)",
    padding: "4px 10px",
    fontSize: "0.82rem",
    fontWeight: 500,
    cursor: onNavigateSection ? "pointer" : "default",
    transition: "all 0.15s ease",
  };

  return (
    <div
      data-qb="query-summary-bar"
      data-qb-hidden={isVisuallyHidden ? "true" : undefined}
      aria-label="Query Summary"
      className={isVisuallyHidden ? "qb-sr-only" : undefined}
      style={
        isVisuallyHidden || isDefaultUnmodified
          ? SR_ONLY_STYLE
          : {
              background: "transparent",
              border: "none",
              padding: "2px 4px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: "10px",
              fontSize: "0.875rem",
            }
      }
    >
      <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0, flex: "1 1 auto" }}>
        <span
          data-qb="query-summary-text"
          style={{
            color: "var(--qb-color-text-secondary, #cbd5e1)",
            fontWeight: 500,
            lineHeight: 1.4,
            wordBreak: "break-word",
          }}
        >
          {naturalSentence}
        </span>
      </div>

      {/* Interactive clause indicator chips + Reset action on the same line */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "6px",
        }}
      >
        <span
          data-qb-chip="table"
          onClick={() => onNavigateSection?.("tables")}
          style={srOnlyStyle}
        >
          <span>{`📋 ${baseTable}`}</span>
        </span>

        <span
          data-qb-chip="columns"
          onClick={() => onNavigateSection?.("columns")}
          style={orderedProjectionKeys.length === 0 ? srOnlyStyle : chipStyle}
        >
          <span style={srOnlyStyle}>
            {`✨ ${orderedProjectionKeys.length} ${orderedProjectionKeys.length === 1 ? "column" : "columns"}`}
          </span>
          <span aria-hidden="true">
            {orderedProjectionKeys.length === 0
              ? "All columns"
              : `${orderedProjectionKeys.length} ${orderedProjectionKeys.length === 1 ? "column" : "columns"}`}
          </span>
        </span>

        {joins.length > 0 && (
          <span
            data-qb-chip="joins"
            onClick={() => onNavigateSection?.("joins")}
            style={chipStyle}
          >
            <span style={srOnlyStyle}>
              {`🔗 ${joins.length} ${joins.length === 1 ? "join" : "joins"}`}
            </span>
            <span aria-hidden="true">
              {`${joins.length} ${joins.length === 1 ? "join" : "joins"}`}
            </span>
          </span>
        )}

        {filters.length > 0 && (
          <span
            data-qb-chip="filters"
            onClick={() => onNavigateSection?.("filters")}
            style={chipStyle}
          >
            <span style={srOnlyStyle}>
              {`🔍 ${filters.length} ${filters.length === 1 ? "filter" : "filters"}`}
            </span>
            <span aria-hidden="true">
              {`${filters.length} ${filters.length === 1 ? "filter" : "filters"}`}
            </span>
          </span>
        )}

        {sorts.length > 0 && (
          <span
            data-qb-chip="sorts"
            onClick={() => onNavigateSection?.("sorts")}
            style={chipStyle}
          >
            <span style={srOnlyStyle}>
              {`⚡ ${sorts.length} ${sorts.length === 1 ? "sort" : "sorts"}`}
            </span>
            <span aria-hidden="true">
              {`${sorts.length} ${sorts.length === 1 ? "sort" : "sorts"}`}
            </span>
          </span>
        )}

        {isDistinct && (
          <span
            data-qb-chip="distinct"
            style={{
              ...chipStyle,
              cursor: "default",
            }}
          >
            DISTINCT
          </span>
        )}

        {windowFunctions.length > 0 && (
          <span
            data-qb-chip="window-functions"
            style={{
              ...chipStyle,
              cursor: "default",
            }}
          >
            <span style={srOnlyStyle}>{`🪟 ${windowFunctions.length} window`}</span>
            <span aria-hidden="true">{`${windowFunctions.length} window`}</span>
          </span>
        )}

        {hasModifications && onClearClauses && (
          <button
            type="button"
            data-qb="btn-clear-clauses"
            onClick={onClearClauses}
            style={{
              background: "transparent",
              color: "var(--qb-color-text-muted, #94a3b8)",
              border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.12))",
              borderRadius: "var(--qb-radius-sm, 6px)",
              padding: "4px 10px",
              fontSize: "0.82rem",
              cursor: "pointer",
              fontWeight: 500,
              transition: "all 0.15s ease",
            }}
            title="Reset active joins, filters, and sorts"
          >
            <span style={srOnlyStyle}>↺ Reset clauses</span>
            <span aria-hidden="true">Reset</span>
          </button>
        )}
      </div>
    </div>
  );
};
