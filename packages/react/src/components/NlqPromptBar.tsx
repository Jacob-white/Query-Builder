import React, { useState } from "react";
import type { QuerySpec } from "../types";
import type { ByoAiSchema } from "../ai/types";
import { getSchemaTableNames } from "../utils/schemaUtils";
import { useNlqQuery, type NlqProviderName } from "../hooks/useNlqQuery";

export interface NlqPromptBarProps {
  schema?: ByoAiSchema;
  currentSpec?: QuerySpec;
  onApplySpec?: (spec: QuerySpec) => void;
  defaultProvider?: NlqProviderName;
  apiUrl?: string;
  dialect?: string;
  className?: string;
  placeholder?: string;
  suggestions?: string[];
  showSuggestions?: boolean;
  showSchemaPills?: boolean;
  unstyled?: boolean;
}

const DEFAULT_SUGGESTIONS = [
  "Top 10 customers sorted by balance descending",
  "Active orders joined with users where amount > 100",
  "Count records grouped by status with count > 5",
];

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

const PROVIDER_PILLS: { id: NlqProviderName; label: string; badgeColor: string }[] = [
  { id: "gemini", label: "✨ Gemini 2.5", badgeColor: "#8b5cf6" },
  { id: "mock", label: "⚡ Rule Engine", badgeColor: "#38bdf8" },
  { id: "openai", label: "OpenAI", badgeColor: "#10b981" },
  { id: "anthropic", label: "Claude", badgeColor: "#f59e0b" },
  { id: "ollama", label: "Ollama", badgeColor: "#64748b" },
];

export const NlqPromptBar: React.FC<NlqPromptBarProps> = ({
  schema,
  currentSpec,
  onApplySpec,
  defaultProvider = "mock",
  apiUrl = "/api/v1/nlq",
  dialect = "postgres",
  className = "",
  placeholder = "Ask in plain English (e.g., 'Find all active orders with total > 100 joined with customers')...",
  suggestions,
  showSuggestions = true,
  showSchemaPills = true,
  unstyled = false,
}) => {
  const s = (styleObj: React.CSSProperties): React.CSSProperties | undefined =>
    unstyled ? undefined : styleObj;
  const [autoApply, setAutoApply] = useState(true);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [showAllTables, setShowAllTables] = useState(false);
  const [tableFilter, setTableFilter] = useState("");
  const [showMoreProviders, setShowMoreProviders] = useState(false);
  const [followUpInput, setFollowUpInput] = useState("");

  const {
    prompt,
    setPrompt,
    isLoading,
    isExplaining,
    error,
    confidence,
    explanation,
    explanationSteps,
    followUps,
    turns,
    provider,
    setProvider,
    history,
    canUndo,
    translatePrompt,
    explainQuery,
    undoLastTranslation,
    restoreTurn,
    clearState,
  } = useNlqQuery({
    schema,
    currentSpec,
    defaultProvider,
    apiUrl,
    dialect,
    autoApply,
    onApply: onApplySpec,
  });

  const handleFollowUpSubmit = () => {
    const trimmed = followUpInput.trim();
    if (!trimmed || isLoading) return;
    setFollowUpInput("");
    void translatePrompt(trimmed);
  };

  const schemaTableNames = getSchemaTableNames(schema);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void translatePrompt();
      setHistoryIndex(-1);
    } else if (e.key === "Escape") {
      clearState();
      setHistoryIndex(-1);
    } else if (e.key === "ArrowUp") {
      if (history.length > 0) {
        e.preventDefault();
        const nextIdx = Math.min(historyIndex + 1, history.length - 1);
        setHistoryIndex(nextIdx);
        setPrompt(history[nextIdx]);
      }
    } else if (e.key === "ArrowDown") {
      if (historyIndex > 0) {
        e.preventDefault();
        const nextIdx = historyIndex - 1;
        setHistoryIndex(nextIdx);
        setPrompt(history[nextIdx]);
      } else if (historyIndex === 0) {
        e.preventDefault();
        setHistoryIndex(-1);
        setPrompt("");
      }
    }
  };

  return (
    <div
      className={`qb-nlq-bar ${className}`}
      style={s({
        border: "1px solid var(--qb-color-border, var(--qb-border-color, #e2e8f0))",
        borderRadius: "8px",
        backgroundColor: "var(--qb-color-surface, var(--qb-bg-primary, #ffffff))",
        color: "var(--qb-color-text, var(--qb-text-primary, #0f172a))",
        padding: "10px 14px",
        marginBottom: "10px",
        boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
      })}
      data-testid="nlq-prompt-bar"
    >
      {/* Unified Prompt + AI Engine Row */}
      <div
        style={s({
          display: "flex",
          alignItems: "center",
          gap: "8px",
          flexWrap: "wrap",
        })}
      >
        <div style={s({ display: "flex", alignItems: "center", gap: "5px", flexShrink: 0 })}>
          <span style={s({ fontSize: "15px" })} role="img" aria-label="AI Prompt">
            ✨
          </span>
          <span
            style={s({
              fontWeight: 700,
              fontSize: "12.5px",
              color: "var(--qb-color-text, var(--qb-text-primary, #0f172a))",
              whiteSpace: "nowrap",
            })}
          >
            Natural Language Query
          </span>
        </div>

        <input
          type="text"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isLoading || isExplaining}
          style={s({
            flex: "1 1 280px",
            padding: "6px 11px",
            fontSize: "12.5px",
            borderRadius: "6px",
            border: "1px solid var(--qb-color-border, var(--qb-border-color, #e2e8f0))",
            backgroundColor: "var(--qb-color-background, var(--qb-bg-secondary, #f8fafc))",
            color: "var(--qb-color-text, var(--qb-text-primary, #0f172a))",
            outline: "none",
          })}
          aria-label="NLQ Input"
        />

        <button
          type="button"
          onClick={() => void translatePrompt()}
          disabled={isLoading || isExplaining || !prompt.trim()}
          style={s({
            padding: "6px 14px",
            fontSize: "12.5px",
            fontWeight: 600,
            borderRadius: "6px",
            border: "none",
            backgroundColor: "var(--qb-color-primary, var(--qb-accent-color, #3b82f6))",
            color: "#ffffff",
            cursor: isLoading || !prompt.trim() ? "not-allowed" : "pointer",
            opacity: isLoading || !prompt.trim() ? 0.6 : 1,
            display: "flex",
            alignItems: "center",
            gap: "6px",
          })}
          aria-label="Generate Query Button"
        >
          {isLoading ? "Generating..." : "Generate"}
        </button>

        {currentSpec && (
          <button
            type="button"
            onClick={() => void explainQuery(currentSpec)}
            disabled={isLoading || isExplaining}
            style={s({
              padding: "6px 10px",
              fontSize: "12px",
              borderRadius: "6px",
              border: "1px solid var(--qb-color-border, var(--qb-border-color, #e2e8f0))",
              backgroundColor: "var(--qb-color-background, var(--qb-bg-secondary, #f8fafc))",
              color: "var(--qb-color-text, var(--qb-text-primary, #0f172a))",
              cursor: isExplaining ? "not-allowed" : "pointer",
            })}
            aria-label="Explain Query Button"
          >
            {isExplaining ? "Explaining..." : "Explain"}
          </button>
        )}

        {canUndo && (
          <button
            type="button"
            onClick={() => undoLastTranslation()}
            style={s({
              padding: "6px 10px",
              fontSize: "12px",
              borderRadius: "6px",
              border: "1px solid var(--qb-color-border, var(--qb-border-color, #e2e8f0))",
              backgroundColor: "var(--qb-color-background, var(--qb-bg-secondary, #f8fafc))",
              color: "var(--qb-color-text, var(--qb-text-primary, #0f172a))",
              cursor: "pointer",
            })}
            aria-label="Undo Translation Button"
          >
            Undo
          </button>
        )}

        <div style={s({ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", marginLeft: "auto" })}>
          <label
            style={s({
              fontSize: "11.5px",
              color: "var(--qb-color-text-muted, var(--qb-text-secondary, #94a3b8))",
              display: "flex",
              alignItems: "center",
              gap: "4px",
              cursor: "pointer",
            })}
          >
            <input
              type="checkbox"
              checked={autoApply}
              onChange={(e) => setAutoApply(e.target.checked)}
              aria-label="Auto-apply to canvas"
              style={{ accentColor: "var(--qb-color-primary, #3b82f6)" }}
            />
            Auto-apply
          </label>

          {/* Accessible native select kept for keyboard/screen-reader & test compatibility */}
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value as NlqProviderName)}
            style={s(SR_ONLY_STYLE)}
            aria-label="NLQ Provider"
          >
            <option value="mock">Hermetic / Mock</option>
            <option value="gemini">Google Gemini</option>
            <option value="openai">OpenAI GPT-4o</option>
            <option value="anthropic">Anthropic Claude</option>
            <option value="ollama">Ollama (Local LLM)</option>
            <option value="custom">Custom</option>
          </select>

          {!unstyled && (
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                background: "var(--qb-color-background, rgba(15, 23, 42, 0.7))",
                padding: "2px",
                borderRadius: "8px",
                border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
              }}
              role="group"
              aria-label="AI Engine Selector"
            >
              {(showMoreProviders ? PROVIDER_PILLS : PROVIDER_PILLS.slice(0, 2)).map((p) => {
                const isActive = provider === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => setProvider(p.id)}
                    style={{
                      padding: "2px 8px",
                      fontSize: "11px",
                      fontWeight: 700,
                      borderRadius: "6px",
                      border: isActive
                        ? `1px solid ${p.badgeColor}`
                        : "1px solid transparent",
                      background: isActive
                        ? `${p.badgeColor}28`
                        : "transparent",
                      color: isActive ? "#f8fafc" : "var(--qb-color-text-muted, #94a3b8)",
                      cursor: "pointer",
                      transition: "all 0.15s ease",
                    }}
                  >
                    {p.label}
                  </button>
                );
              })}
              <button
                type="button"
                onClick={() => setShowMoreProviders((prev) => !prev)}
                title={showMoreProviders ? "Fewer AI engines" : "More AI engines (OpenAI, Claude, Ollama)"}
                style={{
                  padding: "2px 5px",
                  fontSize: "10px",
                  fontWeight: 600,
                  borderRadius: "5px",
                  border: "none",
                  background: "transparent",
                  color: "var(--qb-color-text-muted, #64748b)",
                  cursor: "pointer",
                }}
              >
                {showMoreProviders ? "▴" : "▾"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Compact Quick-Insert Strip (Tables + Suggestions side-by-side) */}
      {(showSchemaPills || showSuggestions) && (
        <div
          style={s({
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "10px",
            marginTop: "6px",
            flexWrap: "wrap",
          })}
        >
          {/* Schema Pills (capped to 6 by default so large 100+ table schemas stay compact) */}
          {showSchemaPills && schemaTableNames.length > 0 && (() => {
            const filteredTables = tableFilter.trim()
              ? schemaTableNames.filter((t) => t.toLowerCase().includes(tableFilter.trim().toLowerCase()))
              : schemaTableNames;
            const visibleTables = showAllTables ? filteredTables.slice(0, 36) : filteredTables.slice(0, 6);
            const hiddenCount = Math.max(0, filteredTables.length - visibleTables.length);

            return (
              <div style={s({ display: "flex", alignItems: "center", gap: "5px", flexWrap: "wrap" })}>
                <span style={s({ fontSize: "11px", color: "var(--qb-color-text-muted, var(--qb-text-secondary, #64748b))", fontWeight: 600 })}>
                  Tables:
                </span>
                {schemaTableNames.length > 6 && showAllTables && (
                  <input
                    type="text"
                    value={tableFilter}
                    onChange={(e) => setTableFilter(e.target.value)}
                    placeholder="Filter tables..."
                    style={s({
                      fontSize: "11px",
                      padding: "2px 8px",
                      borderRadius: "6px",
                      border: "1px solid var(--qb-color-border, #334155)",
                      backgroundColor: "var(--qb-color-background, #0f172a)",
                      color: "var(--qb-color-text, #f8fafc)",
                      width: "120px",
                      outline: "none",
                    })}
                  />
                )}
                {visibleTables.map((tbl) => (
                  <button
                    key={tbl}
                    type="button"
                    onClick={() => setPrompt((prev) => (prev ? `${prev} from ${tbl}` : `Query ${tbl}`))}
                    style={s({
                      fontSize: "11px",
                      padding: "1px 7px",
                      borderRadius: "10px",
                      border: "1px solid var(--qb-color-border, var(--qb-border-color, #e2e8f0))",
                      backgroundColor: "var(--qb-color-background, var(--qb-bg-secondary, #f8fafc))",
                      color: "var(--qb-color-text, var(--qb-text-primary, #0f172a))",
                      cursor: "pointer",
                    })}
                    aria-label={`Insert table ${tbl}`}
                  >
                    {tbl}
                  </button>
                ))}
                {schemaTableNames.length > 6 && (
                  <button
                    type="button"
                    onClick={() => {
                      setShowAllTables((prev) => !prev);
                      if (showAllTables) setTableFilter("");
                    }}
                    style={s({
                      fontSize: "11px",
                      padding: "1px 8px",
                      borderRadius: "10px",
                      border: "1px dashed var(--qb-color-primary, #3b82f6)",
                      backgroundColor: "rgba(59, 130, 246, 0.1)",
                      color: "var(--qb-color-primary, #60a5fa)",
                      cursor: "pointer",
                      fontWeight: 600,
                    })}
                  >
                    {showAllTables ? "Show fewer ▴" : `+${hiddenCount} more tables ▾`}
                  </button>
                )}
              </div>
            );
          })()}

          {/* Suggestion Pills (shown before first turn so active conversations stay uncluttered) */}
          {showSuggestions && turns.length === 0 && (
            <div style={s({ display: "flex", alignItems: "center", gap: "5px", flexWrap: "wrap" })}>
              <span style={s({ fontSize: "11px", color: "var(--qb-color-text-muted, var(--qb-text-secondary, #64748b))" })}>Suggestions:</span>
              {(suggestions && suggestions.length > 0 ? suggestions : DEFAULT_SUGGESTIONS).map((sug, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => {
                    setPrompt(sug);
                    void translatePrompt(sug);
                  }}
                  style={s({
                    fontSize: "11px",
                    padding: "1px 7px",
                    borderRadius: "10px",
                    border: "1px dashed var(--qb-color-border, var(--qb-border-color, #e2e8f0))",
                    backgroundColor: "transparent",
                    color: "var(--qb-color-primary, var(--qb-accent-color, #2563eb))",
                    cursor: "pointer",
                  })}
                  aria-label={`Suggestion: ${sug}`}
                >
                  {sug}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Error Message Callout */}
      {error && (
        <div
          style={s({
            marginTop: "8px",
            padding: "8px 12px",
            borderRadius: "6px",
            backgroundColor: "rgba(239, 68, 68, 0.12)",
            border: "1px solid rgba(239, 68, 68, 0.35)",
            color: "#fca5a5",
            fontSize: "12px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          })}
          data-testid="nlq-error-message"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={clearState}
            style={s({ background: "none", border: "none", color: "#fca5a5", cursor: "pointer", fontWeight: "bold" })}
            aria-label="Dismiss Error"
          >
            ×
          </button>
        </div>
      )}

      {/* Multi-Shot AI Conversation & Explanation Callout */}
      {explanation && !error && (
        <div
          style={s({
            marginTop: "8px",
            padding: "10px 12px",
            borderRadius: "8px",
            backgroundColor: "rgba(16, 185, 129, 0.08)",
            border: "1px solid rgba(16, 185, 129, 0.28)",
            color: "var(--qb-color-text, #e2e8f0)",
            fontSize: "12px",
          })}
          data-testid="nlq-explanation-box"
        >
          <div style={s({ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px", gap: "8px", flexWrap: "wrap" })}>
            <div style={s({ display: "flex", alignItems: "center", gap: "8px" })}>
              <span style={s({ fontWeight: 700, color: "#34d399" })}>✨ AI Query Analysis</span>
              {turns.length > 0 && (
                <span
                  style={s({
                    fontSize: "10.5px",
                    padding: "1px 7px",
                    borderRadius: "999px",
                    backgroundColor: "rgba(139, 92, 246, 0.18)",
                    border: "1px solid rgba(139, 92, 246, 0.4)",
                    color: "#c4b5fd",
                    fontWeight: 600,
                  })}
                  data-testid="nlq-turn-badge"
                >
                  Turn {turns.length}
                </span>
              )}
            </div>
            <div style={s({ display: "flex", alignItems: "center", gap: "8px" })}>
              {confidence !== null && (
                <span
                  style={s({
                    fontSize: "11px",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    backgroundColor: confidence >= 0.8 ? "#dcfce7" : "#fef9c3",
                    color: confidence >= 0.8 ? "#15803d" : "#854d0e",
                    fontWeight: 600,
                  })}
                  data-testid="nlq-confidence-badge"
                >
                  {Math.round(confidence * 100)}% Confidence
                </span>
              )}
              <button
                type="button"
                onClick={() => {
                  setFollowUpInput("");
                  clearState();
                }}
                style={s({
                  fontSize: "11px",
                  padding: "2px 8px",
                  borderRadius: "5px",
                  border: "1px solid rgba(148, 163, 184, 0.3)",
                  backgroundColor: "rgba(15, 23, 42, 0.4)",
                  color: "var(--qb-color-text-muted, #94a3b8)",
                  cursor: "pointer",
                })}
                aria-label="New AI Conversation"
              >
                New Chat
              </button>
            </div>
          </div>

          {/* Prior Conversation Turns Thread */}
          {turns.length > 1 && (
            <div
              style={s({
                display: "flex",
                flexDirection: "column",
                gap: "4px",
                marginBottom: "8px",
                paddingBottom: "8px",
                borderBottom: "1px dashed rgba(148, 163, 184, 0.25)",
              })}
              data-testid="nlq-conversation-thread"
            >
              {turns.slice(0, -1).map((turn, idx) => (
                <div
                  key={turn.id}
                  style={s({
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "8px",
                    padding: "4px 8px",
                    borderRadius: "6px",
                    backgroundColor: "rgba(15, 23, 42, 0.35)",
                    fontSize: "11px",
                    color: "var(--qb-color-text-muted, #94a3b8)",
                  })}
                >
                  <div style={s({ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>
                    <strong style={s({ color: "#93c5fd" })}>#{idx + 1} You:</strong> {`“${turn.prompt}”`}
                    {turn.explanation ? ` → ${turn.explanation}` : ""}
                  </div>
                  <button
                    type="button"
                    onClick={() => restoreTurn(idx)}
                    style={s({
                      fontSize: "10.5px",
                      padding: "1px 6px",
                      borderRadius: "4px",
                      border: "1px solid rgba(56, 189, 248, 0.35)",
                      backgroundColor: "rgba(56, 189, 248, 0.1)",
                      color: "#38bdf8",
                      cursor: "pointer",
                      flexShrink: 0,
                    })}
                    aria-label={`Restore turn ${idx + 1}`}
                  >
                    Revert here
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Latest Turn Prompt & Explanation */}
          {turns.length > 0 && (
            <div
              style={s({
                fontSize: "11px",
                color: "#93c5fd",
                marginBottom: "3px",
                fontWeight: 600,
              })}
            >
              {`💬 You asked: “${turns[turns.length - 1].prompt}”`}
            </div>
          )}
          <div style={s({ lineHeight: 1.5 })}>{explanation}</div>
          {explanationSteps.length > 0 && (
            <ol style={s({ margin: "6px 0 0 16px", padding: 0 })}>
              {explanationSteps.map((step, idx) => (
                <li key={idx} style={s({ marginBottom: "2px" })}>
                  {step}
                </li>
              ))}
            </ol>
          )}

          {/* Multi-Shot Follow-up Refinement Chips + Conversational Reply Input */}
          <div
            style={s({
              marginTop: "8px",
              paddingTop: "8px",
              borderTop: "1px solid rgba(16, 185, 129, 0.22)",
              display: "flex",
              flexDirection: "column",
              gap: "6px",
            })}
          >
            {followUps.length > 0 && (
              <div style={s({ display: "flex", alignItems: "center", gap: "5px", flexWrap: "wrap" })}>
                <span style={s({ fontSize: "11px", color: "#6ee7b7", fontWeight: 600 })}>
                  Refine next:
                </span>
                {followUps.map((chip, idx) => (
                  <button
                    key={idx}
                    type="button"
                    disabled={isLoading}
                    onClick={() => {
                      setPrompt(chip);
                      void translatePrompt(chip);
                    }}
                    style={s({
                      fontSize: "11px",
                      padding: "2px 8px",
                      borderRadius: "999px",
                      border: "1px solid rgba(52, 211, 153, 0.4)",
                      backgroundColor: "rgba(16, 185, 129, 0.14)",
                      color: "#a7f3d0",
                      cursor: isLoading ? "not-allowed" : "pointer",
                      fontWeight: 500,
                    })}
                    aria-label={`Follow-up: ${chip}`}
                  >
                    + {chip}
                  </button>
                ))}
              </div>
            )}

            <div style={s({ display: "flex", alignItems: "center", gap: "6px" })}>
              <input
                type="text"
                value={followUpInput}
                onChange={(e) => setFollowUpInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleFollowUpSubmit();
                  }
                }}
                disabled={isLoading}
                placeholder="Reply to refine this query (e.g. 'only active', 'add column...', 'sort by...', 'limit 5')..."
                style={s({
                  flex: 1,
                  padding: "5px 10px",
                  fontSize: "12px",
                  borderRadius: "6px",
                  border: "1px solid rgba(52, 211, 153, 0.35)",
                  backgroundColor: "rgba(15, 23, 42, 0.65)",
                  color: "var(--qb-color-text, #f8fafc)",
                  outline: "none",
                })}
                aria-label="Follow-up Refinement Input"
                data-testid="nlq-followup-input"
              />
              <button
                type="button"
                disabled={isLoading || !followUpInput.trim()}
                onClick={handleFollowUpSubmit}
                style={s({
                  padding: "5px 12px",
                  fontSize: "11.5px",
                  fontWeight: 700,
                  borderRadius: "6px",
                  border: "1px solid rgba(52, 211, 153, 0.5)",
                  backgroundColor: "#059669",
                  color: "#ffffff",
                  cursor: isLoading || !followUpInput.trim() ? "not-allowed" : "pointer",
                  opacity: isLoading || !followUpInput.trim() ? 0.55 : 1,
                  whiteSpace: "nowrap",
                })}
                aria-label="Submit Follow-up Refinement"
                data-testid="nlq-followup-submit"
              >
                {isLoading ? "Refining..." : "Refine ↵"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
