import React from "react";
import type { QueryBuilderClassNames } from "../../types";
import { useCompoundQueryBuilder } from "./QueryBuilderContext";
import { parseSqlToSpec } from "../../utils/sqlParser";
import { cx } from "../../utils/classNames";

export interface QueryBuilderSqlEditorProps {
  /** Optional container class name */
  className?: string;
  /** Granular slot class names mapping */
  classNames?: QueryBuilderClassNames;
  /** Whether the SQL textarea is read-only */
  readOnly?: boolean;
  /** Textarea rows (default: 10) */
  rows?: number;
  /** Whether to render a "Run Query" action button in the toolbar */
  showExecuteButton?: boolean;
  /** Custom label for the run button (default: "▶ Run Query") */
  executeButtonLabel?: string;
  /** Unstyled mode flag */
  unstyled?: boolean;
}

export const QueryBuilderSqlEditor: React.FC<QueryBuilderSqlEditorProps> = ({
  className,
  classNames: propClassNames,
  readOnly = false,
  rows = 10,
  showExecuteButton = true,
  executeButtonLabel = "▶ Run Query",
  unstyled: propUnstyled,
}) => {
  const {
    sql,
    rawSql,
    isRawMode,
    setRawSql,
    syncSqlToCanvas,
    executeQuery,
    isRunning,
    normalizedSchema,
    unstyled: rootUnstyled,
    classNames: rootClassNames,
  } = useCompoundQueryBuilder();

  const unstyled = propUnstyled ?? rootUnstyled;
  const classNames = propClassNames || rootClassNames;

  const isParseable = isRawMode && Boolean(parseSqlToSpec(rawSql, normalizedSchema));

  return (
    <div
      data-qb="sql-editor-panel"
      className={cx(className, classNames?.sqlEditor)}
      style={
        unstyled
          ? undefined
          : { display: "flex", flexDirection: "column", gap: "8px" }
      }
    >
      <div
        style={
          unstyled
            ? undefined
            : { display: "flex", justifyContent: "space-between", alignItems: "center" }
        }
      >
        <span
          className={cx(classNames?.title)}
          style={
            unstyled
              ? undefined
              : {
                  fontSize: "0.88rem",
                  color: "#94a3b8",
                  fontWeight: 600,
                }
          }
        >
          Live SQL Code Editor
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {isRawMode && (
            <span
              data-qb="sql-sync-badge"
              className={cx(classNames?.sqlSyncBadge)}
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: "0.75rem",
                      color: isParseable ? "#34d399" : "#f87171",
                      background: isParseable
                        ? "rgba(16, 185, 129, 0.15)"
                        : "rgba(239, 68, 68, 0.15)",
                      border: `1px solid ${
                        isParseable
                          ? "rgba(16, 185, 129, 0.3)"
                          : "rgba(239, 68, 68, 0.3)"
                      }`,
                      padding: "2px 8px",
                      borderRadius: "4px",
                      fontWeight: 600,
                    }
              }
            >
              {isParseable
                ? "⚡ Synced with Visual Canvas"
                : "Custom Raw SQL (Visual Canvas Unsynced)"}
            </span>
          )}
          <button
            type="button"
            aria-label="Sync with visual canvas"
            onClick={syncSqlToCanvas}
            style={
              unstyled
                ? undefined
                : {
                    background: "transparent",
                    border: "none",
                    color: "#38bdf8",
                    cursor: "pointer",
                    fontSize: "0.78rem",
                  }
            }
          >
            🔄 Sync with Visual Canvas
          </button>
          {showExecuteButton && (
            <button
              type="button"
              data-qb="btn-execute-sql"
              aria-label="Execute query"
              disabled={isRunning}
              onClick={() => {
                executeQuery().catch(() => {});
              }}
              style={
                unstyled
                  ? undefined
                  : {
                      background: "#3b82f6",
                      color: "#ffffff",
                      border: "none",
                      borderRadius: "6px",
                      padding: "4px 10px",
                      fontSize: "0.78rem",
                      fontWeight: 600,
                      cursor: isRunning ? "not-allowed" : "pointer",
                      opacity: isRunning ? 0.6 : 1,
                    }
              }
            >
              {isRunning ? "⏳ Running..." : executeButtonLabel}
            </button>
          )}
        </div>
      </div>
      <textarea
        aria-label="Raw SQL code"
        data-qb="sql-editor"
        value={sql}
        onChange={(e) => {
          if (!readOnly) {
            setRawSql(e.target.value);
          }
        }}
        readOnly={readOnly}
        rows={rows}
        className={cx(classNames?.sqlTextarea)}
        style={
          unstyled
            ? undefined
            : {
                width: "100%",
                background: "#0f172a",
                color: "#38bdf8",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                fontSize: "0.85rem",
                border: "1px solid rgba(255, 255, 255, 0.12)",
                borderRadius: "6px",
                padding: "12px",
                lineHeight: 1.5,
                resize: "vertical",
                outline: "none",
                boxSizing: "border-box",
              }
        }
      />
    </div>
  );
};
