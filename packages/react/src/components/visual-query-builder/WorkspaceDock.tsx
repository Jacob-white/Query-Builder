import React, { useState } from "react";
import type { QueryResultData, QueryBuilderClassNames } from "../../types";
import type { QueryBuilderTheme } from "../../theme/tokens";
import type { CellRenderer } from "../../theme/QueryBuilderProvider";
import { ResultsPanel, ChartPanel } from "./TabPanels";

export type DockTab = "results" | "chart" | "sql";

export interface WorkspaceDockProps {
  results: QueryResultData | null;
  isLoading: boolean;
  currentSql: string;
  isOpen: boolean;
  onToggleOpen: () => void;
  dockTab: DockTab;
  onSelectDockTab: (tab: DockTab) => void;
  onExpandFullTab: (tab: DockTab) => void;
  cellRenderers?: Record<string, CellRenderer>;
  classNames?: QueryBuilderClassNames;
  unstyled?: boolean;
  theme?: QueryBuilderTheme;
}

/**
 * Collapsible Split-View Workspace Dock rendered below QueryCanvas.
 * Allows viewing live Results, Charts, and SQL without navigating away from the visual builder.
 */
export const WorkspaceDock: React.FC<WorkspaceDockProps> = ({
  results,
  isLoading,
  currentSql,
  isOpen,
  onToggleOpen,
  dockTab,
  onSelectDockTab,
  onExpandFullTab,
  cellRenderers,
  classNames,
  unstyled = false,
  theme: _theme,
}) => {
  const [copied, setCopied] = useState(false);

  // If there are no results and not loading, keep dock dormant unless explicitly toggled
  if (!results && !isLoading && !isOpen) {
    return null;
  }

  const handleCopySql = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(currentSql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  const rowCount = results?.count ?? (results?.rows ? results.rows.length : null);

  if (unstyled) {
    return (
      <div data-qb="workspace-dock" aria-label="Workspace Dock">
        <div data-qb="workspace-dock-header">
          <button
            type="button"
            data-qb-dock-tab="results"
            onClick={() => onSelectDockTab("results")}
          >
            Results {rowCount !== null ? `(${rowCount})` : ""}
          </button>
          <button
            type="button"
            data-qb-dock-tab="chart"
            onClick={() => onSelectDockTab("chart")}
          >
            Chart
          </button>
          <button
            type="button"
            data-qb-dock-tab="sql"
            onClick={() => onSelectDockTab("sql")}
          >
            Live SQL
          </button>
          <button type="button" onClick={() => onExpandFullTab(dockTab)}>
            Full View
          </button>
          <button type="button" onClick={onToggleOpen}>
            {isOpen ? "Collapse" : "Expand"}
          </button>
        </div>
        {isOpen && (
          <div data-qb="workspace-dock-body">
            {dockTab === "results" && (
              <ResultsPanel
                results={results}
                isLoading={isLoading}
                unstyled={unstyled}
                cellRenderers={cellRenderers}
                classNames={classNames}
              />
            )}
            {dockTab === "chart" && <ChartPanel results={results} unstyled={unstyled} />}
            {dockTab === "sql" && (
              <div>
                <pre>{currentSql}</pre>
                <button type="button" onClick={handleCopySql}>
                  {copied ? "Copied" : "Copy SQL"}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      data-qb="workspace-dock"
      aria-label="Workspace Dock"
      style={{
        marginTop: "16px",
        background: "var(--qb-color-surface, rgba(15, 23, 42, 0.9))",
        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.12))",
        borderRadius: "var(--qb-radius-lg, 10px)",
        boxShadow: "0 10px 30px rgba(0, 0, 0, 0.35)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        transition: "all 0.2s ease",
      }}
    >
      {/* Dock Bar Header */}
      <div
        data-qb="workspace-dock-header"
        style={{
          padding: "8px 14px",
          background: "var(--qb-color-surface-hover, rgba(30, 41, 59, 0.95))",
          borderBottom: isOpen ? "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))" : "none",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "10px",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <span style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--qb-color-text, #f8fafc)", marginRight: "6px" }}>
            ⚡ Docked Workspace
          </span>

          <button
            type="button"
            data-qb-dock-tab="results"
            onClick={() => onSelectDockTab("results")}
            style={{
              background: dockTab === "results" ? "var(--qb-color-primary, #3b82f6)" : "transparent",
              color: dockTab === "results" ? "#ffffff" : "var(--qb-color-text-muted, #94a3b8)",
              border: "1px solid",
              borderColor: dockTab === "results" ? "var(--qb-color-primary, #3b82f6)" : "var(--qb-color-border, rgba(255, 255, 255, 0.1))",
              borderRadius: "var(--qb-radius-sm, 6px)",
              padding: "4px 10px",
              fontSize: "0.78rem",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            📊 Results {rowCount !== null ? `(${rowCount})` : ""}
          </button>

          <button
            type="button"
            data-qb-dock-tab="chart"
            onClick={() => onSelectDockTab("chart")}
            style={{
              background: dockTab === "chart" ? "var(--qb-color-accent, #8b5cf6)" : "transparent",
              color: dockTab === "chart" ? "#ffffff" : "var(--qb-color-text-muted, #94a3b8)",
              border: "1px solid",
              borderColor: dockTab === "chart" ? "var(--qb-color-accent, #8b5cf6)" : "var(--qb-color-border, rgba(255, 255, 255, 0.1))",
              borderRadius: "var(--qb-radius-sm, 6px)",
              padding: "4px 10px",
              fontSize: "0.78rem",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            📈 Visual Chart
          </button>

          <button
            type="button"
            data-qb-dock-tab="sql"
            onClick={() => onSelectDockTab("sql")}
            style={{
              background: dockTab === "sql" ? "var(--qb-color-secondary, #0ea5e9)" : "transparent",
              color: dockTab === "sql" ? "#ffffff" : "var(--qb-color-text-muted, #94a3b8)",
              border: "1px solid",
              borderColor: dockTab === "sql" ? "var(--qb-color-secondary, #0ea5e9)" : "var(--qb-color-border, rgba(255, 255, 255, 0.1))",
              borderRadius: "var(--qb-radius-sm, 6px)",
              padding: "4px 10px",
              fontSize: "0.78rem",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            📝 Live SQL
          </button>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <button
            type="button"
            data-qb="btn-dock-full-view"
            onClick={() => onExpandFullTab(dockTab)}
            style={{
              background: "transparent",
              color: "var(--qb-color-text-muted, #94a3b8)",
              border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
              borderRadius: "var(--qb-radius-sm, 4px)",
              padding: "3px 8px",
              fontSize: "0.72rem",
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
            title="Open in full screen tab"
          >
            ⤢ Full View
          </button>

          <button
            type="button"
            data-qb="btn-toggle-dock"
            onClick={onToggleOpen}
            style={{
              background: "transparent",
              color: "var(--qb-color-text-muted, #94a3b8)",
              border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
              borderRadius: "var(--qb-radius-sm, 4px)",
              padding: "3px 8px",
              fontSize: "0.72rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
            title={isOpen ? "Collapse dock" : "Expand dock"}
          >
            {isOpen ? "▾ Collapse" : "▴ Expand"}
          </button>
        </div>
      </div>

      {/* Dock Body */}
      {isOpen && (
        <div
          data-qb="workspace-dock-body"
          style={{
            maxHeight: "450px",
            overflowY: "auto",
            padding: "12px",
            background: "var(--qb-color-background, #0f172a)",
          }}
        >
          {dockTab === "results" && (
            <ResultsPanel
              results={results}
              isLoading={isLoading}
              unstyled={unstyled}
              cellRenderers={cellRenderers}
              classNames={classNames}
            />
          )}

          {dockTab === "chart" && <ChartPanel results={results} unstyled={unstyled} />}

          {dockTab === "sql" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button
                  type="button"
                  onClick={handleCopySql}
                  style={{
                    background: "rgba(59, 130, 246, 0.15)",
                    color: "var(--qb-color-primary, #60a5fa)",
                    border: "1px solid rgba(59, 130, 246, 0.35)",
                    borderRadius: "4px",
                    padding: "3px 10px",
                    fontSize: "0.75rem",
                    cursor: "pointer",
                    fontWeight: 600,
                  }}
                >
                  {copied ? "✓ Copied" : "Copy SQL"}
                </button>
              </div>
              <pre
                style={{
                  margin: 0,
                  padding: "12px",
                  background: "#090d16",
                  color: "#38bdf8",
                  borderRadius: "6px",
                  fontSize: "0.82rem",
                  fontFamily: "var(--qb-font-mono, monospace)",
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.5,
                }}
              >
                {currentSql}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
