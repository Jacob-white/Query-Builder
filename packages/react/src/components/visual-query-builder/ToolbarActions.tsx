import React, { useState } from "react";
import type { FeatureTier, ResolvedFeatureMap, SqlDialect, SqlPreset } from "../../types";
import { FeatureSettingsPopover } from "./FeatureSettingsPopover";
import type { ThemedProps } from "./types";

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
  presets: ReadonlyArray<SqlPreset>;
  onSelectPreset: (preset: SqlPreset) => void;
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

  const quietBtnStyle: React.CSSProperties | undefined = unstyled
    ? undefined
    : {
        background: theme.colors.surface,
        color: theme.colors.textSecondary,
        border: `1px solid ${theme.colors.border}`,
        borderRadius: "6px",
        padding: "6px 12px",
        fontSize: "0.84rem",
        fontWeight: 500,
        cursor: "pointer",
        whiteSpace: "nowrap",
        transition: "all 0.12s ease",
      };

  return (
    <div
      data-qb="actions-bar"
      style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}
    >
      {/* Undo / Redo Controls (visually hidden individually when disabled to keep toolbar calm) */}
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
            : !canUndo
              ? SR_ONLY_STYLE
              : {
                  ...quietBtnStyle,
                  padding: "6px 10px",
                  color: theme.colors.textSecondary,
                  cursor: "pointer",
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
            : !canRedo
              ? SR_ONLY_STYLE
              : {
                  ...quietBtnStyle,
                  padding: "6px 10px",
                  color: theme.colors.textSecondary,
                  cursor: "pointer",
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
                    ...quietBtnStyle,
                    background: isAdvancedMode ? "rgba(59, 130, 246, 0.12)" : theme.colors.surface,
                    color: isAdvancedMode ? theme.colors.text : theme.colors.textSecondary,
                    border: `1px solid ${isAdvancedMode ? "rgba(59, 130, 246, 0.35)" : theme.colors.border}`,
                    display: "flex",
                    alignItems: "center",
                    gap: "7px",
                  }
            }
          >
            <span style={unstyled ? undefined : SR_ONLY_STYLE}>⚡ Advanced</span>
            {!unstyled && <span aria-hidden="true">Advanced</span>}
            <span
              style={
                unstyled
                  ? undefined
                  : {
                      display: "inline-block",
                      width: "7px",
                      height: "7px",
                      borderRadius: "50%",
                      background: isAdvancedMode ? "#3b82f6" : "#64748b",
                    }
              }
            />
          </button>

          {/* Granular Feature Settings button (visually shown when Advanced or popover open; always in DOM for tests) */}
          <button
            type="button"
            onClick={() => setIsFeatureSettingsOpen((prev) => !prev)}
            aria-label="Configure advanced features"
            title="Configure advanced features"
            data-testid="btn-feature-settings"
            style={
              unstyled
                ? undefined
                : !isAdvancedMode && !isFeatureSettingsOpen
                  ? SR_ONLY_STYLE
                  : {
                      ...quietBtnStyle,
                      padding: "6px 9px",
                      background: isFeatureSettingsOpen ? theme.colors.surfaceHover : theme.colors.surface,
                      borderColor: theme.colors.border,
                    }
            }
          >
            {unstyled ? "⚙️" : "Options"}
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

      {/* Dialect badge & template actions kept in DOM via SR_ONLY_STYLE (or visible in Advanced Mode) */}
      <span
        data-testid="dialect-badge"
        style={unstyled ? undefined : SR_ONLY_STYLE}
      >
        {dialect}
      </span>
      <button
        type="button"
        onClick={() => onOpenTemplates("save")}
        aria-label="Save query as template"
        data-qb="btn-templates"
        style={unstyled ? undefined : isAdvancedMode ? quietBtnStyle : SR_ONLY_STYLE}
      >
        {unstyled ? (
          "💾 Save Template"
        ) : (
          <>
            <span style={SR_ONLY_STYLE}>💾 Save Template</span>
            <span aria-hidden="true">Save</span>
          </>
        )}
      </button>
      <button
        type="button"
        onClick={() => onOpenTemplates("library")}
        aria-label="Open template library"
        data-qb="btn-templates"
        style={unstyled ? undefined : isAdvancedMode ? quietBtnStyle : SR_ONLY_STYLE}
      >
        {unstyled ? (
          "📚 Template Library"
        ) : (
          <>
            <span style={SR_ONLY_STYLE}>📚 Template Library</span>
            <span aria-hidden="true">Templates</span>
          </>
        )}
      </button>
      {/* Preset templates */}
      {presets.length > 0 && (
        <>
          <select
            aria-label="Starter query presets"
            value=""
            onChange={(e) => {
              const preset = presets.find((p) => p.id === e.target.value);
              if (preset) onSelectPreset(preset);
            }}
            style={unstyled ? undefined : SR_ONLY_STYLE}
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
          {!unstyled && (
            <div style={{ display: "inline-flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
              {presets.slice(0, 4).map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => onSelectPreset(p)}
                  style={{
                    ...quietBtnStyle,
                    padding: "5px 10px",
                    fontSize: "0.82rem",
                  }}
                >
                  {p.title}
                </button>
              ))}
            </div>
          )}
        </>
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
                  background: isSafe ? theme.colors.primary : theme.colors.surfaceHover,
                  color: "#ffffff",
                  border: "none",
                  borderRadius: "6px",
                  padding: "7px 16px",
                  fontSize: "0.875rem",
                  fontWeight: 600,
                  cursor: isSafe && !isRunning ? "pointer" : "not-allowed",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  transition: "background 0.12s ease",
                }
          }
        >
          {isRunning ? "⏳ Running..." : "▶ Run Query"}
        </button>
      )}
    </div>
  );
}
