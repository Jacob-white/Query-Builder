import React, { useMemo } from "react";
import type { CteSpec, QuerySpec } from "../types";
import { useTheme } from "../theme/ThemeProvider";

export interface PipelineDagCanvasProps {
  ctes: CteSpec[];
  onCtesChange: (ctes: CteSpec[]) => void;
  onSelectStage: (stageName: string | null) => void;
  selectedStage: string | null;
  finalQueryTable?: string;
  unstyled?: boolean;
  className?: string;
}

interface DagNode {
  name: string;
  isFinal: boolean;
  dependencies: string[];
  recursive?: boolean;
  materialized?: boolean;
}

export function detectCteCycles(nodes: { name: string; dependencies: string[] }[]): string[][] {
  const nodeMap = new Map<string, string[]>();
  nodes.forEach((n) => {
    nodeMap.set(n.name, n.dependencies);
  });

  const state = new Map<string, number>(); // 0: unvisited, 1: visiting, 2: visited
  const path: string[] = [];
  const cycles: string[][] = [];

  function dfs(curr: string) {
    state.set(curr, 1);
    path.push(curr);
    const deps = nodeMap.get(curr) || [];
    for (const dep of deps) {
      if (nodeMap.has(dep)) {
        if (state.get(dep) === 1) {
          const startIdx = path.indexOf(dep);
          cycles.push([...path.slice(startIdx), dep]);
        } else if (!state.has(dep) || state.get(dep) === 0) {
          dfs(dep);
        }
      }
    }
    path.pop();
    state.set(curr, 2);
  }

  nodes.forEach((n) => {
    if (!state.has(n.name) || state.get(n.name) === 0) {
      dfs(n.name);
    }
  });

  return cycles;
}

export const PipelineDagCanvas: React.FC<PipelineDagCanvasProps> = ({
  ctes,
  onCtesChange,
  onSelectStage,
  selectedStage,
  finalQueryTable = "Final Presentation Query",
  unstyled = false,
  className,
}) => {
  const { theme } = useTheme();

  // Extract dependency graph
  const dagNodes: DagNode[] = useMemo(() => {
    const list: DagNode[] = ctes.map((cte) => {
      const q = cte.query;
      const deps: string[] = [];
      if (q) {
        if (typeof q.table === "string" && q.table) {
          deps.push(q.table);
        }
        if (Array.isArray(q.joins)) {
          q.joins.forEach((j) => {
            if (typeof j?.table === "string" && j.table) {
              deps.push(j.table);
            }
          });
        }
      }
      return {
        name: cte.name,
        isFinal: false,
        dependencies: deps,
        recursive: cte.recursive,
        materialized: cte.materialized,
      };
    });

    // Final Query Node
    list.push({
      name: "Final Query",
      isFinal: true,
      dependencies: ctes.map((c) => c.name),
    });

    return list;
  }, [ctes]);

  // Cycle detection
  const cycles = useMemo(() => {
    return detectCteCycles(
      dagNodes.filter((n) => !n.isFinal).map((n) => ({
        name: n.name,
        dependencies: n.dependencies,
      }))
    );
  }, [dagNodes]);

  const handleAddStage = () => {
    let newIndex = ctes.length + 1;
    let candidateName = `stage_${newIndex}`;
    while (ctes.some((c) => c.name.toLowerCase() === candidateName.toLowerCase())) {
      newIndex++;
      candidateName = `stage_${newIndex}`;
    }

    const newCte: CteSpec = {
      name: candidateName,
      query: {
        table: (ctes[ctes.length - 1]?.name as any) || ("" as any),
        columns: ["*"],
        joins: [],
        filters: [],
        filter_join: "AND",
        order_by: [],
        distinct: false,
        limit: 50,
      } as unknown as QuerySpec,
    };

    const nextCtes = [...ctes, newCte];
    onCtesChange(nextCtes);
    onSelectStage(candidateName);
  };

  const handleRemoveStage = (stageName: string) => {
    const nextCtes = ctes.filter((c) => c.name !== stageName);
    onCtesChange(nextCtes);
    if (selectedStage === stageName) {
      onSelectStage(null);
    }
  };

  const handleToggleRecursive = (stageName: string) => {
    const nextCtes = ctes.map((c) => {
      if (c.name === stageName) {
        return { ...c, recursive: !c.recursive };
      }
      return c;
    });
    onCtesChange(nextCtes);
  };

  return (
    <div
      className={className}
      data-testid="pipeline-dag-canvas"
      style={
        unstyled
          ? undefined
          : {
              background: theme.colors.background || "#0f172a",
              color: theme.colors.text || "#f8fafc",
              border: `1px solid ${theme.colors.border || "#334155"}`,
              borderRadius: "8px",
              padding: "1.25rem",
              display: "flex",
              flexDirection: "column",
              gap: "1.25rem",
            }
      }
    >
      {/* Top Bar / Controls */}
      <div
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "0.75rem",
              }
        }
      >
        <div>
          <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 600 }}>
            CTE Pipeline DAG Canvas
          </h3>
          <p
            style={{
              margin: "0.25rem 0 0 0",
              fontSize: "0.8125rem",
              color: theme.colors.textMuted || "#94a3b8",
            }}
          >
            Multi-stage Common Table Expressions with automatic dependency detection and drill-down editing.
          </p>
        </div>

        <button
          type="button"
          onClick={handleAddStage}
          data-testid="add-stage-btn"
          style={
            unstyled
              ? undefined
              : {
                  padding: "0.5rem 1rem",
                  background: theme.colors.primary || "#38bdf8",
                  color: "#ffffff",
                  border: "none",
                  borderRadius: "6px",
                  fontSize: "0.875rem",
                  fontWeight: 600,
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "0.375rem",
                }
          }
        >
          + Add Pipeline Stage
        </button>
      </div>

      {/* Cycle Detection Warning Banner */}
      {cycles.length > 0 && (
        <div
          role="alert"
          data-testid="dag-cycle-alert"
          style={
            unstyled
              ? undefined
              : {
                  padding: "0.75rem 1rem",
                  background: "rgba(239, 68, 68, 0.15)",
                  border: "1px solid #ef4444",
                  borderRadius: "6px",
                  color: "#fca5a5",
                  fontSize: "0.875rem",
                }
          }
        >
          <strong>Warning: Circular Dependency Detected!</strong>
          <ul style={{ margin: "0.375rem 0 0 1rem", padding: 0 }}>
            {cycles.map((cyc, idx) => (
              <li key={idx}>{cyc.join(" ➔ ")}</li>
            ))}
          </ul>
        </div>
      )}

      {/* DAG Nodes Display */}
      <div
        data-testid="dag-nodes-container"
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                flexWrap: "wrap",
                alignItems: "stretch",
                gap: "1rem",
                padding: "0.5rem 0",
              }
        }
      >
        {dagNodes.map((node, index) => {
          const isSelected =
            node.isFinal ? selectedStage === null : selectedStage === node.name;

          return (
            <div
              key={node.name}
              data-testid={`dag-node-${node.name}`}
              onClick={() => onSelectStage(node.isFinal ? null : node.name)}
              style={
                unstyled
                  ? undefined
                  : {
                      flex: "1 1 240px",
                      maxWidth: "320px",
                      background: isSelected
                        ? "rgba(56, 189, 248, 0.12)"
                        : theme.colors.surface || "#1e293b",
                      border: `2px solid ${
                        isSelected
                          ? theme.colors.primary || "#38bdf8"
                          : theme.colors.border || "#334155"
                      }`,
                      borderRadius: "8px",
                      padding: "1rem",
                      cursor: "pointer",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "space-between",
                      transition: "all 0.15s ease",
                    }
              }
            >
              <div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: "0.5rem",
                  }}
                >
                  <span
                    style={{
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      padding: "0.125rem 0.5rem",
                      borderRadius: "9999px",
                      background: node.isFinal
                        ? "#10b981"
                        : theme.colors.primary || "#38bdf8",
                      color: "#ffffff",
                    }}
                  >
                    {node.isFinal ? "Output" : `Stage ${index + 1}`}
                  </span>

                  {!node.isFinal && (
                    <button
                      type="button"
                      aria-label={`Remove ${node.name}`}
                      data-testid={`remove-stage-${node.name}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRemoveStage(node.name);
                      }}
                      style={{
                        background: "transparent",
                        border: "none",
                        color: theme.colors.textMuted || "#94a3b8",
                        cursor: "pointer",
                        fontSize: "1.125rem",
                        lineHeight: 1,
                        padding: "0.25rem",
                      }}
                    >
                      ×
                    </button>
                  )}
                </div>

                <div
                  style={{
                    fontSize: "0.9375rem",
                    fontWeight: 600,
                    marginBottom: "0.25rem",
                  }}
                >
                  {node.name}
                </div>

                <div
                  style={{
                    fontSize: "0.75rem",
                    color: theme.colors.textMuted || "#94a3b8",
                  }}
                >
                  {node.isFinal ? (
                    <span>Root query targeting active canvas</span>
                  ) : (
                    <span>
                      Reads:{" "}
                      {node.dependencies.length > 0
                        ? node.dependencies.join(", ")
                        : "(none)"}
                    </span>
                  )}
                </div>
              </div>

              {!node.isFinal && (
                <div
                  style={{
                    marginTop: "0.75rem",
                    paddingTop: "0.5rem",
                    borderTop: `1px solid ${theme.colors.border || "#334155"}`,
                    display: "flex",
                    gap: "0.75rem",
                    fontSize: "0.75rem",
                  }}
                >
                  <label
                    onClick={(e) => e.stopPropagation()}
                    style={{ display: "flex", alignItems: "center", gap: "0.25rem", cursor: "pointer" }}
                  >
                    <input
                      type="checkbox"
                      checked={Boolean(node.recursive)}
                      onChange={() => handleToggleRecursive(node.name)}
                      data-testid={`toggle-recursive-${node.name}`}
                    />
                    Recursive
                  </label>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
