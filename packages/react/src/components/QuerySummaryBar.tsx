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
}

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

  if (unstyled) {
    return (
      <div data-qb="query-summary-bar" aria-label="Query Summary">
        <p data-qb="query-summary-text">{naturalSentence}</p>
        {hasModifications && onClearClauses && (
          <button type="button" data-qb="btn-clear-clauses" onClick={onClearClauses}>
            Reset clauses
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      data-qb="query-summary-bar"
      aria-label="Query Summary"
      style={{
        background: "var(--qb-color-surface, rgba(15, 23, 42, 0.65))",
        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
        borderRadius: "var(--qb-radius-md, 8px)",
        padding: "10px 14px",
        display: "flex",
        flexDirection: "column",
        gap: "8px",
        fontSize: "0.82rem",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
          <span style={{ fontSize: "1rem" }}>📖</span>
          <span
            data-qb="query-summary-text"
            style={{
              color: "var(--qb-color-text, #f1f5f9)",
              fontWeight: 500,
              lineHeight: 1.4,
              wordBreak: "break-word",
            }}
          >
            {naturalSentence}
          </span>
        </div>

        {hasModifications && onClearClauses && (
          <button
            type="button"
            data-qb="btn-clear-clauses"
            onClick={onClearClauses}
            style={{
              background: "transparent",
              color: "var(--qb-color-text-muted, #94a3b8)",
              border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.15))",
              borderRadius: "var(--qb-radius-sm, 4px)",
              padding: "2px 8px",
              fontSize: "0.72rem",
              cursor: "pointer",
              fontWeight: 500,
              transition: "all 0.15s ease",
            }}
            title="Reset active joins, filters, and sorts"
          >
            ↺ Reset clauses
          </button>
        )}
      </div>

      {/* Interactive clause indicator chips */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "6px",
          paddingTop: "2px",
        }}
      >
        <span
          data-qb-chip="table"
          onClick={() => onNavigateSection?.("tables")}
          style={{
            background: "rgba(59, 130, 246, 0.12)",
            color: "var(--qb-color-primary, #60a5fa)",
            border: "1px solid rgba(59, 130, 246, 0.3)",
            borderRadius: "12px",
            padding: "2px 8px",
            fontSize: "0.72rem",
            fontWeight: 600,
            cursor: onNavigateSection ? "pointer" : "default",
          }}
        >
          📋 {baseTable}
        </span>

        <span
          data-qb-chip="columns"
          onClick={() => onNavigateSection?.("columns")}
          style={{
            background: "rgba(16, 185, 129, 0.12)",
            color: "#34d399",
            border: "1px solid rgba(16, 185, 129, 0.3)",
            borderRadius: "12px",
            padding: "2px 8px",
            fontSize: "0.72rem",
            fontWeight: 600,
            cursor: onNavigateSection ? "pointer" : "default",
          }}
        >
          ✨ {orderedProjectionKeys.length} {orderedProjectionKeys.length === 1 ? "column" : "columns"}
        </span>

        {joins.length > 0 && (
          <span
            data-qb-chip="joins"
            onClick={() => onNavigateSection?.("joins")}
            style={{
              background: "rgba(139, 92, 246, 0.12)",
              color: "#a78bfa",
              border: "1px solid rgba(139, 92, 246, 0.3)",
              borderRadius: "12px",
              padding: "2px 8px",
              fontSize: "0.72rem",
              fontWeight: 600,
              cursor: onNavigateSection ? "pointer" : "default",
            }}
          >
            🔗 {joins.length} {joins.length === 1 ? "join" : "joins"}
          </span>
        )}

        {filters.length > 0 && (
          <span
            data-qb-chip="filters"
            onClick={() => onNavigateSection?.("filters")}
            style={{
              background: "rgba(245, 158, 11, 0.12)",
              color: "#fbbf24",
              border: "1px solid rgba(245, 158, 11, 0.3)",
              borderRadius: "12px",
              padding: "2px 8px",
              fontSize: "0.72rem",
              fontWeight: 600,
              cursor: onNavigateSection ? "pointer" : "default",
            }}
          >
            🔍 {filters.length} {filters.length === 1 ? "filter" : "filters"}
          </span>
        )}

        {sorts.length > 0 && (
          <span
            data-qb-chip="sorts"
            onClick={() => onNavigateSection?.("sorts")}
            style={{
              background: "rgba(236, 72, 153, 0.12)",
              color: "#f472b6",
              border: "1px solid rgba(236, 72, 153, 0.3)",
              borderRadius: "12px",
              padding: "2px 8px",
              fontSize: "0.72rem",
              fontWeight: 600,
              cursor: onNavigateSection ? "pointer" : "default",
            }}
          >
            ⚡ {sorts.length} {sorts.length === 1 ? "sort" : "sorts"}
          </span>
        )}

        {isDistinct && (
          <span
            data-qb-chip="distinct"
            style={{
              background: "rgba(14, 165, 233, 0.12)",
              color: "#38bdf8",
              border: "1px solid rgba(14, 165, 233, 0.3)",
              borderRadius: "12px",
              padding: "2px 8px",
              fontSize: "0.72rem",
              fontWeight: 600,
            }}
          >
            DISTINCT
          </span>
        )}

        {windowFunctions.length > 0 && (
          <span
            data-qb-chip="window-functions"
            style={{
              background: "rgba(168, 85, 247, 0.12)",
              color: "#c084fc",
              border: "1px solid rgba(168, 85, 247, 0.3)",
              borderRadius: "12px",
              padding: "2px 8px",
              fontSize: "0.72rem",
              fontWeight: 600,
            }}
          >
            🪟 {windowFunctions.length} window
          </span>
        )}
      </div>
    </div>
  );
};
