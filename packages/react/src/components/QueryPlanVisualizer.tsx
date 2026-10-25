import React, { useState, useMemo, useEffect } from "react";
import type { QueryPlanNode } from "../types";
import { useTheme } from "../theme/ThemeProvider";

export interface QueryPlanVisualizerProps {
  /** The standardized QueryPlanNode root hierarchy. */
  plan: QueryPlanNode;
  /** Optional raw vendor explain payload (Postgres, SQLite, MySQL JSON). */
  rawPlan?: unknown;
  /** Callback fired when a node in the tree is clicked. */
  onNodeSelect?: (node: QueryPlanNode) => void;
  /** Optional container class name. */
  className?: string;
  /** Whether to bypass default utility styles. */
  unstyled?: boolean;
}

type ActiveTab = "tree" | "insights" | "raw";

function getCostColorBadge(percentage: number): {
  bg: string;
  text: string;
  border: string;
  dot: string;
  label: string;
} {
  if (percentage >= 30) {
    return {
      bg: "#fef2f2",
      text: "#991b1b",
      border: "#fecaca",
      dot: "#ef4444",
      label: "High Cost Bottleneck",
    };
  }
  if (percentage >= 10) {
    return {
      bg: "#fffbeb",
      text: "#92400e",
      border: "#fde68a",
      dot: "#f59e0b",
      label: "Moderate Cost",
    };
  }
  return {
    bg: "#f0fdf4",
    text: "#166534",
    border: "#bbf7d0",
    dot: "#10b981",
    label: "Optimal Cost",
  };
}

function collectAllWarnings(node: QueryPlanNode): { nodeType: string; table?: string; warning: string }[] {
  const result: { nodeType: string; table?: string; warning: string }[] = [];
  if (node.warnings && node.warnings.length > 0) {
    for (const w of node.warnings) {
      result.push({ nodeType: node.node_type, table: node.table, warning: w });
    }
  }
  if (node.children && node.children.length > 0) {
    for (const child of node.children) {
      result.push(...collectAllWarnings(child));
    }
  }
  return result;
}

interface PlanTreeNodeProps {
  node: QueryPlanNode;
  depth?: number;
  selectedNode: QueryPlanNode | null;
  onSelect: (node: QueryPlanNode) => void;
  unstyled?: boolean;
}

const PlanTreeNode: React.FC<PlanTreeNodeProps> = ({
  node,
  depth = 0,
  selectedNode,
  onSelect,
  unstyled = false,
}) => {
  const [isExpanded, setIsExpanded] = useState<boolean>(true);
  const costPct = node.cost_percentage ?? 0;
  const badge = getCostColorBadge(costPct);
  const isSelected = selectedNode === node;
  const hasChildren = node.children && node.children.length > 0;
  const hasWarnings = node.warnings && node.warnings.length > 0;
  const s = (st: React.CSSProperties): React.CSSProperties | undefined =>
    unstyled ? undefined : st;

  return (
    <div
      style={s({ marginLeft: depth > 0 ? "18px" : "0px", marginTop: "8px" })}
      data-testid={`plan-node-${node.node_type}`}
    >
      <div
        onClick={() => onSelect(node)}
        style={s({
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "8px 12px",
          borderRadius: "6px",
          backgroundColor: isSelected
            ? "var(--qb-color-surface-hover, rgba(59, 130, 246, 0.12))"
            : "var(--qb-color-surface, #ffffff)",
          border: isSelected
            ? "1px solid #3b82f6"
            : "1px solid var(--qb-color-border, #e2e8f0)",
          cursor: "pointer",
          transition: "all 0.15s ease",
          boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
        })}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setIsExpanded(!isExpanded);
            }}
            style={s({
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "2px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--qb-color-text-muted, #64748b)",
            })}
            aria-label={isExpanded ? "Collapse node" : "Expand node"}
          >
            <span
              style={s({
                transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)",
                display: "inline-block",
                transition: "transform 0.15s",
              })}
            >
              ▶
            </span>
          </button>
        ) : (
          <span
            style={s({
              width: "16px",
              display: "inline-block",
              color: "var(--qb-color-text-muted, #64748b)",
            })}
          >
            •
          </span>
        )}

        <div
          style={s({
            display: "flex",
            alignItems: "center",
            gap: "6px",
            flexGrow: 1,
            flexWrap: "wrap",
          })}
        >
          <strong style={s({ fontSize: "14px", color: "var(--qb-color-text, #0f172a)" })}>
            {node.node_type}
          </strong>
          {node.table && (
            <span
              style={s({
                fontSize: "12px",
                color: "var(--qb-color-text-muted, #64748b)",
                backgroundColor: "var(--qb-color-background, #f8fafc)",
                padding: "2px 6px",
                borderRadius: "4px",
              })}
            >
              on <code>{node.table}</code>
            </span>
          )}
          {node.index_name && (
            <span
              style={s({
                fontSize: "11px",
                color: "#1d4ed8",
                backgroundColor: "#dbeafe",
                padding: "2px 6px",
                borderRadius: "4px",
              })}
            >
              index: {node.index_name}
            </span>
          )}
          {hasWarnings && (
            <span
              title={node.warnings?.join("\n")}
              style={s({
                fontSize: "11px",
                color: "#b45309",
                backgroundColor: "#fef3c7",
                padding: "2px 6px",
                borderRadius: "4px",
                fontWeight: 600,
              })}
            >
              ⚠️ {node.warnings?.length} {node.warnings?.length === 1 ? "warning" : "warnings"}
            </span>
          )}
        </div>

        {/* Cost Badge */}
        <div
          style={s({
            display: "flex",
            alignItems: "center",
            gap: "5px",
            backgroundColor: badge.bg,
            color: badge.text,
            border: `1px solid ${badge.border}`,
            padding: "2px 8px",
            borderRadius: "9999px",
            fontSize: "12px",
            fontWeight: 600,
          })}
          title={badge.label}
        >
          <span
            style={s({
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              backgroundColor: badge.dot,
            })}
          />
          <span>{costPct.toFixed(1)}% cost</span>
        </div>

        <div
          style={s({
            fontSize: "12px",
            color: "var(--qb-color-text-muted, #64748b)",
            minWidth: "90px",
            textAlign: "right",
          })}
        >
          est. {node.rows_estimated?.toLocaleString() ?? 0} rows
        </div>
      </div>

      {/* Predicate detail preview if selected or present */}
      {node.filter_predicate && (
        <div
          style={s({
            marginLeft: "28px",
            marginTop: "4px",
            fontSize: "11px",
            color: "var(--qb-color-text-muted, #64748b)",
          })}
        >
          <span style={s({ fontWeight: 600 })}>Filter:</span> <code>{node.filter_predicate}</code>
        </div>
      )}

      {/* Children */}
      {hasChildren && isExpanded && (
        <div
          style={s({
            borderLeft: "2px dashed var(--qb-color-border, #e2e8f0)",
            marginLeft: "14px",
            paddingLeft: "4px",
          })}
        >
          {node.children!.map((child, idx) => (
            <PlanTreeNode
              key={`${child.node_type}-${child.table ?? idx}`}
              node={child}
              depth={depth + 1}
              selectedNode={selectedNode}
              onSelect={onSelect}
              unstyled={unstyled}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export const QueryPlanVisualizer: React.FC<QueryPlanVisualizerProps> = ({
  plan,
  rawPlan,
  onNodeSelect,
  className = "",
  unstyled = false,
}) => {
  const { cssVariables } = useTheme();
  const [activeTab, setActiveTab] = useState<ActiveTab>("tree");
  const [selectedNode, setSelectedNode] = useState<QueryPlanNode | null>(null);
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const allWarnings = useMemo(() => collectAllWarnings(plan), [plan]);

  const handleNodeClick = (node: QueryPlanNode) => {
    setSelectedNode(node);
    onNodeSelect?.(node);
  };

  const handleCopyJson = () => {
    const dataToCopy = rawPlan || plan;
    navigator.clipboard.writeText(JSON.stringify(dataToCopy, null, 2)).then(() => {
      setCopied(true);
    });
  };

  const s = (st: React.CSSProperties): React.CSSProperties | undefined =>
    unstyled ? undefined : st;

  const baseContainerStyle: React.CSSProperties | undefined = s({
    ...(cssVariables as React.CSSProperties),
    border: "1px solid var(--qb-color-border, #e2e8f0)",
    borderRadius: "8px",
    backgroundColor: "var(--qb-color-background, #f8fafc)",
    color: "var(--qb-color-text, #0f172a)",
    padding: "16px",
    fontFamily: "system-ui, -apple-system, sans-serif",
  });

  return (
    <div className={`qb-plan-visualizer ${className}`} style={baseContainerStyle}>
      {/* Header & Tabs */}
      <div
        style={s({
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderBottom: "1px solid var(--qb-color-border, #e2e8f0)",
          paddingBottom: "12px",
          marginBottom: "16px",
          flexWrap: "wrap",
          gap: "8px",
        })}
      >
        <div style={s({ display: "flex", alignItems: "center", gap: "10px" })}>
          <h3
            style={s({
              margin: 0,
              fontSize: "16px",
              fontWeight: 700,
              color: "var(--qb-color-text, #0f172a)",
            })}
          >
            Visual Query Execution Plan
          </h3>
          {allWarnings.length > 0 && (
            <span
              style={s({
                backgroundColor: "#fef3c7",
                color: "#b45309",
                border: "1px solid #fde68a",
                borderRadius: "9999px",
                padding: "2px 8px",
                fontSize: "12px",
                fontWeight: 600,
              })}
            >
              ⚠️ {allWarnings.length} {allWarnings.length === 1 ? "advisory hint" : "advisory hints"}
            </span>
          )}
        </div>

        <div style={s({ display: "flex", gap: "4px" })}>
          <button
            type="button"
            onClick={() => setActiveTab("tree")}
            style={s({
              padding: "6px 12px",
              borderRadius: "6px",
              fontSize: "13px",
              fontWeight: 500,
              cursor: "pointer",
              border:
                activeTab === "tree"
                  ? "1px solid #3b82f6"
                  : "1px solid var(--qb-color-border, #e2e8f0)",
              backgroundColor:
                activeTab === "tree" ? "#3b82f6" : "var(--qb-color-surface, #ffffff)",
              color: activeTab === "tree" ? "#ffffff" : "var(--qb-color-text, #0f172a)",
            })}
          >
            Visual Tree
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("insights")}
            style={s({
              padding: "6px 12px",
              borderRadius: "6px",
              fontSize: "13px",
              fontWeight: 500,
              cursor: "pointer",
              border:
                activeTab === "insights"
                  ? "1px solid #3b82f6"
                  : "1px solid var(--qb-color-border, #e2e8f0)",
              backgroundColor:
                activeTab === "insights" ? "#3b82f6" : "var(--qb-color-surface, #ffffff)",
              color: activeTab === "insights" ? "#ffffff" : "var(--qb-color-text, #0f172a)",
            })}
          >
            Optimization Insights ({allWarnings.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("raw")}
            style={s({
              padding: "6px 12px",
              borderRadius: "6px",
              fontSize: "13px",
              fontWeight: 500,
              cursor: "pointer",
              border:
                activeTab === "raw"
                  ? "1px solid #3b82f6"
                  : "1px solid var(--qb-color-border, #e2e8f0)",
              backgroundColor:
                activeTab === "raw" ? "#3b82f6" : "var(--qb-color-surface, #ffffff)",
              color: activeTab === "raw" ? "#ffffff" : "var(--qb-color-text, #0f172a)",
            })}
          >
            Raw Plan
          </button>
        </div>
      </div>

      {/* Tab 1: Visual Tree */}
      {activeTab === "tree" && (
        <div>
          {/* Legend */}
          <div
            style={s({
              display: "flex",
              gap: "12px",
              marginBottom: "12px",
              fontSize: "11px",
              color: "var(--qb-color-text-muted, #64748b)",
            })}
          >
            <span style={s({ display: "flex", alignItems: "center", gap: "4px" })}>
              <span
                style={s({
                  width: "8px",
                  height: "8px",
                  borderRadius: "50%",
                  backgroundColor: "#10b981",
                })}
              />
              Optimal (&lt;10%)
            </span>
            <span style={s({ display: "flex", alignItems: "center", gap: "4px" })}>
              <span
                style={s({
                  width: "8px",
                  height: "8px",
                  borderRadius: "50%",
                  backgroundColor: "#f59e0b",
                })}
              />
              Moderate (10%–30%)
            </span>
            <span style={s({ display: "flex", alignItems: "center", gap: "4px" })}>
              <span
                style={s({
                  width: "8px",
                  height: "8px",
                  borderRadius: "50%",
                  backgroundColor: "#ef4444",
                })}
              />
              Bottleneck (&gt;30%)
            </span>
          </div>

          <div
            style={s({
              backgroundColor: "var(--qb-color-surface, #ffffff)",
              border: "1px solid var(--qb-color-border, #e2e8f0)",
              borderRadius: "6px",
              padding: "16px",
              maxHeight: "450px",
              overflowY: "auto",
            })}
          >
            <PlanTreeNode
              node={plan}
              depth={0}
              selectedNode={selectedNode}
              onSelect={handleNodeClick}
              unstyled={unstyled}
            />
          </div>

          {/* Selected Node Details Drawer */}
          {selectedNode && (
            <div
              style={s({
                marginTop: "14px",
                padding: "12px",
                borderRadius: "6px",
                backgroundColor: "var(--qb-color-background, #f8fafc)",
                border: "1px solid var(--qb-color-border, #e2e8f0)",
              })}
            >
              <div
                style={s({
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                })}
              >
                <strong style={s({ fontSize: "13px", color: "var(--qb-color-text, #0f172a)" })}>
                  Selected Node: {selectedNode.node_type}
                </strong>
                <button
                  type="button"
                  onClick={() => setSelectedNode(null)}
                  style={s({
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "var(--qb-color-text-muted, #64748b)",
                  })}
                >
                  ✕
                </button>
              </div>
              <div
                style={s({
                  marginTop: "6px",
                  fontSize: "12px",
                  color: "var(--qb-color-text, #0f172a)",
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                  gap: "6px",
                })}
              >
                <div><strong>Cost Estimate:</strong> {selectedNode.cost_estimate ?? 0}</div>
                <div><strong>Cost Ratio:</strong> {selectedNode.cost_percentage ?? 0}%</div>
                <div><strong>Est. Rows:</strong> {selectedNode.rows_estimated?.toLocaleString() ?? 0}</div>
                {selectedNode.actual_time_ms != null && <div><strong>Actual Time:</strong> {selectedNode.actual_time_ms} ms</div>}
                {selectedNode.rows_actual != null && <div><strong>Actual Rows:</strong> {selectedNode.rows_actual.toLocaleString()}</div>}
                {selectedNode.table && <div><strong>Target Table:</strong> {selectedNode.table}</div>}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Optimization Insights */}
      {activeTab === "insights" && (
        <div style={s({ display: "flex", flexDirection: "column", gap: "10px" })}>
          {allWarnings.length === 0 ? (
            <div
              style={s({
                padding: "24px",
                textAlign: "center",
                backgroundColor: "var(--qb-color-surface, #ffffff)",
                borderRadius: "6px",
                border: "1px solid var(--qb-color-border, #e2e8f0)",
                color: "#166534",
              })}
            >
              <div style={s({ fontSize: "24px", marginBottom: "6px" })}>✅</div>
              <strong style={s({ fontSize: "14px" })}>Optimal Plan Efficiency</strong>
              <p
                style={s({
                  margin: "4px 0 0 0",
                  fontSize: "12px",
                  color: "var(--qb-color-text-muted, #64748b)",
                })}
              >
                All query nodes operate within normal cost bounds. No table scan or missing index bottlenecks detected.
              </p>
            </div>
          ) : (
            allWarnings.map((item, idx) => (
              <div
                key={idx}
                style={s({
                  padding: "12px 16px",
                  borderRadius: "6px",
                  backgroundColor: "var(--qb-color-surface, #ffffff)",
                  border: "1px solid var(--qb-color-suggested-border, #fde68a)",
                  borderLeft: "4px solid #f59e0b",
                  display: "flex",
                  gap: "12px",
                  alignItems: "flex-start",
                })}
              >
                <span style={s({ fontSize: "18px" })}>⚠️</span>
                <div>
                  <div style={s({ fontSize: "13px", fontWeight: 600, color: "var(--qb-color-suggested-text, #b45309)" })}>
                    {item.nodeType} {item.table ? `on ${item.table}` : ""}
                  </div>
                  <div
                    style={s({
                      fontSize: "12px",
                      color: "var(--qb-color-text, #0f172a)",
                      marginTop: "2px",
                    })}
                  >
                    {item.warning}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Tab 3: Raw Plan */}
      {activeTab === "raw" && (
        <div>
          <div style={s({ display: "flex", justifyContent: "flex-end", marginBottom: "8px" })}>
            <button
              type="button"
              onClick={handleCopyJson}
              style={s({
                padding: "4px 10px",
                fontSize: "12px",
                borderRadius: "4px",
                border: "1px solid var(--qb-color-border, #e2e8f0)",
                backgroundColor: "var(--qb-color-surface, #ffffff)",
                cursor: "pointer",
                color: copied ? "#10b981" : "var(--qb-color-text, #0f172a)",
              })}
            >
              {copied ? "✓ Copied!" : "Copy JSON"}
            </button>
          </div>
          <pre
            style={s({
              backgroundColor: "var(--qb-color-surface, #1e293b)",
              color: "var(--qb-color-text, #f8fafc)",
              border: "1px solid var(--qb-color-border, #334155)",
              padding: "14px",
              borderRadius: "6px",
              fontSize: "12px",
              lineHeight: 1.5,
              overflowX: "auto",
              maxHeight: "400px",
            })}
          >
            <code>{JSON.stringify(rawPlan || plan, null, 2)}</code>
          </pre>
        </div>
      )}
    </div>
  );
};
