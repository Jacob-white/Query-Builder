import React from "react";
import type { FeatureTier, ResolvedFeatureMap } from "../../types";
import { ALL_FEATURE_KEYS } from "../../utils/featureUtils";
import type { ThemedProps } from "./types";

export interface FeatureSettingsPopoverProps extends Pick<ThemedProps, "unstyled" | "theme"> {
  featureOverrides: Record<string, FeatureTier>;
  resolvedFeatures: ResolvedFeatureMap;
  onOverride: (key: string, tier: FeatureTier) => void;
  onClose: () => void;
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

/** Per-feature tier override dropdown opened from the advanced-mode gear. */
export function FeatureSettingsPopover({
  featureOverrides,
  resolvedFeatures,
  onOverride,
  onClose,
  unstyled,
  theme,
}: FeatureSettingsPopoverProps) {
  return (
    <div
      data-testid="feature-settings-popover"
      style={
        unstyled
          ? undefined
          : {
              position: "absolute",
              top: "100%",
              right: 0,
              marginTop: "6px",
              width: "310px",
              background: theme.colors.surface,
              border: `1px solid ${theme.colors.border}`,
              borderRadius: theme.radii.md,
              boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.5)",
              padding: "12px",
              zIndex: 1000,
              fontSize: theme.typography.fontSizeXs,
            }
      }
    >
      <div
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "8px",
                paddingBottom: "6px",
                borderBottom: `1px solid ${theme.colors.border}`,
                fontWeight: theme.typography.fontWeightBold,
              }
        }
      >
        <span>Feature Tiers</span>
        <button
          type="button"
          onClick={onClose}
          style={
            unstyled
              ? undefined
              : {
                  background: "none",
                  border: "none",
                  color: theme.colors.textMuted,
                  cursor: "pointer",
                }
          }
        >
          ✕
        </button>
      </div>
      <div
        style={
          unstyled
            ? undefined
            : {
                maxHeight: "240px",
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: "6px",
              }
        }
      >
        {ALL_FEATURE_KEYS.map((key) => {
          const currentTier = featureOverrides[key] ?? resolvedFeatures[key];
          return (
            <div
              key={key}
              style={
                unstyled
                  ? undefined
                  : {
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: "8px",
                    }
              }
            >
              <span
                style={
                  unstyled ? undefined : { textTransform: "capitalize", color: theme.colors.text }
                }
              >
                {key.replace("_", " ")}
              </span>
              <select
                value={currentTier}
                onChange={(e) => onOverride(key, e.target.value as FeatureTier)}
                data-testid={`feature-select-${key}`}
                style={unstyled ? undefined : SR_ONLY_STYLE}
              >
                <option value="standard">Standard</option>
                <option value="advanced">Advanced</option>
                <option value="disabled">Disabled</option>
              </select>
              {!unstyled && (
                <div style={{ display: "inline-flex", gap: "2px", background: theme.colors.background, padding: "2px", borderRadius: "6px", border: `1px solid ${theme.colors.border}` }}>
                  {(["standard", "advanced", "disabled"] as FeatureTier[]).map((tier) => {
                    const isSelected = currentTier === tier;
                    return (
                      <button
                        key={tier}
                        type="button"
                        onClick={() => onOverride(key, tier)}
                        style={{
                          padding: "2px 6px",
                          borderRadius: "4px",
                          fontSize: "0.66rem",
                          fontWeight: isSelected ? 700 : 500,
                          border: "none",
                          cursor: "pointer",
                          background: isSelected ? "rgba(59, 130, 246, 0.25)" : "transparent",
                          color: isSelected ? "#60a5fa" : theme.colors.textMuted,
                          textTransform: "capitalize",
                        }}
                      >
                        {tier === "standard" ? "Std" : tier === "advanced" ? "Adv" : "Off"}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
