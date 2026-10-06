/**
 * Interactive Bring Your Own AI (BYO-AI) Floating & Dockable Assistant Widget.
 */

import React, { useState, useRef, useEffect } from "react";
import type { ByoAiConfig } from "../ai/types";
import type { QuerySpec } from "../types";
import { useBringYourOwnAi } from "../hooks/useBringYourOwnAi";

export interface AiAssistantWidgetProps extends ByoAiConfig {
  schema?: any;
  currentSpec?: QuerySpec | null;
  onApplySpec?: (spec: QuerySpec) => void;
  isOpen?: boolean;
  onToggleOpen?: (open: boolean) => void;
  unstyled?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export const AiAssistantWidget: React.FC<AiAssistantWidgetProps> = ({
  handler,
  apiUrl,
  dialect = "postgres",
  autoApply = false,
  autoHeal = true,
  suggestions = [
    "Show top 10 users by activity",
    "Total revenue grouped by category",
    "Active accounts with balance > 500",
  ],
  widgetPosition = "floating-bottom-right",
  schema,
  currentSpec,
  onApplySpec,
  onSpecGenerated,
  onError,
  isOpen: controlledIsOpen,
  onToggleOpen,
  unstyled = false,
  className = "",
  style = {},
}) => {
  const [internalIsOpen, setInternalIsOpen] = useState<boolean>(false);
  const isOpen = controlledIsOpen !== undefined ? controlledIsOpen : internalIsOpen;

  const setOpen = (open: boolean) => {
    if (onToggleOpen) onToggleOpen(open);
    else setInternalIsOpen(open);
  };

  const [inputVal, setInputVal] = useState<string>("");
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const {
    messages,
    isGenerating,
    error,
    latestSpec,
    latestSql,
    sendMessage,
    applySpec,
    clearMessages,
  } = useBringYourOwnAi({
    handler,
    apiUrl,
    dialect,
    autoApply,
    autoHeal,
    schema,
    currentSpec,
    onApplySpec,
    onSpecGenerated,
    onError,
  });

  useEffect(() => {
    if (isOpen && messagesEndRef.current && typeof messagesEndRef.current.scrollIntoView === "function") {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputVal.trim() || isGenerating) return;
    const promptToSend = inputVal;
    setInputVal("");
    await sendMessage(promptToSend);
  };

  const handleSuggestionClick = async (s: string) => {
    if (isGenerating) return;
    await sendMessage(s);
  };

  const positionStyles: React.CSSProperties =
    widgetPosition === "floating-bottom-right"
      ? { position: "fixed", bottom: "24px", right: "24px", zIndex: 9999 }
      : widgetPosition === "docked-right"
      ? { position: "relative", width: "360px", height: "100%", borderLeft: "1px solid #374151" }
      : { width: "100%", marginBottom: "16px" };

  return (
    <div
      data-testid="ai-assistant-widget"
      className={`qb-ai-assistant-widget ${className}`}
      style={unstyled ? style : { ...positionStyles, fontFamily: "system-ui, -apple-system, sans-serif", ...style }}
    >
      {/* Floating Trigger Button */}
      {!isOpen && widgetPosition === "floating-bottom-right" && (
        <button
          type="button"
          data-testid="ai-widget-launcher"
          onClick={() => setOpen(true)}
          style={
            unstyled
              ? undefined
              : {
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  padding: "10px 18px",
                  background: "linear-gradient(135deg, #6366f1 0%, #a855f7 100%)",
                  color: "#ffffff",
                  border: "none",
                  borderRadius: "9999px",
                  boxShadow: "0 10px 25px -5px rgba(99, 102, 241, 0.4)",
                  cursor: "pointer",
                  fontSize: "14px",
                  fontWeight: 600,
                  transition: "transform 0.15s ease",
                }
          }
        >
          <span>✨</span>
          <span>Ask Your AI</span>
        </button>
      )}

      {/* Main Assistant Chat Window */}
      {(isOpen || widgetPosition !== "floating-bottom-right") && (
        <div
          data-testid="ai-chat-window"
          style={
            unstyled
              ? undefined
              : {
                  display: "flex",
                  flexDirection: "column",
                  width: widgetPosition === "docked-right" ? "100%" : "380px",
                  height: widgetPosition === "docked-right" ? "100%" : "520px",
                  maxHeight: "85vh",
                  background: "#1f2937",
                  color: "#f9fafb",
                  borderRadius: widgetPosition === "docked-right" ? "0" : "16px",
                  boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.4)",
                  border: "1px solid #374151",
                  overflow: "hidden",
                }
          }
        >
          {/* Header */}
          <div
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "12px 16px",
                    background: "#111827",
                    borderBottom: "1px solid #374151",
                  }
            }
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "18px" }}>✨</span>
              <div>
                <div style={{ fontSize: "14px", fontWeight: 700 }}>Bring Your Own AI</div>
                <div style={{ fontSize: "11px", color: "#9ca3af" }}>
                  {handler ? "Host AI Connected" : "Universal NLQ Engine"}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              {messages.length > 0 && (
                <button
                  type="button"
                  data-testid="ai-widget-clear"
                  onClick={clearMessages}
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "transparent",
                          border: "none",
                          color: "#9ca3af",
                          cursor: "pointer",
                          fontSize: "12px",
                          padding: "4px 8px",
                          borderRadius: "4px",
                        }
                  }
                  title="Clear conversation"
                >
                  Clear
                </button>
              )}
              {widgetPosition === "floating-bottom-right" && (
                <button
                  type="button"
                  data-testid="ai-widget-close"
                  onClick={() => setOpen(false)}
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "transparent",
                          border: "none",
                          color: "#9ca3af",
                          cursor: "pointer",
                          fontSize: "16px",
                          padding: "4px",
                        }
                  }
                  title="Close widget"
                >
                  ✕
                </button>
              )}
            </div>
          </div>

          {/* Messages Feed */}
          <div
            data-testid="ai-messages-feed"
            style={
              unstyled
                ? undefined
                : {
                    flex: 1,
                    overflowY: "auto",
                    padding: "14px",
                    display: "flex",
                    flexDirection: "column",
                    gap: "12px",
                  }
            }
          >
            {messages.length === 0 && (
              <div style={{ textAlign: "center", margin: "auto", padding: "16px 0" }}>
                <div style={{ fontSize: "28px", marginBottom: "8px" }}>🤖</div>
                <div style={{ fontSize: "14px", fontWeight: 600, color: "#e5e7eb" }}>
                  How can your AI help query your data?
                </div>
                <div style={{ fontSize: "12px", color: "#9ca3af", marginTop: "4px", maxWidth: "260px" }}>
                  Ask in plain English. Your AI will translate, synthesize joins, and build verified queries.
                </div>

                {/* Suggestions */}
                {suggestions.length > 0 && (
                  <div style={{ marginTop: "16px", display: "flex", flexDirection: "column", gap: "6px" }}>
                    {suggestions.map((s, idx) => (
                      <button
                        key={idx}
                        type="button"
                        data-testid={`ai-suggestion-${idx}`}
                        onClick={() => handleSuggestionClick(s)}
                        style={
                          unstyled
                            ? undefined
                            : {
                                textAlign: "left",
                                background: "#374151",
                                color: "#e5e7eb",
                                border: "1px solid #4b5563",
                                padding: "6px 10px",
                                borderRadius: "8px",
                                fontSize: "12px",
                                cursor: "pointer",
                                transition: "background 0.15s ease",
                              }
                        }
                      >
                        💡 {s}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {messages.map((msg) => (
              <div
                key={msg.id}
                data-testid={`ai-message-${msg.role}`}
                style={{
                  alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                  maxWidth: "90%",
                  display: "flex",
                  flexDirection: "column",
                  gap: "4px",
                }}
              >
                <div
                  style={
                    unstyled
                      ? undefined
                      : {
                          padding: "10px 14px",
                          borderRadius: "12px",
                          fontSize: "13px",
                          lineHeight: "1.4",
                          background:
                            msg.role === "user"
                              ? "#4f46e5"
                              : "#374151",
                          color: "#ffffff",
                        }
                  }
                >
                  {msg.content}
                </div>

                {/* Self-healing notes alert */}
                {msg.healingNotes && msg.healingNotes.length > 0 && (
                  <div
                    data-testid="ai-healing-notes"
                    style={{
                      fontSize: "11px",
                      color: "#fbbf24",
                      background: "rgba(251, 191, 36, 0.1)",
                      border: "1px solid rgba(251, 191, 36, 0.3)",
                      borderRadius: "6px",
                      padding: "4px 8px",
                    }}
                  >
                    🛠️ {msg.healingNotes.join(" ")}
                  </div>
                )}

                {/* Generated SQL snippet preview */}
                {msg.sql && (
                  <div
                    style={{
                      background: "#111827",
                      borderRadius: "8px",
                      padding: "8px 10px",
                      border: "1px solid #374151",
                      marginTop: "4px",
                    }}
                  >
                    <pre
                      style={{
                        margin: 0,
                        fontSize: "11px",
                        color: "#6ee7b7",
                        overflowX: "auto",
                        fontFamily: "monospace",
                      }}
                    >
                      {msg.sql}
                    </pre>

                    {/* Apply Button */}
                    {msg.spec && onApplySpec && (
                      <button
                        type="button"
                        data-testid="ai-apply-spec-btn"
                        onClick={() => applySpec(msg.spec)}
                        style={
                          unstyled
                            ? undefined
                            : {
                                marginTop: "6px",
                                width: "100%",
                                padding: "6px 10px",
                                background: "#2563eb",
                                color: "#ffffff",
                                border: "none",
                                borderRadius: "6px",
                                fontSize: "11px",
                                fontWeight: 600,
                                cursor: "pointer",
                              }
                        }
                      >
                        Apply to Builder ↗
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}

            {isGenerating && (
              <div
                data-testid="ai-generating-indicator"
                style={{
                  alignSelf: "flex-start",
                  background: "#374151",
                  color: "#9ca3af",
                  padding: "8px 12px",
                  borderRadius: "12px",
                  fontSize: "12px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                <span>⚡</span>
                <span>AI is compiling query...</span>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Error Banner */}
          {error && (
            <div
              data-testid="ai-error-banner"
              style={{
                padding: "8px 14px",
                background: "rgba(239, 68, 68, 0.15)",
                color: "#fca5a5",
                fontSize: "12px",
                borderTop: "1px solid rgba(239, 68, 68, 0.3)",
              }}
            >
              ⚠️ {error}
            </div>
          )}

          {/* Input Form */}
          <form
            onSubmit={handleSubmit}
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    padding: "10px 14px",
                    background: "#111827",
                    borderTop: "1px solid #374151",
                  }
            }
          >
            <input
              type="text"
              data-testid="ai-widget-input"
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              placeholder="Ask your AI to build a query..."
              disabled={isGenerating}
              style={
                unstyled
                  ? undefined
                  : {
                      flex: 1,
                      background: "#1f2937",
                      color: "#f9fafb",
                      border: "1px solid #4b5563",
                      borderRadius: "8px",
                      padding: "8px 12px",
                      fontSize: "13px",
                      outline: "none",
                    }
              }
            />
            <button
              type="submit"
              data-testid="ai-widget-submit"
              disabled={!inputVal.trim() || isGenerating}
              style={
                unstyled
                  ? undefined
                  : {
                      padding: "8px 14px",
                      background: !inputVal.trim() || isGenerating ? "#4b5563" : "#6366f1",
                      color: "#ffffff",
                      border: "none",
                      borderRadius: "8px",
                      fontSize: "13px",
                      fontWeight: 600,
                      cursor: !inputVal.trim() || isGenerating ? "not-allowed" : "pointer",
                      transition: "background 0.15s ease",
                    }
              }
            >
              Send
            </button>
          </form>
        </div>
      )}
    </div>
  );
};
