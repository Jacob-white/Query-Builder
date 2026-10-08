import { useState, useCallback, useRef, type Dispatch, type SetStateAction } from "react";
import type { QuerySpec } from "../types";
import type { ByoAiSchema } from "../ai/types";

type NlqSchema = ByoAiSchema;

interface NlqErrorBody {
  error?: { message?: string };
}

interface NlqTranslateResponse {
  spec: QuerySpec;
  confidence?: number;
  explanation?: string;
  steps?: string[];
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

export interface UseNlqQueryOptions {
  schema?: NlqSchema;
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
  provider: NlqProviderName;
  setProvider: (p: NlqProviderName) => void;
  history: string[];
  canUndo: boolean;
  translatePrompt: (overridePrompt?: string) => Promise<QuerySpec | null>;
  explainQuery: (specToExplain?: QuerySpec) => Promise<string | null>;
  undoLastTranslation: () => QuerySpec | null;
  clearState: () => void;
}

export function useNlqQuery(options: UseNlqQueryOptions = {}): UseNlqQueryResult {
  const {
    schema,
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
  const [provider, setProvider] = useState<NlqProviderName>(defaultProvider);
  const [history, setHistory] = useState<string[]>([]);
  const [canUndo, setCanUndo] = useState<boolean>(false);

  const previousSpecsRef = useRef<QuerySpec[]>([]);

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

        if (provider === "custom" && customTranslator) {
          generatedSpec = await customTranslator(activePrompt, schema, dialect);
          generatedConfidence = 1.0;
        } else {
          const endpoint = `${apiUrl.replace(/\/$/, "")}/translate`;
          const resp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: activePrompt,
              schema,
              provider,
              dialect,
            }),
          });

          if (!resp.ok) {
            const errData: NlqErrorBody = await resp.json().catch(() => ({}));
            const msg =
              (errData && errData.error && errData.error.message) ||
              `Translation request failed (${resp.status})`;
            throw new Error(msg);
          }

          const data: NlqTranslateResponse = await resp.json();
          generatedSpec = data.spec;
          generatedConfidence = typeof data.confidence === "number" ? data.confidence : 0.9;
          generatedExplanation = data.explanation || "";
          generatedSteps = Array.isArray(data.steps) ? data.steps : [];
        }

        setConfidence(generatedConfidence);
        setExplanation(generatedExplanation);
        setExplanationSteps(generatedSteps);
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
    [prompt, provider, customTranslator, apiUrl, schema, dialect, autoApply, onApply]
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
        const endpoint = `${apiUrl.replace(/\/$/, "")}/explain`;
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
    setCanUndo(previousSpecsRef.current.length > 1);
    const previous = previousSpecsRef.current[previousSpecsRef.current.length - 1];
    if (previous && onApply) {
      onApply(previous);
    }
    return previous;
  }, [onApply]);

  const clearState = useCallback(() => {
    setPrompt("");
    setError(null);
    setConfidence(null);
    setExplanation(null);
    setExplanationSteps([]);
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
    provider,
    setProvider,
    history,
    canUndo,
    translatePrompt,
    explainQuery,
    undoLastTranslation,
    clearState,
  };
}
