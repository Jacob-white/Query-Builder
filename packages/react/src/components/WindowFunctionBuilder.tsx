import React, { useState, useMemo, useEffect } from "react";
import type { WindowFunctionSpec } from "../types";
import { useTheme } from "../theme/ThemeProvider";

export const SUPPORTED_WINDOW_FUNCTIONS = [
  "ROW_NUMBER",
  "RANK",
  "DENSE_RANK",
  "PERCENT_RANK",
  "CUME_DIST",
  "NTILE",
  "LEAD",
  "LAG",
  "FIRST_VALUE",
  "LAST_VALUE",
  "NTH_VALUE",
  "COUNT",
  "SUM",
  "AVG",
  "MIN",
  "MAX",
] as const;

export interface WindowFunctionBuilderProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (spec: WindowFunctionSpec) => void;
  availableColumns: { table?: string; name: string }[];
  initialSpec?: Partial<WindowFunctionSpec>;
  unstyled?: boolean;
  className?: string;
}

export const WindowFunctionBuilder: React.FC<WindowFunctionBuilderProps> = ({
  isOpen,
  onClose,
  onSave,
  availableColumns,
  initialSpec,
  unstyled = false,
  className,
}) => {
  const { theme } = useTheme();

  const [func, setFunc] = useState<string>(initialSpec?.function || "ROW_NUMBER");
  const [argColumn, setArgColumn] = useState<string>(
    initialSpec?.arguments?.[0] ? String(initialSpec.arguments[0]) : ""
  );
  const [partitionBy, setPartitionBy] = useState<string[]>(
    initialSpec?.partition_by || []
  );
  const [orderByCol, setOrderByCol] = useState<string>(
    initialSpec?.order_by?.[0]?.column || ""
  );
  const [orderDir, setOrderDir] = useState<"ASC" | "DESC">(
    initialSpec?.order_by?.[0]?.direction || "ASC"
  );
  const [enableFrame, setEnableFrame] = useState<boolean>(Boolean(initialSpec?.frame));
  const [frameType, setFrameType] = useState<"ROWS" | "RANGE" | "GROUPS">(
    initialSpec?.frame?.frame_type || "ROWS"
  );
  const [frameStart, setFrameStart] = useState<string>(
    initialSpec?.frame?.start || "UNBOUNDED PRECEDING"
  );
  const [frameEnd, setFrameEnd] = useState<string>(
    initialSpec?.frame?.end || "CURRENT ROW"
  );
  const [exclusion, setExclusion] = useState<string>(
    initialSpec?.frame?.exclusion || "NONE"
  );
  const [alias, setAlias] = useState<string>(initialSpec?.alias || "");

  const handleTogglePartition = (colKey: string) => {
    setPartitionBy((prev) =>
      prev.includes(colKey) ? prev.filter((c) => c !== colKey) : [...prev, colKey]
    );
  };

  const generatedPreview = useMemo(() => {
    const argsStr = argColumn ? argColumn : func === "COUNT" ? "*" : "";
    const partClause =
      partitionBy.length > 0 ? `PARTITION BY ${partitionBy.join(", ")}` : "";
    const orderClause = orderByCol ? `ORDER BY ${orderByCol} ${orderDir}` : "";
    let frameClause = "";
    if (enableFrame) {
      frameClause = `${frameType} BETWEEN ${frameStart} AND ${frameEnd}`;
      if (exclusion && exclusion !== "NONE") {
        frameClause += ` EXCLUDE ${exclusion}`;
      }
    }
    const overTokens = [partClause, orderClause, frameClause].filter(Boolean);
    const overClause = `OVER (${overTokens.join(" ")})`;
    const aliasClause = alias ? ` AS ${alias}` : "";
    return `${func}(${argsStr}) ${overClause}${aliasClause}`;
  }, [func, argColumn, partitionBy, orderByCol, orderDir, enableFrame, frameType, frameStart, frameEnd, exclusion, alias]);

  const handleSave = () => {
    const spec: WindowFunctionSpec = {
      function: func,
      arguments: argColumn ? [argColumn] : [],
      partition_by: partitionBy,
      order_by: orderByCol ? [{ column: orderByCol, direction: orderDir }] : [],
      alias: alias.trim() || undefined,
    };
    if (enableFrame) {
      spec.frame = {
        frame_type: frameType,
        start: frameStart,
        end: frameEnd,
        exclusion: exclusion !== "NONE" ? exclusion : undefined,
      };
    }
    onSave(spec);
    onClose();
  };

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="wf-dialog-title"
      className={className}
      data-testid="window-function-builder-modal"
      style={
        unstyled
          ? undefined
          : {
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: "rgba(0, 0, 0, 0.6)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 10000,
              padding: "1rem",
            }
      }
    >
      <div
        style={
          unstyled
            ? undefined
            : {
                background: theme.colors.surface || "#1e293b",
                color: theme.colors.text || "#f8fafc",
                borderRadius: "8px",
                width: "100%",
                maxWidth: "600px",
                maxHeight: "90vh",
                overflowY: "auto",
                border: `1px solid ${theme.colors.border || "#334155"}`,
                boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
                display: "flex",
                flexDirection: "column",
              }
        }
      >
        {/* Header */}
        <div
          style={
            unstyled
              ? undefined
              : {
                  padding: "1rem 1.25rem",
                  borderBottom: `1px solid ${theme.colors.border || "#334155"}`,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }
          }
        >
          <h2
            id="wf-dialog-title"
            style={
              unstyled
                ? undefined
                : {
                    margin: 0,
                    fontSize: "1.125rem",
                    fontWeight: 600,
                  }
            }
          >
            Window Function Builder
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            data-testid="wf-close-btn"
            style={
              unstyled
                ? undefined
                : {
                    background: "transparent",
                    border: "none",
                    color: theme.colors.textMuted || "#94a3b8",
                    cursor: "pointer",
                    fontSize: "1.25rem",
                    lineHeight: 1,
                  }
            }
          >
            ×
          </button>
        </div>

        {/* Content Body */}
        <div
          style={
            unstyled
              ? undefined
              : {
                  padding: "1.25rem",
                  display: "flex",
                  flexDirection: "column",
                  gap: "1rem",
                }
          }
        >
          {/* Function Selector */}
          <div>
            <label
              htmlFor="wf-func-select"
              style={{ display: "block", marginBottom: "0.375rem", fontSize: "0.875rem", fontWeight: 500 }}
            >
              Function
            </label>
            <select
              id="wf-func-select"
              data-testid="wf-function-select"
              value={func}
              onChange={(e) => setFunc(e.target.value)}
              style={
                unstyled
                  ? undefined
                  : {
                      width: "100%",
                      padding: "0.5rem 0.75rem",
                      background: theme.colors.background || "#0f172a",
                      color: theme.colors.text || "#f8fafc",
                      border: `1px solid ${theme.colors.border || "#334155"}`,
                      borderRadius: "6px",
                    }
              }
            >
              {SUPPORTED_WINDOW_FUNCTIONS.map((fn) => (
                <option key={fn} value={fn}>
                  {fn}
                </option>
              ))}
            </select>
          </div>

          {/* Argument Column (if applicable) */}
          {func !== "ROW_NUMBER" && func !== "RANK" && func !== "DENSE_RANK" && (
            <div>
              <label
                htmlFor="wf-arg-select"
                style={{ display: "block", marginBottom: "0.375rem", fontSize: "0.875rem", fontWeight: 500 }}
              >
                Target Column
              </label>
              <select
                id="wf-arg-select"
                data-testid="wf-arg-select"
                value={argColumn}
                onChange={(e) => setArgColumn(e.target.value)}
                style={
                  unstyled
                    ? undefined
                    : {
                        width: "100%",
                        padding: "0.5rem 0.75rem",
                        background: theme.colors.background || "#0f172a",
                        color: theme.colors.text || "#f8fafc",
                        border: `1px solid ${theme.colors.border || "#334155"}`,
                        borderRadius: "6px",
                      }
                }
              >
                <option value="">(None / Default)</option>
                {availableColumns.map((col) => {
                  const key = col.table ? `${col.table}.${col.name}` : col.name;
                  return (
                    <option key={key} value={key}>
                      {key}
                    </option>
                  );
                })}
              </select>
            </div>
          )}

          {/* Partition By */}
          <div>
            <span
              id="wf-partition-label"
              style={{ display: "block", marginBottom: "0.375rem", fontSize: "0.875rem", fontWeight: 500 }}
            >
              Partition By (Groupings)
            </span>
            <div
              role="group"
              aria-labelledby="wf-partition-label"
              style={
                unstyled
                  ? undefined
                  : {
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "0.5rem",
                      maxHeight: "120px",
                      overflowY: "auto",
                      padding: "0.5rem",
                      border: `1px solid ${theme.colors.border || "#334155"}`,
                      borderRadius: "6px",
                    }
              }
            >
              {availableColumns.length === 0 ? (
                <span style={{ fontSize: "0.8125rem", color: theme.colors.textMuted }}>
                  No columns available
                </span>
              ) : (
                availableColumns.map((col) => {
                  const key = col.table ? `${col.table}.${col.name}` : col.name;
                  const isChecked = partitionBy.includes(key);
                  return (
                    <label
                      key={key}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.25rem",
                        fontSize: "0.8125rem",
                        cursor: "pointer",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => handleTogglePartition(key)}
                        data-testid={`wf-part-${key}`}
                      />
                      {key}
                    </label>
                  );
                })
              )}
            </div>
          </div>

          {/* Order By */}
          <div>
            <label
              htmlFor="wf-order-select"
              style={{ display: "block", marginBottom: "0.375rem", fontSize: "0.875rem", fontWeight: 500 }}
            >
              Order By
            </label>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <select
                id="wf-order-select"
                data-testid="wf-order-col-select"
                value={orderByCol}
                onChange={(e) => setOrderByCol(e.target.value)}
                style={
                  unstyled
                    ? undefined
                    : {
                        flex: 1,
                        padding: "0.5rem 0.75rem",
                        background: theme.colors.background || "#0f172a",
                        color: theme.colors.text || "#f8fafc",
                        border: `1px solid ${theme.colors.border || "#334155"}`,
                        borderRadius: "6px",
                      }
                }
              >
                <option value="">(None)</option>
                {availableColumns.map((col) => {
                  const key = col.table ? `${col.table}.${col.name}` : col.name;
                  return (
                    <option key={key} value={key}>
                      {key}
                    </option>
                  );
                })}
              </select>
              <select
                aria-label="Order direction"
                data-testid="wf-order-dir-select"
                value={orderDir}
                onChange={(e) => setOrderDir(e.target.value as "ASC" | "DESC")}
                style={
                  unstyled
                    ? undefined
                    : {
                        width: "90px",
                        padding: "0.5rem 0.75rem",
                        background: theme.colors.background || "#0f172a",
                        color: theme.colors.text || "#f8fafc",
                        border: `1px solid ${theme.colors.border || "#334155"}`,
                        borderRadius: "6px",
                      }
                }
              >
                <option value="ASC">ASC</option>
                <option value="DESC">DESC</option>
              </select>
            </div>
          </div>

          {/* Frame Boundaries */}
          <div style={{ borderTop: `1px solid ${theme.colors.border || "#334155"}`, paddingTop: "0.75rem" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.875rem", fontWeight: 500, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={enableFrame}
                onChange={(e) => setEnableFrame(e.target.checked)}
                data-testid="wf-enable-frame-checkbox"
              />
              Enable Window Framing (ROWS / RANGE)
            </label>

            {enableFrame && (
              <div style={{ marginTop: "0.5rem", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
                <div>
                  <label htmlFor="wf-frame-type" style={{ display: "block", fontSize: "0.75rem", color: theme.colors.textMuted || "#94a3b8" }}>
                    Frame Type
                  </label>
                  <select
                    id="wf-frame-type"
                    data-testid="wf-frame-type-select"
                    value={frameType}
                    onChange={(e) => setFrameType(e.target.value as "ROWS" | "RANGE" | "GROUPS")}
                    style={{ width: "100%", padding: "0.375rem", background: theme.colors.background || "#0f172a", color: theme.colors.text || "#f8fafc", border: `1px solid ${theme.colors.border || "#334155"}`, borderRadius: "4px" }}
                  >
                    <option value="ROWS">ROWS</option>
                    <option value="RANGE">RANGE</option>
                    <option value="GROUPS">GROUPS</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="wf-exclusion" style={{ display: "block", fontSize: "0.75rem", color: theme.colors.textMuted || "#94a3b8" }}>
                    Exclusion
                  </label>
                  <select
                    id="wf-exclusion"
                    data-testid="wf-exclusion-select"
                    value={exclusion}
                    onChange={(e) => setExclusion(e.target.value)}
                    style={{ width: "100%", padding: "0.375rem", background: theme.colors.background || "#0f172a", color: theme.colors.text || "#f8fafc", border: `1px solid ${theme.colors.border || "#334155"}`, borderRadius: "4px" }}
                  >
                    <option value="NONE">NONE</option>
                    <option value="CURRENT ROW">CURRENT ROW</option>
                    <option value="GROUP">GROUP</option>
                    <option value="TIES">TIES</option>
                    <option value="NO OTHERS">NO OTHERS</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="wf-start-bound" style={{ display: "block", fontSize: "0.75rem", color: theme.colors.textMuted || "#94a3b8" }}>
                    Start Bound
                  </label>
                  <input
                    id="wf-start-bound"
                    data-testid="wf-start-bound-input"
                    type="text"
                    value={frameStart}
                    onChange={(e) => setFrameStart(e.target.value)}
                    style={{ width: "100%", padding: "0.375rem", background: theme.colors.background || "#0f172a", color: theme.colors.text || "#f8fafc", border: `1px solid ${theme.colors.border || "#334155"}`, borderRadius: "4px" }}
                  />
                </div>
                <div>
                  <label htmlFor="wf-end-bound" style={{ display: "block", fontSize: "0.75rem", color: theme.colors.textMuted || "#94a3b8" }}>
                    End Bound
                  </label>
                  <input
                    id="wf-end-bound"
                    data-testid="wf-end-bound-input"
                    type="text"
                    value={frameEnd}
                    onChange={(e) => setFrameEnd(e.target.value)}
                    style={{ width: "100%", padding: "0.375rem", background: theme.colors.background || "#0f172a", color: theme.colors.text || "#f8fafc", border: `1px solid ${theme.colors.border || "#334155"}`, borderRadius: "4px" }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Alias */}
          <div>
            <label
              htmlFor="wf-alias-input"
              style={{ display: "block", marginBottom: "0.375rem", fontSize: "0.875rem", fontWeight: 500 }}
            >
              Output Alias
            </label>
            <input
              id="wf-alias-input"
              type="text"
              data-testid="wf-alias-input"
              value={alias}
              placeholder="e.g. row_num, running_sum"
              onChange={(e) => setAlias(e.target.value)}
              style={
                unstyled
                  ? undefined
                  : {
                      width: "100%",
                      padding: "0.5rem 0.75rem",
                      background: theme.colors.background || "#0f172a",
                      color: theme.colors.text || "#f8fafc",
                      border: `1px solid ${theme.colors.border || "#334155"}`,
                      borderRadius: "6px",
                    }
              }
            />
          </div>

          {/* Live SQL Preview */}
          <div
            style={
              unstyled
                ? undefined
                : {
                    background: "rgba(0, 0, 0, 0.3)",
                    padding: "0.75rem",
                    borderRadius: "6px",
                    fontFamily: "monospace",
                    fontSize: "0.8125rem",
                    color: theme.colors.primary || "#38bdf8",
                    wordBreak: "break-all",
                  }
            }
            data-testid="wf-sql-preview"
          >
            {generatedPreview}
          </div>
        </div>

        {/* Footer Actions */}
        <div
          style={
            unstyled
              ? undefined
              : {
                  padding: "1rem 1.25rem",
                  borderTop: `1px solid ${theme.colors.border || "#334155"}`,
                  display: "flex",
                  justifyContent: "flex-end",
                  gap: "0.75rem",
                }
          }
        >
          <button
            type="button"
            onClick={onClose}
            data-testid="wf-cancel-btn"
            style={
              unstyled
                ? undefined
                : {
                    padding: "0.5rem 1rem",
                    background: "transparent",
                    border: `1px solid ${theme.colors.border || "#334155"}`,
                    color: theme.colors.text || "#f8fafc",
                    borderRadius: "6px",
                    cursor: "pointer",
                  }
            }
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            data-testid="wf-save-btn"
            style={
              unstyled
                ? undefined
                : {
                    padding: "0.5rem 1.25rem",
                    background: theme.colors.primary || "#38bdf8",
                    color: "#ffffff",
                    border: "none",
                    borderRadius: "6px",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            Save Window Function
          </button>
        </div>
      </div>
    </div>
  );
};
