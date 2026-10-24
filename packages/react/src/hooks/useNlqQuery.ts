import { useState, useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { QuerySpec } from "../types";
import type { ByoAiSchema } from "../ai/types";

type NlqSchema = ByoAiSchema;

interface NlqErrorBody {
  error?: { message?: string };
  detail?: string;
}

function buildNlqSubEndpoint(baseApiUrl: string, subPath: "translate" | "explain"): string {
  const qIndex = baseApiUrl.indexOf("?");
  if (qIndex === -1) {
    return `${baseApiUrl.replace(/\/$/, "")}/${subPath}`;
  }
  const pathPart = baseApiUrl.slice(0, qIndex).replace(/\/$/, "");
  const queryPart = baseApiUrl.slice(qIndex);
  return `${pathPart}/${subPath}${queryPart}`;
}

interface NlqTranslateResponse {
  spec: QuerySpec;
  confidence?: number;
  explanation?: string;
  steps?: string[];
  follow_ups?: string[];
}

interface NlqExplainResponse {
  explanation?: string;
  summary?: string;
  steps?: string[];
}

export type NlqProviderName =
  | "mock"
  | "gemini"
  | "openai"
  | "anthropic"
  | "ollama"
  | "custom";

export interface NlqConversationTurn {
  id: string;
  prompt: string;
  spec: QuerySpec;
  explanation: string;
  steps: string[];
  confidence: number;
  followUps: string[];
  timestamp: number;
}

export interface UseNlqQueryOptions {
  schema?: NlqSchema;
  currentSpec?: QuerySpec;
  defaultProvider?: NlqProviderName;
  apiUrl?: string;
  dialect?: string;
  autoApply?: boolean;
  onApply?: (spec: QuerySpec) => void;
  customTranslator?: (
    prompt: string,
    schema?: NlqSchema,
    dialect?: string
  ) => Promise<QuerySpec>;
}

export interface UseNlqQueryResult {
  prompt: string;
  setPrompt: Dispatch<SetStateAction<string>>;
  isLoading: boolean;
  isExplaining: boolean;
  error: string | null;
  confidence: number | null;
  explanation: string | null;
  explanationSteps: string[];
  followUps: string[];
  turns: NlqConversationTurn[];
  provider: NlqProviderName;
  setProvider: (p: NlqProviderName) => void;
  history: string[];
  canUndo: boolean;
  translatePrompt: (overridePrompt?: string) => Promise<QuerySpec | null>;
  explainQuery: (specToExplain?: QuerySpec) => Promise<string | null>;
  undoLastTranslation: () => QuerySpec | null;
  restoreTurn: (turnIndex: number) => QuerySpec | null;
  clearState: () => void;
}

function buildDefaultFollowUps(spec?: QuerySpec): string[] {
  if (!spec || !spec.table) return [];
  const suggestions: string[] = [];
  if (!spec.limit || spec.limit > 25) {
    suggestions.push("Limit to top 10 rows");
  }
  if (!spec.order_by || spec.order_by.length === 0) {
    const firstCol = spec.columns?.[0] && spec.columns[0] !== "*" ? spec.columns[0] : "id";
    suggestions.push(`Sort by ${firstCol} descending`);
  }
  if (!spec.filters || spec.filters.length === 0) {
    suggestions.push(`Filter ${spec.table} where status is active`);
  } else {
    suggestions.push("Remove filters and show all rows");
  }
  return suggestions.slice(0, 3);
}

export function useNlqQuery(options: UseNlqQueryOptions = {}): UseNlqQueryResult {
  const {
    schema,
    currentSpec,
    defaultProvider = "mock",
    apiUrl = "/api/v1/nlq",
    dialect = "postgres",
    autoApply = true,
    onApply,
    customTranslator,
  } = options;

  const [prompt, setPrompt] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isExplaining, setIsExplaining] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [explanation, setExplanation] = useState<string | null>(null);
  const [explanationSteps, setExplanationSteps] = useState<string[]>([]);
  const [followUps, setFollowUps] = useState<string[]>([]);
  const [turns, setTurns] = useState<NlqConversationTurn[]>([]);
  const [provider, setProvider] = useState<NlqProviderName>(defaultProvider);
  const [history, setHistory] = useState<string[]>([]);
  const [canUndo, setCanUndo] = useState<boolean>(false);

  useEffect(() => {
    setProvider(defaultProvider);
  }, [defaultProvider]);

  const previousSpecsRef = useRef<QuerySpec[]>([]);
  const turnsRef = useRef<NlqConversationTurn[]>([]);

  const translatePrompt = useCallback(
    async (overridePrompt?: string): Promise<QuerySpec | null> => {
      const activePrompt = (overridePrompt ?? prompt).trim();
      if (!activePrompt) {
        setError("Prompt cannot be empty.");
        return null;
      }

      setIsLoading(true);
      setError(null);

      try {
        let generatedSpec: QuerySpec;
        let generatedConfidence = 0.95;
        let generatedExplanation = `Translated: "${activePrompt}"`;
        let generatedSteps: string[] = [];
        let generatedFollowUps: string[] = [];

        const latestTurnSpec =
          turnsRef.current.length > 0
            ? turnsRef.current[turnsRef.current.length - 1].spec
            : undefined;
        const activeContextSpec =
          latestTurnSpec ?? (currentSpec && currentSpec.table ? currentSpec : undefined);

        if (provider === "custom" && customTranslator) {
          generatedSpec = await customTranslator(activePrompt, schema, dialect);
          generatedConfidence = 1.0;
        } else {
          const endpoint = buildNlqSubEndpoint(apiUrl, "translate");
          const payload: Record<string, unknown> = {
            prompt: activePrompt,
            schema,
            provider,
            dialect,
          };
          if (activeContextSpec) {
            payload.current_spec = activeContextSpec;
          }
          if (turnsRef.current.length > 0) {
            payload.history = turnsRef.current.map((t) => ({
              prompt: t.prompt,
              spec: t.spec,
              explanation: t.explanation,
            }));
          }

          const resp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });

          if (!resp.ok) {
            const errData: NlqErrorBody = await resp.json().catch(() => ({}));
            const msg =
              (errData && errData.error && errData.error.message) ||
              (errData && errData.detail) ||
              `Translation request failed (${resp.status})`;
            throw new Error(msg);
          }

          const data: NlqTranslateResponse = await resp.json();
          generatedSpec = data.spec;
          generatedConfidence = typeof data.confidence === "number" ? data.confidence : 0.9;
          generatedExplanation = data.explanation || "";
          generatedSteps = Array.isArray(data.steps) ? data.steps : [];
          generatedFollowUps = Array.isArray(data.follow_ups) && data.follow_ups.length > 0
            ? data.follow_ups
            : buildDefaultFollowUps(generatedSpec);
        }

        const newTurn: NlqConversationTurn = {
          id: `turn-${Date.now()}-${turnsRef.current.length + 1}`,
          prompt: activePrompt,
          spec: generatedSpec,
          explanation: generatedExplanation,
          steps: generatedSteps,
          confidence: generatedConfidence,
          followUps: generatedFollowUps,
          timestamp: Date.now(),
        };

        turnsRef.current = [...turnsRef.current, newTurn].slice(-12);
        setTurns(turnsRef.current);
        setConfidence(generatedConfidence);
        setExplanation(generatedExplanation);
        setExplanationSteps(generatedSteps);
        setFollowUps(generatedFollowUps);
        setHistory((prev) => [activePrompt, ...prev.filter((p) => p !== activePrompt)].slice(0, 20));

        previousSpecsRef.current.push(generatedSpec);
        setCanUndo(previousSpecsRef.current.length > 1);

        if (autoApply && onApply) {
          onApply(generatedSpec);
        }

        setIsLoading(false);
        return generatedSpec;
      } catch (err) {
        const errorMsg =
          err instanceof Error
            ? err.message
            : "Failed to translate natural language prompt.";
        setError(errorMsg);
        setIsLoading(false);
        return null;
      }
    },
    [prompt, provider, customTranslator, apiUrl, schema, currentSpec, dialect, autoApply, onApply]
  );

  const explainQuery = useCallback(
    async (specToExplain?: QuerySpec): Promise<string | null> => {
      if (!specToExplain) {
        setError("No query specification provided to explain.");
        return null;
      }

      setIsExplaining(true);
      setError(null);

      try {
        const endpoint = buildNlqSubEndpoint(apiUrl, "explain");
        const resp = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: specToExplain,
            dialect,
            provider,
          }),
        });

        if (!resp.ok) {
          const errData: NlqErrorBody = await resp.json().catch(() => ({}));
          const msg =
            (errData && errData.error && errData.error.message) ||
            (errData && errData.detail) ||
            `Explain request failed (${resp.status})`;
          throw new Error(msg);
        }

        const data: NlqExplainResponse = await resp.json();
        const explText = data.explanation || data.summary || "Explanation generated.";
        const steps = Array.isArray(data.steps) ? data.steps : [];

        setExplanation(explText);
        setExplanationSteps(steps);
        setIsExplaining(false);
        return explText;
      } catch (err) {
        const errorMsg =
          err instanceof Error ? err.message : "Failed to explain query.";
        setError(errorMsg);
        setIsExplaining(false);
        return null;
      }
    },
    [apiUrl, dialect, provider]
  );

  const undoLastTranslation = useCallback((): QuerySpec | null => {
    if (previousSpecsRef.current.length <= 1) {
      setCanUndo(false);
      return null;
    }
    previousSpecsRef.current.pop(); // Remove current
    if (turnsRef.current.length > 0) {
      turnsRef.current = turnsRef.current.slice(0, -1);
      setTurns(turnsRef.current);
      const prevTurn = turnsRef.current[turnsRef.current.length - 1];
      if (prevTurn) {
        setConfidence(prevTurn.confidence);
        setExplanation(prevTurn.explanation);
        setExplanationSteps(prevTurn.steps);
        setFollowUps(prevTurn.followUps);
      }
    }
    setCanUndo(previousSpecsRef.current.length > 1);
    const previous = previousSpecsRef.current[previousSpecsRef.current.length - 1];
    if (previous && onApply) {
      onApply(previous);
    }
    return previous;
  }, [onApply]);

  const restoreTurn = useCallback(
    (turnIndex: number): QuerySpec | null => {
      const target = turnsRef.current[turnIndex];
      if (!target) return null;
      turnsRef.current = turnsRef.current.slice(0, turnIndex + 1);
      setTurns(turnsRef.current);
      previousSpecsRef.current = turnsRef.current.map((t) => t.spec);
      setCanUndo(previousSpecsRef.current.length > 1);
      setConfidence(target.confidence);
      setExplanation(target.explanation);
      setExplanationSteps(target.steps);
      setFollowUps(target.followUps);
      if (autoApply && onApply) {
        onApply(target.spec);
      }
      return target.spec;
    },
    [autoApply, onApply]
  );

  const clearState = useCallback(() => {
    setPrompt("");
    setError(null);
    setConfidence(null);
    setExplanation(null);
    setExplanationSteps([]);
    setFollowUps([]);
    turnsRef.current = [];
    setTurns([]);
    previousSpecsRef.current = [];
    setCanUndo(false);
  }, []);

  return {
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
  };
}
