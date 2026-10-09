import React from "react";
import type { QueryBuilderTheme } from "../../theme/tokens";

interface BannerProps {
  unstyled: boolean;
  theme: QueryBuilderTheme;
}

export interface AdvancedClausesBannerProps extends BannerProps {
  labels: string[];
  onViewAdvanced: () => void;
  onClear: () => void;
}

/** Non-destructive notice that advanced clauses keep compiling while the UI is in simple mode. */
export function AdvancedClausesBanner({
  labels,
  onViewAdvanced,
  onClear,
  unstyled,
  theme,
}: AdvancedClausesBannerProps) {
  return (
    <div
      data-testid="active-advanced-clauses-banner"
      data-qb="advanced-clauses-banner"
      style={
        unstyled
          ? undefined
          : {
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "8px 14px",
              borderRadius: theme.radii.sm,
              background: "rgba(234, 179, 8, 0.12)",
              border: "1px solid rgba(234, 179, 8, 0.35)",
              color: "#eab308",
              fontSize: theme.typography.fontSizeSm,
            }
      }
    >
      <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px" }}>
        <span>⚠️</span>
        <span>
          <strong>{labels.length} hidden advanced clause(s) active</strong> ({labels.join(", ")}).
          These clauses continue compiling.
        </span>
      </div>
      <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px" }}>
        <button
          type="button"
          onClick={onViewAdvanced}
          data-testid="btn-view-advanced-clauses"
          style={
            unstyled
              ? undefined
              : {
                  background: "#eab308",
                  color: "#000",
                  border: "none",
                  borderRadius: theme.radii.xs,
                  padding: "3px 8px",
                  fontSize: theme.typography.fontSizeXs,
                  fontWeight: theme.typography.fontWeightBold,
                  cursor: "pointer",
                }
          }
        >
          View in Advanced Mode
        </button>
        <button
          type="button"
          onClick={onClear}
          data-testid="btn-clear-advanced-clauses"
          style={
            unstyled
              ? undefined
              : {
                  background: "transparent",
                  color: theme.colors.textMuted,
                  border: `1px solid ${theme.colors.border}`,
                  borderRadius: theme.radii.xs,
                  padding: "3px 8px",
                  fontSize: theme.typography.fontSizeXs,
                  cursor: "pointer",
                }
          }
        >
          Clear Clauses
        </button>
      </div>
    </div>
  );
}

export interface SafetyBadgeProps extends BannerProps {
  valid: boolean;
  message?: string;
}

/** Read-only protection / security notice badge. */
export function SafetyBadge({ valid, message, unstyled, theme }: SafetyBadgeProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-qb="safety-badge"
      data-qb-safety={valid ? "valid" : "invalid"}
      style={
        unstyled
          ? undefined
          : {
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              fontSize: theme.typography.fontSizeXs,
              padding: "6px 12px",
              borderRadius: theme.radii.sm,
              background: valid ? theme.colors.successLight : theme.colors.errorLight,
              border: valid
                ? `1px solid ${theme.colors.success}`
                : `1px solid ${theme.colors.error}`,
              color: valid ? theme.colors.success : theme.colors.error,
            }
      }
    >
      <span>{valid ? "🛡️ Read-Only Protected (AST Verified)" : `⚠️ Security Notice: ${message}`}</span>
      <span style={unstyled ? undefined : { color: theme.colors.textMuted }}>
        Dialect: ANSI / PostgreSQL
      </span>
    </div>
  );
}

export interface ExecutionErrorBannerProps extends BannerProps {
  message: string;
}

/** Assertive alert for failed query execution. */
export function ExecutionErrorBanner({ message, unstyled, theme }: ExecutionErrorBannerProps) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      style={
        unstyled
          ? undefined
          : {
              padding: "8px 12px",
              borderRadius: theme.radii.sm,
              background: theme.colors.errorLight,
              border: `1px solid ${theme.colors.error}`,
              color: theme.colors.error,
              fontSize: theme.typography.fontSizeSm,
            }
      }
    >
      ❌ {message}
    </div>
  );
}
