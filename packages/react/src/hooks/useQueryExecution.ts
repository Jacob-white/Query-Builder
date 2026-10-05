import { useState, useRef, useCallback, useEffect } from "react";
import type { QueryResultData } from "../types";
import { useQueryBuilderContext } from "../theme/QueryBuilderProvider";

export interface UseQueryExecutionOptions {
  onExecuteQuery?: (sql: string, spec?: Record<string, unknown>) => Promise<QueryResultData> | void;
  apiEndpoint?: string;
  defaultTimeoutMs?: number;
  initialResults?: QueryResultData | null;
  onError?: (error: Error) => void;
  onSuccess?: (results: QueryResultData) => void;
}

export interface UseQueryExecutionReturn {
  results: QueryResultData | null;
  isLoading: boolean;
  error: string | null;
  latencyMs: number | null;
  executeQuery: (sql: string, spec?: Record<string, unknown>) => Promise<QueryResultData | null>;
  cancelExecution: () => void;
  clearResults: () => void;
  setResults: (data: QueryResultData | null) => void;
}

export function useQueryExecution(
  options: UseQueryExecutionOptions = {},
): UseQueryExecutionReturn {
  const qbContext = useQueryBuilderContext();
  const {
    onExecuteQuery: propExecuteQuery,
    apiEndpoint,
    defaultTimeoutMs,
    initialResults = null,
    onError,
    onSuccess,
  } = options;

  const onExecuteQuery = propExecuteQuery ?? qbContext?.onExecuteQuery;

  const [results, setResults] = useState<QueryResultData | null>(initialResults);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const cancelExecution = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsLoading(false);
  }, []);

  const clearResults = useCallback(() => {
    setResults(null);
    setError(null);
    setLatencyMs(null);
  }, []);

  const executeQuery = useCallback(
    async (sql: string, spec?: Record<string, unknown>): Promise<QueryResultData | null> => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const controller = new AbortController();
      abortControllerRef.current = controller;

      setIsLoading(true);
      setError(null);
      const start = typeof performance !== "undefined" ? performance.now() : Date.now();

      let timeoutId: ReturnType<typeof setTimeout> | undefined;
      if (defaultTimeoutMs && defaultTimeoutMs > 0) {
        timeoutId = setTimeout(() => {
          controller.abort();
        }, defaultTimeoutMs);
      }

      try {
        let resData: QueryResultData | null = null;

        if (onExecuteQuery) {
          const customRes = await onExecuteQuery(sql, spec);
          if (customRes) {
            resData = customRes;
          }
        } else if (apiEndpoint) {
          const resp = await fetch(apiEndpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sql, spec }),
            signal: controller.signal,
          });

          if (!resp.ok) {
            throw new Error(`HTTP error ${resp.status}`);
          }

          const parsed = await resp.json();
          if (parsed && typeof parsed === "object") {
            if ("data" in parsed && parsed.data && typeof parsed.data === "object") {
              resData = parsed.data as QueryResultData;
            } else {
              resData = parsed as QueryResultData;
            }
          }
        }

        clearTimeout(timeoutId);
        const now = typeof performance !== "undefined" ? performance.now() : Date.now();
        const elapsed = Math.round(now - start);

        if (resData) {
          const finalResult: QueryResultData = {
            ...resData,
            latency_ms: resData.latency_ms ?? elapsed,
          };
          setResults(finalResult);
          setLatencyMs(elapsed);
          setIsLoading(false);
          onSuccess?.(finalResult);
          return finalResult;
        }

        setIsLoading(false);
        return null;
      } catch (err: unknown) {
        clearTimeout(timeoutId);
        if ((err as Error)?.name === "AbortError") {
          setIsLoading(false);
          return null;
        }

        const errorObj = err instanceof Error ? err : new Error(String(err));
        setError(errorObj.message);
        setIsLoading(false);
        onError?.(errorObj);
        return null;
      }
    },
    [onExecuteQuery, apiEndpoint, defaultTimeoutMs, onError, onSuccess],
  );

  return {
    results,
    isLoading,
    error,
    latencyMs,
    executeQuery,
    cancelExecution,
    clearResults,
    setResults,
  };
}
