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
  showSuggestions?: boolean;
  showSchemaPills?: boolean;
  unstyled?: boolean;
}

const DEFAULT_SUGGESTIONS = [
  "Top 10 customers sorted by balance descending",
  "Active orders joined with users where amount > 100",
  "Count records grouped by status with count > 5",
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
  showSuggestions = true,
  showSchemaPills = true,
  unstyled = false,
}) => {
  const s = (styleObj: React.CSSProperties): React.CSSProperties | undefined =>
    unstyled ? undefined : styleObj;
  const [autoApply, setAutoApply] = useState(true);
  const [historyIndex, setHistoryIndex] = useState(-1);

  const {
    prompt,
    setPrompt,
    isLoading,
    isExplaining,
    error,
    confidence,
    explanation,
    explanationSteps,
    provider,
    setProvider,
    history,
    canUndo,
    translatePrompt,
    explainQuery,
    undoLastTranslation,
    clearState,
  } = useNlqQuery({
    schema,
    defaultProvider,
    apiUrl,
    dialect,
    autoApply,
    onApply: onApplySpec,
  });

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
        border: "1px solid var(--qb-border-color, #e2e8f0)",
        borderRadius: "8px",
        backgroundColor: "var(--qb-bg-primary, #ffffff)",
        padding: "12px",
        marginBottom: "16px",
        boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
      })}
      data-testid="nlq-prompt-bar"
    >
      {/* Top Header Row */}
      <div
        style={s({
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "8px",
          gap: "8px",
        })}
      >
        <div style={s({ display: "flex", alignItems: "center", gap: "6px" })}>
          <span style={s({ fontSize: "16px" })} role="img" aria-label="AI Prompt">
            ✨
          </span>
          <span style={s({ fontWeight: 600, fontSize: "14px", color: "var(--qb-text-primary, #1e293b)" })}>
            Natural Language Query
          </span>
        </div>

        <div style={s({ display: "flex", alignItems: "center", gap: "8px" })}>
          <label style={s({ fontSize: "12px", color: "var(--qb-text-secondary, #64748b)", display: "flex", alignItems: "center", gap: "4px" })}>
            <input
              type="checkbox"
              checked={autoApply}
              onChange={(e) => setAutoApply(e.target.checked)}
              aria-label="Auto-apply to canvas"
            />
            Auto-apply
          </label>

          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value as NlqProviderName)}
            style={s({
              fontSize: "12px",
              padding: "4px 8px",
              borderRadius: "4px",
              border: "1px solid var(--qb-border-color, #cbd5e1)",
              backgroundColor: "var(--qb-bg-secondary, #f8fafc)",
              color: "var(--qb-text-primary, #334155)",
            })}
            aria-label="NLQ Provider"
          >
            <option value="mock">Hermetic / Mock</option>
            <option value="gemini">Google Gemini</option>
            <option value="openai">OpenAI GPT-4o</option>
            <option value="anthropic">Anthropic Claude</option>
            <option value="ollama">Ollama (Local LLM)</option>
            <option value="custom">Custom</option>
          </select>
        </div>
      </div>

      {/* Input Row */}
      <div style={s({ display: "flex", gap: "8px", alignItems: "center" })}>
        <input
          type="text"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isLoading || isExplaining}
          style={s({
            flex: 1,
            padding: "8px 12px",
            fontSize: "13px",
            borderRadius: "6px",
            border: "1px solid var(--qb-border-color, #cbd5e1)",
            outline: "none",
          })}
          aria-label="NLQ Input"
        />

        <button
          type="button"
          onClick={() => void translatePrompt()}
          disabled={isLoading || isExplaining || !prompt.trim()}
          style={s({
            padding: "8px 16px",
            fontSize: "13px",
            fontWeight: 500,
            borderRadius: "6px",
            border: "none",
            backgroundColor: "var(--qb-accent-color, #3b82f6)",
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
              padding: "8px 12px",
              fontSize: "13px",
              borderRadius: "6px",
              border: "1px solid var(--qb-border-color, #cbd5e1)",
              backgroundColor: "var(--qb-bg-secondary, #f8fafc)",
              color: "var(--qb-text-primary, #334155)",
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
              padding: "8px 12px",
              fontSize: "13px",
              borderRadius: "6px",
              border: "1px solid var(--qb-border-color, #cbd5e1)",
              backgroundColor: "var(--qb-bg-secondary, #f8fafc)",
              color: "var(--qb-text-primary, #334155)",
              cursor: "pointer",
            })}
            aria-label="Undo Translation Button"
          >
            Undo
          </button>
        )}
      </div>

      {/* Schema Pills */}
      {showSchemaPills && schemaTableNames.length > 0 && (
        <div style={s({ display: "flex", alignItems: "center", gap: "6px", marginTop: "8px", flexWrap: "wrap" })}>
          <span style={s({ fontSize: "11px", color: "var(--qb-text-secondary, #64748b)" })}>Tables:</span>
          {schemaTableNames.map((tbl) => (
            <button
              key={tbl}
              type="button"
              onClick={() => setPrompt((prev) => (prev ? `${prev} from ${tbl}` : `Query ${tbl}`))}
              style={s({
                fontSize: "11px",
                padding: "2px 8px",
                borderRadius: "12px",
                border: "1px solid var(--qb-border-color, #e2e8f0)",
                backgroundColor: "var(--qb-bg-secondary, #f1f5f9)",
                color: "var(--qb-text-primary, #475569)",
                cursor: "pointer",
              })}
              aria-label={`Insert table ${tbl}`}
            >
              {tbl}
            </button>
          ))}
        </div>
      )}

      {/* Suggestion Pills */}
      {showSuggestions && (
        <div style={s({ display: "flex", alignItems: "center", gap: "6px", marginTop: "6px", flexWrap: "wrap" })}>
          <span style={s({ fontSize: "11px", color: "var(--qb-text-secondary, #64748b)" })}>Suggestions:</span>
          {DEFAULT_SUGGESTIONS.map((sug, i) => (
            <button
              key={i}
              type="button"
              onClick={() => {
                setPrompt(sug);
                void translatePrompt(sug);
              }}
              style={s({
                fontSize: "11px",
                padding: "2px 8px",
                borderRadius: "12px",
                border: "1px dashed var(--qb-border-color, #cbd5e1)",
                backgroundColor: "transparent",
                color: "var(--qb-accent-color, #2563eb)",
                cursor: "pointer",
              })}
              aria-label={`Suggestion: ${sug}`}
            >
              {sug}
            </button>
          ))}
        </div>
      )}

      {/* Error Message Callout */}
      {error && (
        <div
          style={s({
            marginTop: "8px",
            padding: "8px 12px",
            borderRadius: "6px",
            backgroundColor: "#fef2f2",
            border: "1px solid #fecaca",
            color: "#991b1b",
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
            style={s({ background: "none", border: "none", color: "#991b1b", cursor: "pointer", fontWeight: "bold" })}
            aria-label="Dismiss Error"
          >
            ×
          </button>
        </div>
      )}

      {/* Explanation & Confidence Callout */}
      {explanation && !error && (
        <div
          style={s({
            marginTop: "8px",
            padding: "10px 12px",
            borderRadius: "6px",
            backgroundColor: "#f0fdf4",
            border: "1px solid #bbf7d0",
            color: "#166534",
            fontSize: "12px",
          })}
          data-testid="nlq-explanation-box"
        >
          <div style={s({ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" })}>
            <span style={s({ fontWeight: 600 })}>Query Analysis</span>
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
          </div>
          <div>{explanation}</div>
          {explanationSteps.length > 0 && (
            <ol style={s({ margin: "6px 0 0 16px", padding: 0 })}>
              {explanationSteps.map((step, idx) => (
                <li key={idx} style={s({ marginBottom: "2px" })}>
                  {step}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
};
