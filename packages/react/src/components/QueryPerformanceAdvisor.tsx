/**
 * Query Performance & Cloud Cost Advisor Component.
 * =================================================
 * Displays pre-execution cloud cost estimates (BigQuery, Snowflake),
 * full table scan warnings, and 1-click index recommendations with copyable DDL.
 */

import React, { useState, useMemo, useEffect } from "react";
import { analyzeQueryPerformance } from "../utils/performanceAdvisor";
import { useTheme } from "../theme/ThemeProvider";
import type {
  QuerySpec,
  SchemaSnapshot,
  SqlDialect,
} from "../types";

export interface QueryPerformanceAdvisorProps {
  querySpec: Partial<QuerySpec>;
  sql: string;
  dialect?: SqlDialect;
  schema?: SchemaSnapshot | null;
  tableStats?: Record<string, { rowCount?: number; byteSize?: number }>;
  onApplyIndexDdl?: (ddl: string) => void;
  unstyled?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export const QueryPerformanceAdvisor: React.FC<QueryPerformanceAdvisorProps> = ({
  querySpec,
  sql,
  dialect = "postgres",
  schema,
  tableStats,
  onApplyIndexDdl,
  unstyled = false,
  className = "",
  style = {},
}) => {
  const { cssVariables } = useTheme();
  const [isExpanded, setIsExpanded] = useState(false);
  const [copiedDdlId, setCopiedDdlId] = useState<string | null>(null);

  useEffect(() => {
    if (!copiedDdlId) return;
    const timer = setTimeout(() => setCopiedDdlId(null), 2000);
    return () => clearTimeout(timer);
  }, [copiedDdlId]);

  const insights = useMemo(() => {
    return analyzeQueryPerformance(querySpec, sql, dialect, tableStats, schema);
  }, [querySpec, sql, dialect, tableStats, schema]);

  const costInsight = insights.find((i) => i.type === "cost");
  const warnings = insights.filter((i) => i.type === "warning");
  const indexRecs = insights.filter((i) => i.type === "index");

  const handleCopyDdl = (id: string, ddl: string) => {
    navigator.clipboard?.writeText(ddl);
    setCopiedDdlId(id);
    if (onApplyIndexDdl) {
      onApplyIndexDdl(ddl);
    }
  };

  const s = (styleObj: React.CSSProperties): React.CSSProperties | undefined =>
    unstyled ? undefined : styleObj;

  const containerStyle: React.CSSProperties | undefined = s({
    ...(cssVariables as React.CSSProperties),
    backgroundColor: "var(--qb-color-surface, #1e1e2e)",
    border: "1px solid var(--qb-color-border, #313244)",
    borderRadius: "8px",
    padding: "0.75rem 1rem",
    color: "var(--qb-color-text, #cdd6f4)",
    fontSize: "0.85rem",
    display: "flex",
    flexDirection: "column",
    gap: "0.6rem",
    ...style,
  });

  return (
    <div
      className={`qb-performance-advisor ${className}`}
      style={containerStyle}
      data-testid="query-performance-advisor"
    >
      {/* Top Summary Bar */}
      <div
        style={s({
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "0.5rem",
        })}
      >
        <div style={s({ display: "flex", alignItems: "center", gap: "0.6rem" })}>
          <span style={s({ fontSize: "1rem" })}>💡</span>
          <span style={s({ fontWeight: 600, color: "var(--qb-color-primary, #2563eb)" })}>
            Performance & Cost Advisor:
          </span>
          {costInsight && (
            <span
              style={s({
                fontSize: "0.8rem",
                padding: "0.15rem 0.5rem",
                borderRadius: "12px",
                backgroundColor: "rgba(59, 130, 246, 0.14)",
                color: "var(--qb-color-primary, #2563eb)",
              })}
              data-testid="cost-estimate-badge"
            >
              {costInsight.title}
            </span>
          )}
          {warnings.length > 0 && (
            <span
              style={s({
                fontSize: "0.75rem",
                padding: "0.15rem 0.5rem",
                borderRadius: "12px",
                backgroundColor: "var(--qb-color-suggested-bg, rgba(245, 158, 11, 0.15))",
                color: "var(--qb-color-suggested-text, #b45309)",
              })}
              data-testid="warning-count-badge"
            >
              ⚠️ {warnings.length} warning{warnings.length === 1 ? "" : "s"}
            </span>
          )}
          {indexRecs.length > 0 && (
            <span
              style={s({
                fontSize: "0.75rem",
                padding: "0.15rem 0.5rem",
                borderRadius: "12px",
                backgroundColor: "var(--qb-color-confirmed-bg, rgba(16, 185, 129, 0.15))",
                color: "var(--qb-color-confirmed-text, #047857)",
              })}
              data-testid="index-rec-count-badge"
            >
              ⚡ {indexRecs.length} index recommendation{indexRecs.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        <button
          onClick={() => setIsExpanded(!isExpanded)}
          style={s({
            background: "transparent",
            border: "1px solid var(--qb-color-border, #45475a)",
            borderRadius: "4px",
            color: "var(--qb-color-text, #cdd6f4)",
            padding: "0.25rem 0.6rem",
            fontSize: "0.75rem",
            cursor: "pointer",
          })}
          data-testid="toggle-advisor-details-btn"
        >
          {isExpanded ? "Hide Insights ▲" : "View Insights ▼"}
        </button>
      </div>

      {/* Expanded Insights Panel */}
      {isExpanded && (
        <div
          style={s({
            display: "flex",
            flexDirection: "column",
            gap: "0.75rem",
            paddingTop: "0.5rem",
            borderTop: "1px solid var(--qb-color-border, #313244)",
          })}
          data-testid="advisor-expanded-panel"
        >
          {/* Cloud Cost Details */}
          {costInsight && (
            <div
              style={s({
                padding: "0.5rem 0.75rem",
                backgroundColor: "var(--qb-color-background, #181825)",
                borderRadius: "6px",
                borderLeft: "3px solid var(--qb-color-primary, #2563eb)",
              })}
            >
              <div style={s({ fontWeight: 600, color: "var(--qb-color-primary, #2563eb)" })}>{costInsight.title}</div>
              <div style={s({ color: "var(--qb-color-text-secondary, #64748b)", fontSize: "0.8rem", marginTop: "0.2rem" })}>
                {costInsight.message}
              </div>
            </div>
          )}

          {/* Warnings */}
          {warnings.map((w, idx) => (
            <div
              key={idx}
              style={s({
                padding: "0.5rem 0.75rem",
                backgroundColor: "var(--qb-color-background, #181825)",
                borderRadius: "6px",
                borderLeft: "3px solid var(--qb-color-suggested-text, #b45309)",
              })}
              data-testid={`advisor-warning-${idx}`}
            >
              <div style={s({ fontWeight: 600, color: "var(--qb-color-suggested-text, #b45309)" })}>⚠️ {w.title}</div>
              <div style={s({ color: "var(--qb-color-text-secondary, #64748b)", fontSize: "0.8rem", marginTop: "0.2rem" })}>
                {w.message}
              </div>
            </div>
          ))}

          {/* Index Recommendations */}
          {indexRecs.map((rec, idx) => {
            const r = rec.recommendation!;
            const isCopied = copiedDdlId === r.id;

            return (
              <div
                key={idx}
                style={s({
                  padding: "0.6rem 0.75rem",
                  backgroundColor: "var(--qb-color-background, #181825)",
                  borderRadius: "6px",
                  borderLeft: "3px solid var(--qb-color-confirmed-text, #047857)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.4rem",
                })}
                data-testid={`advisor-index-rec-${idx}`}
              >
                <div style={s({ display: "flex", justifyContent: "space-between", alignItems: "center" })}>
                  <div style={s({ fontWeight: 600, color: "var(--qb-color-confirmed-text, #047857)" })}>
                    🚀 Index Recommendation: {r.indexName}
                  </div>
                  <button
                    onClick={() => handleCopyDdl(r.id, r.ddl)}
                    style={s({
                      padding: "0.25rem 0.6rem",
                      backgroundColor: isCopied ? "#10b981" : "var(--qb-color-surface-hover, #313244)",
                      color: isCopied ? "#ffffff" : "var(--qb-color-text, #cdd6f4)",
                      border: "1px solid var(--qb-color-border, transparent)",
                      borderRadius: "4px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      cursor: "pointer",
                      transition: "all 0.2s ease",
                    })}
                    data-testid={`copy-ddl-btn-${idx}`}
                  >
                    {isCopied ? "✓ Copied" : "Copy DDL"}
                  </button>
                </div>
                <div style={s({ color: "var(--qb-color-text-secondary, #64748b)", fontSize: "0.8rem" })}>{r.rationale}</div>
                <code
                  style={s({
                    backgroundColor: "var(--qb-color-surface, #11111b)",
                    border: "1px solid var(--qb-color-border, transparent)",
                    padding: "0.35rem 0.5rem",
                    borderRadius: "4px",
                    color: "var(--qb-color-primary, #2563eb)",
                    fontFamily: "monospace",
                    fontSize: "0.8rem",
                    wordBreak: "break-all",
                  })}
                >
                  {r.ddl}
                </code>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
