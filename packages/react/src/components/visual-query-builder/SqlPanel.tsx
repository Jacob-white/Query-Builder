import React from "react";
import type { SchemaSnapshot } from "../../types";
import { parseSqlToSpec } from "../../utils/sqlParser";
import { cx } from "../../utils/classNames";
import type { ThemedProps } from "./types";

export interface SqlPanelProps extends ThemedProps {
  currentSql: string;
  rawSql: string;
  isRawMode: boolean;
  schema: SchemaSnapshot | null | undefined;
  /** Raw SQL replaced by a visual edit, offered back to the user. */
  discardedRawSql: string | null;
  onRawSqlChange: (sql: string) => void;
  onDismissDiscarded: () => void;
  onSyncWithVisualCanvas: () => void;
}

/** Raw SQL editor tab with sync badge and the "your SQL was replaced" notice. */
export function SqlPanel({
  currentSql,
  rawSql,
  isRawMode,
  schema,
  discardedRawSql,
  onRawSqlChange,
  onDismissDiscarded,
  onSyncWithVisualCanvas,
  unstyled,
  theme,
  classNames,
}: SqlPanelProps) {
  const isSynced = isRawMode ? Boolean(parseSqlToSpec(rawSql, schema)) : false;

  return (
    <div
      role="tabpanel"
      id="panel-sql"
      aria-labelledby="tab-sql"
      tabIndex={0}
      data-qb="tab-panel"
      data-qb-panel="sql"
      className={cx(classNames?.sqlEditor)}
      style={unstyled ? undefined : { display: "flex", flexDirection: "column", gap: "8px" }}
    >
      {discardedRawSql !== null && (
        <div
          role="status"
          data-qb="raw-sql-discarded-notice"
          style={
            unstyled
              ? undefined
              : {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "8px",
                  padding: "6px 10px",
                  fontSize: theme.typography.fontSizeSm,
                  color: theme.colors.textSecondary,
                  border: `1px solid ${theme.colors.border}`,
                  borderRadius: theme.radii.sm,
                }
          }
        >
          <span>A visual edit replaced your custom SQL with the compiled query.</span>
          <span>
            <button
              type="button"
              data-qb="btn-restore-raw-sql"
              onClick={() => onRawSqlChange(discardedRawSql)}
            >
              Restore my SQL
            </button>{" "}
            <button type="button" data-qb="btn-dismiss-raw-sql-notice" onClick={onDismissDiscarded}>
              Dismiss
            </button>
          </span>
        </div>
      )}
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
                  fontSize: theme.typography.fontSizeBase,
                  color: theme.colors.textMuted,
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
                      color: isSynced ? "#34d399" : "#f87171",
                      background: isSynced ? "rgba(16, 185, 129, 0.15)" : "rgba(239, 68, 68, 0.15)",
                      border: `1px solid ${
                        isSynced ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"
                      }`,
                      padding: "2px 8px",
                      borderRadius: "4px",
                      fontWeight: 600,
                    }
              }
            >
              {isSynced
                ? "⚡ Synced with Visual Canvas (Continuous Sync)"
                : "Custom Raw SQL (Visual Canvas Unsynced)"}
            </span>
          )}
          <button
            type="button"
            aria-label="Sync with visual canvas"
            onClick={onSyncWithVisualCanvas}
            style={
              unstyled
                ? undefined
                : {
                    background: "transparent",
                    border: "none",
                    color: theme.colors.primary,
                    cursor: "pointer",
                    fontSize: theme.typography.fontSizeXs,
                  }
            }
          >
            🔄 Sync with Visual Canvas
          </button>
        </div>
      </div>
      <textarea
        aria-label="Raw SQL code"
        data-qb="sql-editor"
        value={currentSql}
        onChange={(e) => onRawSqlChange(e.target.value)}
        rows={12}
        className={cx(classNames?.sqlTextarea)}
        style={
          unstyled
            ? undefined
            : {
                width: "100%",
                background: theme.colors.background,
                color: "#38bdf8",
                fontFamily: theme.typography.fontMono,
                fontSize: theme.typography.fontSizeSm,
                border: `1px solid ${theme.colors.border}`,
                borderRadius: theme.radii.md,
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
}
