/**
 * Headless Hook for Bring Your Own AI (BYO-AI) in React.
 */

import { useState, useCallback, useRef } from "react";
import type { ByoAiConfig, ByoAiContext, ByoAiMessage, ByoAiResponse } from "../ai/types";
import type { QuerySpec } from "../types";
import { autoHealClientQuerySpec } from "../ai/selfHealing";
import { parseSqlToSpec } from "../utils/sqlParser";
import { compileSpecToSql } from "../utils/compiler";

export interface UseBringYourOwnAiOptions extends ByoAiConfig {
  schema?: any;
  currentSpec?: QuerySpec | null;
  onApplySpec?: (spec: QuerySpec) => void;
}

export interface UseBringYourOwnAiResult {
  messages: ByoAiMessage[];
  isGenerating: boolean;
  error: string | null;
  latestSpec: QuerySpec | null;
  latestSql: string | null;
  sendMessage: (prompt: string) => Promise<ByoAiResponse | null>;
  applySpec: (specToApply?: QuerySpec) => void;
  clearMessages: () => void;
  undoLast: () => void;
}

export function useBringYourOwnAi(options: UseBringYourOwnAiOptions = {}): UseBringYourOwnAiResult {
  const {
    handler,
    apiUrl = "/api/v1/nlq/translate",
    dialect = "postgres",
    autoApply = false,
    autoHeal = true,
    schema,
    currentSpec,
    onApplySpec,
    onSpecGenerated,
    onError,
  } = options;

  const [messages, setMessages] = useState<ByoAiMessage[]>([]);
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [latestSpec, setLatestSpec] = useState<QuerySpec | null>(null);
  const [latestSql, setLatestSql] = useState<string | null>(null);

  const historyRef = useRef<ByoAiMessage[]>([]);
  historyRef.current = messages;

  const sendMessage = useCallback(
    async (promptText: string): Promise<ByoAiResponse | null> => {
      const trimmed = promptText.trim();
      if (!trimmed) {
        setError("Prompt cannot be empty.");
        return null;
      }

      setError(null);
      setIsGenerating(true);

      const userMsg: ByoAiMessage = {
        id: `msg_user_${Date.now()}`,
        role: "user",
        content: trimmed,
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, userMsg]);

      const context: ByoAiContext = {
        prompt: trimmed,
        schema,
        currentSpec,
        dialect,
        history: historyRef.current,
      };

      try {
        let rawResponse: any;

        // 1. Dispatch to Host App's Handler
        if (handler) {
          if (typeof handler === "function") {
            rawResponse = await handler(context);
          } else if (typeof handler.generate === "function") {
            rawResponse = await handler.generate(context);
          } else if (typeof handler.generateQuery === "function") {
            rawResponse = await handler.generateQuery(context);
          } else if (typeof handler.ask === "function") {
            rawResponse = await handler.ask(trimmed, context);
          } else {
            throw new Error("Invalid BYO-AI handler format. Must be a function or client object with .generate() or .ask().");
          }
        } else {
          // 2. Fallback to API endpoint
          const res = await fetch(apiUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: trimmed,
              schema,
              dialect,
            }),
          });
          if (!res.ok) {
            throw new Error(`AI API returned error HTTP ${res.status}`);
          }
          rawResponse = await res.json();
        }

        // 3. Normalize into ByoAiResponse & QuerySpec
        let extractedSpec: Partial<QuerySpec> | null = null;
        let explanationText = `Generated query for "${trimmed}".`;
        let confidenceScore = 0.95;

        if (typeof rawResponse === "string") {
          // Check if raw SQL
          if (/^SELECT\b|^WITH\b/i.test(rawResponse.trim())) {
            extractedSpec = parseSqlToSpec(rawResponse.trim());
          } else {
            try {
              const parsedJson = JSON.parse(rawResponse);
              if (parsedJson && parsedJson.table) {
                extractedSpec = parsedJson;
              } else if (parsedJson && parsedJson.spec) {
                extractedSpec = parsedJson.spec;
                if (parsedJson.explanation) explanationText = parsedJson.explanation;
              }
            } catch {
              explanationText = rawResponse;
            }
          }
        } else if (rawResponse && typeof rawResponse === "object") {
          if (rawResponse.spec) {
            extractedSpec = rawResponse.spec;
            if (rawResponse.explanation) explanationText = rawResponse.explanation;
            if (typeof rawResponse.confidence === "number") confidenceScore = rawResponse.confidence;
          } else if (rawResponse.table) {
            extractedSpec = rawResponse;
          }
        }

        let healingNotes: string[] = [];
        let finalSpec: QuerySpec | null = null;
        let finalSql = "";

        if (extractedSpec) {
          if (autoHeal) {
            const healed = autoHealClientQuerySpec(extractedSpec, schema);
            finalSpec = healed.healedSpec;
            healingNotes = healed.notes;
          } else {
            finalSpec = extractedSpec as QuerySpec;
          }

          finalSql = compileSpecToSql(finalSpec, dialect as any);
        }

        const assistantMsg: ByoAiMessage = {
          id: `msg_ai_${Date.now()}`,
          role: "assistant",
          content: explanationText,
          spec: finalSpec || undefined,
          sql: finalSql || undefined,
          timestamp: Date.now(),
          healingNotes: healingNotes.length > 0 ? healingNotes : undefined,
          confidence: confidenceScore,
        };

        setMessages((prev) => [...prev, assistantMsg]);
        if (finalSpec) {
          setLatestSpec(finalSpec);
          setLatestSql(finalSql);
          if (onSpecGenerated) onSpecGenerated(finalSpec, finalSql);
          if (autoApply && onApplySpec) onApplySpec(finalSpec);
        }

        setIsGenerating(false);

        return {
          spec: finalSpec || undefined,
          sql: finalSql || undefined,
          explanation: explanationText,
          confidence: confidenceScore,
          warnings: healingNotes,
        };
      } catch (err: any) {
        const errMsg = err?.message || String(err);
        setError(errMsg);
        setIsGenerating(false);
        if (onError) onError(err);
        return null;
      }
    },
    [handler, apiUrl, dialect, autoApply, autoHeal, schema, currentSpec, onApplySpec, onSpecGenerated, onError]
  );

  const applySpec = useCallback(
    (specToApply?: QuerySpec) => {
      const target = specToApply || latestSpec;
      if (target && onApplySpec) {
        onApplySpec(target);
      }
    },
    [latestSpec, onApplySpec]
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    setLatestSpec(null);
    setLatestSql(null);
  }, []);

  const undoLast = useCallback(() => {
    setMessages((prev) => prev.slice(0, Math.max(0, prev.length - 2)));
  }, []);

  return {
    messages,
    isGenerating,
    error,
    latestSpec,
    latestSql,
    sendMessage,
    applySpec,
    clearMessages,
    undoLast,
  };
}
