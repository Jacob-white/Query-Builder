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
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const handleCopySql = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(currentSql);
    }
    setCopied(true);
  };

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
        <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px" }}>
          {isRawMode && (
            <span
              data-qb="sql-sync-badge"
              className={cx(classNames?.sqlSyncBadge)}
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: "0.8rem",
                      color: isSynced
                        ? "var(--qb-color-confirmed-text, #34d399)"
                        : "var(--qb-color-error, #f87171)",
                      background: isSynced
                        ? "var(--qb-color-confirmed-bg, rgba(16, 185, 129, 0.15))"
                        : "rgba(239, 68, 68, 0.15)",
                      border: `1px solid ${
                        isSynced
                          ? "var(--qb-color-confirmed-border, rgba(16, 185, 129, 0.3))"
                          : "rgba(239, 68, 68, 0.3)"
                      }`,
                      padding: "4px 10px",
                      borderRadius: "6px",
                      fontWeight: 600,
                    }
              }
            >
              {unstyled ? (
                isSynced
                  ? "⚡ Synced with Visual Canvas (Continuous Sync)"
                  : "Custom Raw SQL (Visual Canvas Unsynced)"
              ) : isSynced ? (
                <>
                  <span
                    style={{
                      position: "absolute",
                      width: "1px",
                      height: "1px",
                      padding: 0,
                      margin: "-1px",
                      overflow: "hidden",
                      clip: "rect(0, 0, 0, 0)",
                      whiteSpace: "nowrap",
                      border: 0,
                    }}
                  >
                    ⚡ Synced with Visual Canvas (Continuous Sync)
                  </span>
                  <span aria-hidden="true">Synced with Visual Canvas</span>
                </>
              ) : (
                "Custom Raw SQL (Visual Canvas Unsynced)"
              )}
            </span>
          )}
          <button
            type="button"
            aria-label="Copy SQL"
            data-qb="btn-copy-sql"
            onClick={handleCopySql}
            style={
              unstyled
                ? undefined
                : {
                    background: theme.colors.surface,
                    border: `1px solid ${theme.colors.border}`,
                    borderRadius: "6px",
                    padding: "5px 11px",
                    color: theme.colors.textSecondary,
                    cursor: "pointer",
                    fontSize: "0.82rem",
                    fontWeight: 500,
                  }
            }
          >
            {copied ? (
              "✓ Copied"
            ) : unstyled ? (
              "📋 Copy SQL"
            ) : (
              <>
                <span
                  style={{
                    position: "absolute",
                    width: "1px",
                    height: "1px",
                    padding: 0,
                    margin: "-1px",
                    overflow: "hidden",
                    clip: "rect(0, 0, 0, 0)",
                    whiteSpace: "nowrap",
                    border: 0,
                  }}
                >
                  📋 Copy SQL
                </span>
                <span aria-hidden="true">Copy SQL</span>
              </>
            )}
          </button>
          <button
            type="button"
            aria-label="Sync with visual canvas"
            onClick={onSyncWithVisualCanvas}
            style={
              unstyled
                ? undefined
                : {
                    background: "transparent",
                    border: `1px solid ${theme.colors.border}`,
                    borderRadius: "6px",
                    padding: "5px 11px",
                    color: theme.colors.textSecondary,
                    cursor: "pointer",
                    fontSize: "0.82rem",
                    fontWeight: 500,
                  }
            }
          >
            {unstyled ? (
              "🔄 Sync with Visual Canvas"
            ) : (
              <>
                <span
                  style={{
                    position: "absolute",
                    width: "1px",
                    height: "1px",
                    padding: 0,
                    margin: "-1px",
                    overflow: "hidden",
                    clip: "rect(0, 0, 0, 0)",
                    whiteSpace: "nowrap",
                    border: 0,
                  }}
                >
                  🔄 Sync with Visual Canvas
                </span>
                <span aria-hidden="true">Reset to Visual SQL</span>
              </>
            )}
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
                color: theme.colors.text,
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
