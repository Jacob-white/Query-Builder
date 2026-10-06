import React from "react";
import type { LiveExecutionStatus } from "../hooks/useLiveExecution";

export interface LiveExecutionBarProps {
  onExecute?: () => void | Promise<void>;
  onCancel?: () => void | Promise<void>;
  onTestConnection?: () => void | Promise<void>;
  isExecuting?: boolean;
  executionTimeMs?: number | null;
  rowCount?: number | null;
  error?: string | null;
  onDismissError?: () => void;
  connectionStatus?: LiveExecutionStatus;
  connectionLatencyMs?: number | null;
  connectionId?: string;
  unstyled?: boolean;
  className?: string;
  showConnectionPill?: boolean;
}

export const LiveExecutionBar: React.FC<LiveExecutionBarProps> = ({
  onExecute,
  onCancel,
  onTestConnection,
  isExecuting = false,
  executionTimeMs = null,
  rowCount = null,
  error = null,
  onDismissError,
  connectionStatus = "idle",
  connectionLatencyMs = null,
  connectionId,
  unstyled = false,
  className = "",
  showConnectionPill = true,
}) => {
  const s = (styleObj: React.CSSProperties): React.CSSProperties | undefined =>
    unstyled ? undefined : styleObj;

  const getStatusColor = (): string => {
    switch (connectionStatus) {
      case "connected":
        return "#10b981"; // green-500
      case "testing":
        return "#f59e0b"; // amber-500
      case "error":
      case "disconnected":
        return "#ef4444"; // red-500
      case "idle":
      default:
        return "#64748b"; // slate-500
    }
  };

  const getStatusLabel = (): string => {
    switch (connectionStatus) {
      case "testing":
        return "Testing...";
      case "connected":
        return `Connected${
          connectionLatencyMs != null ? ` (${connectionLatencyMs}ms)` : ""
        }`;
      case "error":
        return "Connection Error";
      case "disconnected":
        return "Disconnected";
      case "idle":
      default:
        return connectionId ? `DB: ${connectionId}` : "Database Idle";
    }
  };

  const formatExecutionTime = (ms: number): string => {
    if (ms < 1000) {
      return `${ms}ms`;
    }
    return `${(ms / 1000).toFixed(2)}s`;
  };

  return (
    <div
      data-qb="live-execution-bar"
      data-testid="live-execution-bar"
      className={className}
      style={s({
        display: "flex",
        flexDirection: "column",
        gap: "8px",
        padding: "10px 14px",
        background: "#0f172a",
        borderRadius: "8px",
        border: "1px solid #1e293b",
        color: "#f8fafc",
        fontSize: "13px",
      })}
    >
      <div
        style={s({
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "10px",
        })}
      >
        {/* Left Side: Connection Status & Controls */}
        <div
          style={s({
            display: "flex",
            alignItems: "center",
            gap: "10px",
          })}
        >
          {showConnectionPill && (
            <div
              data-qb="connection-status-pill"
              style={s({
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                padding: "3px 10px",
                borderRadius: "9999px",
                background: "#1e293b",
                border: "1px solid #334155",
                fontSize: "12px",
              })}
            >
              <span
                data-testid="status-indicator-dot"
                style={s({
                  width: "8px",
                  height: "8px",
                  borderRadius: "50%",
                  backgroundColor: getStatusColor(),
                  display: "inline-block",
                })}
              />
              <span style={s({ color: "#e2e8f0" })}>{getStatusLabel()}</span>
              {onTestConnection && (
                <button
                  type="button"
                  data-qb="btn-test-connection"
                  aria-label="Test database connection"
                  onClick={onTestConnection}
                  disabled={connectionStatus === "testing"}
                  style={s({
                    marginLeft: "4px",
                    background: "transparent",
                    border: "none",
                    color: "#38bdf8",
                    cursor: connectionStatus === "testing" ? "not-allowed" : "pointer",
                    fontSize: "11px",
                    padding: "0 2px",
                    textDecoration: "underline",
                  })}
                >
                  {connectionStatus === "testing" ? "..." : "Ping"}
                </button>
              )}
            </div>
          )}

          {/* Action Buttons */}
          <button
            type="button"
            data-qb="btn-live-execute"
            aria-label="Execute live query"
            disabled={isExecuting}
            onClick={onExecute}
            style={s({
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              padding: "5px 12px",
              borderRadius: "6px",
              background: isExecuting ? "#475569" : "#2563eb",
              color: "#ffffff",
              border: "none",
              cursor: isExecuting ? "not-allowed" : "pointer",
              fontWeight: 600,
              fontSize: "12px",
            })}
          >
            {isExecuting ? "⏳ Running..." : "▶ Execute Query"}
          </button>

          {isExecuting && onCancel && (
            <button
              type="button"
              data-qb="btn-live-cancel"
              aria-label="Cancel live query execution"
              onClick={onCancel}
              style={s({
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                padding: "5px 10px",
                borderRadius: "6px",
                background: "#dc2626",
                color: "#ffffff",
                border: "none",
                cursor: "pointer",
                fontWeight: 500,
                fontSize: "12px",
              })}
            >
              ⏹ Cancel
            </button>
          )}
        </div>

        {/* Right Side: Execution Timing & Row Count Badges */}
        <div
          style={s({
            display: "flex",
            alignItems: "center",
            gap: "8px",
          })}
        >
          {executionTimeMs != null && (
            <span
              data-qb="execution-time"
              data-testid="execution-time-badge"
              style={s({
                padding: "2px 8px",
                borderRadius: "4px",
                background: "#1e293b",
                color: "#94a3b8",
                fontSize: "12px",
                fontFamily: "monospace",
              })}
            >
              ⏱️ {formatExecutionTime(executionTimeMs)}
            </span>
          )}

          {rowCount != null && (
            <span
              data-qb="row-count-badge"
              data-testid="row-count-badge"
              style={s({
                padding: "2px 8px",
                borderRadius: "4px",
                background: "#064e3b",
                color: "#6ee7b7",
                fontSize: "12px",
                fontWeight: 500,
              })}
            >
              📊 {rowCount.toLocaleString()} rows
            </span>
          )}
        </div>
      </div>

      {/* Error Callout Banner */}
      {error && (
        <div
          role="alert"
          data-qb="live-error-banner"
          data-testid="live-error-banner"
          style={s({
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "#450a0a",
            border: "1px solid #7f1d1d",
            borderRadius: "6px",
            padding: "8px 12px",
            color: "#fca5a5",
            fontSize: "12px",
          })}
        >
          <div style={s({ display: "flex", alignItems: "center", gap: "6px" })}>
            <span>⚠️</span>
            <span>{error}</span>
          </div>
          {onDismissError && (
            <button
              type="button"
              data-qb="btn-dismiss-error"
              aria-label="Dismiss execution error"
              onClick={onDismissError}
              style={s({
                background: "transparent",
                border: "none",
                color: "#fca5a5",
                cursor: "pointer",
                fontSize: "14px",
                fontWeight: "bold",
                padding: "0 4px",
              })}
            >
              ✕
            </button>
          )}
        </div>
      )}
    </div>
  );
};
