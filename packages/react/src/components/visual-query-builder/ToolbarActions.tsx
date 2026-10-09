import React, { useState } from "react";
import type { FeatureTier, ResolvedFeatureMap, SqlDialect } from "../../types";
import { FeatureSettingsPopover } from "./FeatureSettingsPopover";
import type { ThemedProps } from "./types";

export interface ToolbarActionsProps extends Pick<ThemedProps, "unstyled" | "theme"> {
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  allowToggleAdvanced: boolean;
  isAdvancedMode: boolean;
  onToggleAdvanced: () => void;
  resolvedFeatures: ResolvedFeatureMap;
  featureOverrides: Record<string, FeatureTier>;
  onFeatureOverride: (key: string, tier: FeatureTier) => void;
  dialect: SqlDialect;
  onOpenTemplates: (mode: "library" | "save") => void;
  presets: ReadonlyArray<{ id: string; title: string; sql?: string }>;
  onSelectPreset: (sql: string) => void;
  readOnly: boolean;
  isRunning: boolean;
  isSafe: boolean;
  onRun: () => void;
}

/** Right-hand action cluster: undo/redo, advanced mode, dialect, templates, presets and Run. */
export function ToolbarActions({
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  allowToggleAdvanced,
  isAdvancedMode,
  onToggleAdvanced,
  resolvedFeatures,
  featureOverrides,
  onFeatureOverride,
  dialect,
  onOpenTemplates,
  presets,
  onSelectPreset,
  readOnly,
  isRunning,
  isSafe,
  onRun,
  unstyled,
  theme,
}: ToolbarActionsProps) {
  const [isFeatureSettingsOpen, setIsFeatureSettingsOpen] = useState<boolean>(false);

  return (
    <div
      data-qb="actions-bar"
      style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "10px" }}
    >
      {/* Undo / Redo Controls */}
      <button
        type="button"
        onClick={onUndo}
        disabled={!canUndo}
        aria-label="Undo query changes (Cmd+Z)"
        title="Undo (Cmd+Z)"
        data-qb="btn-undo"
        style={
          unstyled
            ? undefined
            : {
                background: canUndo ? theme.colors.surface : "rgba(30, 41, 59, 0.2)",
                color: canUndo ? theme.colors.text : theme.colors.textMuted,
                border: `1px solid ${canUndo ? theme.colors.border : "transparent"}`,
                borderRadius: theme.radii.sm,
                padding: "6px 10px",
                fontSize: theme.typography.fontSizeSm,
                cursor: canUndo ? "pointer" : "not-allowed",
                opacity: canUndo ? 1 : 0.4,
              }
        }
      >
        ↶ Undo
      </button>
      <button
        type="button"
        onClick={onRedo}
        disabled={!canRedo}
        aria-label="Redo query changes (Cmd+Shift+Z)"
        title="Redo (Cmd+Shift+Z)"
        data-qb="btn-redo"
        style={
          unstyled
            ? undefined
            : {
                background: canRedo ? theme.colors.surface : "rgba(30, 41, 59, 0.2)",
                color: canRedo ? theme.colors.text : theme.colors.textMuted,
                border: `1px solid ${canRedo ? theme.colors.border : "transparent"}`,
                borderRadius: theme.radii.sm,
                padding: "6px 10px",
                fontSize: theme.typography.fontSizeSm,
                cursor: canRedo ? "pointer" : "not-allowed",
                opacity: canRedo ? 1 : 0.4,
              }
        }
      >
        ↷ Redo
      </button>

      {/* Advanced Mode Toggle Switch */}
      {allowToggleAdvanced && (
        <div
          data-qb="advanced-mode-control"
          style={
            unstyled
              ? undefined
              : { display: "flex", alignItems: "center", gap: "4px", position: "relative" }
          }
        >
          <button
            type="button"
            onClick={onToggleAdvanced}
            aria-pressed={isAdvancedMode}
            data-testid="btn-toggle-advanced"
            data-qb="btn-toggle-advanced"
            title={isAdvancedMode ? "Switch to Simple Mode" : "Switch to Advanced Mode"}
            style={
              unstyled
                ? undefined
                : {
                    background: isAdvancedMode ? "rgba(168, 85, 247, 0.2)" : theme.colors.surface,
                    color: isAdvancedMode ? "#c084fc" : theme.colors.textMuted,
                    border: `1px solid ${isAdvancedMode ? "#a855f7" : theme.colors.border}`,
                    borderRadius: theme.radii.sm,
                    padding: "6px 10px",
                    fontSize: theme.typography.fontSizeSm,
                    fontWeight: theme.typography.fontWeightSemibold,
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                  }
            }
          >
            <span>⚡ Advanced</span>
            <span
              style={
                unstyled
                  ? undefined
                  : {
                      display: "inline-block",
                      width: "8px",
                      height: "8px",
                      borderRadius: "50%",
                      background: isAdvancedMode ? "#22c55e" : "#64748b",
                    }
              }
            />
          </button>

          {/* Granular Feature Settings Gear */}
          <button
            type="button"
            onClick={() => setIsFeatureSettingsOpen((prev) => !prev)}
            aria-label="Configure advanced features"
            title="Configure advanced features"
            data-testid="btn-feature-settings"
            style={
              unstyled
                ? undefined
                : {
                    background: isFeatureSettingsOpen ? theme.colors.surfaceHover : "transparent",
                    color: theme.colors.textMuted,
                    border: `1px solid ${isFeatureSettingsOpen ? theme.colors.border : "transparent"}`,
                    borderRadius: theme.radii.sm,
                    padding: "6px 8px",
                    fontSize: theme.typography.fontSizeSm,
                    cursor: "pointer",
                  }
            }
          >
            ⚙️
          </button>

          {isFeatureSettingsOpen && (
            <FeatureSettingsPopover
              featureOverrides={featureOverrides}
              resolvedFeatures={resolvedFeatures}
              onOverride={onFeatureOverride}
              onClose={() => setIsFeatureSettingsOpen(false)}
              unstyled={unstyled}
              theme={theme}
            />
          )}
        </div>
      )}

      <span
        data-testid="dialect-badge"
        style={
          unstyled
            ? undefined
            : {
                padding: "4px 8px",
                background: theme.colors.surface,
                border: `1px solid ${theme.colors.border}`,
                borderRadius: theme.radii.xs,
                fontSize: theme.typography.fontSizeXs,
                fontFamily: theme.typography.fontMono,
                color: theme.colors.textMuted,
                textTransform: "uppercase",
              }
        }
      >
        {dialect}
      </span>
      <button
        type="button"
        onClick={() => onOpenTemplates("save")}
        aria-label="Save query as template"
        data-qb="btn-templates"
        style={
          unstyled
            ? undefined
            : {
                background: theme.colors.successLight,
                color: theme.colors.success,
                border: `1px solid ${theme.colors.success}`,
                borderRadius: theme.radii.sm,
                padding: "6px 12px",
                fontSize: theme.typography.fontSizeSm,
                fontWeight: theme.typography.fontWeightSemibold,
                cursor: "pointer",
              }
        }
      >
        💾 Save Template
      </button>
      <button
        type="button"
        onClick={() => onOpenTemplates("library")}
        aria-label="Open template library"
        data-qb="btn-templates"
        style={
          unstyled
            ? undefined
            : {
                background: "rgba(99, 102, 241, 0.15)",
                color: "#818cf8",
                border: "1px solid rgba(99, 102, 241, 0.3)",
                borderRadius: theme.radii.sm,
                padding: "6px 12px",
                fontSize: theme.typography.fontSizeSm,
                fontWeight: theme.typography.fontWeightSemibold,
                cursor: "pointer",
              }
        }
      >
        📚 Template Library
      </button>
      {/* Preset templates */}
      {presets.length > 0 && (
        <select
          aria-label="Starter query presets"
          defaultValue=""
          onChange={(e) => {
            const preset = presets.find((p) => p.id === e.target.value);
            if (preset?.sql) onSelectPreset(preset.sql);
          }}
          style={
            unstyled
              ? undefined
              : {
                  background: theme.colors.surface,
                  color: theme.colors.textSecondary,
                  border: `1px solid ${theme.colors.border}`,
                  borderRadius: theme.radii.sm,
                  padding: "6px 10px",
                  fontSize: theme.typography.fontSizeSm,
                }
          }
        >
          <option value="" disabled>
            ⚡ Starters & Presets...
          </option>
          {presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title}
            </option>
          ))}
        </select>
      )}

      {/* Run Query Button */}
      {!readOnly && (
        <button
          type="button"
          onClick={onRun}
          disabled={isRunning || !isSafe}
          aria-label="Run query"
          data-qb="btn-run"
          data-qb-running={isRunning ? "true" : "false"}
          style={
            unstyled
              ? undefined
              : {
                  background: isSafe ? theme.colors.success : theme.colors.surfaceHover,
                  color: "#ffffff",
                  border: "none",
                  borderRadius: theme.radii.sm,
                  padding: "6px 16px",
                  fontSize: theme.typography.fontSizeBase,
                  fontWeight: theme.typography.fontWeightBold,
                  cursor: isSafe && !isRunning ? "pointer" : "not-allowed",
                  boxShadow: isSafe ? "0 4px 12px rgba(16, 185, 129, 0.3)" : "none",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }
          }
        >
          {isRunning ? "⏳ Running..." : "▶ Run Query"}
        </button>
      )}
    </div>
  );
}
