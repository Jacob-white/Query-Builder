/**
 * Query Performance & Cloud Cost Advisor Component.
 * =================================================
 * Displays pre-execution cloud cost estimates (BigQuery, Snowflake),
 * full table scan warnings, and 1-click index recommendations with copyable DDL.
 */

import React, { useState, useMemo } from "react";
import { analyzeQueryPerformance } from "../utils/performanceAdvisor";
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
  const [isExpanded, setIsExpanded] = useState(false);
  const [copiedDdlId, setCopiedDdlId] = useState<string | null>(null);

  const insights = useMemo(() => {
    return analyzeQueryPerformance(querySpec, sql, dialect, tableStats);
  }, [querySpec, sql, dialect, tableStats]);

  const costInsight = insights.find((i) => i.type === "cost");
  const warnings = insights.filter((i) => i.type === "warning");
  const indexRecs = insights.filter((i) => i.type === "index");

  const handleCopyDdl = (id: string, ddl: string) => {
    navigator.clipboard?.writeText(ddl);
    setCopiedDdlId(id);
    setTimeout(() => setCopiedDdlId(null), 2000);
    if (onApplyIndexDdl) {
      onApplyIndexDdl(ddl);
    }
  };

  const containerStyle: React.CSSProperties = unstyled
    ? {}
    : {
        backgroundColor: "#1e1e2e",
        border: "1px solid #313244",
        borderRadius: "8px",
        padding: "0.75rem 1rem",
        color: "#cdd6f4",
        fontSize: "0.85rem",
        display: "flex",
        flexDirection: "column",
        gap: "0.6rem",
        ...style,
      };

  return (
    <div
      className={`qb-performance-advisor ${className}`}
      style={containerStyle}
      data-testid="query-performance-advisor"
    >
      {/* Top Summary Bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "0.5rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
          <span style={{ fontSize: "1rem" }}>💡</span>
          <span style={{ fontWeight: 600, color: "#89b4fa" }}>
            Performance & Cost Advisor:
          </span>
          {costInsight && (
            <span
              style={{
                fontSize: "0.8rem",
                padding: "0.15rem 0.5rem",
                borderRadius: "12px",
                backgroundColor: "rgba(137, 180, 250, 0.15)",
                color: "#89b4fa",
              }}
              data-testid="cost-estimate-badge"
            >
              {costInsight.title}
            </span>
          )}
          {warnings.length > 0 && (
            <span
              style={{
                fontSize: "0.75rem",
                padding: "0.15rem 0.5rem",
                borderRadius: "12px",
                backgroundColor: "rgba(249, 226, 175, 0.15)",
                color: "#f9e2af",
              }}
              data-testid="warning-count-badge"
            >
              ⚠️ {warnings.length} warning{warnings.length === 1 ? "" : "s"}
            </span>
          )}
          {indexRecs.length > 0 && (
            <span
              style={{
                fontSize: "0.75rem",
                padding: "0.15rem 0.5rem",
                borderRadius: "12px",
                backgroundColor: "rgba(166, 227, 161, 0.15)",
                color: "#a6e3a1",
              }}
              data-testid="index-rec-count-badge"
            >
              ⚡ {indexRecs.length} index recommendation{indexRecs.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        <button
          onClick={() => setIsExpanded(!isExpanded)}
          style={{
            background: "transparent",
            border: "1px solid #45475a",
            borderRadius: "4px",
            color: "#cdd6f4",
            padding: "0.25rem 0.6rem",
            fontSize: "0.75rem",
            cursor: "pointer",
          }}
          data-testid="toggle-advisor-details-btn"
        >
          {isExpanded ? "Hide Insights ▲" : "View Insights ▼"}
        </button>
      </div>

      {/* Expanded Insights Panel */}
      {isExpanded && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "0.75rem",
            paddingTop: "0.5rem",
            borderTop: "1px solid #313244",
          }}
          data-testid="advisor-expanded-panel"
        >
          {/* Cloud Cost Details */}
          {costInsight && (
            <div
              style={{
                padding: "0.5rem 0.75rem",
                backgroundColor: "#181825",
                borderRadius: "6px",
                borderLeft: "3px solid #89b4fa",
              }}
            >
              <div style={{ fontWeight: 600, color: "#89b4fa" }}>{costInsight.title}</div>
              <div style={{ color: "#a6adc8", fontSize: "0.8rem", marginTop: "0.2rem" }}>
                {costInsight.message}
              </div>
            </div>
          )}

          {/* Warnings */}
          {warnings.map((w, idx) => (
            <div
              key={idx}
              style={{
                padding: "0.5rem 0.75rem",
                backgroundColor: "#181825",
                borderRadius: "6px",
                borderLeft: "3px solid #f9e2af",
              }}
              data-testid={`advisor-warning-${idx}`}
            >
              <div style={{ fontWeight: 600, color: "#f9e2af" }}>⚠️ {w.title}</div>
              <div style={{ color: "#a6adc8", fontSize: "0.8rem", marginTop: "0.2rem" }}>
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
                style={{
                  padding: "0.6rem 0.75rem",
                  backgroundColor: "#181825",
                  borderRadius: "6px",
                  borderLeft: "3px solid #a6e3a1",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.4rem",
                }}
                data-testid={`advisor-index-rec-${idx}`}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ fontWeight: 600, color: "#a6e3a1" }}>
                    🚀 Index Recommendation: {r.indexName}
                  </div>
                  <button
                    onClick={() => handleCopyDdl(r.id, r.ddl)}
                    style={{
                      padding: "0.25rem 0.6rem",
                      backgroundColor: isCopied ? "#a6e3a1" : "#313244",
                      color: isCopied ? "#11111b" : "#cdd6f4",
                      border: "none",
                      borderRadius: "4px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      cursor: "pointer",
                      transition: "all 0.2s ease",
                    }}
                    data-testid={`copy-ddl-btn-${idx}`}
                  >
                    {isCopied ? "✓ Copied" : "Copy DDL"}
                  </button>
                </div>
                <div style={{ color: "#a6adc8", fontSize: "0.8rem" }}>{r.rationale}</div>
                <code
                  style={{
                    backgroundColor: "#11111b",
                    padding: "0.35rem 0.5rem",
                    borderRadius: "4px",
                    color: "#f5c2e7",
                    fontFamily: "monospace",
                    fontSize: "0.8rem",
                    wordBreak: "break-all",
                  }}
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
