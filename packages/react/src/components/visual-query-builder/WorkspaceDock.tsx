import React, { useState } from "react";
import type { QueryResultData, QueryBuilderClassNames, SchemaSnapshot } from "../../types";
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
  onReorderColumns?: (newColumns: string[]) => void;
  schema?: SchemaSnapshot | null;
  onFilterByCell?: (
    column: string,
    value: unknown,
    operator: "=" | "!=" | "IS NULL" | "IS NOT NULL",
  ) => void;
  onDrillDownForeignKey?: (
    column: string,
    value: unknown,
    targetTable?: string,
    targetColumn?: string,
  ) => void;
  onPinToDashboard?: () => void;
  cellRenderers?: Record<string, CellRenderer>;
  classNames?: QueryBuilderClassNames;
  unstyled?: boolean;
  theme?: QueryBuilderTheme;
  studioMode?: boolean;
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
  onReorderColumns,
  schema,
  onFilterByCell,
  onDrillDownForeignKey,
  onPinToDashboard,
  cellRenderers,
  classNames,
  unstyled = false,
  theme: _theme,
  studioMode = false,
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
                onReorderColumns={onReorderColumns}
                schema={schema}
                onFilterByCell={onFilterByCell}
                onDrillDownForeignKey={onDrillDownForeignKey}
                onPinToDashboard={onPinToDashboard}
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

  const srOnlyStyle: React.CSSProperties = {
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

  const getDockTabStyle = (active: boolean): React.CSSProperties => ({
    background: active ? "var(--qb-color-surface-active, rgba(255, 255, 255, 0.1))" : "transparent",
    color: active ? "var(--qb-color-text, #f8fafc)" : "var(--qb-color-text-muted, #94a3b8)",
    border: "1px solid",
    borderColor: active
      ? "var(--qb-color-border, rgba(255, 255, 255, 0.14))"
      : "transparent",
    borderRadius: "var(--qb-radius-sm, 6px)",
    padding: "5px 12px",
    fontSize: "0.85rem",
    fontWeight: active ? 600 : 500,
    cursor: "pointer",
    transition: "all 0.15s ease",
  });

  const isSeamlessResults = !studioMode && isOpen && dockTab === "results";

  return (
    <div
      data-qb="workspace-dock"
      aria-label="Workspace Dock"
      style={
        isSeamlessResults
          ? {
              marginTop: "14px",
              display: "flex",
              flexDirection: "column",
            }
          : {
              marginTop: "14px",
              background: "var(--qb-color-surface, #10141f)",
              border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
              borderRadius: "var(--qb-radius-md, 8px)",
              boxShadow: "var(--qb-shadow-md, 0 4px 12px rgba(0, 0, 0, 0.25))",
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
              transition: "all 0.2s ease",
            }
      }
    >
      {/* Dock Bar Header (visually hidden when showing results directly so top TabBar isn't duplicated) */}
      <div
        data-qb="workspace-dock-header"
        style={
          isSeamlessResults
            ? srOnlyStyle
            : {
                padding: "9px 14px",
                background: "var(--qb-color-surface-hover, rgba(22, 27, 40, 0.85))",
                borderBottom: isOpen ? "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.07))" : "none",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "10px",
                flexWrap: "wrap",
              }
        }
      >
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <span style={srOnlyStyle}>⚡ Docked Workspace</span>

          <button
            type="button"
            data-qb-dock-tab="results"
            onClick={() => onSelectDockTab("results")}
            style={getDockTabStyle(dockTab === "results")}
          >
            <span style={srOnlyStyle}>
              {`📊 Results ${rowCount !== null ? `(${rowCount})` : ""}`}
            </span>
            <span aria-hidden="true">
              {`Results ${rowCount !== null ? `(${rowCount})` : ""}`}
            </span>
          </button>

          <button
            type="button"
            data-qb-dock-tab="chart"
            onClick={() => onSelectDockTab("chart")}
            style={getDockTabStyle(dockTab === "chart")}
          >
            <span style={srOnlyStyle}>📈 Visual Chart</span>
            <span aria-hidden="true">Chart</span>
          </button>

          <button
            type="button"
            data-qb-dock-tab="sql"
            onClick={() => onSelectDockTab("sql")}
            style={getDockTabStyle(dockTab === "sql")}
          >
            <span style={srOnlyStyle}>📝 Live SQL</span>
            <span aria-hidden="true">SQL</span>
          </button>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <button
            type="button"
            data-qb="btn-dock-full-view"
            onClick={() => onExpandFullTab(dockTab)}
            style={{
              background: "transparent",
              color: "var(--qb-color-text-muted, #94a3b8)",
              border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
              borderRadius: "var(--qb-radius-sm, 6px)",
              padding: "5px 10px",
              fontSize: "0.82rem",
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
            title="Open in full screen tab"
          >
            <span style={srOnlyStyle}>⤢ Full View</span>
            <span aria-hidden="true">Full View</span>
          </button>

          <button
            type="button"
            data-qb="btn-toggle-dock"
            onClick={onToggleOpen}
            style={{
              background: "transparent",
              color: "var(--qb-color-text-muted, #94a3b8)",
              border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
              borderRadius: "var(--qb-radius-sm, 6px)",
              padding: "5px 10px",
              fontSize: "0.82rem",
              fontWeight: 500,
              cursor: "pointer",
            }}
            title={isOpen ? "Collapse dock" : "Expand dock"}
          >
            <span style={srOnlyStyle}>{isOpen ? "▾ Collapse" : "▴ Expand"}</span>
            <span aria-hidden="true">{isOpen ? "Collapse" : "Expand"}</span>
          </button>
        </div>
      </div>

      {/* Dock Body */}
      {isOpen && (
        <div
          data-qb="workspace-dock-body"
          style={
            isSeamlessResults
              ? {
                  padding: 0,
                  background: "transparent",
                }
              : {
                  maxHeight: "460px",
                  overflowY: "auto",
                  padding: "14px",
                  background: "var(--qb-color-background, #090d16)",
                }
          }
        >
          {dockTab === "results" && (
            <ResultsPanel
              results={results}
              isLoading={isLoading}
              unstyled={unstyled}
              onReorderColumns={onReorderColumns}
              schema={schema}
              onFilterByCell={onFilterByCell}
              onDrillDownForeignKey={onDrillDownForeignKey}
              onPinToDashboard={onPinToDashboard}
              cellRenderers={cellRenderers}
              classNames={classNames}
            />
          )}

          {dockTab === "chart" && <ChartPanel results={results} unstyled={unstyled} />}

          {dockTab === "sql" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button
                  type="button"
                  onClick={handleCopySql}
                  style={{
                    background: "var(--qb-color-surface-hover, rgba(255, 255, 255, 0.05))",
                    color: "var(--qb-color-text, #e2e8f0)",
                    border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                    borderRadius: "6px",
                    padding: "5px 12px",
                    fontSize: "0.84rem",
                    cursor: "pointer",
                    fontWeight: 500,
                  }}
                >
                  {copied ? "✓ Copied" : "Copy SQL"}
                </button>
              </div>
              <pre
                style={{
                  margin: 0,
                  padding: "14px",
                  background: "var(--qb-color-surface, #10141f)",
                  color: "var(--qb-color-text, #e2e8f0)",
                  border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                  borderRadius: "6px",
                  fontSize: "0.875rem",
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
